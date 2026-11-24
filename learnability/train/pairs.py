"""Strict preference pairs per state, deterministic SHA-256 sampling, and graph/state weights.

Pairs exist only between two VALID candidates (data.candidate_valid) of a non-excluded state that
share a comparability key, with strictly different exact node totals; oriented better -> worse
(fewer nodes = better). Equal totals give no pair. Censored, missing, incompatible or unresolved
candidates give no pair; nothing is imputed.

Canonical order of a state's strict pairs (used for unranking without materialising them):
compat groups in sorted key order; inside a group candidates sorted by (exact_nodes, ordinal) and
split into equal-value blocks; pairs (p, q) with p before q's block, by p position then q position.
If a state has more than CAP strict pairs, CAP indices are drawn uniformly without replacement by
Floyd's algorithm driven by SHA-256(seed|solver|state_id|counter) with rejection sampling.
"""
import bisect
import hashlib

SEED = 20261124
CAP = 4096


class _Rng:
    def __init__(self, solver, state_id, seed=SEED):
        self.base = hashlib.sha256(f'{seed}|pairs|{solver}|{state_id}'.encode()).digest(); self.counter = 0

    def below(self, n):
        limit = (1 << 64) // n * n
        while True:
            x = int.from_bytes(hashlib.sha256(self.base + self.counter.to_bytes(8, 'little')).digest()[:8], 'little'); self.counter += 1
            if x < limit:
                return x % n


def floyd_sample(n, k, rng):
    s = set()
    for j in range(n - k, n):
        t = rng.below(j + 1)
        s.add(j if t in s else t)
    return sorted(s)


class _Group:
    """One compat group: ordinals sorted by (nodes, ordinal); cum[p] = strict pairs with first index < p."""
    def __init__(self, ordinals, nodes):
        self.order = sorted(ordinals, key=lambda i: (nodes[i], i)); vals = [nodes[i] for i in self.order]; m = len(vals)
        self.block_end = [0] * m
        # block_end[p] = first position with a strictly larger value than vals[p]
        for p in range(m - 1, -1, -1):
            if p + 1 < m and vals[p + 1] == vals[p]:
                self.block_end[p] = self.block_end[p + 1]
            else:
                self.block_end[p] = p + 1
        self.cum = [0]
        for p in range(m):
            self.cum.append(self.cum[-1] + (m - self.block_end[p]))
        self.total = self.cum[-1]

    def unrank(self, idx):
        p = bisect.bisect_right(self.cum, idx) - 1
        q = self.block_end[p] + (idx - self.cum[p])
        return self.order[p], self.order[q]


def state_pairs(state, cap=CAP):
    """Returns (pairs [(better, worse)], strict_total, info)."""
    groups = state.valid_groups()
    gs = [_Group(groups[k], state.nodes) for k in sorted(groups, key=repr)]
    gs = [g for g in gs if g.order]
    total = sum(g.total for g in gs)
    info = dict(valid_candidates=sum(len(g.order) for g in gs), compat_groups=len(gs), strict_pairs=total)
    if total == 0:
        return [], 0, info
    offsets = [0]
    for g in gs:
        offsets.append(offsets[-1] + g.total)
    if total <= cap:
        idxs = range(total); info['sampled'] = False
    else:
        idxs = floyd_sample(total, cap, _Rng(state.solver, state.state_id)); info['sampled'] = True
    out = []
    for idx in idxs:
        gi = bisect.bisect_right(offsets, idx) - 1
        out.append(gs[gi].unrank(idx - offsets[gi]))
    return out, total, info


def pair_weights(state_pairs_by_index, graph_of_state):
    """w = 1 / (G * S_g * P_s) over states with >=1 retained pair. Returns {state_index: weight per pair}."""
    informative = {si: len(p) for si, p in state_pairs_by_index.items() if p}
    per_graph = {}
    for si in informative:
        per_graph.setdefault(graph_of_state[si], []).append(si)
    G = len(per_graph)
    return {si: 1.0 / (G * len(per_graph[graph_of_state[si]]) * informative[si]) for si in informative}, G
