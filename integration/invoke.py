"""One solver invocation under the integration-v1 measurement protocol (shared by every check and the benchmark).

Timing boundaries (identical for every policy):
  wall_s   driver time.perf_counter() immediately before subprocess.Popen to immediately after wait() returns
  cpu_s    GetProcessTimes(kernel + user) of the solver process after exit: the WHOLE process (loader, input
           parsing, model loading for learned policies, search, feature extraction, scoring, output, summary)
  lifetime process exit FILETIME minus creation FILETIME
The solver also records in-process phase times (summary.json 'timing').

CPU limit: cooperative in-process stop at FVSB_CPU_LIMIT (checked at most every 10 ms of wall in the search
guard) -> status cpu_timeout with final counters of the observed prefix; driver backstop kills at
limit + backstop_grace_s -> cpu_timeout_forced (counters from the last checkpoint, marked partial).
Wall watchdog: STOP file at watchdog_s, kill 5 s later -> wall_watchdog (an infrastructure failure).
"""
import datetime, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, time, uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
try:  # the Stage C Windows measurement module, loaded by path (never shadowing other module names)
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location('stagec_winmeasure', str(ROOT / 'stagec/winmeasure.py'))
    _wm = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_wm)
    measurements, lifetime = _wm.measurements, _wm.lifetime
except Exception:  # pragma: no cover - non-Windows unit tests
    measurements = lifetime = None

POLICIES = ('baseline', 'linear', 'boost')
INFRA_STATUSES = ('wall_watchdog', 'not_run_job_deadline', 'driver_error', 'missing_record', 'build_mismatch')
TIMEOUT_STATUSES = ('cpu_timeout', 'cpu_timeout_forced')
ERROR_STATUSES = ('solver_error', 'policy_error', 'configuration_error')
EXIT_STATUS = {0: 'completed', 74: 'cpu_timeout', 75: 'external_stop', 71: 'policy_error', 72: 'policy_error', 78: 'configuration_error'}


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha(p):
    return sha_bytes(pathlib.Path(p).read_bytes())


def fnv1a64(b):
    h = 14695981039346656037
    for c in b:
        h ^= c; h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return '%016x' % h


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10]


