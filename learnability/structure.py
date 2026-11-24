"""Active-graph structure of a decoded snapshot and its integrity validation.

Status constants are those of the pinned upstream src/lib/Graph.h:
STATUS_IN_SOLUTION=-1, STATUS_DELETED=-2, STATUS_NONE=0 (undecided), STATUS_IN_SAFE=1 (undeletable).
Active vertices have status 0 or 1. N(v) is the set of DISTINCT active vertices listed in v's
adjacency array; an entry's multiplicity is 2 when its neighDouble flag is set, else 1.
Inactive vertices' buffers are ignored (pureDeleteVertex clears only the deleted vertex's own lists).
Validation never alters the structure; violations are reported, not repaired.
"""
STATUS_IN_SOLUTION, STATUS_DELETED, STATUS_NONE, STATUS_SAFE = -1, -2, 0, 1
ACTIVE = (STATUS_NONE, STATUS_SAFE)


def validate_active_adjacency(status, neighbours, neigh_double, double_num, pos_at_neigh):
    """Return a list of integrity error strings (empty when the active adjacency is valid).

    Checks for every active vertex v and adjacency entry i (u = neighbours[v][i]):
    u in range, u active, u != v (no self-loop), no duplicate u, reciprocity (v listed at
    neighbours[u][pos_at_neigh[v][i]]), equal double flags on both sides, and
    double_num[v] == number of flagged entries."""
    n = len(status); errors = []
    def err(msg):
        if len(errors) < 50:
            errors.append(msg)
        elif len(errors) == 50:
            errors.append('... further integrity errors truncated')
    for v in range(n):
        if status[v] not in ACTIVE:
            continue
        seen = set(); flagged = 0
        nv = neighbours[v]; fv = neigh_double[v]; pv = pos_at_neigh[v]
        for i, u in enumerate(nv):
            if not 0 <= u < n:
                err(f'v{v}: neighbour index {u} out of range'); continue
            if u == v:
                err(f'v{v}: self-loop entry'); continue
            if status[u] not in ACTIVE:
                err(f'v{v}: adjacency references inactive vertex {u} (status {status[u]})'); continue
            if u in seen:
                err(f'v{v}: duplicate adjacency entry {u}')
            seen.add(u)
            flagged += bool(fv[i])
            j = pv[i]
            if not (0 <= j < len(neighbours[u]) and neighbours[u][j] == v):
                err(f'v{v}: entry {u} not reciprocated at posAtNeigh={j}'); continue
            if bool(neigh_double[u][j]) != bool(fv[i]):
                err(f'v{v}: double flag of edge to {u} differs between endpoints')
        if double_num[v] != sum(bool(f) for f in fv):
            err(f'v{v}: doubleNum {double_num[v]} != flagged entries {sum(bool(f) for f in fv)}')
        if flagged != sum(bool(f) for f in fv):
            err(f'v{v}: flagged entries to non-active or invalid neighbours')
    return errors
