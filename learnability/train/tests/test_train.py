"""Correctness checks for the offline learnability stage (synthetic data only; no solver runs).
Run: python -m unittest discover -s learnability/train/tests -t .
"""
import itertools
import json
import math
import pathlib
import shutil
import tempfile
import unittest

import numpy as np

from learnability.schema import ALLOWLISTS, ROLES
from learnability.train import boost as B, data as D, evaluate as E, folds as FO, linear as L, pairs as PA, run as R, transforms as T

COLS = ALLOWLISTS['8']


def row(si, graph, k, n, nodes, key=('g', 'c', 10.0), original=0, feats=None, status=None, kind='reservoir'):
    st = status or ('completed' if nodes is not None else 'cpu_timeout')
    r = dict(solver='8', graph_id=graph, state_id=f's{si}', state_index=si, candidate_ordinal=k, is_original_pivot=k == original, sample_kind=kind,
             snapshot_sha256='x', candidate_list_sha256='y', diag_initial_size_cap=5, diag_initial_solFound=True,
             invocation_resolution='unique', join_valid=True, measurement_integrity_ok=True, state_integrity_ok=True, raw_status=st,
             node_observation_kind='exact' if st == 'completed' else 'prefix', exact_nodes=nodes if st == 'completed' else None,
             original_reproduction_recheck='pass' if k == original else 'not_original', state_completed_cap_consistent=True,
             environment_build_group=key[0], experiment_commit=key[1], cpu_budget_s=key[2])
    for j, c in enumerate(COLS):
        r[c] = float((feats or [0.0] * len(COLS))[j]) if feats else float(k + j)
    return r


def make_state(si, graph, nodes, keys=None, original=0, feats=None):
    return D.State([row(si, graph, k, len(nodes), x, key=(keys[k] if keys else ('g', 'c', 10.0)), original=original,
                        feats=None if feats is None else feats[k]) for k, x in enumerate(nodes)])


class Pairs(unittest.TestCase):
    def test_orientation_ties_and_censoring(self):
        s = make_state(0, '001', [5, 3, 3, None, 9])
        p, tot, info = PA.state_pairs(s)
        self.assertEqual(sorted(p), sorted([(1, 0), (2, 0), (1, 4), (2, 4), (0, 4)]))   # better -> worse; 1,2 tie -> no pair; 3 censored
        self.assertEqual((tot, info['valid_candidates']), (5, 4))
        for b, w in p:
            self.assertLess(s.nodes[b], s.nodes[w])

    def test_compatibility_groups(self):
        s = make_state(0, '001', [1, 2, 3, 4], keys=[('a', 'c', 10.0), ('a', 'c', 10.0), ('b', 'c', 10.0), ('b', 'c', 10.0)])
        self.assertEqual(sorted(PA.state_pairs(s)[0]), [(0, 1), (2, 3)])
        s = make_state(0, '001', [1, 2], keys=[('a', 'c', 10.0), (None, 'c', 10.0)])
        self.assertEqual(PA.state_pairs(s)[0], [])                                       # unknown key is not equal

    def test_excluded_state_has_no_pairs(self):
        s = make_state(0, '001', [1, 2, 3]); s.rows[1]['state_completed_cap_consistent'] = False
        self.assertEqual(PA.state_pairs(D.State(s.rows))[0], [])

    def test_sampling_unique_uniform_deterministic(self):
        nodes = list(range(100)) + [50] * 10
        s = make_state(7, '002', nodes)
        p1, tot, info = PA.state_pairs(s, cap=300); p2, _, _ = PA.state_pairs(s, cap=300)
        self.assertEqual(p1, p2); self.assertTrue(info['sampled']); self.assertEqual(len(set(p1)), 300)
        full, tot2, _ = PA.state_pairs(s, cap=10**9)
        self.assertEqual(tot, tot2); self.assertEqual(len(full), tot); self.assertEqual(len(set(full)), tot)
        self.assertTrue(set(p1) <= set(full))
        # unranking enumerates exactly the strict pairs
        expect = {(i, j) if nodes[i] < nodes[j] else (j, i) for i, j in itertools.combinations(range(len(nodes)), 2) if nodes[i] != nodes[j]}
        self.assertEqual(set(full), expect)
        # empirical uniformity of Floyd sampling over a small population
        counts = np.zeros(20)
        for t in range(400):
            for x in PA.floyd_sample(20, 5, PA._Rng('8', f'u{t}')):
                counts[x] += 1
        self.assertLess(np.max(np.abs(counts / counts.sum() - 0.05)), 0.03)

    def test_weights(self):
        pairs = {0: [(0, 1)] * 2, 1: [(0, 1)] * 4, 2: [(0, 1)], 3: []}
        graph = {0: 'a', 1: 'a', 2: 'b', 3: 'c'}
        w, G = PA.pair_weights(pairs, graph)
        self.assertEqual(G, 2)
        self.assertAlmostEqual(sum(w[s] * len(pairs[s]) for s in w), 1.0)
        self.assertAlmostEqual(w[0] * 2 + w[1] * 4, 0.5)                      # each graph has total mass 1/G
        self.assertAlmostEqual(w[0] * 2, w[1] * 4)                            # each informative state equal within graph
        self.assertNotIn(3, w)