def save(p, x):
    pathlib.Path(p).write_text(json.dumps(x, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def cpu_model():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            return winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    except Exception:
        return platform.processor() or 'unknown'


def environment():
    e = os.environ
    return dict(cpu_model=cpu_model(), logical_cpus=os.cpu_count(), os=platform.platform(), python=sys.version.split()[0],
                image=(e.get('ImageOS', '') + ' ' + e.get('ImageVersion', '')).strip() or 'local', runner_name=e.get('RUNNER_NAME', 'local'),
                runner_environment=e.get('RUNNER_ENVIRONMENT', 'local'), github_run_id=e.get('GITHUB_RUN_ID', 'local'),
                github_run_attempt=e.get('GITHUB_RUN_ATTEMPT', 'local'), github_job=e.get('GITHUB_JOB', 'local'))


class Build:
    """A recorded build directory; executable and model hashes are re-checked on load."""

    def __init__(self, path):
        self.path = pathlib.Path(path).resolve()
        self.record = json.loads((self.path / 'build_record.json').read_text())
        for exe, d in self.record['executables'].items():
            if sha(self.path / exe) != d['sha256']:
                raise RuntimeError(f'build_mismatch: {exe}')
        for key, h in self.record['model_hashes'].items():
            if sha(self.path / 'models' / key) != h:
                raise RuntimeError(f'build_mismatch: model {key}')
        self.integrated = self.path / 'integrated/FvsIntegrated.exe'
        self.pristine = self.path / 'baseline/FeedbackVertexSet.exe'
        self.verifier = self.path / 'baseline/Verifier.exe'

    def model(self, solver, family):
        d = self.path / 'models' / solver / family
        return d / 'model.json', (d / 'model_meta.json' if family == 'boost' else None)


def read_graph(p):
    edges = []
    for line in pathlib.Path(p).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            a = line.split(); assert len(a) == 2, (p, line); edges.append((a[0], a[1]))
    return {v for e in edges for v in e}, edges


def check_solution(graph_path, stdout_text, verifier=None, reference=None, workdir=None):
    """Feasibility of a printed FVS (declared size, distinct valid IDs, remaining multigraph is a forest),
    the upstream Verifier, and size versus a trusted optimum when supplied. Feasible != optimal."""
    res = dict(feasible=False, returned_size=None, reference_size=reference, reference_verdict='unknown')
    tokens = stdout_text.split()
    try:
        n = int(tokens[0]); returned = tokens[1:]
    except Exception:
        res['error'] = 'unparsable output'; return res
    vertices, edges = read_graph(graph_path)
    distinct = len(set(returned)) == len(returned); valid = set(returned) <= vertices; count = n == len(returned)
    keep = vertices - set(returned); parent = {v: v for v in keep}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]; v = parent[v]
        return v
    forest = True
    for u, v in edges:   # a repeated edge between kept endpoints is a cycle of length 2
        if u in parent and v in parent:
            a, b = find(u), find(v)
            if a == b:
                forest = False; break
            parent[a] = b
    ver = None
    if verifier is not None and workdir is not None:
        out = pathlib.Path(workdir) / 'solution_for_verifier.txt'; out.write_text(stdout_text)
        v = subprocess.run([str(verifier), str(graph_path), str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ver = v.returncode
        res.update(verifier_exit_code=v.returncode, verifier_stdout=v.stdout.decode(errors='replace')[-2000:])
    res.update(declared_count_matches=count, distinct_ids=distinct, valid_ids=valid, deletion_leaves_forest=forest, returned_size=n,
               feasible=bool(distinct and valid and count and forest and (ver in (None, 0))))
    if reference is not None:
        res['reference_verdict'] = 'match' if n == reference else ('better_than_reference' if n < reference else 'worse_than_reference')
    return res


def run(build, solver, policy, graph_path, out_dir, cpu_limit, watchdog_s, backstop_grace_s=30.0, diag=False, extra_env=None,
        reference=None, graph_id=None, verify=True, label=None, deadline=None):
    """Run one invocation; returns the record dict (also saved as run.json in a fresh directory)."""
    rid = stamp() + '-' + (graph_id or pathlib.Path(graph_path).stem) + '-' + solver + '-' + policy.replace(':', '_')
    d = pathlib.Path(out_dir) / rid; d.mkdir(parents=True)
    pristine = policy == 'pristine'
    exe = build.pristine if pristine else build.integrated
    env = {k: v for k, v in os.environ.items() if not k.startswith('FVSB_')}
    model_rec = None
    if not pristine:
        env.update(FVSB_POLICY=policy, FVSB_SUMMARY=str(d / 'summary.json'), FVSB_CPU_LIMIT=repr(float(cpu_limit)), FVSB_STOP_FILE=str(d / 'STOP'))
        if diag:
            env['FVSB_DIAG'] = '1'
        if policy in ('linear', 'boost'):
            m, meta = build.model(solver, policy)
            env['FVSB_MODEL'] = str(m)
            if meta:
                env['FVSB_MODEL_META'] = str(meta)
            model_rec = dict(model_path=str(m.relative_to(build.path).as_posix()), model_sha256=sha(m), model_fnv1a64=fnv1a64(m.read_bytes()),
                             meta_path=str(meta.relative_to(build.path).as_posix()) if meta else None, meta_sha256=sha(meta) if meta else None,
                             meta_fnv1a64=fnv1a64(meta.read_bytes()) if meta else None)
    env.update(extra_env or {})
    graph_bytes = pathlib.Path(graph_path).read_bytes()
    rec = dict(schema='fvsb-invocation-1', run_id=rid, label=label, solver=solver, policy=policy, graph_id=graph_id or pathlib.Path(graph_path).stem,
               graph_sha256=sha_bytes(graph_bytes), command=[str(exe), solver], stdin=str(graph_path), diagnostic=diag,
               executable=str(exe.relative_to(build.path).as_posix()), executable_sha256=sha(exe), build_id=build.record['build_id'],
               fvsb_environment={k: v for k, v in env.items() if k.startswith('FVSB_')}, model=model_rec, cpu_limit_s=cpu_limit,
               cpu_limit_kind='process CPU (kernel+user, GetProcessTimes); cooperative in-process stop, driver kill at limit+%gs' % backstop_grace_s,
               wall_watchdog_s=watchdog_s, environment=environment(), started_utc=now(), status='started')
    save(d / 'run.json', rec)
    if deadline is not None and time.monotonic() >= deadline:
        rec.update(status='not_run_job_deadline', finished_utc=now()); save(d / 'run.json', rec); return rec
    forced = None; t_stop = None
    with open(graph_path, 'rb') as fi, (d / 'stdout.txt').open('wb') as fo, (d / 'stderr.txt').open('wb') as fe:
        start = time.perf_counter()
        p = subprocess.Popen([str(exe), solver], stdin=fi, stdout=fo, stderr=fe, cwd=str(d), env=env)
        while p.poll() is None:
            el = time.perf_counter() - start
            cpu, _ = measurements(p)
            if forced is None and cpu != 'unknown' and cpu >= cpu_limit + (0 if pristine else backstop_grace_s):
                forced = 'cpu_timeout_forced' if not pristine else 'cpu_timeout'; p.kill()
            if forced is None and el >= watchdog_s:
                if t_stop is None:
                    t_stop = el; (d / 'STOP').write_text('wall_watchdog')
                elif el - t_stop >= 5:
                    forced = 'wall_watchdog'; p.kill()
            if deadline is not None and forced is None and time.monotonic() >= deadline + 60:
                forced = 'not_run_job_deadline'; p.kill()
            time.sleep(0.05)
        p.wait()
        wall = time.perf_counter() - start
    cpu, peak = measurements(p)
    rec.update(wall_s=wall, cpu_s=cpu, peak_working_set_bytes=peak, process_lifetime_s=lifetime(p), exit_code=p.returncode, finished_utc=now(),
               units=dict(wall_s='seconds, perf_counter before Popen to after wait', cpu_s='seconds of process CPU (kernel+user)'))
    summ = None
    for name in ('summary.json', 'summary.json.partial'):
        if (d / name).exists():
            try:
                summ = json.loads((d / name).read_text()); summ['_source'] = name; break
            except Exception:
                pass
    rec['summary'] = summ
    if forced == 'wall_watchdog' or (t_stop is not None and summ and summ.get('status') == 'external_stop'):
        status = 'wall_watchdog'
    elif forced:
        status = forced
    elif pristine:
        status = 'completed' if p.returncode == 0 else 'solver_error'
    else:
        status = EXIT_STATUS.get(p.returncode, 'solver_error')
        if status == 'completed' and (not summ or summ.get('status') != 'completed' or summ.get('_source') != 'summary.json'):
            status = 'driver_error'
        if status == 'external_stop':
            status = 'wall_watchdog'
    rec['status'] = status
    rec['counts_source'] = (summ or {}).get('_source', 'none') if not pristine else 'unavailable_pristine'
    if summ and model_rec:
        m = summ.get('model') or {}
        rec['model_fnv_match'] = m.get('fnv1a64') == model_rec['model_fnv1a64'] and (model_rec['meta_fnv1a64'] is None or m.get('meta_fnv1a64') == model_rec['meta_fnv1a64'])
        if not rec['model_fnv_match'] and status == 'completed':
            rec['status'] = 'build_mismatch'
    stdout = (d / 'stdout.txt').read_bytes()
    rec['stdout_sha256'] = sha_bytes(stdout)
    rec['stderr_tail'] = (d / 'stderr.txt').read_bytes()[-2000:].decode(errors='replace')
    if verify and rec['status'] == 'completed':
        rec['verification'] = check_solution(graph_path, stdout.decode(errors='replace'), build.verifier, reference, d)
        if not rec['verification']['feasible']:
            rec['status'] = 'verification_failed'
    else:
        rec['verification'] = None
    save(d / 'run.json', rec)
    rec['_dir'] = str(d)
    return rec


def flat(rec):
    """Compact numeric view used by checks and reports."""
    s = rec.get('summary') or {}
    v = rec.get('verification') or {}
    return dict(status=rec['status'], cpu_s=rec.get('cpu_s'), wall_s=rec.get('wall_s'), nodes=(s.get('nodes') or {}).get('total'),
                decisions=s.get('decisions'), target=s.get('target_decisions'), eligible=s.get('eligible_decisions'),
                scored=s.get('scored_decisions'), departures=s.get('departures'), size=v.get('returned_size'),
                feasible=v.get('feasible'), counts_source=rec.get('counts_source'))
