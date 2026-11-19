"""Full Stage C: one graph-solver pair on one machine. Original solver first, instrumented second.
Usage: python run_pair.py --build DIR --upstream DIR --graph 029 --solver 8 --out DIR [options]
Every invocation gets a fresh UUID run ID; nothing is overwritten. Replay uses the ORIGINAL pivot only."""
import argparse, csv, datetime, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, time, traceback, uuid, winreg, zlib
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'stagec'))
from winmeasure import measurements, lifetime
from snapshot import decode

LABEL = {'8': 'Cao (Sol8)', '5': 'Chen-style (Sol5)', 'LP': 'Imanishi-Iwata-style (HalfIntBranching)'}
ap = argparse.ArgumentParser()
for a in ['--build', '--upstream', '--graph', '--solver', '--out']: ap.add_argument(a, required=True)
ap.add_argument('--cpu-limit', type=float, default=1800); ap.add_argument('--reserve-bytes', type=int, default=3 * 1024 ** 3)
ap.add_argument('--deadline-s', type=float, default=9000)
ap.add_argument('--seed', type=int, default=20261120); ap.add_argument('--k', type=int, default=32)
ap.add_argument('--first-cap', type=int, default=2 * 1024 ** 2); ap.add_argument('--slot-cap', type=int, default=64 * 1024)
ap.add_argument('--event-log', action='store_true', help='validation only: compact per-decision log')
ap.add_argument('--replay-trace-cap', type=int, default=200000); ap.add_argument('--replays', type=int, default=3)
args = ap.parse_args()
START = time.monotonic()
BUILD = pathlib.Path(args.build).resolve(); REPO = pathlib.Path(args.upstream).resolve(); OUT = pathlib.Path(args.out).resolve()
OUT.mkdir(parents=True, exist_ok=True)
BREC = json.loads((BUILD / 'build_record.json').read_text())
EXE = {'baseline': BUILD / 'baseline/FeedbackVertexSet.exe', 'instrumented': BUILD / 'instrumented/FeedbackVertexSet.exe', 'replay': BUILD / 'instrumented/FeedbackVertexSet.exe'}
VERIFIER = BUILD / 'baseline/Verifier.exe'; CHECKER = BUILD / 'audit-tool/SampleCheck.exe'
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p, x): pathlib.Path(p).write_text(json.dumps(x, indent=2) + '\n', encoding='utf-8')
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def stamp(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10]
def num(x): return isinstance(x, (int, float)) and not isinstance(x, bool)


def environment():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k: cpu = winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    e = os.environ
    return dict(cpu_model=cpu, logical_cpus=os.cpu_count(), os=platform.platform(), python=sys.version.split()[0],
                image=(e.get('ImageOS', '') + ' ' + e.get('ImageVersion', '')).strip() or 'unknown', runner_name=e.get('RUNNER_NAME', 'unknown'),
                runner_environment=e.get('RUNNER_ENVIRONMENT', 'unknown'), github_run_id=e.get('GITHUB_RUN_ID', 'unknown'), github_run_attempt=e.get('GITHUB_RUN_ATTEMPT', 'unknown'),
                github_job=e.get('GITHUB_JOB', 'unknown'), free_disk_bytes=shutil.disk_usage(OUT).free)


def graph_edges(p):
    edges = []
    for line in p.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            a = line.split(); assert len(a) == 2, (p, line); edges.append(tuple(a))
    return {v for e in edges for v in e}, edges


