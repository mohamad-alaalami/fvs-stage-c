# Stage C smoke-test results

Current summary: 3/30 solver/graph pairs. See PROTOCOL.md for definitions and measurement limits.

| Graph | Solver | Status | B | T | A | Snapshots | Total bytes | Bytes/snapshot | CPU overhead | Replay |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 095 | 8 | completed | 3 | 3 | 1 | 1 | 6,309 | 5,008 | below timer resolution for a useful ratio | pass |
| 095 | 5 | completed | 16 | 10 | 0 | 0 | 8,075 | not_applicable | below timer resolution for a useful ratio | not_applicable_zero_A |
| 095 | LP | completed | 21 | 17 | 17 | 17 | 85,841 | 4,393 | below timer resolution for a useful ratio | pass |

Totals: B=40, T=30, A=18, snapshot_count=18, snapshot_bytes=79,696, log_bytes=20,529, total_bytes=100,225, baseline_cpu_s=0, instrumented_cpu_s=0, baseline_wall_s=1, instrumented_wall_s=1.

All run-directory files, including retries, replay checks and metadata: 183,024 bytes. Payload totals above count snapshots and decision/continuation logs only.

Largest payload run: 095/LP, 85,841 bytes.
Largest individual snapshot: 095/8, 5,008 bytes.

## Verification and replay coverage

- Solver 8: 1 A events; 1 replay checks passed. Tested contexts: [{'phase': 'cao_max_degree', 'component_subsolver': False}]. Other phases/component contexts and all unselected A snapshots are not replay-tested. Snapshot readability is checked for every recorded A event.
- Solver 5: 0 A events; 0 replay checks passed. Tested contexts: []. Other phases/component contexts and all unselected A snapshots are not replay-tested. Snapshot readability is checked for every recorded A event.
- Solver LP: 17 A events; 1 replay checks passed. Tested contexts: [{'phase': 'lp_neighbor', 'component_subsolver': False}]. Other phases/component contexts and all unselected A snapshots are not replay-tested. Snapshot readability is checked for every recorded A event.

## Storage implications

A purely linear extrapolation from ten equally representative public graphs to all 100 would multiply payload storage by ten: 1,002,250 bytes from the current measured total. This is a scenario, not a forecast or an upper bound.
It assumes the same solver mix, original policies, snapshot schema, uncompressed encoding, CPU budget, and comparable distributions of branch counts, ambiguity rates, and reduced-state sizes. These ten graphs were deliberately ordered and are not a random sample. Timeouts and disk stops censor the search; incomplete runs give lower bounds on storage for complete searches. Different instrumentation overhead also changes how far a CPU-limited run reaches. Snapshot size alone cannot predict storage: A frequency and search-tree size dominate. Whole-directory storage also includes telemetry, metadata, build products, retries and replay evidence.

## Files

- results.csv: one current row per solver/graph, including both CPU/wall times, statuses, verification, counts, storage and replay status.
- invocations.jsonl: append-only invocation records, including maintenance attempts and replay invocations.
- runs/<ID>/: raw stdout/stderr, verifier output, events.jsonl, snapshots.bin, continuations.jsonl, telemetry, verification.json, audit.json and run.json.
- build_record.json and build-*/: instrumented build provenance and logs; baseline provenance is in ../checkpoint/build_record.json.
- snapshot.py: full binary-state decoder. Example: python snapshot.py SNAPSHOT_FILE OFFSET LENGTH.
- PROTOCOL.md: counting definitions, invariant predicates, replay scope, timing and reserve policy.
- maintenance-20261119T085431Z/: superseded pair summaries and reason for the accounting-fix retry.

The original pinned source and supplied reference files are preserved. No hidden graph is executed. Stage D alternative pivots are outside this test.