class Folds(unittest.TestCase):
    def test_assignment_balanced_disjoint_deterministic(self):
        groups = [[f'{i:03d}'] for i in range(1, 101) if i not in (8, 21)] + [['008', '021']]
        f1, sizes = FO.assign_folds(groups); f2, _ = FO.assign_folds(groups)
        self.assertEqual(f1, f2); self.assertEqual(sorted(sizes), [20] * 5)
        self.assertEqual(f1['008'], f1['021']); self.assertEqual(len(f1), 100)
        self.assertEqual(set(f1.values()), set(range(5)))

    def test_frozen_manifest_shared_by_all_solvers(self):
        frozen = pathlib.Path(__file__).resolve().parents[1] / 'frozen'
        m = json.loads((frozen / 'folds.json').read_text())
        self.assertEqual(len(m['folds']), 100); self.assertTrue(all(len(g) == 3 for g in m['folds']))
        for grp in m['groups']:
            self.assertEqual(len({m['folds'][g] for g in grp}), 1)
        cfg = json.loads((frozen / 'config.json').read_text())
        self.assertEqual(cfg['folds_sha256'], m['manifest_sha256'])

    def test_wl_signature_detects_relabeling(self):
        e1 = [('1', '2'), ('2', '3'), ('3', '1'), ('3', '4')]; e2 = [('a', 'b'), ('b', 'c'), ('c', 'a'), ('a', 'd')]
        self.assertEqual(FO.wl_signature(e1)[0], FO.wl_signature(e2)[0])
        self.assertNotEqual(FO.wl_signature(e1)[0], FO.wl_signature(e1 + [('4', '5')])[0])


