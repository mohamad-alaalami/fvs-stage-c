# Integration v1: frozen learned pivot policies inside the complete solvers

Status: **implementation and public validation. The reserved benchmark is prepared but NOT dispatched.** The graph set and the compute budget below need owner approval.

## Question

For each exact FVS solver (Cao/Sol8 `8`, Chen-style/Sol5 `5`, Imanishi–Iwata-style/HalfIntBranching `LP`), the experiment compares three policies:

- the original pivot selector;
- the solver's own frozen linear ranker;
- the solver's own frozen boosted-tree ranker.

We measure whether using a learned policy at **every** eligible decision of a complete solve changes solved count, search nodes, process CPU time and wall time. The learned runs include the cost of loading the model, computing features and scoring. No single outcome is designated as the success metric.

This differs from Stage D, which substituted one pivot per saved state and then resumed the original policy. Here the policy is called at every eligible decision, including decisions reached because of earlier learned choices and decisions inside component subsolvers.

- **One choice per decision:** the model picks one pivot, and the solver explores that pivot's original two children in their original order.
- **No fallback:** there is no "try the next-ranked pivot".
- **No refitting:** nothing is retrained, retuned or reselected, and the two learned families are separate alternatives.

## Sources of truth (pinned)

| Item | Reference |
|---|---|
| Solver source | karek/FeedbackVertexSet-Experiments `c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4` (`src/`) |
| Eligibility and original order | Stage C `full/StageC.cpp` (`StageC::analyze`) at `3244862`/`4cf65df`; Stage D `staged/PROTOCOL.md` at `4cf65df9de3af1aacbece3820e2986c0fd2b5620` |
| Saved public states | Stage C run 44639720515, records `eece4cfe803a97c47ca178c14caa6b71b1e962c3` (6,502 states, 71,038 candidates) |
| Feature definitions | `learnability/features.py`, `learnability/FEATURES.md` (extraction schema v1); extraction `extract-v1-20261124T115559Z-833e6421` |
| Training, scorer and tie rule | `learnability/train/` at `27c43b7ac77dfd06c5c224e959ea99f61d29923a` (`PROTOCOL.md`, `transforms.py`, `boost.py`, `evaluate.select`) |
| Models | `integration/models/`: the six final public-data refits, copied byte for byte from `learnability-results@e5b840104e1bca378d3bbeeaed795f72dfbad951:runs/45408454796/attempt-1/final/<solver>/<family>/final/`, with SHA-256 in `MODELS.json`, checked by every build and every invocation |

The six models are: Cao linear λ=0.1, Cao boost depth 2 / 50 rounds, Chen linear λ=1e-4, Chen boost depth 3 / 200 rounds, LP linear λ=0.01, LP boost depth 3 / 200 rounds. Fold and ablation models are not used.

## The intervention (`integration/prepare.py`; reviewable diff `integration.patch` in every build record)

The integrated source is a copy of the pinned `src/`. Each edit is an asserted single-occurrence substitution. Exactly three selector sites become policy-controlled. In each one the pinned selector runs first and its result, the **original pivot** v0, is passed to the hook:

| Solver | Site | Eligible pivots (archived order) | Original pivot v0 |
|---|---|---|---|
| Cao (8) | `Sol8::chooseBranchingVertex` | undecided (STATUS_NONE) vertices whose `degWithDouble` equals the maximum, ascending index | `Graph::getMaxDegVWDouble` (lowest-index maximum) |
| Chen (5) | the `ICBranchingSolution::chooseBranchingVertex` fallback, only after the compression hints are exhausted | **every** undecided vertex, ascending index, including lower-scoring ones; the strict component-merging diagnostic is not the eligibility rule | `Graph::getMaxDegToUndeletable` |
| LP | the `HalfIntBranching::solve2` neighbour branch (all-half relaxation case) | distinct undecided neighbours of the current root s, in root adjacency order | `Graph::getMaxDegNeigh(s)` |

