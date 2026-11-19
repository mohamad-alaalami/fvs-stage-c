"""Stage C driver for ONE public graph on one machine (a GitHub Actions job).

Order inside the job: solver 8, 5, LP; each = baseline run, verify, instrumented run,
verify, audit (every event, every A snapshot), one replay check. Every invocation has
a new UUID run ID; nothing is reused or overwritten. No sampling, no record dropping.

Usage: python run_graph.py --build DIR --upstream DIR --graph 029 --out DIR
       [--cpu-limit 1800] [--reserve-bytes N] [--deadline-s S] [--segment-bytes N]
"""
import argparse, csv, datetime, hashlib, json, os, pathlib, re, shutil, subprocess, sys, time, traceback, uuid
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import segments
from snapshot import decode
from winmeasure import measurements, lifetime

SOLVERS = ['8', '5', 'LP']
HIDDEN_DIR = 'pace16-hidden'
START = time.monotonic()
RE_OFF = re.compile(rb'"snapshot_offset":(\d+)')
RE_LEN = re.compile(rb'"snapshot_bytes":(\d+)')
RE_SEQ = re.compile(rb'"sequence":(\d+)')

ap = argparse.ArgumentParser()
ap.add_argument('--build', required=True); ap.add_argument('--upstream', required=True)
ap.add_argument('--graph', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--toolchain', default='')
ap.add_argument('--cpu-limit', type=float, default=1800)
ap.add_argument('--reserve-bytes', type=int, default=3 * 1024 ** 3)
ap.add_argument('--deadline-s', type=float, default=5.25 * 3600)
ap.add_argument('--segment-bytes', type=int, default=256 * 1024 ** 2)
ap.add_argument('--solvers', default=','.join(SOLVERS))
args = ap.parse_args()

BUILD = pathlib.Path(args.build).resolve(); REPO = pathlib.Path(args.upstream).resolve()
OUT = pathlib.Path(args.out).resolve(); OUT.mkdir(parents=True, exist_ok=True)
BREC = json.loads((BUILD / 'build_record.json').read_text())
EXE = dict(baseline=BUILD / 'baseline/FeedbackVertexSet.exe', instrumented=BUILD / 'instrumented/FeedbackVertexSet.exe',
           replay=BUILD / 'instrumented/FeedbackVertexSet.exe')
VERIFIER = BUILD / 'baseline/Verifier.exe'; CHECKER = BUILD / 'audit-tool/SnapshotCheck.exe'
ENV = dict(os.environ)
if args.toolchain:
    ENV['PATH'] = args.toolchain + os.pathsep + ENV['PATH']
RESERVE = args.reserve_bytes; HEADROOM = 64 * 1024 ** 2


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p, x): pathlib.Path(p).write_text(json.dumps(x, indent=2) + '\n', encoding='utf-8')
def free(): return shutil.disk_usage(OUT).free
def stamp(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10]
def past_deadline(): return time.monotonic() - START >= args.deadline_s


def graph_edges(p):
    edges = []
    for line in p.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        a = line.split(); assert len(a) == 2, (p, line); edges.append(tuple(a))
    return {v for e in edges for v in e}, edges


