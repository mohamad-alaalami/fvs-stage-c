"""REPORT.md for one extraction (descriptive audit only; no fitted preprocessing, no predictive claims)."""
import json

AUDIT_ANCHORS = {  # exploratory anchors supplied with the task; recomputed, never forced
    'states_weighted_degree_varies': {'8': 0, '5': 1529, 'LP': 1223},
    'states_nbr_wdeg_mean_varies': {'8': 1273, '5': 1526, 'LP': 1459},
    'states_common_neighbors_varies': {'LP': 1411},
}


def write_report(out, v, timing, cpu, mem):
    c = v['counts']; a = v['audit']; L = []
    L += [f"# Learnability extraction {v['extraction_id']}", '', f"Dataset status: **{v['dataset_status']}** ({v['problem_count']} problems).", '',
          '## Counts', '', '| Solver | States | Candidate rows | Graphs |', '|---|---:|---:|---:|']
    for s in ('8', '5', 'LP'):
        L.append(f"| {s} | {c['states'].get(s, 0)} | {c['candidates'].get(s, 0)} | {c['graphs_represented'].get(s, 0)} |")
    L += ['', f"Graphs represented (any solver): {c['graphs_represented_any']}. Stage D invocations discovered: {c['invocations']} "
          f"(unexpected: {c['unexpected_records']}, duplicated UUIDs: {c['duplicate_uuids']}).", '', '## Acceptance checks', '']
    L += [f"- {k}: {'pass' if ok else 'FAIL'}" for k, ok in v['acceptance'].items()]
    L += ['', '## Outcome observation kinds and record statuses (by solver)', '', '| Solver | exact | prefix | missing | invalid | unresolved_multiple | completed | cpu_timeout | external_stop |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in ('8', '5', 'LP'):
        x = a.get(s, {})
        L.append('| ' + ' | '.join([s] + [str(x.get('kind:' + k, 0)) for k in ('exact', 'prefix', 'missing', 'invalid', 'unresolved_multiple')]
                                    + [str(x.get('status:' + k, 0)) for k in ('completed', 'cpu_timeout', 'external_stop')]) + ' |')
    L += ['', f"All record statuses: {json.dumps(v['record_status_counts'], sort_keys=True)}. 'prefix' rows are CPU- or driver-stopped arms: "
          "their node counts are observed prefixes, never exact totals.", '', '## Audit anchors (recomputed; exploratory, not model claims)', '',
          '| Quantity | Solver | Recomputed | Supplied anchor |', '|---|---|---:|---:|']
    for q, per in AUDIT_ANCHORS.items():
        for s, anchor in per.items():
            got = a.get(s, {}).get(q, 0)
            L.append(f'| {q} | {s} | {got} | {anchor}{"" if got == anchor else " (differs)"} |')
    L += ['', '## Dataset observations', '',
          f"- LP states with exactly one SAFE vertex: {a.get('LP', {}).get('states_with_exactly_one_safe_vertex', 0)} of {c['states'].get('LP', 0)}; "
          f"LP candidates with exactly one SAFE neighbour: {a.get('LP', {}).get('candidates_with_exactly_one_safe_neighbour', 0)} of {c['candidates'].get('LP', 0)}.",
          f"- Cao states whose candidates all share one weighted degree: {a.get('8', {}).get('states_with_tied_weighted_degree', 0)} of {c['states'].get('8', 0)}.",
          f"- Candidates with distinct degree <= 2 (kept, not repaired): " + ', '.join(f"{s}: {a.get(s, {}).get('candidates_distinct_degree_le_2', 0)}" for s in ('8', '5', 'LP')) + '.',
          f"- Candidates with an empty undecided neighbourhood (summaries 0.0, f_cand_none_neighbors = 0): " + ', '.join(f"{s}: {a.get(s, {}).get('candidates_empty_undecided_neighbourhood', 0)}" for s in ('8', '5', 'LP')) + '.',
          f"- Chen states passing the strict qualifying-state test (metadata only; no Chen row is excluded): {a.get('5', {}).get('states_strict_qualifying', 0)}.",
          '', '## Feature variation across rows (descriptive)', '', '| Feature | 8 | 5 | LP |', '|---|---|---|---|']
    fv = v['feature_variation']
    for f in (fv.get('8') or {}):
        L.append(f"| {f} | {fv.get('8', {}).get(f, '-')} | {fv.get('5', {}).get(f, '-')} | {fv.get('LP', {}).get(f, '-')} |")
    L += ['', '## Sampling and censoring patterns (states)', '']
    for s in ('8', '5', 'LP'):
        x = a.get(s, {})
        kinds = {k.split(':', 1)[1]: n for k, n in x.items() if k.startswith('states_sample_kind:')}
        pats = {k.split(':', 1)[1]: n for k, n in x.items() if k.startswith('states_arm_status_pattern:')}
        L.append(f"- {s}: sample kinds {json.dumps(kinds, sort_keys=True)}; per-state arm status sets {json.dumps(pats, sort_keys=True)}")
    rc = v.get('stage_d_report_check', {})
    L += ['', f"Stage D report cross-check: recorded invocations in REPORT.md {rc.get('report_recorded_invocations')} vs discovered {rc.get('discovered_invocations')}; "
          f"states {rc.get('report_states')}; retries listed {rc.get('report_retries')}; per-state recorded_arms mismatches {len(rc.get('states_recorded_arms_mismatch', []))}; agrees: {rc.get('agrees')}.",
          'Only counts are compared; Stage D comparison verdicts are not used.']
    L += ['', '## Anomalies', '']
    L += [f"- {k}: {x['count']}" for k, x in v['anomalies'].items()] or ['- none']
    L += ['', f"Input verification against pinned git trees: {json.dumps({k: x for k, x in v['input_verification'].items() if k != 'failures'})}; "
          f"chunk summaries/schedules agree: {v['chunk_checks']['all_agree']} ({v['chunk_checks']['chunks']} chunks). "
          f"Independent reference implementation: {v['reference_check']['states_checked']} states checked, {v['reference_check']['states_mismatched']} mismatched.",
          '', '## Timing and hardware', '',
          f"Extraction wall {timing['wall_s']:.1f} s, process CPU {timing['cpu_s']:.1f} s on {cpu}; peak memory {mem.get('bytes')} bytes ({mem.get('method')}). "
          'Extraction timing is not a solver-overhead measurement and implies nothing about live inference cost.',
          '', '## Limitations', '',
          '- Rows describe the 6,502 Stage C saved states (first A state, then a seeded reservoir of 32; 64 KiB slot cap, 25,841 selected states excluded for size), not every branching decision.',
          '- Stage D arms are first-pivot continuations under the original policy with a 10 s process-CPU cap; censored arms carry prefixes only. Labels from these continuations describe one changed decision, not repeated learned decisions.',
          '- Arms ran on several CPU models; comparisons require equal environment_build_group (CPU, image, executable) plus equal state, snapshot, candidate list, initial incumbent, experiment and budget.',
          '- States from one graph are correlated; keep every row of a graph (across solvers) in the same future split. The 130 hidden graphs were not accessed.',
          '- Features are our mechanism-motivated FVS design, not a published validated feature set; no predictive value or ML gain is shown here. Live parity and overhead are not established.']
    (out / 'REPORT.md').write_text('\n'.join(L) + '\n', encoding='utf-8', newline='\n')
