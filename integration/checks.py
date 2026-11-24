"""Public acceptance checks for integration-v1 (public data only; reserved graphs are never touched).

  baseline  integrated baseline vs the pristine pinned build (byte-identical output) and vs Stage C records
            (node count, decisions B/T/A, Stage C trace digest) on every Stage C pair that completed with
            instrumented CPU <= --max-stagec-cpu
  oracle    seeded small generated graphs (+ upstream tests/simple): every solver x policy (and seeded
            random-eligible test policies) against an independent brute-force exact optimum
  suite     fixed public correctness suite (003 included): solver x {pristine, baseline, linear, boost}
  live      diagnostic dumps of live decision states (including states reached after earlier learned
            departures and inside component subsolvers) re-scored by the independent Python reference
  overhead  timing of the pristine binary vs the integrated timed baseline (interleaved repetitions) and
            diagnostic feature/scoring timers of the learned policies, on a predefined public subset

Usage: python integration/checks.py <check> --build BUILD --upstream UPSTREAM --out DIR [options]
"""
import argparse, collections, csv, itertools, json, math, pathlib, random, statistics, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT))
import invoke  # noqa: E402

SOLVERS = ('8', '5', 'LP')
LEARNED = ('linear', 'boost')
PUBLIC = 'tests/pace-16open'
# Fixed before any integration result was seen: public graphs on which Stage C completed all three solvers quickly,
# plus 003 (optimum 10) and medium cases with many studied decisions.
SUITE = ['003', '095', '020', '065', '083', '042', '050', '099', '096', '062', '028', '072', '015', '098', '030', '024', '006',
         '007', '059', '077', '085', '044', '005', '009', '046', '041', '019', '045', '057', '049', '031', '002', '070', '091']
OVERHEAD = [('011', '8'), ('092', '8'), ('092', '5'), ('011', '5'), ('011', 'LP'), ('092', 'LP')]
LIVE = [('044', s) for s in SOLVERS] + [('005', s) for s in SOLVERS] + [('009', s) for s in SOLVERS] + [('046', s) for s in SOLVERS]


def opt_of(upstream, gid):
    p = pathlib.Path(upstream) / PUBLIC / f'{gid}.opt'
    return int(p.read_text().split()[0]) if p.exists() else None


def write(out, name, obj):
    (out / name).write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n', encoding='utf-8')


# ------------------------------------------------------------------------------------------- baseline
def check_baseline(a, build, out):
    rows = list(csv.DictReader(open(pathlib.Path(a.stagec_report) / 'results.csv', encoding='utf-8')))
    cases = [r for r in rows if r['baseline_status'] == 'completed' and r['instrumented_status'] == 'completed'
             and float(r['instrumented_cpu_s']) <= a.max_stagec_cpu]
    cases.sort(key=lambda r: (r['solver'], r['graph']))
    results = []; ok_all = True
    for r in cases:
        gid, s = r['graph'], r['solver']
        g = pathlib.Path(a.upstream) / PUBLIC / f'{gid}.graph'
        summ_path = next((pathlib.Path(a.stagec_pairs) / f'{gid}-{s}/attempt-1/invocations').glob('*-instrumented/summary.json'))
        sc = json.loads(summ_path.read_text())
        sc_nodes = sum(v['entered_main'] + v['entered_component'] for v in sc['nodes'].values() if isinstance(v, dict) and 'entered_main' in v)
        ref = opt_of(a.upstream, gid)
        lim = max(60.0, 20 * float(r['instrumented_cpu_s']))
        pr = invoke.run(build, s, 'pristine', g, out / 'runs', lim, 3 * lim + 120, graph_id=gid, reference=ref)
        tb = invoke.run(build, s, 'baseline', g, out / 'runs', lim, 3 * lim + 120, graph_id=gid, reference=ref)
        db = invoke.run(build, s, 'baseline', g, out / 'runs', lim, 3 * lim + 120, graph_id=gid, reference=ref, diag=True)
        ts, ds = tb.get('summary') or {}, db.get('summary') or {}
        chk = dict(
            pristine_completed=pr['status'] == 'completed', timed_completed=tb['status'] == 'completed', diag_completed=db['status'] == 'completed',
            output_identical_to_pristine=pr['stdout_sha256'] == tb['stdout_sha256'] == db['stdout_sha256'],
            size_matches_stagec_baseline=str((tb.get('verification') or {}).get('returned_size')) == r['baseline_size'],
            size_matches_opt=(ref is None) or (tb.get('verification') or {}).get('returned_size') == ref,
            feasible=bool((tb.get('verification') or {}).get('feasible')),
            nodes_equal_stagec=(ts.get('nodes') or {}).get('total') == sc_nodes == (ds.get('nodes') or {}).get('total'),
            decisions_equal_stagec=ts.get('decisions') == sc['B'] == ds.get('decisions'),
            target_equal_stagec=ts.get('target_decisions') == sc['T'] == ds.get('target_decisions'),
            eligible_equal_stagec=ds.get('eligible_decisions') == sc['A'],
            stagec_trace_digest_equal=ds.get('stagec_trace_digest') == sc['trace_digest'],
            pivot_trace_identical_timed_vs_diag=ts.get('pivot_trace_digest') == ds.get('pivot_trace_digest'),
            timed_baseline_enumerated_nothing=ts.get('eligible_decisions') is None and ts.get('scored_decisions') == 0 and ts.get('model') is None,
            original_pivot_always_eligible=ds.get('diag_original_pivot_not_eligible') == 0)
        ok = all(chk.values()); ok_all &= ok
        results.append(dict(graph=gid, solver=s, ok=ok, checks=chk, opt=ref, stagec=dict(B=sc['B'], T=sc['T'], A=sc['A'], nodes=sc_nodes, digest=sc['trace_digest']),
                            timed=invoke.flat(tb), diag=invoke.flat(db), pristine=invoke.flat(pr),
                            cpu=dict(pristine=pr['cpu_s'], timed=tb['cpu_s'], diag=db['cpu_s'])))
        print('baseline', gid, s, 'ok' if ok else 'FAIL ' + str([k for k, v in chk.items() if not v]), flush=True)
    by = collections.Counter(r['solver'] for r in results)
    rep = dict(check='baseline_equivalence', pass_=ok_all and len(results) > 0, cases=len(results), cases_by_solver=dict(by),
               selection=f'Stage C pairs with both runs completed and instrumented CPU <= {a.max_stagec_cpu} s', results=results)
    write(out, 'baseline_report.json', rep); return rep


