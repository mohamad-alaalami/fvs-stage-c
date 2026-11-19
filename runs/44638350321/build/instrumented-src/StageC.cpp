#include "solutions/HalfIntBranching.h"
#include "solutions/SolutionVariants.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <fstream>
#include <sstream>
#include <set>
#include <map>
#include <numeric>
#include <chrono>
#include <cstdlib>
#include <cstdio>
#include <exception>
#include <iomanip>
#include <cstring>
#include <algorithm>
using namespace std;
// Stage C, full-run edition (state schema STAGEC1 unchanged from the smoke test).
// * Every actual branching decision updates exact counters and histograms; there is no per-event log
//   (optional STAGE_EVENT_LOG=1 writes a compact one for validation only).
// * Search nodes (entries to branching / solve1 / solve2) are counted with exactly one outcome each.
// * Replay states: the first A state, plus a fixed-seed reservoir sample (Algorithm R) of later A states,
//   under explicit byte caps. Only selected states are serialized.
namespace {
string directory,variant,graphId,runId,replayFile;
uint64_t replayOffset=0,replayLength=0;
const uint64_t P=1099511628211ULL;
int level=-1;
bool replayMode=false,eventLog=false;
uint64_t reserveBytes=3ULL<<30;
double cpuLimit=1800;
auto lastCheck=chrono::steady_clock::now()-chrono::seconds(1);
auto lastCheckpoint=chrono::steady_clock::now();
// counters
uint64_t B=0,T=0,A=0,Astrict=0,prefix=0,traceCount=0,componentB=0,leafCalls=0;
map<string,uint64_t> counters;
map<string,map<long long,uint64_t>> hist;
uint64_t nodesEntered[3][2]={{0}},outcomes[3][StageC::OUT_COUNT]={{0}},outcomeAnomalies=0;
// node bookkeeping
struct FrameRec { int proc; bool set; uint64_t leafStampAtEntry; BranchingSolution* solver; };
vector<FrameRec> frames;
uint64_t leafStamp=0; int leafLevel=-2; BranchingSolution* leafSolver=nullptr;
// sampling
uint64_t seed=20261120ULL,K=32,firstCap=4ULL<<20,slotCap=64ULL<<10;
struct Sample { bool used=false; uint64_t seq=0,aIndex=0; string state; vector<int> cands; string payload; bool contDone=false,complete=false; uint64_t traceCount=0; string digest="null",finalHash="null"; };
Sample firstA; vector<Sample> slots;
uint64_t aSeen=0,excludedForSize=0,largestExcluded=0,firstAUnsavedBytes=0,selections=0;
vector<uint64_t> selectionLog,excludedLog;
ofstream events;
double cpu(){FILETIME a,b,c,d;GetProcessTimes(GetCurrentProcess(),&a,&b,&c,&d);return ((uint64_t(c.dwHighDateTime)<<32)+c.dwLowDateTime+(uint64_t(d.dwHighDateTime)<<32)+d.dwLowDateTime)/1e7;}
uint64_t hashBytes(const void*p,size_t n,uint64_t h=14695981039346656037ULL){const unsigned char*c=(const unsigned char*)p;for(size_t i=0;i<n;++i){h^=c[i];h*=P;}return h;}
uint64_t hashString(const string&s){return hashBytes(s.data(),s.size());}
uint64_t power(uint64_t p,uint64_t n){uint64_t r=1;while(n){if(n&1)r*=p;p*=p;n>>=1;}return r;}
uint64_t mix(uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
string quote(const string&s){ostringstream o;o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<c;else if(c<32)o<<"\\u"<<hex<<setw(4)<<setfill('0')<<int(c)<<dec;else o<<c;}o<<'"';return o.str();}
string labels(Graph&g,const vector<int>&v){ostringstream o;o<<'[';for(size_t i=0;i<v.size();++i){if(i)o<<',';o<<quote(g.stageNames[v[i]]);}o<<']';return o.str();}
const char* outcomeName(int o){static const char*n[]={"branch","leaf_solution","pruned","no_pivot","delegate_to_solve1","reduction_recursion","interrupted","unclassified"};return n[o];}
const char* procName(int p){static const char*n[]={"branching","solve1","solve2"};return n[p];}
// Fixed ABI: little-endian Windows x64; int32, bool8, uint64 vector lengths.
struct Archive {
 string data; size_t pos=0; bool read=false;
 Archive(){} Archive(const string&s):data(s),read(true){}
 template<class V> void io(V&v){if(read){if(pos+sizeof(V)>data.size())throw runtime_error("truncated snapshot");memcpy(&v,data.data()+pos,sizeof(V));pos+=sizeof(V);}else data.append(reinterpret_cast<char*>(&v),sizeof(V));}
 void io(string&s){uint64_t n=s.size();io(n);if(n>1000000000ULL)throw runtime_error("bad length");if(read){if(pos+n>data.size())throw runtime_error("truncated string");s=data.substr(pos,n);pos+=n;}else data+=s;}
 template<class V> void io(vector<V>&v){uint64_t n=v.size();io(n);if(n>1000000000ULL)throw runtime_error("bad vector length");if(read)v.resize(n);for(uint64_t i=0;i<n;++i){V x=read?V():V(v[i]);io(x);if(read)v[i]=x;}}
 void io(queue<int>&q){vector<int> v;if(!read){auto copy=q;while(!copy.empty()){v.push_back(copy.front());copy.pop();}}io(v);if(read){q=queue<int>();for(int x:v)q.push(x);}}
};
struct DSU {vector<int> p;DSU(int n):p(n){iota(p.begin(),p.end(),0);}int find(int x){while(p[x]!=x)x=p[x];return x;}bool join(int a,int b){a=find(a);b=find(b);if(a==b)return false;p[a]=b;return true;}};
void atomicWrite(const string&path,const string&data){string tmp=path+".tmp";{ofstream f(tmp,ios::binary);f.write(data.data(),data.size());}MoveFileExA(tmp.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING);}
string histJson(){ostringstream o;o<<'{';bool f1=true;for(auto&h:hist){if(!f1)o<<',';f1=false;o<<quote(h.first)<<":{";bool f2=true;for(auto&kv:h.second){if(!f2)o<<',';f2=false;o<<'"'<<kv.first<<"\":"<<kv.second;}o<<'}';}o<<'}';return o.str();}
string continuationJson(const Sample&s){if(!s.contDone)return "null";ostringstream o;o<<"{\"complete\":"<<(s.complete?"true":"false")<<",\"trace_count\":"<<s.traceCount<<",\"trace_digest\":"<<s.digest<<",\"final_state_hash\":"<<s.finalHash<<'}';return o.str();}
string samplesJson(string&bin){
 ostringstream o;bin.clear();
 o<<"{\"schema\":\"stagec-full-samples-1\",\"state_schema\":\"STAGEC1\",\"variant\":"<<quote(variant)<<",\"run_id\":"<<quote(runId)<<",\"graph\":"<<quote(graphId)
  <<",\"rule\":\"first A state; Algorithm R reservoir of size K over later A states (i-th later A event: slot i-1 if i<=K, else slot r=splitmix64(seed+i) mod i if r<K); a selected state larger than slot_cap is excluded and the slot keeps its occupant\""
  <<",\"seed\":"<<seed<<",\"K\":"<<K<<",\"first_cap_bytes\":"<<firstCap<<",\"slot_cap_bytes\":"<<slotCap<<",\"sample_bytes_definition\":\"state bytes + 4 bytes per eligible candidate\""
  <<",\"A_seen\":"<<aSeen<<",\"first_A_unsaved_bytes\":"<<firstAUnsavedBytes<<",\"excluded_for_size\":"<<excludedForSize<<",\"largest_excluded_bytes\":"<<largestExcluded<<",\"selections\":"<<selections;
 o<<",\"selection_log_sequences\":[";for(size_t i=0;i<selectionLog.size();++i)o<<(i?",":"")<<selectionLog[i];o<<"],\"excluded_sequences_first_1000\":[";for(size_t i=0;i<excludedLog.size();++i)o<<(i?",":"")<<excludedLog[i];o<<"],\"samples\":[";
 bool first=true;auto emit=[&](const Sample&s,const string&kind,int slot){if(!s.used)return;if(!first)o<<',';first=false;uint64_t off=bin.size();bin+=s.state;uint64_t coff=bin.size();bin.append((const char*)s.cands.data(),s.cands.size()*4);
  o<<"{\"kind\":"<<quote(kind)<<",\"slot\":"<<slot<<",\"sequence\":"<<s.seq<<",\"event_id\":"<<quote(runId+":"+to_string(s.seq))<<",\"a_index\":"<<s.aIndex<<",\"offset\":"<<off<<",\"state_bytes\":"<<s.state.size()<<",\"candidates_offset\":"<<coff<<",\"candidate_count\":"<<s.cands.size()<<",\"state_fnv\":\""<<hashString(s.state)<<"\",\"event\":"<<s.payload<<",\"continuation\":"<<continuationJson(s)<<'}';};
 emit(firstA,"first_A",-1);for(size_t i=0;i<slots.size();++i)emit(slots[i],"reservoir",int(i));
 o<<"]}\n";return o.str();
}
string summaryJson(const string&status){
 ostringstream o;o<<setprecision(15);
 o<<"{\"status\":"<<quote(status)<<",\"variant\":"<<quote(variant)<<",\"run_id\":"<<quote(runId)<<",\"graph\":"<<quote(graphId)<<",\"cpu_s\":"<<cpu()
  <<",\"B\":"<<B<<",\"T\":"<<T<<",\"A\":"<<A<<",\"A_chen_strict_merge\":"<<Astrict<<",\"component_B\":"<<componentB<<",\"trace_count\":"<<traceCount<<",\"trace_digest\":\""<<prefix<<"\"";
 o<<",\"counters\":{";bool f=true;for(auto&kv:counters){if(!f)o<<',';f=false;o<<quote(kv.first)<<':'<<kv.second;}o<<'}';
 o<<",\"histograms\":"<<histJson();
 o<<",\"nodes\":{";for(int p=0;p<3;++p){o<<(p?",":"")<<quote(procName(p))<<":{\"entered_main\":"<<nodesEntered[p][0]<<",\"entered_component\":"<<nodesEntered[p][1];for(int k=0;k<StageC::OUT_COUNT;++k)o<<','<<quote(outcomeName(k))<<':'<<outcomes[p][k];o<<'}';}
 o<<",\"leaf_solution_updates\":"<<leafCalls<<",\"outcome_anomalies\":"<<outcomeAnomalies<<'}';
 o<<",\"sampling\":{\"A_seen\":"<<aSeen<<",\"first_A_saved\":"<<(firstA.used?"true":"false")<<",\"first_A_unsaved_bytes\":"<<firstAUnsavedBytes<<",\"reservoir_used\":"<<count_if(slots.begin(),slots.end(),[](const Sample&s){return s.used;})<<",\"excluded_for_size\":"<<excludedForSize<<",\"seed\":"<<seed<<",\"K\":"<<K<<'}';
 o<<"}\n";return o.str();
}
void checkpoint(const string&status,bool final){
 string bin,meta=samplesJson(bin);
 atomicWrite(directory+"/samples.bin",bin);atomicWrite(directory+"/samples.json",meta);
 atomicWrite(directory+(final?"/summary.json":"/summary.partial.json"),summaryJson(status));
}
}