Everything else is the pinned code: reductions, pruning, incumbent updates, component handling, recursion, child construction, child order, Sol5's hint path and LP's root selection (`solve1`) and relaxation reductions.

- **When the model is called:** only when at least two distinct eligible pivots exist. Otherwise v0 is used.
- **Selection:** the highest model score wins. On an exact tie, v0 wins if it is among the maxima; otherwise the earliest maximum in archived order.
- **Explicit errors:** a non-finite score, a v0 that is not eligible, a model that fails to load or verify, or a component subsolver without the policy each stop the run with an explicit error status (`policy_error`, exit 71 or 72). The run is never silently completed with the baseline policy.
- **Component subsolvers:** they are created only by `BranchingSolution::reduceConnectedComponents` through `clone()`. The single added line `s->policy = policy;` hands them the same policy. Every slow-path hook checks that the policy is present, so a missing propagation is an error rather than a silent baseline.
- **Policy choice:** at process start from `FVSB_POLICY`. All three variants run the **same executable** with the same command line `FvsIntegrated.exe <solver> < graph`.
- **Timed baseline:** each hook reduces to counting the decision and returning v0. No candidate is enumerated, no feature is computed and no model is loaded.

### Features and scoring (`integration/native/FvsPolicy.cpp`)

Features are computed from the live reduced state immediately before selection, exactly as `learnability/features.py` defines them:

- active vertices have status 0 or 1;
- N(v) is the set of distinct active neighbours u ≠ v, and a double-flagged entry counts twice;
- w(v) = |N(v)| plus the number of flagged neighbours;
- neighbour summaries (minimum, mean as integer sum divided by count in float64, maximum) are taken over undecided neighbours, with 0.0 for an empty set;
- state counts are taken over active vertices;
- the remaining threshold is `size_cap − |X|` of the current (sub)solver;
- the LP root-common-neighbour feature is |N(v) ∩ N(root)|.

The model inputs are exactly the frozen allowlists (12/12/11) in the export's `input_order`. Loading fails if they differ.

**Linear model.** The export's base standardisation (population std; a zero-std column maps to 0) is applied, then the candidate × context products in candidate-major order, standardised again. The score is s = Σ θ_j φ_j accumulated left to right in the saved φ order.

**Boosted trees.** XGBoost 2.1.3 JSON semantics:

- inputs are converted to float32;
- a numerical split goes left iff x < condition (no missing values occur);
- leaf values are accumulated in float32 in tree order from base_score 0;
- the float32 margin is widened exactly to double.

**Numerical finding (diagnostic, not a policy change).** The batched numpy product `transform(X) @ theta`, used by the offline evaluation, is position-dependent at the 1e-15 level: bit-identical feature rows can receive scores that differ by one ulp. That breaks exact model ties by row position rather than by the frozen rule. The live scorer is a pure function of each candidate's features, so identical candidates tie exactly and the frozen tie rule applies as written. The replay check reports how often the two differ, and requires every difference to be explained by bit-identical candidate rows.

## Exactness and running-time guarantees

All three solvers branch on a pivot v with child 1 "v in the solution" and child 2 "v undeletable" (for LP, "merge v into the undeletable root"). For any feasible solution F consistent with the current partial assignment, either v ∈ F or v ∉ F. The two children therefore partition the solutions for **any** undecided v, and the incumbent bound `|X| ≥ size_cap` prunes only non-improving nodes, whichever v is chosen. Exhaustiveness can only be lost through a pruning rule whose validity depends on how v was chosen.

**Cao (8).**
- **Pivot-dependent rule:** Sol8 adds `impossible(): br2 ≥ 2·size_cap`, where `br2` counts undeletable branches on the current path. This bound comes from Cao's analysis of maximum-degree branching. The only pivot-dependent premise it can use is that each branching vertex maximises the branching score (`degWithDouble`) over undecided vertices at its decision.
- **Why the substitution is safe:** every allowed substitute is such a maximiser. The tie-break by vertex index is the only thing that changes, and no graph-theoretic argument can depend on vertex indices.
- **Exactness:** the learned Cao policies are therefore exact whenever the pinned Cao implementation is. We do not re-prove the upstream bound. The oracle check also randomises tie choices.
- **Running time:** the O*(8^k)-type guarantee likewise needs only maximum-degree branching, so it is preserved.

