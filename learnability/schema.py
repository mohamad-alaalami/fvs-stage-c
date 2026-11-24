"""Candidate-table schema v1: ordered columns, logical types, roles, allowlists, typed I/O.

CSV conventions: UTF-8, LF line endings, csv.QUOTE_MINIMAL; null = empty cell; booleans
'true'/'false'; int64 decimal; float64 shortest round-trip repr (never NaN/Infinity);
'json' cells hold canonical JSON (sorted keys, no spaces). IDs and labels stay strings.
Never rely on pandas/spreadsheet type inference: use load_table().
"""
import csv
import json
import math

from . import FEATURE_SCHEMA_VERSION
from .features import FEATURE_COLUMNS

# (name, logical type, role, nullable, description)
_C = []
def col(name, typ, role, nullable, desc):
    _C.append(dict(name=name, type=typ, role=role, nullable=nullable, description=desc))

# keys and decision context
col('solver', 'string', 'key', False, "Native solver: '8' (Cao/Sol8), '5' (Chen-style/Sol5), 'LP' (Imanishi-Iwata-style/HalfIntBranching).")
col('graph_id', 'string', 'group', False, "PACE 2016 public graph ID, e.g. '001'. Future grouping key: keep all rows of a graph together, across solvers.")
col('state_id', 'string', 'key', False, 'Stage C event ID of the saved state (<instrumented run id>:<sequence>).')
col('state_index', 'int64', 'metadata', False, 'Ordinal of the state in the pinned Stage D index (0-based).')
col('candidate_local_id', 'int64', 'key', False, 'Local vertex ID of the eligible candidate in the snapshot.')
col('candidate_label', 'string', 'metadata', False, 'stageNames label (original input vertex label) of the candidate.')
col('candidate_ordinal', 'int64', 'metadata', False, 'Position of the candidate in the validated eligible list (0-based). Not a model input.')
col('original_local_id', 'int64', 'metadata', False, 'Local ID of the pivot chosen by the original policy at this state.')
col('is_original_pivot', 'bool', 'metadata', False, 'Candidate equals the original pivot. Not a model input.')
col('root_local_id', 'int64', 'metadata', True, 'LP only: saved solve2 root (active SAFE vertex); null for 8 and 5.')
col('phase', 'string', 'metadata', False, 'Stage C decision phase (cao_max_degree, chen_fallback, lp_neighbor).')
col('component_subsolver', 'bool', 'metadata', False, 'Decision occurred inside a connected-component subsolver (isSub).')
col('depth', 'int64', 'metadata', False, 'Stage C recursive search-frame depth (root call = 0). Metadata only.')
col('solver_depth', 'int64', 'metadata', False, 'Upstream BranchingSolution::depth at the decision. Metadata only.')
# sampling / provenance
col('sample_kind', 'string', 'metadata', False, "Stage C sample kind: 'first_A' or 'reservoir'.")
col('sample_slot', 'int64', 'metadata', False, 'Reservoir slot (-1 for first_A).')
col('sample_sequence', 'int64', 'metadata', False, 'Decision sequence number within the Stage C instrumented run.')
col('sample_a_index', 'int64', 'metadata', False, 'Index of this A event among the run\'s A events (1 = first).')
col('snapshot_bytes', 'int64', 'metadata', False, 'Length of the STAGEC1 snapshot in bytes.')
col('state_metadata_ref', 'string', 'provenance', False, "Reference to the parent state's record: 'states.jsonl#<state_id>'.")
col('stage_c_run_id', 'string', 'provenance', False, 'Stage C workflow run of record.')
col('stage_d_run_id', 'string', 'provenance', False, 'Stage D workflow run of record.')
col('snapshot_sha256', 'string', 'provenance', False, 'SHA-256 of the snapshot bytes (verified against the index).')
col('candidate_list_sha256', 'string', 'provenance', False, 'SHA-256 of the little-endian int32 candidate list bytes (verified).')
col('packed_sha256', 'string', 'provenance', False, 'SHA-256 of the samples.bin.zz stream containing the state (verified).')
col('snapshot_source_path', 'string', 'provenance', False, 'samples.json path (relative to the Stage C records commit) the state was sliced from.')
col('sample_offset', 'int64', 'provenance', False, 'Byte offset of the snapshot in the decompressed samples.bin stream.')
col('candidates_offset', 'int64', 'provenance', False, 'Byte offset of the candidate list in the decompressed stream.')
# features (filled from features.FEATURE_DEFINITIONS)
FEATURE_DEFINITIONS = {
    'f_cand_none_neighbors': ('int64', False, '|D(v)|: distinct active neighbours of v with status 0.'),
    'f_cand_safe_neighbors': ('int64', False, '|U(v)|: distinct active neighbours of v with status 1.'),
    'f_cand_double_edges': ('int64', False, 'Number of distinct active neighbours u of v whose edge {v,u} is flagged double.'),
    'f_nbr_none_wdeg_min': ('float64', False, 'min over u in D(v) of w(u) = |N(u)| + double edges of u; 0.0 if D(v) is empty.'),
    'f_nbr_none_wdeg_mean': ('float64', False, 'sum over u in D(v) of w(u) (integer) / |D(v)| (float64); 0.0 if D(v) is empty.'),
    'f_nbr_none_wdeg_max': ('float64', False, 'max over u in D(v) of w(u); 0.0 if D(v) is empty.'),
    'f_state_none_vertices': ('int64', False, 'Active vertices with status 0 (isolated ones included).'),
    'f_state_safe_vertices': ('int64', False, 'Active vertices with status 1 (isolated ones included).'),
    'f_state_distinct_edges': ('int64', False, 'Unordered active pairs {u,w} that are adjacent, each counted once regardless of multiplicity.'),
    'f_state_double_edges': ('int64', False, 'Unordered active adjacent pairs whose edge is flagged double.'),
    'f_state_remaining_threshold': ('int64', False, 'snapshot.size_cap - len(snapshot.X); size_cap is the strict improvement cutoff, so an improving solution may delete threshold-1 more vertices. Not clamped.'),
    'f_state_candidate_count': ('int64', False, 'Length of the validated eligible-candidate list.'),
    'f_lp_root_common_neighbors': ('int64', True, 'LP only: |N(v) intersect N(r)| over distinct active vertices (r = saved root); null for 8 and 5.'),
}
for name in FEATURE_COLUMNS:
    t, nullable, d = FEATURE_DEFINITIONS[name]
    col(name, t, 'feature', nullable, d)
