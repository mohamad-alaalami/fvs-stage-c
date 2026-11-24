"""Exercise the benchmark driver, retry rule and report generator on PUBLIC fixtures (never reserved graphs).

  * schedule rule and balance on the 100 public IDs and on 130 synthetic placeholder IDs (no files)
  * real bench.py jobs on public graphs with a short CPU limit (timeouts occur), three policies per job
  * injected cases: wall watchdog (infrastructure -> exit 1 -> retried as attempt 2), missing model (policy_error),
    unknown policy (configuration_error), corrupted output (verification failure), missing invocation record
  * report.py over all attempts: the attempt rule, categories and the exclusion of timeouts from paired measures

Usage: python integration/fixture_bench.py --build BUILD --upstream UPSTREAM --out DIR [--cpu-limit 3]
"""
import argparse, json, os, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import schedule as S  # noqa: E402

FIXTURES = ['003', '095', '044', '005', '009', '046', '011', '092', '017', '014', '057', '037']
FAULT_JOBS = {('8', '011'): 'watchdog:linear', ('5', '044'): 'model-missing:boost', ('LP', '009'): 'bad-policy:linear',
              ('8', '003'): 'corrupt-output:boost', ('5', '095'): 'skip-record:baseline'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True); ap.add_argument('--upstream', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--cpu-limit', type=float, default=3.0)
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=False)
    checks = {}
    pub = [f'{i:03d}' for i in range(1, 101)]
    sp = S.make_schedule(pub); checks['public_100_balance'] = S.check_balance(sp)
    syn = [f'placeholder-{i:03d}' for i in range(130)]
    ss = S.make_schedule(syn); checks['placeholder_130_balance'] = S.check_balance(ss)
    m = ss['manifest']
    checks['budget_1170_invocations'] = m['invocations'] == 1170 and m['max_solver_cpu_hours'] == 585.0
    (out / 'placeholder_manifest.json').write_text(json.dumps(m, indent=2) + '\n')
    sched = S.make_schedule(FIXTURES, cpu_limit=a.cpu_limit)
    (out / 'schedule.json').write_text(json.dumps(sched, indent=2) + '\n')
    gdir = pathlib.Path(a.upstream) / 'tests/pace-16open'
    exits = {}
    for s in S.SOLVERS:
        for j in sched['jobs'][s]:
            key = (s, j['graph_id']); fault = FAULT_JOBS.get(key)
            cmd = [sys.executable, str(HERE / 'bench.py'), '--build', a.build, '--schedule', str(out / 'schedule.json'), '--solver', s, '--index', str(j['index']),
                   '--graph-dir', str(gdir), '--out', str(out / 'jobs' / f'{s}-{j["graph_id"]}' / 'attempt-1')]
            if fault:
                cmd += ['--fault', fault]
            if key == ('8', '095'):
                cmd += ['--timing-repetitions', '1']
            env = dict(os.environ, GITHUB_RUN_ATTEMPT='1')
            exits[key] = subprocess.run(cmd, env=env).returncode
            if exits[key] == 1:   # paired retry of the whole job as a new attempt
                cmd2 = [c for c in cmd if c not in ('--fault', fault)]
                cmd2[cmd2.index(str(out / 'jobs' / f'{s}-{j["graph_id"]}' / 'attempt-1'))] = str(out / 'jobs' / f'{s}-{j["graph_id"]}' / 'attempt-2')
                env['GITHUB_RUN_ATTEMPT'] = '2'
                exits[key + ('retry',)] = subprocess.run(cmd2, env=env).returncode
    checks['infra_fault_jobs_exit_1'] = exits[('8', '011')] == 1 and exits[('5', '095')] == 1
    checks['non_infra_jobs_exit_0'] = all(v == 0 for k, v in exits.items() if k not in (('8', '011'), ('5', '095')))
    subprocess.run([sys.executable, str(HERE / 'report.py'), '--schedule', str(out / 'schedule.json'), '--jobs', str(out / 'jobs'), '--out', str(out / 'report'),
                    '--title', 'Public fixture exercise (NOT benchmark results)'], check=True, stdout=subprocess.DEVNULL)
    rep = json.loads((out / 'report' / 'report.json').read_text())
    def cat(s, fam, k):
        return rep['solvers'][s]['comparisons'][f'baseline_vs_{fam}']['categories'].get(k, 0)
    rows = {r['graph_id']: r for r in __import__('csv').DictReader(open(out / 'report' / 'per_graph_8.csv'))}
    checks['retry_attempt_used'] = rep['solvers']['8']['job_outcomes'].get('ok') == len(FIXTURES) and rows['011']['attempt'] == '2' and rows['003']['attempt'] == '1'
    checks['verification_failure_counted'] = cat('8', 'boost', 'verification_failure') >= 1
    checks['policy_error_counted'] = cat('5', 'boost', 'error') >= 1
    checks['configuration_error_counted'] = cat('LP', 'linear', 'error') >= 1
    checks['timeouts_present'] = any(rep['solvers'][s]['timeout_observed_prefixes'] for s in S.SOLVERS)
    checks['timeouts_never_in_pairs'] = all(
        v['pairs'] == rep['solvers'][s]['comparisons'][c]['categories'].get('both_solved', 0)
        for s in S.SOLVERS for c in rep['solvers'][s]['comparisons'] for v in rep['solvers'][s]['comparisons'][c]['measures'].values())
    checks['jointly_solved_less_than_all'] = any(rep['solvers'][s]['comparisons'][c]['jointly_solved'] < len(FIXTURES) for s in S.SOLVERS for c in rep['solvers'][s]['comparisons'])
    jr = json.loads(next((out / 'jobs' / '8-095' / 'attempt-1').rglob('job.json')).read_text())
    checks['timing_repetitions_recorded_separately'] = bool(jr.get('timing_repetitions'))
    ok = all(checks.values())
    res = dict(check='benchmark_fixture_exercise', pass_=ok, checks=checks, exits={'/'.join(k): v for k, v in exits.items()}, fixtures=FIXTURES, faults={'/'.join(k): v for k, v in FAULT_JOBS.items()}, cpu_limit_s=a.cpu_limit)
    (out / 'fixture_report.json').write_text(json.dumps(res, indent=2, sort_keys=True) + '\n')
    print('fixture', 'PASS' if ok else 'FAIL', checks)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
