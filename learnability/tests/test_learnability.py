"""Unit and end-to-end tests (standard library unittest). Run from the repository root:
    python -m unittest discover -s learnability/tests -t .
"""
import copy
import csv
import inspect
import json
import random
import shutil
import tempfile
import unittest
import pathlib

from learnability import extract, pins
from learnability.decode import load_pinned_decoder, decode_checked, SnapshotError
from learnability.eligibility import eligible_candidates, EligibilityError, classical_rank
from learnability.features import compute_features, FEATURE_COLUMNS
from learnability.outcomes import parse_outcome, environment_build_group
from learnability.reference import reference_features
from learnability.schema import load_table, ALLOWLISTS, ROLES, format_cell, parse_cell, COLUMN_NAMES, model_inputs
from learnability.structure import validate_active_adjacency
from learnability.tests import fixtures as F


def feats(g, cands, size_cap=5, x=1, solver='8', root=None):
    return compute_features(solver, g['status'], g['neighbours'], g['neighDouble'], size_cap, x, cands, root)


class PureFeatureFixtures(unittest.TestCase):
    """Hand-calculated multigraph (not required to be a reachable snapshot)."""
    def test_hand_calculated_values(self):
        g = F.hand_graph()
        state, rows, diag = feats(g, [0, 6, 7], size_cap=5, x=1, solver='LP', root=2)
        self.assertEqual(state, dict(f_state_none_vertices=5, f_state_safe_vertices=1, f_state_distinct_edges=5, f_state_double_edges=1,
                                     f_state_remaining_threshold=4, f_state_candidate_count=3))
        self.assertEqual(diag['wdeg'], {0: 4, 1: 3, 2: 2, 3: 2, 6: 0, 7: 1})
        self.assertEqual(diag['weighted_degree_sum'], 2 * (5 + 1))
        r0, r6, r7 = rows
        self.assertEqual((r0['f_cand_none_neighbors'], r0['f_cand_safe_neighbors'], r0['f_cand_double_edges']), (2, 1, 1))
        self.assertEqual((r0['f_nbr_none_wdeg_min'], r0['f_nbr_none_wdeg_mean'], r0['f_nbr_none_wdeg_max']), (2.0, 2.5, 3.0))
        self.assertEqual(r0['f_lp_root_common_neighbors'], 1)          # N(0) & N(2) = {1}
        self.assertEqual((r0['diag_cand_distinct_degree'], r0['diag_cand_weighted_degree']), (3, 4))
        # isolated active vertex: empty undecided neighbourhood -> zeros, count 0 keeps emptiness explicit
        self.assertEqual([r6[c] for c in FEATURE_COLUMNS[:6]], [0, 0, 0, 0.0, 0.0, 0.0])
        self.assertEqual(r6['f_lp_root_common_neighbors'], 0)
        self.assertEqual((r7['f_nbr_none_wdeg_min'], r7['f_nbr_none_wdeg_mean'], r7['f_nbr_none_wdeg_max']), (2.0, 2.0, 2.0))
        self.assertIsInstance(r0['f_nbr_none_wdeg_mean'], float)

    def test_non_lp_column_is_null(self):
        _, rows, _ = feats(F.hand_graph(), [0], solver='8')
        self.assertIsNone(rows[0]['f_lp_root_common_neighbors'])

    def test_threshold_convention_not_clamped(self):
        for cap, x, want in ((5, 1, 4), (3, 3, 0), (2, 3, -1)):
            self.assertEqual(feats(F.hand_graph(), [0], size_cap=cap, x=x)[0]['f_state_remaining_threshold'], want)

    def test_edges_counted_once_regardless_of_multiplicity(self):
        g = F.make_graph([0, 0], [(0, 1, True)])
        st, rows, _ = feats(g, [0, 1], x=0)
        self.assertEqual((st['f_state_distinct_edges'], st['f_state_double_edges']), (1, 1))
        self.assertEqual(rows[0]['f_cand_none_neighbors'], 1)   # neighbour counted once, not twice
        self.assertEqual(rows[0]['diag_cand_weighted_degree'], 2)

    def test_inactive_buffers_ignored(self):
        g = F.hand_graph()
        self.assertEqual(validate_active_adjacency(g['status'], g['neighbours'], g['neighDouble'], g['doubleNum'], g['posAtNeigh']), [])
        g2 = copy.deepcopy(g); g2['neighbours'][5] = [0, 1, 3]; g2['neighDouble'][5] = [True, False, False]; g2['posAtNeigh'][5] = [0, 0, 0]
        self.assertEqual(feats(g, [0, 1, 3])[:2], feats(g2, [0, 1, 3])[:2])       # stale buffers of inactive vertex 5 ignored

    def test_signature_has_no_outcome_inputs(self):
        params = list(inspect.signature(compute_features).parameters)
        self.assertEqual(params, ['solver', 'status', 'neighbours', 'neigh_double', 'size_cap', 'x_size', 'candidates', 'root'])

    def test_budget_changes_only_threshold(self):
        a = feats(F.hand_graph(), [0, 6, 7], size_cap=5)[1]; b = feats(F.hand_graph(), [0, 6, 7], size_cap=9)[1]
        for ra, rb in zip(a, b):
            diff = {c for c in ra if ra[c] != rb[c]}
            self.assertEqual(diff, {'f_state_remaining_threshold'})


