"""Addendum: rescore the archived linear CV fold models with the deployed scorer and the exact tie rule.

Frozen inputs only: the 90 exported linear fold models (6 lambdas x 5 folds x 3 solvers) of offline run
45408454796 (learnability-results e5b8401), the frozen fold manifest, extraction
extract-v1-20261124T115559Z-833e6421 and the public Stage C snapshots. Nothing is refitted or retuned,
no solver is run, and no reserved graph is touched (all states come from the public extraction).

For every fold model and every state of its held-out fold:
  old       = the original offline scorer, LinearTransform.from_export(...).transform(X) @ theta per state
              (numpy batched), which must reproduce every archived summary of run 45408454796 exactly
  deployed  = PolicyReplay.exe from validated build 45493670014 (the solver's own FvsPolicy selectCore,
              features computed live from the snapshot), and a Python left-to-right replica of the live
              summation that must agree with it bit for bit
Both arms use learnability.train.evaluate.select (argmax; exact ties -> original if among maxima, else the
lowest archived ordinal) and evaluate_state / summarise / choose unchanged.

Usage: python rescore_linear.py --learn-root R --data D --inputs IN --stagec-records S --work W --out O
"""
import argparse, collections, gzip, hashlib, json, math, os, pathlib, platform, subprocess, sys, time, zlib

SOLVERS = ('8', '5', 'LP')
LAMBDAS = [1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]
RUN = 'runs/45408454796/attempt-1'
REPLAY_SHA = '24e2fd2ee046a13a113e5519aa79820dc8c22096a5ce90be460ee7282b5adf4f'


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def jload(p):
    return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))


