# Addendum rescore-linear-v1-20261125T154331Z-02ac7c57: linear fold models rescored with the deployed scorer

Addendum to offline learnability run 45408454796 (branch `learnability-results`, commit `e5b8401`). Nothing was refitted, retuned or reselected; no solver was run; no reserved graph was opened (all states are from the public extraction `extract-v1-20261124T115559Z-833e6421`).

## What was done

- **Models:** the 90 archived linear CV fold models (3 solvers x 6 lambdas x 5 folds), each scored only on its original held-out fold.
- **Old scorer:** the offline scorer as run in training, `transform(X) @ theta` (numpy, batched per state). It reproduces every archived summary of run 45408454796 exactly, including per-fold summaries, and the archived per-state records of the three frozen configurations (one state differs only in the last bit of `log`, a libm difference; selection identical).
- **Corrected scorer:** `PolicyReplay.exe` from validated build 45493670014 (sha256 `24e2fd2e...`). It runs the solver's own `selectCore`, with features computed live from the Stage C snapshot. A Python left-to-right replica of the live summation agreed with it bit for bit on every candidate, and the live features equalled the archived table exactly.
- **Unchanged rules:** the tie rule (argmax; exact ties go to the original pivot if it is among the maxima, else the lowest archived ordinal), `evaluate_state`, the development metric and the configuration-choice rule are the frozen code of commit `27c43b7`.
- **Checks:** 480/480 passed.

**Definitions.** A *changed selection* is a held-out state where the corrected pick differs from the old pick. The *observed node total* is the Stage D exact node count of the selected candidate. It is *observable* for a changed state when both picks are valid with the same comparability key in a non-excluded state; otherwise it is reported as unobservable, never imputed. The *development metric* is the frozen selection metric: graph-equal mean of log((1+selected)/(1+original)) on the fixed complete-compatible subset (lower is better, 0 = original pivot).

## Frozen configurations

| Solver | Frozen config | Held-out states | Changed selections | Node total observable | Changed | Lower / higher | Unchanged | Unobservable | Old metric | Corrected metric | Choice would change? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 (Chen) | lambda=0.0001 | 2212 | 168 (7.6%) | 162 | 44 | 17 / 27 | 118 | 6 | -0.062628 | -0.061402 | **yes**, to lambda=1e-05 |
| 8 (Cao) | lambda=0.1 | 1983 | 54 (2.7%) | 48 | 18 | 10 / 8 | 30 | 6 | -0.026629 | -0.026894 | no |
| LP | lambda=0.01 | 2307 | 251 (10.9%) | 250 | 7 | 4 / 3 | 243 | 1 | -0.037300 | -0.037266 | no |

In every changed state, across all 18 configurations, the two picks have identical feature rows and the old pick is still one of the deployed maxima. The change is therefore purely the tie rule now being applied to exact ties. No change ever moves a selection away from the original pivot; most move to it.

## Configuration choice (all lambdas, unchanged choice rule)

### 5 (Chen)

| Config | Changed selections | Node total changed (of observable) | Old metric | Corrected metric | Old agreement | Corrected agreement | Old W/T/L | Corrected W/T/L |
|---|---|---|---|---|---|---|---|---|
| lambda=0.0001 (frozen) | 168 | 44 of 162 | -0.062628 | -0.061402 | 0.6153 | 0.6858 | 297/1716/159 | 273/1762/143 |
| lambda=0.001 | 239 | 40 of 230 | -0.055095 | -0.055246 | 0.5796 | 0.6840 | 289/1720/161 | 271/1767/141 |
| lambda=0.01 | 178 | 39 of 172 | -0.053530 | -0.053330 | 0.6035 | 0.6799 | 280/1715/183 | 261/1759/164 |
| lambda=0.1 | 183 | 47 of 179 | -0.048340 | -0.048526 | 0.5940 | 0.6727 | 283/1696/198 | 258/1746/177 |
| lambda=1 | 192 | 42 of 188 | -0.040537 | -0.040265 | 0.5393 | 0.6198 | 288/1611/270 | 268/1654/251 |
| lambda=1e-05 | 215 | 63 of 208 | -0.062112 | -0.062433 | 0.5882 | 0.6799 | 301/1693/176 | 274/1759/144 |

- Old ranking: lambda=0.0001, lambda=1e-05, lambda=0.001, lambda=0.01, lambda=0.1, lambda=1; choice **lambda=0.0001** (margin to runner-up 5.16e-04).
- Corrected ranking: lambda=1e-05, lambda=0.0001, lambda=0.001, lambda=0.01, lambda=0.1, lambda=1; choice **lambda=1e-05** (margin 1.03e-03).
- Choice would change: **yes**.

