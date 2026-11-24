# Offline learnability stage: frozen protocol (fvs-learnability-offline-v1)

Question: can the Stage D measured first-pivot preferences be learned from decision-time features on graphs excluded from parameter fitting? This stage does **not** measure repeated learned decisions, prediction overhead or complete-solver performance. No FVS solver is executed. The machine-readable configuration is `frozen/config.json`. The fold manifest (`frozen/folds.json`) and pair hashes (`frozen/pairs_manifest.json`) were written before any training run.

## Inputs

- **Extraction:** `extract-v1-20261124T115559Z-833e6421`, built from Stage C run 44639720515 (records `eece4cf`) and Stage D run 45059940845 (experiment `4cf65df`); SEA upstream `c0290698`.
- **Transport:** `learnability/data/<extraction>/` holds the gzipped candidate tables, `states.jsonl` (gzip is transport only), and the original `schema.json`, `manifest.json`, `COMPLETE`, `validation.json` and `REPORT.md`. Every job checks that the `COMPLETE` marker equals SHA-256(`manifest.json`) and that the SHA-256 of every decompressed file matches the manifest.
- **Not committed:** the 468 MB `invocations.jsonl` sidecar. Its hash is in the manifest, and it can be regenerated from the immutable Stage C and Stage D commits with `learnability/extract.py`.
- **Hidden graphs:** the 130 reserved graphs are never opened. Only `tests/pace-16open` is checked out from upstream.

## Targets

- **Valid candidate:** unique invocation, `join_valid`, `measurement_integrity_ok`, `state_integrity_ok`, `raw_status = completed`, `node_observation_kind = exact`, integer `exact_nodes` ≥ 0, and no original-reproduction FAIL.
- **Excluded state** (no pairs, not in the selection subset): the state has completed-cap inconsistency, an original-reproduction FAIL, or a state-integrity failure.
- **Comparability key:** (`environment_build_group` = SHA-256 of {CPU, image, executable}, `experiment_commit`, `cpu_budget_s`). An unknown part means not comparable.
- **Strict pair:** two valid candidates of a non-excluded state with equal keys, where i is preferred to j iff `exact_nodes[i] < exact_nodes[j]`. Equal totals give no pair, and censored, missing or incompatible comparisons give no pair. Nothing is imputed, and completion is never turned into a node preference. Chen states are not filtered by strict qualification. Snapshot and initial incumbent are equal within a state by construction (one snapshot per state; record joins verified initial incumbents).
- **Prediction:** every eligible candidate is scored, whatever its outcome availability.

## Folds

Five fixed folds over all 100 public graphs. The same assignment applies to every solver.

- **Bounded audit:** raw LF content SHA-256, canonical edge-multiset SHA-256, and a 1-WL colour-refinement signature (≤ 10 rounds). Graphs that agree on any of these are grouped together.
- **Result:** no exact duplicates. Two 1-WL matches, 008 ~ 021 (1,846 vertices, 2,203 edges) and 015 ~ 098 (118 vertices, 179 edges), are probably relabelled copies, and each pair is kept in one group. The pinned upstream documents no related-instance families.
- **Scope:** this audit does not prove absence of isomorphic or related instances.
- **Assignment:** groups are ordered by SHA-256(`20261124|fold|<first graph id>`); each goes to the fold with the fewest graphs, lowest index on ties. Result: 98 groups, 20 graphs per fold. No outcomes, features or labels are consulted, and there is no reshuffling.
- **Use:** each configuration trains on four folds and predicts the fifth. These are development predictions used for model selection, not an unbiased final test, and there is no nested CV.

## Pairs and weights

- **Generation:** each valid unordered strict pair is generated once, oriented better → worse.
- **Sampling:** when a state has more than 4,096 strict pairs, 4,096 indices are drawn uniformly without replacement. The draw uses Floyd's algorithm on SHA-256(`20261124|pairs|<solver>|<state_id>|counter`) with rejection sampling, over the canonical pair order, by unranking, so the quadratic table is never materialised. Python's `hash()` is never used.
- **Frozen counts:** Cao 16,013 retained of 16,013 strict; Chen 490,007 of 920,359 (21 states sampled); LP 35,428 of 35,428. The same pairs are used for every family and configuration.
- **Weights:** within each training set, w = 1/(G · S_g · P_s), where G = graphs with ≥ 1 informative state, S_g = informative states of graph g, and P_s = retained pairs of state s. Weights sum to 1, and the magnitude of node savings is never used.

## Features

- **Inputs:** only the extraction allowlists (12 inputs for Cao and Chen, 11 for LP).
- **Candidate columns:** `f_cand_*`, `f_nbr_*`, `f_lp_root_common_neighbors`. **Context columns:** `f_state_*`.
- **Linear features:** standardised candidate columns, plus all candidate × context products of standardised base columns, each product standardised again.
  - Means and population standard deviations are fitted on all candidate rows of the training-fold states only.
  - Zero-variance columns map to 0. Pure context terms are omitted (they cancel in pairs), and there is no intercept.
  - Dimensions: 6 + 36 = 42 (Cao and Chen); 6 + 30 = 36 (LP).
