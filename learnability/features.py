"""Frozen extraction feature schema v1 (pure functions; decision-time inputs only).

compute_features() receives ONLY decoded pre-decision structure (status, adjacency, double
flags, size_cap, |X|), the eligible candidate IDs and (LP) the saved root. It has no access to
outcomes, timings, environments, sampling metadata, graph files or optima, and it never
mutates its inputs or runs reductions.

Complexity: O(allocated N + active adjacency entries + sum of candidate degrees) per state,
plus O(deg(root)) for the LP root-neighbour set. This is a complexity statement, not a live
runtime guarantee.
"""
from .structure import ACTIVE, STATUS_NONE, STATUS_SAFE

FEATURE_COLUMNS = (
    'f_cand_none_neighbors', 'f_cand_safe_neighbors', 'f_cand_double_edges',
    'f_nbr_none_wdeg_min', 'f_nbr_none_wdeg_mean', 'f_nbr_none_wdeg_max',
    'f_state_none_vertices', 'f_state_safe_vertices', 'f_state_distinct_edges', 'f_state_double_edges',
    'f_state_remaining_threshold', 'f_state_candidate_count', 'f_lp_root_common_neighbors',
)


def active_neighbourhoods(status, neighbours, neigh_double):
    """{v: {u: is_double}} for active v over DISTINCT active neighbours u (u != v)."""
    n = len(status); out = {}
    for v in range(n):
        if status[v] not in ACTIVE:
            continue
        d = {}
        for u, f in zip(neighbours[v], neigh_double[v]):
            if 0 <= u < n and u != v and status[u] in ACTIVE:
                d[u] = d.get(u, False) or bool(f)
        out[v] = d
    return out


def compute_features(solver, status, neighbours, neigh_double, size_cap, x_size, candidates, root=None):
    """Return (state_features, per_candidate_features, diagnostics) for one saved state.

    per_candidate_features is a list aligned with `candidates` (order preserved)."""
    nb = active_neighbourhoods(status, neighbours, neigh_double)
    wdeg = {v: len(d) + sum(d.values()) for v, d in nb.items()}
    none_count = sum(1 for v in nb if status[v] == STATUS_NONE)
    safe_count = sum(1 for v in nb if status[v] == STATUS_SAFE)
    degree_sum = sum(len(d) for d in nb.values())
    double_sum = sum(sum(d.values()) for d in nb.values())
    state = dict(
        f_state_none_vertices=none_count, f_state_safe_vertices=safe_count,
        # Each unordered active pair appears once from each endpoint in a reciprocal adjacency;
        # an odd sum signals an integrity violation, which validation reports separately.
        f_state_distinct_edges=degree_sum // 2, f_state_double_edges=double_sum // 2,
        f_state_remaining_threshold=size_cap - x_size,
        f_state_candidate_count=len(candidates),
    )
    diagnostics = dict(degree_sum=degree_sum, double_sum=double_sum, weighted_degree_sum=sum(wdeg.values()))
    root_set = set(nb.get(root, {})) if solver == 'LP' and root is not None else None
    rows = []
    for v in candidates:
        d = nb.get(v, {})
        none_n = [u for u in d if status[u] == STATUS_NONE]
        safe_n = sum(1 for u in d if status[u] == STATUS_SAFE)
        dbl = sum(d.values())
        ws = [wdeg[u] for u in none_n]
        row = dict(state)
        row.update(
            f_cand_none_neighbors=len(none_n), f_cand_safe_neighbors=safe_n, f_cand_double_edges=dbl,
            f_nbr_none_wdeg_min=float(min(ws)) if ws else 0.0,
            f_nbr_none_wdeg_mean=(sum(ws) / len(ws)) if ws else 0.0,  # integer sum, then float64 division
            f_nbr_none_wdeg_max=float(max(ws)) if ws else 0.0,
            f_lp_root_common_neighbors=(len(set(d) & root_set) if root_set is not None else None),
            diag_cand_distinct_degree=len(none_n) + safe_n,
            diag_cand_weighted_degree=len(none_n) + safe_n + dbl,
        )
        rows.append(row)
    return state, rows, dict(diagnostics, wdeg=wdeg)
