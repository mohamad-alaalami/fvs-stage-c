"""Paired benchmark report (integration-v1): baseline vs linear and baseline vs boost, separately per solver.

Usage: python integration/report.py --schedule schedule.json --jobs DIR [DIR ...] --out OUT

Input: job.json records anywhere under the given directories (attempt directories are preserved; the record's
GitHub run attempt and path identify it). Attempt rule (fixed in advance): per (solver, graph), the first attempt
without an infrastructure failure; invocations of different attempts are never mixed; a job without such an
attempt is 'infrastructure_failure' for all three policies. A scheduled job with no record is 'missing_record'.

Definitions
  solved            status completed AND verified feasible
  timeout           cpu_timeout / cpu_timeout_forced: an OBSERVED PREFIX; its nodes are not a complete tree and its
                    CPU cap is not a solve time; timeouts never enter differences or ratios
  error             solver_error / policy_error / configuration_error / driver_error / build_mismatch
  verification      verification_failed (a completed run whose output is not a feasible FVS), or completed sizes that
                    disagree between policies (exact solvers must agree), counted separately
  paired measures   only on jointly solved pairs: difference = learned - baseline; ratio = learned / baseline, defined
                    only when the baseline value > 0 (nodes >= 1 always; CPU can be 0 at Windows timer resolution);
                    log ratios aggregate as a geometric mean over graphs with a 95% percentile graph bootstrap
                    (2000 resamples, seed from SHA-256 of the quantity label)
"""
import argparse, collections, csv, hashlib, json, math, pathlib, statistics, sys

POLICIES = ('baseline', 'linear', 'boost')
INFRA = ('wall_watchdog', 'not_run_job_deadline', 'driver_error', 'missing_record', 'build_mismatch')
ERRORS = ('solver_error', 'policy_error', 'configuration_error')
TIMEOUTS = ('cpu_timeout', 'cpu_timeout_forced')


