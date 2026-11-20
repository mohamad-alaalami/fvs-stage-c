# Full Stage C: results of run 44639720515

- **Run:** https://github.com/mohamad-alaalami/fvs-stage-c/actions/runs/44639720515, experiment commit `3244862`, upstream `c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4`.
- **Records:** branch `full-results`, `runs/44639720515/`. One-row-per-pair table: `report/results.csv`. Summary: `report/summary.json`. Operator notes: `report/NOTES.md`. Per-pair records: `pairs/<graph>-<solver>/attempt-1/` (`pair.json`, invocation directories, `samples.bin.zz`, `samples.json`).

## Coverage and verification

All 300 scheduled pairs (100 public graphs × 8/5/LP) have records: 0 missing, 0 runner errors, 1 attempt each. The 130 hidden graphs were not run.

| Solver | Both completed | Both timed out | Baseline completed, instrumented timed out | Zero-branch pairs |
|---|---:|---:|---:|---:|
| 8 (Cao) | 48 | 52 | 0 | 8 |
| 5 (Chen) | 42 | 56 | 2 (014, 037) | 3 |
| LP | 46 | 54 | 0 | 5 |

- **Answers:** every completed answer is feasible (declared size, distinct valid IDs, forest after deletion, upstream Verifier with no optimum-file argument). None contradicts a supplied `.opt` (96 matches across all runs). Where both runs completed, original and instrumented answers always have the same size.
- **Consistency:** all checks pass, except the documented node-entry off-by-one at a CPU stop (036/5, 084/LP; see PROTOCOL Known limitations 1).
- **Saved states:** every saved state passes `SampleCheck` (byte-equal round trip, identical eligible candidates, original selector returns the recorded pivot).
- **Replay:** every executed replay matches. Pairs with A > 0 but no replay: 8 Cao pairs (no saved continuation finished within the cap before the CPU stop) and 037/8 (first A state over 2 MiB, nothing saved).

## Decision counts (observed; timed-out pairs contribute their observed prefix)

| Solver | B | T | A | A/T | A_chen_strict_merge |
|---|---:|---:|---:|---:|---:|
| 8 | 1,800,552,703 | 1,800,552,703 | 1,405,564,561 | 0.781 | n/a |
| 5 | 4,888,868,671 | 4,538,925,208 | 4,538,925,208 | 1.000 | 10,987,602 (0.24% of T) |
| LP | 2,204,734,745 | 1,981,812,663 | 1,981,812,663 | 1.000 | n/a |

These are totals over pairs with very different CPU coverage, because timed-out pairs stop at 1,800 s. Use the per-pair rows and histograms for analysis, not these totals.

## Storage, overhead, sampling

- **Saved states:** 6,502 across the 300 pairs; 103.8 MB raw, 7.4 MB stored (zlib-9). States excluded for size (64 KiB slot cap): 25,841, in 77 pairs. One first A state over 2 MiB (037/8).
- **Instrumented/original CPU ratio** where both completed with baseline ≥ 1 s: Cao median 1.12 (max 1.24), LP 1.07 (max 1.13), Chen 1.54 (max 2.55).
- **Sampling:** seed 20261120, K = 32, first-A cap 2 MiB, slot cap 64 KiB; no Actions artifacts used.
