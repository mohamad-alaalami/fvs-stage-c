# Stage C smoke-test protocol

Pinned source: c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4. The original checkout and checkpoint executables are preserved. Instrumented code lives in `src`; each instrumented build has a new directory, source hashes, build commands and executable hash. The compiler and `-include string -std=c++11 -O3` flags come from the verified checkpoint. Assertions remain enabled.

Only public graphs 095, 029, 076, 031, 002, 069, 089, 071, 014, 038 are scheduled, in that order; configurations are 8, 5, LP, in that order. Each pair runs baseline first, then instrumented, then verifies/audits/replays. The 130 hidden graphs are reserved. Guard checks use 095 only and are separated from experiment rows. No alternate pivots are tried.

## Decisions and candidates

An event is emitted immediately before executing the original two-child continuation. The three hooks are BranchingSolution::stageContinue (extracted without changing its branch bodies), HalfIntBranching::stageRoot, and HalfIntBranching::stageNeighbor. All component subsolvers use these same hooks. Reductions, approximation construction, and LP recursion after a relaxation reduction do not produce events. CubicSolver is the polynomial reduction solver, not one of the measured branch selectors.

- B: every actual decision at one of those hooks.
- Cao T: every actual Sol8 pivot. Candidates are every STATUS_NONE vertex whose `degree + doubleNum` equals the selected maximum score. Original index-order tie breaking remains unchanged.
- Chen T: a pivot returned by the fallback selector, after the hint loop has found no remaining eligible hint. The event distinguishes a returned hint from a fallback, rather than inferring this from the post-pop size of the hint list.
- Chen qualifying state: the STATUS_NONE induced multigraph is a forest; the STATUS_IN_SAFE induced multigraph is a forest; no undecided vertex has two edges into the same undeletable component (including a double edge); the stored union-find partition agrees with a freshly computed partition of the undeletable graph. These predicates are computed without mutating the original union-find. Every undecided vertex touching at least two distinct undeletable components is eligible in a qualifying state, regardless of score. Raw touch candidates, forest verdicts and individual invariant verdicts are logged even when qualification fails. Nonforest fallback states and undeletable invariant failures are reported separately.
- LP T: an actual neighbor branch in solve2's equality case. Candidates are distinct undecided neighbors in the root's existing adjacency order. The original pivot remains the unmodified getMaxDegNeigh result; its membership in the eligible set is logged. Root-selection branches count only toward B.
- A: T with at least two distinct eligible candidates. No candidate sampling.

Every event has a globally unique run-ID/sequence ID, graph, solver, phase, global recursion depth, upstream solver depth, component-subsolver flag, local pivot, original input vertex label, root where applicable, candidate labels/count and B/T/A flags. `depth` is recursive search-call depth, including component calls and LP reduction recursion; it is not claimed to be the number of prior branching decisions. Input labels survive nested component renumbering through a separate instrumentation-only map.

## Snapshots and replay

Every A event has one complete serialized local continuation state, appended to `snapshots.bin`. The event supplies its byte offset, byte length and FNV-1a checksum. No compression is used. Packing avoids millions of individual files; it does not omit any states. `snapshot.py` decodes states to JSON and checks structure.

The snapshot includes all Graph fields: N, M, deleted, changeInU, ordered adjacency, per-edge double flags, doubleNum, reciprocal adjacency positions, statuses, oldNumbers, solution vertices X, self-loop queue/list, ordered degree-2 queue, vis, ccNr, ccVertices, union-find representatives and weights, and original input labels. Solver fields include solFound, ordered branching_hints, incumbent sol, isSub, upstream depth, size_cap, the chosen hint/fallback flag, Cao br2, and LP kernelize_switch. Metadata includes solver type, phase, root, original selected local pivot, and recursion depth.

Restoration reconstructs these fields directly, checks byte-for-byte reserialization, and enters the original selected branch continuation without rerunning the selector or pre-branch reductions. The continuation includes both original children and all descendant component subsolvers. It compares the deterministic branch trace length, a 64-bit polynomial/FNV trace digest, and a full final-state FNV digest against the original continuation. This is a local-subtree replay, not restoration of the entire ancestor call stack or resumption of the whole run. The local state contains everything the subtree reads; ancestors are not consulted until it returns. The digest is a deterministic regression check, not a cryptographic equivalence proof.

The audit reads every A snapshot, not a sample. For replay it chooses a completed A continuation with at most 1000 decisions, preferring the largest such continuation in that run. It does not claim every snapshot has been replayed. Specific tested phases/component contexts and untested contexts must be reported. No A means no replay state for that run, not a failed test.

## Limits, durability, measurements

Each baseline and instrumented invocation has a 1800-second **process CPU** limit; there is no 30-minute wall-time substitution. Windows GetProcessTimes supplies kernel+user CPU. The external monitor polls every 50 ms and checks disk every second. The instrumented process checks its own CPU and disk at search/reduction entry, throttled to every 100 ms of wall time. CPU polling can overshoot slightly; observed CPU is retained.

Reserve: **10 GiB free** on the output volume. Launch and the external monitor use an additional 64 MiB headroom. Before each snapshot, the writer requires the reserve plus the entire snapshot size plus 1 MiB. Reserve-triggered stops halt the remaining schedule; rows for unstarted jobs are marked not run, never zero branches. There is no automatic compression/sampling/record-dropping fallback. Growth telemetry records snapshot and decision/continuation-log sizes with wall time and remaining disk space.

Snapshot bytes are flushed before their event record; event and continuation records are flushed after every write. Cooperative CPU/disk/interruption exceptions unwind scopes, mark unfinished continuations incomplete and write partial counters. The external monitor allows five seconds for cooperative stopping, then kills a nonresponsive process. Complete records remain available after hard termination; a trailing incomplete line is reported, not treated as a full event. A process kill cannot guarantee a final solver summary or a completed FVS.

Wall time starts before process creation and ends on observing completion; it includes startup and up to 50 ms monitoring latency but excludes verification/audit/replay. CPU includes instrumentation work in the solver process, but excludes the Python monitor and subsequent audit/replay. Peak working set comes from Windows GetProcessMemoryInfo. Very short CPU readings are quantized, so ratios near zero are not reliable performance measurements. Timeout pairs do not yield an uncensored full-run overhead ratio. No warmup runs are added.

## Verification and records

Both executables' completed outputs are checked for declared count, distinct valid IDs, and a forest after deletion. The original checkpoint Verifier is called with only graph and output, never an optimum-file argument. Supplied `.opt` sizes are compared separately; absent optima remain unknown. `.stats` and historical `.out` files are not optimum authorities. Completed baseline/instrumented runs must agree in returned size and feasibility; different optimal sets are allowed.

The audit recomputes B/T/A from event records, checks B >= T >= A, compares against the native summary, and requires readable snapshots for every A. `runs/<unique-id>` holds all raw records. `invocations.jsonl` is append-only, including retries, replay calls and interrupted runs. `results.csv` and `pairs.json` are the current one-row-per-pair summary; superseded summaries are archived before maintenance retries. The initial build naming collision, subsequent disk-accounting repair, and maintenance stop are retained in their build/history directories. The maintenance stop was initiated by the agent, not requested by the user.

`total_bytes` in the pair summary means uncompressed snapshots plus event and continuation logs. It excludes small telemetry, verifier output, metadata, executables, replay artifacts and superseded attempts; final reporting must distinguish this payload total from whole-directory storage. Snapshot mean bytes divides snapshot bytes by count; zero snapshots is not applicable, never division by zero.