def execute(graph, solver, kind, extra=None):
    rid = stamp() + '-' + graph + '-' + solver + '-' + kind
    d = OUT / 'runs' / rid; d.mkdir(parents=True)
    command = [str(EXE[kind]), solver] + (extra or [])
    inp = REPO / 'tests/pace-16open' / f'{graph}.graph'
    env = dict(ENV, STAGE_DIR=str(d), STAGE_GRAPH='pace-16open/' + graph + '.graph', STAGE_RUN=rid,
               STAGE_CPU_LIMIT=str(args.cpu_limit), STAGE_RESERVE_BYTES=str(RESERVE), STAGE_SEGMENT_BYTES=str(args.segment_bytes))
    rec = dict(run_id=rid, graph=graph, solver=solver, kind=kind, command=command, command_line=subprocess.list2cmdline(command) + ' < ' + str(inp),
               cwd=str(REPO), input=str(inp), graph_sha256=sha(inp), build_id=BREC['build_id'], executable_sha256=sha(EXE[kind]),
               cpu_limit_s=args.cpu_limit, cpu_limit_kind='process CPU (kernel+user), GetProcessTimes', free_disk_before=free(),
               reserve_bytes=RESERVE, segment_bytes=args.segment_bytes, status='started', directory=str(d),
               cpu_s='unknown', wall_s='unknown', process_lifetime_s='unknown', peak_working_set_bytes='unknown', exit_code='unknown')
    save(d / 'run.json', rec)
    print('START', rid, flush=True)
    if rec['free_disk_before'] <= RESERVE + HEADROOM:
        rec.update(status='not_run_disk_reserve'); save(d / 'run.json', rec); log_invocation(rec); return rec
    if past_deadline():
        rec.update(status='not_run_job_deadline'); save(d / 'run.json', rec); log_invocation(rec); return rec
    comp = segments.Compressor(d) if kind != 'baseline' else None
    start = time.perf_counter(); stop_reason = None; stop_at = None; last_tel = -10; last_prog = -60
    with inp.open('rb') as fi, (d / 'stdout.txt').open('wb') as fo, (d / 'stderr.txt').open('wb') as fe, (d / 'telemetry.jsonl').open('w') as tel:
        p = subprocess.Popen(command, stdin=fi, stdout=fo, stderr=fe, cwd=REPO, env=env)
        if comp: comp.start()
        try:
            while p.poll() is None:
                el = time.perf_counter() - start; cpu, _ = measurements(p)
                if el - last_tel >= 1:
                    f = free(); s = segments.sizes(d) if kind != 'baseline' else {}
                    tel.write(json.dumps(dict(wall_s=el, cpu_s=cpu, free_bytes=f, streams=s)) + '\n'); tel.flush(); last_tel = el
                    if f <= RESERVE + HEADROOM: stop_reason = stop_reason or 'disk_reserve'
                if cpu != 'unknown' and cpu >= args.cpu_limit: stop_reason = stop_reason or 'cpu_timeout'
                if past_deadline(): stop_reason = stop_reason or 'job_deadline'
                if comp and comp.error: stop_reason = stop_reason or 'compressor_error'
                if (OUT / 'STOP').exists(): stop_reason = stop_reason or 'user_interruption'
                if stop_reason and stop_at is None:
                    stop_at = el
                    if kind == 'baseline': p.kill()
                    else: (d / 'STOP').write_text(stop_reason)
                if stop_at is not None and el - stop_at >= 5 and p.poll() is None:
                    p.kill(); rec['forced_termination'] = True
                if el - last_prog >= 60:
                    print('PROGRESS', rid, 'cpu_s', cpu, 'wall_s', round(el, 1), 'free', f, flush=True); last_prog = el
                time.sleep(.05)
            p.wait()
        except KeyboardInterrupt:
            stop_reason = 'user_interruption'; (d / 'STOP').write_text(stop_reason)
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill(); p.wait()
        rec['wall_s'] = time.perf_counter() - start
        rec['cpu_s'], rec['peak_working_set_bytes'] = measurements(p); rec['process_lifetime_s'] = lifetime(p); rec['exit_code'] = p.returncode
    rec['wall_measurement_method'] = 'perf_counter from before process creation to observed exit (<=50 ms polling latency); process_lifetime_s is exit-minus-creation FILETIME'
    if comp:
        try: rec['segments_compressed'] = comp.finish()
        except Exception as e: rec['compressor_error'] = repr(e); stop_reason = stop_reason or 'compressor_error'
    rec['status'] = stop_reason or ('completed' if p.returncode == 0 else {73: 'disk_reserve', 74: 'cpu_timeout', 75: 'external_stop'}.get(p.returncode, 'failed'))
    if (d / 'solver_summary.json').exists():
        rec['solver_summary'] = json.loads((d / 'solver_summary.json').read_text())
        if rec['solver_summary']['status'] != 'completed' and not stop_reason: rec['status'] = rec['solver_summary']['status']
    rec['free_disk_after'] = free()
    if kind != 'baseline':
        s = segments.sizes(d); rec['streams'] = s
        rec['snapshot_bytes'] = s['snapshots']['raw_bytes']; rec['snapshot_stored_bytes'] = s['snapshots']['stored_bytes']
        rec['log_bytes'] = s['events']['raw_bytes'] + s['continuations']['raw_bytes']
        rec['log_stored_bytes'] = s['events']['stored_bytes'] + s['continuations']['stored_bytes']
    else:
        rec.update(snapshot_bytes=0, snapshot_stored_bytes=0, log_bytes=0, log_stored_bytes=0)
    rec['observed_growth_bytes_per_wall_s'] = (rec['snapshot_bytes'] + rec['log_bytes']) / rec['wall_s'] if rec['wall_s'] else 'unknown'
    rec['observed_growth_bytes_per_cpu_s'] = (rec['snapshot_bytes'] + rec['log_bytes']) / rec['cpu_s'] if isinstance(rec['cpu_s'], float) and rec['cpu_s'] > 0 else 'unknown'
    save(d / 'run.json', rec); log_invocation(rec)
    print('FINISH', rid, rec['status'], 'cpu', rec['cpu_s'], 'wall', round(rec['wall_s'], 3), 'bytes', rec['snapshot_bytes'] + rec['log_bytes'], flush=True)
    return rec