**Chen (5).**
- **No pivot-dependent pruning:** `impossible()` is the default `false`, and the reductions (simple rules plus component splitting) are properties of the state.
- **Exactness:** any undecided pivot gives an exhaustive partition, so every fallback substitution, including lower-scoring vertices, preserves exactness.
- **Running time:** the published O*(5^k)-type analysis needs pivots with the strict disjoint-forest / component-merging property. The pinned fallback already ignores that property at most decisions: Stage C measured `A_chen_strict_merge` = 0.24% of target decisions. Neither the original implementation nor the learned policies carry that worst-case guarantee at fallback decisions, and no runtime claim is made.

**LP.**
- **Exhaustive branch:** at an actual neighbour branch the root s is undeletable. For an undecided neighbour v, either v ∈ F, or v ∉ F and then v and s are adjacent undeletable vertices whose contraction (`merge`, which also deletes vertices with double edges into the merged root) preserves the solution set.
- **State-only pruning:** the pruning and reduction rules (`highTotalDoubleCnt`, `reduceTooManyDouble`, `kernelize`, the relaxation reductions) depend on the state and the remaining budget, not on which neighbour was chosen.
- **Exactness:** exactness holds for every eligible neighbour. If the original pivot is not an undecided neighbour, that is an explicit error in learned mode; diagnostic mode counts such cases and none were seen.
- **Running time:** as we read Imanishi–Iwata, their analysis branches on an arbitrary neighbour of the undeletable root, so the guarantee should carry over. We do not re-derive it and claim only exactness.

**Verdict:** no solver's exactness is blocked. The Cao result is conditional on the pinned upstream pruning rule (premise: maximality only).

## Measurement (identical for every policy; `integration/invoke.py`)

- **Wall time:** `time.perf_counter()` immediately before `Popen`, to immediately after `wait()` returns.
- **Process CPU:** `GetProcessTimes` kernel+user of the whole solver process after exit. This covers loader, input parsing, model loading, search, feature extraction, scoring, output and the summary write. In-process phase times are recorded too.
- **CPU limit:** an independent per-invocation process-CPU limit.
  - The search guard reads `GetTickCount64` at every node and `reduce()` iteration. It checks `GetProcessTimes` and an external STOP file at most every 10 ms of wall time.
  - At the limit the run stops cooperatively with final counters for the observed prefix (`cpu_timeout`). The driver kills the process at limit + 30 s (`cpu_timeout_forced`, with counters from the last 60-second checkpoint).
  - The wall watchdog (1.25·limit + 120 s) is an infrastructure failure.
- **Nodes:** entries to `branching()`, `solve1()` and `solve2()`, component subsolvers included. This is the Stage C definition, checked to be equal for the baseline.
- **Decisions:**
  - B: actual two-child branches.
  - T: decisions at the studied selector.
  - A, eligible: T with at least two eligible pivots. A is measured only when candidates are enumerated (learned or diagnostic runs), and is `null` in the timed baseline.
  - Scored: model invocations.
  - Departures: scored decisions with chosen ≠ v0 at the current state.
  - Also recorded: scored decisions in component subsolvers, scored decisions after the first departure, and an FNV pivot-trace digest over (phase, depth, pivot) of every decision.
- **Statuses:** `completed`, `cpu_timeout`, `cpu_timeout_forced`, `solver_error`, `policy_error`, `configuration_error`, `verification_failed` (results); `wall_watchdog`, `not_run_job_deadline`, `driver_error`, `missing_record`, `build_mismatch` (infrastructure).
- **Verification:**
  - **Feasibility:** declared size, distinct valid IDs, and the remaining multigraph is a forest (a repeated edge is a 2-cycle), plus the upstream Verifier.
  - **Size:** compared with a trusted optimum when one is available (public `.opt` files; on reserved graphs, the agreement of all completed policies). Feasibility alone does not prove optimality.
