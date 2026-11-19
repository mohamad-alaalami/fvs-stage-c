// Offline validation only: never enters any search or chooses a pivot.
// Input on stdin (binary): every complete event line in sequence order; each line
// whose A flag is true is immediately followed by exactly snapshot_bytes raw bytes
// of that event's snapshot. The Python runner produces this stream from the
// (possibly compressed) segment files, so no full raw copy is needed on disk.
#include "solutions/HalfIntBranching.h"
#include "solutions/SolutionVariants.h"
#include <iostream>
#include <set>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <io.h>
#include <fcntl.h>
using namespace std;
static uint64_t field(const string&line,const string&key){size_t p=line.find("\""+key+"\":");if(p==string::npos)throw runtime_error("missing field "+key);return strtoull(line.c_str()+p+key.size()+3,0,10);}
static bool flag(const string&line,const string&key){return line.find("\""+key+"\":true")!=string::npos;}
struct Input {
 vector<char> buf=vector<char>(1<<20);size_t pos=0,len=0;
 bool fill(){pos=0;len=fread(buf.data(),1,buf.size(),stdin);return len>0;}
 bool line(string&s){s.clear();while(true){if(pos==len&&!fill())return !s.empty();char*b=buf.data()+pos;char*nl=(char*)memchr(b,'\n',len-pos);if(nl){s.append(b,nl-b);pos+=nl-b+1;return true;}s.append(b,len-pos);pos=len;}}
 void bytes(string&s,uint64_t n){s.clear();s.reserve(n);while(s.size()<n){if(pos==len&&!fill())throw runtime_error("truncated snapshot stream");size_t k=min<uint64_t>(n-s.size(),len-pos);s.append(buf.data()+pos,k);pos+=k;}}
};
int main(int argc,char**argv){
 if(argc!=2)return 2;
 _setmode(_fileno(stdin),_O_BINARY);
 StageC::init(argc,argv); // variant and a separate audit-output directory only
 Input in;
 uint64_t B=0,T=0,A=0,bytes=0,largest=0,largestSeq=0,components=0,invariants=0,nonforest=0;string line,data;
 try {
 while(in.line(line)){
   if(line.empty()||line.back()!='}')throw runtime_error("partial event line");
   bool b=flag(line,"B"),t=flag(line,"T"),a=flag(line,"A");
   if(!b||b<t||t<a||field(line,"sequence")!=B+1)throw runtime_error("event count/order invariant");
   ++B;T+=t;A+=a;components+=flag(line,"component_subsolver");
   invariants+=line.find("\"invariants_hold\":false")!=string::npos;
   nonforest+=line.find("\"undecided_forest\":false")!=string::npos;
   // PACE vertex labels in this selected dataset are decimal strings. Parse the
   // exact serialized candidate array without converting labels to integers.
   size_t start=line.find("\"candidate_ids\":[");if(start==string::npos)throw runtime_error("missing candidates");start+=17;
   size_t end=line.find(']',start);if(end==string::npos)throw runtime_error("bad candidates");
   set<string> unique;size_t cur=start;uint64_t count=0;
   while(cur<end){size_t q=line.find('"',cur);if(q==string::npos||q>=end)break;size_t r=line.find('"',q+1);if(r==string::npos||r>=end)throw runtime_error("bad candidate string");string id=line.substr(q+1,r-q-1);if(!unique.insert(id).second)throw runtime_error("duplicate candidate");++count;cur=r+1;}
   if(count!=field(line,"candidate_count")||a!=(t&&count>=2))throw runtime_error("candidate count/A mismatch");
   if(!a)continue;
   uint64_t length=field(line,"snapshot_bytes");if(!length)throw runtime_error("missing A snapshot");
   in.bytes(data,length);
   Graph graph;BranchingSolution*solver=nullptr;int phase,pivot,root;
   StageC::restore(data,solver,graph,phase,pivot,root);
   if(StageC::state(solver,graph,phase,pivot,root)!=data)throw runtime_error("state roundtrip mismatch");
   bool target,ambiguous;string payload=StageC::decision(solver,graph,phase,pivot,root,target,ambiguous);
   if(!ambiguous||!target||line.find(payload)==string::npos)throw runtime_error("restored decision differs from event");
   delete solver;bytes+=length;if(length>largest){largest=length;largestSeq=B;}
 }
 cout<<"{\"B\":"<<B<<",\"T\":"<<T<<",\"A\":"<<A<<",\"snapshot_count\":"<<A<<",\"snapshot_bytes\":"<<bytes<<",\"largest_snapshot_bytes\":"<<largest<<",\"largest_snapshot_sequence\":"<<largestSeq<<",\"component_events\":"<<components<<",\"invariant_failures\":"<<invariants<<",\"nonforest_fallbacks\":"<<nonforest<<",\"all_A_snapshots_readable\":true,\"all_A_roundtrips_and_decisions_match\":true}\n";
 }catch(const exception&e){cerr<<e.what()<<" at event "<<B<<"\n";return 4;}
 return 0;
}