### 8 (Cao)

| Config | Changed selections | Node total changed (of observable) | Old metric | Corrected metric | Old agreement | Corrected agreement | Old W/T/L | Corrected W/T/L |
|---|---|---|---|---|---|---|---|---|
| lambda=0.0001 | 117 | 31 of 105 | -0.025912 | -0.026492 | 0.4871 | 0.5310 | 277/1434/196 | 268/1464/181 |
| lambda=0.001 | 98 | 21 of 85 | -0.026009 | -0.025588 | 0.4927 | 0.5285 | 277/1440/189 | 271/1461/181 |
| lambda=0.01 | 96 | 19 of 91 | -0.026042 | -0.025717 | 0.4907 | 0.5280 | 280/1438/190 | 273/1455/183 |
| lambda=0.1 (frozen) | 54 | 18 of 48 | -0.026629 | -0.026894 | 0.5139 | 0.5330 | 278/1445/187 | 274/1460/179 |
| lambda=1 | 99 | 26 of 90 | -0.026600 | -0.026742 | 0.4962 | 0.5310 | 283/1438/187 | 277/1458/177 |
| lambda=1e-05 | 109 | 33 of 96 | -0.024601 | -0.025237 | 0.4902 | 0.5310 | 273/1441/192 | 268/1468/177 |

- Old ranking: lambda=0.1, lambda=1, lambda=0.01, lambda=0.001, lambda=0.0001, lambda=1e-05; choice **lambda=0.1** (margin to runner-up 2.96e-05).
- Corrected ranking: lambda=0.1, lambda=1, lambda=0.0001, lambda=0.01, lambda=0.001, lambda=1e-05; choice **lambda=0.1** (margin 1.52e-04).
- Choice would change: **no**.

### LP

| Config | Changed selections | Node total changed (of observable) | Old metric | Corrected metric | Old agreement | Corrected agreement | Old W/T/L | Corrected W/T/L |
|---|---|---|---|---|---|---|---|---|
| lambda=0.0001 | 253 | 14 of 251 | -0.034614 | -0.035977 | 0.5626 | 0.6485 | 323/1817/147 | 326/1823/140 |
| lambda=0.001 | 261 | 9 of 259 | -0.034080 | -0.034036 | 0.5553 | 0.6541 | 308/1843/137 | 305/1853/132 |
| lambda=0.01 (frozen) | 251 | 7 of 250 | -0.037300 | -0.037266 | 0.5566 | 0.6515 | 298/1860/132 | 297/1865/129 |
| lambda=0.1 | 203 | 3 of 201 | -0.035485 | -0.035174 | 0.5804 | 0.6563 | 290/1866/133 | 289/1871/131 |
| lambda=1 | 207 | 11 of 204 | -0.029871 | -0.030765 | 0.5765 | 0.6537 | 283/1863/143 | 283/1872/137 |
| lambda=1e-05 | 169 | 12 of 168 | -0.032412 | -0.033378 | 0.5847 | 0.6424 | 323/1820/145 | 321/1827/141 |

- Old ranking: lambda=0.01, lambda=0.1, lambda=0.0001, lambda=0.001, lambda=1e-05, lambda=1; choice **lambda=0.01** (margin to runner-up 1.81e-03).
- Corrected ranking: lambda=0.01, lambda=0.0001, lambda=0.1, lambda=0.001, lambda=1e-05, lambda=1; choice **lambda=0.01** (margin 1.29e-03).
- Choice would change: **no**.

## Interpretation limits

- **Development estimates:** these are pooled out-of-fold development estimates, not an unbiased test, and they carry the selection optimism of the original protocol. No bootstrap was recomputed.
- **Small margins:** the margins between configurations are small, so a changed choice here does not show that one lambda is better.
- **Frozen models unchanged:** the frozen refits, the deployed models and their hashes are unchanged. This addendum only reports what the archived development metric becomes under the deployed tie rule.
- **Superseded first execution:** it is kept in `superseded-execution-1/`. Its two failed checks were check-design issues, not result changes: CRLF in the `git archive` copy of `folds.json` (identical after LF normalisation), and one archived `selection_cost` differing in its last bit. Its results are identical to this execution.

## Files

- `results.json`: every check, the old and corrected summaries per configuration, tallies, rankings and the environment.
- `changed_states.jsonl.gz`: one record per changed state, for every solver and configuration.
- `code/`: `rescore_linear.py`, `make_report.py`.
- `inputs/`: the archived fold models, frozen manifests, selection, selected-state records and `PolicyReplay.exe`.
- `MANIFEST.json`: SHA-256 of every file; `COMPLETE` holds SHA-256(`MANIFEST.json`).