# ------------------------------------------------------------------------------------------- oracle
def gen_graphs(seed, per_type):
    rnd = random.Random(seed); graphs = []
    def emit(kind, n, edges):
        labels = list(range(1, n + 1)); rnd.shuffle(labels)
        es = [(labels[u], labels[v]) for u, v in edges]
        rnd.shuffle(es)
        graphs.append((f'{kind}-{len(graphs):03d}', n, es))
    def gnp(n, p, off=0):
        return [(u + off, v + off) for u, v in itertools.combinations(range(n), 2) if rnd.random() < p]
    for _ in range(per_type):
        n = rnd.randint(6, 16); emit('gnp', n, gnp(n, rnd.uniform(0.25, 0.6)))
    for _ in range(per_type):
        n = rnd.randint(6, 15); e = gnp(n, rnd.uniform(0.25, 0.5)); e += [x for x in e if rnd.random() < 0.2]; emit('multi', n, e)
    for _ in range(per_type):
        k = rnd.randint(2, 3); sizes = [rnd.randint(5, 7) for _ in range(k)]; e = []; off = 0; starts = []
        for sz in sizes:
            starts.append(off); e += gnp(sz, rnd.uniform(0.55, 0.8), off); off += sz
        for i in range(k - 1):
            e.append((starts[i] + rnd.randrange(sizes[i]), starts[i + 1] + rnd.randrange(sizes[i + 1])))
        emit('blocks', off, e)
    for _ in range(per_type):
        n = rnd.randint(10, 14); emit('dense', n, gnp(n, rnd.uniform(0.6, 0.8)))
    return graphs


