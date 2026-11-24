"""Run one benchmark job: one (solver, graph), the three policies sequentially on this runner, in the
scheduled order, with identical build, inputs, CPU budget, thread limits and measurement boundaries.

Usage: python integration/bench.py --build BUILD --schedule schedule.json --solver 8 --index 17 --graph-dir DIR --out OUT
           [--cpu-limit 1800] [--deadline-minutes 160] [--timing-repetitions 0 --repeat-under-s 60]
           [--fault KIND:POLICY]   (public fixture tests only; refused with --reserved)
Exit code 1 iff an infrastructure failure occurred (so "Re-run failed jobs" retries exactly those jobs).
"""
import argparse, json, os, pathlib, shutil, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import invoke  # noqa: E402
from schedule import watchdog_s  # noqa: E402

FAULTS = ('watchdog', 'model-missing', 'bad-policy', 'corrupt-output', 'skip-record')


def main():
    ap = argparse.ArgumentParser()
    for x in ('--build', '--schedule', '--solver', '--graph-dir', '--out'):
        ap.add_argument(x, required=True)
    ap.add_argument('--index', type=int, required=True); ap.add_argument('--cpu-limit', type=float, default=None)
    ap.add_argument('--deadline-minutes', type=float, default=None); ap.add_argument('--timing-repetitions', type=int, default=0)
    ap.add_argument('--repeat-under-s', type=float, default=60.0); ap.add_argument('--fault', action='append', default=[])
    ap.add_argument('--reserved', action='store_true', help='reserved benchmark: no faults, no reference files required')
    a = ap.parse_args()
    t_start = time.monotonic()
    if a.reserved and a.fault:
        raise SystemExit('fault injection is refused in the reserved benchmark')
    sched = json.loads(pathlib.Path(a.schedule).read_text())
    job = sched['jobs'][a.solver][a.index]
    assert job['index'] == a.index and job['solver'] == a.solver
    cpu_limit = a.cpu_limit if a.cpu_limit is not None else sched['manifest']['cpu_limit_s']
    wd = watchdog_s(cpu_limit)
    deadline = t_start + 60 * (a.deadline_minutes if a.deadline_minutes else (3 * wd / 60 + 15))
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=False)
    faults = dict(f.split(':', 1) for f in a.fault)
    for k in faults:
        assert k in FAULTS, k
    build = invoke.Build(a.build)
    gpath = pathlib.Path(a.graph_dir) / f"{job['graph_id']}.graph"
    opt = gpath.with_suffix('.opt')
    reference = int(opt.read_text().split()[0]) if (opt.exists() and not a.reserved) else None
    rec = dict(schema='integration-v1-job', job=job, cpu_limit_s=cpu_limit, wall_watchdog_s=wd, build_id=build.record['build_id'],
               executables=build.record['executables'], model_hashes=build.record['model_hashes'], environment=invoke.environment(),
               graph_sha256=invoke.sha(gpath), reference_optimum=reference, faults=faults or None, started_utc=invoke.now(),
               thread_limits=dict((k, os.environ.get(k)) for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')), invocations={})
    invoke.save(out / 'job.json', rec)
    for pol in job['order']:
        f = faults
        env = {}
        if f.get('model-missing') == pol:
            env['FVSB_MODEL'] = str(out / 'missing-model.json')
        if f.get('bad-policy') == pol:
            env['FVSB_POLICY'] = 'not-a-policy'
        w = 0.5 if f.get('watchdog') == pol else wd
        r = invoke.run(build, a.solver, pol, gpath, out / 'invocations', cpu_limit, w, graph_id=job['graph_id'], reference=reference,
                       extra_env=env, deadline=deadline, verify=f.get('corrupt-output') != pol, label=f'job {a.solver}/{a.index}')
        if f.get('corrupt-output') == pol and r['status'] == 'completed':
            d = pathlib.Path(r['_dir']); txt = (d / 'stdout.txt').read_text().split()
            bad = ' '.join([txt[0]] + txt[1:-1] + ([txt[1]] if len(txt) > 2 else ['nonexistent-vertex']))   # duplicate a vertex, drop one
            r['verification'] = invoke.check_solution(gpath, bad + '\n', build.verifier, reference, d); r['fault_injected'] = 'corrupt-output'
            if not r['verification']['feasible']:
                r['status'] = 'verification_failed'
            invoke.save(d / 'run.json', {k: v for k, v in r.items() if k != '_dir'})
        if f.get('skip-record') == pol:
            shutil.rmtree(r['_dir']); rec['invocations'][pol] = dict(status='missing_record', run_dir=None); continue
        rec['invocations'][pol] = dict(invoke.flat(r), run_dir=pathlib.Path(r['_dir']).relative_to(out).as_posix(), run_id=r['run_id'],
                                       exit_code=r.get('exit_code'), executable_sha256=r['executable_sha256'], model=r.get('model'))
        invoke.save(out / 'job.json', rec)
    inv = rec['invocations']
    infra = sorted(p for p, v in inv.items() if v['status'] in invoke.INFRA_STATUSES)
    sizes = {p: v['size'] for p, v in inv.items() if v['status'] == 'completed'}
    rec.update(infrastructure_failure=bool(infra), infrastructure_failed_policies=infra,
               completed_sizes_agree=len(set(sizes.values())) <= 1, finished_utc=invoke.now(), job_wall_s=time.monotonic() - t_start)
    if a.timing_repetitions and all(v['status'] == 'completed' and (v['cpu_s'] or 0) < a.repeat_under_s for v in inv.values()):
        reps = []
        for k in range(a.timing_repetitions):
            order = job['order'][k + 1:] + job['order'][:k + 1]
            for pol in order:
                r = invoke.run(build, a.solver, pol, gpath, out / 'repetitions', cpu_limit, wd, graph_id=job['graph_id'], reference=reference, deadline=deadline)
                reps.append(dict(invoke.flat(r), policy=pol, repetition=k + 1, run_id=r['run_id']))
        rec['timing_repetitions'] = reps
    invoke.save(out / 'job.json', rec)
    print('JOB', a.solver, job['graph_id'], {p: v['status'] for p, v in inv.items()}, 'infra' if infra else 'ok', flush=True)
    return 1 if infra else 0


if __name__ == '__main__':
    sys.exit(main())
