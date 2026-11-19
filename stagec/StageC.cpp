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
using namespace std;
// Stage C instrumentation, GitHub Actions edition (schema STAGEC1, unchanged).
// Difference from the local edition: snapshots, events and continuation records
// are written to numbered segment files (<stream>/seg-NNNNNN.<ext>) so that a
// sidecar can losslessly compress closed segments while the search runs.
// Concatenating a stream's segments in index order yields exactly the bytes the
// local edition wrote to its single file; every event keeps that global offset.
namespace {
string directory,variant,graphId,runId,replayFile;
uint64_t replayOffset=0,replayLength=0;
struct Segmented {
 string dir,ext; uint64_t limit=256ULL<<20,global=0,inSeg=0; int index=-1; ofstream out;
 void start(const string&d,const string&e,uint64_t lim){dir=d;ext=e;limit=lim;CreateDirectoryA(dir.c_str(),0);next();}
 // The previous segment is closed before the next file is created: the sidecar
 // treats a segment as closed exactly when a higher-numbered one exists.
 void next(){if(out.is_open())out.close();++index;char n[32];snprintf(n,sizeof n,"/seg-%06d",index);out.open(dir+n+ext,ios::binary);inSeg=0;if(!out)throw runtime_error("cannot open segment "+dir);}
 void write(const string&s,int&seg,uint64_t&local,uint64_t&glob){if(inSeg>0&&inSeg+s.size()>limit)next();seg=index;local=inSeg;glob=global;out.write(s.data(),s.size());out.flush();if(!out)throw StageStop{"io_error",77};inSeg+=s.size();global+=s.size();}
 void write(const string&s){int a;uint64_t b,c;write(s,a,b,c);}
 void flush(){if(out.is_open())out.flush();}
 bool open()const{return out.is_open();}
};
Segmented events,snapshots,continuationLog;
uint64_t B=0,T=0,A=0,prefix=0,traceCount=0,snapshotBytes=0;
const uint64_t P=1099511628211ULL;
int level=-1;
bool replayMode=false;
uint64_t reserveBytes=10ULL*1024*1024*1024;
auto lastCheck=chrono::steady_clock::now()-chrono::seconds(1);
double cpuLimit=1800;
double cpu(){FILETIME a,b,c,d;GetProcessTimes(GetCurrentProcess(),&a,&b,&c,&d);return ((uint64_t(c.dwHighDateTime)<<32)+c.dwLowDateTime+(uint64_t(d.dwHighDateTime)<<32)+d.dwLowDateTime)/1e7;}
uint64_t hashString(const string&s){uint64_t h=14695981039346656037ULL;for(unsigned char c:s){h^=c;h*=P;}return h;}
uint64_t power(uint64_t p,uint64_t n){uint64_t r=1;while(n){if(n&1)r*=p;p*=p;n>>=1;}return r;}
string quote(const string&s){ostringstream o;o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<c;else if(c<32)o<<"\\u"<<hex<<setw(4)<<setfill('0')<<int(c)<<dec;else o<<c;}o<<'"';return o.str();}
string ids(Graph&g,const vector<int>&v){ostringstream o;o<<'[';for(size_t i=0;i<v.size();++i){if(i)o<<',';o<<quote(g.stageNames[v[i]]);}o<<']';return o.str();}
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
}

void StageC::init(int argc,char**argv){
 variant=argc>1?argv[1]:"8";
 const char* p=getenv("STAGE_DIR");directory=p?p:".";
 p=getenv("STAGE_GRAPH");graphId=p?p:"unknown";
 p=getenv("STAGE_RUN");runId=p?p:"unknown";
 p=getenv("STAGE_CPU_LIMIT");if(p)cpuLimit=atof(p);
 p=getenv("STAGE_RESERVE_BYTES");if(p)reserveBytes=strtoull(p,0,10);
 uint64_t segmentBytes=256ULL<<20;p=getenv("STAGE_SEGMENT_BYTES");if(p)segmentBytes=strtoull(p,0,10);
 if(argc==6 && string(argv[2])=="--replay"){replayMode=true;replayFile=argv[3];replayOffset=strtoull(argv[4],0,10);replayLength=strtoull(argv[5],0,10);}
 events.start(directory+"/events",".jsonl",segmentBytes);continuationLog.start(directory+"/continuations",".jsonl",segmentBytes);
 if(!replayMode)snapshots.start(directory+"/snapshots",".bin",segmentBytes);
}
bool StageC::isReplay(){return replayMode;}
void StageC::guard(){
 auto now=chrono::steady_clock::now();if(now-lastCheck<chrono::milliseconds(100))return;lastCheck=now;
 if(GetFileAttributesA((directory+"/STOP").c_str())!=INVALID_FILE_ATTRIBUTES)throw StageStop{"external_stop",75};
 if(cpu()>=cpuLimit)throw StageStop{"cpu_timeout",74};
 ULARGE_INTEGER free;if(!GetDiskFreeSpaceExA(directory.c_str(),&free,0,0))throw StageStop{"disk_query_failed",76};
 if(free.QuadPart<=reserveBytes)throw StageStop{"disk_reserve",73};
}
StageFrame::StageFrame(){++level;StageC::guard();}
StageFrame::~StageFrame(){--level;}

