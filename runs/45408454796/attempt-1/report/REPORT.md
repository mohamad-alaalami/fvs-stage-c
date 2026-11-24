# Offline learnability results (fvs-learnability-offline-v1)

Extraction `extract-v1-20261124T115559Z-833e6421`. Development (cross-validated) results; NOT an unbiased final test. No solver was run; nothing here measures complete-solver performance.

Fits: 216/216 ok ({"main_cv": 180, "final_refit": 6, "ablation": 30}); total fit CPU 249 s.

## Selection metric by configuration

Metric: graph-aggregated mean of log((1+selected nodes)/(1+original nodes)) on the fixed complete-compatible subset (lower is better; 0 = original pivot).

| Solver | Family | Config | Valid | Metric | Agreement | Comparable W/T/L | Best-candidate rate |
|---|---|---|---|---:|---:|---|---:|
| 8 | linear | lambda=1e-05 | True | -0.0246 | 0.490 | 273/1441/192 | 0.718 |
| 8 | linear | lambda=0.0001 | True | -0.0259 | 0.487 | 277/1434/196 | 0.718 |
| 8 | linear | lambda=0.001 | True | -0.0260 | 0.493 | 277/1440/189 | 0.716 |
| 8 | linear | lambda=0.01 | True | -0.0260 | 0.491 | 280/1438/190 | 0.715 |
| 8 | linear | lambda=0.1 **(selected)** | True | -0.0266 | 0.514 | 278/1445/187 | 0.718 |
| 8 | linear | lambda=1 | True | -0.0266 | 0.496 | 283/1438/187 | 0.719 |
| 8 | boost | depth=2,rounds=50 **(selected)** | True | -0.0300 | 0.631 | 243/1533/142 | 0.714 |
| 8 | boost | depth=2,rounds=100 | True | -0.0280 | 0.584 | 254/1498/163 | 0.715 |
| 8 | boost | depth=2,rounds=200 | True | -0.0254 | 0.580 | 256/1492/167 | 0.714 |
| 8 | boost | depth=3,rounds=50 | True | -0.0232 | 0.621 | 239/1526/153 | 0.711 |
| 8 | boost | depth=3,rounds=100 | True | -0.0253 | 0.596 | 248/1509/160 | 0.711 |
| 8 | boost | depth=3,rounds=200 | True | -0.0242 | 0.572 | 247/1502/165 | 0.715 |
| 5 | linear | lambda=1e-05 | True | -0.0621 | 0.588 | 301/1693/176 | 0.663 |
| 5 | linear | lambda=0.0001 **(selected)** | True | -0.0626 | 0.615 | 297/1716/159 | 0.671 |
| 5 | linear | lambda=0.001 | True | -0.0551 | 0.580 | 289/1720/161 | 0.663 |
| 5 | linear | lambda=0.01 | True | -0.0535 | 0.604 | 280/1715/183 | 0.658 |
| 5 | linear | lambda=0.1 | True | -0.0483 | 0.594 | 283/1696/198 | 0.655 |
| 5 | linear | lambda=1 | True | -0.0405 | 0.539 | 288/1611/270 | 0.634 |
| 5 | boost | depth=2,rounds=50 | True | -0.0488 | 0.763 | 201/1883/107 | 0.663 |
| 5 | boost | depth=2,rounds=100 | True | -0.0521 | 0.735 | 220/1846/121 | 0.661 |
| 5 | boost | depth=2,rounds=200 | True | -0.0527 | 0.740 | 222/1846/121 | 0.660 |
| 5 | boost | depth=3,rounds=50 | True | -0.0385 | 0.755 | 186/1900/107 | 0.652 |
| 5 | boost | depth=3,rounds=100 | True | -0.0468 | 0.727 | 214/1871/105 | 0.661 |
| 5 | boost | depth=3,rounds=200 **(selected)** | True | -0.0581 | 0.735 | 219/1874/99 | 0.667 |
| LP | linear | lambda=1e-05 | True | -0.0324 | 0.585 | 323/1820/145 | 0.783 |
| LP | linear | lambda=0.0001 | True | -0.0346 | 0.563 | 323/1817/147 | 0.783 |
| LP | linear | lambda=0.001 | True | -0.0341 | 0.555 | 308/1843/137 | 0.780 |
| LP | linear | lambda=0.01 **(selected)** | True | -0.0373 | 0.557 | 298/1860/132 | 0.779 |
| LP | linear | lambda=0.1 | True | -0.0355 | 0.580 | 290/1866/133 | 0.778 |
| LP | linear | lambda=1 | True | -0.0299 | 0.577 | 283/1863/143 | 0.772 |
| LP | boost | depth=2,rounds=50 | True | -0.0394 | 0.745 | 268/1909/115 | 0.779 |
| LP | boost | depth=2,rounds=100 | True | -0.0419 | 0.735 | 271/1914/107 | 0.780 |
| LP | boost | depth=2,rounds=200 | True | -0.0466 | 0.723 | 272/1904/116 | 0.776 |
| LP | boost | depth=3,rounds=50 | True | -0.0415 | 0.704 | 281/1915/98 | 0.789 |
| LP | boost | depth=3,rounds=100 | True | -0.0467 | 0.678 | 290/1880/123 | 0.783 |
| LP | boost | depth=3,rounds=200 **(selected)** | True | -0.0496 | 0.667 | 297/1872/123 | 0.787 |

