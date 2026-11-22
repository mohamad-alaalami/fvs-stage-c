#include <functional>
// First decision only: same two-child bodies as stageContinue / stageNeighbor.
// All recursive calls use the unchanged original selector and continuation.
int StageC::replay(){
 ifstream in(replayFile,ios::binary);in.seekg(replayOffset);string bytes(replayLength,'\0');in.read(&bytes[0],bytes.size());if(!in)throw runtime_error("snapshot read failed");
 BranchingSolution*s=nullptr;Graph g;int phase,original,root;restore(bytes,s,g,phase,original,root);
 if(state(s,g,phase,original,root)!=bytes)throw runtime_error("snapshot round-trip mismatch");
 StageAnalysis an=analyze(s,g,phase,original,root);
 if(!an.ambiguous||!an.pivotEligible||(phase!=0&&phase!=2))throw runtime_error("not an eligible saved choice");
 int v=forcedPivot<0?original:forcedPivot;
 if(find(an.candidates.begin(),an.candidates.end(),v)==an.candidates.end())throw runtime_error("pivot outside domain");
 auto nodes=[](){uint64_t n=0;for(int p=0;p<3;++p)for(int c=0;c<2;++c)n+=nodesEntered[p][c];return n;};
 auto incumbent=[&](){ostringstream o;o<<"{\"size_cap\":"<<s->size_cap<<",\"solFound\":"<<(s->solFound?"true":"false")<<",\"sol\":[";for(size_t i=0;i<s->sol.size();++i)o<<(i?",":"")<<s->sol[i];o<<"]}";return o.str();};
 string initial=incumbent(),status="completed";int code=0;
 struct Child {string status="unstarted",reason="preceding_child_not_completed",before="null",after="null";uint64_t n=0,b=0;double cpu=0,wall=0;};
 Child child[2];int activeChild=-1;uint64_t activeN=0,activeB=0;double activeCpu=0;auto activeWall=chrono::steady_clock::now();
 double startCpu=cpu();auto startWall=chrono::steady_clock::now();
 auto executeChild=[&](int i,const std::function<void()>&body){
  Child&c=child[i];c.before=incumbent();uint64_t n0=nodes(),b0=B;double c0=cpu();auto w0=chrono::steady_clock::now();
  c.status="running";c.reason="";activeChild=i;activeN=n0;activeB=b0;activeCpu=c0;activeWall=w0;
  try{StageC::guard();body();c.status="completed";}
  catch(const StageStop&stop){c.status=stop.reason;c.reason=stop.reason;c.n=nodes()-n0;c.b=B-b0;c.cpu=cpu()-c0;c.wall=chrono::duration<double>(chrono::steady_clock::now()-w0).count();c.after=incumbent();throw;}
  c.n=nodes()-n0;c.b=B-b0;c.cpu=cpu()-c0;c.wall=chrono::duration<double>(chrono::steady_clock::now()-w0).count();c.after=incumbent();activeChild=-1;
 };
 armCheckpoint=[&](){
  ostringstream o;o<<setprecision(15)<<"{\"status\":\"observed_prefix\",\"total_nodes\":"<<nodes()<<",\"branching_decisions\":"<<B<<",\"cpu_s_at_checkpoint\":"<<cpu()<<",\"final_incumbent\":"<<incumbent()<<",\"children\":[";
  for(int i=0;i<2;++i){auto c=child[i];if(i==activeChild){c.n=nodes()-activeN;c.b=B-activeB;c.cpu=cpu()-activeCpu;c.wall=chrono::duration<double>(chrono::steady_clock::now()-activeWall).count();c.after=incumbent();}o<<(i?",":"")<<"{\"order\":"<<i+1<<",\"status\":"<<quote(c.status)<<",\"nodes\":"<<c.n<<",\"branching_decisions\":"<<c.b<<",\"cpu_s\":"<<c.cpu<<",\"wall_s\":"<<c.wall<<",\"incumbent_before\":"<<c.before<<",\"incumbent_after\":"<<c.after<<"}";}
  o<<"]}";atomicWrite(directory+"/arm.partial.json",o.str());
 };
 armCheckpoint();
 try {
  StageDecision decision(s,g,phase,v,root);
  Graph g2(g);
  if(phase==0){
   executeChild(0,[&](){g.putInSolution(v);s->stepIntoDeletionBranch(g);s->branching(g);s->stepOutOfDeletionBranch(g);});
   executeChild(1,[&](){g2.putInSafe(v);s->stepIntoUndeletableBranch(g);s->branching(g2);s->stepOutOfUndeletableBranch(g);});
  }else{
   auto lp=dynamic_cast<HalfIntBranching*>(s);
   executeChild(0,[&](){g.putInSolution(v);lp->solve2(g,root);});
   executeChild(1,[&](){g2.merge(root,v);lp->solve2(g2,root);});
  }
 }catch(const StageStop&stop){status=stop.reason;code=stop.code;}
 double elapsedCpu=cpu()-startCpu,elapsedWall=chrono::duration<double>(chrono::steady_clock::now()-startWall).count();
 ostringstream o;o<<setprecision(15)<<"{\"status\":"<<quote(status)<<",\"candidate_local_id\":"<<v<<",\"original_local_id\":"<<original<<",\"initial_incumbent\":"<<initial<<",\"final_incumbent\":"<<incumbent()<<",\"total_nodes\":"<<nodes()<<",\"branching_decisions\":"<<B<<",\"root_decisions\":"<<(B?1:0)<<",\"continuation_cpu_s\":"<<elapsedCpu<<",\"continuation_wall_s\":"<<elapsedWall<<",\"setup_cpu_s\":"<<startCpu<<",\"parent_overhead_cpu_s\":"<<elapsedCpu-child[0].cpu-child[1].cpu<<",\"parent_overhead_wall_s\":"<<elapsedWall-child[0].wall-child[1].wall<<",\"children\":[";
 for(int i=0;i<2;++i){auto&c=child[i];o<<(i?",":"")<<"{\"order\":"<<i+1<<",\"action\":"<<quote(i==0?"delete_pivot":phase==0?"mark_pivot_undeletable":"merge_pivot_into_root")<<",\"status\":"<<quote(c.status)<<",\"stop_reason\":"<<quote(c.reason)<<",\"nodes\":"<<c.n<<",\"branching_decisions\":"<<c.b<<",\"cpu_s\":"<<c.cpu<<",\"wall_s\":"<<c.wall<<",\"incumbent_before\":"<<c.before<<",\"incumbent_after\":"<<c.after<<"}";}
 o<<"],\"nodes_reconcile\":"<<(nodes()==child[0].n+child[1].n?"true":"false")<<",\"branches_reconcile\":"<<(B==child[0].b+child[1].b+(B?1:0)?"true":"false")<<"}";
 armCheckpoint=nullptr;atomicWrite(directory+"/arm.json",o.str());finish(status);delete s;return code;
}
