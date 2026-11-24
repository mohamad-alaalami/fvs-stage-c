"""Offline learnability experiment driver.

  python -m learnability.train.run freeze  --data D --graphs G --frozen F      (local, before dispatch)
  python -m learnability.train.run prepare --data D --graphs G --frozen F --out O
  python -m learnability.train.run cv      --data D --frozen F --solver S --family {linear,boost} --out O
  python -m learnability.train.run select  --frozen F --cv-root R --out O
  python -m learnability.train.run final   --data D --frozen F --solver S --family X --selection SEL --out O
  python -m learnability.train.run report  --data D --frozen F --root R --out O
"""
import argparse
import gzip
import hashlib
import json
import os
import pathlib
import platform
import sys
import time

import numpy as np

from . import data as D
from . import evaluate as E
from . import folds as FO
from . import pairs as PA
from . import transforms as T

HERE = pathlib.Path(__file__).resolve().parent
LAMBDAS = [1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0]
BOOST_GRID = [dict(max_depth=d, rounds=r) for d in (2, 3) for r in (50, 100, 200)]


def configs(family):
    if family == 'linear':
        return [dict(id=f'lambda={l:g}', **{'lambda': l}) for l in LAMBDAS]
    return [dict(id=f'depth={c["max_depth"]},rounds={c["rounds"]}', **c) for c in BOOST_GRID]


def jdump(p, x):
    p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp'); tmp.write_text(json.dumps(x, indent=1, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8', newline='\n'); os.replace(tmp, p)


def jload(p):
    return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))


def environment():
    import scipy, xgboost
    return dict(python=sys.version, platform=platform.platform(), machine=platform.machine(), numpy=np.__version__, scipy=scipy.__version__,
                xgboost=xgboost.__version__, threads={k: os.environ.get(k) for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')},
                github=dict(run_id=os.environ.get('GITHUB_RUN_ID'), run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), sha=os.environ.get('GITHUB_SHA'),
                            job=os.environ.get('GITHUB_JOB'), runner=os.environ.get('RUNNER_NAME'), image=os.environ.get('ImageOS', '') + ' ' + os.environ.get('ImageVersion', '')))


# ------------------------------------------------------------------ shared data
class SolverData:
    def __init__(self, data_dir, frozen, solver):
        cfg = jload(pathlib.Path(frozen) / 'config.json')
        self.solver = solver; self.schema = D.load_schema(data_dir)
        self.states = D.build_states(D.load_rows(data_dir, solver, self.schema))
        folds = jload(pathlib.Path(frozen) / 'folds.json')['folds']
        self.fold_of = {s.state_index: folds[s.graph_id] for s in self.states}
        self.inputs = T.inputs_for(solver)
        assert self.inputs == cfg['inputs'][solver]
        self.X = {s.state_index: np.array(D.feature_matrix(s, self.inputs)) for s in self.states}
        self.pairs = {}; self.strict = {}; self.pinfo = {}
        for s in self.states:
            p, tot, info = PA.state_pairs(s)
            self.pairs[s.state_index] = p; self.strict[s.state_index] = tot; self.pinfo[s.state_index] = info
        self.by_index = {s.state_index: s for s in self.states}
        self.graph_of = {s.state_index: s.graph_id for s in self.states}

    def pair_array(self):
        rows = [(si, b, w) for si in sorted(self.pairs) for b, w in self.pairs[si]]
        return np.array(rows, dtype='<i4').reshape(-1, 3)


def pair_hash(arr):
    return hashlib.sha256(np.ascontiguousarray(arr, dtype='<i4').tobytes()).hexdigest()


