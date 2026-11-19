"""Build once for the full Stage C run: original solver + Verifier (pinned source, untouched),
full-run instrumented solver, SampleCheck. Same toolchain/flags as the verified checkpoint.
Usage: python build.py <w64devkit bin dir> <pinned upstream checkout> <output dir>"""
import datetime, hashlib, json, os, pathlib, platform, subprocess, sys, uuid, winreg

HERE = pathlib.Path(__file__).resolve().parent
COMMIT = 'c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4'
FLAGS = ['-include', 'string', '-std=c++11', '-O3']
SOLVER_TUS = ['Main.cpp', 'solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/Translator.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp']
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p, x): pathlib.Path(p).write_text(json.dumps(x, indent=2) + '\n', encoding='utf-8')


def main():
    tc, upstream, out = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PATH=str(tc) + os.pathsep + os.environ['PATH']); gxx = str(tc / 'g++.exe')
    git = lambda *a: subprocess.check_output(['git', *a], cwd=upstream, text=True).strip()
    assert git('rev-parse', 'HEAD') == COMMIT and git('status', '--porcelain') == ''
    manifest = json.loads((HERE.parent / 'records/local-checkpoint/reference_manifest.json').read_text())
    bad = [r['path'] for r in manifest if sha(upstream / r['path']) != r['sha256']]
    assert not bad, bad[:5]
    log = []
    def run(cmd):
        p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log.append(dict(command=cmd, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)); print(subprocess.list2cmdline(cmd), flush=True)
        if p.returncode: print(p.stdout, p.stderr); save(out / 'build_log.json', log); raise SystemExit(p.returncode)
    def build(src, tus, exe, inc=None, extra=()):
        obj = out / 'obj' / (exe.parent.name + '-' + exe.stem); obj.mkdir(parents=True); exe.parent.mkdir(parents=True, exist_ok=True); objs = []
        for tu in [*(src / t for t in tus), *extra]:
            o = obj / (pathlib.Path(tu).name + '.obj'); run([gxx, *FLAGS, *(['-I', str(inc)] if inc else []), '-o', str(o), '-c', str(tu)]); objs.append(str(o))
        run([gxx, *FLAGS, *objs, '-o', str(exe)])
    base = upstream / 'src'; inst = out / 'instrumented-src'
    build(base, SOLVER_TUS, out / 'baseline/FeedbackVertexSet.exe')
    build(base, ['OutputVerifier.cpp'], out / 'baseline/Verifier.exe')
    run([sys.executable, '-I', str(HERE / 'prepare.py'), str(base), str(inst)])
    build(inst, SOLVER_TUS + ['StageC.cpp'], out / 'instrumented/FeedbackVertexSet.exe')
    build(inst, ['StageC.cpp', 'solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp'],
          out / 'audit-tool/SampleCheck.exe', inc=inst, extra=[HERE / 'SampleCheck.cpp'])
    assert git('status', '--porcelain') == ''
    diff = subprocess.run(['git', 'diff', '--no-index', '--', str(base), str(inst)], capture_output=True); (out / 'instrumentation.patch').write_bytes(diff.stdout)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k: cpu = winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    exes = ['baseline/FeedbackVertexSet.exe', 'baseline/Verifier.exe', 'instrumented/FeedbackVertexSet.exe', 'audit-tool/SampleCheck.exe']
    record = dict(build_id='full-build-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8],
        full_commit=COMMIT, source_url='https://github.com/karek/FeedbackVertexSet-Experiments', experiment_commit=os.environ.get('GITHUB_SHA', 'unknown'),
        github_run_id=os.environ.get('GITHUB_RUN_ID', 'unknown'),
        build_runner=dict(os=platform.platform(), cpu_model=cpu, logical_cpus=os.cpu_count(), image=(os.environ.get('ImageOS', '') + ' ' + os.environ.get('ImageVersion', '')).strip() or 'unknown'),
        compiler_version=subprocess.check_output([gxx, '--version'], env=env, text=True).strip(),
        toolchain_url=os.environ.get('TOOLCHAIN_URL', 'unknown'), toolchain_archive_sha256=os.environ.get('TOOLCHAIN_SHA256', 'unknown'),
        effective_cxx_flags=' '.join(FLAGS), assertions='enabled (no -DNDEBUG), as in the checkpoint',
        command_lines=[subprocess.list2cmdline(c['command']) for c in log],
        executables={e: dict(sha256=sha(out / e)) for e in exes},
        instrumented_source_hashes={p.relative_to(inst).as_posix(): sha(p) for p in sorted(inst.rglob('*')) if p.is_file()},
        experiment_tool_hashes={p.relative_to(HERE.parent).as_posix(): sha(p) for d in ('full', 'stagec') for p in sorted((HERE.parent / d).glob('*')) if p.is_file() and p.suffix in ('.py', '.cpp', '.h')},
        reference_files_verified=len(manifest),
        native_counters='The original executable prints only the solution size and vertices; it emits no native counters or node count.',
        workarounds=['-include string supplies a header missing upstream (GCC 16); no upstream source edited.', 'g++ called directly; same flags as checkpoint compile_commands.'])
    save(out / 'build_log.json', log); save(out / 'build_record.json', record)
    print(record['build_id'], record['compiler_version'].splitlines()[0])


if __name__ == '__main__':
    main()