def reorder(g, seed):
    """Consistently permute every adjacency list (keeping posAtNeigh correct)."""
    rnd = random.Random(seed); n = len(g['status'])
    order = [list(range(len(g['neighbours'][v]))) for v in range(n)]
    for o in order: rnd.shuffle(o)
    newpos = [{old: new for new, old in enumerate(o)} for o in order]
    out = dict(g, neighbours=[[g['neighbours'][v][i] for i in order[v]] for v in range(n)],
               neighDouble=[[g['neighDouble'][v][i] for i in order[v]] for v in range(n)])
    out['posAtNeigh'] = [[newpos[g['neighbours'][v][i]][g['posAtNeigh'][v][i]] if g['status'][v] in (0, 1) and g['status'][g['neighbours'][v][i]] in (0, 1) else 0
                          for i in order[v]] for v in range(n)]
    return out


def relabel(g, perm):
    n = len(g['status']); inv = {perm[i]: i for i in range(n)}
    return dict(status=[g['status'][inv[i]] for i in range(n)], neighbours=[[perm[u] for u in g['neighbours'][inv[i]]] for i in range(n)],
                neighDouble=[list(g['neighDouble'][inv[i]]) for i in range(n)], posAtNeigh=[list(g['posAtNeigh'][inv[i]]) for i in range(n)],
                doubleNum=[g['doubleNum'][inv[i]] for i in range(n)])


def random_graph(seed, n=14):
    rnd = random.Random(seed)
    status = [rnd.choice([0, 0, 0, 1, -1, -2]) for _ in range(n)]
    act = [v for v in range(n) if status[v] in (0, 1)]
    edges = [(u, v, rnd.random() < .3) for i, u in enumerate(act) for v in act[i + 1:] if rnd.random() < .35]
    return F.make_graph(status, edges)


class Invariance(unittest.TestCase):
    def test_adjacency_reordering(self):
        for seed in range(30):
            g = random_graph(seed); cands = [v for v, s in enumerate(g['status']) if s == 0]
            r = reorder(g, seed)
            self.assertEqual(validate_active_adjacency(r['status'], r['neighbours'], r['neighDouble'], r['doubleNum'], r['posAtNeigh']), [])
            self.assertEqual(feats(g, cands)[1], feats(r, cands)[1])

    def test_vertex_relabeling(self):
        for seed in range(30):
            g = random_graph(seed); n = len(g['status']); perm = list(range(n)); random.Random(seed).shuffle(perm)
            cands = [v for v, s in enumerate(g['status']) if s == 0]
            root = next((v for v, s in enumerate(g['status']) if s == 1), None)
            a = feats(g, cands, solver='LP' if root is not None else '8', root=root)[1]
            b = feats(relabel(g, perm), [perm[v] for v in cands], solver='LP' if root is not None else '8', root=None if root is None else perm[root])[1]
            self.assertEqual(a, b)


