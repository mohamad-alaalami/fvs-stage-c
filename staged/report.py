"""Regenerate censored comparisons from immutable indexed per-arm records."""
import pathlib,json,sys,collections,statistics
def comparison(original,other,metric):
 if not original or not other:return 'unresolved',None
 a,b=original['status'],other['status']
 if original['environment']['cpu']!=other['environment']['cpu'] or original['environment']['image']!=other['environment']['image'] or original['executable_sha256']!=other['executable_sha256']:return 'unresolved_environment',None
 if a=='completed' and b=='cpu_timeout':return 'original_completion_winner',None
 if b=='completed' and a=='cpu_timeout':return 'alternative_completion_winner',None
 if a!='completed' or b!='completed':return 'unresolved',None
 if original['measurement']['final_incumbent']['size_cap']!=other['measurement']['final_incumbent']['size_cap']:return 'unresolved_correctness_discrepancy',None
 x=original['measurement']['total_nodes'] if metric=='nodes' else original['cpu_s'];y=other['measurement']['total_nodes'] if metric=='nodes' else other['cpu_s']
 return ('tie' if x==y else 'alternative_better' if y<x else 'original_better'),dict(original=x,alternative=y,absolute_reduction=x-y,fractional_reduction=(x-y)/x if x else None)
def main():
 index=json.loads(pathlib.Path(sys.argv[1]).read_text());root=pathlib.Path(sys.argv[2]);out=pathlib.Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
 arms=collections.defaultdict(list)
 for p in root.glob('chunks/*/attempt-*/records.jsonl'):
  for line in p.read_text().splitlines():
   r=json.loads(line);r['record_path']=p.relative_to(root).as_posix();arms[(r['state_id'],r['candidate_local_id'])].append(r)
 states=[];groups=collections.defaultdict(list);retries={}
 for s in index['states']:
  rows={v:arms.get((s['state_id'],v),[]) for v in s['candidates']}
  # Never silently choose a retry or mix independent attempts.
  chosen={v:x[0] if len(x)==1 else None for v,x in rows.items()};o=chosen[s['event']['local_pivot']]
  comparisons=[]
  for v in s['candidates']:
   if len(rows[v])>1:retries[s['state_id']+':'+str(v)]=[r['run_id'] for r in rows[v]]
   if v==s['event']['local_pivot']:continue
   row={'candidate_local_id':v}
   for metric in ['nodes','cpu']:
    verdict,margin=comparison(o,chosen[v],metric);row[metric]={'verdict':verdict,'margin':margin}
   comparisons.append(row)
  result={'state_id':s['state_id'],'solver':s['solver'],'graph':s['graph'],'candidates':len(s['candidates']),'recorded_arms':sum(bool(x) for x in rows.values()),'strict_qualification':s['event'].get('qualifying_state'),'comparisons':comparisons,'ranks':{}}
  for metric in ['nodes','cpu']:
   verdicts=[x[metric]['verdict'] for x in comparisons];unresolved=sum(x.startswith('unresolved') for x in verdicts)
   better=sum(x in ['alternative_better','alternative_completion_winner'] for x in verdicts);ties=verdicts.count('tie')
   rank=1+better if not unresolved and o and o['status']=='completed' and (metric!='nodes' or all(r and r['status']=='completed' for r in chosen.values())) else None
   result['ranks'][metric]={'original_rank':rank,'tied_alternatives':ties,'unresolved_comparisons':unresolved,'alternatives_better':better,'any_alternative_better':better>0}
  states.append(result);groups[(s['solver'],s['graph'])].append(result)
 pergraph=[]
 for (solver,graph),rows in sorted(groups.items()):
  pergraph.append(dict(solver=solver,graph=graph,states=len(rows),**{metric:dict(states_with_better_alternative=sum(r['ranks'][metric]['any_alternative_better'] for r in rows),states_with_unresolved=sum(r['ranks'][metric]['unresolved_comparisons']>0 for r in rows),better_state_fraction=sum(r['ranks'][metric]['any_alternative_better'] for r in rows)/len(rows)) for metric in ['nodes','cpu']}))
 persolver={solver:{'states':sum(x['states'] for x in pergraph if x['solver']==solver),'graphs_with_saved_states':sum(x['solver']==solver for x in pergraph),'equal_graph_weight_better_fraction':{m:statistics.mean(x[m]['better_state_fraction'] for x in pergraph if x['solver']==solver) for m in ['nodes','cpu']}} for solver in ['8','5','LP']}
 for name,data in [('states',states),('per_graph',pergraph),('per_solver',persolver),('retries_requiring_resolution',retries)]: (out/(name+'.json')).write_text(json.dumps(data,separators=(',',':')))
 count=sum(len(x) for x in arms.values());text=f'# Stage D report\n\nIndexed states: {len(states)}. Scheduled arms: 71038. Recorded invocations (including retries): {count}.\n\n'
 text+='Only complete node totals are ranked. A completed arm beats a CPU-censored arm on completion within budget; two censored arms remain unresolved. Cross-CPU/image comparisons and multiple attempts are unresolved. Raw prefixes remain available.\n\n'
 text+='These results describe the 6502 Stage C saved states, with its first-state/reservoir selection and 64 KiB slot exclusion; they do not estimate all branching decisions. Per-graph results and equal-graph averages avoid treating hard-graph state totals as independent graph evidence.\n\n'
 text+='|Solver|States|Graphs|Equal-graph fraction with node/completion improvement|\n|---|---:|---:|---:|\n'
 for solver,d in persolver.items():text+=f'|{solver}|{d["states"]}|{d["graphs_with_saved_states"]}|{d["equal_graph_weight_better_fraction"]["nodes"]:.4f}|\n'
 (out/'REPORT.md').write_text(text)
if __name__=='__main__':main()