def log_invocation(rec):
    with (OUT / 'invocations.jsonl').open('a') as f:
        f.write(json.dumps(rec) + '\n'); f.flush(); os.fsync(f.fileno())


def verify(rec):
    d = pathlib.Path(rec['directory']); inp = pathlib.Path(rec['input']); opt = inp.with_suffix('.opt')
    res = {'feasible': 'unknown', 'reference_size': int(opt.read_text().split()[0]) if opt.exists() else 'unknown',
           'reference_source': str(opt.relative_to(REPO).as_posix()) if opt.exists() else 'unknown', 'reference_verdict': 'unknown', 'returned_size': 'unknown'}
    if rec['status'] == 'completed':
        try:
            tokens = (d / 'stdout.txt').read_text().split(); n = int(tokens[0]); returned = tokens[1:]; vertices, edges = graph_edges(inp)
            distinct = len(set(returned)) == len(returned); valid = set(returned) <= vertices; count = n == len(returned) and n >= 0
            parent = {v: v for v in vertices - set(returned)}
            def find(v):
                while parent[v] != v: parent[v] = parent[parent[v]]; v = parent[v]
                return v
            forest = True
            for u, v in edges:
                if u not in parent or v not in parent: continue
                a, b = find(u), find(v)
                if a == b: forest = False; break
                parent[a] = b
            cmd = [str(VERIFIER), str(inp), str(d / 'stdout.txt')]  # no optimum-file argument
            v = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
            (d / 'verifier.stdout.txt').write_bytes(v.stdout); (d / 'verifier.stderr.txt').write_bytes(v.stderr)
            res.update(feasible=all([distinct, valid, count, forest, v.returncode == 0]), declared_count=count, distinct=distinct, valid_ids=valid,
                       forest=forest, returned_size=n, returned_vertices=returned, verifier_command=cmd, verifier_exit_code=v.returncode)
            if opt.exists(): res['reference_verdict'] = 'match' if n == res['reference_size'] else 'mismatch'
        except Exception as e:
            res.update(feasible=False, error=repr(e))
    else:
        (d / 'verifier.stdout.txt').write_text('Not run: solver did not complete.\n')
    save(d / 'verification.json', res); return res


