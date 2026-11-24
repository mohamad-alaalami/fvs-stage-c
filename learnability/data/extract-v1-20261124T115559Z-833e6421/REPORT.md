# Learnability extraction extract-v1-20261124T115559Z-833e6421

Dataset status: **complete_validated** (0 problems).

## Counts

| Solver | States | Candidate rows | Graphs |
|---|---:|---:|---:|
| 8 | 1983 | 12684 | 91 |
| 5 | 2212 | 43773 | 95 |
| LP | 2307 | 14581 | 92 |

Graphs represented (any solver): 97. Stage D invocations discovered: 71038 (unexpected: 0, duplicated UUIDs: 0).

## Acceptance checks

- states_total: pass
- candidates_total: pass
- per_solver_counts: pass
- all_invocations_accounted: pass
- every_candidate_unique_invocation: pass
- no_unexpected_records: pass
- no_duplicate_uuids: pass
- reference_features_match_all_states: pass
- all_states_integrity_ok: pass
- inputs_verified_against_pins: pass
- chunk_summaries_agree: pass
- no_join_or_measurement_errors: pass
- completed_caps_consistent: pass
- stage_d_report_agrees: pass

## Outcome observation kinds and record statuses (by solver)

| Solver | exact | prefix | missing | invalid | unresolved_multiple | completed | cpu_timeout | external_stop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 9081 | 3603 | 0 | 0 | 0 | 9081 | 3597 | 6 |
| 5 | 43773 | 0 | 0 | 0 | 0 | 43773 | 0 | 0 |
| LP | 14581 | 0 | 0 | 0 | 0 | 14581 | 0 | 0 |

All record statuses: {"completed": 67435, "cpu_timeout": 3597, "external_stop": 6}. 'prefix' rows are CPU- or driver-stopped arms: their node counts are observed prefixes, never exact totals.

## Audit anchors (recomputed; exploratory, not model claims)

| Quantity | Solver | Recomputed | Supplied anchor |
|---|---|---:|---:|
| states_weighted_degree_varies | 8 | 0 | 0 |
| states_weighted_degree_varies | 5 | 1529 | 1529 |
| states_weighted_degree_varies | LP | 1223 | 1223 |
| states_nbr_wdeg_mean_varies | 8 | 1273 | 1273 |
| states_nbr_wdeg_mean_varies | 5 | 1526 | 1526 |
| states_nbr_wdeg_mean_varies | LP | 1459 | 1459 |
| states_common_neighbors_varies | LP | 1411 | 1411 |

## Dataset observations

- LP states with exactly one SAFE vertex: 2307 of 2307; LP candidates with exactly one SAFE neighbour: 14581 of 14581.
- Cao states whose candidates all share one weighted degree: 1983 of 1983.
- Candidates with distinct degree <= 2 (kept, not repaired): 8: 113, 5: 632, LP: 17.
- Candidates with an empty undecided neighbourhood (summaries 0.0, f_cand_none_neighbors = 0): 8: 860, 5: 17, LP: 0.
- Chen states passing the strict qualifying-state test (metadata only; no Chen row is excluded): 59.

## Feature variation across rows (descriptive)

| Feature | 8 | 5 | LP |
|---|---|---|---|
| f_cand_none_neighbors | varies | varies | varies |
| f_cand_safe_neighbors | varies | varies | constant |
| f_cand_double_edges | varies | varies | varies |
| f_nbr_none_wdeg_min | varies | varies | varies |
| f_nbr_none_wdeg_mean | varies | varies | varies |
| f_nbr_none_wdeg_max | varies | varies | varies |
| f_state_none_vertices | varies | varies | varies |
| f_state_safe_vertices | varies | varies | constant |
| f_state_distinct_edges | varies | varies | varies |
| f_state_double_edges | varies | varies | varies |
| f_state_remaining_threshold | varies | varies | varies |
| f_state_candidate_count | varies | varies | varies |
| f_lp_root_common_neighbors | constant | constant | varies |

## Sampling and censoring patterns (states)

- 8: sample kinds {"first_A": 91, "reservoir": 1892}; per-state arm status sets {"completed": 1924, "cpu_timeout": 54, "cpu_timeout+external_stop": 5}
- 5: sample kinds {"first_A": 95, "reservoir": 2117}; per-state arm status sets {"completed": 2212}
- LP: sample kinds {"first_A": 92, "reservoir": 2215}; per-state arm status sets {"completed": 2307}

Stage D report cross-check: recorded invocations in REPORT.md 71038 vs discovered 71038; states 6502; retries listed 0; per-state recorded_arms mismatches 0; agrees: True.
Only counts are compared; Stage D comparison verdicts are not used.

## Anomalies

- join_errors: 0
- measurement_errors: 0
- completed_cap_inconsistent: 0

Input verification against pinned git trees: {"verified": 2791}; chunk summaries/schedules agree: True (555 chunks). Independent reference implementation: 6502 states checked, 0 mismatched.

## Timing and hardware

Extraction wall 57.5 s, process CPU 15.2 s on 12th Gen Intel(R) Core(TM) i5-12500H; peak memory 587067392 bytes (GetProcessMemoryInfo PeakWorkingSetSize (this process)). Extraction timing is not a solver-overhead measurement and implies nothing about live inference cost.

## Limitations

- Rows describe the 6,502 Stage C saved states (first A state, then a seeded reservoir of 32; 64 KiB slot cap, 25,841 selected states excluded for size), not every branching decision.
- Stage D arms are first-pivot continuations under the original policy with a 10 s process-CPU cap; censored arms carry prefixes only. Labels from these continuations describe one changed decision, not repeated learned decisions.
- Arms ran on several CPU models; comparisons require equal environment_build_group (CPU, image, executable) plus equal state, snapshot, candidate list, initial incumbent, experiment and budget.
- States from one graph are correlated; keep every row of a graph (across solvers) in the same future split. The 130 hidden graphs were not accessed.
- Features are our mechanism-motivated FVS design, not a published validated feature set; no predictive value or ML gain is shown here. Live parity and overhead are not established.
