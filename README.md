# Learning-Guided Branching for FVS: Stage C smoke test

Instrumentation and runner for Stage C of an empirical study of branching decisions in the SEA 2018 FVS solvers
([karek/FeedbackVertexSet-Experiments](https://github.com/karek/FeedbackVertexSet-Experiments), pinned to
`c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4`). The upstream source is cloned at that commit by the workflow and is never modified.

* `stagec/`: instrumentation (`StageC.cpp/.h`, applied by `prepare.py`), build, per-pair driver, segment compressor, offline auditor, aggregator.
* `.github/workflows/stage-c.yml`: build once, then one Windows job per (graph, solver) pair, then an aggregate report.
* `records/local-checkpoint/`: verified checkpoint records (dataset inventory, reference manifest, build record).
* `records/local-stage-c/`: the partial local Stage C batch (095 complete; 029/8 interrupted), preserved as is.
* `PROTOCOL-GHA.md`: what is measured, and every difference from the local protocol (`records/local-stage-c/PROTOCOL.md`).

Graphs: public `pace-16open` 095, 029, 076, 031, 002, 069, 089, 071, 014, 038. The 130 hidden graphs are never run.
Solvers: `8` (Cao), `5` (Chen-style), `LP` (Imanishi–Iwata-style) with their original policies.

## Running and collecting results

```
gh workflow run stage-c.yml                    # defaults: the ten graphs, 1800 s CPU, 3 GiB reserve
gh run list --workflow stage-c.yml
gh run download <run-id> -n stagec-report      # results.csv, REPORT.md, summary.json
gh run download <run-id> -n stagec-029-8       # all raw records for one pair (zlib segments)
```

Decoding raw records: `stagec/segments.py` (`iter_lines`, `iter_chunks`) reads segment streams;
`stagec/snapshot.py` decodes one snapshot. An event's `snapshot_offset` is its offset in the concatenated snapshot stream.
