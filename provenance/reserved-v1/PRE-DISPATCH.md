# Reserved benchmark (integration v1): pre-dispatch provenance

This record was written on 2026-11-25, before `integration-reserved.yml` was dispatched. It is part of the benchmark's provenance and is never edited after dispatch; later facts go into new files.

## Owner approval

On 2026-11-25 the owner explicitly approved:
- launching the reserved end-to-end benchmark on all 130 reserved graphs (`tests/pace16-hidden` at upstream `c0290698`), with all three solvers (8, 5, LP) and the baseline, linear and boost policies;
- 1,170 invocations, each with an independent 1,800 s process-CPU cap, for at most 585 solver CPU-hours before infrastructure retries;
- timing repetitions left **disabled**;
- the committed retry rule: only infrastructure failures, the whole three-policy job re-run together, at most two retries, every attempt preserved;
- the validated paired layout: 390 graph-solver jobs, three policies run sequentially on one runner in the frozen rotating order, three matrices, at most 20 jobs at once;
- registering the workflow on `main` with a minimal one-file change.

## Experiment identity (verified before dispatch)

| Item | Value | How it was verified |
|---|---|---|
| Experiment commit | `d65bb5519edcc9f8acf8dc6bb2805fe20472d04e` | `refs/heads/integration-v1-20261124` still points here (not moved) |
| Validation run | 45493670014 | `runs/45493670014/public-validation/attempt-1/validation/validation.json`: `all_passed: true`, `experiment_commit` = the commit above |
| Build | `integration-build-20261124T214255Z-97f58c0b` (`runs/45493670014/build/attempt-1/`) | `build_record.json`: `experiment_commit` = the commit above, `reserved_files_read: 0` |
| Approval token | `APPROVE-32c64732c4db4dc8` | recomputed as `APPROVE-` + SHA-256(committed `integration/benchmark/MANIFEST.json` bytes)[:16]; equal to the previously reported value |
| Manifest | 130 graphs, 1,170 invocations, `cpu_limit_s` 1800, `max_solver_cpu_hours` 585, `max_concurrent_jobs` 20, timing repetitions `enabled: false` | read from the committed manifest |

Executables, comparing the blob on `integration-results` with `build_record.json`:

| File | SHA-256 |
|---|---|
| baseline/FeedbackVertexSet.exe | `9fe46be6cf7b3cefba1271c69ee7904e113aa52ba69d066779f177faf3c4562a` |
| baseline/Verifier.exe | `522a0f1f54f80f66bfe01fa9787adcd20e164271d138ace9f02e56c181047239` |
| integrated/FvsIntegrated.exe | `a409b4ebf962956b333903a036a5c4c971ec787067aa476ecc07c3bfaa24970b` |
| tools/PolicyReplay.exe | `24e2fd2ee046a13a113e5519aa79820dc8c22096a5ce90be460ee7282b5adf4f` |

The six frozen models are listed in `integration/models/MODELS.json` at the experiment commit. The hashes are equal to `build_record.json` `model_hashes`.

| Model | Config | model.json | model_meta.json |
|---|---|---|---|
| 8/linear | lambda=0.1 | `6c43249cdb3052e4b228cd63f88317fd39f2cbdf72776f1d7b36c77f77e0d47c` | – |
| 8/boost | depth=2,rounds=50 | `fb7f8c14e9fe0fc3e14c97087a12406197c5261c914aaa8c7c4f09dcd0dfadef` | `77b9122e08b4c5fc166cfbd13036015cc8ffb40216fe6defe86c62eb91e5e50d` |
| 5/linear | lambda=0.0001 | `a01d2053b24cb85b5f929d9c904f9d16437fa2db9e78cee45189c07b5b061295` | – |
| 5/boost | depth=3,rounds=200 | `87a34cea0d1b13d19dedbad8aaf794ce62ca0fca6225ea1de2f3d91409d99568` | `a6e83b8f505c140effe203124cfd3e399f5d49fc355cec0b23f99f97bbb651b8` |
| LP/linear | lambda=0.01 | `fc62ad4d3297ce7c14ace67128a1291b99d23e88f495c8e1ffaef5de13104b65` | – |
| LP/boost | depth=3,rounds=200 | `1c5ab0959e5ce1443a0581fb9ba9d28d25f0509542350310841a2bee1c52d8a1` | `f64f1ede0dcaf5de61a836c1ad07c7f7191e170ecc51bd664c7db9545d377efa` |

## Model line endings (provenance correction; no change to any model)

