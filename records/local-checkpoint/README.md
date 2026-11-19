# Local FVS checkpoint

Pinned commit: `c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4`.

All three configurations completed sequentially on public `tests/pace-16open/003.graph`; 53 vertices, 89 edge records. All returned size 10, matching the supplied `.opt`, and passed independent and upstream feasibility verification.

| Subset | Graphs | Supplied .opt | Unknown optimum |
|---|---:|---:|---:|
| pace-16open | 100 | 33 | 67 |
| pace16-hidden | 130 | 0 | 130 |

Inventory keys combine subset and filename. The repository also contains 20 simple graphs; those are outside this checkpoint and were not run. All 294 PACE companion files (33 .opt, 31 .out, 230 .stats) were hashed, made read-only, and rehashed after verification. Historical .out and .stats files are preserved but are not treated as supplied optimum certificates.

## Source-confirmed configuration

- Cao: `8` selects `Sol8` (Main.cpp:21–32). Maximum degree counting double edges, undeletable-branch bound, connected-component splitting and cubic solver enabled.
- Chen-style: `5` selects `Sol5` (Main.cpp:33–39). Sol5 inherits ICBranchingSolution (SolutionVariants.h:43–70). BranchingSolution::solve initializes approximation-based branching_hints; ICBranchingSolution consumes these before choosing maximum degree into the undeletable set. This is the compression-guided behavior implemented by this revision: no separate outer iterative-compression loop or command-line activation is needed. `5 IC` would still select Sol5; it adds no effect. Connected-component splitting is enabled, cubic solver is not.
- Imanishi–Iwata-style: `LP` selects `HalfIntBranching` (Main.cpp:62–68), with original solve1/solve2 half-integral branching and kernelization. Connected-component splitting is enabled; cubic solver is not.
- No optional Full/noCC/Deg3 flags, branching changes, instrumentation, or source edits. Source checkout remains clean.

## Exact recorded invocations

Working directory for all invocations: `C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\FeedbackVertexSet-Experiments`. The Python harness passes the graph as a binary stdin stream; the following are equivalent cmd.exe redirections. All use a 300-second wall-time limit enforced by the harness.

```bat
C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\checkpoint\build-20261119T075207Z-48b75ae2\release\FeedbackVertexSet.exe 8 < "C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\FeedbackVertexSet-Experiments\tests\pace-16open\003.graph"
C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\checkpoint\build-20261119T075207Z-48b75ae2\release\FeedbackVertexSet.exe 5 < "C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\FeedbackVertexSet-Experiments\tests\pace-16open\003.graph"
C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\checkpoint\build-20261119T075207Z-48b75ae2\release\FeedbackVertexSet.exe LP < "C:\Users\HP\Documents\Codex\2026-11-19\vbnet-i-m-a-cs-senior\outputs\FeedbackVertexSet-Experiments\tests\pace-16open\003.graph"
```

## Results

| Run ID | Variant | Exit | Size | Feasible | Optimum | CPU (s) | Wall (s) | Peak working set (bytes) |
|---|---|---:|---:|---|---|---:|---:|---:|
| 20261119T075230Z-8-2d397533eb76 | Cao | 0 | 10 | pass | match | 0.0 | 0.282178 | 4182016 |
| 20261119T075230Z-5-7047623cf570 | Chen-style disjoint FVS | 0 | 10 | pass | match | 0.0 | 0.032960 | 4145152 |
| 20261119T075230Z-LP-067eeb4068de | Imanishi-Iwata-style | 0 | 10 | pass | match | 0.0 | 0.017155 | 4186112 |

Returned IDs in every run: `44 14 36 49 2 6 31 23 4 27`. The reference contains a different optimal set, which is acceptable.

Independent verification checks exact declared count, distinct IDs, membership in the graph, and acyclicity of every remaining edge using disjoint-set union (including self-loop/parallel-edge cycle detection). The fresh upstream Verifier receives only input graph and output file; its stdout says `OPT not provided`. Reference size is compared separately. No solver counters were emitted; raw stdout/stderr are retained unchanged and unavailable counters are recorded as unknown.

The OS reported 0.0 seconds process CPU for all three short runs; wall times include process startup and cannot support performance ranking. No warmups or additional benchmark invocations were performed.

## Build and discrepancies

Successful build: `build-20261119T075207Z-48b75ae2`. GCC 16.2.0, CMake 4.3.1-msvc1, Ninja 1.13.2, Windows x64, Intel Core i5-12500H. Effective flags: `-include string -std=c++11 -O3`. Assertions remain enabled, matching upstream Release configuration.

- The checked-in src/build directory was not reused. Every build attempt has its own new directory and logs.
- Portable GCC 2.11.0 distribution was downloaded and extracted under work/toolchain; its URL and archive SHA-256 are in the shared build record.
- Two sandboxed configure attempts stalled in Ninja compiler tests and were terminated; both are retained. An outside-sandbox build reached compilation but failed on missing `<string>` in CubicSolver.cpp. The successful fresh build supplies `-include string`, with no source modification.
- CMake emits an old-minimum-version deprecation warning. No CMake source edit was needed.
- 003.stats contains `53,89,11`, whereas 003.opt declares 10. The `.opt` is the requested reference authority; the historical statistics field is not substituted for it.
- Git core.autocrlf is true; SHA-256 identifiers describe the actual checked-out bytes used in this Windows run.

## Saved records and reproduction

- `dataset_inventory.csv`: all 230 graph identities, paths, graph hashes, counts, reference availability and supplied companion paths.
- `reference_manifest.json` and `reference_integrity_after.json`: supplied companion hashes and unchanged-after-verification result.
- `graph_record.json`: selected input and reference identifiers.
- `build_record.json`: shared successful-build provenance, exact build commands, compiler version, compile commands, executable/verifier hashes, OS, CPU and timing methods. Each build directory also retains its own record and raw build logs.
- `results.csv`: append-only invocation records with absolute raw-artifact links. `runs/<run_id>/` contains stdout, stderr, verifier stdout/stderr, detailed checks and invocation JSON.
- `../checkpoint.py`: reproduction harness. From the workspace run `python outputs/checkpoint.py build` to create a fresh build (requires the retained portable toolchain and outside-sandbox process permissions here), then `python outputs/checkpoint.py run` to append new run IDs. The initial inventory is already saved. Do not alter supplied references.

The scope ends here: only public 003.graph was executed.
