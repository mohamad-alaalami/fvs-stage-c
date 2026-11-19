"""Generate the full Stage C schedule from the verified checkpoint inventory.
Writes schedule.json and (in Actions) matrix outputs part1/part2 (GitHub caps a matrix at 256 jobs)."""
import csv, json, os, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = list(csv.DictReader((ROOT / 'records/local-checkpoint/dataset_inventory.csv').open()))
public = sorted(r['filename'][:-6] for r in rows if r['subset'] == 'pace-16open')
hidden = [r for r in rows if r['subset'] == 'pace16-hidden']
assert len(public) == 100 == len(set(public)) and len(hidden) == 130, (len(public), len(hidden))
pairs = [dict(graph=g, solver=s) for g in public for s in ['8', '5', 'LP']]
assert len(pairs) == 300 == len({(p['graph'], p['solver']) for p in pairs})
assert all((ROOT / 'records/local-checkpoint/dataset_inventory.csv').exists() and p['graph'].isdigit() for p in pairs)
out = dict(source='records/local-checkpoint/dataset_inventory.csv (subset pace-16open)', graphs=public, solvers=['8', '5', 'LP'],
           pair_count=len(pairs), hidden_graphs_reserved=len(hidden), part1=pairs[:150], part2=pairs[150:])
dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'schedule.json'
dest.write_text(json.dumps(out, indent=2) + '\n')
if os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('part1=' + json.dumps({'include': pairs[:150]}) + '\n'); f.write('part2=' + json.dumps({'include': pairs[150:]}) + '\n')
print(len(pairs), 'pairs;', len(public), 'public graphs; hidden reserved:', len(hidden))
