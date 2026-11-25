# Addendum rescore-linear-v1-20261125T154331Z-02ac7c57

This addendum rescores the archived linear cross-validation fold models of offline learnability run 45408454796. It uses the deployed integration scorer and the exact frozen tie rule. Nothing was retrained, retuned or reselected, no FVS solver was run, and none of the 130 reserved graphs was listed, read or opened.

## Authoritative result

| Item | Path | Status |
|---|---|---|
| Report | [`addenda/rescore-linear-v1-20261125T154331Z-02ac7c57/REPORT.md`](addenda/rescore-linear-v1-20261125T154331Z-02ac7c57/REPORT.md) | **authoritative** |
| Results | `addenda/…/results.json` (480/480 checks pass, `all_checks_pass: true`) | **authoritative** |
| Changed-state records | `addenda/…/changed_states.jsonl.gz` (3,092 records over 18 configurations) | **authoritative** |
| Run log | `addenda/…/run.log` | **authoritative** |
| Hash manifest | `addenda/…/MANIFEST.json`, with `COMPLETE` = SHA-256(`MANIFEST.json`) = `24994bf9b648bff9c492211b2d0c4bd9333be9645d946f6f119dec4cea283016` (see below) | seal of the folder |
| Superseded execution | `addenda/…/superseded-execution-1/` | **not authoritative**, kept for the record |

**Why execution 1 was superseded.** It failed two checks, both caused by the checks rather than by the data:
- the `git archive` copy of `frozen/folds.json` had CRLF line endings, and is identical to the training branch after LF normalisation;
- one archived `selection_cost` differed from the rebuilt value only in its last bit (`math.log`, Windows UCRT vs ubuntu glibc), with an identical selection.

Both checks were made precise (LF-normalised bytes plus the embedded manifest hash; a 1-ulp allowance on `selection_cost` only, with the case listed in `results.json`). Everything was then rerun.

Between the two executions, the `solvers` section of `results.json` is value-identical and `changed_states.jsonl.gz` is byte-identical. The sealed folder is committed byte for byte, and `.gitattributes` disables line-ending conversion so the manifest stays valid on checkout.

## Chen (solver 5): the corrected choice would differ; the benchmark models stay frozen

Under the deployed scorer and exact tie rule, applying the unchanged choice rule to the corrected development metric would have chosen a different Chen linear configuration:
- **Archived choice:** λ=1e-4, metric −0.062628 (λ=1e-5 runner-up at −0.062112).
- **Corrected choice:** λ=1e-5, metric −0.062433 (λ=1e-4 runner-up at −0.061402, a margin of 1.0e-3).

The Cao (λ=0.1) and LP (λ=0.01) choices do not change.

**Decision (ours, made before this addendum):** the six benchmark models stay frozen, including the Chen linear λ=1e-4 refit. This addendum does not change, replace or reselect any model. These are optimistic development estimates with small margins, so they do not show that λ=1e-5 is better. The finding is recorded so the reserved benchmark can be read with it in mind.

The frozen benchmark models, as listed in `integration/models/MODELS.json` at integration commit `d65bb55` (unchanged):

| Model | Config | model.json SHA-256 | model_meta.json SHA-256 |
|---|---|---|---|
| 8/linear | lambda=0.1 | `6c43249cdb3052e4b228cd63f88317fd39f2cbdf72776f1d7b36c77f77e0d47c` | – |
| 8/boost | depth=2,rounds=50 | `fb7f8c14e9fe0fc3e14c97087a12406197c5261c914aaa8c7c4f09dcd0dfadef` | `77b9122e08b4c5fc166cfbd13036015cc8ffb40216fe6defe86c62eb91e5e50d` |
| 5/linear | lambda=0.0001 | `a01d2053b24cb85b5f929d9c904f9d16437fa2db9e78cee45189c07b5b061295` | – |
| 5/boost | depth=3,rounds=200 | `87a34cea0d1b13d19dedbad8aaf794ce62ca0fca6225ea1de2f3d91409d99568` | `a6e83b8f505c140effe203124cfd3e399f5d49fc355cec0b23f99f97bbb651b8` |
| LP/linear | lambda=0.01 | `fc62ad4d3297ce7c14ace67128a1291b99d23e88f495c8e1ffaef5de13104b65` | – |
| LP/boost | depth=3,rounds=200 | `1c5ab0959e5ce1443a0581fb9ba9d28d25f0509542350310841a2bee1c52d8a1` | `f64f1ede0dcaf5de61a836c1ad07c7f7191e170ecc51bd664c7db9545d377efa` |

