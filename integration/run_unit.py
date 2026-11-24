"""Run the integration unit tests and write unit_report.json. Usage: python integration/run_unit.py OUT_DIR"""
import io, json, pathlib, sys, unittest

out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
root = pathlib.Path(__file__).resolve().parent.parent
suite = unittest.defaultTestLoader.discover(str(root / 'integration/tests'), top_level_dir=str(root))
buf = io.StringIO(); res = unittest.TextTestRunner(stream=buf, verbosity=2).run(suite)
(out / 'unit_tests.txt').write_text(buf.getvalue(), encoding='utf-8')
rep = dict(check='unit_tests', tests=res.testsRun, failures=len(res.failures) + len(res.errors), skipped=len(res.skipped),
           pass_=res.wasSuccessful() and not res.skipped)
(out / 'unit_report.json').write_text(json.dumps(rep, indent=2) + '\n', encoding='utf-8')
print(buf.getvalue()[-2000:]); print(rep)
sys.exit(0 if rep['pass_'] else 1)
