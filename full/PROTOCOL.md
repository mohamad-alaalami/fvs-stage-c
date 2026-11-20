# Stage C full run: protocol

This is a separate experiment from the 10-graph smoke test (`stagec/`, `.github/workflows/stage-c.yml`, tag `stage-c-smoke`, run 44630346885). The smoke test's code, runs and artifacts are not modified.

## Scope

- **Graphs:** all 100 `tests/pace-16open` graphs, taken from `records/local-checkpoint/dataset_inventory.csv`. `full/schedule.py` asserts 100 distinct public graphs, 300 distinct pairs, and that the 130 `pace16-hidden` graphs are absent. The hidden graphs are never run.
- **Solvers:** `8` (Sol8, Cao), `5` (Sol5, Chen-style), `LP` (HalfIntBranching, Imanishi–Iwata-style). The original pivot, tie-breaking, child order, reductions and pruning are unchanged; the hooks only observe.
- **Source and build:** upstream `c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4`, built once per workflow run by the `build` job. The toolchain is w64devkit 2.11.0, GCC 16.2.0, SHA-256-checked, with flags `-include string -std=c++11 -O3` and assertions on. The original solver and `Verifier` are built from the untouched pinned source. The instrumented solver comes from `full/prepare.py`, which applies the smoke edits unchanged and adds node hooks. `build_record.json` holds source hashes, tool hashes and executable hashes; every pair re-checks the executable hashes.
- **Jobs:** one GitHub-hosted `windows-latest` job per pair, as two matrices of 150 (GitHub caps a matrix at 256 jobs). Each matrix has `max-parallel: 20`, the Free plan's total concurrency for standard runners; jobs beyond that queue. Each job runs the original solver, then the instrumented solver, on the same runner and input, each with its own **1,800 s process-CPU** limit (`GetProcessTimes`, polled every 50 ms). Wall time is recorded separately. Each pair's `environment.json` records the execution runner's CPU model and image.

## Counting definitions

A **decision** is an actual two-child branch about to run: `BranchingSolution::stageContinue` (Sol8/Sol5, main search and component subsolvers alike), `HalfIntBranching::stageRoot` (solve1) and `HalfIntBranching::stageNeighbor` (solve2). Reductions, the approximation, CubicSolver, and LP relaxation-reduction recursion are not decisions.

- **B:** every decision.
- **T:** a decision at the selector under study.
- **A:** a T decision with at least 2 distinct eligible pivots.
- **Cao (8):** T = every Sol8 pivot. Eligible = every STATUS_NONE vertex whose `degWithDouble` equals the maximum over STATUS_NONE vertices, which is the score `Graph::getMaxDegVWDouble` maximizes, double edges included.
- **Chen (5):** the pinned `ICBranchingSolution::chooseBranchingVertex` pops `branching_hints` until it finds a usable (STATUS_NONE) hint. Only when the hints run out does it call `Graph::getMaxDegToUndeletable`. That function scans **every STATUS_NONE vertex**, ranking by number of adjacency entries into U, then by `degWithDouble`. Any undecided vertex can win, and the function does not require touching two components.
  - T = a fallback decision.
  - Implementation-level **A** = a fallback with at least 2 vertices in that domain (all STATUS_NONE, lower-scoring ones included). `pivot_eligible` confirms that the original pivot is in the domain.
  - Separately named **`A_chen_strict_merge`**: a fallback whose state is qualifying (undecided graph a forest; undeletable graph a forest; no undecided vertex with two edges into one undeletable component; stored union-find partition equal to a fresh one), **and** which has at least 2 undecided vertices that each touch at least 2 distinct undeletable components. This is the smoke test's old A.
  - Individual verdict counters are kept under `chen:*`.
- **LP:** T = a `solve2` neighbor branch. Eligible = distinct STATUS_NONE neighbors of the current root, in adjacency order, including lower-scoring ones; the pivot is `getMaxDegNeigh`, checked for membership. Root-selection branches (`solve1`) count toward B only.

**Depth convention:** `depth` = number of enclosing search-procedure frames (`branching`/`solve1`/`solve2`), with the root call at depth 0. It includes component-subsolver frames and LP reduction-recursion/delegation frames, so it is recursive call depth, not the number of earlier decisions. `solver_depth` = upstream `BranchingSolution::depth` (branch steps within the current solver instance). LP never changes `solver_depth`, so it stays 0 there.