def training_set(sd, train_idx, columns):
    """Concatenate training candidate rows; build pair index arrays and weights."""
    tp = {si: sd.pairs[si] for si in train_idx}
    wmap, G = PA.pair_weights(tp, sd.graph_of)
    offs = {}; Xs = []; n = 0
    for si in train_idx:
        offs[si] = n; Xs.append(sd.X[si][:, [sd.inputs.index(c) for c in columns]]); n += sd.by_index[si].n
    X = np.concatenate(Xs) if Xs else np.zeros((0, len(columns)))
    b, w, wt = [], [], []
    for si in train_idx:
        for bb, ww in tp[si]:
            b.append(offs[si] + bb); w.append(offs[si] + ww); wt.append(wmap[si])
    info = dict(train_states=len(train_idx), informative_states=len(wmap), contributing_graphs=G, retained_pairs=len(b),
                weight_sum=float(np.sum(wt)) if wt else 0.0, candidate_rows=int(n))
    return X, np.array(b, dtype=np.int64), np.array(w, dtype=np.int64), np.array(wt, dtype=np.float64), offs, info


def fit_and_score(sd, family, cfg, train_idx, test_idx, columns, model_dir):
    """Fit one model; score every candidate of every test state. Returns (status, evals, scores)."""
    from . import linear as L, boost as B
    t0 = time.perf_counter(); c0 = time.process_time()
    X, b, w, wt, offs, info = training_set(sd, train_idx, columns)
    status = dict(family=family, config=cfg, columns=columns, **info)
    if len(b) == 0:
        status.update(ok=False, failure='no training pairs'); return status, [], {}
    if family == 'linear':
        tr = T.LinearTransform(columns).fit(X)          # training rows only
        Phi = tr.transform(X)
        theta, conv = L.fit(Phi, b, w, wt, cfg['lambda'])
        s_tr = Phi @ theta
        status.update(convergence=conv, train_loss_unregularised=float(np.sum(wt * np.logaddexp(0.0, -(s_tr[b] - s_tr[w])))))
        model = dict(format='fvs-pairwise-linear-v1', solver=sd.solver, family='linear', config=cfg, transform=tr.export(),
                     theta=[float(x) for x in theta], score='s = sum(theta[j] * phi[j])', provenance='see fit_status.json')
        jdump(model_dir / 'model.json', model)
        back = jload(model_dir / 'model.json'); tr2 = T.LinearTransform.from_export(back['transform']); th2 = np.array(back['theta'])
        scorer = lambda Xt: Phi_score(tr, theta, Xt); scorer2 = lambda Xt: Phi_score(tr2, th2, Xt)
        ok = conv['converged']
        if not ok:
            status['failure'] = 'linear optimiser did not meet the convergence rule'
    else:
        used = np.unique(np.concatenate([b, w])); remap = -np.ones(len(X), dtype=np.int64); remap[used] = np.arange(len(used))
        booster, meta = B.fit(X[used], remap[b], remap[w], wt, cfg['max_depth'], cfg['rounds'])
        status.update(boost=meta, rows_in_dmatrix=int(len(used)), train_loss_unregularised=meta['train_loss'])
        model_dir.mkdir(parents=True, exist_ok=True); booster.save_model(str(model_dir / 'model.json'))
        jdump(model_dir / 'model_meta.json', dict(format='xgboost-json-margin', solver=sd.solver, family='boost', config=cfg, input_order=columns,
                                                  score='booster.predict(DMatrix(raw inputs in input_order), output_margin=True)', base_score=0.0))
        b2 = B.load(model_dir / 'model.json')
        scorer = lambda Xt: B.score(booster, Xt); scorer2 = lambda Xt: B.score(b2, Xt)
        ok = meta['finite']
        if not ok:
            status['failure'] = 'non-finite training margins'
    evals, scores, maxdiff = [], {}, 0.0
    for si in test_idx:
        s = sd.by_index[si]; Xt = sd.X[si][:, [sd.inputs.index(c) for c in columns]]
        sc = scorer(Xt); sc2 = scorer2(Xt); maxdiff = max(maxdiff, float(np.max(np.abs(sc - sc2))) if len(sc) else 0.0)
        try:
            sel, ntied = E.select([float(x) for x in sc], s.original)
        except E.ScoreError:
            status.update(ok=False, failure=f'non-finite score at {s.state_id}'); return status, [], {}
        e = E.evaluate_state(s, sel); e['tied_at_max'] = ntied; evals.append(e); scores[s.state_id] = [float(x) for x in sc]
    status['export_roundtrip_max_abs_diff'] = maxdiff
    if maxdiff > 1e-6:
        ok = False; status['failure'] = f'exported model scores differ by {maxdiff}'
    status.update(ok=bool(ok), wall_s=time.perf_counter() - t0, cpu_s=time.process_time() - c0, test_states=len(test_idx))
    return status, evals, scores