def brute_force(n, edges, names):
    """Minimum FVS of a multigraph (a repeated edge is a 2-cycle) by increasing-size exhaustive search."""
    idx = {v: i for i, v in enumerate(names)}; E = [(idx[u], idx[v]) for u, v in edges]
    def acyclic(removed):
        parent = list(range(n))
        def f(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        for u, v in E:
            if u in removed or v in removed:
                continue
            a, b = f(u), f(v)
            if a == b:
                return False
            parent[a] = b
        return True
    for k in range(n + 1):
        for comb in itertools.combinations(range(n), k):
            if acyclic(set(comb)):
                return k
    return n


def check_oracle(a, build, out):
    gdir = out / 'graphs'; gdir.mkdir(parents=True)
    cases = []
    for gid, n, es in gen_graphs(a.seed, a.per_type):
        p = gdir / f'{gid}.graph'; p.write_text(''.join(f'{u} {v}\n' for u, v in es))
        names = sorted({str(x) for e in es for x in e}); cases.append((gid, p, brute_force(len(names), [(str(u), str(v)) for u, v in es], names)))
    simple = sorted((pathlib.Path(a.upstream) / 'tests/simple').glob('*.graph'))
    for p in simple:
        vs, es = invoke.read_graph(p); names = sorted(vs)
        bf = brute_force(len(names), es, names) if len(names) <= 18 else None
        opt = p.with_suffix('.opt'); ref = int(opt.read_text().split()[0]) if opt.exists() else None
        if bf is not None and ref is not None and bf != ref:
            raise SystemExit(f'oracle disagrees with upstream .opt on {p.name}: {bf} vs {ref}')
        if bf is not None or ref is not None:
            cases.append(('simple-' + p.stem, p, bf if bf is not None else ref))
    policies = ['pristine', 'baseline', 'linear', 'boost'] + [f'random-test:{s}' for s in a.random_seeds]
    agg = collections.defaultdict(collections.Counter); fails = []
    for gid, p, opt in cases:
        for s in SOLVERS:
            for pol in policies:
                r = invoke.run(build, s, pol, p, out / 'runs', 60.0, 300.0, graph_id=gid, reference=opt)
                f = invoke.flat(r); key = f'{s}/{pol}'
                c = agg[key]; c['runs'] += 1
                good = r['status'] == 'completed' and f['feasible'] and f['size'] == opt
                c['correct'] += good
                summ = r.get('summary') or {}
                for k in ('scored_decisions', 'departures', 'scored_in_component_subsolvers', 'scored_after_first_departure'):
                    c[k] += int(summ.get(k) or 0)
                c['component_nodes'] += sum(v.get('component', 0) for k2, v in (summ.get('nodes') or {}).items() if isinstance(v, dict))
                if not good:
                    fails.append(dict(graph=gid, solver=s, policy=pol, status=r['status'], size=f['size'], opt=opt, dir=r['_dir']))
                else:
                    import shutil; shutil.rmtree(r['_dir'])
        print('oracle', gid, 'fails so far', len(fails), flush=True)
    learned_exercised = {k: v['scored_decisions'] > 0 and v['departures'] > 0 for k, v in agg.items() if k.split('/')[1] != 'pristine' and k.split('/')[1] != 'baseline'}
    rep = dict(check='exact_oracle', pass_=not fails and all(learned_exercised.values()), graphs=len(cases), generated=len(cases) - sum(1 for c in cases if c[0].startswith('simple-')),
               seed=a.seed, policies=policies, per_solver_policy=dict((k, dict(v)) for k, v in sorted(agg.items())), learned_policies_exercised=learned_exercised,
               failures=fails[:200], oracle='brute force over vertex subsets of increasing size; a repeated edge counts as a 2-cycle; cross-checked against tests/simple .opt')
    write(out, 'oracle_report.json', rep); return rep


# ------------------------------------------------------------------------------------------- suite
def check_suite(a, build, out):
    results = []; agg = collections.defaultdict(collections.Counter); ok_all = True
    for gid in SUITE:
        g = pathlib.Path(a.upstream) / PUBLIC / f'{gid}.graph'; ref = opt_of(a.upstream, gid)
        for s in SOLVERS:
            recs = {pol: invoke.run(build, s, pol, g, out / 'runs', a.cpu_limit, a.cpu_limit * 1.25 + 120, graph_id=gid, reference=ref)
                    for pol in ('pristine', 'baseline', 'linear', 'boost')}
            trusted = ref if ref is not None else ((recs['pristine'].get('verification') or {}).get('returned_size') if recs['pristine']['status'] == 'completed' else None)
            row = dict(graph=gid, solver=s, opt_file=ref, trusted_optimum=trusted, trusted_source='opt file' if ref is not None else ('pristine pinned solver' if trusted is not None else None))
            for pol, r in recs.items():
                f = invoke.flat(r); row[pol] = f
                c = agg[f'{s}/{pol}']; c['runs'] += 1; c[r['status']] += 1
                summ = r.get('summary') or {}
                for k in ('scored_decisions', 'departures', 'scored_in_component_subsolvers', 'scored_after_first_departure'):
                    c[k] += int(summ.get(k) or 0)
                if r['status'] == 'completed':
                    good = f['feasible'] and trusted is not None and f['size'] == trusted
                    c['correct'] += good
                    if not good:
                        ok_all = False; row.setdefault('failures', []).append(pol)
                elif r['status'] in ('cpu_timeout', 'cpu_timeout_forced'):
                    row.setdefault('not_completed_within_suite_budget', []).append(pol)
                    if pol in ('pristine', 'baseline'):
                        ok_all = False; row.setdefault('failures', []).append(pol)
                else:
                    ok_all = False; row.setdefault('failures', []).append(pol)
            row['baseline_output_identical_to_pristine'] = recs['pristine']['stdout_sha256'] == recs['baseline']['stdout_sha256']
            ok_all &= row['baseline_output_identical_to_pristine']
            results.append(row)
            print('suite', gid, s, row.get('failures', 'ok'), row.get('not_completed_within_suite_budget', ''), flush=True)
    rep = dict(check='public_correctness_suite', pass_=ok_all, graphs=SUITE, cpu_limit_s=a.cpu_limit, cases=len(results),
               per_solver_policy=dict((k, dict(v)) for k, v in sorted(agg.items())), results=results,
               note='A learned run that does not finish within the suite CPU budget is a performance observation, reported but not a correctness failure; every completed run must be feasible and optimal.')
    write(out, 'suite_report.json', rep); return rep


# ------------------------------------------------------------------------------------------- live
def check_live(a, build, out):
    import numpy as np, xgboost as xgb
    from learnability.features import compute_features, FEATURE_COLUMNS
    from learnability.train import transforms as T
    from learnability.train.evaluate import select
    c = collections.Counter(); bad = []; per_run = []
    for gid, s in LIVE:
        g = pathlib.Path(a.upstream) / PUBLIC / f'{gid}.graph'
        for fam in LEARNED:
            dump = out / 'dumps' / f'{gid}-{s}-{fam}.jsonl'; dump.parent.mkdir(parents=True, exist_ok=True)
            r = invoke.run(build, s, fam, g, out / 'runs', a.cpu_limit, a.cpu_limit * 1.25 + 120, graph_id=gid, diag=True, verify=True,
                           extra_env=dict(FVSB_DUMP_STATES=str(dump), FVSB_DUMP_EVERY=str(a.dump_every), FVSB_DUMP_MAX=str(a.dump_max)), reference=opt_of(a.upstream, gid))
            m, meta = build.model(s, fam)
            mj = json.loads(m.read_text())
            if fam == 'linear':
                tr = T.LinearTransform.from_export(mj['transform']); th = np.array(mj['theta']); cols = mj['transform']['input_order']
            else:
                bst = xgb.Booster(); bst.load_model(str(m)); cols = json.loads(meta.read_text())['input_order']
            n_states = 0
            for line in dump.read_text().splitlines() if dump.exists() else []:
                d = json.loads(line); n_states += 1; c['states'] += 1
                c['after_departure'] += d['departures_before'] > 0; c['component_subsolver'] += d['component_subsolver']
                root = d['root'] if s == 'LP' else None
                cands = d['candidates']
                _, feats, _ = compute_features(s, d['status'], d['neighbours'], d['neigh_double'], d['size_cap'], d['x_size'], cands, root)
                F = len(FEATURE_COLUMNS); nf = d['features']
                for i, fr in enumerate(feats):
                    for j, col in enumerate(FEATURE_COLUMNS):
                        if col == 'f_lp_root_common_neighbors' and s != 'LP':
                            continue
                        if float(fr[col]) != nf[i * F + j]:
                            c['feature_mismatch'] += 1
                X = np.array([[float(fr[col]) for col in cols] for fr in feats], dtype=np.float64)
                if fam == 'linear':
                    Phi = tr.transform(X); ref = []
                    for i in range(len(Phi)):
                        t = 0.0
                        for j in range(len(th)):
                            t += float(th[j]) * float(Phi[i, j])
                        ref.append(t)
                else:
                    ref = [float(x) for x in bst.predict(xgb.DMatrix(X), output_margin=True).astype(np.float64)]
                if ref != d['scores']:
                    c['score_mismatch'] += 1
                pos, _ = select(ref, cands.index(d['original']))
                if cands[pos] != d['chosen']:
                    c['selection_mismatch'] += 1; bad.append(dict(graph=gid, solver=s, family=fam, decision=d['decision']))
            summ = r.get('summary') or {}
            per_run.append(dict(graph=gid, solver=s, family=fam, status=r['status'], dumped_states=n_states, scored=summ.get('scored_decisions'),
                                departures=summ.get('departures'), scored_in_component_subsolvers=summ.get('scored_in_component_subsolvers'),
                                scored_after_first_departure=summ.get('scored_after_first_departure'), feasible=(r.get('verification') or {}).get('feasible'),
                                size=(r.get('verification') or {}).get('returned_size'), diag_feature_s=summ.get('diag_feature_s'), diag_score_s=summ.get('diag_score_s')))
            print('live', gid, s, fam, n_states, dict(c), flush=True)
    ok = c['states'] > 0 and c['feature_mismatch'] == 0 and c['score_mismatch'] == 0 and c['selection_mismatch'] == 0 and c['after_departure'] > 0
    rep = dict(check='live_state_rescoring', pass_=ok, counts=dict(c), runs=per_run, mismatches=bad[:50], dump_every=a.dump_every, dump_max=a.dump_max,
               note='States are dumped from the live diagnostic solver immediately before selection (N <= 20000), including states reached after earlier departures.')
    write(out, 'live_report.json', rep); return rep


# ------------------------------------------------------------------------------------------- overhead
def check_overhead(a, build, out):
    rows = []
    for gid, s in OVERHEAD:
        g = pathlib.Path(a.upstream) / PUBLIC / f'{gid}.graph'
        for rep in range(a.repetitions):
            order = ('pristine', 'baseline') if rep % 2 == 0 else ('baseline', 'pristine')
            for pol in order:
                r = invoke.run(build, s, pol, g, out / 'runs', a.cpu_limit, a.cpu_limit * 1.25 + 120, graph_id=gid, verify=False)
                rows.append(dict(graph=gid, solver=s, policy=pol, repetition=rep, status=r['status'], cpu_s=r['cpu_s'], wall_s=r['wall_s'], nodes=invoke.flat(r)['nodes']))
        for fam in LEARNED:
            for diag in (False, True):
                r = invoke.run(build, s, fam, g, out / 'runs', a.cpu_limit, a.cpu_limit * 1.25 + 120, graph_id=gid, verify=False, diag=diag)
                summ = r.get('summary') or {}
                rows.append(dict(graph=gid, solver=s, policy=fam + ('-diagnostic' if diag else ''), repetition=0, status=r['status'], cpu_s=r['cpu_s'], wall_s=r['wall_s'],
                                 nodes=invoke.flat(r)['nodes'], scored=summ.get('scored_decisions'), diag_feature_s=summ.get('diag_feature_s'),
                                 diag_score_s=summ.get('diag_score_s'), diag_select_s=summ.get('diag_select_s'), model_load_cpu_s=(summ.get('timing') or {}).get('after_attach_cpu_s')))
        print('overhead', gid, s, flush=True)
    summary = []
    for gid, s in OVERHEAD:
        pc = [r['cpu_s'] for r in rows if (r['graph'], r['solver'], r['policy']) == (gid, s, 'pristine') and r['status'] == 'completed']
        bc = [r['cpu_s'] for r in rows if (r['graph'], r['solver'], r['policy']) == (gid, s, 'baseline') and r['status'] == 'completed']
        if pc and bc:
            summary.append(dict(graph=gid, solver=s, pristine_cpu_median=statistics.median(pc), baseline_cpu_median=statistics.median(bc),
                                ratio=statistics.median(bc) / statistics.median(pc) if statistics.median(pc) > 0 else None, n=len(pc)))
    ok = len(summary) == len(OVERHEAD)
    rep = dict(check='instrumentation_overhead', pass_=ok, cases=OVERHEAD, repetitions=a.repetitions, summary=summary, rows=rows,
               note='Integrated timed baseline vs the pristine pinned binary: the difference is the cost of node/decision counters, the '
                    'pivot-trace hash, the CPU guard and summary output. Diagnostic rows time feature extraction and scoring separately; '
                    'diagnostic timers perturb execution and are never used for primary timing.')
    write(out, 'overhead_report.json', rep); return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('check', choices=['baseline', 'oracle', 'suite', 'live', 'overhead'])
    ap.add_argument('--build', required=True); ap.add_argument('--upstream', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--stagec-report'); ap.add_argument('--stagec-pairs'); ap.add_argument('--max-stagec-cpu', type=float, default=60.0)
    ap.add_argument('--seed', type=int, default=20261124); ap.add_argument('--per-type', type=int, default=60)
    ap.add_argument('--random-seeds', type=int, nargs='*', default=[1, 2, 3])
    ap.add_argument('--cpu-limit', type=float, default=600.0); ap.add_argument('--repetitions', type=int, default=3)
    ap.add_argument('--dump-every', type=int, default=97); ap.add_argument('--dump-max', type=int, default=60)
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=False)
    build = invoke.Build(a.build)
    t0 = time.time()
    rep = dict(baseline=check_baseline, oracle=check_oracle, suite=check_suite, live=check_live, overhead=check_overhead)[a.check](a, build, out)
    print(a.check, 'PASS' if rep['pass_'] else 'FAIL', round(time.time() - t0, 1), 's')
    return 0 if rep['pass_'] else 1


if __name__ == '__main__':
    sys.exit(main())