- **Timed baseline vs pristine binary:** they differ only by counter increments, the tick check, the pivot-trace hash and the summary write. The overhead check measures this on a predefined subset.
- **Diagnostic mode** (`FVSB_DIAG=1`) adds candidate enumeration in the baseline, the Stage C trace digest, feature and scoring timers, and optional state dumps. It is used only in public checks, never for primary timing.

## Public acceptance checks (`integration-public.yml`; public data only)

| Check | Expected coverage | Pass criterion |
|---|---|---|
| Replay (`replay_check.py`) | all 6,502 saved states / 71,038 candidates | Exact agreement on candidate membership and order, original pivot (snapshot and table), and every feature (Python extractor and extraction table). Boost scores bit-identical to xgboost 2.1.3. Linear scores bit-identical to the per-candidate evaluation of the frozen export, and within 1e-9 of numpy batched. Selected pivot and tie count identical to the reference selection. |
| Baseline (`checks.py baseline`) | every Stage C pair with both runs completed and instrumented CPU ≤ 60 s | Timed and diagnostic baseline output byte-identical to the pristine pinned binary; nodes, B, T equal to Stage C; A and the Stage C trace digest equal (diagnostic); timed baseline enumerates nothing |
| Oracle (`checks.py oracle`) | 240 seeded generated graphs (G(n,p), multi-edge, block and dense families, n ≤ 16) + `tests/simple` × 3 solvers × {pristine, baseline, linear, boost, 3 seeded random-eligible test policies} | every run completed, feasible and equal to the brute-force optimum; learned policies scored and departed |
| Suite (`checks.py suite`) | 34 fixed public graphs including 003 (optimum 10) × 3 solvers × {pristine, baseline, linear, boost}, 600 s CPU each | every completed run feasible and optimal; baseline identical to pristine; learned timeouts reported as performance observations |
| Live (`checks.py live`) | dumped live states of 12 graph–solver runs × 2 families, including states after departures and in subsolvers | features, scores and selections exactly reproduced by the Python reference |
| Overhead (`checks.py overhead`) | 6 predefined public cases × 3 interleaved repetitions | measured and reported |
| Fixture (`fixture_bench.py`) and dry run | public jobs with short CPU limits: timeouts, injected watchdog, model, policy, output and record faults, retry attempt; dry run of the reserved job layout and publishing | all fixture assertions true; report generated |
| Unit (`run_unit.py`) | schedule, report categories and zero handling, solution checks, model hashes, source edits | all pass |

The public checks validate correctness and measurement. Nothing in them is used to change the learned policies.

## Final benchmark (prepared, not dispatched; `integration-reserved.yml`, `integration/benchmark/MANIFEST.json`)

- **Graph set (proposed):** all 130 graphs of `tests/pace16-hidden` at the pinned upstream commit. IDs are listed (names only) inside the dispatched workflow; each job checks out only its own graph file.
- **Budget (proposed):** 130 graphs × 3 solvers × 3 policies = **1,170 invocations**, each with an independent **1,800 s process-CPU** limit, for at most **585 solver CPU-hours** before setup, verification or retries.
- **Layout:**
  - one job per (solver, graph) on `windows-2025`, running the three policies **sequentially** in the scheduled order on the same runner;
  - three static 130-job matrices with max-parallel 7/7/6 (at most 20 concurrent jobs, the Free-plan limit);
  - per-invocation wall watchdog 2,370 s, job timeout 149 min (3 × 2,370 s + setup and publish headroom).
- **Runner minutes:**
  - worst case about 50,100 runner-minutes, if every invocation reaches the limit and the watchdog;
  - CPU-bound lower bound at full concurrency about 29 h of wall time, worst case about 42 h;
  - standard runners are free for this public repository.
