"""Validate and exhaustively index the experiment-of-record Stage C states."""
import pathlib,json,zlib,struct,hashlib,collections,sys,subprocess,os
ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'stagec'))
from snapshot import decode
RUN='44639720515'
def sha(b):return hashlib.sha256(b).hexdigest()
def fnv(b):
 h=14695981039346656037
 for x in b:h=((h^x)*1099511628211)&((1<<64)-1)
 return str(h)
def main():
 source=pathlib.Path(sys.argv[1]).resolve();out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
 run=source/'runs'/RUN;build=json.loads((run/'build/build_record.json').read_text())
 assert build['full_commit']=='c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4'
 for name,digest in build['instrumented_source_hashes'].items():assert sha((run/'build/instrumented-src'/name).read_bytes())==digest,name
 states=[];hist=collections.Counter();by=collections.defaultdict(lambda:dict(states=0,pivots=0));native=[]
 for meta in sorted((run/'pairs').glob('*/attempt-1/invocations/*-instrumented/samples.json')):
  m=json.loads(meta.read_text());packed=meta.with_name('samples.bin.zz');raw=zlib.decompress(packed.read_bytes());stream=bytearray()
  for sample in m['samples']:
   blob=raw[sample['offset']:sample['offset']+sample['state_bytes']];assert fnv(blob)==sample['state_fnv']
   cb=raw[sample['candidates_offset']:sample['candidates_offset']+4*sample['candidate_count']];c=list(struct.unpack('<'+'i'*sample['candidate_count'],cb));s=decode(blob)
   assert len(set(c))==len(c)>=2 and s['pivot'] in c and s['variant']==m['variant']
   e=sample['event'];assert e['local_pivot']==s['pivot'] and e['original_pivot']==s['stageNames'][s['pivot']] and e['component_subsolver']==s['isSub']
   none=[i for i in range(s['N']) if s['status'][i]==0];degree=lambda i:len(s['neighbours'][i])+s['doubleNum'][i]
   if s['variant']=='8':eligible=[i for i in none if degree(i)==max(map(degree,none))];scores=[degree(i) for i in c]
   elif s['variant']=='5':
    assert not s['stageHint'] and not s['branching_hints'];eligible=none
    scores=[(sum(s['status'][j]==1 for j in s['neighbours'][i]),degree(i)) for i in c]
   else:
    assert s['phase']==2;eligible=list(dict.fromkeys(i for i in s['neighbours'][s['root']] if s['status'][i]==0));scores=[degree(i) for i in c]
   assert c==eligible
   graph=m['graph'].split('/')[-1].split('.')[0];identifier=sample['event_id']
   states.append(dict(state_id=identifier,graph=graph,solver=m['variant'],event=e,metadata_path=meta.relative_to(source).as_posix(),packed_sha256=sha(packed.read_bytes()),snapshot_sha256=sha(blob),candidate_list_sha256=sha(cb),sample=sample,candidates=c,candidate_labels=[s['stageNames'][i] for i in c],scores=scores,initial_incumbent={'size_cap':s['size_cap'],'solFound':s['solFound'],'sol':list(s['sol'])},snapshot_N=s['N']))
   hist[len(c)]+=1;by[m['variant']]['states']+=1;by[m['variant']]['pivots']+=len(c)
   stream+=f"{sample['sequence']} {len(blob)} {len(c)}\n".encode()+blob+cb
  if stream:
   checker=run/'build/audit-tool/SampleCheck.exe';p=subprocess.run([str(checker),m['variant']],input=stream,capture_output=True,env=dict(os.environ,STAGE_DIR=str(out.resolve())))
   assert p.returncode==0,(meta,p.stderr)
   records=[json.loads(x) for x in p.stdout.splitlines()];assert len(records)==len(m['samples']) and all(x['ok'] for x in records)
   native.append(dict(metadata_path=meta.relative_to(source).as_posix(),checks=records))
 assert len(states)==6502 and sum(len(s['candidates']) for s in states)==71038
 chunks=[];current=[]
 for idx,s in enumerate(states):
  for candidate in s['candidates']:
   current.append([idx,candidate])
   if len(current)==128:chunks.append(current);current=[]
 if current:chunks.append(current)
 index={'stage_c_run':RUN,'records_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),'stage_c_experiment_commit':build['experiment_commit'],'build_id':build['build_id'],'states':states,'chunks':chunks}
 (out/'index.json').write_text(json.dumps(index,separators=(',',':')))
 (out/'validation.json').write_text(json.dumps(native,separators=(',',':')))
 summary={'states':len(states),'candidate_continuations':sum(len(s['candidates']) for s in states),'per_solver':dict(by),'candidate_count_distribution':dict(sorted(hist.items())),'jobs':len(chunks),'max_candidates_per_job':128,'cpu_budget_s':10,'upper_budget_cpu_hours':71038*10/3600,'idealized_20_runner_hours':71038*10/3600/20,'largest_by_bytes':sorted([{'state_id':s['state_id'],'graph':s['graph'],'solver':s['solver'],'bytes':s['sample']['state_bytes'],'candidates':len(s['candidates'])} for s in states],key=lambda x:x['bytes'],reverse=True)[:10],'largest_by_candidates':sorted([{'state_id':s['state_id'],'graph':s['graph'],'solver':s['solver'],'bytes':s['sample']['state_bytes'],'candidates':len(s['candidates'])} for s in states],key=lambda x:x['candidates'],reverse=True)[:10],'native_validated_states':sum(len(x['checks']) for x in native)}
 (out/'workload.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if not k.startswith('largest')},indent=2))
if __name__=='__main__':main()