def Phi_score(tr, theta, Xt):
    return tr.transform(Xt) @ theta


def write_fit(out, status, evals, scores):
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / 'evals.jsonl.gz', 'wt', encoding='utf-8', newline='\n') as f:
        for e in evals:
            f.write(json.dumps(e, sort_keys=True) + '\n')
    with gzip.open(out / 'scores.jsonl.gz', 'wt', encoding='utf-8', newline='\n') as f:
        for k in sorted(scores):
            f.write(json.dumps(dict(state_id=k, scores=scores[k])) + '\n')
    jdump(out / 'fit_status.json', status); jdump(out / 'done.json', dict(ok=status['ok']))


def read_evals(p):
    with gzip.open(p, 'rt', encoding='utf-8') as f:
        return [json.loads(l) for l in f]


# ------------------------------------------------------------------ commands
def cmd_freeze(a):
    frozen = pathlib.Path(a.frozen); frozen.mkdir(parents=True, exist_ok=True)
    manifest, checked = D.verify_extraction(a.data, a.extraction_id)
    schema = D.load_schema(a.data)
    gids = sorted(r['filename'][:-6] for r in _public_inventory(a.inventory))
    folds = FO.build_manifest(a.graphs, gids, a.upstream_commit)
    jdump(frozen / 'folds.json', folds)
    pm = {}
    for s in D.SOLVERS:
        rows = D.load_rows(a.data, s, schema); states = D.build_states(rows)
        arr = []; strict = 0; sampled = 0; inf = 0
        for st in states:
            p, tot, info = PA.state_pairs(st); strict += tot; sampled += bool(info.get('sampled')); inf += bool(p)
            arr += [(st.state_index, b, w) for b, w in p]
        arr = np.array(arr, dtype='<i4').reshape(-1, 3)
        pm[s] = dict(retained_pairs=int(len(arr)), strict_pairs_total=int(strict), sampled_states=sampled, informative_states=inf, states=len(states), sha256=pair_hash(arr))
    jdump(frozen / 'pairs_manifest.json', dict(schema='fvs-learnability-pairs-v1', seed=PA.SEED, cap=PA.CAP, rule=PA.__doc__.strip(), per_solver=pm))
    cfg = dict(experiment='fvs-learnability-offline-v1', extraction_id=a.extraction_id, extraction_hashes=checked,
               extraction_manifest_sha256=D.sha256_bytes(D.read_member(a.data, 'manifest.json')), upstream_commit=a.upstream_commit,
               stage_c_run='44639720515', stage_d_run='45059940845', stage_d_experiment_commit='4cf65df9de3af1aacbece3820e2986c0fd2b5620',
               inputs={s: T.inputs_for(s) for s in D.SOLVERS}, ablation_inputs={s: T.inputs_for(s, True) for s in D.SOLVERS},
               ablation_removed=list(T.ABLATION_REMOVED), linear_lambdas=LAMBDAS, boost_grid=BOOST_GRID,
               boost_frozen_params=__import__('learnability.train.boost', fromlist=['x']).FROZEN_PARAMS,
               linear_optimizer=dict(method='L-BFGS-B', **__import__('learnability.train.linear', fromlist=['x']).OPTIONS, grad_inf_norm_tol=1e-6),
               folds_sha256=folds['manifest_sha256'], pairs_sha256={s: pm[s]['sha256'] for s in pm}, bootstrap=dict(resamples=2000, seed=20261124),
               scheduled_fits=dict(main_cv=180, final_refits=6, ablation=30, total=216),
               dependency_pins=(HERE / 'requirements.txt').read_text().split())
    jdump(frozen / 'config.json', cfg)
    print(json.dumps(dict(folds=folds['fold_sizes'], groups=len(folds['groups']), matches=folds['matches'], pairs=pm), indent=1))


