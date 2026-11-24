"""Unit tests for integration-v1 (public, synthetic). Run: python -m unittest discover -s integration/tests -t ."""
import hashlib, json, os, pathlib, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import schedule as S  # noqa: E402
import invoke  # noqa: E402

UPSTREAM = os.environ.get('INTEGRATION_UPSTREAM')


class ScheduleTests(unittest.TestCase):
    def test_deterministic_and_balanced(self):
        for n in (1, 5, 6, 7, 12, 100, 130):
            ids = [f'g{i:03d}' for i in range(n)]
            a, b = S.make_schedule(ids), S.make_schedule(list(reversed(ids)))
            self.assertEqual(a, b)
            if n >= 6:
                self.assertTrue(S.check_balance(a))
            for s in S.SOLVERS:
                self.assertEqual([j['graph_id'] for j in a['jobs'][s]], sorted(ids))
                for j in a['jobs'][s]:
                    self.assertEqual(sorted(j['order']), sorted(S.POLICIES))

    def test_rank_rule(self):
        ids = [f'g{i:03d}' for i in range(30)]
        sch = S.make_schedule(ids)
        for s in S.SOLVERS:
            ranked = sorted(ids, key=lambda g: hashlib.sha256(f'integration-v1|order|{s}|{g}'.encode()).hexdigest())
            for j in sch['jobs'][s]:
                self.assertEqual(j['order'], S.PERMS[ranked.index(j['graph_id']) % 6])

    def test_budget(self):
        m = S.make_schedule([f'p{i}' for i in range(130)])['manifest']
        self.assertEqual(m['invocations'], 1170); self.assertEqual(m['max_solver_cpu_hours'], 585.0)
        self.assertEqual(m['max_concurrent_jobs'], 20)
        self.assertGreater(m['job_timeout_minutes'] * 60, 3 * S.watchdog_s(1800))

    def test_duplicates_refused(self):
        with self.assertRaises(AssertionError):
            S.make_schedule(['a', 'a'])


def inv(status, nodes=None, cpu=None, wall=None, size=None, feasible=None):
    return dict(status=status, nodes=nodes, cpu_s=cpu, wall_s=wall, size=size, feasible=feasible, decisions=None, target=None, eligible=None,
                scored=None, departures=None, counts_source='summary.json')


class ReportTests(unittest.TestCase):
    def run_report(self, jobs):
        import report as R
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            sched = S.make_schedule([g for g, _ in jobs])
            (t / 's.json').write_text(json.dumps(sched))
            for g, (att, invs) in jobs:
                for k, (attempt, infra) in enumerate(att):
                    d = t / 'jobs' / g / f'attempt-{attempt}'; d.mkdir(parents=True)
                    j = dict(schema='integration-v1-job', job=dict(solver='8', graph_id=g, order=['baseline', 'linear', 'boost']), environment=dict(github_run_attempt=str(attempt), cpu_model='x', image='y'),
                             invocations=invs[k], infrastructure_failure=infra, completed_sizes_agree=True)
                    (d / 'job.json').write_text(json.dumps(j))
            subprocess.run([sys.executable, str(HERE / 'report.py'), '--schedule', str(t / 's.json'), '--jobs', str(t / 'jobs'), '--out', str(t / 'out')], check=True, stdout=subprocess.DEVNULL)
            return json.loads((t / 'out/report.json').read_text())['solvers']['8']['comparisons']

    def test_categories_and_measures(self):
        ok = lambda n, c: inv('completed', n, c, c + 0.01, 5, True)
        jobs = [('a', ([(1, False)], [dict(baseline=ok(10, 1.0), linear=ok(5, 0.5), boost=ok(20, 2.0))])),
                ('b', ([(1, False)], [dict(baseline=ok(10, 0.0), linear=ok(10, 0.0), boost=ok(10, 0.0))])),
                ('c', ([(1, False)], [dict(baseline=inv('cpu_timeout', 999, 1800.0, 1801.0), linear=ok(7, 3.0), boost=inv('cpu_timeout', 5, 1800.0, 1800.0))])),
                ('d', ([(1, False)], [dict(baseline=ok(7, 3.0), linear=inv('policy_error'), boost=inv('verification_failed', 3, 1.0, 1.0, 4, False))])),
                ('e', ([(1, True), (2, False)], [dict(baseline=inv('wall_watchdog'), linear=ok(1, 1.0), boost=ok(1, 1.0)), dict(baseline=ok(2, 1.0), linear=ok(3, 1.5), boost=ok(2, 1.0))])),
                ('f', ([(1, True)], [dict(baseline=inv('wall_watchdog'), linear=ok(1, 1.0), boost=ok(1, 1.0))]))]
        c = self.run_report(jobs)
        lin, bst = c['baseline_vs_linear'], c['baseline_vs_boost']
        self.assertEqual(lin['categories'], dict(both_solved=3, learned_only_solved=1, error=1, infrastructure_failure=1))
        self.assertEqual(bst['categories'], dict(both_solved=3, both_timed_out=1, verification_failure=1, infrastructure_failure=1))
        nodes = lin['measures']['nodes']; cpu = lin['measures']['cpu_s']
        self.assertEqual(nodes['pairs'], 3); self.assertEqual(nodes['learned_lower'], 1); self.assertEqual(nodes['learned_higher'], 1)
        self.assertEqual(cpu['ratio_undefined_pairs'], 1)   # graph b: baseline CPU 0 -> no ratio
        self.assertAlmostEqual(nodes['geometric_mean_ratio'], (0.5 * 1.0 * 1.5) ** (1 / 3))
        self.assertEqual(lin['solved_baseline'], 4); self.assertEqual(lin['solved_learned'], 4)

    def test_missing_record(self):
        jobs = [('a', ([(1, False)], [dict(baseline=inv('completed', 1, 1.0, 1.0, 1, True), linear=inv('completed', 1, 1.0, 1.0, 1, True), boost=inv('completed', 1, 1.0, 1.0, 1, True))]))]
        import report as R
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t); sched = S.make_schedule(['a', 'zz']); (t / 's.json').write_text(json.dumps(sched)); (t / 'jobs').mkdir()
            subprocess.run([sys.executable, str(HERE / 'report.py'), '--schedule', str(t / 's.json'), '--jobs', str(t / 'jobs'), '--out', str(t / 'out')], check=True, stdout=subprocess.DEVNULL)
            r = json.loads((t / 'out/report.json').read_text())
            self.assertEqual(r['solvers']['8']['job_outcomes'], dict(missing_record=2))


