"""Write integration/benchmark/MANIFEST.json: the proposed reserved-benchmark budget and rules (no graph IDs).
The reserved workflow requires approval = "APPROVE-" + first 16 hex of SHA-256(MANIFEST.json bytes)."""
import json, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import schedule as S

m = S.make_schedule([f'placeholder-{i:03d}' for i in range(130)])['manifest']
m.pop('balance')
jobs = 130 * 3
m['timing_repetitions'] = dict(
    enabled=False, proposed_repetitions=2, eligible='jobs in which all three policies complete with process CPU < 60 s',
    max_extra_invocations=jobs * 2 * 3, max_extra_cpu_hours=round(jobs * 2 * 3 * 60 / 3600, 1),
    max_extra_runner_minutes=round(jobs * 2 * 3 * (60 + 5) / 60),
    note='OPTIONAL and separately approved; NOT included in the 585 CPU-hour budget; same runner, rotated policy order (bench.py --timing-repetitions 2); '
         'primary records are never replaced; repetitions only estimate timing noise on short solves')
m.update(
    status='PROPOSED - graph set and compute budget require owner approval before dispatch',
    graph_set='all 130 graphs of tests/pace16-hidden at karek/FeedbackVertexSet-Experiments c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4; '
              'IDs are listed (git ls-tree, no blobs) only inside the dispatched reserved workflow; each job checks out only its own graph file',
    build='the exact build of a passing public validation run of the same commit (input validation_run), fetched from integration-results and hash-checked',
    models='integration/models/MODELS.json: the six frozen final refits of learnability run 45408454796 (results commit e5b8401), never retrained or reselected',
    measurement=dict(wall='driver perf_counter immediately before Popen to after wait()', cpu='GetProcessTimes kernel+user of the whole solver process after exit',
                     includes='process start, graph parsing, model loading (learned), search, feature extraction, scoring, output, summary write',
                     nodes='entries to branching()/solve1()/solve2(), component subsolvers included (Stage C definition)',
                     decisions='two-child branches (B); target decisions T; eligible decisions A (>=2 distinct eligible pivots; not measured in the timed baseline, which never enumerates candidates); scored decisions; departures (chosen != original pivot at the current state)',
                     cooperative_stop='in-process at the CPU limit (checked at most every 10 ms of wall); driver kill at limit + 30 s -> cpu_timeout_forced'),
    statuses=dict(results=['completed', 'cpu_timeout', 'cpu_timeout_forced', 'solver_error', 'policy_error', 'configuration_error', 'verification_failed'],
                  infrastructure=['wall_watchdog', 'not_run_job_deadline', 'driver_error', 'missing_record', 'build_mismatch']),
    analysis='integration/report.py: per solver, baseline vs linear and baseline vs boost separately; per-graph rows; solved categories; paired '
             'node/CPU/wall differences and ratios on jointly solved graphs only with graph bootstrap; timeouts as observed prefixes only',
    approval_token_rule='APPROVE- + first 16 hex digits of SHA-256 of this file')
p = HERE / 'MANIFEST.json'
p.write_bytes((json.dumps(m, indent=2, sort_keys=True) + '\n').encode())
import hashlib
print('APPROVE-' + hashlib.sha256(p.read_bytes()).hexdigest()[:16])
