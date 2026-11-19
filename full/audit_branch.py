"""Operator audit of committed full-run records (read-only).
Usage: python audit_branch.py <full-results clone dir> <run_id>
Prints one line of totals and one line per problem pair."""
import json, pathlib, sys, collections
root = pathlib.Path(sys.argv[1]) / 'runs' / sys.argv[2]
sched = json.loads((root / 'schedule.json').read_text())
expected = [(p['graph'], p['solver']) for p in sched['part1'] + sched['part2']]
assert len(expected) == 300 == len(set(expected))
stat = collections.Counter(); problems = []; totals = collections.Counter()
for g, s in expected:
    att = sorted((root / 'pairs' / f'{g}-{s}').glob('attempt-*/pair.json'), key=lambda p: int(p.parent.name.split('-')[1]))
    if not att:
        stat['not_yet'] += 1; continue
    p = json.loads(att[-1].read_text()); stat['attempts>1'] += len(att) > 1
    if p['status'] != 'recorded':
        problems.append(f'{g}/{s}: status={p["status"]} {p.get("error", "")[-300:]!r}'); stat[p['status']] += 1; continue
    b, i, c = p['baseline'], p['instrumented'], p['counts']
    stat['recorded'] += 1; stat['base:' + b['status']] += 1; stat['inst:' + i['status']] += 1
    why = []
    if not c: why.append('no counts')
    else:
        totals['B'] += c['B']; totals['T'] += c['T']; totals['A'] += c['A']; totals['strict'] += c['A_chen_strict_merge']
        if not p['consistency_pass']: why.append('consistency ' + str([k for k, v in p['consistency'].items() if not v]))
        if c['nodes']['outcome_anomalies']: why.append('node anomalies')
        if any(k.startswith('anomaly:') for k in c['counters']): why.append('pivot anomaly ' + str({k: v for k, v in c['counters'].items() if k.startswith('anomaly:')}))
    for side, r in (('baseline', b), ('instrumented', i)):
        v = r['verification']
        if r['status'] == 'completed' and v['feasible'] is not True: why.append(f'{side} infeasible')
        if v.get('reference_verdict') == 'mismatch': why.append(f'{side} reference mismatch {v["returned_size"]} vs {v["reference_size"]}')
        if r['status'] not in ('completed', 'cpu_timeout'): why.append(f'{side} status {r["status"]} exit {r["exit_code"]}')
    a = p['solution_agreement']
    if isinstance(a, dict) and not (a['sizes_equal'] and a['both_feasible']): why.append(f'baseline/instrumented disagree {a}')
    if p['sample_check']['status'] not in ('pass', 'not_applicable_no_saved_state'): why.append('sample_check ' + p['sample_check']['status'])
    if p['replay']['status'] == 'fail': why.append('replay fail')
    if c and c['A'] > 0 and p['replay']['status'] != 'pass': stat['replay_untested_with_A'] += 1
    if p['sample_metadata'].get('first_A_unsaved_bytes'): stat['first_A_too_big'] += 1
    totals['stored_bytes'] += p['sample_storage']['stored_bytes']
    if why: problems.append(f'{g}/{s}: ' + '; '.join(why))
print('TOTALS', dict(stat), dict(totals))
for x in problems: print('PROBLEM', x)
