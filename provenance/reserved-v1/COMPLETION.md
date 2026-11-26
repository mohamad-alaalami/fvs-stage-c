# Reserved benchmark v1: completion record

| Item | Value |
|---|---|
| Run | [45656199418](https://github.com/mohamad-alaalami/fvs-stage-c/actions/runs/45656199418), attempt 1 only |
| Experiment commit | `d65bb5519edcc9f8acf8dc6bb2805fe20472d04e` (`integration-v1-20261124`) |
| Validation run / build | 45493670014 / `integration-build-20261124T214255Z-97f58c0b` |
| Dispatched / finished | 2026-11-25T16:39:08Z / 2026-11-26T15:11:37Z (22 h 32 min elapsed) |
| GitHub jobs | 393 of 393 `success` (guard, schedule, 390 bench, report) |
| Results commit (report attempt 1) | `ff65964ee88fdacd1ab60e2d21e60d8872cf1ad8` |
| Report | `runs/45656199418/report/attempt-1/REPORT.md` |
| Infrastructure retries | **none** (no infrastructure failures; the retry rule was never invoked) |

## Accounting (independent re-audit of every `job.json`)

The audit script `completion_audit.py` and its output `completion_audit.txt` are in this folder. It was run on the tree at `ff65964`.

**Coverage**
- 390 of 390 graph–solver job records, all from attempt 1.
- 1,170 of 1,170 scheduled invocations recorded: 438 `completed`, 732 `cpu_timeout`.
- 0 `cpu_timeout_forced`, 0 errors, 0 missing, 0 infrastructure failures.

**Correctness**
- All 438 completed invocations were verified feasible and exited with code 0.
- Within each job, the completed policies' solution sizes agree in all 390 jobs.
- The completed sizes also agree across the three solvers on every graph that more than one solver solved (53 graphs have at least one completed result).

**Integrity and settings**
- All four executables and all six model files match the validated build in every record.
- Thread limits were 1 in every record.
- The frozen rotation was used: each of the six policy orders was used 21 or 22 times per solver.

**Learned policies were exercised**
- All 780 learned invocations recorded their model.
- Learned policies scored at least one decision on 116 of 130 graphs for Chen, 111 for Cao and 115 for LP.

## Compute

**Solver process CPU:** 371.27 h of the 585 h nominal ceiling.
- Cao (8): 116.49 h
- Chen (5): 126.97 h
- LP: 127.81 h

**Wall time:** 373.23 h summed over invocations; bench-job wall time totals 373.25 h.

**Cost:** standard GitHub-hosted runners on a public repository; no paid compute.

**CPU cap overshoot.** 17 of the 732 timeouts recorded 1.0–27.75 s of CPU above the 1,800 s cap (maximum 1,827.75 s, LP graph 46 linear). This is enforcement lag. These runs are still recorded as `cpu_timeout`, are treated as censored prefixes and are never used as solve times.

## Outcomes needing attention (recorded, not retried)

Solved-count differences between baseline and a learned policy occur only for Chen linear: 3 graphs solved by baseline were not solved by linear, and there were none the other way. Boost solved the same graphs as baseline for every solver.

| Graph | Baseline | Linear | Boost |
|---|---|---|---|
| 65 | solved, 18.9 s, 333,195 nodes | timeout, 22,992,294 nodes in prefix | solved, 10.0 s, 113,832 nodes |
| 68 | solved, 1,185.6 s | timeout | solved, 1,150.9 s |
| 88 | solved, 924.8 s | timeout | solved, 1,730.2 s |

Under the corrected tie rule (addendum `7159586`), the Chen linear configuration choice would have been λ=1e-5, not the frozen λ=1e-4. By prior decision, models were not changed, and nothing here was retried or re-tuned.

No correctness defect or measurement bug was found.
