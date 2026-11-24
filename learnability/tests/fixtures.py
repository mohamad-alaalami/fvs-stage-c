"""Test fixtures: hand-built multigraph states, a StageC1 encoder mirroring the pinned decoder's
field order, and a miniature pinned dataset (experiment tree, Stage C and Stage D records)."""
import hashlib
import json
import pathlib
import struct
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[2]          # the experiment-commit checkout
PINNED_DECODER = ROOT / 'stagec' / 'snapshot.py'


def make_graph(status, edges, stale=None):
    """edges: list of (u, v, is_double). stale: {inactive v: [entries]} left in inactive buffers."""
    n = len(status)
    nb = [[] for _ in range(n)]; nd = [[] for _ in range(n)]; pos = [[] for _ in range(n)]
    for u, v, d in edges:
        pu, pv = len(nb[u]), len(nb[v])
        nb[u].append(v); nd[u].append(d); pos[u].append(pv)
        nb[v].append(u); nd[v].append(d); pos[v].append(pu)
    for v, entries in (stale or {}).items():
        for u in entries:
            nb[v].append(u); nd[v].append(False); pos[v].append(0)
    dn = [sum(x) for x in nd]
    return dict(status=list(status), neighbours=nb, neighDouble=nd, posAtNeigh=pos, doubleNum=dn)


def full_state(variant, g, pivot, root=-1, phase=0, size_cap=5, X=(), sol=(), solFound=True, hints=(), stageHint=False,
               depth=3, solver_depth=1, isSub=False, names=None):
    n = len(g['status'])
    s = dict(magic='STAGEC1', variant=variant, depth=depth, phase=phase, pivot=pivot, root=root, N=n, M=7, deleted=0, changeInU=False,
             oldNumbers=list(range(n)), X=list(X), selfLoops=[], deg2ToReduce=[], vis=[0] * n, ccNr=[0] * n, ccVertices=[],
             fuRepr=[-1] * n, fuWeight=[1] * n, stageNames=names or [str(100 + i) for i in range(n)], solFound=solFound,
             branching_hints=list(hints), sol=list(sol), isSub=isSub, solver_depth=solver_depth, size_cap=size_cap, stageHint=stageHint)
    s.update(g)
    if variant == '8':
        s['br2'] = 0
    if variant == 'LP':
        s['kernelize_switch'] = True
    return s


def encode(s):
    """Inverse of the pinned stagec/snapshot.py decode()."""
    out = bytearray()
    def string(x):
        b = x.encode(); out.extend(struct.pack('<Q', len(b))); out.extend(b)
    def vec(xs, kind):
        out.extend(struct.pack('<Q', len(xs)))
        for x in xs:
            if kind == 'int': out.extend(struct.pack('<i', x))
            elif kind == 'bool': out.extend(struct.pack('<?', x))
            elif kind == 'string': string(x)
            else: vec(x, kind[0])
    string(s['magic']); string(s['variant'])
    for f in ('depth', 'phase', 'pivot', 'root', 'N', 'M', 'deleted'):
        out.extend(struct.pack('<i', s[f]))
    out.extend(struct.pack('<?', s['changeInU']))
    for f, kind in [('neighbours', ['int']), ('neighDouble', ['bool']), ('doubleNum', 'int'), ('posAtNeigh', ['int']), ('status', 'int'),
                    ('oldNumbers', 'int'), ('X', 'int'), ('selfLoops', 'int'), ('deg2ToReduce', 'int'), ('vis', 'int'), ('ccNr', 'int'),
                    ('ccVertices', ['int']), ('fuRepr', 'int'), ('fuWeight', 'int'), ('stageNames', 'string')]:
        vec(s[f], kind)
    out.extend(struct.pack('<?', s['solFound'])); vec(s['branching_hints'], 'int'); vec(s['sol'], 'int'); out.extend(struct.pack('<?', s['isSub']))
    out.extend(struct.pack('<i', s['solver_depth'])); out.extend(struct.pack('<i', s['size_cap'])); out.extend(struct.pack('<?', s['stageHint']))
    if s['variant'] == '8': out.extend(struct.pack('<i', s['br2']))
    if s['variant'] == 'LP': out.extend(struct.pack('<?', s['kernelize_switch']))
    return bytes(out)


def hand_graph():
    """0..7: statuses N N U N X D N N; edges 0=1 (double), 0-2, 1-2, 0-3, 3-7; vertex 6 isolated active;
    vertex 4 (in solution) keeps a stale buffer entry that must be ignored."""
    status = [0, 0, 1, 0, -1, -2, 0, 0]
    return make_graph(status, [(0, 1, True), (0, 2, False), (1, 2, False), (0, 3, False), (3, 7, False)], stale={4: [0]})


