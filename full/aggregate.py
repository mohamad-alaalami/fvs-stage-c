"""Compact report: exactly one row for each of the 300 scheduled pairs.
Usage: python aggregate.py <schedule.json> <runs/<run_id> dir> <output dir> <tree URL base>
record_status: recorded | runner_error | missing (no pair.json: job never started or failed before recording).
A measured zero is 0; missing data is 'missing'; inapplicable values are 'n/a'."""
import csv, json, pathlib, sys
sched = json.loads(pathlib.Path(sys.argv[1]).read_text()); base = pathlib.Path(sys.argv[2]); out = pathlib.Path(sys.argv[3]); url = sys.argv[4]
out.mkdir(parents=True, exist_ok=True)
rows = []; T = dict(B=0, T=0, A=0, A_chen_strict_merge=0, sample_stored_bytes=0, sample_raw_bytes=0)
for p in sched['part1'] + sched['part2']:
    g, s = p['graph'], p['solver']; d = base / 'pairs' / f'{g}-{s}'
    attempts = sorted(d.glob('attempt-*/pair.json'), key=lambda x: int(x.parent.name.split('-')[1])) if d.exists() else []
    row = dict(graph=g, solver=s, attempts=len(attempts))
    if not attempts:
        row.update(record_status='missing'); rows.append(row); continue
    j = json.loads(attempts[-1].read_text()); rel = attempts[-1].parent.relative_to(base.parent.parent).as_posix()
    row.update(record_status=j['status'], record_path=rel, record_url=f'{url}/{rel}')
    if j['status'] != 'recorded':
        rows.append(row); continue
    b, i, c = j['baseline'], j['instrumented'], j.get('counts')
    bv, iv = b['verification'], i['verification']
    nodes = c['nodes'] if c else None
    ntot = sum(nodes[k]['entered_main'] + nodes[k]['entered_component'] for k in ('branching', 'solve1', 'solve2')) if c else 'missing'
    ncomp = sum(nodes[k]['entered_component'] for k in ('branching', 'solve1', 'solve2')) if c else 'missing'
    agree = j['solution_agreement']
    row.update(vertices=j['vertices'], edges=j['edges'], reference_optimum=j['reference_optimum'],
               baseline_status=b['status'], baseline_exit=b['exit_code'], baseline_cpu_s=b['cpu_s'], baseline_wall_s=b['wall_s'], baseline_peak_bytes=b['peak_working_set_bytes'],
               baseline_size=bv['returned_size'], baseline_feasible=bv['feasible'], baseline_reference=bv['reference_verdict'], baseline_nodes='unavailable',
               instrumented_status=i['status'], instrumented_exit=i['exit_code'], instrumented_cpu_s=i['cpu_s'], instrumented_wall_s=i['wall_s'], instrumented_peak_bytes=i['peak_working_set_bytes'],
               instrumented_size=iv['returned_size'], instrumented_feasible=iv['feasible'], instrumented_reference=iv['reference_verdict'],
               sizes_agree=agree['sizes_equal'] if isinstance(agree, dict) else 'n/a', counts_source=i['counts_source'],
               B=c['B'] if c else 'missing', T=c['T'] if c else 'missing', A=c['A'] if c else 'missing',
               A_chen_strict_merge=(c['A_chen_strict_merge'] if s == '5' else 'n/a') if c else 'missing',
               instrumented_nodes=ntot, component_nodes=ncomp, consistency=('pass' if j['consistency_pass'] else 'fail') if c else 'missing',
               saved_states=len(j['saved_states']), first_A_saved=j['sample_metadata'].get('first_A_unsaved_bytes', 0) == 0 and any(x['kind'] == 'first_A' for x in j['saved_states']),
               first_A_unsaved_bytes=j['sample_metadata'].get('first_A_unsaved_bytes', 0), excluded_for_size=j['sample_metadata'].get('excluded_for_size', 0),
               sample_raw_bytes=j['sample_storage']['raw_bytes'], sample_stored_bytes=j['sample_storage']['stored_bytes'],
               sample_check=j['sample_check']['status'], replay=j['replay']['status'], replays_run=len(j['replay'].get('results', [])),
               exec_cpu=j['execution_environment']['cpu_model'], exec_image=j['execution_environment']['image'], build_id=j['build_id'],
               baseline_run_id=b['run_id'], instrumented_run_id=i['run_id'])
    for k in T:
        if isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool): T[k] += row[k]
    rows.append(row)
assert len(rows) == 300
fields = []
for r in rows: fields += [k for k in r if k not in fields]
with (out / 'results.csv').open('w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, restval='n/a'); w.writeheader(); w.writerows(rows)
count = lambda pred: sum(1 for r in rows if pred(r))
summary = dict(pairs=300, recorded=count(lambda r: r['record_status'] == 'recorded'), missing=count(lambda r: r['record_status'] == 'missing'),
               runner_error=count(lambda r: r['record_status'] == 'runner_error'),
               both_completed=count(lambda r: r.get('baseline_status') == r.get('instrumented_status') == 'completed'),
               baseline_status={k: count(lambda r, k=k: r.get('baseline_status') == k) for k in sorted({r.get('baseline_status') for r in rows if r.get('baseline_status')})},
               instrumented_status={k: count(lambda r, k=k: r.get('instrumented_status') == k) for k in sorted({r.get('instrumented_status') for r in rows if r.get('instrumented_status')})},
               zero_branch_pairs=count(lambda r: r.get('B') == 0), totals=T,
               problems=dict(consistency_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('consistency') == 'fail'],
                             infeasible=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('baseline_feasible') is False or r.get('instrumented_feasible') is False],
                             reference_mismatch=[f"{r['graph']}/{r['solver']}" for r in rows if 'mismatch' in (r.get('baseline_reference'), r.get('instrumented_reference'))],
                             size_disagreement=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('sizes_agree') is False],
                             sample_check_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('sample_check') == 'fail'],
                             replay_fail=[f"{r['graph']}/{r['solver']}" for r in rows if r.get('replay') == 'fail'],
                             replay_untested_with_A=[f"{r['graph']}/{r['solver']}: {r.get('replay')}" for r in rows if isinstance(r.get('A'), int) and r['A'] > 0 and r.get('replay') != 'pass']))
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
L = ['# Full Stage C report', '', f"300 scheduled pairs: {summary['recorded']} recorded, {summary['runner_error']} runner errors, {summary['missing']} missing. "
     f"Both runs completed: {summary['both_completed']}. Baseline timings and instrumented timings are separate columns and are never combined.", '',
     '| Graph | Solver | Record | Baseline | Base CPU s | Instr. | Instr. CPU s | B | T | A | A strict (Chen) | Saved | Check | Replay |', '|' + '---|' * 14]
f2 = lambda x: f'{x:.2f}' if isinstance(x, float) else str(x)
for r in rows:
    L.append('| ' + ' | '.join(str(x) for x in [r['graph'], r['solver'], r['record_status'], r.get('baseline_status', '-'), f2(r.get('baseline_cpu_s', '-')), r.get('instrumented_status', '-'),
             f2(r.get('instrumented_cpu_s', '-')), r.get('B', '-'), r.get('T', '-'), r.get('A', '-'), r.get('A_chen_strict_merge', '-'), r.get('saved_states', '-'), r.get('sample_check', '-'), r.get('replay', '-')]) + ' |')
L += ['', '## Summary', '', '```json', json.dumps(summary, indent=2), '```']
(out / 'REPORT.md').write_text('\n'.join(L) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in summary.items() if k != 'problems'}, indent=2))