## Selected configurations versus the original pivot

| Solver | Family | Config | Subset states/graphs | Metric | 95% graph-bootstrap interval | Comparable log-ratio (interval) | Ablation metric | Main - ablation (interval) |
|---|---|---|---|---:|---|---|---:|---|
| 8 | linear | lambda=0.1 | 1878/83 | -0.0266 | [-0.0449, -0.0117] | -0.0256 [-0.0427, -0.0110] | -0.0296 | 0.0029 [-0.0004, 0.0065] |
| 8 | boost | depth=2,rounds=50 | 1878/83 | -0.0300 | [-0.0467, -0.0166] | -0.0288 [-0.0457, -0.0151] | -0.0312 | 0.0012 [-0.0031, 0.0057] |
| 5 | linear | lambda=0.0001 | 1990/92 | -0.0626 | [-0.0986, -0.0331] | -0.0628 [-0.1011, -0.0320] | -0.0594 | -0.0032 [-0.0086, 0.0025] |
| 5 | boost | depth=3,rounds=200 | 1990/92 | -0.0581 | [-0.0919, -0.0305] | -0.0501 [-0.0859, -0.0217] | -0.0580 | -0.0001 [-0.0055, 0.0057] |
| LP | linear | lambda=0.01 | 2241/92 | -0.0373 | [-0.0540, -0.0207] | -0.0380 [-0.0540, -0.0218] | 0.0017 | -0.0390 [-0.0556, -0.0218] |
| LP | boost | depth=3,rounds=200 | 2241/92 | -0.0496 | [-0.0749, -0.0287] | -0.0500 [-0.0748, -0.0304] | -0.0057 | -0.0440 [-0.0596, -0.0282] |

Intervals: paired graph bootstrap (2000 fixed-seed resamples of graphs). They describe development uncertainty conditional on this selection procedure and do not correct selection optimism.

## Coverage

| Solver | States | Informative | All-tie | Entirely censored | Env-incompatible | Excluded | Subset states/graphs | Retained/strict pairs | Graphs w/o informative states |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| 5 | 2212 | 1766 | 446 | 0 | 222 | 0 | 1990/92 | 490007/920359 | 001, 008, 021, 041, 068, 071, 082, 090 |
| 8 | 1983 | 1086 | 838 | 59 | 46 | 0 | 1878/83 | 16013/16013 | 001, 008, 014, 019, 021, 022, 039, 041, 053, 057, 068, 071, 072, 073, 078, 080, 082, 083, 090, 095, 096 |
| LP | 2307 | 1474 | 833 | 0 | 66 | 0 | 2241/92 | 35428/35428 | 001, 008, 021, 032, 041, 068, 071, 079 |

## Limitations

- Saved Stage C states are a selected sample (first A state plus seeded reservoir; 64 KiB slot cap); outcomes are single first-pivot substitutions followed by the original policy, with a 10 s CPU cap per arm.
- Labels are exact node totals of those continuations; the node metric is a surrogate. Repeated learned decisions, prediction overhead and complete-solver behaviour are untested.
- Cross-validated selection over 6 configurations per family reuses the same folds for selection and reporting; selected-model results are optimistic development estimates.
- Pairs are restricted to identical CPU/image/executable groups; states spanning runners contribute only within-group pairs and are outside the selection subset.
- Graph identity audit is bounded (raw/edge-multiset hashes, 1-WL signatures); it does not prove absence of isomorphic or related instances.
- The 130 reserved hidden graphs were not accessed; they remain the future independent benchmark.
