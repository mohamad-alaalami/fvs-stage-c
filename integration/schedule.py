"""Benchmark schedule and budget manifest (integration-v1).

The rule is fixed in advance and applied at dispatch to whatever graph list the owner approves:
  * one job per (solver, graph); the job runs baseline, linear and boost SEQUENTIALLY on one runner
  * policy order: graphs of each solver are ranked by SHA-256("integration-v1|order|<solver>|<graph_id>");
    the graph of rank r uses permutation PERMS[r mod 6] (all six orders of the three policies, fixed list)
    -> each order is used floor(n/6) or ceil(n/6) times per solver; each policy appears in each position
       within one of n/3 per solver
  * matrix index of a job = position of its graph in sorted(graph_ids); one static matrix per solver
Scheduling never opens graph files: it needs graph IDs only (the reserved workflow lists them at dispatch).

Usage: python integration/schedule.py --graph-ids FILE --out schedule.json [--cpu-limit 1800] [--expect 130]
"""
import argparse, collections, hashlib, itertools, json, math, pathlib, sys

POLICIES = ('baseline', 'linear', 'boost')
# Fixed order: the three cyclic rotations, then the three reversed rotations. Any three consecutive entries
# of each half place every policy once in every position, so leftovers (n mod 6) stay within 1 of n/3.
PERMS = [['baseline', 'linear', 'boost'], ['linear', 'boost', 'baseline'], ['boost', 'baseline', 'linear'],
         ['baseline', 'boost', 'linear'], ['boost', 'linear', 'baseline'], ['linear', 'baseline', 'boost']]
assert sorted(map(tuple, PERMS)) == sorted(itertools.permutations(POLICIES))
SOLVERS = ('8', '5', 'LP')
TAG = 'integration-v1'
MAX_PARALLEL = {'8': 7, '5': 7, 'LP': 6}          # sum 20 = the Free-plan concurrency for standard runners
SETUP_MINUTES = 10                                 # checkout, Python, fetch + verify build, publish (observed on public runs)


def rank_key(solver, gid):
    return hashlib.sha256(f'{TAG}|order|{solver}|{gid}'.encode()).hexdigest()


def watchdog_s(cpu_limit):
    return 1.25 * cpu_limit + 120.0


def make_schedule(graph_ids, solvers=SOLVERS, cpu_limit=1800.0, timing_repetitions=0, repeat_under_s=60.0):
    ids = sorted(set(graph_ids))
    assert len(ids) == len(graph_ids), 'duplicate graph ids'
    jobs = {}
    for s in solvers:
        ranked = sorted(ids, key=lambda g: rank_key(s, g))
        rank = {g: r for r, g in enumerate(ranked)}
        jobs[s] = [dict(solver=s, index=i, graph_id=g, rank=rank[g], order=PERMS[rank[g] % 6]) for i, g in enumerate(ids)]
    n_inv = len(ids) * len(solvers) * len(POLICIES)
    job_wall_max_s = len(POLICIES) * watchdog_s(cpu_limit)
    per_job_minutes = job_wall_max_s / 60 + SETUP_MINUTES
    jobs_total = len(ids) * len(solvers)
    manifest = dict(
        graphs=len(ids), solvers=list(solvers), policies=list(POLICIES), invocations=n_inv, cpu_limit_s=cpu_limit,
        cpu_limit_kind='independent per-invocation PROCESS-CPU limit (kernel+user)',
        max_solver_cpu_hours=n_inv * cpu_limit / 3600,
        per_invocation_wall_watchdog_s=watchdog_s(cpu_limit), job_timeout_minutes=math.ceil(per_job_minutes + 20),
        job_layout=f'{len(solvers)} static matrices (one per solver) of {len(ids)} jobs; each job = one graph, three policies sequentially on one runner',
        max_parallel_per_matrix=MAX_PARALLEL, max_concurrent_jobs=sum(MAX_PARALLEL[s] for s in solvers),
        runner='windows-2025 (standard GitHub-hosted, 4 vCPU); one solver process at a time per runner',
        worst_case_runner_minutes=round(jobs_total * per_job_minutes),
        expected_upper_runner_minutes_note='worst case assumes every invocation reaches its CPU limit and its wall equals the watchdog; '
                                           'Stage C observed wall ~= CPU + 1% for these single-threaded solvers',
        worst_case_wall_hours_at_max_concurrency=round(jobs_total * per_job_minutes / 60 / sum(MAX_PARALLEL[s] for s in solvers), 1),
        cpu_bound_wall_hours_at_max_concurrency=round(n_inv * cpu_limit / 3600 / sum(MAX_PARALLEL[s] for s in solvers), 1),
        billing='standard GitHub-hosted runners are free for public repositories; Windows runners bill at 2x minutes only on private repositories',
        timing_repetitions=dict(enabled=timing_repetitions > 0, repetitions=timing_repetitions, eligible='jobs in which all three policies complete with CPU < %g s' % repeat_under_s,
                                max_extra_cpu_hours=round(jobs_total * timing_repetitions * len(POLICIES) * repeat_under_s / 3600, 1),
                                note='NOT included in max_solver_cpu_hours; proposed separately; repetitions rotate the policy order and are never used to replace primary records'),
        retry_rule='A job is retried only after an infrastructure failure (wall_watchdog, not_run_job_deadline, driver_error, missing_record, '
                   'build_mismatch, runner loss or a failed publish). The whole job (all three policies, same order) is re-run as a new attempt via '
                   '"Re-run failed jobs"; at most 2 retries. Analysis uses, per job, the first attempt without an infrastructure failure, never '
                   'mixing invocations of different attempts; after 3 failed attempts the job is reported as infrastructure_failure. Solver timeouts, '
                   'solver errors, policy errors and verification failures are results and are never retried. Every attempt is preserved.',
        order_rule='PERMS[rank mod 6], rank by SHA-256("%s|order|<solver>|<graph_id>")' % TAG, perms=PERMS)
    balance = {}
    for s in solvers:
        pos = collections.Counter((j['order'][k], k) for j in jobs[s] for k in range(3))
        balance[s] = dict(orders=dict(collections.Counter(' > '.join(j['order']) for j in jobs[s])),
                          position_counts={f'{p}@{k}': pos[(p, k)] for p in POLICIES for k in range(3)})
    manifest['balance'] = balance
    return dict(schema='integration-v1-schedule', tag=TAG, graph_ids=ids, jobs=jobs, manifest=manifest)


def check_balance(sched):
    n = len(sched['graph_ids'])
    for s, b in sched['manifest']['balance'].items():
        for c in b['orders'].values():
            assert n // 6 <= c <= -(-n // 6), (s, b['orders'])
        for c in b['position_counts'].values():
            assert abs(c - n / 3) <= 1, (s, b['position_counts'])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--graph-ids', required=True, help='text file, one graph id per line'); ap.add_argument('--out', required=True)
    ap.add_argument('--cpu-limit', type=float, default=1800.0); ap.add_argument('--expect', type=int, default=0)
    ap.add_argument('--timing-repetitions', type=int, default=0)
    a = ap.parse_args()
    ids = [x.strip() for x in pathlib.Path(a.graph_ids).read_text().splitlines() if x.strip()]
    if a.expect and len(ids) != a.expect:
        raise SystemExit(f'expected {a.expect} graph ids, found {len(ids)}')
    sched = make_schedule(ids, cpu_limit=a.cpu_limit, timing_repetitions=a.timing_repetitions)
    check_balance(sched)
    pathlib.Path(a.out).write_text(json.dumps(sched, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(sched['manifest'], indent=2)[:3000])


if __name__ == '__main__':
    sys.exit(main())
