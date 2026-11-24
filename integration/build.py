"""Build integration-v1 once: pristine baseline + Verifier, the integrated solver, the replay tool.

Usage: python integration/build.py <w64devkit bin dir> <pinned upstream checkout> <output dir>

Same toolchain and flags as Stage C / Stage D (w64devkit 2.11.0, GCC 16.2.0, -include string -std=c++11 -O3,
assertions on). Only public-graph reference hashes are checked; reserved paths are never read.
The integrated solver and the replay tool are linked from the SAME object files (FvsPolicy.o, FvsHooks.o,
Graph.o, ...), so the replay exercises the executable code of the timed solver.
"""
import datetime, hashlib, json, os, pathlib, platform, subprocess, sys, uuid

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import prepare  # noqa: E402

COMMIT = 'c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4'
FLAGS = ['-include', 'string', '-std=c++11', '-O3']
SOLVER_TUS = ['Main.cpp', 'solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/Translator.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp']
INTEGRATION_TUS = SOLVER_TUS + ['FvsHooks.cpp', 'FvsPolicy.cpp']
REPLAY_TUS = ['solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp', 'FvsHooks.cpp', 'FvsPolicy.cpp']
TOOLCHAIN_SHA256 = '54c2bb9962e8a30c8270e34c5efc3d5fee579f53087fa7d435b95fbba2af7b2b'


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def save(p, x):
    pathlib.Path(p).write_text(json.dumps(x, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def cpu_model():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
            return winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    except Exception:
        return platform.processor() or 'unknown'


def verify_models(dest):
    """Copy the six frozen models into the build after checking every recorded SHA-256."""
    man = json.loads((HERE / 'models/MODELS.json').read_text())
    out = {}
    for key, d in sorted(man['models'].items()):
        s, f = key.split('/')
        (dest / s / f).mkdir(parents=True, exist_ok=True)
        for name in ('model.json', 'model_meta.json'):
            if name in d:
                src = HERE / 'models' / s / f / name
                assert sha(src) == d[name]['sha256'], (key, name)
                (dest / s / f / name).write_bytes(src.read_bytes())
                out[f'{key}/{name}'] = d[name]['sha256']
    return man, out


def main():
    tc, upstream, out = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PATH=str(tc) + os.pathsep + os.environ['PATH']); gxx = str(tc / 'g++.exe')
    git = lambda *a: subprocess.check_output(['git', *a], cwd=upstream, text=True).strip()
    assert git('rev-parse', 'HEAD') == COMMIT
    assert git('status', '--porcelain', '--', 'src') == '', 'pinned src must be clean'
    # Public reference files only (the manifest also lists reserved files: never read them).
    manifest = json.loads((ROOT / 'records/local-checkpoint/reference_manifest.json').read_text())
    public = [r for r in manifest if r['path'].startswith('tests/pace-16open/')]
    present = [r for r in public if (upstream / r['path']).exists()]
    # The checkpoint manifest hashed CRLF checkouts (Windows autocrlf); accept raw or CRLF-normalised bytes.
    def ref_ok(r):
        b = (upstream / r['path']).read_bytes()
        return hashlib.sha256(b).hexdigest() == r['sha256'] or hashlib.sha256(b.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest() == r['sha256']
    bad = [r['path'] for r in present if not ref_ok(r)]
    assert not bad, bad[:5]
    log = []

    def run(cmd):
        p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log.append(dict(command=cmd, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)); print(subprocess.list2cmdline(cmd), flush=True)
        if p.returncode:
            print(p.stdout, p.stderr); save(out / 'build_log.json', log); raise SystemExit(p.returncode)

    def compile_all(src, tus, objdir, inc=None):
        objdir.mkdir(parents=True); objs = {}
        for tu in tus:
            o = objdir / (tu.replace('/', '_') + '.o')
            run([gxx, *FLAGS, *(['-I', str(inc)] if inc else []), '-o', str(o), '-c', str(src / tu)]); objs[tu] = str(o)
        return objs

    def link(objs, exe):
        exe.parent.mkdir(parents=True, exist_ok=True); run([gxx, *FLAGS, *objs, '-o', str(exe)])

    base = upstream / 'src'
    bobj = compile_all(base, SOLVER_TUS, out / 'obj/baseline')
    link([bobj[t] for t in SOLVER_TUS], out / 'baseline/FeedbackVertexSet.exe')
    vobj = compile_all(base, ['OutputVerifier.cpp'], out / 'obj/verifier')
    link([vobj['OutputVerifier.cpp']], out / 'baseline/Verifier.exe')
    inst = out / 'integrated-src'
    _, touched = prepare.prepare(base, inst)
    (inst / 'PolicyReplay.cpp').write_bytes((HERE / 'native/PolicyReplay.cpp').read_bytes())
    iobj = compile_all(inst, INTEGRATION_TUS + ['PolicyReplay.cpp'], out / 'obj/integrated', inc=inst)
    link([iobj[t] for t in INTEGRATION_TUS], out / 'integrated/FvsIntegrated.exe')
    link([iobj[t] for t in REPLAY_TUS + ['PolicyReplay.cpp']], out / 'tools/PolicyReplay.exe')
    assert git('status', '--porcelain', '--', 'src') == ''
    diff = subprocess.run(['git', 'diff', '--no-index', '--', str(base), str(inst)], capture_output=True)
    (out / 'integration.patch').write_bytes(diff.stdout)
    models_manifest, model_hashes = verify_models(out / 'models')
    exes = ['baseline/FeedbackVertexSet.exe', 'baseline/Verifier.exe', 'integrated/FvsIntegrated.exe', 'tools/PolicyReplay.exe']
    e = os.environ
    record = dict(
        build_id='integration-build-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8],
        upstream_commit=COMMIT, upstream_url='https://github.com/karek/FeedbackVertexSet-Experiments',
        experiment_commit=e.get('GITHUB_SHA', 'local'), github_run_id=e.get('GITHUB_RUN_ID', 'local'), github_run_attempt=e.get('GITHUB_RUN_ATTEMPT', 'local'),
        build_runner=dict(os=platform.platform(), cpu_model=cpu_model(), logical_cpus=os.cpu_count(),
                          image=(e.get('ImageOS', '') + ' ' + e.get('ImageVersion', '')).strip() or 'local'),
        compiler_version=subprocess.check_output([gxx, '--version'], env=env, text=True).strip(),
        toolchain='w64devkit 2.11.0', toolchain_archive_sha256=e.get('TOOLCHAIN_SHA256', TOOLCHAIN_SHA256),
        flags=' '.join(FLAGS), assertions='enabled (no -DNDEBUG), as in Stage C and Stage D',
        command_lines=[subprocess.list2cmdline(c['command']) for c in log],
        executables={x: dict(sha256=sha(out / x)) for x in exes},
        shared_objects_between_solver_and_replay=sorted(set(REPLAY_TUS) & set(INTEGRATION_TUS)),
        prepared_files_edited=touched,
        integrated_source_hashes={p.relative_to(inst).as_posix(): sha(p) for p in sorted(inst.rglob('*')) if p.is_file()},
        pinned_source_hashes={p.relative_to(base).as_posix(): sha(p) for p in sorted(base.rglob('*')) if p.is_file() and 'build' not in p.relative_to(base).parts},
        experiment_tool_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((HERE).rglob('*')) if p.is_file() and p.suffix in ('.py', '.cpp', '.h', '.json', '.md') and 'models' not in p.relative_to(HERE).parts},
        model_hashes=model_hashes, models_results_commit=models_manifest['results_commit'], models_training_commit=models_manifest['training_commit'],
        public_reference_files_verified=len(present), reserved_files_read=0,
        integration_patch_sha256=sha(out / 'integration.patch'))
    save(out / 'build_log.json', log); save(out / 'build_record.json', record)
    print(record['build_id'], record['compiler_version'].splitlines()[0])


if __name__ == '__main__':
    main()