class Features(unittest.TestCase):
    def test_allowlists(self):
        for s in ('8', '5', 'LP'):
            cols = T.inputs_for(s); self.assertEqual(cols, ALLOWLISTS[s])
            self.assertTrue(all(ROLES[c] == 'feature' for c in cols))
            cand, ctx = T.split(cols); self.assertTrue(cand and ctx)
            ab = T.inputs_for(s, True); self.assertFalse(set(ab) & set(T.ABLATION_REMOVED)); self.assertTrue(set(ab) < set(cols))
        self.assertEqual(len(ALLOWLISTS['8']), 12); self.assertEqual(len(ALLOWLISTS['LP']), 11)

    def test_transform_training_only_and_zero_variance(self):
        rng = np.random.default_rng(1); X = rng.normal(size=(50, 12)); X[:, 3] = 7.0
        t = T.LinearTransform(COLS).fit(X)
        Phi = t.transform(X)
        self.assertEqual(Phi.shape[1], 6 + 36)
        self.assertTrue(np.all(Phi[:, 3] == 0))                                # zero-variance candidate column -> 0
        self.assertTrue(np.allclose(Phi[:, [0, 1, 2, 4, 5]].mean(0), 0) and np.allclose(Phi[:, [0, 1, 2, 4, 5]].std(0), 1))
        t2 = T.LinearTransform.from_export(json.loads(json.dumps(t.export())))
        self.assertTrue(np.array_equal(t2.transform(X * 3), t.transform(X * 3)))  # export round trip is exact

    def test_shared_additive_invariance(self):
        rng = np.random.default_rng(2); s = rng.normal(size=10); b = np.array([0, 2, 5]); w = np.array([1, 3, 6]); wt = np.array([.2, .3, .5])
        self.assertAlmostEqual(B.pair_loss(s, b, w, wt), B.pair_loss(s + 4.2, b, w, wt))
        g1, h1 = B.pair_grad_hess(s, b, w, wt, 1.0); g2, h2 = B.pair_grad_hess(s + 4.2, b, w, wt, 1.0)
        self.assertTrue(np.allclose(g1, g2) and np.allclose(h1, h2))


class Objectives(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3); self.Phi = rng.normal(size=(12, 5)); self.b = rng.integers(0, 12, 30); self.w = (self.b + 1 + rng.integers(0, 10, 30)) % 12
        self.wt = rng.random(30); self.wt /= self.wt.sum(); self.theta = rng.normal(size=5)

    def test_linear_gradient_finite_difference(self):
        for lam in (0.0, 0.1):
            f, g = L.loss_grad(self.theta, self.Phi, self.b, self.w, self.wt, lam)
            for j in range(5):
                e = np.zeros(5); e[j] = 1e-6
                num = (L.loss_grad(self.theta + e, self.Phi, self.b, self.w, self.wt, lam)[0] - L.loss_grad(self.theta - e, self.Phi, self.b, self.w, self.wt, lam)[0]) / 2e-6
                self.assertAlmostEqual(num, g[j], places=6)

    def test_boost_gradient_and_hessian_bound(self):
        s = self.Phi @ self.theta; C = 7.0
        g, h = B.pair_grad_hess(s, self.b, self.w, self.wt, C)
        for i in range(12):
            e = np.zeros(12); e[i] = 1e-6
            num = (B.pair_loss(s + e, self.b, self.w, self.wt) - B.pair_loss(s - e, self.b, self.w, self.wt)) / 2e-6
            self.assertAlmostEqual(num * C, g[i], places=5)                  # common scaling C verified
        H = np.zeros((12, 12))
        for bb, ww, wt in zip(self.b, self.w, self.wt):
            p = 1 / (1 + math.exp(-(s[ww] - s[bb]))); v = np.zeros(12); v[bb] += 1; v[ww] -= 1
            H += wt * p * (1 - p) * np.outer(v, v)
        Hnum = np.zeros((12, 12))
        for i in range(12):
            e = np.zeros(12); e[i] = 1e-5
            Hnum[:, i] = (B.pair_grad_hess(s + e, self.b, self.w, self.wt, 1.0)[0] - B.pair_grad_hess(s - e, self.b, self.w, self.wt, 1.0)[0]) / 2e-5
        self.assertTrue(np.allclose(H, Hnum, atol=1e-6))                     # exact Hessian (non-diagonal) by finite difference
        self.assertGreater(np.abs(H - np.diag(np.diag(H))).max(), 0)
        self.assertGreaterEqual(np.linalg.eigvalsh(np.diag(h / C) - H).min(), -1e-12)   # diagonal upper bound is valid


