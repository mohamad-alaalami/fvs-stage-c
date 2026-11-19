// Offline validation of saved Stage C states; never searches, never tries another pivot.
// stdin (binary), per sample: "<sequence> <state_bytes> <candidate_count>\n", state bytes, int32 candidates.
// For each sample: restore -> re-serialize (byte equality) -> re-classify (same phase, A, eligible set)
// -> re-run the ORIGINAL selector on the restored state and confirm it returns the recorded pivot.
#include "solutions/HalfIntBranching.h"
#include "solutions/SolutionVariants.h"
#include <iostream>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <io.h>
#include <fcntl.h>
using namespace std;
static bool readLine(string&s){s.clear();int c;while((c=getchar())!=EOF){if(c=='\n')return true;s.push_back(char(c));}return !s.empty();}
static void readBytes(string&s,size_t n){s.assign(n,'\0');if(n&&fread(&s[0],1,n,stdin)!=n)throw runtime_error("truncated sample stream");}
int main(int argc,char**argv){
 if(argc!=2)return 2;
 _setmode(_fileno(stdin),_O_BINARY);
 StageC::init(argc,argv);
 string line,data,cbytes;int checked=0,failed=0;
 try{
 while(readLine(line)){
   unsigned long long seq,len,cc;if(sscanf(line.c_str(),"%llu %llu %llu",&seq,&len,&cc)!=3)throw runtime_error("bad header");
   readBytes(data,len);readBytes(cbytes,cc*4);vector<int> stored(cc);if(cc)memcpy(stored.data(),cbytes.data(),cc*4);
   Graph g;BranchingSolution*s=nullptr;int phase,pivot,root;StageC::restore(data,s,g,phase,pivot,root);
   bool roundtrip=StageC::state(s,g,phase,pivot,root)==data;
   StageAnalysis an=StageC::analyze(s,g,phase,pivot,root);
   bool candidatesMatch=an.candidates==stored;
   bool pivotInCandidates=find(an.candidates.begin(),an.candidates.end(),pivot)!=an.candidates.end();
   int selected=-2;string selector;
   if(phase==0){selector=argv[1][0]=='8'?"Sol8::chooseBranchingVertex (getMaxDegVWDouble)":"ICBranchingSolution::chooseBranchingVertex (hints, then getMaxDegToUndeletable)";selected=s->chooseBranchingVertex(g);}
   else if(phase==2){selector="Graph::getMaxDegNeigh(root)";selected=g.getMaxDegNeigh(root).first;}
   else {selector="Graph::getMaxDegV";selected=g.getMaxDegV().first;}
   bool ok=roundtrip&&candidatesMatch&&an.ambiguous&&an.pivotEligible&&pivotInCandidates&&selected==pivot;
   ++checked;failed+=!ok;
   cout<<"{\"sequence\":"<<seq<<",\"phase\":\""<<StageC::phaseName(an.phase)<<"\",\"roundtrip\":"<<(roundtrip?"true":"false")<<",\"candidates_match\":"<<(candidatesMatch?"true":"false")
       <<",\"A\":"<<(an.ambiguous?"true":"false")<<",\"pivot_eligible\":"<<(an.pivotEligible?"true":"false")<<",\"pivot_in_candidates\":"<<(pivotInCandidates?"true":"false")
       <<",\"selector\":\""<<selector<<"\",\"selector_pivot\":"<<selected<<",\"recorded_pivot\":"<<pivot<<",\"selector_matches\":"<<(selected==pivot?"true":"false")<<",\"ok\":"<<(ok?"true":"false")<<"}\n";
   delete s;
 }
 }catch(const exception&e){cerr<<e.what()<<" after "<<checked<<" samples\n";return 4;}
 cerr<<"checked "<<checked<<" failed "<<failed<<"\n";
 return failed?5:0;
}