const char* StageC::phaseName(int p){static const char*n[]={"cao_max_degree","chen_hint","chen_fallback","lp_root","lp_neighbor"};return n[p];}
void StageC::init(int argc,char**argv){
 variant=argc>1?argv[1]:"8";
 const char* p=getenv("STAGE_DIR");directory=p?p:".";
 p=getenv("STAGE_GRAPH");graphId=p?p:"unknown";
 p=getenv("STAGE_RUN");runId=p?p:"unknown";
 p=getenv("STAGE_CPU_LIMIT");if(p)cpuLimit=atof(p);
 p=getenv("STAGE_RESERVE_BYTES");if(p)reserveBytes=strtoull(p,0,10);
 p=getenv("STAGE_SAMPLE_SEED");if(p)seed=strtoull(p,0,10);
 p=getenv("STAGE_SAMPLE_K");if(p)K=strtoull(p,0,10);
 p=getenv("STAGE_FIRST_CAP_BYTES");if(p)firstCap=strtoull(p,0,10);
 p=getenv("STAGE_SLOT_CAP_BYTES");if(p)slotCap=strtoull(p,0,10);
 p=getenv("STAGE_EVENT_LOG");eventLog=p&&string(p)=="1";
 slots.assign(K,Sample());
 if(argc==6 && string(argv[2])=="--replay"){replayMode=true;replayFile=argv[3];replayOffset=strtoull(argv[4],0,10);replayLength=strtoull(argv[5],0,10);}
 if(eventLog){events.open(directory+"/events.jsonl",ios::binary);if(!events)throw runtime_error("cannot open event log");}
}
bool StageC::isReplay(){return replayMode;}
void StageC::guard(){
 auto now=chrono::steady_clock::now();if(now-lastCheck<chrono::milliseconds(100))return;lastCheck=now;
 if(GetFileAttributesA((directory+"/STOP").c_str())!=INVALID_FILE_ATTRIBUTES)throw StageStop{"external_stop",75};
 if(cpu()>=cpuLimit)throw StageStop{"cpu_timeout",74};
 ULARGE_INTEGER free;if(!GetDiskFreeSpaceExA(directory.c_str(),&free,0,0))throw StageStop{"disk_query_failed",76};
 if(free.QuadPart<=reserveBytes)throw StageStop{"disk_reserve",73};
 if(!replayMode&&now-lastCheckpoint>=chrono::seconds(30)){lastCheckpoint=now;checkpoint("running",false);}
}
// ---- search nodes -------------------------------------------------------------------------
StageFrame::StageFrame(int proc,BranchingSolution*s){++level;frames.push_back(FrameRec{proc,false,leafStamp,s});nodesEntered[proc][s->isSub?1:0]++;StageC::guard();}
StageFrame::~StageFrame(){FrameRec f=frames.back();if(!f.set){int o=uncaught_exception()?StageC::OUT_INTERRUPTED:StageC::OUT_UNCLASSIFIED;outcomes[f.proc][o]++;if(o==StageC::OUT_UNCLASSIFIED)++outcomeAnomalies;}frames.pop_back();--level;}
void StageC::outcome(int o){if(frames.empty())return;FrameRec&f=frames.back();if(f.set){++outcomeAnomalies;return;}f.set=true;outcomes[f.proc][o]++;}
void StageC::leaf(BranchingSolution*s){++leafStamp;leafLevel=level;leafSolver=s;++leafCalls;}
// reduce() returned RED_NOSOLUTION: a leaf if this node's own reduce() called trySolUpdate, else pruned.
void StageC::noSolution(BranchingSolution*s){if(frames.empty())return;FrameRec&f=frames.back();outcome(leafStamp>f.leafStampAtEntry&&leafLevel==level&&leafSolver==s?OUT_LEAF:OUT_PRUNED);}

