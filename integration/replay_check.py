"""Public replay acceptance check: every saved Stage C state through the integration code (PolicyReplay.exe,
which links the solver's own FvsPolicy/FvsHooks/Graph objects) versus an independent Python reference.

Reference, per state (nothing is shared with the C++ code):
  * snapshot slice of the Stage C record, decoded by the pinned stagec/snapshot.py (learnability.decode)
  * candidates / order / original pivot: the archived candidate bytes, the extraction table (ordinal order,
    is_original_pivot) and the snapshot's recorded pivot
  * features: learnability.features.compute_features on the decoded snapshot AND the extraction table values
  * linear scores: the frozen export through learnability.train.transforms.LinearTransform (numpy, the trained
    scorer `transform(X) @ theta`), plus an exact left-to-right replica of the documented live summation order
  * boost scores: xgboost 2.1.3 Booster.load_model(frozen model.json).predict(DMatrix(X), output_margin=True)
  * selection: learnability.train.evaluate.select (argmax; exact ties -> original if among maxima, else earliest)
Discrete values are compared exactly. Numerical tolerances are reported, and the selected pivot must agree
exactly with the reference selection computed from the reference scores.

Usage: python integration/replay_check.py --build BUILD --extraction DIR --stagec-records DIR --out DIR
"""
import argparse, collections, csv, gzip, hashlib, json, math, pathlib, subprocess, sys, time, zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from learnability.decode import load_pinned_decoder, decode_checked  # noqa: E402
from learnability.features import compute_features, FEATURE_COLUMNS  # noqa: E402

