"""Extract feature schema v1 candidate tables from pinned Stage C states and Stage D records.

Usage (any OS with Python >= 3.8; standard library only):
  python -m learnability.extract --experiment-tree <checkout of the Stage D experiment commit>
      --stagec-records <checkout of the Stage C records commit> --staged-records <checkout of the Stage D results commit>
      --output-root <directory> [--extraction-id ID] [--no-git-verify]

Output is built in <output-root>/.<id>.partial and atomically renamed to <output-root>/<id> only
when every acceptance check passes; otherwise it is renamed to <id>.INCOMPLETE and the exit code
is 2. Existing directories are never overwritten. No solver is built or run.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import secrets
import struct
import subprocess
import sys
import time
import zlib

from . import EXTRACTOR_NAME, EXTRACTOR_VERSION, FEATURE_SCHEMA_VERSION
from . import pins
from .decode import load_pinned_decoder, decode_checked, SnapshotError
from .eligibility import eligible_candidates, classical_rank, raw_weighted_degree, EligibilityError
from .features import compute_features, FEATURE_COLUMNS
from .outcomes import parse_outcome, canonical
from .reference import reference_features
from .schema import TableWriter, schema_document, ALLOWLISTS, COLUMN_NAMES
from .structure import validate_active_adjacency

HERE = pathlib.Path(__file__).resolve().parent
CHUNK_RE = re.compile(r'^runs/' + pins.STAGE_D_RUN + r'/chunks/([^/]+)/(attempt-[^/]+)/records\.jsonl$')


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def git_blob_id(b):
    return hashlib.sha1(b'blob %d\0' % len(b) + b).hexdigest()


def fnv64(b):
    h = 14695981039346656037
    for x in b:
        h = ((h ^ x) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return str(h)


def peak_memory_bytes():
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class PMC(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
            c = PMC(); c.cb = ctypes.sizeof(c)
            k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = wintypes.HANDLE
            p = ctypes.WinDLL('psapi'); p.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            if p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return dict(bytes=int(c.PeakWorkingSetSize), method='GetProcessMemoryInfo PeakWorkingSetSize (this process)')
        else:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return dict(bytes=int(r if sys.platform == 'darwin' else r * 1024), method='getrusage ru_maxrss (this process)')
    except Exception as e:  # measurement is optional
        return dict(bytes=None, method=f'unavailable: {e!r}')
    return dict(bytes=None, method='unavailable')


def cpu_model():
    try:
        if os.name == 'nt':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
                return winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
        if os.path.exists('/proc/cpuinfo'):
            for line in open('/proc/cpuinfo'):
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or 'unknown'


class Verifier:
    """Checks that files read from a checkout equal the blobs of a pinned commit (git ls-tree; no blob fetch)."""
    def __init__(self, enabled):
        self.enabled = enabled; self.trees = {}; self.results = collections.Counter(); self.failures = []

    def tree(self, root, commit, prefix):
        key = (str(root), commit, prefix)
        if key not in self.trees:
            out = subprocess.run(['git', '-C', str(root), 'ls-tree', '-r', commit, '--', prefix], capture_output=True, text=True, check=True).stdout
            entries = {}
            for line in out.splitlines():
                meta, path = line.split('\t', 1)
                mode, typ, oid = meta.split()
                entries[path] = oid
            self.trees[key] = entries
        return self.trees[key]

    def check(self, root, commit, prefix, rel, data):
        if not self.enabled:
            self.results['not_verified'] += 1; return None
        want = self.tree(root, commit, prefix).get(rel)
        ok = want is not None and want == git_blob_id(data)
        self.results['verified' if ok else 'mismatch'] += 1
        if not ok:
            self.failures.append(dict(root=str(root), commit=commit, path=rel, expected_blob=want, actual_blob=git_blob_id(data)))
        return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--experiment-tree', required=True); ap.add_argument('--stagec-records', required=True)
    ap.add_argument('--staged-records', required=True); ap.add_argument('--output-root', required=True)
    ap.add_argument('--extraction-id'); ap.add_argument('--no-git-verify', action='store_true')
    a = ap.parse_args(argv)
    t0 = time.perf_counter(); c0 = time.process_time(); started = datetime.datetime.now(datetime.timezone.utc)
    ext_id = a.extraction_id or f'extract-v1-{started.strftime("%Y%m%dT%H%M%SZ")}-{secrets.token_hex(4)}'
    if not re.fullmatch(r'extract-v1-[0-9A-Za-z_.-]+', ext_id):
        sys.exit('extraction id must match extract-v1-<suffix>')
    root = pathlib.Path(a.output_root).resolve(); root.mkdir(parents=True, exist_ok=True)
    final, partial, failed = root / ext_id, root / f'.{ext_id}.partial', root / f'{ext_id}.INCOMPLETE'
    for p in (final, partial, failed):
        if p.exists():
            sys.exit(f'refusing to reuse existing output path {p}')
    partial.mkdir()
    exp = pathlib.Path(a.experiment_tree).resolve(); scr = pathlib.Path(a.stagec_records).resolve(); sdr = pathlib.Path(a.staged_records).resolve()
    ver = Verifier(not a.no_git_verify)
    problems = []          # anything here prevents the complete/clean status
    inputs = {}
    try:
        # ---------------- pinned experiment files ----------------
        for rel in pins.EXPERIMENT_FILES:
            data = (exp / rel).read_bytes()
            ok = ver.check(exp, pins.STAGE_D_EXPERIMENT_COMMIT, rel, rel, data)
            inputs[f'experiment:{rel}'] = dict(sha256=sha256(data), git_blob=git_blob_id(data), bytes=len(data), commit=pins.STAGE_D_EXPERIMENT_COMMIT, verified=ok)
            if ok is False:
                problems.append(f'experiment file {rel} differs from the pinned commit')
        decode, decoder_sha = load_pinned_decoder(exp / 'stagec/snapshot.py')
        index_bytes = zlib.decompress((exp / 'staged/index.json.zz').read_bytes())
        index_sha = sha256(index_bytes); index = json.loads(index_bytes)
        native = json.loads(zlib.decompress((exp / 'staged/validation.json.zz').read_bytes()))
        for k, want in [('stage_c_run', pins.STAGE_C_RUN), ('records_commit', pins.STAGE_C_RECORDS_COMMIT), ('stage_c_experiment_commit', pins.STAGE_C_EXPERIMENT_COMMIT)]:
            if index.get(k) != want:
                problems.append(f'index {k}={index.get(k)!r} != pinned {want}')
        states = index['states']
        native_ok = {}
        for entry in native:
            for chk in entry['checks']:
                native_ok[(entry['metadata_path'], chk['sequence'])] = bool(chk.get('ok'))
        # expected per-candidate join information, from the index only
        expected = {}; scheduled = {}
        for si, s in enumerate(states):
            for k, v in enumerate(s['candidates']):
                key = (s['solver'], s['state_id'], v)
                if key in expected:
                    problems.append(f'duplicate candidate key in index {key}')
                expected[key] = dict(state_id=s['state_id'], graph_id=s['graph'], solver=s['solver'], phase=s['event']['phase'],
                                     component_subsolver=s['event']['component_subsolver'], snapshot_sha256=s['snapshot_sha256'],
                                     candidate_list_sha256=s['candidate_list_sha256'], candidate_local_id=v, candidate_label=s['candidate_labels'][k],
                                     is_original_pivot=v == s['event']['local_pivot'], original_local_id=s['event']['local_pivot'], state_index=si,
                                     initial_incumbent=s['initial_incumbent'], classical_score=s['scores'][k], classical_rank=classical_rank(s['scores'], k),
                                     stage_c_continuation=s['sample'].get('continuation'))
        for ci, arms in enumerate(index['chunks']):
            for si, v in arms:
                scheduled[(si, v)] = str(ci)
        pinned = dict(stage_d_experiment_commit=pins.STAGE_D_EXPERIMENT_COMMIT, cpu_budget_s=pins.CPU_BUDGET_S)

        # ---------------- Stage D records (single streaming pass) ----------------
        rec_files = []
        for p in (sdr / 'runs' / pins.STAGE_D_RUN / 'chunks').glob('*/attempt-*/records.jsonl'):
            rel = p.relative_to(sdr).as_posix(); m = CHUNK_RE.match(rel)
            if not m:
                problems.append(f'unexpected records path {rel}'); continue
            rec_files.append((int(m.group(1)) if m.group(1).isdigit() else 10**9, m.group(1), m.group(2), rel, p))
        rec_files.sort(key=lambda x: (x[0], x[1], x[2]))
        by_key = collections.defaultdict(list); run_ids = collections.Counter(); unexpected = []; chunk_checks = []
        status_counter = collections.Counter()
        with (partial / 'invocations.jsonl').open('w', encoding='utf-8', newline='\n') as inv:
            for _, chunk, attempt, rel, p in rec_files:
                data = p.read_bytes(); fsha = sha256(data)
                ok = ver.check(sdr, pins.STAGE_D_RESULTS_COMMIT, f'runs/{pins.STAGE_D_RUN}/chunks', rel, data)
                inputs[f'stage_d:{rel}'] = dict(sha256=fsha, git_blob=git_blob_id(data), bytes=len(data), commit=pins.STAGE_D_RESULTS_COMMIT, verified=ok)
                if ok is False:
                    problems.append(f'{rel} differs from the pinned Stage D results commit')
                counts = collections.Counter(); n = 0
                for line_no, line in enumerate(data.decode('utf-8').split('\n'), 1):
                    if not line.strip():
                        continue
                    n += 1
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError as e:
                        problems.append(f'{rel}:{line_no} unparseable record: {e}'); unexpected.append(dict(path=rel, line=line_no, reason='unparseable')); continue
                    counts[r.get('status')] += 1; status_counter[r.get('status')] += 1; run_ids[r.get('run_id')] += 1
                    key = (r.get('solver'), r.get('state_id'), r.get('candidate_local_id'))
                    ref = dict(run_id=r.get('run_id'), chunk_id=chunk, attempt_id=attempt, source_record_path=rel, source_record_line=line_no)
                    matched = key in expected
                    sched_chunk = scheduled.get((r.get('state_index'), r.get('candidate_local_id')))
                    entry = dict(ref=ref, record_file_sha256=fsha)   # raw record goes only to invocations.jsonl
                    if matched:
                        fields, jerr, merr = parse_outcome(r, expected[key], pinned)
                        if sched_chunk != chunk:
                            jerr.append(f'record found in chunk {chunk} but scheduled in chunk {sched_chunk}')
                        entry.update(fields=fields, join_errors=jerr, measurement_errors=merr)
                        by_key[key].append(entry)
                    else:
                        unexpected.append(dict(path=rel, line=line_no, key=list(key), reason='no matching indexed candidate'))
                    inv.write(canonical(dict(provenance=dict(ref, record_file_sha256=fsha), matched_indexed_candidate=matched,
                                             scheduled_chunk=sched_chunk, raw_record=r)) + '\n')
                summ_p = p.with_name('summary.json'); sched_p = p.with_name('schedule.json')
                summ = json.loads(summ_p.read_bytes()) if summ_p.exists() else None
                sched = json.loads(sched_p.read_bytes()) if sched_p.exists() else None
                for q in (summ_p, sched_p, p.with_name('environment.json')):
                    if q.exists():
                        qd = q.read_bytes(); qrel = q.relative_to(sdr).as_posix()
                        qok = ver.check(sdr, pins.STAGE_D_RESULTS_COMMIT, f'runs/{pins.STAGE_D_RUN}/chunks', qrel, qd)
                        inputs[f'stage_d:{qrel}'] = dict(sha256=sha256(qd), git_blob=git_blob_id(qd), bytes=len(qd), commit=pins.STAGE_D_RESULTS_COMMIT, verified=qok)
                        if qok is False:
                            problems.append(f'{qrel} differs from the pinned commit')
                cc = dict(chunk_id=chunk, attempt_id=attempt, records=n, summary_arms=summ and summ.get('arms'),
                          summary_status_counts=summ and summ.get('status_counts'), recomputed_status_counts=dict(sorted(counts.items())),
                          schedule_index_sha256=sched and sched.get('index_sha256'), scheduled_arms=len(index['chunks'][int(chunk)]) if chunk.isdigit() and int(chunk) < len(index['chunks']) else None)
                cc['summary_agrees'] = bool(summ) and summ.get('arms') == n and summ.get('status_counts') == dict(counts)
                cc['schedule_index_matches'] = bool(sched) and sched.get('index_sha256') == index_sha
                cc['schedule_arms_match'] = bool(sched) and sorted(map(tuple, sched.get('arms', []))) == sorted((si, v, pins.CPU_BUDGET_S) for si, v in index['chunks'][int(chunk)])
                chunk_checks.append(cc)
                if not (cc['summary_agrees'] and cc['schedule_index_matches'] and cc['schedule_arms_match'] and n == cc['scheduled_arms']):
                    problems.append(f'chunk {chunk}/{attempt} summary/schedule check failed')
        dup_uuid = sorted(k for k, v in run_ids.items() if v > 1)
        if dup_uuid:
            problems.append(f'{len(dup_uuid)} duplicated invocation UUIDs')
        if unexpected:
            problems.append(f'{len(unexpected)} records do not match an indexed candidate')
        # ---------------- Stage D report cross-check (counts only; no comparison verdicts reused) ----------------
        rep_dir = sdr / 'runs' / pins.STAGE_D_RUN / 'report' / 'attempt-1'; report_check = dict(available=rep_dir.exists())
        if rep_dir.exists():
            for name in ('REPORT.md', 'states.json', 'per_graph.json', 'per_solver.json', 'retries_requiring_resolution.json'):
                qd = (rep_dir / name).read_bytes(); qrel = (rep_dir / name).relative_to(sdr).as_posix()
                qok = ver.check(sdr, pins.STAGE_D_RESULTS_COMMIT, f'runs/{pins.STAGE_D_RUN}/report', qrel, qd)
                inputs[f'stage_d:{qrel}'] = dict(sha256=sha256(qd), git_blob=git_blob_id(qd), bytes=len(qd), commit=pins.STAGE_D_RESULTS_COMMIT, verified=qok)
                if qok is False:
                    problems.append(f'{qrel} differs from the pinned commit')
            m_ = re.search(r'Recorded invocations \(including retries\): (\d+)', (rep_dir / 'REPORT.md').read_text(encoding='utf-8'))
            rep_states = json.loads((rep_dir / 'states.json').read_bytes()); retries = json.loads((rep_dir / 'retries_requiring_resolution.json').read_bytes())
            per_state = collections.Counter(k[1] for k, v in by_key.items() for _ in v)
            report_check.update(report_recorded_invocations=int(m_.group(1)) if m_ else None, discovered_invocations=sum(run_ids.values()),
                                report_states=len(rep_states), report_retries=len(retries),
                                states_recorded_arms_mismatch=[x['state_id'] for x in rep_states if x['recorded_arms'] != per_state.get(x['state_id'], 0)][:20])
            idx_c = {s['state_id']: len(s['candidates']) for s in states}
            report_check['states_candidate_count_mismatch'] = [x['state_id'] for x in rep_states if idx_c.get(x['state_id']) != x['candidates']][:20]
            report_check['agrees'] = (report_check['report_recorded_invocations'] == report_check['discovered_invocations'] and len(rep_states) == len(states)
                                      and not report_check['states_recorded_arms_mismatch'] and not report_check['states_candidate_count_mismatch']
                                      and len(retries) == sum(len(v) > 1 for v in by_key.values()))
            if not report_check['agrees']:
                problems.append('Stage D report counts disagree with the discovered records')
        else:
            problems.append('Stage D report directory not available')
        chunk_ids = {c['chunk_id'] for c in chunk_checks}
        if len(chunk_ids) != pins.EXPECTED_CHUNKS or len(index['chunks']) != pins.EXPECTED_CHUNKS:
            problems.append(f'expected {pins.EXPECTED_CHUNKS} chunks; found {len(chunk_ids)} record chunks, {len(index["chunks"])} indexed')

        # ---------------- states: verify, decode, validate, features, join ----------------
        cache_path = None; cache = None
        state_rows = []; anomaly = collections.defaultdict(list)
        audit = collections.defaultdict(collections.Counter)
        feature_values = collections.defaultdict(lambda: collections.defaultdict(set))
        ref_mismatch = 0; ref_checked = 0
        files = {s: (partial / f'candidates_{s}.csv').open('w', encoding='utf-8', newline='') for s in ('8', '5', 'LP')}
        writers = {s: TableWriter(f) for s, f in files.items()}
        written = collections.Counter()
        with (partial / 'states.jsonl').open('w', encoding='utf-8', newline='\n') as sfh:
            for si, s in enumerate(states):
                solver = s['solver']; errors = []; checks = {}
                meta_rel = s['metadata_path']
                if meta_rel != cache_path:
                    mp = scr / meta_rel; packed_p = mp.with_name('samples.bin.zz')
                    mdata = mp.read_bytes(); pdata = packed_p.read_bytes()
                    for rel, data in ((meta_rel, mdata), (packed_p.relative_to(scr).as_posix(), pdata)):
                        ok = ver.check(scr, pins.STAGE_C_RECORDS_COMMIT, f'runs/{pins.STAGE_C_RUN}/pairs', rel, data)
                        inputs[f'stage_c:{rel}'] = dict(sha256=sha256(data), git_blob=git_blob_id(data), bytes=len(data), commit=pins.STAGE_C_RECORDS_COMMIT, verified=ok)
                        if ok is False:
                            problems.append(f'{rel} differs from the pinned Stage C records commit')
                    cache = dict(meta=json.loads(mdata), packed_sha=sha256(pdata), raw=zlib.decompress(pdata)); cache_path = meta_rel
                meta, raw = cache['meta'], cache['raw']; samp = s['sample']
                checks['packed_sha256'] = cache['packed_sha'] == s['packed_sha256']
                match = [x for x in meta['samples'] if x['sequence'] == samp['sequence']]
                checks['metadata_sample_matches_index'] = len(match) == 1 and match[0] == samp and meta['variant'] == solver and meta['graph'].split('/')[-1].split('.')[0] == s['graph']
                o, L, co, cc = samp['offset'], samp['state_bytes'], samp['candidates_offset'], samp['candidate_count']
                checks['slice_bounds'] = 0 <= o and o + L <= len(raw) and 0 <= co and co + 4 * cc <= len(raw) and cc == len(s['candidates'])
                blob = raw[o:o + L] if checks['slice_bounds'] else b''; cb = raw[co:co + 4 * cc] if checks['slice_bounds'] else b''
                checks['snapshot_sha256'] = sha256(blob) == s['snapshot_sha256']
                checks['candidate_list_sha256'] = sha256(cb) == s['candidate_list_sha256']
                checks['state_fnv'] = fnv64(blob) == samp.get('state_fnv') if 'state_fnv' in samp else None
                cand_bytes = list(struct.unpack('<' + 'i' * cc, cb)) if len(cb) == 4 * cc else None
                checks['candidate_bytes_match_index'] = cand_bytes == s['candidates']
                checks['native_samplecheck_ok'] = native_ok.get((meta_rel, samp['sequence']))
                dec = None; struct_errors = []; feats = None
                try:
                    dec = decode_checked(decode, blob, expected_variant=solver); checks['decode'] = True
                except SnapshotError as e:
                    checks['decode'] = False; errors.append(str(e))
                if dec:
                    ev = s['event']; inc = s['initial_incumbent']
                    checks['pivot_matches'] = dec['pivot'] == ev['local_pivot'] and dec['stageNames'][dec['pivot']] == ev['original_pivot']
                    checks['root_matches'] = (dec['phase'] == 2 and ev['root'] == dec['stageNames'][dec['root']]) if solver == 'LP' else ev['root'] is None
                    checks['event_context_matches'] = ev['component_subsolver'] == dec['isSub'] and ev['depth'] == dec['depth'] and ev['solver_depth'] == dec['solver_depth'] and ev['candidate_count'] == len(s['candidates'])
                    checks['initial_incumbent_matches'] = inc == {'size_cap': dec['size_cap'], 'solFound': dec['solFound'], 'sol': list(dec['sol'])}
                    checks['labels_match'] = s['candidate_labels'] == [dec['stageNames'][c] for c in s['candidates']]
                    checks['snapshot_N_matches'] = s.get('snapshot_N') == dec['N']
                    try:
                        cands, scores = eligible_candidates(dec)
                        checks['eligibility_and_order_match'] = cands == s['candidates']
                        checks['scores_match_index'] = scores == s['scores']
                    except EligibilityError as e:
                        checks['eligibility_and_order_match'] = False; checks['scores_match_index'] = False; errors.append(str(e))
                    checks['pivot_in_candidates'] = dec['pivot'] in s['candidates']
                    if solver == '5':
                        checks['chen_hints_exhausted'] = not dec['stageHint'] and not dec['branching_hints']
                    if solver == 'LP':
                        checks['lp_root_active_safe'] = dec['status'][dec['root']] == 1
                    struct_errors = validate_active_adjacency(dec['status'], dec['neighbours'], dec['neighDouble'], dec['doubleNum'], dec['posAtNeigh'])
                    checks['active_adjacency_valid'] = not struct_errors
                    root = dec['root'] if solver == 'LP' else None
                    state_f, feats, diag = compute_features(solver, dec['status'], dec['neighbours'], dec['neighDouble'], dec['size_cap'], len(dec['X']), s['candidates'], root)
                    wdeg = diag['wdeg']
                    checks['raw_degree_equals_active_weighted_degree'] = all(raw_weighted_degree(dec, v) == w for v, w in wdeg.items())
                    checks['weighted_degree_identity'] = diag['weighted_degree_sum'] == 2 * (state_f['f_state_distinct_edges'] + state_f['f_state_double_edges']) and diag['degree_sum'] % 2 == 0 and diag['double_sum'] % 2 == 0
                    checks['remaining_threshold_positive'] = state_f['f_state_remaining_threshold'] > 0
                    refrows = reference_features(solver, dec['status'], dec['neighbours'], dec['neighDouble'], dec['size_cap'], len(dec['X']), s['candidates'], root)
                    ref_checked += 1
                    same = all(all(a_[c] == b_[c] for c in FEATURE_COLUMNS) for a_, b_ in zip(feats, refrows)) and len(feats) == len(refrows)
                    checks['reference_features_match'] = same; ref_mismatch += not same
                    for k, fr in enumerate(feats):
                        sc = s['scores'][k]
                        want = fr['diag_cand_weighted_degree'] if solver != '5' else [fr['f_cand_safe_neighbors'], fr['diag_cand_weighted_degree']]
                        if sc != want:
                            checks['classical_score_matches_features'] = False
                        if solver == 'LP' and fr['f_lp_root_common_neighbors'] > min(fr['diag_cand_distinct_degree'], len(set(x for x in dec['neighbours'][root] if dec['status'][x] in (0, 1)))):
                            checks['lp_common_neighbor_bound'] = False
                    checks.setdefault('classical_score_matches_features', True)
                    if solver == 'LP':
                        checks.setdefault('lp_common_neighbor_bound', True)
                    # dataset observations (validated, not universal assertions)
                    if solver == 'LP':
                        audit['LP']['states_with_exactly_one_safe_vertex'] += state_f['f_state_safe_vertices'] == 1
                        audit['LP']['candidates_with_exactly_one_safe_neighbour'] += sum(fr['f_cand_safe_neighbors'] == 1 for fr in feats)
                    if solver == '8':
                        audit['8']['states_with_tied_weighted_degree'] += len({fr['diag_cand_weighted_degree'] for fr in feats}) == 1
                    audit[solver]['states_weighted_degree_varies'] += len({fr['diag_cand_weighted_degree'] for fr in feats}) > 1
                    audit[solver]['states_nbr_wdeg_mean_varies'] += len({fr['f_nbr_none_wdeg_mean'] for fr in feats}) > 1
                    if solver == 'LP':
                        audit['LP']['states_common_neighbors_varies'] += len({fr['f_lp_root_common_neighbors'] for fr in feats}) > 1
                    audit[solver]['candidates_distinct_degree_le_2'] += sum(fr['diag_cand_distinct_degree'] <= 2 for fr in feats)
                    audit[solver]['candidates_empty_undecided_neighbourhood'] += sum(fr['f_cand_none_neighbors'] == 0 for fr in feats)
                    if solver == '5':
                        audit['5']['states_strict_qualifying'] += bool(s['event'].get('qualifying_state'))
                for name, v in checks.items():
                    if v is False:
                        errors.append(f'state check failed: {name}')
                    if v is None and name in ('native_samplecheck_ok',):
                        errors.append(f'state check has no evidence: {name}')
                errors += struct_errors
                integrity = not errors and dec is not None
                if not integrity:
                    anomaly['state_integrity'].append(dict(state_id=s['state_id'], solver=solver, errors=errors[:20]))
                    problems.append(f'state {s["state_id"]} failed integrity checks')
                # ----- join outcomes and write rows -----
                arm_rows = []
                for k, v in enumerate(s['candidates']):
                    key = (solver, s['state_id'], v); recs = by_key.get(key, [])
                    arm_rows.append((k, v, recs))
                completed_caps = set()
                for k, v, recs in arm_rows:
                    if len(recs) == 1 and recs[0]['fields']['raw_status'] == 'completed' and not recs[0]['join_errors'] and not recs[0]['measurement_errors']:
                        completed_caps.add(recs[0]['fields']['final_size_cap'])
                cap_consistent = None if not completed_caps else len(completed_caps) == 1
                if cap_consistent is False:
                    anomaly['completed_cap_inconsistent'].append(dict(state_id=s['state_id'], caps=sorted(completed_caps)))
                    problems.append(f'state {s["state_id"]} has inconsistent completed final size_cap')
                audit[solver]['states_sample_kind:' + samp['kind']] += 1
                kinds_here = {recs[0]['fields']['raw_status'] if len(recs) == 1 else 'unresolved' for _, _, recs in arm_rows}
                audit[solver]['states_arm_status_pattern:' + '+'.join(sorted(kinds_here))] += 1
                for k, v, recs in arm_rows:
                    fr = feats[k] if feats else {c: None for c in FEATURE_COLUMNS}
                    row = {c: None for c in COLUMN_NAMES}
                    row.update(solver=solver, graph_id=s['graph'], state_id=s['state_id'], state_index=si, candidate_local_id=v,
                               candidate_label=s['candidate_labels'][k], candidate_ordinal=k, original_local_id=s['event']['local_pivot'],
                               is_original_pivot=v == s['event']['local_pivot'], root_local_id=(dec['root'] if dec and solver == 'LP' else None),
                               phase=s['event']['phase'], component_subsolver=s['event']['component_subsolver'], depth=s['event']['depth'],
                               solver_depth=s['event']['solver_depth'], sample_kind=samp['kind'], sample_slot=samp['slot'], sample_sequence=samp['sequence'],
                               sample_a_index=samp['a_index'], snapshot_bytes=samp['state_bytes'], state_metadata_ref=f'states.jsonl#{s["state_id"]}',
                               stage_c_run_id=pins.STAGE_C_RUN, stage_d_run_id=pins.STAGE_D_RUN, snapshot_sha256=s['snapshot_sha256'],
                               candidate_list_sha256=s['candidate_list_sha256'], packed_sha256=s['packed_sha256'], snapshot_source_path=meta_rel,
                               sample_offset=samp['offset'], candidates_offset=samp['candidates_offset'])
                    for c in FEATURE_COLUMNS:
                        row[c] = fr[c]
                    if dec:
                        row.update(diag_allocated_N=dec['N'], diag_stored_M=dec['M'], diag_current_X_size=len(dec['X']), diag_initial_size_cap=dec['size_cap'],
                                   diag_initial_solFound=dec['solFound'], diag_cand_distinct_degree=fr['diag_cand_distinct_degree'],
                                   diag_cand_weighted_degree=fr['diag_cand_weighted_degree'])
                    row.update(classical_score_json=s['scores'][k], classical_rank=classical_rank(s['scores'], k),
                               invocation_count=len(recs), invocation_resolution='unique' if len(recs) == 1 else ('missing' if not recs else 'multiple'),
                               invocation_refs_json=[r_['ref'] for r_ in recs], state_integrity_ok=integrity, state_completed_cap_consistent=cap_consistent)
                    rerrs = [f'state: {e}' for e in errors[:5]]
                    if len(recs) == 1:
                        r1 = recs[0]; f1 = dict(r1['fields'])
                        jv = not r1['join_errors']
                        if not jv or not integrity:
                            if f1['node_observation_kind'] == 'exact':
                                f1['node_observation_kind'] = 'invalid'
                            f1['exact_nodes'] = None
                        notes = f1.pop('_notes', [])
                        for c in list(f1):
                            if c in row:
                                row[c] = f1[c]
                        row.update(invocation_run_id=r1['ref']['run_id'], chunk_id=r1['ref']['chunk_id'], attempt_id=r1['ref']['attempt_id'],
                                   source_record_path=r1['ref']['source_record_path'], source_record_line=r1['ref']['source_record_line'],
                                   source_record_sha256=r1['record_file_sha256'], join_valid=jv, measurement_integrity_ok=not r1['measurement_errors'])
                        rerrs += [f'join: {e}' for e in r1['join_errors']] + [f'measurement: {e}' for e in r1['measurement_errors']] + [f'note: {e}' for e in notes]
                        if r1['join_errors']:
                            anomaly['join_errors'].append(dict(key=list(key), errors=r1['join_errors']))
                            problems.append(f'join errors for {key}')
                        if r1['measurement_errors']:
                            anomaly['measurement_errors'].append(dict(key=list(key), errors=r1['measurement_errors']))
                            problems.append(f'measurement errors for {key}')
                    else:
                        row['node_observation_kind'] = 'missing' if not recs else 'unresolved_multiple'
                        anomaly['missing_invocations' if not recs else 'multiple_invocations'].append(dict(key=list(key), refs=[r_['ref'] for r_ in recs]))
                        problems.append(f'{"missing" if not recs else "multiple"} invocation for {key}')
                    row['validation_errors_json'] = rerrs
                    writers[solver].write(row); written[solver] += 1
                    audit[solver]['kind:' + row['node_observation_kind']] += 1
                    if row['raw_status']:
                        audit[solver]['status:' + row['raw_status']] += 1
                    for c in FEATURE_COLUMNS:
                        if len(feature_values[solver][c]) < 2:
                            feature_values[solver][c].add(row[c])
                state_rec = dict(state_id=s['state_id'], state_index=si, solver=solver, graph_id=s['graph'], metadata_path=meta_rel,
                                 packed_sha256=s['packed_sha256'], snapshot_sha256=s['snapshot_sha256'], candidate_list_sha256=s['candidate_list_sha256'],
                                 sample={k_: v_ for k_, v_ in samp.items() if k_ not in ('continuation', 'event')}, event=s['event'],
                                 candidates=s['candidates'], candidate_labels=s['candidate_labels'], classical_scores=s['scores'],
                                 initial_incumbent=s['initial_incumbent'],
                                 decoded=None if not dec else dict(N=dec['N'], M=dec['M'], deleted=dec['deleted'], phase=dec['phase'], pivot=dec['pivot'], root=dec['root'],
                                                                     depth=dec['depth'], solver_depth=dec['solver_depth'], isSub=dec['isSub'], size_cap=dec['size_cap'],
                                                                     solFound=dec['solFound'], X_size=len(dec['X']), stageHint=dec['stageHint'],
                                                                     branching_hints_remaining=len(dec['branching_hints']), self_loop_queue=len(dec['selfLoops']),
                                                                     deg2_queue=len(dec['deg2ToReduce']), **({'br2': dec['br2']} if 'br2' in dec else {}),
                                                                     **({'kernelize_switch': dec['kernelize_switch']} if 'kernelize_switch' in dec else {})),
                                 state_features=None if not feats else {c: feats[0][c] for c in FEATURE_COLUMNS if c.startswith('f_state_')},
                                 checks=checks, integrity_ok=integrity, integrity_errors=errors[:50], completed_cap_consistent=cap_consistent,
                                 outcome_reference_not_a_feature=dict(stage_c_continuation=samp.get('continuation')))
                sfh.write(canonical(state_rec) + '\n'); state_rows.append(dict(solver=solver, graph=s['graph'], integrity=integrity))
        for f in files.values():
            f.close()
        t_extract = time.perf_counter() - t0

        # ---------------- acceptance ----------------
        acc = {}
        per = collections.Counter(r['solver'] for r in state_rows)
        acc['states_total'] = len(state_rows) == pins.EXPECTED_STATES
        acc['candidates_total'] = sum(written.values()) == pins.EXPECTED_CANDIDATES
        acc['per_solver_counts'] = all(per[s] == pins.EXPECTED[s]['states'] and written[s] == pins.EXPECTED[s]['candidates'] for s in pins.EXPECTED)
        acc['all_invocations_accounted'] = sum(len(v) for v in by_key.values()) + len(unexpected) == sum(run_ids.values())
        acc['every_candidate_unique_invocation'] = all(len(by_key.get(k, [])) == 1 for k in expected) and len(by_key) == len(expected)
        acc['no_unexpected_records'] = not unexpected
        acc['no_duplicate_uuids'] = not dup_uuid
        acc['reference_features_match_all_states'] = ref_checked == len(states) and ref_mismatch == 0
        acc['all_states_integrity_ok'] = all(r['integrity'] for r in state_rows)
        acc['inputs_verified_against_pins'] = ver.enabled and not ver.failures
        acc['chunk_summaries_agree'] = all(c['summary_agrees'] and c['schedule_index_matches'] and c['schedule_arms_match'] for c in chunk_checks)
        acc['no_join_or_measurement_errors'] = not anomaly['join_errors'] and not anomaly['measurement_errors']
        acc['completed_caps_consistent'] = not anomaly['completed_cap_inconsistent']
        acc['stage_d_report_agrees'] = bool(report_check.get('agrees'))
        status = 'complete_validated' if all(acc.values()) and not problems else 'incomplete'
        validation = dict(extraction_id=ext_id, dataset_status=status, acceptance=acc, problems=problems[:500], problem_count=len(problems),
                          counts=dict(states=dict(per), candidates=dict(written), invocations=sum(run_ids.values()), unexpected_records=len(unexpected),
                                      duplicate_uuids=len(dup_uuid), graphs_represented={s: len({r['graph'] for r in state_rows if r['solver'] == s}) for s in pins.EXPECTED},
                                      graphs_represented_any=len({r['graph'] for r in state_rows})),
                          record_status_counts=dict(status_counter), audit={k: dict(v) for k, v in audit.items()},
                          feature_variation={s: {c: ('varies' if len(v) > 1 else 'constant') for c, v in d.items()} for s, d in feature_values.items()},
                          reference_check=dict(states_checked=ref_checked, states_mismatched=ref_mismatch), stage_d_report_check=report_check,
                          input_verification=dict(ver.results, failures=ver.failures[:50]),
                          chunk_checks=dict(chunks=len(chunk_checks), all_agree=acc['chunk_summaries_agree'],
                                            failures=[c for c in chunk_checks if not (c['summary_agrees'] and c['schedule_index_matches'] and c['schedule_arms_match'])][:20]),
                          anomalies={k: dict(count=len(v), examples=v[:25]) for k, v in anomaly.items()}, unexpected_records=unexpected[:100],
                          duplicate_uuid_examples=dup_uuid[:20])
        (partial / 'validation.json').write_text(json.dumps(validation, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        (partial / 'schema.json').write_text(json.dumps(schema_document(), indent=1) + '\n', encoding='utf-8', newline='\n')
        from .report import write_report
        outputs = {}
        ended = datetime.datetime.now(datetime.timezone.utc)
        timing = dict(wall_s=time.perf_counter() - t0, cpu_s=time.process_time() - c0, extraction_core_wall_s=t_extract)
        write_report(partial, validation, timing, cpu_model(), peak_memory_bytes())
        for name in sorted(os.listdir(partial)):
            data = (partial / name).read_bytes(); outputs[name] = dict(sha256=sha256(data), bytes=len(data))
        manifest = dict(extraction_id=ext_id, dataset_status=status, extractor=dict(name=EXTRACTOR_NAME, version=EXTRACTOR_VERSION, feature_schema=FEATURE_SCHEMA_VERSION,
                        source_sha256={p.name: sha256(p.read_bytes()) for p in sorted(HERE.glob('*.py'))}, pinned_decoder_sha256=decoder_sha),
                        python=dict(version=sys.version, implementation=platform.python_implementation(), dependencies='standard library only'),
                        platform=dict(os=platform.platform(), machine=platform.machine(), cpu=cpu_model()),
                        command=[sys.executable, '-m', 'learnability.extract'] + (argv if argv is not None else sys.argv[1:]),
                        started_utc=started.isoformat(), ended_utc=ended.isoformat(), timing=timing, peak_memory=peak_memory_bytes(),
                        immutable_refs=dict(repository=pins.REPOSITORY, sea_upstream=pins.SEA_UPSTREAM, sea_commit=pins.SEA_COMMIT,
                                            stage_c_run=pins.STAGE_C_RUN, stage_c_experiment_commit=pins.STAGE_C_EXPERIMENT_COMMIT, stage_c_records_commit=pins.STAGE_C_RECORDS_COMMIT,
                                            stage_d_run=pins.STAGE_D_RUN, stage_d_experiment_commit=pins.STAGE_D_EXPERIMENT_COMMIT, stage_d_results_commit=pins.STAGE_D_RESULTS_COMMIT),
                        index=dict(decompressed_sha256=index_sha, states=len(states), chunks=len(index['chunks'])),
                        input_roots=dict(experiment_tree=str(exp), stagec_records=str(scr), staged_records=str(sdr)),
                        inputs=inputs, outputs=outputs, counts=validation['counts'], git_verification=dict(ver.results))
        (partial / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    except Exception:
        import traceback
        (partial / 'FAILURE.txt').write_text(traceback.format_exc(), encoding='utf-8')
        os.rename(partial, failed)
        print(f'extraction failed; diagnostics in {failed}', file=sys.stderr)
        raise
    if status == 'complete_validated':
        (partial / 'COMPLETE').write_text(sha256((partial / 'manifest.json').read_bytes()) + '\n', encoding='utf-8', newline='\n')
        os.rename(partial, final)
        print(f'COMPLETE {final}')
        return 0
    os.rename(partial, failed)
    print(f'INCOMPLETE {failed}: {len(problems)} problems; see validation.json', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