class IntegrityValidation(unittest.TestCase):
    def errors(self, g):
        return validate_active_adjacency(g['status'], g['neighbours'], g['neighDouble'], g['doubleNum'], g['posAtNeigh'])

    def test_detects_violations(self):
        base = F.make_graph([0, 0, 0, -2], [(0, 1, True), (1, 2, False)])
        cases = {}
        g = copy.deepcopy(base); g['neighDouble'][1][0] = False; g['doubleNum'][1] = 0; cases['flag mismatch'] = g
        g = copy.deepcopy(base); g['doubleNum'][0] = 5; cases['doubleNum'] = g
        g = copy.deepcopy(base); g['neighbours'][0].append(3); g['neighDouble'][0].append(False); g['posAtNeigh'][0].append(0); cases['inactive ref'] = g
        g = copy.deepcopy(base); g['neighbours'][2].append(2); g['neighDouble'][2].append(False); g['posAtNeigh'][2].append(0); cases['self-loop'] = g
        g = copy.deepcopy(base); g['neighbours'][0].append(1); g['neighDouble'][0].append(False); g['posAtNeigh'][0].append(0); cases['duplicate'] = g
        g = copy.deepcopy(base); g['posAtNeigh'][2][0] = 0; g['neighbours'][1] = [0, 0]; cases['non-reciprocal'] = g
        self.assertEqual(self.errors(base), [])
        for name, g in cases.items():
            self.assertTrue(self.errors(g), name)


class ReferenceAgreement(unittest.TestCase):
    def test_reference_matches_main_on_random_graphs(self):
        for seed in range(200):
            g = random_graph(seed, n=random.Random(seed).randint(2, 25)); cands = [v for v, s in enumerate(g['status']) if s == 0]
            root = next((v for v, s in enumerate(g['status']) if s == 1), None); solver = 'LP' if root is not None else '5'
            main = feats(g, cands, solver=solver, root=root)[1]
            ref = reference_features(solver, g['status'], g['neighbours'], g['neighDouble'], 5, 1, cands, root)
            self.assertEqual([{c: r[c] for c in FEATURE_COLUMNS} for r in main], ref)


class EligibleStateFixtures(unittest.TestCase):
    """Reduced-state fixtures that satisfy the eligibility premises, round-tripped through the pinned decoder."""
    @classmethod
    def setUpClass(cls):
        cls.decode = staticmethod(load_pinned_decoder(F.PINNED_DECODER)[0])

    def test_cao_ties_and_order(self):
        s = decode_checked(self.decode, F.encode(F.cao_state()), '8')
        self.assertEqual(eligible_candidates(s), ([0, 1, 3], [3, 3, 3]))

    def test_lp_root_adjacency_order(self):
        s = decode_checked(self.decode, F.encode(F.lp_state()), 'LP')
        self.assertEqual(eligible_candidates(s)[0], [2, 0, 3])
        st, rows, _ = compute_features('LP', s['status'], s['neighbours'], s['neighDouble'], s['size_cap'], len(s['X']), [2, 0, 3], s['root'])
        self.assertEqual(st['f_state_safe_vertices'], 1)
        self.assertTrue(all(r['f_cand_safe_neighbors'] == 1 for r in rows))
        # N(4)={2,0,3}; N(2)={4,1,3} -> {3}; N(0)={4,1,3} -> {3}; N(3)={4,0,2} -> {0,2}
        self.assertEqual([r['f_lp_root_common_neighbors'] for r in rows], [1, 1, 2])

    def test_chen_requires_exhausted_hints(self):
        st = F.cao_state(); st['variant'] = '5'; del st['br2']
        s = decode_checked(self.decode, F.encode(st), '5')
        cands, scores = eligible_candidates(s)
        self.assertEqual(cands, [0, 1, 2, 3])                       # every undecided vertex, lower scores included
        self.assertEqual(scores, [[0, 3], [0, 3], [0, 1], [1, 3]])
        st['branching_hints'] = [2]
        with self.assertRaises(EligibilityError):
            eligible_candidates(decode_checked(self.decode, F.encode(st), '5'))

    def test_lp_root_must_be_safe(self):
        st = F.lp_state(); st['status'] = list(st['status']); st['status'][4] = 0
        with self.assertRaises(EligibilityError):
            eligible_candidates(decode_checked(self.decode, F.encode(st), 'LP'))

    def test_decoder_rejects_truncation_and_variant(self):
        b = F.encode(F.cao_state())
        with self.assertRaises(SnapshotError):
            decode_checked(self.decode, b[:-3], '8')
        with self.assertRaises(SnapshotError):
            decode_checked(self.decode, b, 'LP')

    def test_classical_rank(self):
        self.assertEqual([classical_rank([[1, 4], [2, 1], [1, 4]], k) for k in range(3)], [2, 1, 2])