def cao_state():
    """Valid Cao decision: undecided 0..3 with weighted degrees 3,3,2,3 -> candidates [0,1,3]."""
    status = [0, 0, 0, 0, 1, -2]
    g = make_graph(status, [(0, 1, True), (0, 2, False), (1, 3, False), (3, 4, True)])
    return full_state('8', g, pivot=0, size_cap=4, X=[], sol=[0, 1, 2, 3], depth=2, solver_depth=1)


def lp_state():
    """Valid LP solve2 neighbour branch: root 4 (SAFE); undecided neighbours in adjacency order 2,0,3."""
    status = [0, 0, 0, 0, 1, -1]
    g = make_graph(status, [(4, 2, False), (4, 0, False), (4, 3, False), (0, 1, False), (1, 2, True), (0, 3, False), (2, 3, False)])
    return full_state('LP', g, pivot=2, root=4, phase=2, size_cap=4, X=[5], sol=[0, 1, 2, 5], depth=4, solver_depth=0)


# ---------------------------------------------------------------- miniature pinned dataset
def _sha(b): return hashlib.sha256(b).hexdigest()
def _fnv(b):
    h = 14695981039346656037
    for x in b: h = ((h ^ x) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return str(h)


def build_dataset(base, mutate=None):
    """Write experiment/, stagec/ and staged/ trees for two states (one Cao, one LP).

    mutate(kind, obj) may alter index/records before writing: kind in {'index','records'}."""
    from learnability.eligibility import eligible_candidates, classical_rank
    base = pathlib.Path(base)
    exp, scr, sdr = base / 'experiment', base / 'stagec', base / 'staged'
    for d in (exp / 'staged', exp / 'stagec', exp / 'full'):
        d.mkdir(parents=True, exist_ok=True)
    (exp / 'stagec' / 'snapshot.py').write_bytes(PINNED_DECODER.read_bytes())
    for rel in ('staged/PROTOCOL.md', 'staged/inventory.py', 'staged/run.py', 'staged/report.py', 'staged/continuation.cpp.inc', 'full/PROTOCOL.md', 'full/RESULTS.md'):
        (exp / rel).write_text('fixture\n')
    states = []; native = []
    for graph, st in (('095', cao_state()), ('014', lp_state())):
        variant = st['variant']; run = f'20261120T000000Z-fixture-{graph}-{variant}-instrumented'
        meta_rel = f'runs/44639720515/pairs/{graph}-{variant}/attempt-1/invocations/{run}/samples.json'
        d = scr / meta_rel; d.parent.mkdir(parents=True, exist_ok=True)
        blob = encode(st); cands, scores = eligible_candidates(st); cb = struct.pack('<' + 'i' * len(cands), *cands)
        ev = dict(phase='cao_max_degree' if variant == '8' else 'lp_neighbor', depth=st['depth'], solver_depth=st['solver_depth'], component_subsolver=st['isSub'],
                  local_pivot=st['pivot'], original_pivot=st['stageNames'][st['pivot']], root=None if variant == '8' else st['stageNames'][st['root']],
                  candidate_count=len(cands), pivot_eligible=True, T=True, A=True)
        sample = dict(kind='first_A', slot=-1, sequence=7, event_id=f'{run}:7', a_index=1, offset=0, state_bytes=len(blob), candidates_offset=len(blob),
                      candidate_count=len(cands), state_fnv=_fnv(blob), event=ev, continuation=dict(complete=True, trace_count=3, trace_digest='11', final_state_hash='22'))
        packed = zlib.compress(blob + cb)
        d.write_text(json.dumps(dict(variant=variant, graph=f'pace-16open/{graph}.graph', samples=[sample])))
        d.with_name('samples.bin.zz').write_bytes(packed)
        states.append(dict(state_id=sample['event_id'], graph=graph, solver=variant, event=ev, metadata_path=meta_rel, packed_sha256=_sha(packed),
                           snapshot_sha256=_sha(blob), candidate_list_sha256=_sha(cb), sample=sample, candidates=cands,
                           candidate_labels=[st['stageNames'][c] for c in cands], scores=scores,
                           initial_incumbent=dict(size_cap=st['size_cap'], solFound=st['solFound'], sol=st['sol']), snapshot_N=st['N']))
        native.append(dict(metadata_path=meta_rel, checks=[dict(sequence=7, ok=True)]))
    chunks = [[[0, c] for c in states[0]['candidates']], [[1, c] for c in states[1]['candidates']]]
    index = dict(stage_c_run='44639720515', records_commit='eece4cfe803a97c47ca178c14caa6b71b1e962c3',
                 stage_c_experiment_commit='3244862ea2905ce24c811b962084c2b8a13310bd', build_id='fixture', states=states, chunks=chunks)
    if mutate: mutate('index', index)
    ib = json.dumps(index).encode()
    (exp / 'staged' / 'index.json.zz').write_bytes(zlib.compress(ib))
    (exp / 'staged' / 'validation.json.zz').write_bytes(zlib.compress(json.dumps(native).encode()))
    records = {}
    for ci, arms in enumerate(chunks):
        out = []
        for si, v in arms:
            s = states[si]; k = s['candidates'].index(v); orig = v == s['event']['local_pivot']
            meas = dict(status='completed', candidate_local_id=v, original_local_id=s['event']['local_pivot'], initial_incumbent=s['initial_incumbent'],
                        final_incumbent=dict(size_cap=s['initial_incumbent']['size_cap'] - 1, solFound=True, sol=[0]), total_nodes=5 + k, branching_decisions=3,
                        root_decisions=1, continuation_cpu_s=0.0, continuation_wall_s=0.001, setup_cpu_s=0.0, parent_overhead_cpu_s=0.0, parent_overhead_wall_s=0.0001,
                        children=[dict(order=1, status='completed', nodes=3 + k, branching_decisions=1), dict(order=2, status='completed', nodes=2, branching_decisions=1)],
                        nodes_reconcile=True, branches_reconcile=True)
            out.append(dict(run_id=f'uuid-{si}-{v}', state_id=s['state_id'], graph=s['graph'], solver=s['solver'], phase=s['event']['phase'],
                            component_subsolver=s['event']['component_subsolver'], snapshot_sha256=s['snapshot_sha256'], candidate_list_sha256=s['candidate_list_sha256'],
                            candidate_local_id=v, candidate_id=s['candidate_labels'][k], original_pivot=orig, classical_score=s['scores'][k],
                            classical_rank=classical_rank(s['scores'], k), initial_incumbent=s['initial_incumbent'], command=['x'], command_line='x',
                            executable_sha256='e' * 64, source_hashes={'a.cpp': 'f' * 64}, experiment_commit='4cf65df9de3af1aacbece3820e2986c0fd2b5620',
                            environment=dict(cpu='CPU A', os='Windows', image='img 1', runner='r1'), cpu_budget_s=10, status='completed', counts_source='final',
                            exit_code=0, cpu_s=0.0, wall_s=0.01, driver_wall_s=0.02, peak_memory_bytes=4096, measurement=meas, finalization_cpu_s=0.0,
                            process_wall_outside_continuation_s=0.009, continuation=dict(complete=True, trace_count=3, trace_digest='11', final_state_hash='22') if orig else dict(complete=True, trace_count=9, trace_digest='x', final_state_hash='y'),
                            original_reproduction='pass' if orig else 'not_original', state_index=si))
        records[str(ci)] = out
    if mutate: mutate('records', records)
    for ci, out in records.items():
        d = sdr / 'runs' / '45059940845' / 'chunks' / ci / 'attempt-1'; d.mkdir(parents=True, exist_ok=True)
        (d / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in out), newline='\n')
        counts = {}
        for r in out: counts[r['status']] = counts.get(r['status'], 0) + 1
        (d / 'summary.json').write_text(json.dumps(dict(arms=len(out), status_counts=counts)))
        (d / 'schedule.json').write_text(json.dumps(dict(chunk=int(ci), arms=[[si, v, 10] for si, v in chunks[int(ci)]], index_sha256=_sha(ib))))
        (d / 'environment.json').write_text(json.dumps(dict(cpu='CPU A')))
    rep = sdr / 'runs' / '45059940845' / 'report' / 'attempt-1'; rep.mkdir(parents=True, exist_ok=True)
    total = sum(len(v) for v in records.values())
    arms = {}
    for out in records.values():
        for r in out:
            if any(r['state_id'] == s['state_id'] and r['candidate_local_id'] in s['candidates'] for s in states):
                arms[r['state_id']] = arms.get(r['state_id'], 0) + 1
    (rep / 'REPORT.md').write_text(f'# Stage D report\n\nIndexed states: {len(states)}. Scheduled arms: 6. Recorded invocations (including retries): {total}.\n')
    (rep / 'states.json').write_text(json.dumps([dict(state_id=s['state_id'], candidates=len(s['candidates']), recorded_arms=arms.get(s['state_id'], 0)) for s in states]))
    for name in ('per_graph.json', 'per_solver.json', 'retries_requiring_resolution.json'):
        (rep / name).write_text('{}')
    return exp, scr, sdr, index