- **Timing repetitions (optional, separately approved, off by default):** 2 rotated repetitions for jobs in which all three policies finish in under 60 s CPU. At most 2,340 extra invocations, 39 CPU-hours.
- **Policy order:** graphs of each solver are ranked by SHA-256(`integration-v1|order|<solver>|<graph_id>`) and the graph of rank r uses `PERMS[r mod 6]`. PERMS is the three cyclic rotations followed by the three reversed rotations. Every order is used ⌊n/6⌋ or ⌈n/6⌉ times, and every policy sits in every position within one of n/3 times.
- **Identical conditions:** one validated build (the public validation run's recorded build, hash-checked), identical inputs, budgets, thread limits and measurement boundaries. Each record holds runner, CPU model, image, executable and model hashes.
- **Retry rule (fixed now):**
  - Only infrastructure failures are retried: watchdog, deadline, driver error, missing record, build mismatch, runner loss or a failed publish.
  - The whole job (all three policies, same order) is re-run as a new attempt via "Re-run failed jobs", at most twice.
  - Analysis uses the first attempt without an infrastructure failure and never mixes attempts.
  - Timeouts and solver, policy or verification failures are results and are never retried.
  - Every attempt is preserved under `runs/<run_id>/jobs/<solver>/<graph>/attempt-<n>/`.
- **Report (`report.py`):** per solver, baseline vs linear and baseline vs boost separately.
  - Per-graph rows (CSV).
  - Solved counts: both, baseline only, learned only, both timed out, errors, verification failures, size disagreements and infrastructure failures.
  - Node, CPU and wall differences and ratios on jointly solved pairs only. A ratio is defined only when both values are > 0.
  - Geometric-mean ratio with a 95% graph bootstrap, plus medians, totals and win/equal/loss counts.
  - Timeouts appear only as observed prefixes. The jointly solved subset is reported apart from the full 130.
- **Dispatch:** see `integration/DISPATCH.md`. The owner must approve the manifest token. GitHub requires a `workflow_dispatch` workflow to exist on the default branch, which this work does not modify, so the dispatch steps include that owner action.

## Limitations

- The public checks cannot predict reserved-graph performance. The offline training data (Stage C/D states) are a selected sample.
- Single runs on shared GitHub-hosted hardware carry timing noise. Pairing on one runner and the order rotation control the main biases but do not remove the noise; the optional repetitions estimate it on short solves.
- The Cao exactness argument relies on the pinned upstream pruning rule. Chen's fallback carries no worst-case guarantee in either the original or the learned policies.

## Public validation history

- **Run 45490269433 (commit 16d4f27), cancelled by the operator.**
  - **Bug:** relative `--out` paths were passed to the solver unchanged, while the solver runs with its run directory as working directory. `FVSB_SUMMARY`, the dump file and the STOP file were therefore written to the wrong place, and every invocation in the graph-running checks was classified `driver_error`.
  - **What still passed:** the replay check (all 6,502 states) and the unit tests, which do not use those paths. The 12 concurrent dry-run publishes all landed, exercising the publish retry path.
  - **Records:** preserved on `integration-results` under `runs/45490269433/` as a superseded attempt.
  - **Fix:** `invoke.run` resolves the run directory, the graph and every `FVSB_*` path to absolute paths. This was verified locally with relative paths, matching CI.
- **Run 45491182988 (commit 0189aa8), cancelled by the operator.**
  - **Bug:** `bench.py` computed run-directory paths relative to an unresolved relative `--out`, which raised an error after each dry-run job. The fixture check was exposed to the same bug.
  - **Records:** preserved under `runs/45491182988/`.
  - **Fix:** every driver (`bench.py`, `checks.py`, `fixture_bench.py`, `replay_check.py`) resolves its input and output paths. This was verified locally with CI-style relative paths: the bench job, the full fixture exercise (13/13 assertions), and the baseline, oracle and validation aggregation.
