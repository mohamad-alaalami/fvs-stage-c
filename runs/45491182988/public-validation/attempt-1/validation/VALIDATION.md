# Integration-v1 public validation

Build `integration-build-20261124T212815Z-0c4436bb`, experiment commit `0189aa8e5e1a6ae514d803c8a91562213157a6fe`, run 45491182988.

**Overall: FAIL**

| Check | Expected | Observed | Result |
|---|---|---|---|
| Replay of all saved public states through the integration code | 6502 states / 71038 candidates; exact discrete agreement; exact selections | 6502 states / 71038 candidates | PASS |
| Baseline equivalence vs pristine build and Stage C records | every Stage C pair completed with instrumented CPU <= 60 s; identical output, nodes, B/T/A, trace digest | not run | FAIL |
| Exact oracle on generated small graphs + tests/simple | all completed, feasible, size = brute-force optimum; learned policies exercised | not run | FAIL |
| Fixed public correctness suite (incl. 003, optimum 10) | 34 graphs x 3 solvers; completed runs feasible and optimal | not run | FAIL |
| Live decision states re-scored by the Python reference | exact features, scores and selections, including post-departure states | 1268 states (1244 after a departure, 136 in component subsolvers) | PASS |
| Instrumentation overhead and diagnostic timers | 6 predefined cases measured | not run | FAIL |
| Benchmark driver / retry / report exercise on public fixtures | all fixture checks true | not run | FAIL |
| Unit tests (schedule, report, model loading, tie rule) | all pass | 9 tests, 0 failures | PASS |

## Executables

- `baseline/FeedbackVertexSet.exe` 9fe46be6cf7b3cefba1271c69ee7904e113aa52ba69d066779f177faf3c4562a
- `baseline/Verifier.exe` 522a0f1f54f80f66bfe01fa9787adcd20e164271d138ace9f02e56c181047239
- `integrated/FvsIntegrated.exe` a409b4ebf962956b333903a036a5c4c971ec787067aa476ecc07c3bfaa24970b
- `tools/PolicyReplay.exe` 24e2fd2ee046a13a113e5519aa79820dc8c22096a5ce90be460ee7282b5adf4f

## Frozen models (SHA-256)

- `5/boost/model.json` 87a34cea0d1b13d19dedbad8aaf794ce62ca0fca6225ea1de2f3d91409d99568
- `5/boost/model_meta.json` a6e83b8f505c140effe203124cfd3e399f5d49fc355cec0b23f99f97bbb651b8
- `5/linear/model.json` a01d2053b24cb85b5f929d9c904f9d16437fa2db9e78cee45189c07b5b061295
- `8/boost/model.json` fb7f8c14e9fe0fc3e14c97087a12406197c5261c914aaa8c7c4f09dcd0dfadef
- `8/boost/model_meta.json` 77b9122e08b4c5fc166cfbd13036015cc8ffb40216fe6defe86c62eb91e5e50d
- `8/linear/model.json` 6c43249cdb3052e4b228cd63f88317fd39f2cbdf72776f1d7b36c77f77e0d47c
- `LP/boost/model.json` 1c5ab0959e5ce1443a0581fb9ba9d28d25f0509542350310841a2bee1c52d8a1
- `LP/boost/model_meta.json` f64f1ede0dcaf5de61a836c1ad07c7f7191e170ecc51bd664c7db9545d377efa
- `LP/linear/model.json` fc62ad4d3297ce7c14ace67128a1291b99d23e88f495c8e1ffaef5de13104b65
