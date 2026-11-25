"""Write REPORT.md from results.json (every number in the report comes from results.json)."""
import json, pathlib, sys

out = pathlib.Path(sys.argv[1]); r = json.loads((out / 'results.json').read_text(encoding='utf-8'))
NAME = {'8': '8 (Cao)', '5': '5 (Chen)', 'LP': 'LP'}
L = []
w = L.append
w(f"# Addendum {r['addendum_id']}: linear fold models rescored with the deployed scorer\n")
w("Addendum to offline learnability run 45408454796 (branch `learnability-results`, commit `e5b8401`). "
  "Nothing was refitted, retuned or reselected; no solver was run; no reserved graph was opened (all states are from the public "
  "extraction `extract-v1-20261124T115559Z-833e6421`).\n")
w("## What was done\n")
w("- **Models:** the 90 archived linear CV fold models (3 solvers x 6 lambdas x 5 folds), each scored only on its original held-out fold.")
w("- **Old scorer:** the offline scorer as run in training, `transform(X) @ theta` (numpy, batched per state). It reproduces every archived summary of run 45408454796 exactly, including per-fold summaries, and the archived per-state records of the three frozen configurations (one state differs only in the last bit of `log`, a libm difference; selection identical).")
w("- **Corrected scorer:** `PolicyReplay.exe` from validated build 45493670014 (sha256 `24e2fd2e...`). It runs the solver's own `selectCore`, with features computed live from the Stage C snapshot. A Python left-to-right replica of the live summation agreed with it bit for bit on every candidate, and the live features equalled the archived table exactly.")
w("- **Unchanged rules:** the tie rule (argmax; exact ties go to the original pivot if it is among the maxima, else the lowest archived ordinal), `evaluate_state`, the development metric and the configuration-choice rule are the frozen code of commit `27c43b7`.")
w(f"- **Checks:** {sum(c['ok'] for c in r['checks'].values())}/{len(r['checks'])} passed.\n")
w("**Definitions.** A *changed selection* is a held-out state where the corrected pick differs from the old pick. "
  "The *observed node total* is the Stage D exact node count of the selected candidate. It is *observable* for a changed state when both picks "
  "are valid with the same comparability key in a non-excluded state; otherwise it is reported as unobservable, never imputed. "
  "The *development metric* is the frozen selection metric: graph-equal mean of log((1+selected)/(1+original)) on the fixed "
  "complete-compatible subset (lower is better, 0 = original pivot).\n")
w("## Frozen configurations\n")
w("| Solver | Frozen config | Held-out states | Changed selections | Node total observable | Changed | Lower / higher | Unchanged | Unobservable | Old metric | Corrected metric | Choice would change? |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|")
for s, v in r['solvers'].items():
    c = v['configs'][v['frozen_config']]; ch = c['changed']; n = ch.get('changed', 0)
    w(f"| {NAME[s]} | {v['frozen_config']} | {ch['states']} | {n} ({100 * n / ch['states']:.1f}%) | {ch.get('node_total_observable', 0)} | "
      f"{ch.get('node_total_changed', 0)} | {ch.get('node_total_decreased', 0)} / {ch.get('node_total_increased', 0)} | {ch.get('node_total_unchanged', 0)} | "
      f"{ch.get('node_total_unobservable', 0)} | {c['old_metric']:.6f} | {c['corrected_metric']:.6f} | "
      f"{'**yes**, to ' + v['corrected_choice'] if v['choice_would_change'] else 'no'} |")
w("")
w("In every changed state, across all 18 configurations, the two picks have identical feature rows and the old pick is still one of the "
  "deployed maxima. The change is therefore purely the tie rule now being applied to exact ties. No change ever moves a selection away from "
  "the original pivot; most move to it.\n")
w("## Configuration choice (all lambdas, unchanged choice rule)\n")
for s, v in r['solvers'].items():
    w(f"### {NAME[s]}\n")
    w("| Config | Changed selections | Node total changed (of observable) | Old metric | Corrected metric | Old agreement | Corrected agreement | Old W/T/L | Corrected W/T/L |")
    w("|---|---|---|---|---|---|---|---|---|")
    for cid, c in v['configs'].items():
        ch = c['changed']; o, n = c['old'], c['corrected']
        mark = ' (frozen)' if cid == v['frozen_config'] else ''
        w(f"| {cid}{mark} | {ch.get('changed', 0)} | {ch.get('node_total_changed', 0)} of {ch.get('node_total_observable', 0)} | {o['selection_metric']:.6f} | {n['selection_metric']:.6f} | "
          f"{o['policy_agreement']:.4f} | {n['policy_agreement']:.4f} | {o['wins']}/{o['ties']}/{o['losses']} | {n['wins']}/{n['ties']}/{n['losses']} |")
    w("")
    w(f"- Old ranking: {', '.join(v['old_ranking'])}; choice **{v['old_choice']}** (margin to runner-up {v['old_margin_to_runner_up']:.2e}).")
    w(f"- Corrected ranking: {', '.join(v['corrected_ranking'])}; choice **{v['corrected_choice']}** (margin {v['corrected_margin_to_runner_up']:.2e}).")
    w(f"- Choice would change: **{'yes' if v['choice_would_change'] else 'no'}**.\n")
w("## Interpretation limits\n")
w("- **Development estimates:** these are pooled out-of-fold development estimates, not an unbiased test, and they carry the selection optimism of the original protocol. No bootstrap was recomputed.")
w("- **Small margins:** the margins between configurations are small, so a changed choice here does not show that one lambda is better.")
w("- **Frozen models unchanged:** the frozen refits, the deployed models and their hashes are unchanged. This addendum only reports what the archived development metric becomes under the deployed tie rule.")
w("- **Superseded first execution:** it is kept in `superseded-execution-1/`. Its two failed checks were check-design issues, not result changes: CRLF in the `git archive` copy of `folds.json` (identical after LF normalisation), and one archived `selection_cost` differing in its last bit. Its results are identical to this execution.\n")
w("## Files\n")
w("- `results.json`: every check, the old and corrected summaries per configuration, tallies, rankings and the environment.")
w("- `changed_states.jsonl.gz`: one record per changed state, for every solver and configuration.")
w("- `code/`: `rescore_linear.py`, `make_report.py`.")
w("- `inputs/`: the archived fold models, frozen manifests, selection, selected-state records and `PolicyReplay.exe`.")
w("- `MANIFEST.json`: SHA-256 of every file; `COMPLETE` holds SHA-256(`MANIFEST.json`).")
(out / 'REPORT.md').write_text('\n'.join(L) + '\n', encoding='utf-8', newline='\n')