`MODELS.json` says the models were "copied byte-for-byte" from `learnability-results@e5b8401`. That is not literally true.
- **What differs:** the committed files are the training outputs with LF line endings converted to CRLF. Their parsed JSON values are identical to the originals, and the recorded hashes are the hashes of the CRLF form. The single-line boost `model.json` files are unaffected.
- **Effect on scoring:** none. The public replay already showed bit-exact scoring with these files.
- **How the build stores them:** `integration-results` has no `.gitattributes`, so its blobs of the multi-line model files are LF.
- **Probe:** the reserved jobs therefore depend on the Windows runner's checkout converting LF back to CRLF, a path the public dry run did not exercise (it used an Actions artifact). Before dispatch this was tested by probe run [45655543541](https://github.com/mohamad-alaalami/fvs-stage-c/actions/runs/45655543541) (branch `probe-reserved-build-checkout-20261125`, commit `77c942f`).
- **Probe result:** on `windows-2025`, the reserved jobs' exact `actions/checkout` step produced CRLF files, all nine model hashes matched the build record, and the frozen `invoke.Build` hash check passed. The probe touched no graph and published nothing.

## Rescoring addendum (completed and published before dispatch)

- **Addendum:** `rescore-linear-v1-20261125T154331Z-02ac7c57`.
- **Branch and commit:** `addendum-rescore-linear-v1-20261125`, commit `7159586c32170249ac99bb0ba4fdb1408264c17f`.
- **Report:** https://github.com/mohamad-alaalami/fvs-stage-c/blob/7159586c32170249ac99bb0ba4fdb1408264c17f/addenda/rescore-linear-v1-20261125T154331Z-02ac7c57/REPORT.md
- **Disclosure:** rescoring the archived linear fold models with the deployed scorer and the exact tie rule changes the offline development metric. Under the unchanged choice rule, it would select a **different Chen (solver 5) linear configuration**: λ=1e-5 (corrected metric −0.062433) instead of the frozen λ=1e-4 (corrected −0.061402; archived −0.062628). The Cao and LP choices do not change.
- **Decision:** by the owner's prior decision, the **six benchmark models remain frozen**, including the Chen linear λ=1e-4 refit. Nothing was retrained, retuned or reselected. The Chen linear results of this benchmark should be read with this disclosure.

## Incident: reserved graph files checksummed locally (2026-11-24)

During the integration implementation on 2026-11-24, a local hash check iterated every entry of `records/local-checkpoint/reference_manifest.json`. That file lists `tests/pace16-hidden` alongside `tests/pace-16open`.
- **What was touched:** a local Python process on the developer laptop read the 130 reserved graph files of the local upstream checkout (`outputs/FeedbackVertexSet-Experiments/tests/pace16-hidden`) and computed their SHA-256 hashes, comparing them against the manifest.
- **What was output:** only a mismatch count (0) and directory names. No graph content, statistics or sizes were shown, nothing was transmitted, and nothing from it was used anywhere.
- **Already frozen at the time:** the learned models (frozen at `e5b8401` by run 45408454796, which finished earlier), features, eligibility, tie rule, policy order rule, CPU caps and manifest, none of which depend on reserved-graph content.
- **Reported:** the incident was disclosed to the owner immediately.
- **Fixed afterwards:** `integration/build.py` filters the local manifest to `tests/pace-16open`, the CI workflows check out only `tests/pace-16open` (the public jobs assert `pace16-hidden` is absent), and each reserved job sparse-checks-out only its own graph file.
- **Not recorded in the frozen protocol:** this incident is not in `integration/PROTOCOL.md` at the experiment commit, which could not be amended without invalidating the validated commit, so it is recorded here.

## Default-branch registration

- **Commit:** `main` was advanced from `4cf65df` to `b2bda1b8104ac81259d42e5a109a411761ababba` by a fast-forward push (no force; `main` is unprotected and has no rulesets).
- **Contents:** one file, `.github/workflows/integration-reserved.yml`, added as the identical git blob of the experiment commit (`183c58c63bba9e76d2b5da828d4e9e8b50eaf9e0`). Research code and the manifest stay at the experiment commit.
- **Why nothing else can start:** every workflow on `main` is `workflow_dispatch`-only. The only push-triggered workflows in the repository are scoped to their own research branches (`integration-public.yml`, `learnability-offline.yml`) and the probe branch.
- **Checked after the push:** no run started.

## Duplicate check before dispatch

Before dispatch:
- no run was queued or in progress;
- the reserved workflow had never been registered, so it could not have run;
- `integration-results` contained no reserved schedule or job records; its only `runs/` entries are the three public validation runs.