// The field list is deliberately exhaustive, including caches and queue order.
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
string StageC::decision(BranchingSolution*s,Graph&g,int phase,int pivot,int root,bool&target,bool&ambiguous){
 vector<int> candidates;string name,flags="";
 target=false;
 if(variant=="8"){
   target=true;name="cao_max_degree";int score=g.degWithDouble(pivot);
   for(int i=0;i<g.N;++i)if(g.isNone(i)&&g.degWithDouble(i)==score)candidates.push_back(i);
 }else if(variant=="5"){
   target=!s->stageHint;name=target?"chen_fallback":"chen_hint";
   if(target){
    DSU n(g.N),u(g.N);bool nforest=true,uforest=true,uniqueTouch=true,ufConsistent=true;
    for(int i=0;i<g.N;++i)for(size_t j=0;j<g.neighbours[i].size();++j){int v=g.neighbours[i][j];if(i>v)continue;
      if(g.isNone(i)&&g.isNone(v)){if(!n.join(i,v)||g.neighDouble[i][j])nforest=false;}
      if(g.isInU(i)&&g.isInU(v)){if(!u.join(i,v)||g.neighDouble[i][j])uforest=false;}
    }
    map<int,int> graphToUF,ufToGraph;
    auto ufroot=[&](int x){int steps=0;while(g.fuRepr[x]>=0){x=g.fuRepr[x];if(++steps>g.N)return -1;}return x;};
    for(int i=0;i<g.N;++i)if(g.isInU(i)){int a=u.find(i),b=ufroot(i);if(b<0)ufConsistent=false;
      if(graphToUF.count(a)&&graphToUF[a]!=b)ufConsistent=false;if(ufToGraph.count(b)&&ufToGraph[b]!=a)ufConsistent=false;graphToUF[a]=b;ufToGraph[b]=a;}
    for(int i=0;i<g.N;++i)if(g.isNone(i)){set<int> touched;for(size_t j=0;j<g.neighbours[i].size();++j){int v=g.neighbours[i][j];if(g.isInU(v)){if(!touched.insert(u.find(v)).second||g.neighDouble[i][j])uniqueTouch=false;}}
      if(touched.size()>=2)candidates.push_back(i);
    }
    bool qualified=nforest&&uforest&&uniqueTouch&&ufConsistent;
    flags=",\"undecided_forest\":"+string(nforest?"true":"false")+",\"undeletable_forest\":"+(uforest?"true":"false")+",\"unique_undeletable_component_touch\":"+(uniqueTouch?"true":"false")+",\"union_find_partition_matches\":"+(ufConsistent?"true":"false")+",\"invariants_hold\":"+(uforest&&uniqueTouch&&ufConsistent?"true":"false")+",\"qualifying_state\":"+(qualified?"true":"false")+",\"raw_touch_candidates\":"+ids(g,candidates);
    if(!qualified)candidates.clear();
   }
 }else if(phase==1){name="lp_root";}else{
   target=true;name="lp_neighbor";set<int> seen;
   for(int v:g.neighbours[root])if(g.isNone(v)&&seen.insert(v).second)candidates.push_back(v);
   flags=",\"pivot_eligible\":"+string(find(candidates.begin(),candidates.end(),pivot)!=candidates.end()?"true":"false");
 }
 ambiguous=target&&candidates.size()>=2;
 ostringstream o;o<<"\"phase\":"<<quote(name)<<",\"depth\":"<<level<<",\"solver_depth\":"<<s->depth<<",\"component_subsolver\":"<<(s->isSub?"true":"false")<<",\"local_pivot\":"<<pivot<<",\"original_pivot\":"<<quote(g.stageNames[pivot])<<",\"root\":"<<(root<0?"null":quote(g.stageNames[root]))<<",\"candidate_ids\":"<<ids(g,candidates)<<",\"candidate_count\":"<<candidates.size()<<",\"B\":true,\"T\":"<<(target?"true":"false")<<",\"A\":"<<(ambiguous?"true":"false")<<flags;
 return o.str();
}
StageDecision::StageDecision(BranchingSolution*s,Graph&g,int ph,int v,int r):solver(s),graph(g),phase(ph),pivot(v),root(r){
 StageC::guard();bool target;string payload=StageC::decision(s,g,ph,v,r,target,ambiguous);
 startHash=prefix;startCount=traceCount;
 id=B+1;
 uint64_t offset=0,length=0,local=0;int segment=-1;string stateHash="null";
 if(ambiguous&&!replayMode){string bytes=StageC::state(s,g,ph,v,r);length=bytes.size();
  ULARGE_INTEGER free;if(!GetDiskFreeSpaceExA(directory.c_str(),&free,0,0)||free.QuadPart<=reserveBytes+length+1024*1024)throw StageStop{"disk_reserve",73};
  snapshots.write(bytes,segment,local,offset);snapshotBytes+=length;stateHash=quote(to_string(hashString(bytes)));}
 ostringstream o;o<<"{\"event_id\":"<<quote(runId+":"+to_string(id))<<",\"sequence\":"<<id<<",\"graph\":"<<quote(graphId)<<",\"solver\":"<<quote(variant)<<","<<payload<<",\"snapshot_offset\":"<<offset<<",\"snapshot_bytes\":"<<length<<",\"snapshot_segment\":"<<(segment<0?string("null"):to_string(segment))<<",\"snapshot_segment_offset\":"<<local<<",\"snapshot_hash\":"<<stateHash<<"}\n";
 events.write(o.str());
 prefix=prefix*P+hashString(payload);++traceCount;++B;if(target)++T;if(ambiguous)++A;
}
StageDecision::~StageDecision(){
 if(!ambiguous && !replayMode)return;
 bool complete=!uncaught_exception();uint64_t count=traceCount-startCount;
 string finalHash=complete?quote(to_string(hashString(StageC::state(solver,graph,phase,pivot,root)))):"null";
 ostringstream o;o<<"{\"sequence\":"<<id<<",\"complete\":"<<(complete?"true":"false")<<",\"trace_count\":"<<count<<",\"trace_digest\":"<<quote(to_string(prefix-startHash*power(P,count)))<<",\"final_state_hash\":"<<finalHash<<"}\n";
 // Destructors are noexcept: an I/O failure here is detected by the runner as a
 // missing continuation record, never by terminating the process.
 try{continuationLog.write(o.str());}catch(...){}
}
void StageC::finish(const string&status){ofstream f(directory+"/solver_summary.json");f<<"{\"status\":"<<quote(status)<<",\"B\":"<<B<<",\"T\":"<<T<<",\"A\":"<<A<<",\"snapshot_bytes\":"<<snapshotBytes<<",\"cpu_s\":"<<setprecision(15)<<cpu()<<",\"trace_count\":"<<traceCount<<",\"trace_digest\":"<<quote(to_string(prefix))<<",\"segments\":{\"events\":"<<events.index+1<<",\"snapshots\":"<<snapshots.index+1<<",\"continuations\":"<<continuationLog.index+1<<"}}\n";events.flush();continuationLog.flush();snapshots.flush();}
int StageC::replay(){
 ifstream in(replayFile,ios::binary);in.seekg(replayOffset);string bytes(replayLength,'\0');in.read(&bytes[0],bytes.size());if(!in)throw runtime_error("snapshot read failed");
 BranchingSolution*s=nullptr;Graph g;int phase,pivot,root;restore(bytes,s,g,phase,pivot,root);
 if(state(s,g,phase,pivot,root)!=bytes)throw runtime_error("snapshot round-trip mismatch");
 try {if(phase==0)s->stageContinue(g,pivot);else if(phase==1)dynamic_cast<HalfIntBranching*>(s)->stageRoot(g,root);else dynamic_cast<HalfIntBranching*>(s)->stageNeighbor(g,root,pivot);}
 catch(const StageStop&stop){finish(stop.reason);delete s;return stop.code;}
 finish("completed");delete s;return 0;
}