// ---- states --------------------------------------------------------------------------------
#define GRAPH_FIELDS(APPLY) APPLY(N) APPLY(M) APPLY(deleted) APPLY(changeInU) APPLY(neighbours) APPLY(neighDouble) APPLY(doubleNum) APPLY(posAtNeigh) APPLY(status) APPLY(oldNumbers) APPLY(X) APPLY(selfLoops) APPLY(deg2ToReduce) APPLY(vis) APPLY(ccNr) APPLY(ccVertices) APPLY(fuRepr) APPLY(fuWeight) APPLY(stageNames)
string StageC::state(BranchingSolution*s,Graph&g,int phase,int pivot,int root){
 Archive a;string magic="STAGEC1";a.io(magic);a.io(variant);a.io(level);a.io(phase);a.io(pivot);a.io(root);
 #define FIELD(f) a.io(g.f);
 GRAPH_FIELDS(FIELD)
 #undef FIELD
 a.io(s->solFound);a.io(s->branching_hints);a.io(s->sol);a.io(s->isSub);a.io(s->depth);a.io(s->size_cap);a.io(s->stageHint);
 if(variant=="8")a.io(dynamic_cast<Sol8*>(s)->br2);
 if(variant=="LP")a.io(dynamic_cast<HalfIntBranching*>(s)->kernelize_switch);
 return a.data;
}
void StageC::restore(const string&bytes,BranchingSolution*&s,Graph&g,int&phase,int&pivot,int&root){
 Archive a(bytes);string magic,storedVariant;a.io(magic);a.io(storedVariant);if(magic!="STAGEC1"||storedVariant!=variant)throw runtime_error("snapshot schema/variant mismatch");
 a.io(level);a.io(phase);a.io(pivot);a.io(root);
 #define FIELD(f) a.io(g.f);
 GRAPH_FIELDS(FIELD)
 #undef FIELD
 if(variant=="8")s=new Sol8();else if(variant=="5")s=new Sol5();else s=new HalfIntBranching();
 a.io(s->solFound);a.io(s->branching_hints);a.io(s->sol);a.io(s->isSub);a.io(s->depth);a.io(s->size_cap);a.io(s->stageHint);
 if(variant=="8")a.io(dynamic_cast<Sol8*>(s)->br2);
 if(variant=="LP")a.io(dynamic_cast<HalfIntBranching*>(s)->kernelize_switch);
 if(a.pos!=bytes.size())throw runtime_error("snapshot trailing bytes");
}

