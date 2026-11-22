"""Execute exact scheduled pivot arms; one process and fresh restoration per arm."""
import pathlib,sys,json,os,zlib,hashlib,subprocess,time,uuid,platform,winreg,zipfile,argparse,shutil
HERE=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent/'stagec'))
from winmeasure import measurements,lifetime
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2),encoding='utf-8')
def environment():
 with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:cpu=winreg.QueryValueEx(k,'ProcessorNameString')[0].strip()
 return dict(cpu=cpu,os=platform.platform(),image=os.getenv('ImageOS','local')+' '+os.getenv('ImageVersion','unknown'),runner=os.getenv('RUNNER_NAME','local'))
def run_arm(exe,s,candidate,snapshot,out,budget,build,envinfo,deadline):
 rid=str(uuid.uuid4());d=out/rid;d.mkdir();env=dict(os.environ,STAGE_DIR=str(d),STAGE_CPU_LIMIT=str(budget),STAGE_RESERVE_BYTES=str(3*1024**3),STAGE_GRAPH=s['graph'],STAGE_RUN=rid)
 command=[str(exe),s['solver'],'--pivot',str(snapshot),'0',str(s['sample']['state_bytes']),str(candidate)]
 ordinal=s['candidates'].index(candidate);score=s['scores'][ordinal]
 rec=dict(run_id=rid,state_id=s['state_id'],graph=s['graph'],solver=s['solver'],phase=s['event']['phase'],component_subsolver=s['event']['component_subsolver'],snapshot_sha256=s['snapshot_sha256'],candidate_list_sha256=s['candidate_list_sha256'],candidate_local_id=candidate,candidate_id=s['candidate_labels'][ordinal],original_pivot=candidate==s['event']['local_pivot'],classical_score=score,classical_rank=1+sum(tuple(x) > tuple(score) if isinstance(score,list) else x>score for x in s['scores']),initial_incumbent=s['initial_incumbent'],command=command,command_line=subprocess.list2cmdline(command),executable_sha256=build['executable_sha256'],source_hashes=build['source_hashes'],experiment_commit=build['experiment_commit'],environment=envinfo,cpu_budget_s=budget,status='started',counts_source='unknown')
 save(d/'run.json',rec);stop=None;stop_at=None;start=time.monotonic()
 if start>=deadline or shutil.disk_usage(out).free<3*1024**3:
  rec['status']='unstarted_deadline' if start>=deadline else 'unstarted_disk_reserve';save(d/'run.json',rec);return rec
 with (d/'stdout.txt').open('wb') as fo,(d/'stderr.txt').open('wb') as fe:
  p=subprocess.Popen(command,stdout=fo,stderr=fe,env=env)
  while p.poll() is None:
   cpu,_=measurements(p);now=time.monotonic()
   if cpu!='unknown' and cpu>=budget:stop=stop or 'cpu_timeout'
   if now>=deadline:stop=stop or 'runner_deadline'
   if shutil.disk_usage(out).free<3*1024**3:stop=stop or 'disk_reserve'
   if stop and stop_at is None:
    stop_at=now;(d/'STOP.tmp').write_text(stop);os.replace(d/'STOP.tmp',d/'STOP')
   if stop_at is not None and now-stop_at>1:p.kill();rec['forced_termination']=True
   time.sleep(.005)
  p.wait();rec.update(exit_code=p.returncode,cpu_s=measurements(p)[0],wall_s=lifetime(p),driver_wall_s=time.monotonic()-start,peak_memory_bytes=measurements(p)[1])
 if (d/'arm.json').exists():
  arm=json.loads((d/'arm.json').read_text());rec.update(status=arm['status'],counts_source='final',measurement=arm)
  assert arm['nodes_reconcile'] and arm['branches_reconcile']
  assert arm['initial_incumbent']==s['initial_incumbent']
  rec['finalization_cpu_s']=rec['cpu_s']-arm['setup_cpu_s']-arm['continuation_cpu_s']
  rec['process_wall_outside_continuation_s']=rec['wall_s']-arm['continuation_wall_s']
  summary=json.loads((d/'summary.json').read_text());entered=sum(summary['nodes'][proc]['entered_main']+summary['nodes'][proc]['entered_component'] for proc in ['branching','solve1','solve2'])
  assert entered==arm['total_nodes'] and summary['nodes']['outcome_anomalies']==0
 else:
  rec.update(status=stop or 'failed',error='no final arm record',counts_source='missing')
  if (d/'arm.partial.json').exists():rec.update(counts_source='checkpoint_prefix',measurement=json.loads((d/'arm.partial.json').read_text()))
 if (d/'replay_result.json').exists():rec['continuation']=json.loads((d/'replay_result.json').read_text())
 expected=s['sample']['continuation']
 if rec['original_pivot'] and rec['status']=='completed' and expected and expected['complete']:
  actual=rec.get('continuation',{});rec['original_reproduction']='pass' if all(actual.get(k)==expected[k] for k in ['trace_count','trace_digest','final_state_hash']) else 'FAIL'
 else:rec['original_reproduction']='untested_censored_or_no_complete_stage_c_reference' if rec['original_pivot'] else 'not_original'
 save(d/'run.json',rec);return rec
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--records',required=True);ap.add_argument('--index',required=True);ap.add_argument('--build',required=True);ap.add_argument('--out',required=True);ap.add_argument('--chunk',type=int);ap.add_argument('--pilot',choices=['8','5','LP']);args=ap.parse_args()
 records=pathlib.Path(args.records).resolve();index=json.loads(pathlib.Path(args.index).read_text());builddir=pathlib.Path(args.build).resolve();out=pathlib.Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 build=json.loads((builddir/'build.json').read_text());exe=builddir/'StageD.exe';assert sha(exe)==build['executable_sha256'];envinfo=environment();save(out/'environment.json',envinfo)
 if args.pilot:
  eligible=[(i,s) for i,s in enumerate(index['states']) if s['solver']==args.pilot]
  small=next((i,s) for i,s in eligible if s['graph']=='095' and s['sample']['continuation'] and s['sample']['continuation']['complete'])
  hard=max(eligible,key=lambda x:((x[1]['sample']['continuation'] or {}).get('trace_count',0)))
  schedule=[(small[0],v,10) for v in small[1]['candidates']]+[(hard[0],hard[1]['event']['local_pivot'],.01),(hard[0],hard[1]['event']['local_pivot'],10),(hard[0],hard[1]['candidates'][-1],10)]
 else:schedule=[(i,c,10) for i,c in index['chunks'][args.chunk]]
 save(out/'schedule.json',dict(chunk=args.chunk,pilot=args.pilot,arms=schedule,index_sha256=sha(args.index)))
 raw=out/'raw';raw.mkdir(exist_ok=True);scratch=out/'scratch';scratch.mkdir(exist_ok=True);results=[];deadline=time.monotonic()+14400
 for i,c,budget in schedule:
  s=index['states'][i];snapshot=scratch/f'{i}.bin'
  if not snapshot.exists():
   meta=records/s['metadata_path'];packed=meta.with_name('samples.bin.zz');assert sha(packed)==s['packed_sha256'];data=zlib.decompress(packed.read_bytes());sample=s['sample'];snapshot.write_bytes(data[sample['offset']:sample['offset']+sample['state_bytes']]);assert sha(snapshot)==s['snapshot_sha256']
  rec=run_arm(exe,s,c,snapshot,raw,budget,build,envinfo,deadline);rec['state_index']=i;results.append(rec)
  with (out/'records.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(rec,separators=(',',':'))+'\n')
  print(rec['state_id'],c,rec['status'],rec.get('cpu_s'),flush=True)
  if rec.get('original_reproduction')=='FAIL':raise RuntimeError('original continuation mismatch; stopping this chunk')
 with zipfile.ZipFile(out/'raw.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for p in raw.rglob('*'):
   if p.is_file():z.write(p,p.relative_to(raw))
 # These are newly-created, archived per-arm files; preserve originals in raw.zip.
 assert raw.resolve().parent==out.resolve() and scratch.resolve().parent==out.resolve() and not raw.is_symlink() and not scratch.is_symlink()
 shutil.rmtree(raw);shutil.rmtree(scratch)
 summary=dict(arms=len(results),status_counts={k:sum(r['status']==k for r in results) for k in sorted({r['status'] for r in results})},total_cpu_s=sum(r.get('cpu_s',0) for r in results),raw_zip_bytes=(out/'raw.zip').stat().st_size,records_bytes=(out/'records.jsonl').stat().st_size)
 save(out/'summary.json',summary)
 if args.pilot:
  completed_small=[r for r in results if r['state_index']==small[0] and r['status']=='completed']
  assert len(completed_small)==len(small[1]['candidates'])
  assert len({r['measurement']['final_incumbent']['size_cap'] for r in completed_small})==1
  assert any(r['original_reproduction']=='pass' for r in results)
  assert any(r['status']=='completed' and not r['original_pivot'] for r in results)
  assert any(r['status']=='cpu_timeout' and r.get('measurement',{}).get('children',[{},{}])[1].get('status')=='unstarted' for r in results)
  assert all(r['counts_source']=='final' for r in results)
if __name__=='__main__':main()