def expected_for(rec):
    return dict(state_id=rec['state_id'], graph_id=rec['graph'], solver=rec['solver'], phase=rec['phase'], component_subsolver=rec['component_subsolver'],
                snapshot_sha256=rec['snapshot_sha256'], candidate_list_sha256=rec['candidate_list_sha256'], candidate_local_id=rec['candidate_local_id'],
                candidate_label=rec['candidate_id'], is_original_pivot=rec['original_pivot'], original_local_id=rec['measurement']['original_local_id'],
                state_index=rec['state_index'], initial_incumbent=rec['initial_incumbent'], classical_score=rec['classical_score'], classical_rank=rec['classical_rank'],
                stage_c_continuation=dict(complete=True, trace_count=3, trace_digest='11', final_state_hash='22'))


PINNED = dict(stage_d_experiment_commit=pins.STAGE_D_EXPERIMENT_COMMIT, cpu_budget_s=10)


class Outcomes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        F.build_dataset(tmp)
        with open(pathlib.Path(tmp) / 'staged/runs/45059940845/chunks/0/attempt-1/records.jsonl', encoding='utf-8') as fh:
            self.recs = [json.loads(l) for l in fh]

    def rec(self, original):
        return copy.deepcopy(next(r for r in self.recs if r['original_pivot'] == original))

    def test_completed_is_exact(self):
        r = self.rec(True); f, j, m = parse_outcome(r, expected_for(r), PINNED)
        self.assertEqual((j, m, f['node_observation_kind'], f['exact_nodes'], f['original_reproduction_recheck']), ([], [], 'exact', 5, 'pass'))
        self.assertEqual(f['process_cpu_s'], 0.0)        # zero is a measurement, not missing
        self.assertIsNone(f['forced_termination'])       # unspecified -> null

    def censor(self, r, status, code):
        r['status'] = status; r['exit_code'] = code; r['measurement']['status'] = status
        r['measurement']['children'][0]['status'] = status; r['measurement']['children'][1]['status'] = 'unstarted'
        r['measurement']['children'][1]['nodes'] = 0; r['measurement']['children'][1]['branching_decisions'] = 0
        r['measurement']['total_nodes'] = r['measurement']['children'][0]['nodes']; r['measurement']['branching_decisions'] = 2
        r['original_reproduction'] = 'not_original' if not r['original_pivot'] else 'untested_censored_or_no_complete_stage_c_reference'
        return r

    def test_censored_is_prefix_even_with_final_counts(self):
        for status, code in (('cpu_timeout', 74), ('cpu_timeout', 75), ('external_stop', 75)):
            r = self.censor(self.rec(False), status, code); f, j, m = parse_outcome(r, expected_for(r), PINNED)
            self.assertEqual((m, f['node_observation_kind'], f['exact_nodes'], f['counts_source']), ([], 'prefix', None, 'final'))
            self.assertIsNotNone(f['observed_nodes'])

    def test_external_stop_with_cpu_exit_code_is_flagged(self):
        r = self.censor(self.rec(False), 'external_stop', 74)
        self.assertEqual(parse_outcome(r, expected_for(r), PINNED)[0]['node_observation_kind'], 'invalid')

    def test_failed_and_unknown_statuses_invalid(self):
        r = self.censor(self.rec(False), 'failed', 1)
        self.assertEqual(parse_outcome(r, expected_for(r), PINNED)[0]['node_observation_kind'], 'invalid')
        r = self.rec(False); exp = expected_for(r); del r['measurement']; r['status'] = 'failed'
        f, j, m = parse_outcome(r, exp, PINNED)
        self.assertEqual((f['node_observation_kind'], f['observed_nodes']), ('missing', None))

    def test_unknown_timing_is_null_not_zero(self):
        r = self.rec(False); r['cpu_s'] = 'unknown'; f, j, m = parse_outcome(r, expected_for(r), PINNED)
        self.assertIsNone(f['process_cpu_s']); self.assertEqual(m, [])
        self.assertTrue(f['_notes']); self.assertEqual(f['node_observation_kind'], 'exact')   # nodes unaffected; never reconstructed from wall

    def test_original_replay_failure(self):
        r = self.rec(True); r['continuation']['trace_digest'] = 'other'
        f, j, m = parse_outcome(r, expected_for(r), PINNED)
        self.assertEqual((f['original_reproduction_recheck'], f['node_observation_kind'], f['exact_nodes']), ('FAIL', 'invalid', None))
        r = self.rec(True); r['original_reproduction'] = 'FAIL'
        self.assertEqual(parse_outcome(r, expected_for(r), PINNED)[0]['node_observation_kind'], 'invalid')

    def test_join_mismatches(self):
        for field, value in (('snapshot_sha256', '0' * 64), ('graph', '999'), ('candidate_local_id', 99), ('candidate_list_sha256', '1' * 64), ('initial_incumbent', {})):
            r = self.rec(False); exp = expected_for(r); r[field] = value
            self.assertTrue(parse_outcome(r, exp, PINNED)[1], field)

    def test_environment_group(self):
        e = dict(cpu='A', image='I')
        self.assertIsNone(environment_build_group(dict(cpu='A'), 'x'))
        self.assertIsNone(environment_build_group(e, None))
        self.assertNotEqual(environment_build_group(e, 'x'), environment_build_group(e, 'y'))
        self.assertNotEqual(environment_build_group(e, 'x'), environment_build_group(dict(cpu='B', image='I'), 'x'))
        self.assertEqual(environment_build_group(e, 'x'), environment_build_group(dict(image='I', cpu='A', os='other', runner='other'), 'x'))


