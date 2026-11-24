"""Stage D invocation records -> typed outcome / provenance columns (no labels, no imputation).

Outcomes are joined AFTER features are computed and never feed back into them. Unknown or
non-numeric source timings become null in typed columns (raw strings stay in invocations.jsonl);
0 is a real measurement. CPU is never reconstructed from wall time. Non-completed arms never
get exact_nodes, even when counts_source is 'final' (a final record can describe a prefix).
"""
import hashlib
import json
import math

COMPLETED = 'completed'
# Stop statuses written by the pinned Stage D build (StageC::guard): the solver's own CPU check
# raises cpu_timeout with exit 74; a STOP file written by the driver raises its reason with exit
# 75 (the driver writes 'cpu_timeout' when it measures the budget exhausted); an empty reason
# reads back as external_stop (75). Disk/deadline stops use 73/75.
STOP_EXIT_CODES = {'cpu_timeout': {74, 75}, 'external_stop': {75}, 'runner_deadline': {75}, 'disk_reserve': {73, 75}}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def number_or_null(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return float(x)


def int_or_null(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def environment_build_group(env, executable_sha256):
    """Canonical-JSON SHA-256 of the explicit (cpu, image, executable_sha256) tuple, or None if
    any key is missing/empty. Used to express the Stage D comparability rule; not a feature."""
    cpu = (env or {}).get('cpu'); image = (env or {}).get('image')
    if not all(isinstance(x, str) and x for x in (cpu, image, executable_sha256)):
        return None
    return sha256_text(canonical({'cpu': cpu, 'executable_sha256': executable_sha256, 'image': image}))


def check_join(record, expected):
    """Join-key and immutable-input agreement between one record and its indexed candidate."""
    e = []
    checks = [
        ('state_id', record.get('state_id'), expected['state_id']),
        ('graph', record.get('graph'), expected['graph_id']),
        ('solver', record.get('solver'), expected['solver']),
        ('phase', record.get('phase'), expected['phase']),
        ('component_subsolver', record.get('component_subsolver'), expected['component_subsolver']),
        ('snapshot_sha256', record.get('snapshot_sha256'), expected['snapshot_sha256']),
        ('candidate_list_sha256', record.get('candidate_list_sha256'), expected['candidate_list_sha256']),
        ('candidate_local_id', record.get('candidate_local_id'), expected['candidate_local_id']),
        ('candidate_id', record.get('candidate_id'), expected['candidate_label']),
        ('original_pivot', record.get('original_pivot'), expected['is_original_pivot']),
        ('state_index', record.get('state_index'), expected['state_index']),
        ('initial_incumbent', record.get('initial_incumbent'), expected['initial_incumbent']),
        ('classical_score', record.get('classical_score'), expected['classical_score']),
        ('classical_rank', record.get('classical_rank'), expected['classical_rank']),
    ]
    for name, got, want in checks:
        if got != want:
            e.append(f'join mismatch {name}: record={got!r} index={want!r}')
    return e


def parse_outcome(record, expected, pinned):
    """Flatten one UNIQUE record. Returns (fields, join_errors, measurement_errors)."""
    join_errors = check_join(record, expected)
    me = []
    m = record.get('measurement')
    raw_status = record.get('status')
    exit_code = record.get('exit_code') if isinstance(record.get('exit_code'), int) and not isinstance(record.get('exit_code'), bool) else None
    forced = record.get('forced_termination') if isinstance(record.get('forced_termination'), bool) else None
    env = record.get('environment') or {}
    if record.get('experiment_commit') != pinned['stage_d_experiment_commit']:
        join_errors.append(f'experiment_commit {record.get("experiment_commit")!r} is not the pinned Stage D commit')
    if record.get('cpu_budget_s') != pinned['cpu_budget_s']:
        join_errors.append(f'cpu_budget_s {record.get("cpu_budget_s")!r} != {pinned["cpu_budget_s"]}')
    f = dict(
        raw_status=raw_status, counts_source=record.get('counts_source'), exit_code=exit_code, forced_termination=forced,
        original_reproduction=record.get('original_reproduction'),
        environment_cpu=env.get('cpu'), environment_image=env.get('image'), environment_os=env.get('os'), environment_runner=env.get('runner'),
        cpu_budget_s=number_or_null(record.get('cpu_budget_s')),
        experiment_commit=record.get('experiment_commit'), executable_sha256=record.get('executable_sha256'),
        source_hashes_sha256=sha256_text(canonical(record['source_hashes'])) if isinstance(record.get('source_hashes'), dict) else None,
        environment_build_group=environment_build_group(env, record.get('executable_sha256')),
        process_cpu_s=number_or_null(record.get('cpu_s')), process_wall_s=number_or_null(record.get('wall_s')),
        driver_wall_s=number_or_null(record.get('driver_wall_s')),
        finalization_cpu_s=number_or_null(record.get('finalization_cpu_s')),
        peak_memory_bytes=int_or_null(record.get('peak_memory_bytes')),
        measurement_status=None, observed_nodes=None, exact_nodes=None, observed_branching_decisions=None,
        nodes_reconcile=None, branches_reconcile=None, final_size_cap=None, final_solFound=None,
        setup_cpu_s=None, continuation_cpu_s=None, continuation_wall_s=None, parent_overhead_cpu_s=None, parent_overhead_wall_s=None,
        node_observation_kind='missing', original_reproduction_recheck=None,
    )
    notes = []
    for k in ('cpu_s', 'wall_s', 'driver_wall_s', 'finalization_cpu_s'):
        if k in record and number_or_null(record[k]) is None:
            notes.append(f'{k} is not a finite number ({record[k]!r}); typed column set to null, raw value kept in invocations.jsonl')
    f['_notes'] = notes
    if not isinstance(m, dict):
        if raw_status == COMPLETED:
            me.append('completed record has no measurement')
        f['node_observation_kind'] = 'missing'
        return f, join_errors, me
    f.update(measurement_status=m.get('status'), nodes_reconcile=m.get('nodes_reconcile') if isinstance(m.get('nodes_reconcile'), bool) else None,
             branches_reconcile=m.get('branches_reconcile') if isinstance(m.get('branches_reconcile'), bool) else None,
             observed_nodes=int_or_null(m.get('total_nodes')), observed_branching_decisions=int_or_null(m.get('branching_decisions')),
             setup_cpu_s=number_or_null(m.get('setup_cpu_s')), continuation_cpu_s=number_or_null(m.get('continuation_cpu_s')),
             continuation_wall_s=number_or_null(m.get('continuation_wall_s')), parent_overhead_cpu_s=number_or_null(m.get('parent_overhead_cpu_s')),
             parent_overhead_wall_s=number_or_null(m.get('parent_overhead_wall_s')))
    fin = m.get('final_incumbent') or {}
    f['final_size_cap'] = fin.get('size_cap') if isinstance(fin.get('size_cap'), int) and not isinstance(fin.get('size_cap'), bool) else None
    f['final_solFound'] = fin.get('solFound') if isinstance(fin.get('solFound'), bool) else None
    # ---- measurement integrity ----
    if f['observed_nodes'] is None:
        me.append(f'total_nodes invalid: {m.get("total_nodes")!r}')
    if f['observed_branching_decisions'] is None:
        me.append(f'branching_decisions invalid: {m.get("branching_decisions")!r}')
    if m.get('status') != raw_status:
        me.append(f'status disagreement: record={raw_status!r} measurement={m.get("status")!r}')
    if m.get('candidate_local_id') != expected['candidate_local_id']:
        me.append('measurement.candidate_local_id differs from the indexed candidate')
    if m.get('original_local_id') != expected['original_local_id']:
        me.append('measurement.original_local_id differs from the indexed original pivot')
    if m.get('initial_incumbent') != expected['initial_incumbent']:
        me.append('measurement.initial_incumbent differs from the indexed initial incumbent')
    children = m.get('children') if isinstance(m.get('children'), list) else []
    if len(children) != 2:
        me.append(f'expected 2 children, found {len(children)}')
    else:
        if f['observed_nodes'] is not None and sum(c.get('nodes', -1) for c in children) != f['observed_nodes']:
            me.append('total_nodes != child nodes sum')
        if f['observed_branching_decisions'] is not None and sum(c.get('branching_decisions', -1) for c in children) + m.get('root_decisions', -1) != f['observed_branching_decisions']:
            me.append('branching_decisions != child decisions + root decision')
    if f['nodes_reconcile'] is not True:
        me.append(f'nodes_reconcile is {m.get("nodes_reconcile")!r}')
    if f['branches_reconcile'] is not True:
        me.append(f'branches_reconcile is {m.get("branches_reconcile")!r}')
    if f['final_size_cap'] is not None and f['final_size_cap'] > expected['initial_incumbent']['size_cap']:
        me.append('final size_cap exceeds the initial size_cap')
    cs = [c.get('status') for c in children]
    if raw_status == COMPLETED:
        if exit_code != 0:
            me.append(f'completed record has exit_code {exit_code!r}')
        if cs != [COMPLETED, COMPLETED]:
            me.append(f'completed record has child statuses {cs}')
        if record.get('counts_source') != 'final':
            me.append(f'completed record has counts_source {record.get("counts_source")!r}')
        if forced is True:
            me.append('completed record was force-terminated')
    else:
        allowed = STOP_EXIT_CODES.get(raw_status)
        if allowed is None:
            me.append(f'unrecognised non-completed status {raw_status!r}')
        elif exit_code not in allowed:
            me.append(f'status {raw_status!r} with exit_code {exit_code!r} (expected one of {sorted(allowed)})')
        if cs == [COMPLETED, COMPLETED]:
            me.append('non-completed record reports both children completed')
    # ---- original-pivot reproduction recheck from archived digests (no solver execution) ----
    ref = expected.get('stage_c_continuation')
    rec_rep = record.get('original_reproduction')
    if expected['is_original_pivot']:
        if raw_status == COMPLETED and ref and ref.get('complete'):
            got = record.get('continuation') or {}
            ok = all(got.get(k) == ref.get(k) for k in ('trace_count', 'trace_digest', 'final_state_hash'))
            f['original_reproduction_recheck'] = 'pass' if ok else 'FAIL'
            if rec_rep != f['original_reproduction_recheck']:
                me.append(f'original_reproduction recorded {rec_rep!r} but archived-digest recheck gives {f["original_reproduction_recheck"]!r}')
        else:
            f['original_reproduction_recheck'] = 'untested'
            if rec_rep not in ('untested_censored_or_no_complete_stage_c_reference',):
                me.append(f'original arm without a testable reference has original_reproduction {rec_rep!r}')
    else:
        f['original_reproduction_recheck'] = 'not_original'
        if rec_rep != 'not_original':
            me.append(f'non-original arm has original_reproduction {rec_rep!r}')
    if rec_rep == 'FAIL' or f['original_reproduction_recheck'] == 'FAIL':
        me.append('original reproduction FAIL')
    # ---- observation kind ----
    if me:
        f['node_observation_kind'] = 'invalid'
    elif raw_status == COMPLETED:
        f['node_observation_kind'] = 'exact'; f['exact_nodes'] = f['observed_nodes']
    else:
        f['node_observation_kind'] = 'prefix'
    return f, join_errors, me