def boot_ci(values, label, B=2000):
    import random
    if len(values) < 2:
        return None
    seed = int(hashlib.sha256(('integration-v1|boot|' + label).encode()).hexdigest()[:16], 16)
    rnd = random.Random(seed); n = len(values); means = []
    for _ in range(B):
        means.append(sum(values[rnd.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [means[int(0.025 * B)], means[int(0.975 * B) - 1]]


def load_jobs(dirs):
    found = collections.defaultdict(list)
    for d in dirs:
        for p in sorted(pathlib.Path(d).rglob('job.json')):
            r = json.loads(p.read_text())
            if r.get('schema') != 'integration-v1-job':
                continue
            att = r.get('environment', {}).get('github_run_attempt', 'local')
            try:
                att_n = int(att)
            except ValueError:
                att_n = 0
            found[(r['job']['solver'], r['job']['graph_id'])].append((att_n, str(p), r))
    return found


def outcome(inv):
    s = inv['status']
    if s == 'completed' and inv.get('feasible'):
        return 'solved'
    if s == 'completed':
        return 'verification_failed'
    if s in TIMEOUTS:
        return 'timeout'
    if s in ERRORS:
        return 'error'
    if s == 'verification_failed':
        return 'verification_failed'
    return 'infrastructure'


def pair_stats(rows, fam, solver):
    cats = collections.Counter(); joint = []
    for r in rows:
        b, l = r['baseline'], r[fam]
        if r['job_outcome'] != 'ok':
            cats['infrastructure_failure' if r['job_outcome'] == 'infrastructure_failure' else 'missing_record'] += 1; continue
        ob, ol = outcome(b), outcome(l)
        if 'verification_failed' in (ob, ol):
            cats['verification_failure'] += 1
        elif 'error' in (ob, ol):
            cats['error'] += 1
        elif 'infrastructure' in (ob, ol):
            cats['infrastructure_failure'] += 1
        elif ob == ol == 'solved':
            if b['size'] != l['size']:
                cats['size_disagreement'] += 1
            else:
                cats['both_solved'] += 1; joint.append(r)
        elif ob == 'solved':
            cats['baseline_only_solved'] += 1
        elif ol == 'solved':
            cats['learned_only_solved'] += 1
        else:
            cats['both_timed_out'] += 1
    meas = {}
    for m in ('nodes', 'cpu_s', 'wall_s'):
        diffs = [r[fam][m] - r['baseline'][m] for r in joint]
        defined = [(r[fam][m], r['baseline'][m]) for r in joint if r['baseline'][m] and r['baseline'][m] > 0 and r[fam][m] and r[fam][m] > 0]
        logs = [math.log(x / y) for x, y in defined]
        ci = boot_ci(logs, f'{solver}|{fam}|{m}')
        meas[m] = dict(
            pairs=len(joint), ratio_defined_pairs=len(defined), ratio_undefined_pairs=len(joint) - len(defined),
            zero_rule='ratio defined only when both values > 0; differences use every jointly solved pair',
            learned_lower=sum(d < 0 for d in diffs), equal=sum(d == 0 for d in diffs), learned_higher=sum(d > 0 for d in diffs),
            median_difference=statistics.median(diffs) if diffs else None, sum_baseline=sum(r['baseline'][m] for r in joint), sum_learned=sum(r[fam][m] for r in joint),
            median_ratio=statistics.median([x / y for x, y in defined]) if defined else None,
            geometric_mean_ratio=math.exp(sum(logs) / len(logs)) if logs else None,
            geometric_mean_ratio_ci95=[math.exp(ci[0]), math.exp(ci[1])] if ci else None)
    solved_b = sum(1 for r in rows if r['job_outcome'] == 'ok' and outcome(r['baseline']) == 'solved')
    solved_l = sum(1 for r in rows if r['job_outcome'] == 'ok' and outcome(r[fam]) == 'solved')
    return dict(categories=dict(cats), graphs=len(rows), solved_baseline=solved_b, solved_learned=solved_l, jointly_solved=len(joint), measures=meas)


def build_rows(sched, found):
    rows = {s: [] for s in sched['jobs']}; notes = []
    for s, jobs in sched['jobs'].items():
        for j in jobs:
            cands = sorted(found.get((s, j['graph_id']), []), key=lambda x: (x[0], x[1]))
            chosen = next((c for c in cands if not c[2].get('infrastructure_failure')), None)
            row = dict(solver=s, graph_id=j['graph_id'], order=' > '.join(j['order']), attempts_found=len(cands))
            if chosen is None:
                row['job_outcome'] = 'infrastructure_failure' if cands else 'missing_record'
                for p in POLICIES:
                    row[p] = dict(status=row['job_outcome'], nodes=None, cpu_s=None, wall_s=None, size=None, feasible=None)
            else:
                row['job_outcome'] = 'ok'; row['attempt'] = chosen[0]; row['record'] = chosen[1]
                r = chosen[2]
                for p in POLICIES:
                    row[p] = r['invocations'].get(p, dict(status='missing_record'))
                row['completed_sizes_agree'] = r.get('completed_sizes_agree')
                row['environment'] = dict(cpu_model=r['environment'].get('cpu_model'), image=r['environment'].get('image'))
            rows[s].append(row)
    return rows, notes


def write_csv(path, rows):
    cols = ['solver', 'graph_id', 'order', 'job_outcome', 'attempt', 'attempts_found']
    for p in POLICIES:
        cols += [f'{p}_{k}' for k in ('status', 'size', 'feasible', 'cpu_s', 'wall_s', 'nodes', 'decisions', 'target', 'eligible', 'scored', 'departures', 'counts_source')]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(cols)
        for r in rows:
            line = [r.get('solver'), r.get('graph_id'), r.get('order'), r.get('job_outcome'), r.get('attempt'), r.get('attempts_found')]
            for p in POLICIES:
                v = r[p]
                line += [v.get(k) for k in ('status', 'size', 'feasible', 'cpu_s', 'wall_s', 'nodes', 'decisions', 'target', 'eligible', 'scored', 'departures', 'counts_source')]
            w.writerow(line)


def fmt(x, nd=3):
    if x is None:
        return 'n/a'
    if isinstance(x, float):
        return f'{x:.{nd}f}'
    return str(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--schedule', required=True); ap.add_argument('--jobs', nargs='+', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='Integration-v1 benchmark report')
    a = ap.parse_args()
    sched = json.loads(pathlib.Path(a.schedule).read_text())
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    found = load_jobs(a.jobs)
    rows, _ = build_rows(sched, found)
    report = dict(schema='integration-v1-report', graphs=len(sched['graph_ids']), solvers={}, definitions=__doc__)
    md = [f'# {a.title}', '', f'Graphs scheduled: {len(sched["graph_ids"])} per solver. Every scheduled job is listed in the per-graph CSV. '
          'Paired measures use only jointly solved graphs, a subset of the scheduled graphs, and are optimistic about neither side: '
          'timeouts, errors and verification failures are counted, never imputed.', '']
    for s, rs in rows.items():
        write_csv(out / f'per_graph_{s}.csv', rs)
        status = {p: dict(collections.Counter(r[p]['status'] for r in rs)) for p in POLICIES}
        sres = dict(status_counts=status, job_outcomes=dict(collections.Counter(r['job_outcome'] for r in rs)), comparisons={})
        md += [f'## Solver {s}', '', 'Status counts: ' + '; '.join(f'{p}: ' + ', '.join(f'{k} {v}' for k, v in sorted(c.items())) for p, c in status.items()), '']
        for fam in ('linear', 'boost'):
            st = pair_stats(rs, fam, s); sres['comparisons'][f'baseline_vs_{fam}'] = st
            c = st['categories']
            md += [f'### Baseline vs {fam}', '',
                   f'Solved: baseline {st["solved_baseline"]}/{st["graphs"]}, {fam} {st["solved_learned"]}/{st["graphs"]}. '
                   f'Both solved {c.get("both_solved", 0)}; baseline only {c.get("baseline_only_solved", 0)}; {fam} only {c.get("learned_only_solved", 0)}; '
                   f'both timed out {c.get("both_timed_out", 0)}; errors {c.get("error", 0)}; verification failures {c.get("verification_failure", 0)}; '
                   f'size disagreements {c.get("size_disagreement", 0)}; infrastructure failures {c.get("infrastructure_failure", 0)}; missing {c.get("missing_record", 0)}.', '',
                   f'Jointly solved subset: {st["jointly_solved"]} of {st["graphs"]} graphs (not the full set).', '',
                   '| Measure | Pairs (ratio-defined) | learned lower / equal / higher | Median diff (learned - baseline) | Median ratio | Geometric-mean ratio [95% graph bootstrap] | Sum baseline | Sum learned |',
                   '|---|---|---|---:|---:|---|---:|---:|']
            for m, v in st['measures'].items():
                ci = v['geometric_mean_ratio_ci95']
                md.append(f'| {m} | {v["pairs"]} ({v["ratio_defined_pairs"]}) | {v["learned_lower"]} / {v["equal"]} / {v["learned_higher"]} | {fmt(v["median_difference"])} | '
                          f'{fmt(v["median_ratio"])} | {fmt(v["geometric_mean_ratio"])} [{fmt(ci[0]) if ci else "n/a"}, {fmt(ci[1]) if ci else "n/a"}] | {fmt(v["sum_baseline"])} | {fmt(v["sum_learned"])} |')
            md.append('')
        tp = [dict(graph=r['graph_id'], policy=p, observed_prefix_nodes=r[p].get('nodes'), cpu_s=r[p].get('cpu_s')) for r in rs for p in POLICIES if r[p].get('status') in TIMEOUTS]
        sres['timeout_observed_prefixes'] = tp
        md += [f'Timed-out invocations: {len(tp)} (observed prefixes only; listed in report.json, never used as complete trees or solve times).', '']
        report['solvers'][s] = sres
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    (out / 'REPORT.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md[:40]))


if __name__ == '__main__':
    sys.exit(main())
