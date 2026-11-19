"""Merge per-pair job records into results.csv, summary.json and REPORT.md.
Usage: python aggregate.py <dir with summary-* artifact folders> <output dir>
Missing pairs (job failed/cancelled before writing records) appear as 'job_missing', never as zero."""
import csv, json, pathlib, sys

GRAPHS = ['095', '029', '076', '031', '002', '069', '089', '071', '014', '038']
SOLVERS = ['8', '5', 'LP']
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
found = {}
for p in src.rglob('pairs.json'):
    for r in json.loads(p.read_text()):
        found[(r['graph'], r['solver'])] = r
rows = []
for g in GRAPHS:
    for s in SOLVERS:
        rows.append(found.get((g, s), dict(graph=g, solver=s, status='job_missing', replay='untested')))
fields = []
for r in rows:
    fields += [k for k in r if k not in fields]
with (out / 'results.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, restval='unknown'); w.writeheader(); w.writerows(rows)

keys = ['B', 'T', 'A', 'snapshot_count', 'snapshot_bytes', 'log_bytes', 'total_bytes', 'snapshot_stored_bytes', 'log_stored_bytes', 'total_stored_bytes',
        'baseline_cpu_s', 'instrumented_cpu_s', 'baseline_wall_s', 'instrumented_wall_s']
totals = {k: sum(r[k] for r in rows if num(r.get(k))) for k in keys}
measured = [r for r in rows if num(r.get('total_bytes'))]
largest = max(measured, key=lambda r: r['total_bytes'], default=None)
largest_snap = max((r for r in rows if num(r.get('largest_snapshot_bytes'))), key=lambda r: r['largest_snapshot_bytes'], default=None)
complete = [r for r in rows if r.get('status') == 'completed']
censored = [r for r in measured if r.get('status') != 'completed']
checks = dict(
    B_ge_T_ge_A=all(r['B'] >= r['T'] >= r['A'] for r in rows if num(r.get('B'))),
    audits_pass=sum(r.get('audit') == 'pass' for r in rows), audits_partial=sum(r.get('audit') == 'partial' for r in rows),
    audits_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('audit') == 'fail'],
    replay_pass=sum(r.get('replay') == 'pass' for r in rows), replay_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('replay') == 'fail'],
    replay_untested_with_A=[f"{r['graph']}/{r['solver']}: {r.get('replay')}" for r in rows if num(r.get('A')) and r['A'] > 0 and r.get('replay') != 'pass'],
    feasibility_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('feasible') is False or r.get('baseline_feasible') is False],
    reference_mismatch=[f"{r['graph']}/{r['solver']}" for r in rows if 'mismatch' in (r.get('reference_verdict'), r.get('baseline_reference_verdict'))],
    baseline_disagreement=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('baseline_validation') is False],
    invariant_failures=sum(r['invariant_failures'] for r in rows if num(r.get('invariant_failures'))),
    job_missing=[f"{r['graph']}/{r['solver']}" for r in rows if r['status'] == 'job_missing'])
summary = dict(pairs=len(rows), completed_pairs=len(complete), censored_pairs=[f"{r['graph']}/{r['solver']}: {r['status']}" for r in censored],
               totals=totals, largest_run=largest and {k: largest.get(k) for k in ['graph', 'solver', 'status', 'total_bytes', 'total_stored_bytes', 'A']},
               largest_snapshot=largest_snap and {k: largest_snap.get(k) for k in ['graph', 'solver', 'largest_snapshot_bytes', 'instrumented_run_id']},
               checks=checks)
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


def fmt(x, d=0):
    return f'{x:,.{d}f}' if num(x) else str(x)


def overhead(r):
    b, i = r.get('baseline_cpu_s'), r.get('instrumented_cpu_s')
    if r.get('status') != 'completed' or r.get('baseline_status') != 'completed': return 'censored'
    if not (num(b) and num(i)) or min(b, i) < .1: return 'below timer resolution'
    return f'{i / b:.3f}x'


L = ['# Stage C smoke test (GitHub Actions)', '',
     f"{len(complete)}/30 pairs completed within the 1,800 s CPU limit; {len(censored)} censored (timeout/disk/deadline); "
     f"{len(checks['job_missing'])} missing. Byte columns: logical = uncompressed snapshot + event + continuation streams; stored = zlib-6 on disk/artifact.", '',
     '| Graph | Solver | Status | B | T | A | Snapshots | Logical bytes | Stored bytes | Bytes/snapshot | CPU overhead | Replay |',
     '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|']
for r in rows:
    L.append('| ' + ' | '.join([r['graph'], r['solver'], str(r['status']), *[fmt(r.get(k, 'unknown')) for k in ['B', 'T', 'A', 'snapshot_count', 'total_bytes', 'total_stored_bytes', 'bytes_per_snapshot']],
                                overhead(r), str(r.get('replay'))]) + ' |')
L += ['', '**Totals:** ' + ', '.join(f'{k} = {fmt(v, 1 if k.endswith("_s") else 0)}' for k, v in totals.items()), '']
if largest: L.append(f"**Largest run:** {largest['graph']}/{largest['solver']} ({largest['status']}): {fmt(largest['total_bytes'])} logical bytes, {fmt(largest['total_stored_bytes'])} stored.")
if largest_snap: L.append(f"**Largest snapshot:** {fmt(largest_snap['largest_snapshot_bytes'])} bytes ({largest_snap['graph']}/{largest_snap['solver']}).")
L += ['', '## Checks', '', '```json', json.dumps(checks, indent=2), '```', '', '## Storage implications for the 100 public graphs', '']
if complete or censored:
    per_cpu = [r['observed_growth_bytes_per_cpu_s'] for r in censored if num(r.get('observed_growth_bytes_per_cpu_s'))]
    ratio = totals['total_bytes'] / totals['total_stored_bytes'] if totals['total_stored_bytes'] else 'unknown'
    L += [f"- Measured payload over these 30 pairs: {fmt(totals['total_bytes'])} logical bytes, {fmt(totals['total_stored_bytes'])} stored (compression ratio {fmt(ratio, 1)}x).",
          f"- Linear 10x scenario (100 graphs x 3 solvers): ~{fmt(totals['total_bytes'] * 10)} logical / ~{fmt(totals['total_stored_bytes'] * 10)} stored bytes.",
          f"- Censored runs grow at {', '.join(fmt(x / 2**20, 1) + ' MiB/CPU-s' for x in per_cpu) or 'n/a'}; each censored run's bytes are a lower bound for its complete search.",
          '- Assumptions: the ten graphs (a hand-picked, not random, order) are representative of the public set; same solver mix, original policies, snapshot schema, zlib-6 codec, 1,800 s CPU budget and comparable runner speed. '
          'Storage is dominated by A-event frequency x search-tree size, not snapshot size; censored (timed-out) runs make every total a lower bound, and a faster machine reaches further into the tree within the same CPU budget, producing more bytes.']
(out / 'REPORT.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print('\n'.join(L))