# diagnostics (not model inputs)
col('diag_allocated_N', 'int64', 'diagnostic', False, 'Allocated vertex slots N in the snapshot (NOT the active size).')
col('diag_stored_M', 'int64', 'diagnostic', False, 'Stored M field (NOT a trustworthy residual edge count).')
col('diag_current_X_size', 'int64', 'diagnostic', False, 'len(snapshot.X) at the decision.')
col('diag_initial_size_cap', 'int64', 'diagnostic', False, 'Snapshot size_cap (strict improvement cutoff) at the decision.')
col('diag_initial_solFound', 'bool', 'diagnostic', False, 'Snapshot solFound at the decision.')
col('diag_cand_distinct_degree', 'int64', 'diagnostic', False, 'f_cand_none_neighbors + f_cand_safe_neighbors.')
col('diag_cand_weighted_degree', 'int64', 'diagnostic', False, 'diag_cand_distinct_degree + f_cand_double_edges (equals the upstream degWithDouble).')
col('classical_score_json', 'json', 'diagnostic', False, "Original selector score: Cao/LP weighted degree; Chen [edges into U, weighted degree]. Metadata only.")
col('classical_rank', 'int64', 'diagnostic', False, '1 + number of candidates with a strictly greater classical score. Metadata only.')
# invocation provenance
col('invocation_count', 'int64', 'provenance', False, 'Number of Stage D records found for this candidate key in the pinned run.')
col('invocation_resolution', 'string', 'provenance', False, "'unique', 'missing' or 'multiple'. With 'multiple' no attempt is chosen and scalar outcome fields are null.")
col('invocation_refs_json', 'json', 'provenance', False, 'All records for this key: [{run_id, chunk_id, attempt_id, source_record_path, source_record_line}].')
for name, typ, d in [('invocation_run_id', 'string', 'Stage D arm UUID.'), ('chunk_id', 'string', 'Stage D chunk directory name.'),
                     ('attempt_id', 'string', 'Chunk attempt directory name.'), ('source_record_path', 'string', 'records.jsonl path relative to the Stage D results commit.'),
                     ('source_record_line', 'int64', '1-based line of the record in records.jsonl.'), ('source_record_sha256', 'string', 'SHA-256 of that records.jsonl file.'),
                     ('experiment_commit', 'string', 'Stage D experiment commit recorded by the arm.'), ('executable_sha256', 'string', 'SHA-256 of the Stage D executable.'),
                     ('source_hashes_sha256', 'string', 'Canonical-JSON SHA-256 of the arm\'s source_hashes map (full map in invocations.jsonl).'),
                     ('environment_build_group', 'string', 'Canonical-JSON SHA-256 of {cpu, image, executable_sha256}; null if any part is missing. Comparability key, not a feature.')]:
    col(name, typ, 'provenance', True, d + ' Null unless invocation_resolution is unique.')