class TypedTable(unittest.TestCase):
    def test_cell_round_trip(self):
        for v, t in (('001', 'string'), (0, 'int64'), (-7, 'int64'), (None, 'int64'), (True, 'bool'), (False, 'bool'), (0.1 + 0.2, 'float64'),
                     (2.5, 'float64'), (0.0, 'float64'), (1e-300, 'float64'), ([1, {'a': None}], 'json')):
            self.assertEqual(parse_cell(format_cell(v, t), t), v)
        self.assertEqual(format_cell(3, 'float64'), '3.0')
        with self.assertRaises(ValueError):
            format_cell(float('nan'), 'float64')

    def test_allowlists_only_features(self):
        for solver, cols in ALLOWLISTS.items():
            self.assertTrue(all(ROLES[c] == 'feature' for c in cols))
            self.assertFalse({'graph_id', 'candidate_label', 'is_original_pivot', 'exact_nodes', 'process_cpu_s'} & set(cols))
        self.assertNotIn('f_lp_root_common_neighbors', ALLOWLISTS['8'])
        self.assertNotIn('f_cand_safe_neighbors', ALLOWLISTS['LP']); self.assertNotIn('f_state_safe_vertices', ALLOWLISTS['LP'])


class EndToEnd(unittest.TestCase):
    """Run the real extractor on a miniature pinned dataset (git verification replaced by a stub)."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: getattr(pins, k) for k in ('EXPECTED', 'EXPECTED_STATES', 'EXPECTED_CANDIDATES', 'EXPECTED_CHUNKS')}
        self.addCleanup(lambda: [setattr(pins, k, v) for k, v in saved.items()])
        pins.EXPECTED = {'8': dict(states=1, candidates=3), '5': dict(states=0, candidates=0), 'LP': dict(states=1, candidates=3)}
        pins.EXPECTED_STATES, pins.EXPECTED_CANDIDATES, pins.EXPECTED_CHUNKS = 2, 6, 2
        real = extract.Verifier
        class Stub(real):
            def __init__(self, enabled): super().__init__(enabled); self.enabled = True
            def check(self, *a): self.results['verified'] += 1; return True
        extract.Verifier = Stub; self.addCleanup(setattr, extract, 'Verifier', real)

    def run_extract(self, name, mutate=None, ext='extract-v1-test'):
        exp, scr, sdr, _ = F.build_dataset(self.tmp / name, mutate)
        out = self.tmp / name / 'out'
        code = extract.main(['--experiment-tree', str(exp), '--stagec-records', str(scr), '--staged-records', str(sdr), '--output-root', str(out), '--extraction-id', ext])
        d = out / ext if code == 0 else out / (ext + '.INCOMPLETE')
        return code, d, json.loads((d / 'validation.json').read_text())

    def test_clean_dataset_completes_and_round_trips(self):
        code, d, v = self.run_extract('clean')
        self.assertEqual((code, v['dataset_status']), (0, 'complete_validated'), v['problems'])
        self.assertTrue((d / 'COMPLETE').exists())
        rows = load_table(d / 'candidates_LP.csv', d / 'schema.json')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['graph_id'], '014')                      # leading zero preserved
        self.assertIsInstance(rows[0]['f_nbr_none_wdeg_mean'], float); self.assertIsInstance(rows[0]['f_lp_root_common_neighbors'], int)
        self.assertEqual([r['node_observation_kind'] for r in rows], ['exact'] * 3)
        self.assertEqual(len(model_inputs(rows[0], 'LP')), 11)
        cao = load_table(d / 'candidates_8.csv', d / 'schema.json')
        self.assertTrue(all(r['f_lp_root_common_neighbors'] is None for r in cao))
        with open(d / 'candidates_8.csv', newline='') as f:
            self.assertEqual(next(csv.reader(f)), list(COLUMN_NAMES))
        self.assertNotIn(b'\r\n', (d / 'candidates_8.csv').read_bytes())

    def test_deterministic_rerun_into_new_directory(self):
        _, d1, _ = self.run_extract('det', ext='extract-v1-a')
        exp = self.tmp / 'det'
        out2 = self.tmp / 'det' / 'out2'
        code = extract.main(['--experiment-tree', str(exp / 'experiment'), '--stagec-records', str(exp / 'stagec'), '--staged-records', str(exp / 'staged'),
                             '--output-root', str(out2), '--extraction-id', 'extract-v1-b'])
        self.assertEqual(code, 0)
        for name in ('candidates_8.csv', 'candidates_5.csv', 'candidates_LP.csv', 'states.jsonl', 'invocations.jsonl', 'schema.json'):
            self.assertEqual((d1 / name).read_bytes(), (out2 / 'extract-v1-b' / name).read_bytes(), name)

    def test_refuses_existing_output(self):
        self.run_extract('reuse')
        exp = self.tmp / 'reuse'
        with self.assertRaises(SystemExit):
            extract.main(['--experiment-tree', str(exp / 'experiment'), '--stagec-records', str(exp / 'stagec'), '--staged-records', str(exp / 'staged'),
                          '--output-root', str(exp / 'out'), '--extraction-id', 'extract-v1-test'])

    def test_duplicate_attempt_is_multiple_with_null_outcomes(self):
        def mut(kind, obj):
            if kind == 'records':
                dup = copy.deepcopy(obj['1'][0]); dup['run_id'] = 'uuid-retry'; obj['1'].append(dup)
        code, d, v = self.run_extract('dup', mut)
        self.assertEqual((code, v['dataset_status']), (2, 'incomplete'))
        rows = load_table(d / 'candidates_LP.csv', d / 'schema.json')
        r = rows[0]
        self.assertEqual((r['invocation_resolution'], r['invocation_count'], r['node_observation_kind'], r['exact_nodes'], r['process_cpu_s']),
                         ('multiple', 2, 'unresolved_multiple', None, None))
        self.assertEqual(len(r['invocation_refs_json']), 2)
        self.assertEqual(len((d / 'invocations.jsonl').read_text().splitlines()), 7)  # nothing collapsed
        self.assertIsNotNone(r['f_cand_none_neighbors'])                   # features kept

    def test_missing_invocation_keeps_feature_row(self):
        def mut(kind, obj):
            if kind == 'records': obj['0'].pop()
        code, d, v = self.run_extract('missing', mut)
        self.assertEqual(code, 2)
        rows = load_table(d / 'candidates_8.csv', d / 'schema.json')
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[-1]['invocation_resolution'], rows[-1]['node_observation_kind'], rows[-1]['join_valid']), ('missing', 'missing', None))

    def test_duplicate_uuid_flagged(self):
        def mut(kind, obj):
            if kind == 'records': obj['0'][1]['run_id'] = obj['0'][0]['run_id']
        code, d, v = self.run_extract('uuid', mut)
        self.assertEqual((code, v['counts']['duplicate_uuids']), (2, 1))

    def test_snapshot_hash_mismatch_fails_state(self):
        def mut(kind, obj):
            if kind == 'index': obj['states'][0]['snapshot_sha256'] = '0' * 64
        code, d, v = self.run_extract('hash', mut)
        self.assertEqual(code, 2)
        self.assertFalse(v['acceptance']['all_states_integrity_ok'])

    def test_wrong_graph_join_and_unexpected_record(self):
        def mut(kind, obj):
            if kind == 'records':
                obj['0'][0]['graph'] = '999'
                extra = copy.deepcopy(obj['0'][1]); extra['run_id'] = 'stray'; extra['candidate_local_id'] = 2; obj['0'].append(extra)
        code, d, v = self.run_extract('join', mut)
        self.assertEqual(code, 2)
        self.assertEqual(v['counts']['unexpected_records'], 1)
        rows = load_table(d / 'candidates_8.csv', d / 'schema.json')
        self.assertFalse(rows[0]['join_valid']); self.assertIsNone(rows[0]['exact_nodes'])

    def test_censored_and_replay_failure_rows(self):
        def mut(kind, obj):
            if kind == 'records':
                r = obj['1'][1]; r.update(status='cpu_timeout', exit_code=74); r['measurement']['status'] = 'cpu_timeout'
                r['measurement']['children'][1].update(status='unstarted', nodes=0, branching_decisions=0)
                r['measurement']['total_nodes'] = r['measurement']['children'][0]['nodes']; r['measurement']['branching_decisions'] = 2
                orig = next(x for x in obj['0'] if x['original_pivot']); orig['continuation']['trace_digest'] = 'bad'
        code, d, v = self.run_extract('cens', mut)
        lp = load_table(d / 'candidates_LP.csv', d / 'schema.json'); cao = load_table(d / 'candidates_8.csv', d / 'schema.json')
        self.assertEqual((lp[1]['node_observation_kind'], lp[1]['exact_nodes']), ('prefix', None))
        self.assertIsNotNone(lp[1]['observed_nodes'])
        o = next(r for r in cao if r['is_original_pivot'])
        self.assertEqual((o['original_reproduction_recheck'], o['node_observation_kind']), ('FAIL', 'invalid'))
        self.assertEqual(code, 2)

    def test_stage_d_report_disagreement_blocks_completion(self):
        exp, scr, sdr, _ = F.build_dataset(self.tmp / 'rep')
        p = sdr / 'runs/45059940845/report/attempt-1/REPORT.md'; p.write_text(p.read_text().replace('(including retries): 6', '(including retries): 7'))
        code = extract.main(['--experiment-tree', str(exp), '--stagec-records', str(scr), '--staged-records', str(sdr),
                             '--output-root', str(self.tmp / 'rep' / 'out'), '--extraction-id', 'extract-v1-rep'])
        v = json.loads((self.tmp / 'rep' / 'out' / 'extract-v1-rep.INCOMPLETE' / 'validation.json').read_text())
        self.assertEqual(code, 2); self.assertFalse(v['acceptance']['stage_d_report_agrees'])

    def test_completed_cap_inconsistency_flags_state(self):
        def mut(kind, obj):
            if kind == 'records': obj['0'][2]['measurement']['final_incumbent']['size_cap'] = 1
        code, d, v = self.run_extract('cap', mut)
        rows = load_table(d / 'candidates_8.csv', d / 'schema.json')
        self.assertEqual(code, 2)
        self.assertTrue(all(r['state_completed_cap_consistent'] is False for r in rows))

    def test_features_unaffected_by_outcome_and_environment(self):
        def mut(kind, obj):
            if kind == 'records':
                for r in obj['0'] + obj['1']:
                    r['cpu_s'] = 9.99; r['environment']['cpu'] = 'Other CPU'; r['measurement']['total_nodes'] += 0
        _, d1, _ = self.run_extract('fa'); _, d2, _ = self.run_extract('fb', mut)
        for name in ('candidates_8.csv', 'candidates_LP.csv'):
            a = load_table(d1 / name, d1 / 'schema.json'); b = load_table(d2 / name, d2 / 'schema.json')
            self.assertEqual([[r[c] for c in FEATURE_COLUMNS] for r in a], [[r[c] for c in FEATURE_COLUMNS] for r in b])
            self.assertNotEqual([r['environment_build_group'] for r in a], [r['environment_build_group'] for r in b])


if __name__ == '__main__':
    unittest.main()