The reserved benchmark workflow (`integration-reserved.yml`) remains **undispatched**. This branch contains no workflows, so pushing it triggers nothing.

## Provenance

| Input | Source |
|---|---|
| Rescoring code | `addenda/…/code/rescore_linear.py`, `addenda/…/code/make_report.py` (hashed in the manifest) |
| Training code imported by the rescoring code (`learnability.train` run/evaluate/transforms/data, `learnability.features`) | branch `learnability-offline-v1-20261124`, commit `27c43b7ac77dfd06c5c224e959ea99f61d29923a` (clean worktree) |
| Extraction `extract-v1-20261124T115559Z-833e6421` | same commit, `learnability/data/extract-v1-20261124T115559Z-833e6421/`; verified against the frozen config's extraction hashes |
| 90 linear CV fold models, `frozen/`, `selection/selection.json`, `report/selected_states_*_linear.jsonl.gz`, final boost models (a required but unused PolicyReplay argument) | branch `learnability-results`, commit `e5b840104e1bca378d3bbeeaed795f72dfbad951`, `runs/45408454796/attempt-1/`; copied into `addenda/…/inputs/` |
| Deployed scorer `PolicyReplay.exe` (SHA-256 `24e2fd2ee046a13a113e5519aa79820dc8c22096a5ce90be460ee7282b5adf4f`) | branch `integration-results`, commit `5590294dff521e8ed2ffe41b366929326d663760`, `runs/45493670014/build/attempt-1/tools/PolicyReplay.exe`; built by validation run 45493670014 from integration commit `d65bb55`; copied into `addenda/…/inputs/` |
| Stage C snapshots (278 `samples.bin.zz` files, listed in `provenance/stagec-samples-used.txt`) | branch `full-results`, commit `eece4cfe803a97c47ca178c14caa6b71b1e962c3`, `runs/44639720515/`; every file was verified equal to its git blob there |
| Environment | Windows 11 x86-64 (Intel i5-12500H); `provenance/python-version.txt` (3.13.5) and `provenance/pip-freeze.txt` (numpy 2.1.3, scipy 1.14.1, xgboost 2.1.3); OpenBLAS 0.3.27 (in `results.json`); `OMP/OPENBLAS/MKL_NUM_THREADS=1`, `PYTHONHASHSEED=0` |

## Verify the seal

```
cd addenda/rescore-linear-v1-20261125T154331Z-02ac7c57
python -c "import json,hashlib,pathlib; m=json.load(open('MANIFEST.json')); print(sum(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()!=f['sha256'] for p,f in m['files'].items()), 'mismatches'); print(open('COMPLETE').read().strip()==hashlib.sha256(open('MANIFEST.json','rb').read()).hexdigest())"
```

## Reproduce (Windows x86-64; PolicyReplay.exe is a Windows binary)

```
# L = checkout of learnability-offline-v1-20261124 at 27c43b7
# R = directory holding full-results@eece4cf runs/44639720515/... (at least the 278 files listed in provenance/)
# A = addenda/rescore-linear-v1-20261125T154331Z-02ac7c57 on this branch
set OMP_NUM_THREADS=1 & set OPENBLAS_NUM_THREADS=1 & set MKL_NUM_THREADS=1 & set PYTHONHASHSEED=0
mkdir OUT & copy A\ID OUT\ID
python -I A/code/rescore_linear.py --learn-root L --data L/learnability/data/extract-v1-20261124T115559Z-833e6421 --inputs A/inputs --stagec-records R --work WORK --out OUT
python A/code/make_report.py OUT
```

**What a rerun should reproduce:**
- `solvers` in `results.json`, `changed_states.jsonl.gz` and `REPORT.md` should match.
- `wall_s` and `environment` will differ.

**Reproducing the old side:** the old side (numpy batched `transform(X) @ theta`) reproduced the archived training summaries exactly on this machine. Its result can depend on the BLAS kernel. On another machine, the `*:old_summary_reproduces_archive` and `*:old_per_state_reproduces_archived_selected_states` checks show whether it still reproduces there. The corrected side is the deployed native scorer and does not depend on BLAS.
