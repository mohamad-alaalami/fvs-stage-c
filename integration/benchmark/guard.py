"""Reserved-benchmark guard: the given public validation run passed for THIS commit and its build is from it.
Usage: python integration/benchmark/guard.py <results/runs/VALIDATION_RUN> <commit sha>"""
import glob, json, sys
run, sha = sys.argv[1], sys.argv[2]
vals = sorted(glob.glob(f'{run}/public-validation/attempt-*/validation/validation.json'))
assert vals, 'no public validation record for that run'
assert any((v := json.load(open(p)))['all_passed'] and v['experiment_commit'] == sha for p in vals), 'validation did not pass for this commit'
rec = json.load(open(f'{run}/build/attempt-1/build_record.json'))
assert rec['experiment_commit'] == sha, 'validated build is from another commit'
print('approved; validated build', rec['build_id'])
