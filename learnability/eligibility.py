"""Eligible-candidate recomputation, exactly as the pinned staged/inventory.py (raw arrays).

8  (Sol8 / Graph::getMaxDegVWDouble): STATUS_NONE vertices tied for the maximum
   len(neighbours)+doubleNum, increasing local ID. Score = that weighted degree.
5  (ICBranchingSolution fallback / Graph::getMaxDegToUndeletable domain): every STATUS_NONE
   vertex, increasing local ID; requires stageHint false and empty branching_hints.
   Score = (adjacency entries with status 1, weighted degree).
LP (HalfIntBranching::solve2 neighbour branch): saved root's adjacency order filtered to
   STATUS_NONE, first occurrence kept; requires phase 2 and an active SAFE root. Score = weighted degree.
"""


class EligibilityError(ValueError):
    pass


def raw_weighted_degree(s, i):
    return len(s['neighbours'][i]) + s['doubleNum'][i]


def eligible_candidates(s):
    """Return (candidates, scores) recomputed from a decoded snapshot; raises EligibilityError."""
    status = s['status']; n = s['N']
    none = [i for i in range(n) if status[i] == 0]
    v = s['variant']
    if v == '8':
        if s['phase'] != 0:
            raise EligibilityError('Cao state is not a stageContinue (phase 0) decision')
        if not none:
            raise EligibilityError('no undecided vertex')
        best = max(raw_weighted_degree(s, i) for i in none)
        cands = [i for i in none if raw_weighted_degree(s, i) == best]
        scores = [raw_weighted_degree(s, i) for i in cands]
    elif v == '5':
        if s['phase'] != 0:
            raise EligibilityError('Chen state is not a stageContinue (phase 0) decision')
        if s['stageHint'] or s['branching_hints']:
            raise EligibilityError('Chen fallback requires exhausted hints (stageHint false, no hints left)')
        cands = none
        scores = [[sum(status[j] == 1 for j in s['neighbours'][i]), raw_weighted_degree(s, i)] for i in cands]
    elif v == 'LP':
        if s['phase'] != 2:
            raise EligibilityError('LP state is not a solve2 neighbour branch (phase 2)')
        r = s['root']
        if not 0 <= r < n or status[r] != 1:
            raise EligibilityError('LP root is not an active SAFE vertex')
        cands = list(dict.fromkeys(i for i in s['neighbours'][r] if status[i] == 0))
        scores = [raw_weighted_degree(s, i) for i in cands]
    else:
        raise EligibilityError(f'unknown variant {v}')
    return cands, scores


def classical_rank(scores, k):
    """Stage D's rank: 1 + number of candidates whose score is strictly greater (tuple order)."""
    key = lambda x: tuple(x) if isinstance(x, (list, tuple)) else (x,)
    return 1 + sum(key(x) > key(scores[k]) for x in scores)