def execute(kind, extra=None, extra_env=None):
    rid = stamp() + '-' + args.graph + '-' + args.solver + '-' + kind
    d = OUT / 'invocations' / rid; d.mkdir(parents=True)
    command = [str(EXE[kind]), args.solver] + (extra or [])
    inp = REPO / 'tests/pace-16open' / f'{args.graph}.graph'
    env = dict(os.environ, STAGE_DIR=str(d), STAGE_GRAPH='pace-16open/' + args.graph + '.graph', STAGE_RUN=rid, STAGE_CPU_LIMIT=str(args.cpu_limit),
               STAGE_RESERVE_BYTES=str(args.reserve_bytes), STAGE_SAMPLE_SEED=str(args.seed), STAGE_SAMPLE_K=str(args.k),
               STAGE_FIRST_CAP_BYTES=str(args.first_cap), STAGE_SLOT_CAP_BYTES=str(args.slot_cap), **(extra_env or {}))
    stage_env = {k: v for k, v in env.items() if k.startswith('STAGE_')}
    rec = dict(run_id=rid, kind=kind, graph='pace-16open/' + args.graph + '.graph', solver=args.solver, command=command,
               command_line=subprocess.list2cmdline(command) + ' < ' + inp.relative_to(REPO).as_posix(), cwd=str(REPO),
               environment_variables=stage_env if kind != 'baseline' else 'inherited runner environment (STAGE_* ignored by the original executable)',
               build_id=BREC['build_id'], executable=str(EXE[kind].relative_to(BUILD).as_posix()), executable_sha256=sha(EXE[kind]),
               cpu_limit_s=args.cpu_limit, cpu_limit_kind='process CPU (kernel+user), Windows GetProcessTimes, polled every 50 ms',
               started_utc=now(), status='started', cpu_s='unknown', wall_s='unknown', process_lifetime_s='unknown', peak_working_set_bytes='unknown', exit_code='unknown')
    save(d / 'run.json', rec); print('START', rid, flush=True)
    if time.monotonic() - START >= args.deadline_s:
        rec.update(status='not_run_job_deadline'); save(d / 'run.json', rec); return rec, d
    if shutil.disk_usage(OUT).free <= args.reserve_bytes:
        rec.update(status='not_run_disk_reserve'); save(d / 'run.json', rec); return rec, d
    start = time.perf_counter(); stop = None; stop_at = None; last = -60
    with inp.open('rb') as fi, (d / 'stdout.txt').open('wb') as fo, (d / 'stderr.txt').open('wb') as fe:
        p = subprocess.Popen(command, stdin=fi, stdout=fo, stderr=fe, cwd=REPO, env=env)
        while p.poll() is None:
            el = time.perf_counter() - start; cpu, _ = measurements(p)
            if cpu != 'unknown' and cpu >= args.cpu_limit: stop = stop or 'cpu_timeout'
            if time.monotonic() - START >= args.deadline_s: stop = stop or 'job_deadline'
            if shutil.disk_usage(OUT).free <= args.reserve_bytes: stop = stop or 'disk_reserve'
            if stop and stop_at is None:
                stop_at = el
                if kind == 'baseline': p.kill()
                else: (d / 'STOP').write_text(stop)
            if stop_at is not None and el - stop_at >= 5 and p.poll() is None: p.kill(); rec['forced_termination'] = True
            if el - last >= 60: print('PROGRESS', rid, 'cpu_s', cpu, 'wall_s', round(el, 1), flush=True); last = el
            time.sleep(.05)
        p.wait()
        rec['wall_s'] = time.perf_counter() - start; rec['cpu_s'], rec['peak_working_set_bytes'] = measurements(p)
        rec['process_lifetime_s'] = lifetime(p); rec['exit_code'] = p.returncode
    rec['units'] = dict(cpu_s='seconds of process CPU', wall_s='seconds (perf_counter, process start to observed exit)', peak_working_set_bytes='bytes')
    rec['status'] = stop or ('completed' if p.returncode == 0 else {73: 'disk_reserve', 74: 'cpu_timeout', 75: 'external_stop'}.get(p.returncode, 'failed'))
    rec['finished_utc'] = now(); save(d / 'run.json', rec)
    print('FINISH', rid, rec['status'], 'cpu', rec['cpu_s'], 'wall', round(rec['wall_s'], 3), flush=True)
    return rec, d