def _public_inventory(path):
    import csv
    with open(path, encoding='utf-8', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['subset'] == 'pace-16open']   # reserved rows discarded unread beyond the subset field
    assert len(rows) == 100
    return rows


def cmd_prepare(a):
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True); frozen = pathlib.Path(a.frozen); cfg = jload(frozen / 'config.json')
    manifest, checked = D.verify_extraction(a.data, cfg['extraction_id'])
    assert checked == cfg['extraction_hashes'], 'extraction hashes differ from the frozen config'
    folds = jload(frozen / 'folds.json'); res = dict(extraction=checked)
    if a.graphs:
        gids = sorted(folds['folds']); again = FO.build_manifest(a.graphs, gids, cfg['upstream_commit'])
        res['folds_recomputed_equal'] = again['manifest_sha256'] == folds['manifest_sha256'] == cfg['folds_sha256'] and again['graph_audit'] == folds['graph_audit']
        assert res['folds_recomputed_equal'], 'fold manifest does not reproduce'
    cov = {}
    for s in D.SOLVERS:
        sd = SolverData(a.data, frozen, s); arr = sd.pair_array(); h = pair_hash(arr)
        assert h == cfg['pairs_sha256'][s], f'pairs for {s} do not reproduce'
        np.savez_compressed(out / f'pairs_{s}.npz', pairs=arr)
        cov[s] = coverage(sd, folds)
    res.update(pairs_reproduced=True, pairs_sha256=cfg['pairs_sha256'], coverage=cov, environment=environment())
    jdump(out / 'prepare.json', res); print(json.dumps({s: {k: v for k, v in c.items() if not isinstance(v, (dict, list))} for s, c in cov.items()}, indent=1))


def coverage(sd, folds):
    st = sd.states; c = {}
    c['graphs_in_manifest'] = len(folds['folds']); c['graphs_with_states'] = len({s.graph_id for s in st})
    c['states'] = len(st); c['candidates'] = sum(s.n for s in st)
    c['valid_candidates'] = sum(sum(s.valid) for s in st)
    c['states_excluded'] = sum(s.excluded for s in st)
    c['states_entirely_censored'] = sum(s.censoring() == 'entirely_censored' for s in st)
    c['states_partially_censored'] = sum(s.censoring() == 'partially_censored' for s in st)
    c['states_env_incompatible_valid_candidates'] = sum(len(s.valid_groups()) > 1 for s in st)
    c['states_lt2_valid'] = sum(sum(s.valid) < 2 for s in st)
    c['states_all_tie'] = sum(sum(s.valid) >= 2 and sd.strict[s.state_index] == 0 for s in st)
    c['states_informative'] = sum(bool(sd.pairs[s.state_index]) for s in st)
    c['states_sampled_pairs'] = sum(bool(sd.pinfo[s.state_index].get('sampled')) for s in st)
    c['strict_pairs_total'] = sum(sd.strict.values()); c['retained_pairs'] = sum(len(p) for p in sd.pairs.values())
    c['selection_subset_states'] = sum(s.complete_compatible() for s in st)
    c['selection_subset_graphs'] = len({s.graph_id for s in st if s.complete_compatible()})
    c['sample_kind_states'] = {k: sum(s.sample_kind == k for s in st) for k in ('first_A', 'reservoir')}
    c['sample_kind_selection_subset'] = {k: sum(s.sample_kind == k and s.complete_compatible() for s in st) for k in ('first_A', 'reservoir')}
    infg = {s.graph_id for s in st if sd.pairs[s.state_index]}
    c['graphs_without_informative_states'] = sorted({s.graph_id for s in st} - infg)
    c['per_fold'] = {}
    for k in range(5):
        tr = [s.state_index for s in st if sd.fold_of[s.state_index] != k]
        _, _, _, _, _, info = training_set(sd, tr, sd.inputs)
        c['per_fold'][str(k)] = dict(info, heldout_states=sum(sd.fold_of[s.state_index] == k for s in st),
                                    heldout_subset_states=sum(sd.fold_of[s.state_index] == k and s.complete_compatible() for s in st))
    c['per_graph'] = {g: dict(states=sum(s.graph_id == g for s in st), informative=sum(s.graph_id == g and bool(sd.pairs[s.state_index]) for s in st),
                              subset=sum(s.graph_id == g and s.complete_compatible() for s in st), fold=folds['folds'][g]) for g in sorted({s.graph_id for s in st})}
    return c