def audit(rec):
    """Recompute B/T/A from every event; restore every A snapshot natively; replay one."""
    d = pathlib.Path(rec['directory']); out = d / 'native-audit'; out.mkdir(exist_ok=True)
    res = dict(audit='untested', replay='untested', failures=[])
    if not (d / 'events').exists():
        res.update(audit='no_event_log', B='unknown', T='unknown', A='unknown', snapshot_count=0, snapshot_bytes=0, largest_snapshot_bytes=0)
        save(d / 'audit.json', res); return res
    choice = None; cont_lines = 0
    for line, complete in segments.iter_lines(d / 'continuations'):
        if not complete: res['failures'].append('trailing partial continuation line'); break
        e = json.loads(line); cont_lines += 1
        if e['complete'] and e['trace_count'] <= 1000 and (choice is None or e['trace_count'] > choice['trace_count']): choice = e
    cmd = [str(CHECKER), rec['solver']]
    t0 = time.perf_counter()
    with (out / 'stdout.json').open('wb') as so, (out / 'stderr.txt').open('wb') as se:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=so, stderr=se, env=dict(ENV, STAGE_DIR=str(out)))
        reader = segments.ByteReader(d / 'snapshots'); running = 0; py = dict(B=0, T=0, A=0); rep_event = rep_bytes = None
        try:
            for line, complete in segments.iter_lines(d / 'events'):
                if not complete: res['failures'].append('trailing partial event line (hard termination)'); break
                py['B'] += 1; py['T'] += b'"T":true' in line
                p.stdin.write(line + b'\n')
                if b'"A":true' in line:
                    py['A'] += 1
                    off = int(RE_OFF.search(line).group(1)); n = int(RE_LEN.search(line).group(1))
                    if off != running: raise RuntimeError(f'snapshot offset gap at event {py["B"]}: {off} != {running}')
                    data = reader.read(n); running += n; p.stdin.write(data)
                    if choice and rep_event is None and int(RE_SEQ.search(line).group(1)) == choice['sequence']:
                        rep_event = json.loads(line); rep_bytes = data
            p.stdin.close()
        except BrokenPipeError:
            pass
        p.wait()
    unreferenced = reader.remaining()
    save(out / 'invocation.json', dict(command=cmd, wall_s=time.perf_counter() - t0, exit_code=p.returncode, executable_sha256=sha(CHECKER),
                                       purpose='restore, re-serialize and re-derive the decision for every A snapshot; no search'))
    if p.returncode != 0:
        res.update(audit='fail', failures=res['failures'] + ['SnapshotCheck: ' + (out / 'stderr.txt').read_text(errors='replace')], B=py['B'], T=py['T'], A=py['A'])
        save(d / 'audit.json', res); return res
    native = json.loads((out / 'stdout.json').read_text()); res.update(native)
    summary = rec.get('solver_summary')
    res['python_counts'] = py; res['unreferenced_snapshot_bytes'] = unreferenced
    res['summary_counts_match'] = all(summary.get(k) == native[k] for k in py) if summary else 'no_final_summary'
    ok = native['B'] >= native['T'] >= native['A'] == native['snapshot_count'] and py == {k: native[k] for k in py} and unreferenced == 0 \
        and native['snapshot_bytes'] == rec['snapshot_bytes'] and res['summary_counts_match'] is not False and cont_lines == native['A']
    if cont_lines != native['A']: res['failures'].append(f'continuation records {cont_lines} != A {native["A"]}')
    res['audit'] = 'pass' if ok and res['summary_counts_match'] is True and not res['failures'] else ('partial' if ok else 'fail')
    res['replay'] = 'not_applicable_zero_A' if native['A'] == 0 else ('untested_no_completed_continuation_le_1000' if not choice else 'untested')
    if choice and rep_event is not None:
        state = decode(rep_bytes); assert state['stageNames'][state['pivot']] == rep_event['original_pivot']
        snap = d / 'replay-input'; snap.mkdir(exist_ok=True); sp = snap / f'sequence-{choice["sequence"]}.bin'; sp.write_bytes(rep_bytes)
        r = execute(rec['graph'], rec['solver'], 'replay', ['--replay', str(sp), '0', str(len(rep_bytes))])
        actual = None
        for line, complete in segments.iter_lines(pathlib.Path(r['directory']) / 'continuations'):
            if complete and json.loads(line)['sequence'] == 1: actual = json.loads(line); break
        passed = r['status'] == 'completed' and actual is not None and all(choice[k] == actual[k] for k in ['complete', 'trace_count', 'trace_digest', 'final_state_hash'])
        res.update(replay='pass' if passed else 'fail', replay_run_id=r['run_id'], replay_event_id=rep_event['event_id'], replay_phase=rep_event['phase'],
                   replay_component_subsolver=rep_event['component_subsolver'], replay_original_pivot=rep_event['original_pivot'],
                   expected_continuation=choice, actual_continuation=actual)
    save(d / 'audit.json', res); return res


def num(x): return isinstance(x, (int, float)) and not isinstance(x, bool)


