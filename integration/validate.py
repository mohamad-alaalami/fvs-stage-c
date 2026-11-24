"""Combine the public acceptance reports into validation.json and VALIDATION.md (expected vs observed, pass/fail).

Usage: python integration/validate.py --reports DIR --build-record build_record.json --out DIR
Each check writes <name>_report.json; a missing report is a FAIL ('not run').
"""
import argparse, json, pathlib, sys

CHECKS = [
    ('replay_report.json', 'Replay of all saved public states through the integration code',
     lambda r: f"{r.get('observed_states')} states / {r.get('observed_candidates')} candidates", '6502 states / 71038 candidates; exact discrete agreement; exact selections'),
    ('baseline_report.json', 'Baseline equivalence vs pristine build and Stage C records',
     lambda r: f"{r.get('cases')} pairs {r.get('cases_by_solver')}", 'every Stage C pair completed with instrumented CPU <= 60 s; identical output, nodes, B/T/A, trace digest'),
    ('oracle_report.json', 'Exact oracle on generated small graphs + tests/simple',
     lambda r: f"{r.get('graphs')} graphs x 3 solvers x {len(r.get('policies', []))} policies", 'all completed, feasible, size = brute-force optimum; learned policies exercised'),
    ('suite_report.json', 'Fixed public correctness suite (incl. 003, optimum 10)',
     lambda r: f"{r.get('cases')} graph-solver cases x 4 policies", '34 graphs x 3 solvers; completed runs feasible and optimal'),
    ('live_report.json', 'Live decision states re-scored by the Python reference',
     lambda r: f"{(r.get('counts') or {}).get('states')} states ({(r.get('counts') or {}).get('after_departure')} after a departure, {(r.get('counts') or {}).get('component_subsolver')} in component subsolvers)", 'exact features, scores and selections, including post-departure states'),
    ('overhead_report.json', 'Instrumentation overhead and diagnostic timers',
     lambda r: f"{len(r.get('summary', []))} cases x {r.get('repetitions')} repetitions", '6 predefined cases measured'),
    ('fixture_report.json', 'Benchmark driver / retry / report exercise on public fixtures',
     lambda r: f"{sum(1 for v in (r.get('checks') or {}).values() if v)}/{len(r.get('checks') or {})} checks", 'all fixture checks true'),
    ('unit_report.json', 'Unit tests (schedule, report, model loading, tie rule)',
     lambda r: f"{r.get('tests')} tests, {r.get('failures')} failures", 'all pass'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reports', required=True); ap.add_argument('--build-record', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    reports = pathlib.Path(a.reports); out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    br = json.loads(pathlib.Path(a.build_record).read_text())
    rows = []; allok = True
    for name, title, observed, expected in CHECKS:
        hits = sorted(reports.rglob(name))
        if not hits:
            rows.append(dict(check=title, file=name, expected=expected, observed='not run', passed=False)); allok = False; continue
        r = json.loads(hits[0].read_text())
        ok = bool(r.get('pass_'))
        rows.append(dict(check=title, file=str(hits[0].relative_to(reports).as_posix()), expected=expected, observed=observed(r), passed=ok)); allok &= ok
    res = dict(schema='integration-v1-validation', all_passed=allok, checks=rows, build_id=br['build_id'], experiment_commit=br['experiment_commit'],
               executables=br['executables'], model_hashes=br['model_hashes'], github_run_id=br.get('github_run_id'))
    (out / 'validation.json').write_text(json.dumps(res, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    md = ['# Integration-v1 public validation', '', f"Build `{br['build_id']}`, experiment commit `{br['experiment_commit']}`, run {br.get('github_run_id')}.", '',
          f"**Overall: {'PASS' if allok else 'FAIL'}**", '', '| Check | Expected | Observed | Result |', '|---|---|---|---|']
    for r in rows:
        md.append(f"| {r['check']} | {r['expected']} | {r['observed']} | {'PASS' if r['passed'] else 'FAIL'} |")
    md += ['', '## Executables', ''] + [f"- `{k}` {v['sha256']}" for k, v in sorted(br['executables'].items())]
    md += ['', '## Frozen models (SHA-256)', ''] + [f"- `{k}` {v}" for k, v in sorted(br['model_hashes'].items())]
    (out / 'VALIDATION.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
