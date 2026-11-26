# Integration-v1 reserved benchmark

Graphs scheduled: 130 per solver. Every scheduled job is listed in the per-graph CSV. Paired measures use only jointly solved graphs, a subset of the scheduled graphs, and are optimistic about neither side: timeouts, errors and verification failures are counted, never imputed.

## Solver 5

Status counts: baseline: completed 48, cpu_timeout 82; linear: completed 45, cpu_timeout 85; boost: completed 48, cpu_timeout 82

### Baseline vs linear

Solved: baseline 48/130, linear 45/130. Both solved 45; baseline only 3; linear only 0; both timed out 82; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 45 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 45 (45) | 18 / 20 / 7 | 0 | 1.000 | 0.980 [0.837, 1.233] | 266190570 | 260992898 |
| cpu_s | 45 (23) | 13 / 19 / 13 | 0.000 | 1.000 | 1.153 [0.899, 1.651] | 800.797 | 1211.047 |
| wall_s | 45 (45) | 18 / 0 / 27 | 0.000 | 1.002 | 1.033 [0.928, 1.169] | 806.532 | 1219.775 |

### Baseline vs boost

Solved: baseline 48/130, boost 48/130. Both solved 48; baseline only 0; boost only 0; both timed out 82; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 48 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 48 (48) | 22 / 21 / 5 | 0.000 | 1.000 | 0.871 [0.804, 0.932] | 847816086 | 536069555 |
| cpu_s | 48 (32) | 2 / 20 / 26 | 0.016 | 1.464 | 1.497 [1.284, 1.749] | 2930.094 | 4749.141 |
| wall_s | 48 (48) | 10 / 0 / 38 | 0.007 | 1.135 | 1.271 [1.154, 1.409] | 2943.679 | 4771.499 |

Timed-out invocations: 249 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

## Solver 8

Status counts: baseline: completed 53, cpu_timeout 77; linear: completed 53, cpu_timeout 77; boost: completed 53, cpu_timeout 77

### Baseline vs linear

Solved: baseline 53/130, linear 53/130. Both solved 53; baseline only 0; linear only 0; both timed out 77; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 53 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 53 (53) | 20 / 26 / 7 | 0 | 1.000 | 0.923 [0.880, 0.964] | 127649241 | 117004468 |
| cpu_s | 53 (27) | 20 / 21 / 12 | 0.000 | 1.000 | 0.968 [0.894, 1.058] | 1188.797 | 1222.484 |
| wall_s | 53 (53) | 27 / 0 / 26 | -0.000 | 1.000 | 0.972 [0.943, 1.000] | 1197.697 | 1231.868 |

### Baseline vs boost

Solved: baseline 53/130, boost 53/130. Both solved 53; baseline only 0; boost only 0; both timed out 77; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 53 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 53 (53) | 22 / 28 / 3 | 0 | 1.000 | 0.917 [0.878, 0.952] | 127649241 | 105258977 |
| cpu_s | 53 (30) | 15 / 27 / 11 | 0.000 | 1.000 | 0.969 [0.925, 1.008] | 1188.797 | 1157.875 |
| wall_s | 53 (53) | 26 / 0 / 27 | 0.000 | 1.000 | 0.998 [0.962, 1.037] | 1197.697 | 1167.602 |

Timed-out invocations: 231 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

## Solver LP

Status counts: baseline: completed 46, cpu_timeout 84; linear: completed 46, cpu_timeout 84; boost: completed 46, cpu_timeout 84

### Baseline vs linear

Solved: baseline 46/130, linear 46/130. Both solved 46; baseline only 0; linear only 0; both timed out 84; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 46 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 46 (46) | 25 / 18 / 3 | -3.000 | 0.977 | 0.910 [0.872, 0.948] | 249093569 | 219125766 |
| cpu_s | 46 (24) | 15 / 21 / 10 | 0.000 | 1.000 | 1.008 [0.918, 1.122] | 2007.672 | 1904.750 |
| wall_s | 46 (46) | 24 / 0 / 22 | -0.000 | 0.998 | 0.978 [0.953, 1.003] | 2022.227 | 1918.630 |

### Baseline vs boost

Solved: baseline 46/130, boost 46/130. Both solved 46; baseline only 0; boost only 0; both timed out 84; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 46 of 130 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 46 (46) | 24 / 15 / 7 | -2.500 | 0.948 | 0.941 [0.896, 0.991] | 249093569 | 218701632 |
| cpu_s | 46 (28) | 2 / 17 / 27 | 0.016 | 1.155 | 1.160 [1.076, 1.267] | 2007.672 | 2484.594 |
| wall_s | 46 (46) | 13 / 0 / 33 | 0.004 | 1.040 | 1.081 [1.032, 1.135] | 2022.227 | 2500.714 |

Timed-out invocations: 252 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