def verify(rec, d):
    inp = REPO / 'tests/pace-16open' / f'{args.graph}.graph'; opt = inp.with_suffix('.opt')
    res = dict(feasible='unknown', returned_size='unknown', reference_size=int(opt.read_text().split()[0]) if opt.exists() else 'unknown',
               reference_source=opt.relative_to(REPO).as_posix() if opt.exists() else 'unknown', reference_verdict='unknown')
    if rec['status'] != 'completed':
        res['note'] = 'not verified: invocation did not complete'; save(d / 'verification.json', res); return res
    try:
        tokens = (d / 'stdout.txt').read_text().split(); n = int(tokens[0]); returned = tokens[1:]; vertices, edges = graph_edges(inp)
        distinct = len(set(returned)) == len(returned); valid = set(returned) <= vertices; count = n == len(returned) and n >= 0
        parent = {v: v for v in vertices - set(returned)}
        def find(v):
            while parent[v] != v: parent[v] = parent[parent[v]]; v = parent[v]
            return v
        forest = True
        for u, v in edges:
            if u in parent and v in parent:
                a, b = find(u), find(v)
                if a == b: forest = False; break
                parent[a] = b
        cmd = [str(VERIFIER), str(inp), str(d / 'stdout.txt')]  # no optional optimum-file argument
        v = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (d / 'verifier.stdout.txt').write_bytes(v.stdout); (d / 'verifier.stderr.txt').write_bytes(v.stderr)
        res.update(feasible=all([distinct, valid, count, forest, v.returncode == 0]), declared_count_matches=count, distinct_ids=distinct, valid_ids=valid,
                   deletion_leaves_forest=forest, returned_size=n, returned_vertices=returned, verifier_command=subprocess.list2cmdline(cmd), verifier_exit_code=v.returncode)
        if opt.exists(): res['reference_verdict'] = 'match' if n == res['reference_size'] else 'mismatch'
    except Exception as e:
        res.update(feasible=False, error=repr(e))
    save(d / 'verification.json', res); return res


def compress_samples(d):
    raw = d / 'samples.bin'
    if not raw.exists(): return dict(raw_bytes=0, stored_bytes=0, codec='none')
    data = raw.read_bytes(); z = zlib.compress(data, 9)
    assert zlib.decompress(z) == data
    (d / 'samples.bin.zz').write_bytes(z); h = hashlib.sha256(data).hexdigest(); raw.unlink()
    return dict(raw_bytes=len(data), raw_sha256=h, stored_bytes=len(z), codec='zlib-9', file='samples.bin.zz')


def consistency(summary):
    """Internal checks on the exact counters, histograms and node outcomes."""
    c = {}; h = summary['histograms']; B, T, A = summary['B'], summary['T'], summary['A']
    tot = lambda prefix: sum(v for k, hh in h.items() if k.startswith(prefix) for v in hh.values())
    c['B>=T>=A'] = B >= T >= A
    c['A_chen_strict_merge<=T'] = summary['A_chen_strict_merge'] <= T
    c['phase_counts_sum_to_B'] = sum(v for k, v in summary['counters'].items() if k.startswith('phase:')) == B
    c['B_depth_hist_sums_to_B'] = tot('B_by_depth:') == B
    c['B_solver_depth_hist_sums_to_B'] = tot('B_by_solver_depth:') == B
    c['T_candidate_hist_sums_to_T'] = tot('T_candidate_count:') == T
    c['A_depth_hist_sums_to_A'] = tot('A_by_depth:') == A
    c['A_equals_T_decisions_with_>=2_candidates'] = sum(v for k, hh in h.items() if k.startswith('T_candidate_count:') for n, v in hh.items() if int(n) >= 2) == A
    c['strict_hist_sums'] = sum(h.get('A_chen_strict_merge_by_depth', {}).values()) == summary['A_chen_strict_merge']
    nodes = summary['nodes']; procs = [p for p in ('branching', 'solve1', 'solve2')]
    c['every_node_has_one_outcome'] = all(nodes[p]['entered_main'] + nodes[p]['entered_component'] == sum(nodes[p][o] for o in
        ['branch', 'leaf_solution', 'pruned', 'no_pivot', 'delegate_to_solve1', 'reduction_recursion', 'interrupted', 'unclassified']) for p in procs)
    c['branch_outcomes_equal_B'] = sum(nodes[p]['branch'] for p in procs) == B
    c['no_unclassified_nodes'] = all(nodes[p]['unclassified'] == 0 for p in procs) and nodes['outcome_anomalies'] == 0
    c['original_pivot_always_eligible'] = not any(k.startswith('anomaly:') for k in summary['counters'])
    return c


