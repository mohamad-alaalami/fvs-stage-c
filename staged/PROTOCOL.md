# Stage D: exhaustive first-pivot continuations

Input of record: Stage C run **44639720515**, experiment
`3244862ea2905ce24c811b962084c2b8a13310bd`, results branch commit
`eece4cfe803a97c47ca178c14caa6b71b1e962c3`, SEA upstream
`c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4`.
Stage C files, branches and artifacts are preserved. No model is trained.

## Validated workload

All **6502 states / 71038 candidates** are indexed with source paths, snapshot
and candidate SHA256, labels, scores, initial incumbent, event context, and
Stage C continuation results. Every state passed the archived native
SampleCheck (byte-equal restoration, reclassification and original selector).
The Python inventory independently checks binary FNV, candidate lists and IDs.

|Solver|States|Candidate continuations|
|---|---:|---:|
|Cao 8|1983|12684|
|Chen 5|2212|43773|
|LP|2307|14581|

Candidate counts range from 2 to 1531. Largest snapshot: 1,356,570 bytes.
128 candidates per job produces **555 jobs**, in three matrices of 185.
Each matrix is below 256. The three matrices run as sequential waves, each
capped at 20, enforcing at most 20 concurrent experiment jobs independently
of account-level limits.
CPU budget sum is 197.3278 hours; dividing by 20 gives 9.8664 hours **only as
an idealized upper-budget calculation**, not a wall-time prediction. Initialization,
publication, machine speed, queueing and CPU/wall differences remain.

## Correctness argument and first-pivot isolation

Cao candidates are maximum degWithDouble ties. Chen candidates are every
distinct STATUS_NONE vertex after compression hints exhaust, including lower
scores. Sol5's inherited branch body partitions feasible solutions into v in
the deletion set and v undeletable. It invokes the same general reductions,
component solvers and incumbent pruning on both sides; its step-in/out hooks
only maintain depth. No branch-body condition requires the selected vertex
to maximize its score or to satisfy the disjoint-forest premise. Thus the
implementation domain can be substituted without making the strict theoretical
set the eligibility rule. No Chen subset is excluded. The saved qualifying-state,
forest/component checks and strict merge count remain analysis attributes.

LP candidates are distinct undecided neighbors of the saved root at a genuine
solve2 neighbor branch. Deletion versus merging that neighbor into the undeletable
root partitions the possibilities. Pre-branch reductions have handled double
edges into the undeletable set; validation checks this premise. Root selection,
relaxation reductions, and later pivots remain the original implementation.

Each arm launches a fresh process, restores the exact same bytes and incumbent,
changes only the first pivot, and calls the original recursive procedures.
The first-child deletion and second-child undeletable/merge bodies are copied
verbatim in operation order from Stage C. The incumbent improved by child 1
is intentionally shared with child 2, as in the original solver. Across arms,
the incumbent is reset by restoration. Source hashes and binary hash identify
the one Stage D build reused by pilot and full experiment.

## Accounting and budgets

Nodes are recursive entries into branching/solve1/solve2, including components.
The already-reduced saved parent is not a new recursive node; its decision is
one branching decision. Therefore total nodes = child nodes summed, and total
decisions = 1 parent decision + child decisions (0 if stopped before the parent).
Parent setup/copy/instrumentation overhead is recorded separately so CPU and
wall reconcile with child measurements. Entire process CPU, including restore,
instrumentation, cleanup and output, is reported separately from continuation
CPU. The Stage C constructor-stop off-by-one is fixed by guarding before counting
node entry; this changes accounting only.

Every candidate, including the original, has a **10-second process CPU budget**.
GetProcessTimes is checked at solver guards (at most 1 ms between wall checks)
and externally every 5 ms. Cooperative unwinding retains final counters; actual
CPU reflects Windows timer granularity and stop latency, rather than being
clamped to 10. A 1-second emergency grace precedes forced termination; such
records use the last 100 ms checkpoint as an explicitly incomplete observed
prefix, never a complete total. Disk reserve is 3 GiB; a 4-hour driver deadline
leaves publication time within the 5-hour job limit. Unstarted arms and second
children have explicit statuses. Short .01-second forced-stop tests are pilot
validation only; all scheduled full arms use 10 seconds.

## Environment, comparison, and reporting

Use standard `windows-2025` runners, the same GCC 16.2.0 toolchain and flags as
Stage C (`-include string -std=c++11 -O3`, assertions on). Actual CPU model and
image version are recorded per arm. GitHub cannot guarantee identical hardware
across standard runners: comparisons require matching CPU model, image version
and executable hash; otherwise report unresolved_environment. This is especially
relevant for candidates split across jobs. No candidate is discarded for that.

Both complete: compare full nodes and process CPU, retaining ties and margins.
Only one completes: report completion-within-budget winner; do not assign a full
node rank across censored arms. Both time out: full-runtime and node ranking are
unknown; observed prefixes remain secondary data. Retries get unique UUIDs and
attempt directories; the report does not silently select among multiple attempts.
Per-state and per-graph records plus equal-graph averages keep hard graphs from
dominating a solver-level result. The first-state/reservoir selection and 64 KiB
Stage C slot exclusion remain explicit limits on inference.

## Durable storage and reproduction

No new Actions artifacts or caches are used. Build, pilot, chunks, raw ZIPs and
regenerable reports go to **stage-d-results/runs/<run_id>/**. Git branch records
have no automatic expiry. Existing Stage C Actions artifacts are untouched.
Per-arm raw files and failures live in each chunk's raw.zip, with records.jsonl
providing an index. The source snapshot remains on the immutable Stage C results
commit; Stage D references it by SHA256 rather than duplicating it per candidate.
Measured local test records average roughly 10 KiB per arm before Git compression
(raw ZIP + JSON index); a conservative 2 GiB results planning reserve covers
all 71038 arms, with no individual 128-arm chunk expected near GitHub's 100 MiB
file limit. The pilot records actual sizes for the final projection. Publication
retries preserve unique destinations and never overwrite an earlier attempt.

Regenerate: decompress staged/index.json.zz, then run
`python staged/report.py index.json <stage-d-results run directory> report`.
The pilot tests all candidates at a small saved state of each solver, original
digest replay, a difficult original and alternative, and forced timeout handling.
The full workflow is dispatched once only after pilot checks pass.
