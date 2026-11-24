# Learnability extraction (feature schema v1)

This module builds offline candidate tables for learning-to-rank research on exact Feedback Vertex Set branching. It extracts features from the saved Stage C branching states and joins them, unchanged, to the Stage D first-pivot continuation records. It does **not** train models, create folds or preference pairs, fit normalisation, run or modify solvers, or touch the 130 reserved hidden graphs. It is standard-library Python (3.8 or later) and needs no Windows build.

## Pinned inputs

| Input | Ref | Paths used |
|---|---|---|
| Stage D experiment code | `4cf65df9de3af1aacbece3820e2986c0fd2b5620` (`main`) | `staged/index.json.zz`, `staged/validation.json.zz`, `stagec/snapshot.py`, and the `staged/*` and `full/*` docs listed in `pins.py` |
| Stage C records | `eece4cfe803a97c47ca178c14caa6b71b1e962c3` (`full-results`), run 44639720515 | `runs/44639720515/pairs/*/attempt-1/invocations/*-instrumented/samples.{json,bin.zz}` |
| Stage D records | `a5dbb1eb87ea1052a0240bf4b4da8d364b37a890` (`stage-d-results`), run 45059940845 | `runs/45059940845/chunks/*/attempt-*/{records.jsonl,summary.json,schedule.json,environment.json}`; `raw.zip` is not needed |

The other run on `stage-d-results` (`runs/45057608643`, the pilot and build) is not scanned. The extractor confirms each input file is byte-identical to the blob at its pinned commit, using `git ls-tree`, which downloads no blobs.

Get the inputs without downloading every `raw.zip` (read-only; on Windows Git Bash set `MSYS_NO_PATHCONV=1` so the patterns are not rewritten):

```bash
git clone --filter=blob:none --no-checkout https://github.com/mohamad-alaalami/fvs-stage-c.git repo
cd repo && git config core.autocrlf false && git config core.eol lf          # byte-exact text files
git fetch origin full-results stage-d-results
git worktree add --no-checkout ../stagec-records eece4cfe803a97c47ca178c14caa6b71b1e962c3
(cd ../stagec-records && git sparse-checkout set --no-cone \
   "/runs/44639720515/pairs/*/attempt-1/invocations/*-instrumented/samples.json" \
   "/runs/44639720515/pairs/*/attempt-1/invocations/*-instrumented/samples.bin.zz" && git checkout)
git worktree add --no-checkout ../staged-records a5dbb1eb87ea1052a0240bf4b4da8d364b37a890
(cd ../staged-records && git sparse-checkout set --no-cone \
   "/runs/45059940845/chunks/*/attempt-*/records.jsonl" "/runs/45059940845/chunks/*/attempt-*/summary.json" \
   "/runs/45059940845/chunks/*/attempt-*/schedule.json" "/runs/45059940845/chunks/*/attempt-*/environment.json" \
   "/runs/45059940845/report/" && git checkout)
```

The experiment tree is any checkout of `4cf65df` that also contains this `learnability/` directory, for example `git worktree add -b learnability-v1 <dir> 4cf65df`.

## Run

From the experiment-tree root (Windows `python`, or `python3` elsewhere):

```bash
python -m unittest discover -s learnability/tests -t .
python -m learnability.extract --experiment-tree . \
    --stagec-records <stagec-records> --staged-records <staged-records> --output-root <outputs>
```

The extractor builds `<outputs>/.<id>.partial/`. When every acceptance check passes it writes `COMPLETE` and renames the directory to `<outputs>/extract-v1-<UTC>-<suffix>/`. Otherwise it renames it to `<id>.INCOMPLETE` and exits with code 2. It never reuses an existing path. Determinism check: run again with `--extraction-id extract-v1-<other>` into a different output root, then compare the `candidates_*.csv` bytes.

## Outputs

| File | Content |
|---|---|
| `candidates_8.csv`, `candidates_5.csv`, `candidates_LP.csv` | One row per indexed candidate, ordered by `state_index` then `candidate_ordinal`. Key: (`solver`, `state_id`, `candidate_local_id`); `graph_id` is the grouping key. |
| `states.jsonl` | One record per state: sampling and event metadata (strict Chen qualification included), decoded summary, every check, and the archived Stage C continuation kept under `outcome_reference_not_a_feature`. |
| `invocations.jsonl` | Every record found in the pinned Stage D run: complete raw record, provenance, and the matched/scheduled flags. |
| `schema.json` | Ordered columns, logical types, roles, null rules, formulas, and per-solver model-input allowlists. |
| `manifest.json` | Input and output hashes, refs, extractor hashes, Python/platform, command, UTC times, timing, peak memory, counts. |
| `validation.json`, `REPORT.md` | Acceptance checks, anomaly inventory, distributions, feature variation, audit anchors, limitations. |

## Loading with explicit types

```python
from learnability.schema import load_table, model_inputs, ALLOWLISTS
rows = load_table('<extraction>/candidates_LP.csv', '<extraction>/schema.json')   # never use type inference
x = [model_inputs(r, 'LP') for r in rows]                                        # explicit allowlist, never column prefixes
```

Empty cells are null; booleans are `true`/`false`; IDs such as `001` stay strings; `json` columns are parsed. `exact_nodes` is non-null only for unique, valid, completed, reconciled, join-valid arms. Censored arms give `observed_nodes` as a prefix (`node_observation_kind = prefix`).

## Comparing two arms later

Two invocations are comparable only when all of these hold:

- same `state_id`, `snapshot_sha256`, `candidate_list_sha256` and initial incumbent;
- both resolve to `unique` with `join_valid` and `measurement_integrity_ok`;
- equal, non-null `environment_build_group` (canonical-JSON SHA-256 of `{cpu, image, executable_sha256}`, the Stage D rule);
- equal `experiment_commit` and `cpu_budget_s`.

A missing key means unknown, not equal. Runner name and OS are provenance only. This key is not a model feature and does not by itself make a pair valid.

See `FEATURES.md` for the feature dictionary.