# outcomes (never model inputs)
for name, typ, d in [
    ('raw_status', 'string', 'Record status as written (completed, cpu_timeout, external_stop, ...).'),
    ('counts_source', 'string', "Record counts_source ('final' can still describe a censored prefix)."),
    ('exit_code', 'int64', 'Process exit code.'),
    ('forced_termination', 'bool', 'True if the driver force-killed the arm; null when the record does not specify it.'),
    ('original_reproduction', 'string', 'Recorded original-pivot reproduction verdict.'),
    ('original_reproduction_recheck', 'string', "Recheck from archived Stage C digests: pass / FAIL / untested / not_original (no solver run)."),
    ('environment_cpu', 'string', 'Runner CPU model string.'), ('environment_image', 'string', 'Runner image string.'),
    ('environment_os', 'string', 'Runner OS string (provenance).'), ('environment_runner', 'string', 'Runner name (provenance; not a compatibility key).'),
    ('cpu_budget_s', 'float64', 'Process-CPU budget of the arm (seconds).'),
    ('observed_nodes', 'int64', 'measurement.total_nodes (recursive search-node entries in both children), when a valid integer >= 0.'),
    ('exact_nodes', 'int64', 'observed_nodes only for a unique, valid, completed, reconciled, non-forced, join-valid arm; null otherwise (including every censored arm).'),
    ('observed_branching_decisions', 'int64', 'measurement.branching_decisions (parent decision + child decisions).'),
    ('node_observation_kind', 'string', "exact | prefix | missing | invalid | unresolved_multiple."),
    ('measurement_status', 'string', 'measurement.status.'),
    ('nodes_reconcile', 'bool', 'Recorded nodes_reconcile flag.'), ('branches_reconcile', 'bool', 'Recorded branches_reconcile flag.'),
    ('final_size_cap', 'int64', 'Final incumbent size_cap after the continuation (not a proven graph optimum).'),
    ('final_solFound', 'bool', 'Final incumbent solFound.'),
    ('process_cpu_s', 'float64', 'record.cpu_s: whole-process CPU seconds (GetProcessTimes). 0.0 is a timer reading, not proof of zero work.'),
    ('process_wall_s', 'float64', 'record.wall_s: process lifetime seconds.'),
    ('driver_wall_s', 'float64', 'record.driver_wall_s: driver-measured wall seconds.'),
    ('setup_cpu_s', 'float64', 'measurement.setup_cpu_s.'), ('continuation_cpu_s', 'float64', 'measurement.continuation_cpu_s.'),
    ('continuation_wall_s', 'float64', 'measurement.continuation_wall_s.'), ('parent_overhead_cpu_s', 'float64', 'measurement.parent_overhead_cpu_s.'),
    ('parent_overhead_wall_s', 'float64', 'measurement.parent_overhead_wall_s.'),
    ('finalization_cpu_s', 'float64', 'record.finalization_cpu_s as recorded.'), ('peak_memory_bytes', 'int64', 'record.peak_memory_bytes.'),
]:
    col(name, typ, 'outcome', True, d + ' Null unless invocation_resolution is unique and the value is present and valid.')
# validation
col('join_valid', 'bool', 'validation', True, 'Unique record agrees with the index on every join key and immutable input; null when no unique record.')
col('state_integrity_ok', 'bool', 'validation', False, 'Parent state passed every hash, decode, eligibility and active-adjacency check.')
col('measurement_integrity_ok', 'bool', 'validation', True, 'Unique record passed all measurement consistency checks; null when no unique record.')
col('state_completed_cap_consistent', 'bool', 'validation', True, 'All unique completed arms of the state report the same final size_cap; null when the state has no unique completed arm.')
col('validation_errors_json', 'json', 'validation', False, 'List of row-level validation error strings (state, join and measurement); [] when none.')

COLUMNS = tuple(_C)
COLUMN_NAMES = tuple(c['name'] for c in COLUMNS)
TYPES = {c['name']: c['type'] for c in COLUMNS}
ROLES = {c['name']: c['role'] for c in COLUMNS}

