import json, glob, collections, statistics, sys, os
R = sys.argv[1]
EXE = {'baseline/FeedbackVertexSet.exe':'9fe46be6','baseline/Verifier.exe':'522a0f1f','integrated/FvsIntegrated.exe':'a409b4eb','tools/PolicyReplay.exe':'24e2fd2e'}
MOD = {'5/linear/model.json':'a01d2053','5/boost/model.json':'87a34cea','8/linear/model.json':'6c43249c','8/boost/model.json':'fb7f8c14','LP/linear/model.json':'fc62ad4d','LP/boost/model.json':'1c5ab095'}
jobs = [json.load(open(p)) for p in sorted(glob.glob(f'{R}/jobs/*/*/attempt-*/job.json'))]
print('job records', len(jobs), 'attempts', collections.Counter(j['environment']['github_run_attempt'] for j in jobs))
bad=[]
st=collections.Counter(); cpu=collections.defaultdict(float); wall=collections.defaultdict(float); jobwall=0
sizes=collections.defaultdict(dict); tocpu=[]; feas=collections.Counter(); usedmodel=collections.Counter(); exercised=collections.Counter()
ids=set(); orders=collections.Counter()
for j in jobs:
    s=j['job']['solver']; g=j['job']['graph_id']; ids.add((s,g)); orders[(s,tuple(j['job']['order']))]+=1
    jobwall+=j['job_wall_s']
    for k,h in EXE.items():
        if not j['executables'][k]['sha256'].startswith(h): bad.append(('exe',s,g,k))
    for k,h in MOD.items():
        if not j['model_hashes'][k].startswith(h): bad.append(('model',s,g,k))
    if j['infrastructure_failure'] or j['faults']: bad.append(('infra/faults',s,g,j['faults']))
    if j['thread_limits']!={'MKL_NUM_THREADS':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}: bad.append(('threads',s,g))
    if j['completed_sizes_agree'] is not True: bad.append(('sizes',s,g))
    inv=j['invocations']
    if set(inv)!={'baseline','linear','boost'}: bad.append(('inv',s,g,list(inv)))
    for p,x in inv.items():
        st[(s,p,x['status'])]+=1; cpu[s]+=x['cpu_s']; wall[s]+=x['wall_s']
        if x['status']=='completed':
            feas[x['feasible']]+=1; sizes[g][(s,p)]=x['size']
            if x['exit_code']!=0: bad.append(('exit',s,g,p,x['exit_code']))
        else:
            tocpu.append(x['cpu_s'])
        if p!='baseline':
            usedmodel[x.get('model') is not None]+=1
            if (x.get('scored') or 0)>0: exercised[(s,p)]+=1
        if not x['executable_sha256'].startswith('a409b4eb'): bad.append(('invexe',s,g,p))
print('distinct graph-solver jobs', len(ids))
print('statuses', dict(sorted(st.items())))
print('completed feasible', feas)
print('learned invocations with model recorded', usedmodel, 'scored>0', dict(exercised))
print('timeout cpu min/median/max', min(tocpu), statistics.median(tocpu), max(tocpu), 'n', len(tocpu))
# cross-solver size agreement per graph
dis=[g for g,d in sizes.items() if len(set(d.values()))>1]
print('graphs with completed results', len(sizes), 'cross-solver size disagreements', dis)
print('cpu_s by solver (h)', {s:round(v/3600,2) for s,v in cpu.items()}, 'total h', round(sum(cpu.values())/3600,2))
print('invocation wall by solver (h)', {s:round(v/3600,2) for s,v in wall.items()}, 'total h', round(sum(wall.values())/3600,2), 'job wall total h', round(jobwall/3600,2))
oc=collections.defaultdict(collections.Counter)
for (s,o),n in orders.items(): oc[s][n]+=1
print('order usage counts per solver', {s:dict(c) for s,c in oc.items()})
print('BAD', bad[:20], len(bad))
# Chen baseline-only graphs and per-graph regressions/improvements in solved status
for s in ['5','8','LP']:
    for p in ['linear','boost']:
        bo=[];lo=[]
        for j in jobs:
            if j['job']['solver']!=s: continue
            b=j['invocations']['baseline']['status']=='completed'; l=j['invocations'][p]['status']=='completed'
            if b and not l: bo.append((j['job']['graph_id'], round(j['invocations']['baseline']['cpu_s'],1)))
            if l and not b: lo.append((j['job']['graph_id'], round(j['invocations'][p]['cpu_s'],1)))
        if bo or lo: print(s,p,'baseline-only',bo,'learned-only',lo)