def cmd_cv(a):
    out = pathlib.Path(a.out); sd = SolverData(a.data, a.frozen, a.solver); summary = []
    cfgf = jload(pathlib.Path(a.frozen) / 'config.json')
    assert pair_hash(sd.pair_array()) == cfgf['pairs_sha256'][a.solver], 'pairs differ from the frozen manifest'
    assert D.verify_extraction(a.data, cfgf['extraction_id'])[1] == cfgf['extraction_hashes']
    for cfg in configs(a.family):
        cdir = out / a.solver / a.family / cfg['id']
        for k in range(5):
            fdir = cdir / f'fold{k}'
            if (fdir / 'done.json').exists() and jload(fdir / 'done.json')['ok']:
                print('skip (done)', a.solver, a.family, cfg['id'], k, flush=True); continue
            train = [s.state_index for s in sd.states if sd.fold_of[s.state_index] != k]
            test = [s.state_index for s in sd.states if sd.fold_of[s.state_index] == k]
            status, evals, scores = fit_and_score(sd, a.family, cfg, train, test, sd.inputs, fdir)
            status.update(fold=k, solver=a.solver, environment=environment()); write_fit(fdir, status, evals, scores)
            print('FIT', a.solver, a.family, cfg['id'], 'fold', k, 'ok' if status['ok'] else 'FAILED ' + status.get('failure', ''), round(status.get('wall_s', 0), 1), 's', flush=True)
            summary.append(dict(config=cfg['id'], fold=k, ok=status['ok']))
    jdump(out / a.solver / a.family / 'cv_done.json', dict(fits=summary))


def config_result(cdir, folds_n=5):
    st = [jload(cdir / f'fold{k}' / 'fit_status.json') for k in range(folds_n)]
    evals = [e for k in range(folds_n) for e in read_evals(cdir / f'fold{k}' / 'evals.jsonl.gz')]
    valid = all(s['ok'] for s in st)
    summ = E.summarise(evals); metric = summ['selection_metric'] if valid else None
    per_fold = {}
    for k in range(folds_n):
        ek = [e for e in read_evals(cdir / f'fold{k}' / 'evals.jsonl.gz')]
        per_fold[str(k)] = dict(E.summarise(ek), ok=st[k]['ok'], wall_s=st[k].get('wall_s'), cpu_s=st[k].get('cpu_s'), failure=st[k].get('failure'),
                                convergence=st[k].get('convergence'), retained_pairs=st[k].get('retained_pairs'), contributing_graphs=st[k].get('contributing_graphs'))
    return dict(valid=valid, metric=metric, summary=summ, per_fold=per_fold, per_graph=E.graph_aggregate(evals)[1]), evals


