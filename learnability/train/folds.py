"""Public-graph identity audit and fixed graph-fold assignment (outcome-free, feature-free).

Audit scope (bounded; NOT a proof of non-isomorphism or of unrelatedness):
  1. raw content SHA-256 after CRLF->LF normalisation;
  2. canonical edge-multiset SHA-256 (edge endpoints sorted, edge list sorted, comments/blank lines dropped);
  3. 1-WL colour-refinement signature (initial colour = degree; at most 10 rounds or until the
     partition stops refining). Equal signatures are necessary, not sufficient, for isomorphism.
Graphs that agree on ANY of these are placed in one group (conservative: possible isomorphs stay
together). The pinned upstream documents no related-instance families, so no documented groups exist.
Only tests/pace-16open is read; the reserved hidden set is never opened.
"""
import hashlib
import json
import pathlib

SEED = 20261124
N_FOLDS = 5


def parse_graph(text):
    edges = []
    for line in text.replace('\r\n', '\n').split('\n'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        a, b = s.split()
        edges.append((a, b))
    return edges


def wl_signature(edges, rounds=10):
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b); adj.setdefault(b, []).append(a)
    colour = {v: str(len(n)) for v, n in adj.items()}
    n_classes = len(set(colour.values())); history = []
    for r in range(rounds):
        new = {v: hashlib.sha256((colour[v] + '|' + ','.join(sorted(colour[u] for u in adj[v]))).encode()).hexdigest()[:16] for v in adj}
        hist = sorted(new.values()); history.append(hashlib.sha256('\n'.join(hist).encode()).hexdigest())
        colour = new
        k = len(set(colour.values()))
        if k == n_classes:
            break
        n_classes = k
    return hashlib.sha256(('|'.join(history) + f'|V{len(adj)}|E{len(edges)}').encode()).hexdigest(), len(history)


def audit(graph_dir, graph_ids):
    graph_dir = pathlib.Path(graph_dir); rec = {}
    for g in graph_ids:
        raw = (graph_dir / f'{g}.graph').read_bytes().replace(b'\r\n', b'\n')
        edges = parse_graph(raw.decode('utf-8'))
        canon = sorted(tuple(sorted(e)) for e in edges)
        wl, wl_rounds = wl_signature(edges)
        rec[g] = dict(raw_lf_sha256=hashlib.sha256(raw).hexdigest(),
                      edge_multiset_sha256=hashlib.sha256('\n'.join(f'{a} {b}' for a, b in canon).encode()).hexdigest(),
                      wl_signature=wl, wl_rounds=wl_rounds, vertices=len({v for e in edges for v in e}), edges=len(edges))
    parent = {g: g for g in graph_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    matches = []
    for field in ('raw_lf_sha256', 'edge_multiset_sha256', 'wl_signature'):
        seen = {}
        for g in graph_ids:
            v = rec[g][field]
            if v in seen:
                matches.append(dict(kind=field, graphs=[seen[v], g])); a, b = find(seen[v]), find(g)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            else:
                seen[v] = g
    groups = {}
    for g in graph_ids:
        groups.setdefault(find(g), []).append(g)
    return rec, matches, sorted(sorted(v) for v in groups.values())


def assign_folds(groups, seed=SEED, k=N_FOLDS):
    """Groups in SHA-256 order of (seed, first graph id); each to the fold with fewest graphs (ties: lowest index)."""
    order = sorted(groups, key=lambda grp: hashlib.sha256(f'{seed}|fold|{grp[0]}'.encode()).hexdigest())
    sizes = [0] * k; fold_of = {}
    for grp in order:
        f = min(range(k), key=lambda i: (sizes[i], i))
        for g in grp:
            fold_of[g] = f
        sizes[f] += len(grp)
    return fold_of, sizes


def build_manifest(graph_dir, graph_ids, upstream_commit):
    rec, matches, groups = audit(graph_dir, graph_ids)
    fold_of, sizes = assign_folds(groups)
    body = dict(schema='fvs-learnability-folds-v1', seed=SEED, n_folds=N_FOLDS, upstream_commit=upstream_commit, graph_set='tests/pace-16open (100 public graphs)',
                audit_scope=__doc__.strip(), documented_related_groups='none documented in the pinned upstream (README lists solver variants only)',
                matches=matches, groups=groups, fold_sizes=sizes, folds={g: fold_of[g] for g in graph_ids}, graph_audit=rec,
                assignment_rule='groups ordered by sha256("<seed>|fold|<first graph id>"), each placed in the fold with the fewest graphs (ties -> lowest fold index); no outcome, feature or label is consulted')
    body['manifest_sha256'] = hashlib.sha256(json.dumps({k: body[k] for k in ('seed', 'n_folds', 'groups', 'folds')}, sort_keys=True).encode()).hexdigest()
    return body