def check_samples(d, meta):
    blob = zlib.decompress((d / 'samples.bin.zz').read_bytes()) if (d / 'samples.bin.zz').exists() else b''
    stream = bytearray(); expected = []
    for s in meta['samples']:
        state = blob[s['offset']:s['offset'] + s['state_bytes']]; cands = blob[s['candidates_offset']:s['candidates_offset'] + 4 * s['candidate_count']]
        decoded = decode(state); assert decoded['stageNames'][decoded['pivot']] == s['event']['original_pivot']
        stream += f"{s['sequence']} {len(state)} {s['candidate_count']}\n".encode() + state + cands; expected.append(s['sequence'])
    if not expected: return dict(status='not_applicable_no_saved_state', results=[])
    out = d / 'sample-check'; out.mkdir(exist_ok=True)
    p = subprocess.run([str(CHECKER), args.solver], input=bytes(stream), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, STAGE_DIR=str(out)))
    (out / 'stdout.jsonl').write_bytes(p.stdout); (out / 'stderr.txt').write_bytes(p.stderr)
    results = [json.loads(l) for l in p.stdout.decode().splitlines() if l.strip()]
    ok = p.returncode == 0 and [r['sequence'] for r in results] == expected and all(r['ok'] for r in results)
    return dict(status='pass' if ok else 'fail', exit_code=p.returncode, checked=len(results), results=results, checker_sha256=sha(CHECKER))


def replays(d, meta):
    blob = zlib.decompress((d / 'samples.bin.zz').read_bytes()) if (d / 'samples.bin.zz').exists() else b''
    eligible = [s for s in meta['samples'] if s['continuation'] and s['continuation']['complete'] and s['continuation']['trace_count'] <= args.replay_trace_cap]
    first = [s for s in eligible if s['kind'] == 'first_A']; rest = sorted((s for s in eligible if s['kind'] != 'first_A'), key=lambda s: -s['continuation']['trace_count'])
    chosen = (first + rest)[:args.replays]; results = []
    for s in chosen:
        f = d / 'replay-input'; f.mkdir(exist_ok=True); sp = f / f"sequence-{s['sequence']}.bin"; sp.write_bytes(blob[s['offset']:s['offset'] + s['state_bytes']])
        rec, rd = execute('replay', ['--replay', str(sp), '0', str(s['state_bytes'])])
        actual = json.loads((rd / 'replay_result.json').read_text()) if (rd / 'replay_result.json').exists() else None
        exp = s['continuation']; passed = rec['status'] == 'completed' and actual is not None and all(actual[k] == exp[k] for k in ['complete', 'trace_count', 'trace_digest', 'final_state_hash'])
        results.append(dict(sequence=s['sequence'], event_id=s['event_id'], kind=s['kind'], phase=s['event']['phase'], component_subsolver=s['event']['component_subsolver'],
                            original_pivot=s['event']['original_pivot'], replay_run_id=rec['run_id'], expected=exp, actual=actual, passed=passed,
                            replay_input=f"bytes [{s['offset']}, {s['offset'] + s['state_bytes']}) of zlib-decompressed samples.bin.zz (raw copy deleted after replay)"))
        sp.unlink()
    untested = dict(saved_states=len(meta['samples']), with_complete_continuation=sum(1 for s in meta['samples'] if s['continuation'] and s['continuation']['complete']),
                    within_trace_cap=len(eligible), replayed=len(results))
    status = 'not_applicable_no_saved_state' if not meta['samples'] else ('untested_no_complete_continuation_within_cap' if not results else ('pass' if all(r['passed'] for r in results) else 'fail'))
    return dict(status=status, trace_cap=args.replay_trace_cap, results=results, coverage=untested)