def pair(graph, solver):
    b = execute(graph, solver, 'baseline'); vb = verify(b)
    i = execute(graph, solver, 'instrumented'); vi = verify(i)
    try:
        a = audit(i) if i['status'] not in ('not_run_disk_reserve', 'not_run_job_deadline') else dict(audit='not_run', replay='untested')
    except Exception:
        a = dict(audit='fail', replay='untested', failures=[traceback.format_exc()]); save(pathlib.Path(i['directory']) / 'audit.json', a)
    both = b['status'] == i['status'] == 'completed'
    eq = (vb['returned_size'] == vi['returned_size'] and vb['feasible'] is True and vi['feasible'] is True) if both else 'unknown'
    ratio = lambda x, y: x / y if both and num(x) and num(y) and y > 0 else 'unknown'
    sb = i.get('snapshot_bytes', 0); lb = i.get('log_bytes', 0); sc = a.get('snapshot_count', 'unknown')
    row = dict(graph=graph, solver=solver, status=i['status'], baseline_status=b['status'],
               B=a.get('B', 'unknown'), T=a.get('T', 'unknown'), A=a.get('A', 'unknown'), snapshot_count=sc,
               snapshot_bytes=sb, log_bytes=lb, total_bytes=sb + lb,
               snapshot_stored_bytes=i.get('snapshot_stored_bytes', 0), log_stored_bytes=i.get('log_stored_bytes', 0),
               total_stored_bytes=i.get('snapshot_stored_bytes', 0) + i.get('log_stored_bytes', 0),
               bytes_per_snapshot=sb / sc if num(sc) and sc else 'not_applicable', largest_snapshot_bytes=a.get('largest_snapshot_bytes', 'unknown'),
               baseline_cpu_s=b['cpu_s'], instrumented_cpu_s=i['cpu_s'], baseline_wall_s=b['wall_s'], instrumented_wall_s=i['wall_s'],
               cpu_overhead_ratio=ratio(i['cpu_s'], b['cpu_s']), wall_overhead_ratio=ratio(i['wall_s'], b['wall_s']),
               baseline_peak_working_set_bytes=b['peak_working_set_bytes'], instrumented_peak_working_set_bytes=i['peak_working_set_bytes'],
               baseline_feasible=vb['feasible'], feasible=vi['feasible'], baseline_size=vb['returned_size'], returned_size=vi['returned_size'],
               reference_size=vi['reference_size'], reference_verdict=vi['reference_verdict'], baseline_reference_verdict=vb['reference_verdict'],
               baseline_validation=eq, audit=a['audit'], replay=a['replay'], invariant_failures=a.get('invariant_failures', 'unknown'),
               nonforest_fallbacks=a.get('nonforest_fallbacks', 'unknown'), component_events=a.get('component_events', 'unknown'),
               baseline_run_id=b['run_id'], instrumented_run_id=i['run_id'], replay_run_id=a.get('replay_run_id', ''),
               observed_growth_bytes_per_wall_s=i.get('observed_growth_bytes_per_wall_s', 'unknown'),
               observed_growth_bytes_per_cpu_s=i.get('observed_growth_bytes_per_cpu_s', 'unknown'),
               build_id=BREC['build_id'], runner_cpu=BREC['runner']['cpu_model'])
    print('PAIR', json.dumps(row), flush=True)
    return row


def main():
    g = args.graph
    assert re.fullmatch(r'\d{3}', g), g
    inp = REPO / 'tests/pace-16open' / f'{g}.graph'
    assert HIDDEN_DIR not in str(inp)
    inventory = {r['graph_id']: r for r in csv.DictReader((HERE.parent / 'records/local-checkpoint/dataset_inventory.csv').open())}
    ref = inventory['pace-16open/' + g + '.graph']; assert sha(inp) == ref['graph_sha256'], 'graph hash differs from checkpoint inventory'
    for k, p in EXE.items(): assert sha(p) == BREC['executables'][('baseline' if k == 'baseline' else 'instrumented') + '/FeedbackVertexSet.exe']['sha256']
    vertices, edges = graph_edges(inp)
    save(OUT / 'graph_job.json', dict(graph='pace-16open/' + g + '.graph', graph_sha256=ref['graph_sha256'], vertices=len(vertices), edges=len(edges),
         reference_optimum=ref['reference_optimum'], reference_source=ref['reference_source'], build_id=BREC['build_id'], runner=BREC['runner'],
         cpu_limit_s=args.cpu_limit, reserve_bytes=RESERVE, segment_bytes=args.segment_bytes, deadline_s=args.deadline_s,
         free_bytes_at_start=free(), output_volume=str(OUT.anchor), started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         solver_order=args.solvers.split(','), sampling='none', hidden_graphs='reserved (not run)'))
    rows = []
    for s in args.solvers.split(','):
        rows.append(pair(g, s))
        save(OUT / 'pairs.json', rows)
        with (OUT / 'results.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
    save(OUT / 'reference_integrity_after.json', dict(unchanged=all(sha(REPO / r['path']) == r['sha256'] for r in json.loads((HERE.parent / 'records/local-checkpoint/reference_manifest.json').read_text()))))
    print('DONE', g, [(r['solver'], r['status'], r['audit'], r['replay']) for r in rows], flush=True)


if __name__ == '__main__':
    main()