// ---- decision classification -----------------------------------------------------------------
StageAnalysis StageC::analyze(BranchingSolution*s,Graph&g,int phase,int pivot,int root){
 StageAnalysis r;
 if(variant=="8"){
   // Sol8 pivot = Graph::getMaxDegVWDouble: first STATUS_NONE vertex with maximal degWithDouble (> 0).
   r.phase=0;r.target=true;int best=0;
   for(int i=0;i<g.N;++i)if(g.isNone(i)&&g.degWithDouble(i)>best)best=g.degWithDouble(i);
   for(int i=0;i<g.N;++i)if(g.isNone(i)&&g.degWithDouble(i)==best)r.candidates.push_back(i);
   r.pivotEligible=g.isNone(pivot)&&g.degWithDouble(pivot)==best;
 }else if(variant=="5"){
   // ICBranchingSolution: a popped usable hint, else Graph::getMaxDegToUndeletable, whose candidate
   // domain is every STATUS_NONE vertex (ranked by edges into U, then degWithDouble; any score can win).
   if(s->stageHint){r.phase=1;}
   else{
    r.phase=2;r.target=true;r.chen=true;
    for(int i=0;i<g.N;++i)if(g.isNone(i))r.candidates.push_back(i);
    r.pivotEligible=g.isNone(pivot);
    DSU n(g.N),u(g.N);
    for(int i=0;i<g.N;++i)for(size_t j=0;j<g.neighbours[i].size();++j){int v=g.neighbours[i][j];if(i>v)continue;
      if(g.isNone(i)&&g.isNone(v)){if(!n.join(i,v)||g.neighDouble[i][j])r.undecidedForest=false;}
      if(g.isInU(i)&&g.isInU(v)){if(!u.join(i,v)||g.neighDouble[i][j])r.undeletableForest=false;}
    }
    map<int,int> graphToUF,ufToGraph;
    auto ufroot=[&](int x){int steps=0;while(g.fuRepr[x]>=0){x=g.fuRepr[x];if(++steps>g.N)return -1;}return x;};
    for(int i=0;i<g.N;++i)if(g.isInU(i)){int a=u.find(i),b=ufroot(i);if(b<0)r.ufMatches=false;
      if(graphToUF.count(a)&&graphToUF[a]!=b)r.ufMatches=false;if(ufToGraph.count(b)&&ufToGraph[b]!=a)r.ufMatches=false;graphToUF[a]=b;ufToGraph[b]=a;}
    for(int i=0;i<g.N;++i)if(g.isNone(i)){set<int> touched;for(size_t j=0;j<g.neighbours[i].size();++j){int v=g.neighbours[i][j];if(g.isInU(v)){if(!touched.insert(u.find(v)).second||g.neighDouble[i][j])r.uniqueTouch=false;}}
      if(touched.size()>=2)r.mergeCandidates.push_back(i);}
    r.qualifying=r.undecidedForest&&r.undeletableForest&&r.uniqueTouch&&r.ufMatches;
    r.strictA=r.qualifying&&r.mergeCandidates.size()>=2;
   }
 }else if(phase==1){r.phase=3;}
 else{
   // solve2 neighbour branch: distinct STATUS_NONE neighbours of the root s in adjacency order.
   r.phase=4;r.target=true;set<int> seen;
   for(int v:g.neighbours[root])if(g.isNone(v)&&seen.insert(v).second)r.candidates.push_back(v);
   r.pivotEligible=seen.count(pivot)>0;
 }
 r.ambiguous=r.target&&r.candidates.size()>=2;
 return r;
}
StageDecision::StageDecision(BranchingSolution*s,Graph&g,int ph,int v,int r):solver(s),graph(g),phase(ph),pivot(v),root(r),saved(0){
 // Event description for saved states only (never built for unsaved decisions).
 auto payloadJson=[&](const StageAnalysis&r,int pivot,int root)->string{
 ostringstream o;o<<"{\"phase\":"<<quote(StageC::phaseName(r.phase))<<",\"depth\":"<<level<<",\"solver_depth\":"<<s->depth<<",\"component_subsolver\":"<<(s->isSub?"true":"false")
  <<",\"local_pivot\":"<<pivot<<",\"original_pivot\":"<<quote(g.stageNames[pivot])<<",\"root\":"<<(root<0?"null":quote(g.stageNames[root]))<<",\"candidate_count\":"<<r.candidates.size()
  <<",\"pivot_eligible\":"<<(r.pivotEligible?"true":"false")<<",\"T\":"<<(r.target?"true":"false")<<",\"A\":"<<(r.ambiguous?"true":"false");
 if(r.chen)o<<",\"undecided_forest\":"<<(r.undecidedForest?"true":"false")<<",\"undeletable_forest\":"<<(r.undeletableForest?"true":"false")<<",\"unique_undeletable_component_touch\":"<<(r.uniqueTouch?"true":"false")
  <<",\"union_find_partition_matches\":"<<(r.ufMatches?"true":"false")<<",\"qualifying_state\":"<<(r.qualifying?"true":"false")<<",\"A_chen_strict_merge\":"<<(r.strictA?"true":"false")<<",\"merge_candidates\":"<<labels(g,r.mergeCandidates);
 o<<'}';return o.str();
 };
 StageC::guard();StageC::outcome(StageC::OUT_BRANCH);
 StageAnalysis an=StageC::analyze(s,g,ph,v,r);ambiguous=an.ambiguous;
 string pn=StageC::phaseName(an.phase);
 startHash=prefix;startCount=traceCount;id=B+1;
 ++B;if(s->isSub)++componentB;counters["phase:"+pn]++;
 hist["B_by_depth:"+pn][level]++;hist["B_by_solver_depth:"+pn][s->depth]++;
 if(an.target){++T;hist["T_candidate_count:"+pn][(long long)an.candidates.size()]++;if(!an.pivotEligible)counters["anomaly:pivot_not_in_eligible_set:"+pn]++;}
 if(an.ambiguous){++A;hist["A_by_depth:"+pn][level]++;}
 if(an.chen){
   hist["chen_merge_candidate_count"][(long long)an.mergeCandidates.size()]++;
   counters["chen:undecided_forest_false"]+=!an.undecidedForest;counters["chen:undeletable_forest_false"]+=!an.undeletableForest;
   counters["chen:unique_undeletable_touch_false"]+=!an.uniqueTouch;counters["chen:union_find_partition_mismatch"]+=!an.ufMatches;
   counters["chen:invariant_failure"]+=!(an.undeletableForest&&an.uniqueTouch&&an.ufMatches);counters["chen:qualifying_state"]+=an.qualifying;
   counters["chen:pivot_is_merge_candidate"]+=binary_search(an.mergeCandidates.begin(),an.mergeCandidates.end(),v);
   if(an.strictA){++Astrict;hist["A_chen_strict_merge_by_depth"][level]++;}
 }
 uint64_t key[4]={uint64_t(an.phase),uint64_t(level),uint64_t(v),uint64_t(an.candidates.size())};
 prefix=prefix*P+hashBytes(key,sizeof key);++traceCount;
 if(eventLog){events<<"{\"sequence\":"<<id<<",\"phase\":"<<quote(pn)<<",\"depth\":"<<level<<",\"solver_depth\":"<<s->depth<<",\"component_subsolver\":"<<(s->isSub?"true":"false")<<",\"original_pivot\":"<<quote(g.stageNames[v])<<",\"candidate_count\":"<<an.candidates.size()<<",\"merge_candidate_count\":"<<an.mergeCandidates.size()<<",\"qualifying_state\":"<<(an.qualifying?"true":"false")<<",\"T\":"<<(an.target?"true":"false")<<",\"A\":"<<(an.ambiguous?"true":"false")<<",\"A_chen_strict_merge\":"<<(an.strictA?"true":"false")<<"}\n";events.flush();}
 if(!an.ambiguous||replayMode)return;
 ++aSeen;
 auto make=[&](Sample&dst){dst=Sample();dst.used=true;dst.seq=id;dst.aIndex=aSeen;dst.state=StageC::state(s,g,ph,v,r);dst.cands=an.candidates;dst.payload=payloadJson(an,v,r);};
 if(aSeen==1){
   Sample tmp;make(tmp);uint64_t bytes=tmp.state.size()+4*tmp.cands.size();
   if(bytes<=firstCap){firstA=std::move(tmp);saved=1;selectionLog.push_back(id);++selections;}else firstAUnsavedBytes=bytes;
   return;
 }
 uint64_t i=aSeen-1,slot;
 if(i<=K)slot=i-1;else{uint64_t rr=mix(seed+i)%i;if(rr>=K)return;slot=rr;}
 Sample tmp;make(tmp);uint64_t bytes=tmp.state.size()+4*tmp.cands.size();
 if(bytes>slotCap){++excludedForSize;largestExcluded=max(largestExcluded,bytes);if(excludedLog.size()<1000)excludedLog.push_back(id);return;}
 slots[slot]=std::move(tmp);saved=2+int(slot);selectionLog.push_back(id);++selections;
}
StageDecision::~StageDecision(){
 bool isFirstReplay=replayMode&&id==1;
 Sample*target=nullptr;
 if(saved==1&&firstA.seq==id)target=&firstA;else if(saved>=2&&slots[saved-2].seq==id)target=&slots[saved-2];
 if(!target&&!isFirstReplay)return;
 bool complete=!uncaught_exception();uint64_t count=traceCount-startCount;
 string digest="\""+to_string(prefix-startHash*power(P,count))+"\"";
 string finalHash=complete?"\""+to_string(hashString(StageC::state(solver,graph,phase,pivot,root)))+"\"":"null";
 if(target){target->contDone=true;target->complete=complete;target->traceCount=count;target->digest=digest;target->finalHash=finalHash;}
 if(isFirstReplay){try{ofstream f(directory+"/replay_result.json");f<<"{\"complete\":"<<(complete?"true":"false")<<",\"trace_count\":"<<count<<",\"trace_digest\":"<<digest<<",\"final_state_hash\":"<<finalHash<<"}\n";}catch(...){}}
}
void StageC::finish(const string&status){if(eventLog)events.flush();if(!replayMode)checkpoint(status,true);else atomicWrite(directory+"/summary.json",summaryJson(status));}
int StageC::replay(){
 ifstream in(replayFile,ios::binary);in.seekg(replayOffset);string bytes(replayLength,'\0');in.read(&bytes[0],bytes.size());if(!in)throw runtime_error("snapshot read failed");
 BranchingSolution*s=nullptr;Graph g;int phase,pivot,root;restore(bytes,s,g,phase,pivot,root);
 if(state(s,g,phase,pivot,root)!=bytes)throw runtime_error("snapshot round-trip mismatch");
 try {if(phase==0)s->stageContinue(g,pivot);else if(phase==1)dynamic_cast<HalfIntBranching*>(s)->stageRoot(g,root);else dynamic_cast<HalfIntBranching*>(s)->stageNeighbor(g,root,pivot);}
 catch(const StageStop&stop){finish(stop.reason);delete s;return stop.code;}
 finish("completed");delete s;return 0;
}