def jdump(p, x):
    pathlib.Path(p).write_text(json.dumps(x, indent=1, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def sequential(tr, theta, Xt):
    """Live summation order: phi in phi_order, s += theta_j * phi_j left to right (FvsPolicy.cpp score())."""
    Phi = tr.transform(Xt)
    out = []
    for i in range(len(Phi)):
        s = 0.0
        for j in range(len(theta)):
            s += float(theta[j]) * float(Phi[i, j])
        out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    for x in ('--learn-root', '--data', '--inputs', '--stagec-records', '--work', '--out'):
        ap.add_argument(x, required=True)
    a = ap.parse_args()
    learn = pathlib.Path(a.learn_root).resolve(); inputs = pathlib.Path(a.inputs).resolve(); rec = pathlib.Path(a.stagec_records).resolve()
    work = pathlib.Path(a.work).resolve(); out = pathlib.Path(a.out).resolve(); data = pathlib.Path(a.data).resolve()
    sys.path.insert(0, str(learn))
    import numpy as np
    from learnability.train import run as R, evaluate as E, transforms as T, data as D
    run = inputs / RUN; frozen = run / 'frozen'
    t0 = time.time()
    checks = collections.OrderedDict(); fail = []

    def check(name, ok, detail=None):
        checks[name] = dict(ok=bool(ok), detail=detail)
        if not ok:
            fail.append(name); print('CHECK FAILED', name, detail, flush=True)

    cfg = jload(frozen / 'config.json')
    _, hashes = D.verify_extraction(data, cfg['extraction_id'])
    check('extraction_hashes_equal_frozen_config', hashes == cfg['extraction_hashes'])
    # git archive on Windows wrote this file with CRLF; compare LF-normalised bytes and the embedded manifest hash
    lf = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    check('fold_manifest_equal_training_branch', lf(frozen / 'folds.json') == lf(learn / 'learnability/train/frozen/folds.json')
          and jload(frozen / 'folds.json')['manifest_sha256'] == cfg['folds_sha256'], lf(frozen / 'folds.json'))
    replay = inputs / 'PolicyReplay.exe'
    check('policy_replay_is_validated_build', sha_file(replay) == REPLAY_SHA, sha_file(replay))
    selection = jload(run / 'selection/selection.json')
    work.mkdir(parents=True, exist_ok=True)
    bins = {}
    results = dict(addendum_id=(out / 'ID').read_text().strip() if (out / 'ID').exists() else None, solvers={})
    changes_out = gzip.open(out / 'changed_states.jsonl.gz', 'wt', encoding='utf-8', newline='\n')
    for solver in SOLVERS:
        sd = R.SolverData(data, frozen, solver)
        check(f'{solver}:pairs_equal_frozen', R.pair_hash(sd.pair_array()) == cfg['pairs_sha256'][solver])
        boost = run / f'final/{solver}/boost/final'
        sres = dict(configs={})
        for lam in LAMBDAS:
            cid = f'lambda={lam:g}'
            old_ev, new_ev, per_state = [], [], []
            st_ok = []
            for k in range(5):
                fdir = run / f'cv/{solver}/linear/{cid}/fold{k}'
                status = jload(fdir / 'fit_status.json'); st_ok.append(status['ok'])
                model = jload(fdir / 'model.json')
                check(f'{solver}:{cid}:fold{k}:model_identity', model['solver'] == solver and model['family'] == 'linear' and model['config']['lambda'] == lam
                      and status['fold'] == k and status['columns'] == sd.inputs)
                tr = T.LinearTransform.from_export(model['transform']); theta = np.array(model['theta'], dtype=np.float64)
                test = [s for s in sd.states if sd.fold_of[s.state_index] == k]
                check(f'{solver}:{cid}:fold{k}:heldout_count', len(test) == status['test_states'], (len(test), status['test_states']))
                # native deployed scorer on the held-out states
                tsv = []
                for s in test:
                    r0 = s.rows[0]
                    src = rec / pathlib.Path(r0['snapshot_source_path']).parent / 'samples.bin.zz'
                    if src not in bins:
                        p = work / 'bins' / (hashlib.sha256(str(src).encode()).hexdigest()[:16] + '.bin')
                        if not p.exists():
                            p.parent.mkdir(exist_ok=True); p.write_bytes(zlib.decompress(src.read_bytes()))
                        bins[src] = p
                    tsv.append('\t'.join([s.state_id, str(bins[src]), str(r0['sample_offset']), str(r0['snapshot_bytes']), str(r0['candidates_offset']), str(s.n)]))
                tp = work / f'{solver}_{cid}_fold{k}.tsv'; tp.write_text('\n'.join(tsv) + '\n', encoding='utf-8', newline='\n')
                with open(tp, 'rb') as fi:
                    pr = subprocess.run([str(replay), solver, str(fdir / 'model.json'), str(boost / 'model.json'), str(boost / 'model_meta.json')],
                                        stdin=fi, capture_output=True)
                lines = [json.loads(l) for l in pr.stdout.decode('utf-8').splitlines() if l.strip()]
                check(f'{solver}:{cid}:fold{k}:native_exit', pr.returncode == 0, pr.stderr.decode()[-300:])
                nat = {n['state_id']: n for n in lines[1:]}
                bad = collections.Counter()
                for s in test:
                    n = nat.get(s.state_id)
                    if n is None or n.get('error'):
                        bad['native_error'] += 1; continue
                    cands = [r['candidate_local_id'] for r in s.rows]
                    if n['candidates'] != cands or not n['archived_candidates_match']: bad['candidates'] += 1
                    if n['original'] != cands[s.original]: bad['original'] += 1
                    Xt = sd.X[s.state_index]
                    F = len(n['features']) // s.n
                    from learnability.features import FEATURE_COLUMNS
                    nf = np.array(n['features'], dtype=np.float64).reshape(s.n, F)
                    if not np.array_equal(nf[:, [FEATURE_COLUMNS.index(c) for c in sd.inputs]], Xt): bad['features'] += 1
                    old_sc = [float(x) for x in R.Phi_score(tr, theta, Xt)]          # original offline scorer
                    seq_sc = sequential(tr, theta, Xt)
                    old_sel, old_tied = E.select(old_sc, s.original)
                    new_sel, new_tied = E.select(seq_sc, s.original)
                    if n['linear']['scored']:
                        if n['linear']['scores'] != seq_sc: bad['native_vs_sequential_scores'] += 1
                        if cands.index(n['linear']['chosen']) != new_sel or n['linear']['tied'] != new_tied: bad['native_vs_sequential_selection'] += 1
                    else:
                        if s.n >= 2 or cands.index(n['linear']['chosen']) != new_sel: bad['native_unscored'] += 1
                    eo = E.evaluate_state(s, old_sel); eo['tied_at_max'] = old_tied
                    en = E.evaluate_state(s, new_sel); en['tied_at_max'] = new_tied
                    old_ev.append(eo); new_ev.append(en)
                    rec_ = dict(state_id=s.state_id, graph_id=s.graph_id, fold=k, sample_kind=s.sample_kind, candidates=s.n, original=s.original,
                                old_selected=old_sel, new_selected=new_sel, old_tied=old_tied, new_tied=new_tied,
                                old_numpy_max_minus_new_max=max(old_sc) - max(seq_sc),
                                max_abs_numpy_vs_deployed=max(abs(x - y) for x, y in zip(old_sc, seq_sc)),
                                complete_compatible=eo['complete_compatible'], old_nodes=eo['selected_nodes'], new_nodes=en['selected_nodes'],
                                old_cost=eo['selection_cost'], new_cost=en['selection_cost'], old_outcome=eo['outcome'], new_outcome=en['outcome'],
                                old_comparable=eo['comparable'], new_comparable=en['comparable'])
                    if old_sel != new_sel:
                        rec_['identical_feature_rows'] = bool(np.array_equal(Xt[old_sel], Xt[new_sel]))
                        rec_['old_selected_in_deployed_maxima'] = seq_sc[old_sel] == max(seq_sc)
                        rec_['valid_old'] = s.valid[old_sel]; rec_['valid_new'] = s.valid[new_sel]
                        rec_['same_key'] = s.valid[old_sel] and s.valid[new_sel] and s.key[old_sel] == s.key[new_sel] and not s.excluded
                    per_state.append(rec_)
                check(f'{solver}:{cid}:fold{k}:deployed_scorer_agreement', not bad, dict(bad))
            valid = all(st_ok)
            old_sum = E.summarise(old_ev); new_sum = E.summarise(new_ev)
            arch = next(r for r in selection[f'{solver}/linear']['all'] if r['config']['id'] == cid)
            check(f'{solver}:{cid}:old_summary_reproduces_archive', old_sum == arch['summary'] and valid == arch['valid'],
                  {kk: (old_sum.get(kk), arch['summary'].get(kk)) for kk in arch['summary'] if old_sum.get(kk) != arch['summary'].get(kk)})
            for k in range(5):
                ok_k = E.summarise([e for e, p in zip(old_ev, per_state) if p['fold'] == k])
                ak = {kk: v for kk, v in arch['per_fold'][str(k)].items() if kk in ok_k}
                check(f'{solver}:{cid}:fold{k}:old_fold_summary_reproduces_archive', ok_k == ak)
            if cid == selection[f'{solver}/linear']['selected']['id']:
                archived = {}
                with gzip.open(run / f'report/selected_states_{solver}_linear.jsonl.gz', 'rt', encoding='utf-8') as f:
                    for l in f:
                        e = json.loads(l); archived[e['state_id']] = e
                # every field exact, except selection_cost = math.log(...), where the platform libm (ubuntu glibc
                # in training, Windows UCRT here) may differ in the last bit: allowed within 1 ulp and counted
                diff, ulp = 0, []
                for e in old_ev:
                    a_ = archived.get(e['state_id'])
                    if a_ == e:
                        continue
                    ks = {f for f in set(a_ or {}) | set(e) if (a_ or {}).get(f) != e.get(f)}
                    if a_ is not None and ks == {'selection_cost'} and abs(a_['selection_cost'] - e['selection_cost']) <= math.ulp(e['selection_cost']):
                        ulp.append(dict(state_id=e['state_id'], archived=a_['selection_cost'], rebuilt=e['selection_cost']))
                    else:
                        diff += 1
                check(f'{solver}:{cid}:old_per_state_reproduces_archived_selected_states', diff == 0 and len(archived) == len(old_ev),
                      dict(differing=diff, archived=len(archived), rebuilt=len(old_ev), selection_cost_last_bit_only=ulp))
            ch = [p for p in per_state if p['old_selected'] != p['new_selected']]
            for p in ch:
                changes_out.write(json.dumps(dict(p, solver=solver, config=cid), sort_keys=True) + '\n')
            sres['configs'][cid] = dict(valid=valid, lam=lam, old=old_sum, corrected=new_sum, changed=tally(ch, per_state),
                                        old_metric=old_sum['selection_metric'], corrected_metric=new_sum['selection_metric'])
            print(solver, cid, 'changed', len(ch), 'old', old_sum['selection_metric'], 'new', new_sum['selection_metric'], flush=True)
        # selection rule, unchanged, applied to the old and to the corrected metrics
        rows_old = [dict(config=dict(id=c, **{'lambda': v['lam']}), valid=v['valid'], metric=v['old_metric']) for c, v in sres['configs'].items()]
        rows_new = [dict(config=dict(id=c, **{'lambda': v['lam']}), valid=v['valid'], metric=v['corrected_metric']) for c, v in sres['configs'].items()]
        bo, bn = E.choose('linear', rows_old), E.choose('linear', rows_new)
        frozen_id = selection[f'{solver}/linear']['selected']['id']
        check(f'{solver}:old_choice_reproduces_archive', bo['config']['id'] == frozen_id)
        rank = lambda rows: [r['config']['id'] for r in sorted(rows, key=lambda r: (r['metric'], -r['config']['lambda']))]
        sres.update(frozen_config=frozen_id, old_choice=bo['config']['id'], corrected_choice=bn['config']['id'],
                    choice_would_change=bo['config']['id'] != bn['config']['id'], old_ranking=rank(rows_old), corrected_ranking=rank(rows_new),
                    corrected_margin_to_runner_up=sorted(r['metric'] for r in rows_new)[1] - sorted(r['metric'] for r in rows_new)[0],
                    old_margin_to_runner_up=sorted(r['metric'] for r in rows_old)[1] - sorted(r['metric'] for r in rows_old)[0])
        results['solvers'][solver] = sres
    changes_out.close()
    import numpy, scipy
    results.update(checks=checks, all_checks_pass=not fail, failed_checks=fail, wall_s=time.time() - t0,
                   environment=dict(python=sys.version, platform=platform.platform(), numpy=numpy.__version__, scipy=scipy.__version__,
                                    blas=numpy.show_config(mode='dicts')['Build Dependencies']['blas'],
                                    threads={k: os.environ.get(k) for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_CORETYPE')}))
    jdump(out / 'results.json', results)
    print('ALL CHECKS PASS' if not fail else f'{len(fail)} CHECKS FAILED: {fail[:10]}', flush=True)
    return 0 if not fail else 1


def tally(ch, per_state):
    """Changed selections and what they did to the observed node total of the selected candidate."""
    t = collections.Counter()
    for p in ch:
        t['changed'] += 1
        t['changed_identical_feature_rows'] += p['identical_feature_rows']
        t['changed_old_pick_still_a_deployed_maximum'] += p['old_selected_in_deployed_maxima']
        if p['complete_compatible']:
            t['changed_in_selection_subset'] += 1
        if p['same_key']:
            t['node_total_observable'] += 1
            if p['old_nodes'] != p['new_nodes']:
                t['node_total_changed'] += 1
                t['node_total_increased' if p['new_nodes'] > p['old_nodes'] else 'node_total_decreased'] += 1
            else:
                t['node_total_unchanged'] += 1
        else:
            t['node_total_unobservable'] += 1
            t['unobservable_' + ('both_invalid' if not (p['valid_old'] or p['valid_new']) else 'old_invalid' if not p['valid_old'] else 'new_invalid' if not p['valid_new'] else 'incompatible_or_excluded')] += 1
        t['changed_to_original'] += p['new_selected'] == p['original']
        t['changed_from_original'] += p['old_selected'] == p['original']
        t['outcome_' + p['old_outcome'] + '->' + p['new_outcome']] += 1
    d = dict(sorted(t.items()))
    d['states'] = len(per_state)
    d['sum_new_minus_old_nodes_observable'] = sum(p['new_nodes'] - p['old_nodes'] for p in ch if p['same_key'])
    d['sum_cost_change_selection_subset'] = sum(p['new_cost'] - p['old_cost'] for p in ch if p['complete_compatible'])
    d['max_abs_numpy_vs_deployed_score'] = max((p['max_abs_numpy_vs_deployed'] for p in per_state), default=0.0)
    return d


if __name__ == '__main__':
    sys.exit(main())
