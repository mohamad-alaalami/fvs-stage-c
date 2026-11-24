"""Load and verify the extraction's candidate tables; build per-state candidate structures.

Tables are read with the extraction schema's logical types (never inferred). Before use, the
decompressed bytes of every consumed file are checked against the extraction manifest's SHA-256.
"""
import csv
import gzip
import hashlib
import io
import json
import pathlib

from learnability.schema import parse_cell

SOLVERS = ('8', '5', 'LP')


class DataError(RuntimeError):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def read_member(data_dir, name):
    """Bytes of an extraction output, from name or name.gz (gzip is transport only)."""
    p = pathlib.Path(data_dir) / name
    if p.exists():
        return p.read_bytes()
    g = p.with_name(name + '.gz')
    if g.exists():
        return gzip.decompress(g.read_bytes())
    raise DataError(f'missing extraction file {name}')


def verify_extraction(data_dir, expected_extraction_id):
    """Check COMPLETE marker, manifest identity and the SHA-256 of every consumed file."""
    manifest_bytes = read_member(data_dir, 'manifest.json'); manifest = json.loads(manifest_bytes)
    complete = read_member(data_dir, 'COMPLETE').decode().strip()
    if complete != sha256_bytes(manifest_bytes):
        raise DataError('COMPLETE marker does not match manifest.json')
    if manifest['extraction_id'] != expected_extraction_id or manifest['dataset_status'] != 'complete_validated':
        raise DataError(f'unexpected extraction {manifest["extraction_id"]} / {manifest["dataset_status"]}')
    checked = {}
    for name in ('candidates_8.csv', 'candidates_5.csv', 'candidates_LP.csv', 'schema.json', 'states.jsonl', 'validation.json', 'REPORT.md'):
        b = read_member(data_dir, name); h = sha256_bytes(b)
        if h != manifest['outputs'][name]['sha256']:
            raise DataError(f'{name} SHA-256 {h} differs from the extraction manifest')
        checked[name] = h
    return manifest, checked


def load_schema(data_dir):
    return json.loads(read_member(data_dir, 'schema.json'))


def load_rows(data_dir, solver, schema):
    """Typed rows of candidates_<solver>.csv using schema.json column types."""
    cols = schema['columns']; names = [c['name'] for c in cols]; types = [c['type'] for c in cols]
    text = read_member(data_dir, f'candidates_{solver}.csv').decode('utf-8')
    r = csv.reader(io.StringIO(text, newline=''))
    if next(r) != names:
        raise DataError('header does not match schema column order')
    rows = []
    for rec in r:
        if len(rec) != len(names):
            raise DataError('row width mismatch')
        rows.append({n: parse_cell(x, t) for n, x, t in zip(names, rec, types)})
    return rows


def candidate_valid(r):
    """Unique, integrity-valid, completed invocation with an exact node total."""
    return (r['invocation_resolution'] == 'unique' and r['join_valid'] is True and r['measurement_integrity_ok'] is True
            and r['state_integrity_ok'] is True and r['raw_status'] == 'completed' and r['node_observation_kind'] == 'exact'
            and isinstance(r['exact_nodes'], int) and r['exact_nodes'] >= 0 and r['original_reproduction_recheck'] != 'FAIL')


def compat_key(r):
    """Comparability key: (CPU/image/executable group, experiment, budget); None if any part is unknown."""
    k = (r['environment_build_group'], r['experiment_commit'], r['cpu_budget_s'])
    return None if any(x is None for x in k) else k


class State:
    __slots__ = ('solver', 'graph_id', 'state_id', 'state_index', 'sample_kind', 'snapshot_sha256', 'rows', 'n', 'original', 'valid',
                 'nodes', 'key', 'excluded', 'exclusion_reasons', 'status')

    def __init__(self, rows):
        rows = sorted(rows, key=lambda r: r['candidate_ordinal'])
        if [r['candidate_ordinal'] for r in rows] != list(range(len(rows))):
            raise DataError(f'candidate ordinals of {rows[0]["state_id"]} are not 0..n-1')
        r0 = rows[0]
        for f in ('solver', 'graph_id', 'state_id', 'state_index', 'snapshot_sha256', 'candidate_list_sha256', 'diag_initial_size_cap', 'diag_initial_solFound', 'sample_kind'):
            if any(r[f] != r0[f] for r in rows):
                raise DataError(f'state {r0["state_id"]} has inconsistent {f}')
        self.solver, self.graph_id, self.state_id, self.state_index = r0['solver'], r0['graph_id'], r0['state_id'], r0['state_index']
        self.sample_kind, self.snapshot_sha256 = r0['sample_kind'], r0['snapshot_sha256']
        self.rows = rows; self.n = len(rows)
        orig = [i for i, r in enumerate(rows) if r['is_original_pivot']]
        if len(orig) != 1:
            raise DataError(f'state {self.state_id} has {len(orig)} original pivots')
        self.original = orig[0]
        self.valid = [candidate_valid(r) for r in rows]
        self.nodes = [r['exact_nodes'] if v else None for r, v in zip(rows, self.valid)]
        self.key = [compat_key(r) if v else None for r, v in zip(rows, self.valid)]
        self.status = [r['raw_status'] for r in rows]
        reasons = []
        if any(r['state_completed_cap_consistent'] is False for r in rows):
            reasons.append('completed_cap_inconsistent')
        if any(r['original_reproduction_recheck'] == 'FAIL' for r in rows):
            reasons.append('original_reproduction_fail')
        if any(r['state_integrity_ok'] is not True for r in rows):
            reasons.append('state_integrity')
        self.exclusion_reasons = reasons; self.excluded = bool(reasons)

    def valid_groups(self):
        """{compat key: [ordinals]} over valid candidates of a non-excluded state."""
        g = {}
        if self.excluded:
            return g
        for i, (v, k) in enumerate(zip(self.valid, self.key)):
            if v and k is not None:
                g.setdefault(k, []).append(i)
        return g

    def complete_compatible(self):
        """Every candidate valid and all mutually compatible (one key), state not excluded."""
        return not self.excluded and all(self.valid) and len({k for k in self.key}) == 1 and self.key[0] is not None

    def censoring(self):
        if all(s != 'completed' for s in self.status):
            return 'entirely_censored'
        if any(s != 'completed' for s in self.status):
            return 'partially_censored'
        return 'none_censored'


def build_states(rows):
    by = {}
    for r in rows:
        by.setdefault(r['state_id'], []).append(r)
    states = [State(v) for v in by.values()]
    states.sort(key=lambda s: s.state_index)
    return states


def feature_matrix(state, columns):
    """Raw allowlisted inputs for every candidate of a state (rows in candidate order)."""
    out = []
    for r in state.rows:
        vals = [r[c] for c in columns]
        if any(v is None for v in vals):
            raise DataError(f'null model input in {state.state_id}')
        out.append([float(v) for v in vals])
    return out