**Per-pair exact outputs** (`summary.json` of the instrumented invocation):
- B, T, A, `A_chen_strict_merge`, `component_B`;
- phase counts and `chen:*` counters;
- histograms `B_by_depth:<phase>`, `B_by_solver_depth:<phase>`, `A_by_depth:<phase>` and `T_candidate_count:<phase>`, plus `chen_merge_candidate_count` and `A_chen_strict_merge_by_depth`;
- a trace digest over the decision sequence.

Every observed decision is counted, saved or not. On a CPU stop the solver unwinds cooperatively and writes the final summary of the observed prefix (`counts_source=final`, status `cpu_timeout`). A checkpoint written every 30 s (`summary.partial.json`) covers a hard kill. A measured zero is 0; a missing record is `missing`.

## Search nodes

A **node** is one entry to `branching()` (Sol8/Sol5) or `solve1()`/`solve2()` (LP), counted as main or component (`isSub`). Each node has exactly one outcome:

- `branch`: a decision follows. The `branch` outcomes summed equal B.
- `leaf_solution`: this node's own `reduce()` reached an empty graph and called `trySolUpdate`.
- `pruned`: any other `reduce()` → RED_NOSOLUTION. This covers the size cap, `impossible()` (Sol8's `br2` rule), an infeasible component, and LP's double-edge bound and kernelize.
- `no_pivot`: the selector returned -1.
- `delegate_to_solve1`: LP solve2 with a root of degree 0; the following solve1 is its own node.
- `reduction_recursion`: LP solve2 after a relaxation reduction; the following solve2 is its own node and is not a decision.
- `interrupted`: unwinding after a CPU, disk or external stop.

Component subsolver roots are nodes of the subsolver. The original executable emits no counters (it prints only the solution), so `baseline.node_count` = `unavailable`. Node counts come only from the instrumented invocation, under that invocation's run ID and build ID. They are never paired with baseline timing as if from one invocation.

## Replay states

- **Saved:** the first A state of the pair (cap **2 MiB**), plus an Algorithm R reservoir of **K = 32** over later A states. The i-th later A event fills slot i−1 when i ≤ K. Otherwise r = splitmix64(seed + i) mod i, and the event replaces slot r if r < K. The **seed is 20261120**.
- **Size exclusions:** a selected state over the **64 KiB** slot cap is excluded and counted (`excluded_for_size`, `largest_excluded_bytes`, the first 1,000 excluded sequences), and that slot keeps its previous state. A first state that doesn't fit is recorded as `first_A_unsaved_bytes`.
- **Budget:** state bytes plus 4 bytes per candidate. Worst case per pair is 2 MiB + 32 × 64 KiB = 4 MiB raw, and 300 pairs × 4 MiB = **1.17 GiB raw worst case**, stored zlib-9 (verified round trip).
- **Contents:** each state is the smoke schema `STAGEC1`, with the full reduced graph, statuses, double edges, queues, union-find, incumbent `sol`, `size_cap`, hints in order, Sol8 `br2`, LP `kernelize_switch`, the original pivot and root, and input labels. Each also records its eligible candidate list (int32 local indices), the event description, and its continuation result (trace count, digest, final-state hash, complete flag).
- **Checks:** `SampleCheck` checks every saved state. It restores and re-serializes (byte-equal), re-derives the classification and the exact candidate list, and re-runs the original selector on the restored state, confirming the recorded pivot.
- **Replay:** up to 3 saved states with a complete continuation of at most 200,000 decisions (the first A state first, then the largest) are replayed with the **original pivot** under the original continuation, and compared on trace count, digest and final-state hash. States without a complete continuation (for example, cut off by a timeout) are reported as untested in `replay.coverage`. No alternative pivots are tried.

## Storage and cost

- **Compute:** standard GitHub-hosted runners are free in public repositories (GitHub billing docs). This account's usage API shows the smoke run's Windows minutes fully discounted, with $0 net.
- **Records:** the full run uses **no Actions artifacts**. GitHub's docs don't establish whether public-repo artifacts count against the Free plan's 500 MB allowance, and the smoke run already holds about 2.7 GB. All full-run records (schedule, build, every pair, report) are committed to the `full-results` branch of this public repo under `runs/<run_id>/`. Git repository storage is not billed, and branch contents do not expire. Re-run jobs write to `attempt-<n>/`, so earlier attempts are kept.
- **Disk:** runner free disk (about 220 GiB observed on D:) is separate from retained storage. The solver also keeps a 3 GiB free-disk reserve guard.

## Dispatch history

- **Run 44638350321** (commit 0562031) was cancelled by the operator minutes after it started. Every started pair job failed in "Fetch the build of this run": Git Bash path conversion rewrote the sparse-checkout patterns, so the build directory was never checked out (`cp: cannot stat .../build`). **No pair invocation ran**, so no measurement exists from that run. Its schedule, build and an all-`missing` report remain on `full-results` under `runs/44638350321/` as a record of the attempt.
- The fix (`MSYS_NO_PATHCONV=1`) was tested locally against the real branch: the sparse fetch worked, the executable hash matched the build record, and two concurrent `publish.sh` pushes into a local copy of the branch both landed, one after a retry.
- **Run 44639066875** (commit 3caa335) was cancelled by the operator about 3 minutes after its pair jobs started. Pairs ran correctly, but 3 of the first 9 lost their push race. The `git pull --rebase` retry then failed with "Committer identity unknown", because the bot identity had been passed only to the first commit, so those 3 pairs' records (002/8, 005/8, 003/5) were not committed. The 6 pairs it did commit are preserved under `runs/44639066875/`; they are a superseded attempt.
- **Fix:** `publish.sh` now sets the identity in the clone's config. It was tested locally with no global or system git identity, using 4 concurrent publishers into a local copy of the branch: all 4 records landed, 3 of them after a rebase. A fallback step now keeps a pair's small records as an Actions artifact (`unpublished-<graph>-<solver>-attempt-<n>`) only if publishing still fails. The experiment was then dispatched again; that run is the experiment of record.

## Known limitations observed during run 44639720515 (documented, not corrected mid-run)

1. **Stop inside node entry (node-outcome off-by-one).** `StageFrame`'s constructor counts the node as entered and then calls `StageC::guard()`. If the CPU, disk or external stop is raised by that particular guard call, C++ does not run the destructor of an object that never finished constructing, so this one node receives no `interrupted` outcome. Entered nodes then exceed recorded outcomes by exactly 1, and the stored check `every_node_has_one_outcome` is `false`, although every other count (B, T, A, histograms, sampling) is unaffected. `full/audit_branch.py` classifies a pair as `stop_inside_node_entry` when this is the only failed check, the gap is exactly 1, and the instrumented run did not complete. A future build should count the entry only after `guard()` returns.
2. **Chen instrumentation overhead.** On every fallback, the Chen classification also runs the strict-merge check: union-find over the undeletable and undecided graphs plus touch sets, O(N + M). Where both Chen runs completed, instrumented CPU was a median of about 1.5× the baseline, at most about 2.6×. On at least one pair (014/5: baseline completed in 336 s) the instrumented run reached the 1,800 s limit, so its counts cover only the observed prefix. Such pairs are listed as "baseline completed, instrumented cpu_timeout". Cao and LP overheads were about 1.1×.
3. **Size exclusions in the reservoir.** On larger reduced graphs, many selected A states exceed the 64 KiB slot cap and are excluded (counted in `excluded_for_size`), so those pairs keep few reservoir states. A first A state above 2 MiB is not saved (`first_A_unsaved_bytes`).
4. **Replay coverage.** Pairs whose saved states have no complete continuation within 200,000 decisions (typically when the search was stopped by the CPU limit before any saved subtree finished) report `untested_no_complete_continuation_within_cap`.

## Validation before launch (laptop; same toolchain and flags)

- **095, all solvers:** every decision matches the smoke event records field by field (40/40: sequence, phase, depth, solver depth, component flag, original pivot, T). Cao and LP also match on candidate count and A (B/T/A = 3/3/1 and 21/17/17). For Chen, B = 16 and T = 10. The strict count, merge-candidate counts and qualifying verdicts equal the smoke values (A_strict = 0). The implementation-level A = 10, with domain sizes of 3–15 undecided vertices.
- **Limit:** the smoke 095 Chen records have no saved states (old A = 0) and no domain sizes. The domain evidence therefore comes from the 10 newly saved fallback states, on which the re-run `getMaxDegToUndeletable` returned the recorded pivot every time.
- **Checks passed:** all consistency checks, every sample check, and replay checks for all three solvers.
- **Stress tests on 029** with 20 s / 15 s CPU limits: Cao 792,073 decisions, Chen 3,480,443, LP 4,256,711. All consistency checks passed and saved state stayed at 10–15 KB per pair. Cao instrumented throughput was about 40k decisions per CPU-second, against about 27k in the smoke test's save-everything mode.