- **Boosted trees:** raw allowlisted inputs. There is no feature search, clipping or outcome-driven transform.

## Models (per solver; 3 solvers × 2 families × 6 configurations × 5 folds = 180 CV fits)

**Linear ranker.**
- Loss: s = θ·φ; L = Σ w log(1 + exp(−(s_b − s_w))) + λ/2 ‖θ‖², computed with `logaddexp`.
- Optimiser: SciPy L-BFGS-B from θ = 0 (maxiter 10000, maxfun 50000, gtol 1e-8, ftol 1e-14, maxcor 20).
- Converged iff ‖∇L‖∞ ≤ 1e-6, θ is finite, and the iteration limit is not reached. Anything else is a failed fit, and a configuration with any failed fold is invalid for selection.
- λ ∈ {1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1}.

**Boosted-tree scorer.**
- XGBoost 2.1.3 `xgb.train` with a custom objective computing the same loss on per-candidate margins.
- With p = σ(s_w − s_b): g_b −= w·p, g_w += w·p; h_b, h_w += 2·w·p(1 − p).
- The exact Hessian has off-diagonal terms. D = diag(h) is a valid upper bound, because D − H = Σ w p(1−p)(e_b + e_w)(e_b + e_w)ᵀ ⪰ 0; this is verified numerically in the tests.
- Common scaling: g and h are multiplied by C = number of retained training pairs, for every fit. This is equivalent to the unscaled loss with `reg_lambda`/C and `min_child_weight`/C. The scaling is verified by finite differences.
- Rows: candidates occurring in ≥ 1 retained training pair.
- Grid: max_depth ∈ {2, 3} × rounds ∈ {50, 100, 200}, each trained separately.
- Frozen parameters: eta 0.05, subsample 1, colsample_* 1, min_child_weight 1, reg_lambda 1, reg_alpha 0, gamma 0, max_delta_step 0, tree_method exact, nthread 1, seed 20261124, base_score 0, no default eval metric, no early stopping.

**Determinism and environment.** OMP, OpenBLAS and MKL threads are set to 1, with `PYTHONHASHSEED=0`. Pins: numpy 2.1.3, scipy 1.14.1, xgboost 2.1.3, Python 3.12 on `ubuntu-24.04`. No new configuration may be added after results are seen.

## Prediction, evaluation, selection

- **Selection rule:** the argmax score is chosen. On exact ties, the original pivot wins if it is among the maxima, else the lowest archived ordinal. There is no epsilon, gate or randomness, and a non-finite score fails the fit.
- **Exported-model check:** every fold model is exported (linear JSON with the transform, or XGBoost JSON), reloaded, and must reproduce the scores (max |Δ| ≤ 1e-6).
- **Per held-out state:** all scores, the selected and original candidates, comparability and exclusion reasons are kept.
  - When both arms are valid and compatible, report original − selected nodes, selected/original (only when original > 0), and win/tie/loss.
  - Otherwise the state is unresolved with explicit reasons, and no invented numeric cost is assigned.
  - Policy agreement is reported separately.
- **Fixed selection subset:** states in which every candidate is valid and all share one comparability key. On it:
  - cost = log((1 + selected)/(1 + original)), averaged within each graph over pooled out-of-fold states, then equally across graphs. Lower is better; 0 means the original pivot.
  - Best-candidate rate (any tied minimum counts) is secondary and is defined only on this subset.
- **Choosing configurations:** one per family per solver. Ties: larger λ for linear; fewer rounds, then smaller depth, for boosting. Families are not compared against each other; both advance.
- **Refits:** each selected configuration is refitted on all public data, with preprocessing re-fitted on public data (6 final models). These are retained and exported, not deployed.

## Ablation (30 fits)

Remove `f_nbr_none_wdeg_min/mean/max` and, for LP, `f_lp_root_common_neighbors`. Linear interactions involving them disappear with them. The same selected hyperparameters, folds, pairs and weights are used, with no retuning and no promotion. This is a development diagnostic only.

## Uncertainty and reporting

- **Bootstrap:** paired graph bootstrap with 2,000 resamples. The seed is derived by SHA-256 from 20261124 and a per-quantity label. It is applied to the selected models' graph-level selection metric, the comparable-state log ratio, and the main − ablation difference.
- **Interpretation:** these intervals describe development uncertainty conditional on this selection procedure and do not correct selection optimism.
- **Coverage:** reported by graph, state, candidate and pair, including all-tie states, entirely censored states, environment incompatibility, uninformative graphs, subset membership and first_A vs reservoir counts.
- **No claims:** no subgroup searches, no causal claims, and no claims of solver speedup or publication readiness.
