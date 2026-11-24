"""Independent reference implementation of feature schema v1, for validation only.

Built from a different representation: an explicit set of unordered vertex pairs
(frozensets) with a separate set of double pairs, collected from EVERY active endpoint's
adjacency entries. Degrees and neighbourhoods are derived from the pair sets rather than
from per-vertex adjacency dictionaries, and the edge count is the size of the pair set
(not a halved degree sum). It shares no code with features.py.
"""


def reference_features(solver, status, neighbours, neigh_double, size_cap, x_size, candidates, root=None):
    active = {v for v, s in enumerate(status) if s == 0 or s == 1}
    none_set = {v for v in active if status[v] == 0}
    safe_set = {v for v in active if status[v] == 1}
    pairs = set(); doubles = set()
    for v in sorted(active):
        for u, flag in zip(neighbours[v], neigh_double[v]):
            if u in active and u != v:
                e = frozenset((u, v))
                pairs.add(e)
                if flag:
                    doubles.add(e)
    incident = {v: set() for v in active}
    for e in pairs:
        a, b = tuple(e)
        incident[a].add(b); incident[b].add(a)
    def weighted(v):
        return len(incident[v]) + sum(1 for u in incident[v] if frozenset((u, v)) in doubles)
    out = []
    for v in candidates:
        nbrs = incident.get(v, set())
        und = nbrs & none_set
        w = sorted(weighted(u) for u in und)
        row = {
            'f_cand_none_neighbors': len(und),
            'f_cand_safe_neighbors': len(nbrs & safe_set),
            'f_cand_double_edges': sum(1 for u in nbrs if frozenset((u, v)) in doubles),
            'f_nbr_none_wdeg_min': float(w[0]) if w else 0.0,
            'f_nbr_none_wdeg_mean': (sum(w) / len(w)) if w else 0.0,
            'f_nbr_none_wdeg_max': float(w[-1]) if w else 0.0,
            'f_state_none_vertices': len(none_set),
            'f_state_safe_vertices': len(safe_set),
            'f_state_distinct_edges': len(pairs),
            'f_state_double_edges': len(doubles),
            'f_state_remaining_threshold': size_cap - x_size,
            'f_state_candidate_count': len(candidates),
            'f_lp_root_common_neighbors': len(nbrs & incident.get(root, set())) if solver == 'LP' else None,
        }
        out.append(row)
    return out