class SolutionCheckTests(unittest.TestCase):
    def test_feasibility_with_multiedge(self):
        with tempfile.TemporaryDirectory() as t:
            g = pathlib.Path(t) / 'g.graph'; g.write_text('a b\nb c\nc a\nc d\nc d\n')
            self.assertTrue(invoke.check_solution(g, '1\nc \n', reference=1)['feasible'])
            self.assertFalse(invoke.check_solution(g, '1\na \n')['feasible'])          # c-d double edge remains: 2-cycle
            self.assertFalse(invoke.check_solution(g, '2\nc c \n')['feasible'])        # duplicate id
            self.assertEqual(invoke.check_solution(g, '2\nc d \n', reference=1)['reference_verdict'], 'worse_than_reference')


class ModelTests(unittest.TestCase):
    def test_model_hashes(self):
        man = json.loads((HERE / 'models/MODELS.json').read_text())
        self.assertEqual(len(man['models']), 6)
        for key, d in man['models'].items():
            s, f = key.split('/')
            for name in ('model.json', 'model_meta.json'):
                if name in d:
                    self.assertEqual(hashlib.sha256((HERE / 'models' / s / f / name).read_bytes()).hexdigest(), d[name]['sha256'])
        sel = {'8/linear': 'lambda=0.1', '8/boost': 'depth=2,rounds=50', '5/linear': 'lambda=0.0001', '5/boost': 'depth=3,rounds=200',
               'LP/linear': 'lambda=0.01', 'LP/boost': 'depth=3,rounds=200'}
        self.assertEqual({k: v['config']['id'] for k, v in man['models'].items()}, sel)


@unittest.skipUnless(UPSTREAM, 'INTEGRATION_UPSTREAM not set')
class PrepareTests(unittest.TestCase):
    def test_edits_apply_once(self):
        import prepare
        with tempfile.TemporaryDirectory() as t:
            dest, touched = prepare.prepare(pathlib.Path(UPSTREAM) / 'src', pathlib.Path(t) / 'p')
            self.assertEqual(touched, sorted({r for r, _, _ in prepare.EDITS}))
            txt = (dest / 'solutions/SolutionVariants.h').read_text()
            self.assertEqual(txt.count('fvsb::caoSelect'), 1); self.assertEqual(txt.count('fvsb::chenSelect'), 1)
            self.assertEqual((dest / 'solutions/HalfIntBranching.cpp').read_text().count('fvsb::lpSelect'), 1)


if __name__ == '__main__':
    unittest.main()