ALLOWLISTS = {
    '8': list(FEATURE_COLUMNS[:12]),
    '5': list(FEATURE_COLUMNS[:12]),
    'LP': ['f_cand_none_neighbors', 'f_cand_double_edges', 'f_nbr_none_wdeg_min', 'f_nbr_none_wdeg_mean', 'f_nbr_none_wdeg_max',
           'f_state_none_vertices', 'f_state_distinct_edges', 'f_state_double_edges', 'f_state_remaining_threshold',
           'f_state_candidate_count', 'f_lp_root_common_neighbors'],
}
assert all(ROLES[c] == 'feature' for v in ALLOWLISTS.values() for c in v)
assert len(ALLOWLISTS['8']) == 12 and len(ALLOWLISTS['LP']) == 11


def schema_document():
    return dict(schema='fvs-learnability-candidates', feature_schema_version=FEATURE_SCHEMA_VERSION,
                csv=dict(encoding='utf-8', line_terminator='\\n', quoting='csv.QUOTE_MINIMAL', null='empty cell',
                         booleans=['true', 'false'], float64='shortest round-trip decimal (Python repr); NaN/Infinity forbidden',
                         json='canonical JSON (sorted keys, separators , and :)', row_order='state_index, then candidate_ordinal',
                         unique_key=['solver', 'state_id', 'candidate_local_id']),
                columns=list(COLUMNS), model_input_allowlists=ALLOWLISTS,
                allowlist_note='Initial v1 input allowlists. LP excludes f_cand_safe_neighbors and f_state_safe_vertices (stored for audit: every saved LP state has exactly one SAFE vertex, the root, and every candidate neighbours it). Choosing training feature blocks is a separate, later decision.')


def format_cell(value, typ):
    if value is None:
        return ''
    if typ == 'bool':
        if not isinstance(value, bool):
            raise TypeError(f'expected bool, got {value!r}')
        return 'true' if value else 'false'
    if typ == 'int64':
        if isinstance(value, bool) or not isinstance(value, int) or not -2**63 <= value < 2**63:
            raise TypeError(f'expected int64, got {value!r}')
        return str(value)
    if typ == 'float64':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f'expected float64, got {value!r}')
        value = float(value)
        if not math.isfinite(value):
            raise ValueError('non-finite float')
        return repr(value)
    if typ == 'json':
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if not isinstance(value, str) or value == '':
        raise TypeError(f'expected non-empty string, got {value!r}')
    return value


def parse_cell(text, typ):
    if text == '':
        return None
    if typ == 'bool':
        if text not in ('true', 'false'):
            raise ValueError(f'bad bool {text!r}')
        return text == 'true'
    if typ == 'int64':
        return int(text)
    if typ == 'float64':
        x = float(text)
        if not math.isfinite(x):
            raise ValueError('non-finite float')
        return x
    if typ == 'json':
        return json.loads(text)
    return text


class TableWriter:
    def __init__(self, fh):
        self.w = csv.writer(fh, lineterminator='\n', quoting=csv.QUOTE_MINIMAL)
        self.w.writerow(COLUMN_NAMES)

    def write(self, row):
        missing = set(COLUMN_NAMES) - set(row); extra = set(row) - set(COLUMN_NAMES)
        if missing or extra:
            raise KeyError(f'row columns mismatch: missing={sorted(missing)} extra={sorted(extra)}')
        out = []
        for c in COLUMNS:
            v = row[c['name']]
            if v is None and not c['nullable']:
                raise ValueError(f'null in non-nullable column {c["name"]}')
            out.append(format_cell(v, c['type']))
        self.w.writerow(out)


def load_table(path, schema_path=None):
    """Typed loader: returns a list of dicts with str/int/float/bool/None/JSON values.

    Uses schema.json types when given (else this module's schema) and checks the header order."""
    if schema_path is not None:
        with open(schema_path, encoding='utf-8') as f:
            cols = json.load(f)['columns']
    else:
        cols = list(COLUMNS)
    names = [c['name'] for c in cols]; types = [c['type'] for c in cols]
    rows = []
    with open(path, encoding='utf-8', newline='') as f:
        r = csv.reader(f)
        header = next(r)
        if header != names:
            raise ValueError('CSV header does not match the schema column order')
        for rec in r:
            if len(rec) != len(names):
                raise ValueError('row width mismatch')
            rows.append({n: parse_cell(x, t) for n, x, t in zip(names, rec, types)})
    return rows


def model_inputs(row, solver):
    """The v1 model-input vector of one typed row, by the explicit allowlist (never by prefix)."""
    return [row[c] for c in ALLOWLISTS[solver]]
