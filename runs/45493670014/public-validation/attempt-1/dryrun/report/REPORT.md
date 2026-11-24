# Public dry run (NOT benchmark results)

Graphs scheduled: 4 per solver. Every scheduled job is listed in the per-graph CSV. Paired measures use only jointly solved graphs, a subset of the scheduled graphs, and are optimistic about neither side: timeouts, errors and verification failures are counted, never imputed.

## Solver 5

Status counts: baseline: completed 2, cpu_timeout 2; linear: completed 2, cpu_timeout 2; boost: completed 2, cpu_timeout 2

### Baseline vs linear

Solved: baseline 2/4, linear 2/4. Both solved 2; baseline only 0; linear only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 2 / 0 / 0 | -1135.000 | 0.850 | 0.843 [0.742, 0.959] | 8828 | 6558 |
| cpu_s | 2 (1) | 0 / 1 / 1 | 0.008 | 1.000 | 1.000 [n/a, n/a] | 0.062 | 0.078 |
| wall_s | 2 (2) | 1 / 0 / 1 | 0.005 | 1.087 | 1.083 [0.999, 1.175] | 0.154 | 0.163 |

### Baseline vs boost

Solved: baseline 2/4, boost 2/4. Both solved 2; baseline only 0; boost only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 2 / 0 / 0 | -805.000 | 0.888 | 0.885 [0.817, 0.959] | 8828 | 7218 |
| cpu_s | 2 (1) | 0 / 0 / 2 | 0.047 | 2.250 | 2.250 [n/a, n/a] | 0.062 | 0.156 |
| wall_s | 2 (2) | 0 / 0 / 2 | 0.029 | 1.279 | 1.248 [1.001, 1.556] | 0.154 | 0.211 |

Timed-out invocations: 6 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

## Solver 8

Status counts: baseline: completed 2, cpu_timeout 2; linear: completed 2, cpu_timeout 2; boost: completed 2, cpu_timeout 2

### Baseline vs linear

Solved: baseline 2/4, linear 2/4. Both solved 2; baseline only 0; linear only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 1 / 0 / 1 | -901.000 | 0.934 | 0.926 [0.808, 1.061] | 9440 | 7638 |
| cpu_s | 2 (1) | 0 / 2 / 0 | 0.000 | 1.000 | 1.000 [n/a, n/a] | 0.094 | 0.094 |
| wall_s | 2 (2) | 1 / 0 / 1 | 0.000 | 1.037 | 1.033 [0.941, 1.134] | 0.161 | 0.161 |

### Baseline vs boost

Solved: baseline 2/4, boost 2/4. Both solved 2; baseline only 0; boost only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 1 / 1 / 0 | -952.000 | 0.899 | 0.893 [0.798, 1.000] | 9440 | 7536 |
| cpu_s | 2 (1) | 0 / 2 / 0 | 0.000 | 1.000 | 1.000 [n/a, n/a] | 0.094 | 0.094 |
| wall_s | 2 (2) | 1 / 0 / 1 | -0.003 | 0.976 | 0.975 [0.936, 1.016] | 0.161 | 0.155 |

Timed-out invocations: 6 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

## Solver LP

Status counts: baseline: completed 2, cpu_timeout 2; linear: completed 2, cpu_timeout 2; boost: completed 2, cpu_timeout 2

### Baseline vs linear

Solved: baseline 2/4, linear 2/4. Both solved 2; baseline only 0; linear only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 2 / 0 / 0 | -342.500 | 0.708 | 0.682 [0.519, 0.898] | 6632 | 5947 |
| cpu_s | 2 (1) | 1 / 1 / 0 | -0.008 | 1.000 | 1.000 [n/a, n/a] | 0.109 | 0.094 |
| wall_s | 2 (2) | 2 / 0 / 0 | -0.015 | 0.825 | 0.815 [0.695, 0.954] | 0.235 | 0.204 |

### Baseline vs boost

Solved: baseline 2/4, boost 2/4. Both solved 2; baseline only 0; boost only 0; both timed out 2; errors 0; verification failures 0; size disagreements 0; infrastructure failures 0; missing 0.

Jointly solved subset: 2 of 4 graphs (not the full set).

| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |
|---|---|---|---:|---:|---|---:|---:|
| nodes | 2 (2) | 2 / 0 / 0 | -226.000 | 0.947 | 0.947 [0.932, 0.963] | 6632 | 6180 |
| cpu_s | 2 (2) | 0 / 1 / 1 | 0.023 | 1.250 | 1.225 [1.000, 1.500] | 0.109 | 0.156 |
| wall_s | 2 (2) | 2 / 0 / 0 | -0.015 | 0.825 | 0.814 [0.693, 0.956] | 0.235 | 0.204 |

Timed-out invocations: 6 (observed prefixes only; listed in report.json, never used as complete trees or solve times).

