"""Build baseline + instrumented solvers, Verifier and SnapshotCheck from the pinned source.
Usage: python build.py <w64devkit bin dir> <pinned upstream checkout> <output dir>
Flags are the verified checkpoint's effective flags: -include string -std=c++11 -O3
(assertions enabled, as in the checkpoint). g++ is called directly, one translation
unit at a time, then linked with the same flags; the checkpoint used CMake+Ninja,
whose recorded compile commands are exactly these flags (plus dependency-file flags).
"""
import datetime, hashlib, json, os, pathlib, platform, subprocess, sys, uuid, winreg

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
COMMIT = 'c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4'
FLAGS = ['-include', 'string', '-std=c++11', '-O3']
SOLVER_TUS = ['Main.cpp', 'solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/Translator.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp']


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p, x): pathlib.Path(p).write_text(json.dumps(x, indent=2) + '\n', encoding='utf-8')


def main():
    tc, upstream, out = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PATH=str(tc) + os.pathsep + os.environ['PATH'])
    gxx = str(tc / 'g++.exe')
    git = lambda *a: subprocess.check_output(['git', *a], cwd=upstream, text=True).strip()
    assert git('rev-parse', 'HEAD') == COMMIT, 'upstream checkout is not the pinned commit'
    assert git('status', '--porcelain') == '', 'upstream checkout must be clean'
    manifest = json.loads((REPO_ROOT / 'records/local-checkpoint/reference_manifest.json').read_text())
    bad = [r['path'] for r in manifest if sha(upstream / r['path']) != r['sha256']]
    assert not bad, ('supplied reference files differ from checkpoint manifest', bad[:5])

    log = []
    def run(cmd, cwd=None):
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log.append(dict(command=cmd, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr))
        print(subprocess.list2cmdline(cmd), flush=True)
        if p.returncode:
            print(p.stdout, p.stderr)
            save(out / 'build_log.json', log)
            raise SystemExit(p.returncode)

    def build(src, tus, exe, extra_inc=None, extra_src=()):
        obj = out / 'obj' / (exe.parent.name + '-' + exe.stem); obj.mkdir(parents=True); exe.parent.mkdir(parents=True, exist_ok=True)
        objs = []
        for tu in [*(src / t for t in tus), *extra_src]:
            o = obj / (pathlib.Path(tu).name + '.obj')
            run([gxx, *FLAGS, *(['-I', str(extra_inc)] if extra_inc else []), '-o', str(o), '-c', str(tu)])
            objs.append(str(o))
        run([gxx, *FLAGS, *objs, '-o', str(exe)])

    base_src = upstream / 'src'
    build(base_src, SOLVER_TUS, out / 'baseline' / 'FeedbackVertexSet.exe')
    build(base_src, ['OutputVerifier.cpp'], out / 'baseline' / 'Verifier.exe')
    inst_src = out / 'instrumented-src'
    run([sys.executable, '-I', str(HERE / 'prepare.py'), str(base_src), str(inst_src)])
    build(inst_src, SOLVER_TUS + ['StageC.cpp'], out / 'instrumented' / 'FeedbackVertexSet.exe')
    build(inst_src, ['StageC.cpp', 'solutions/HalfIntBranching.cpp', 'lib/Graph.cpp', 'lib/CubicSolver.cpp', 'lib/HalfIntRelax.cpp'],
          out / 'audit-tool' / 'SnapshotCheck.exe', extra_inc=inst_src, extra_src=[HERE / 'SnapshotCheck.cpp'])
    assert git('status', '--porcelain') == '', 'build modified the pinned checkout'
    diff = subprocess.run(['git', 'diff', '--no-index', '--', str(base_src), str(inst_src)], capture_output=True)
    (out / 'instrumentation.patch').write_bytes(diff.stdout)

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:
        cpu = winreg.QueryValueEx(k, 'ProcessorNameString')[0]
    exes = {name: out / name for name in ['baseline/FeedbackVertexSet.exe', 'baseline/Verifier.exe', 'instrumented/FeedbackVertexSet.exe', 'audit-tool/SnapshotCheck.exe']}
    record = dict(
        build_id='gha-build-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8],
        full_commit=COMMIT, source_url='https://github.com/karek/FeedbackVertexSet-Experiments',
        stage_c_repo_commit=os.environ.get('GITHUB_SHA', 'unknown'), github_run_id=os.environ.get('GITHUB_RUN_ID', 'unknown'),
        runner=dict(os=platform.platform(), cpu_model=cpu, architecture=platform.machine(), logical_cpus=os.cpu_count(),
                    runner_name=os.environ.get('RUNNER_NAME', 'unknown'), image=os.environ.get('ImageOS', 'unknown') + ' ' + os.environ.get('ImageVersion', '')),
        compiler_version=subprocess.check_output([gxx, '--version'], env=env, text=True).strip(),
        toolchain_url=os.environ.get('TOOLCHAIN_URL', 'unknown'), toolchain_archive_sha256=os.environ.get('TOOLCHAIN_SHA256', 'unknown'),
        effective_cxx_flags=' '.join(FLAGS), assertions='enabled (no -DNDEBUG), as in the checkpoint',
        python=sys.version, commands=[c['command'] for c in log],
        command_lines=[subprocess.list2cmdline(c['command']) for c in log],
        executables={k: dict(path=k, sha256=sha(v)) for k, v in exes.items()},
        instrumented_source_hashes={p.relative_to(inst_src).as_posix(): sha(p) for p in sorted(inst_src.rglob('*')) if p.is_file()},
        stage_c_tool_hashes={p.name: sha(p) for p in sorted(HERE.glob('*')) if p.is_file() and p.suffix in ('.py', '.cpp', '.h')},
        reference_files_verified=len(manifest),
        workarounds=['-include string supplies a header missing upstream (GCC 16); no upstream source edited.',
                     'g++ invoked directly instead of CMake/Ninja; same flags as the checkpoint compile_commands.'])
    save(out / 'build_log.json', log)
    save(out / 'build_record.json', record)
    print(json.dumps({k: record[k] for k in ['build_id', 'full_commit', 'effective_cxx_flags']}, indent=2))
    print(record['compiler_version'].splitlines()[0])


if __name__ == '__main__':
    main()