def cmd_select(a):
    root = pathlib.Path(a.cv_root); out = pathlib.Path(a.out); sel = {}
    for s in D.SOLVERS:
        for fam in ('linear', 'boost'):
            res = []
            for cfg in configs(fam):
                r, _ = config_result(root / s / fam / cfg['id']); r['config'] = cfg; res.append(r)
            best = E.choose(fam, res)
            sel[f'{s}/{fam}'] = dict(selected=best['config'] if best else None, selected_metric=best['metric'] if best else None,
                                     all=[dict(config=r['config'], valid=r['valid'], metric=r['metric'], summary=r['summary'], per_fold=r['per_fold']) for r in res],
                                     rule='lowest graph-aggregated mean log((1+selected)/(1+original)) on the fixed complete-compatible subset; ties: ' +
                                          ('larger lambda' if fam == 'linear' else 'fewer rounds, then smaller depth'))
    jdump(out / 'selection.json', sel); print(json.dumps({k: (v['selected'], v['selected_metric']) for k, v in sel.items()}, indent=1))


def cmd_final(a):
    out = pathlib.Path(a.out); sd = SolverData(a.data, a.frozen, a.solver); sel = jload(a.selection)[f'{a.solver}/{a.family}']
    assert pair_hash(sd.pair_array()) == jload(pathlib.Path(a.frozen) / 'config.json')['pairs_sha256'][a.solver], 'pairs differ from the frozen manifest'
    cfg = sel['selected']
    if cfg is None:
        jdump(out / a.solver / a.family / 'final_skipped.json', dict(reason='no valid configuration to refit')); return
    allidx = [s.state_index for s in sd.states]
    fdir = out / a.solver / a.family / 'final'
    if not ((fdir / 'done.json').exists() and jload(fdir / 'done.json')['ok']):
        status, _, _ = fit_and_score(sd, a.family, cfg, allidx, [], sd.inputs, fdir)
        status.update(kind='final_refit_all_public', solver=a.solver, environment=environment()); write_fit(fdir, status, [], {})
        print('FINAL', a.solver, a.family, cfg['id'], 'ok' if status['ok'] else 'FAILED', flush=True)
    cols = T.inputs_for(a.solver, ablation=True)
    for k in range(5):
        adir = out / a.solver / a.family / 'ablation' / f'fold{k}'
        if (adir / 'done.json').exists() and jload(adir / 'done.json')['ok']:
            continue
        train = [s.state_index for s in sd.states if sd.fold_of[s.state_index] != k]
        test = [s.state_index for s in sd.states if sd.fold_of[s.state_index] == k]
        status, evals, scores = fit_and_score(sd, a.family, cfg, train, test, cols, adir)
        status.update(kind='ablation', fold=k, solver=a.solver, environment=environment()); write_fit(adir, status, evals, scores)
        print('ABLATION', a.solver, a.family, cfg['id'], 'fold', k, 'ok' if status['ok'] else 'FAILED', flush=True)


def cmd_report(a):
    from .report import write_report
    write_report(pathlib.Path(a.root), pathlib.Path(a.out), pathlib.Path(a.frozen))


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('freeze'); [p.add_argument(x, required=True) for x in ('--data', '--graphs', '--frozen', '--inventory', '--extraction-id', '--upstream-commit')]
    p = sub.add_parser('prepare'); [p.add_argument(x, required=True) for x in ('--data', '--frozen', '--out')]; p.add_argument('--graphs')
    p = sub.add_parser('cv'); [p.add_argument(x, required=True) for x in ('--data', '--frozen', '--solver', '--family', '--out')]
    p = sub.add_parser('select'); [p.add_argument(x, required=True) for x in ('--frozen', '--cv-root', '--out')]
    p = sub.add_parser('final'); [p.add_argument(x, required=True) for x in ('--data', '--frozen', '--solver', '--family', '--selection', '--out')]
    p = sub.add_parser('report'); [p.add_argument(x, required=True) for x in ('--frozen', '--root', '--out')]
    a = ap.parse_args(argv)
    dict(freeze=cmd_freeze, prepare=cmd_prepare, cv=cmd_cv, select=cmd_select, final=cmd_final, report=cmd_report)[a.cmd](a)


if __name__ == '__main__':
    main()