SOLVERS = ('8', '5', 'LP')
EXPECTED = dict(states=6502, candidates=71038, by_solver={'8': (1983, 12684), '5': (2212, 43773), 'LP': (2307, 14581)})
LINEAR_ABS_TOL = 1e-9   # documented tolerance between live (sequential) and numpy (BLAS) linear scores


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load_candidates(extraction, solver):
    rows = collections.OrderedDict()
    with gzip.open(extraction / f'candidates_{solver}.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            rows.setdefault(r['state_id'], []).append(r)
    for sid, rs in rows.items():
        rs.sort(key=lambda r: int(r['candidate_ordinal']))
    return rows


def reference_scores(solver, models, X):
    import numpy as np
    import xgboost as xgb
    from learnability.train import transforms as T
    lin = models['linear']; tr = T.LinearTransform.from_export(lin['transform']); theta = np.array(lin['theta'], dtype=np.float64)
    cols = lin['transform']['input_order']
    Xl = np.array([[row[c] for c in cols] for row in X], dtype=np.float64)
    Phi = tr.transform(Xl)
    numpy_scores = Phi @ theta
    seq = []
    for i in range(len(Phi)):
        s = 0.0
        for j in range(len(theta)):
            s += float(theta[j]) * float(Phi[i, j])
        seq.append(s)
    bcols = models['boost_meta']['input_order']
    Xb = np.array([[row[c] for c in bcols] for row in X], dtype=np.float64)
    boost = models['booster'].predict(xgb.DMatrix(Xb), output_margin=True).astype(np.float64)
    return [float(x) for x in numpy_scores], seq, [float(x) for x in boost]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True); ap.add_argument('--extraction', required=True)
    ap.add_argument('--stagec-records', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=0, help='testing only: first N states per solver')
    a = ap.parse_args()
    import xgboost as xgb
    from learnability.train.evaluate import select
    build = pathlib.Path(a.build); ext = pathlib.Path(a.extraction); rec = pathlib.Path(a.stagec_records); out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    decode, decoder_sha = load_pinned_decoder(ROOT / 'stagec/snapshot.py')
    t0 = time.time()
    report = dict(check='replay_acceptance', expected=EXPECTED, decoder_sha256=decoder_sha, linear_abs_tolerance=LINEAR_ABS_TOL, solvers={})
    binaries = {}
    allok = True
    for solver in SOLVERS:
        rows = load_candidates(ext, solver)
        items = list(rows.items())[: a.limit] if a.limit else list(rows.items())
        tsv = []
        for sid, rs in items:
            r0 = rs[0]
            src = rec / pathlib.Path(r0['snapshot_source_path']).parent / 'samples.bin.zz'
            if src not in binaries:
                raw = zlib.decompress(src.read_bytes()); p = out / 'bins' / (sha(str(src).encode())[:16] + '.bin')
                p.parent.mkdir(exist_ok=True); p.write_bytes(raw); binaries[src] = (p, raw)
            p, raw = binaries[src]
            tsv.append('\t'.join([sid, str(p), r0['sample_offset'], r0['snapshot_bytes'], r0['candidates_offset'], str(len(rs))]))
        (out / f'replay_{solver}.tsv').write_text('\n'.join(tsv) + '\n', encoding='utf-8')
        md = build / 'models' / solver
        cmd = [str(build / 'tools/PolicyReplay.exe'), solver, str(md / 'linear/model.json'), str(md / 'boost/model.json'), str(md / 'boost/model_meta.json')]
        with open(out / f'replay_{solver}.tsv', 'rb') as fi, open(out / f'native_{solver}.jsonl', 'wb') as fo:
            pr = subprocess.run(cmd, stdin=fi, stdout=fo, stderr=subprocess.PIPE)
        (out / f'native_{solver}.stderr.txt').write_bytes(pr.stderr)
        native = [json.loads(l) for l in (out / f'native_{solver}.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
        header, native = native[0], {n['state_id']: n for n in native[1:]}
        models = dict(linear=json.loads((md / 'linear/model.json').read_text()), boost_meta=json.loads((md / 'boost/model_meta.json').read_text()))
        bst = xgb.Booster(); bst.load_model(str(md / 'boost/model.json')); models['booster'] = bst
        c = collections.Counter(); mism = collections.defaultdict(list); maxdiff = dict(linear_sequential=0.0, boost=0.0, linear_numpy_batched=0.0)
        tie_states = collections.Counter()
        for sid, rs in items:
            n = native.get(sid); c['states'] += 1; c['candidates'] += len(rs)
            def bad(kind, detail=None):
                c['mismatch:' + kind] += 1
                if len(mism[kind]) < 20: mism[kind].append(dict(state_id=sid, detail=detail))
            if n is None or n.get('error'):
                bad('native_error', n and n.get('error')); continue
            r0 = rs[0]
            p, raw = binaries[rec / pathlib.Path(r0['snapshot_source_path']).parent / 'samples.bin.zz']
            blob = raw[int(r0['sample_offset']): int(r0['sample_offset']) + int(r0['snapshot_bytes'])]
            if sha(blob) != r0['snapshot_sha256']: bad('snapshot_sha256')
            dec = decode_checked(decode, blob, solver)
            cands = [int(r['candidate_local_id']) for r in rs]
            archived = list(int.from_bytes(raw[int(r0['candidates_offset']) + 4 * i: int(r0['candidates_offset']) + 4 * i + 4], 'little', signed=True) for i in range(len(rs)))
            orig_table = [int(r['candidate_local_id']) for r in rs if r['is_original_pivot'] == 'true']
            if n['candidates'] != cands: bad('candidates_vs_table', dict(native=n['candidates'][:10], table=cands[:10]))
            if n['candidates'] != archived or not n['archived_candidates_match']: bad('candidates_vs_archived')
            if n['original'] != dec['pivot'] or n['recorded_pivot'] != dec['pivot']: bad('original_vs_snapshot', dict(native=n['original'], snapshot=dec['pivot']))
            if orig_table != [dec['pivot']]: bad('original_vs_table')
            root = dec['root'] if solver == 'LP' else None
            if solver == 'LP' and n['root'] != dec['root']: bad('root')
            _, feats, _ = compute_features(solver, dec['status'], dec['neighbours'], dec['neighDouble'], dec['size_cap'], len(dec['X']), cands, root)
            nf = n['features']; F = len(FEATURE_COLUMNS)
            if len(nf) != F * len(cands): bad('feature_shape'); continue
            X = []
            for i, (fr, tr) in enumerate(zip(feats, rs)):
                row = {}
                for j, col in enumerate(FEATURE_COLUMNS):
                    v = nf[i * F + j]
                    if col == 'f_lp_root_common_neighbors' and solver != 'LP':
                        continue
                    ref = float(fr[col]); tab = float(tr[col])
                    if v != ref: bad('feature_vs_python:' + col, dict(candidate=cands[i], native=v, python=ref))
                    if v != tab: bad('feature_vs_table:' + col, dict(candidate=cands[i], native=v, table=tab))
                    row[col] = ref
                X.append(row)
            ln, ls, bs = reference_scores(solver, models, X)
            orig_pos = cands.index(dec['pivot'])
            # Reference scores: boost = xgboost library margins (must be bit-identical); linear = the frozen
            # export evaluated per candidate (numpy transform, left-to-right sum; must be bit-identical),
            # with the batched numpy matmul `transform(X) @ theta` held to LINEAR_ABS_TOL.
            for fam, ref_scores, nat in (('linear', ls, n['linear']), ('boost', bs, n['boost'])):
                if not nat['scored']: bad(fam + '_not_scored'); continue
                d = max(abs(x - y) for x, y in zip(nat['scores'], ref_scores))
                key = 'linear_sequential' if fam == 'linear' else 'boost'
                maxdiff[key] = max(maxdiff[key], d)
                if d != 0.0: bad(fam + '_score_not_exact', dict(max_abs_diff=d))
                ref_pos, ref_tied = select(ref_scores, orig_pos)
                nat_pos = cands.index(nat['chosen'])
                if nat_pos != ref_pos or nat['tied'] != ref_tied:
                    bad(fam + '_selection_vs_reference', dict(native=nat['chosen'], reference=cands[ref_pos], tied_native=nat['tied'], tied_reference=ref_tied))
                if ref_tied > 1: tie_states[fam] += 1
                if nat['chosen'] != dec['pivot']: c[fam + ':departures'] += 1
            # Diagnostic: batched numpy scores (the offline evaluation's code path).
            d = max(abs(x - y) for x, y in zip(n['linear']['scores'], ln))
            maxdiff['linear_numpy_batched'] = max(maxdiff.get('linear_numpy_batched', 0.0), d)
            if d > LINEAR_ABS_TOL: bad('linear_numpy_batched_beyond_tolerance', dict(max_abs_diff=d))
            np_pos, np_tied = select(ln, orig_pos)
            if cands[np_pos] != n['linear']['chosen']:
                c['diag:linear_selection_differs_under_numpy_batched'] += 1
                live = n['linear']['scores']; m = max(live)
                live_tied = {i for i, x in enumerate(live) if x == m}
                rows = {tuple(nf[i * F:(i + 1) * F]) for i in live_tied}
                explained = np_pos in live_tied and len(rows) == 1 and max(abs(ln[i] - ln[np_pos]) for i in live_tied) <= LINEAR_ABS_TOL
                if explained: c['diag:numpy_batched_difference_explained_identical_rows'] += 1
                else: bad('linear_numpy_batched_difference_unexplained', dict(native=n['linear']['chosen'], numpy=cands[np_pos]))
        exp_s, exp_c = EXPECTED['by_solver'][solver]
        coverage_ok = (c['states'], c['candidates']) == (exp_s, exp_c) or a.limit
        mism_total = sum(v for k, v in c.items() if k.startswith('mismatch:'))
        ok = bool(coverage_ok) and mism_total == 0 and pr.returncode == 0
        allok &= ok
        report['solvers'][solver] = dict(pass_=ok, expected_states=exp_s, expected_candidates=exp_c, observed_states=c['states'], observed_candidates=c['candidates'],
                                         native_exit=pr.returncode, native_header=header, counts=dict(c), max_abs_score_diff=maxdiff,
                                         reference_tie_states=dict(tie_states), mismatch_examples=dict(mism))
        print(solver, 'ok' if ok else 'FAIL', dict(c), maxdiff, flush=True)
    tot_s = sum(v['observed_states'] for v in report['solvers'].values()); tot_c = sum(v['observed_candidates'] for v in report['solvers'].values())
    report.update(observed_states=tot_s, observed_candidates=tot_c, pass_=allok and (a.limit or (tot_s, tot_c) == (EXPECTED['states'], EXPECTED['candidates'])),
                  limit=a.limit, seconds=round(time.time() - t0, 1))
    import gzip, shutil
    for solver in SOLVERS:   # keep the native outputs compactly (deterministic gzip, mtime 0)
        src = out / f'native_{solver}.jsonl'
        if src.exists():
            with open(src, 'rb') as fi, open(out / f'native_{solver}.jsonl.gz', 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as fo:
                shutil.copyfileobj(fi, fo)
            src.unlink()
    for p, _ in binaries.values():
        p.unlink()
    (out / 'bins').rmdir()
    (out / 'replay_report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('PASS' if report['pass_'] else 'FAIL', tot_s, tot_c)
    return 0 if report['pass_'] else 1


if __name__ == '__main__':
    sys.exit(main())