def main():
    g, s = args.graph, args.solver
    assert len(g) == 3 and g.isdigit() and s in LABEL
    inv = {r['graph_id']: r for r in csv.DictReader((HERE.parent / 'records/local-checkpoint/dataset_inventory.csv').open())}
    ref = inv['pace-16open/' + g + '.graph']; inp = REPO / 'tests/pace-16open' / f'{g}.graph'
    assert ref['subset'] == 'pace-16open' and sha(inp) == ref['graph_sha256']
    for k in ['baseline/FeedbackVertexSet.exe', 'baseline/Verifier.exe', 'instrumented/FeedbackVertexSet.exe', 'audit-tool/SampleCheck.exe']:
        assert sha(BUILD / k) == BREC['executables'][k]['sha256'], ('executable hash differs from build record', k)
    env = environment(); save(OUT / 'environment.json', env)
    pair = dict(graph=g, subset='pace-16open', filename=g + '.graph', graph_sha256=ref['graph_sha256'], vertices=int(ref['vertices']), edges=int(ref['edges']),
                reference_optimum=ref['reference_optimum'], reference_source=ref['reference_source'], solver=s, solver_label=LABEL[s],
                upstream_commit=BREC['full_commit'], experiment_commit=os.environ.get('GITHUB_SHA', 'local'), build_id=BREC['build_id'], execution_environment=env,
                sampling=dict(seed=args.seed, K=args.k, first_cap_bytes=args.first_cap, slot_cap_bytes=args.slot_cap), status='started')
    save(OUT / 'pair.json', pair)
    try:
        b, bd = execute('baseline'); vb = verify(b, bd)
        i, idir = execute('instrumented', extra_env={'STAGE_EVENT_LOG': '1'} if args.event_log else None); vi = verify(i, idir)
        src = 'final' if (idir / 'summary.json').exists() else ('partial_checkpoint' if (idir / 'summary.partial.json').exists() else 'none')
        summary = json.loads((idir / ('summary.json' if src == 'final' else 'summary.partial.json')).read_text()) if src != 'none' else None
        meta = json.loads((idir / 'samples.json').read_text()) if (idir / 'samples.json').exists() else dict(samples=[])
        storage = compress_samples(idir)
        checks = consistency(summary) if summary else {}
        sc = check_samples(idir, meta) if summary else dict(status='untested_no_summary')
        rp = replays(idir, meta) if summary else dict(status='untested_no_summary')
        both = b['status'] == i['status'] == 'completed'
        pair.update(status='recorded', baseline=dict(run_id=b['run_id'], status=b['status'], exit_code=b['exit_code'], cpu_s=b['cpu_s'], wall_s=b['wall_s'],
                        peak_working_set_bytes=b['peak_working_set_bytes'], verification=vb, node_count='unavailable: the original executable emits no counters'),
                    instrumented=dict(run_id=i['run_id'], status=i['status'], exit_code=i['exit_code'], cpu_s=i['cpu_s'], wall_s=i['wall_s'],
                        peak_working_set_bytes=i['peak_working_set_bytes'], verification=vi, counts_source=src),
                    solution_agreement=(dict(sizes_equal=vb['returned_size'] == vi['returned_size'], both_feasible=vb['feasible'] is True and vi['feasible'] is True) if both else 'not_applicable: not both completed'),
                    counts=summary, consistency=checks, consistency_pass=bool(checks) and all(checks.values()),
                    sample_storage=storage, sample_metadata={k: v for k, v in meta.items() if k != 'samples'},
                    saved_states=[dict(kind=x['kind'], slot=x['slot'], sequence=x['sequence'], event_id=x['event_id'], a_index=x['a_index'], state_bytes=x['state_bytes'],
                                       candidate_count=x['candidate_count'], phase=x['event']['phase'], continuation=x['continuation']) for x in meta['samples']],
                    sample_check=sc, replay=rp, finished_utc=now())
    except Exception:
        pair.update(status='runner_error', error=traceback.format_exc())
    save(OUT / 'pair.json', pair)
    print('PAIR', g, s, pair['status'], pair.get('baseline', {}).get('status'), pair.get('instrumented', {}).get('status'),
          'B', (pair.get('counts') or {}).get('B'), 'T', (pair.get('counts') or {}).get('T'), 'A', (pair.get('counts') or {}).get('A'),
          'consistency', pair.get('consistency_pass'), 'samples', pair.get('sample_check', {}).get('status'), 'replay', pair.get('replay', {}).get('status'), flush=True)


if __name__ == '__main__':
    main()