def synthetic_solver(n_graphs=10, states_per=6, n=5, seed=0, signal=True):
    """Better candidates have larger feature 0 (if signal)."""
    rng = np.random.default_rng(seed); sd = type('SD', (), {})(); sd.solver = '8'; sd.inputs = list(COLS); sd.states = []
    si = 0
    for gi in range(n_graphs):
        for _ in range(states_per):
            f = rng.normal(size=(n, len(COLS)))
            nodes = [int(100 - 10 * f[k, 0]) if signal else int(rng.integers(1, 50)) for k in range(n)]
            sd.states.append(make_state(si, f'{gi:03d}', nodes, original=int(rng.integers(0, n)), feats=f.tolist())); si += 1
    sd.by_index = {s.state_index: s for s in sd.states}; sd.graph_of = {s.state_index: s.graph_id for s in sd.states}
    sd.fold_of = {s.state_index: int(s.graph_id) % 5 for s in sd.states}
    sd.X = {s.state_index: np.array(D.feature_matrix(s, COLS)) for s in sd.states}
    sd.pairs = {s.state_index: PA.state_pairs(s)[0] for s in sd.states}
    return sd


class Learning(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_fit(self, family, cfg, sd=None, mutate_test=None, tag='a'):
        sd = sd or synthetic_solver()
        train = [s.state_index for s in sd.states if sd.fold_of[s.state_index] != 0]; test = [s.state_index for s in sd.states if sd.fold_of[s.state_index] == 0]
        if mutate_test:
            mutate_test(sd, test)
        return R.fit_and_score(sd, family, cfg, train, test, COLS, self.tmp / f'{family}-{tag}'), sd

    def test_both_rankers_learn_known_preference(self):
        for fam, cfg in (('linear', {'id': 'l', 'lambda': 1e-3}), ('boost', {'id': 'b', 'max_depth': 2, 'rounds': 100})):
            (status, evals, scores), _ = self.run_fit(fam, cfg)
            self.assertTrue(status['ok'], status)
            best = np.mean([e['best_selected'] for e in evals if e['best_selected'] is not None])
            self.assertGreater(best, 0.9, fam)
            self.assertLess(E.summarise(evals)['selection_metric'], 0, fam)

    def test_held_out_outcomes_and_features_do_not_affect_training(self):
        cfg = {'id': 'l', 'lambda': 1e-2}
        (st1, ev1, sc1), _ = self.run_fit('linear', cfg, tag='a')
        def flip(sd, test):
            for si in test:
                s = sd.by_index[si]; s.nodes = [None if x is None else 10**6 - x for x in s.nodes]
        (st2, ev2, sc2), _ = self.run_fit('linear', cfg, mutate_test=flip, tag='b')
        self.assertEqual(sc1, sc2)                                           # predictions invariant to outcome changes
        m1 = json.loads((self.tmp / 'linear-a' / 'model.json').read_text()); m2 = json.loads((self.tmp / 'linear-b' / 'model.json').read_text())
        self.assertEqual(m1['theta'], m2['theta']); self.assertEqual(m1['transform'], m2['transform'])
        def scramble(sd, test):
            for si in test:
                sd.X[si] = sd.X[si] * 1000 + 5
        (st3, _, _), _ = self.run_fit('linear', cfg, mutate_test=scramble, tag='c')
        m3 = json.loads((self.tmp / 'linear-c' / 'model.json').read_text())
        self.assertEqual(m1['transform'], m3['transform']); self.assertEqual(m1['theta'], m3['theta'])   # preprocessing never sees held-out rows

    def test_boost_deterministic_and_export_roundtrip(self):
        cfg = {'id': 'b', 'max_depth': 3, 'rounds': 50}
        (s1, _, sc1), _ = self.run_fit('boost', cfg, tag='x'); (s2, _, sc2), _ = self.run_fit('boost', cfg, tag='y')
        self.assertEqual(sc1, sc2); self.assertEqual(s1['export_roundtrip_max_abs_diff'], 0.0)
        self.assertEqual((self.tmp / 'boost-x' / 'model.json').read_bytes(), (self.tmp / 'boost-y' / 'model.json').read_bytes())

    def test_linear_nonconvergence_is_a_failure(self):
        old = dict(L.OPTIONS); L.OPTIONS['maxiter'] = 1
        try:
            (status, _, _), _ = self.run_fit('linear', {'id': 'l', 'lambda': 1e-5})
        finally:
            L.OPTIONS.clear(); L.OPTIONS.update(old)
        self.assertFalse(status['ok']); self.assertIn('convergence', status['failure'])


class Selection(unittest.TestCase):
    def test_tie_rules(self):
        self.assertEqual(E.select([1.0, 3.0, 3.0], 2), (2, 2))               # original among maxima
        self.assertEqual(E.select([1.0, 3.0, 3.0], 0), (1, 2))               # else lowest archived ordinal
        self.assertEqual(E.select([0.1 + 0.2, 0.3], 1), (0, 1))              # exact comparison, no epsilon band
        with self.assertRaises(E.ScoreError):
            E.select([1.0, float('nan')], 0)

    def test_state_metrics_hand_calculated(self):
        s = make_state(0, '001', [4, 0, 9], original=0)
        e = E.evaluate_state(s, 1)
        self.assertEqual((e['outcome'], e['node_difference'], e['ratio'], e['best_selected']), ('win', 4, 0.0, True))
        self.assertAlmostEqual(e['selection_cost'], math.log(1 / 5))
        s0 = make_state(0, '001', [0, 3], original=0); e0 = E.evaluate_state(s0, 1)
        self.assertEqual((e0['outcome'], e0['ratio']), ('loss', None))            # zero denominator -> ratio undefined
        self.assertAlmostEqual(e0['selection_cost'], math.log(4 / 1))
        sc = make_state(0, '001', [None, 3, 5], original=0)
        ec = E.evaluate_state(sc, 0)
        self.assertEqual((ec['agrees_with_original'], ec['comparable'], ec['node_difference'], ec['selection_cost']), (True, False, None, None))
        si = make_state(0, '001', [2, 3], keys=[('a', 'c', 10.0), ('b', 'c', 10.0)], original=0)
        ei = E.evaluate_state(si, 1)
        self.assertEqual(ei['unresolved_reasons'], ['environment_incompatible']); self.assertFalse(si.complete_compatible())

    def test_graph_aggregation_and_choose(self):
        ev = [dict(graph_id='a', selection_cost=1.0), dict(graph_id='a', selection_cost=3.0), dict(graph_id='b', selection_cost=0.0)]
        self.assertEqual(E.graph_aggregate(ev)[0], 1.0)                       # (mean(1,3) + 0) / 2
        lin = [dict(config={'lambda': l}, metric=m, valid=True) for l, m in ((1e-3, .5), (1e-1, .5), (1.0, .6))]
        self.assertEqual(E.choose('linear', lin)['config']['lambda'], 1e-1)
        bo = [dict(config={'rounds': r, 'max_depth': d}, metric=.2, valid=True) for d, r in ((3, 50), (2, 100), (2, 50))]
        self.assertEqual(E.choose('boost', bo)['config'], {'rounds': 50, 'max_depth': 2})
        bad = [dict(config={'lambda': 1.0}, metric=None, valid=False)]
        self.assertIsNone(E.choose('linear', bad))

    def test_bootstrap_resamples_graphs(self):
        b1 = E.bootstrap({'a': -1.0, 'b': 0.0, 'c': 1.0}, label='t'); b2 = E.bootstrap({'a': -1.0, 'b': 0.0, 'c': 1.0}, label='t')
        self.assertEqual(b1, b2); self.assertEqual(b1['graphs'], 3); self.assertEqual(b1['estimate'], 0.0)
        self.assertTrue(-1.0 <= b1['ci95'][0] <= 0.0 <= b1['ci95'][1] <= 1.0)


if __name__ == '__main__':
    unittest.main()
