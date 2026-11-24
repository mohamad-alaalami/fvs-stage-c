"""Aggregate CV, selection, final refits and ablation into results.json and REPORT.md (descriptive)."""
import gzip
import json
import pathlib

from . import evaluate as E

SOLVERS = ('8', '5', 'LP'); FAMILIES = ('linear', 'boost')


def _j(p):
    return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))


def _evals(p):
    with gzip.open(p, 'rt', encoding='utf-8') as f:
        return [json.loads(l) for l in f]


def write_report(root, out, frozen):
    from .run import configs, config_result
    out.mkdir(parents=True, exist_ok=True)
    cfg = _j(frozen / 'config.json'); sel = _j(root / 'selection' / 'selection.json'); prep = _j(root / 'prepare' / 'prepare.json')
    fits = []; results = dict(experiment=cfg['experiment'], extraction_id=cfg['extraction_id'], coverage=prep['coverage'], per=dict())
    for s in SOLVERS:
        for fam in FAMILIES:
            key = f'{s}/{fam}'; entry = dict(configs=[])
            for c in configs(fam):
                cdir = root / 'cv' / s / fam / c['id']
                for k in range(5):
                    st = _j(cdir / f'fold{k}' / 'fit_status.json')
                    fits.append(dict(kind='main_cv', solver=s, family=fam, config=c['id'], fold=k, ok=st['ok'], wall_s=st.get('wall_s'), cpu_s=st.get('cpu_s'),
                                     failure=st.get('failure'), converged=(st.get('convergence') or {}).get('converged'), iterations=(st.get('convergence') or {}).get('iterations'),
                                     grad_inf_norm=(st.get('convergence') or {}).get('grad_inf_norm'), retained_pairs=st.get('retained_pairs'), contributing_graphs=st.get('contributing_graphs')))
                r, _ = config_result(cdir); entry['configs'].append(dict(config=c, valid=r['valid'], metric=r['metric'], summary=r['summary'], per_fold=r['per_fold']))
            chosen = sel[key]['selected']; entry['selected'] = chosen
            if chosen:
                cdir = root / 'cv' / s / fam / chosen['id']
                r, ev = config_result(cdir)
                entry['selected_summary'] = r['summary']; entry['selected_per_graph'] = r['per_graph']
                entry['bootstrap_selection_metric'] = E.bootstrap(r['per_graph'], label=f'{key}|selection')
                _, cmp_g = E.graph_aggregate([dict(e, cl=(__import__('math').log((1 + e['selected_nodes']) / (1 + e['original_nodes'])) if e['comparable'] else None)) for e in ev], 'cl')
                entry['bootstrap_comparable_log_ratio'] = E.bootstrap(cmp_g, label=f'{key}|comparable')
                with gzip.open(out / f'selected_states_{s}_{fam}.jsonl.gz', 'wt', encoding='utf-8', newline='\n') as f:
                    for e in sorted(ev, key=lambda e: e['state_index']):
                        f.write(json.dumps(e, sort_keys=True) + '\n')
                fdir = root / 'final' / s / fam
                fst = _j(fdir / 'final' / 'fit_status.json')
                fits.append(dict(kind='final_refit', solver=s, family=fam, config=chosen['id'], fold=None, ok=fst['ok'], wall_s=fst.get('wall_s'), cpu_s=fst.get('cpu_s'),
                                 failure=fst.get('failure'), converged=(fst.get('convergence') or {}).get('converged')))
                entry['final'] = dict(ok=fst['ok'], retained_pairs=fst.get('retained_pairs'), contributing_graphs=fst.get('contributing_graphs'), convergence=fst.get('convergence'))
                ab_ok = True; ab_ev = []
                for k in range(5):
                    ast = _j(fdir / 'ablation' / f'fold{k}' / 'fit_status.json'); ab_ok &= ast['ok']
                    fits.append(dict(kind='ablation', solver=s, family=fam, config=chosen['id'], fold=k, ok=ast['ok'], wall_s=ast.get('wall_s'), cpu_s=ast.get('cpu_s'),
                                     failure=ast.get('failure'), converged=(ast.get('convergence') or {}).get('converged')))
                    ab_ev += _evals(fdir / 'ablation' / f'fold{k}' / 'evals.jsonl.gz')
                asum = E.summarise(ab_ev); _, agm = E.graph_aggregate(ab_ev)
                common = sorted(set(agm) & set(r['per_graph']))
                entry['ablation'] = dict(valid=ab_ok, summary=asum, metric=asum['selection_metric'] if ab_ok else None,
                                         paired_graph_difference_main_minus_ablation=E.bootstrap({g: r['per_graph'][g] - agm[g] for g in common}, label=f'{key}|ablation'),
                                         note='development diagnostic with the main selected hyperparameters; not a confirmatory feature-effect estimate')
            results['per'][key] = entry
    results['fits'] = dict(total=len(fits), ok=sum(f['ok'] for f in fits), failed=[f for f in fits if not f['ok']],
                           by_kind={k: sum(f['kind'] == k for f in fits) for k in ('main_cv', 'final_refit', 'ablation')},
                           cpu_s_total=sum(f['cpu_s'] or 0 for f in fits), wall_s_total=sum(f['wall_s'] or 0 for f in fits))
    (out / 'fits.json').write_text(json.dumps(fits, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (out / 'results.json').write_text(json.dumps(results, indent=1, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    _markdown(out, results, cfg)


def _f(x, d=4):
    return '-' if x is None else (f'{x:.{d}f}' if isinstance(x, float) else str(x))


def _markdown(out, R, cfg):
    L = [f"# Offline learnability results ({R['experiment']})", '', f"Extraction `{R['extraction_id']}`. Development (cross-validated) results; NOT an unbiased final test. "
         'No solver was run; nothing here measures complete-solver performance.', '',
         f"Fits: {R['fits']['ok']}/{R['fits']['total']} ok ({json.dumps(R['fits']['by_kind'])}); total fit CPU {R['fits']['cpu_s_total']:.0f} s.", '',
         '## Selection metric by configuration', '', 'Metric: graph-aggregated mean of log((1+selected nodes)/(1+original nodes)) on the fixed complete-compatible subset (lower is better; 0 = original pivot).', '',
         '| Solver | Family | Config | Valid | Metric | Agreement | Comparable W/T/L | Best-candidate rate |', '|---|---|---|---|---:|---:|---|---:|']
    for key, e in R['per'].items():
        s, fam = key.split('/')
        for c in e['configs']:
            m = c['summary']; star = ' **(selected)**' if e['selected'] and c['config']['id'] == e['selected']['id'] else ''
            L.append(f"| {s} | {fam} | {c['config']['id']}{star} | {c['valid']} | {_f(c['metric'])} | {_f(m['policy_agreement'], 3)} | {m['wins']}/{m['ties']}/{m['losses']} | {_f(m['best_candidate_rate'], 3)} |")
    L += ['', '## Selected configurations versus the original pivot', '', '| Solver | Family | Config | Subset states/graphs | Metric | 95% graph-bootstrap interval | Comparable log-ratio (interval) | Ablation metric | Main - ablation (interval) |', '|---|---|---|---|---:|---|---|---:|---|']
    for key, e in R['per'].items():
        s, fam = key.split('/')
        if not e['selected']:
            L.append(f'| {s} | {fam} | none valid | - | - | - | - | - | - |'); continue
        m = e['selected_summary']; b = e['bootstrap_selection_metric']; bc = e['bootstrap_comparable_log_ratio']; ab = e['ablation']; d = ab['paired_graph_difference_main_minus_ablation']
        L.append(f"| {s} | {fam} | {e['selected']['id']} | {m['selection_subset_states']}/{m['selection_subset_graphs']} | {_f(m['selection_metric'])} | "
                 f"[{_f(b['ci95'][0])}, {_f(b['ci95'][1])}] | {_f(bc['estimate'])} [{_f(bc['ci95'][0])}, {_f(bc['ci95'][1])}] | {_f(ab['metric'])} | "
                 f"{_f(d['estimate']) if d else '-'} [{_f(d['ci95'][0]) if d else '-'}, {_f(d['ci95'][1]) if d else '-'}] |")
    L += ['', 'Intervals: paired graph bootstrap (2000 fixed-seed resamples of graphs). They describe development uncertainty conditional on this selection procedure and do not correct selection optimism.', '',
          '## Coverage', '', '| Solver | States | Informative | All-tie | Entirely censored | Env-incompatible | Excluded | Subset states/graphs | Retained/strict pairs | Graphs w/o informative states |', '|---|---:|---:|---:|---:|---:|---:|---|---|---|']
    for s, c in R['coverage'].items():
        L.append(f"| {s} | {c['states']} | {c['states_informative']} | {c['states_all_tie']} | {c['states_entirely_censored']} | {c['states_env_incompatible_valid_candidates']} | {c['states_excluded']} | "
                 f"{c['selection_subset_states']}/{c['selection_subset_graphs']} | {c['retained_pairs']}/{c['strict_pairs_total']} | {', '.join(c['graphs_without_informative_states']) or 'none'} |")
    L += ['', '## Limitations', '',
          '- Saved Stage C states are a selected sample (first A state plus seeded reservoir; 64 KiB slot cap); outcomes are single first-pivot substitutions followed by the original policy, with a 10 s CPU cap per arm.',
          '- Labels are exact node totals of those continuations; the node metric is a surrogate. Repeated learned decisions, prediction overhead and complete-solver behaviour are untested.',
          '- Cross-validated selection over 6 configurations per family reuses the same folds for selection and reporting; selected-model results are optimistic development estimates.',
          '- Pairs are restricted to identical CPU/image/executable groups; states spanning runners contribute only within-group pairs and are outside the selection subset.',
          '- Graph identity audit is bounded (raw/edge-multiset hashes, 1-WL signatures); it does not prove absence of isomorphic or related instances.',
          '- The 130 reserved hidden graphs were not accessed; they remain the future independent benchmark.']
    (out / 'REPORT.md').write_text('\n'.join(L) + '\n', encoding='utf-8', newline='\n')
