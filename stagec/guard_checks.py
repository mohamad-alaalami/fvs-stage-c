"""Clean-stop checks for the instrumented build (graph 095 only; separate from experiment rows).
Usage: python guard_checks.py <build dir> <upstream checkout> <output dir>"""
import json, pathlib, shutil, subprocess, sys
build, repo, out = (pathlib.Path(a).resolve() for a in sys.argv[1:4])
exe = build / 'instrumented/FeedbackVertexSet.exe'
checks = []
for name, overrides, expected in [('cpu_zero', {'STAGE_CPU_LIMIT': '0'}, 74),
                                  ('disk_reserve', {'STAGE_RESERVE_BYTES': str(shutil.disk_usage(out.parent if out.parent.exists() else '.').free + 1024 ** 3)}, 73)]:
    d = out / name; d.mkdir(parents=True)
    env = dict(__import__('os').environ, STAGE_DIR=str(d), STAGE_GRAPH='pace-16open/095.graph', STAGE_RUN='guard-' + name, **overrides)
    with (repo / 'tests/pace-16open/095.graph').open('rb') as f:
        p = subprocess.run([str(exe), '8'], stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
    (d / 'stdout.txt').write_bytes(p.stdout); (d / 'stderr.txt').write_bytes(p.stderr)
    summary = json.loads((d / 'solver_summary.json').read_text())
    events = sum(f.stat().st_size for f in (d / 'events').iterdir())
    ok = p.returncode == expected and summary['B'] == summary['T'] == summary['A'] == 0 and events == 0
    checks.append(dict(name=name, environment_overrides=overrides, exit_code=p.returncode, expected_exit_code=expected, summary=summary, event_bytes=events, passed=ok))
(out / 'results.json').write_text(json.dumps(checks, indent=2) + '\n')
print(json.dumps([(c['name'], c['passed']) for c in checks]))
assert all(c['passed'] for c in checks), checks
