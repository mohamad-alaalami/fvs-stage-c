"""Held-out selection, selected-vs-original evaluation, graph aggregation, selection rule, bootstrap."""
import hashlib
import math

import numpy as np


class ScoreError(RuntimeError):
    pass


def select(scores, original):
    """argmax; exact ties -> original pivot if among maxima, else lowest archived ordinal."""
    if not all(math.isfinite(x) for x in scores):
        raise ScoreError('non-finite score')
    m = max(scores); tied = [i for i, x in enumerate(scores) if x == m]
    return original if original in tied else tied[0], len(tied)


def evaluate_state(state, selected):
    """Selected-vs-original outcome for one held-out state; never invents costs."""
    o = state.original; e = dict(state_id=state.state_id, graph_id=state.graph_id, state_index=state.state_index, sample_kind=state.sample_kind,
                                 selected=selected, original=o, agrees_with_original=selected == o, candidates=state.n,
                                 complete_compatible=state.complete_compatible())
    reasons = list(state.exclusion_reasons)
    if not state.valid[selected]: reasons.append(f'selected_{state.status[selected]}_or_invalid')
    if not state.valid[o]: reasons.append(f'original_{state.status[o]}_or_invalid')
    if not reasons and state.key[selected] != state.key[o]: reasons.append('environment_incompatible')
    if reasons:
        e.update(comparable=False, unresolved_reasons=reasons, selected_nodes=state.nodes[selected], original_nodes=state.nodes[o],
                 node_difference=None, ratio=None, outcome='unresolved', selection_cost=None, best_selected=None)
        return e
    sn, on = state.nodes[selected], state.nodes[o]
    e.update(comparable=True, unresolved_reasons=[], selected_nodes=sn, original_nodes=on, node_difference=on - sn,
             ratio=(sn / on) if on > 0 else None, outcome='win' if sn < on else ('tie' if sn == on else 'loss'))
    if e['complete_compatible']:
        e['selection_cost'] = math.log((1 + sn) / (1 + on)); e['best_selected'] = sn == min(state.nodes)
    else:
        e['selection_cost'] = None; e['best_selected'] = None
    return e


def graph_aggregate(evals, field='selection_cost'):
    """Mean of `field` within each graph (states pooled across folds), then equally across graphs."""
    per = {}
    for e in evals:
        if e.get(field) is not None:
            per.setdefault(e['graph_id'], []).append(e[field])
    gm = {g: sum(v) / len(v) for g, v in sorted(per.items())}
    return (sum(gm.values()) / len(gm) if gm else None), gm


def summarise(evals):
    n = len(evals); comp = [e for e in evals if e['comparable']]; sub = [e for e in evals if e['selection_cost'] is not None]
    agg, gm = graph_aggregate(evals)
    agg_cmp, _ = graph_aggregate([dict(e, comparable_log=(math.log((1 + e['selected_nodes']) / (1 + e['original_nodes'])) if e['comparable'] else None)) for e in evals], 'comparable_log')
    return dict(states=n, policy_agreement=sum(e['agrees_with_original'] for e in evals) / n if n else None,
                comparable_states=len(comp), unresolved_states=n - len(comp),
                wins=sum(e['outcome'] == 'win' for e in comp), ties=sum(e['outcome'] == 'tie' for e in comp), losses=sum(e['outcome'] == 'loss' for e in comp),
                total_node_difference_comparable=sum(e['node_difference'] for e in comp),
                selection_subset_states=len(sub), selection_subset_graphs=len(gm), selection_metric=agg,
                comparable_graph_mean_log_ratio=agg_cmp,
                best_candidate_rate=(sum(e['best_selected'] for e in sub) / len(sub)) if sub else None,
                unresolved_reason_counts=_count(r for e in evals for r in e['unresolved_reasons']))


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items()))


def choose(family, results):
    """results: list of dict(config=..., metric=float|None, valid=bool). Lower metric wins.
    Exact ties: linear -> larger lambda; boost -> fewer rounds, then smaller depth."""
    ok = [r for r in results if r['valid'] and r['metric'] is not None]
    if not ok:
        return None
    if family == 'linear':
        key = lambda r: (r['metric'], -r['config']['lambda'])
    else:
        key = lambda r: (r['metric'], r['config']['rounds'], r['config']['max_depth'])
    return min(ok, key=key)


def bootstrap(graph_values, n=2000, label='', seed=20261124):
    """Paired graph bootstrap of the equal-graph mean (graphs resampled with replacement)."""
    vals = np.array([graph_values[g] for g in sorted(graph_values)], dtype=np.float64)
    if len(vals) == 0:
        return None
    s = int.from_bytes(hashlib.sha256(f'{seed}|bootstrap|{label}'.encode()).digest()[:8], 'little')
    rng = np.random.Generator(np.random.PCG64(s))
    idx = rng.integers(0, len(vals), size=(n, len(vals)))
    means = vals[idx].mean(axis=1)
    return dict(resamples=n, graphs=len(vals), estimate=float(vals.mean()), ci95=[float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
                fraction_below_zero=float(np.mean(means < 0)), seed_label=label,
                note='descriptive development uncertainty conditional on this selection procedure; does not correct selection optimism')
