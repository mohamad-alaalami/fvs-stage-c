"""Create the instrumented source copy; never edit the pinned checkout.
Usage: python prepare.py <pinned upstream src dir> <destination dir>
The edit list is identical to the local Stage C prepare.py; only paths are parameters.
"""
import pathlib, shutil, sys
ROOT=pathlib.Path(__file__).resolve().parent
BASE_SRC=pathlib.Path(sys.argv[1]).resolve()
SRC=pathlib.Path(sys.argv[2]).resolve()
if SRC.exists(): raise SystemExit('destination already exists; preserve it')
shutil.copytree(BASE_SRC,SRC,ignore=shutil.ignore_patterns('build'))
def edit(file,old,new):
 p=SRC/file; s=p.read_text(); assert old in s,(file,old); p.write_text(s.replace(old,new))
edit('lib/Graph.h','class Graph {','class StageC;\nclass Graph {\n    friend class StageC;\npublic:\n    vector<string> stageNames;')
edit('lib/Graph.cpp','oldNumbers = oldNums;','oldNumbers = oldNums;\n    for (int i=0;i<n;++i) stageNames[i]=full.stageNames[oldNums[i]];')
edit('lib/Graph.cpp','N = N_;','N = N_;\n    stageNames.resize(N);')
edit('solutions/Solution.h','#include <cassert>','#include <cassert>\n#include "../StageC.h"')
edit('solutions/Solution.h','class BranchingSolution : public Solution {','class BranchingSolution : public Solution {\n    friend class StageC;')
edit('solutions/Solution.h','    bool isSub;','    bool isSub;\npublic:\n    bool stageHint=false;\nprotected:')
edit('solutions/Solution.h','        while(true) {','        while(true) {\n            StageC::guard();')
edit('solutions/Solution.h','    void branching(Graph& brG) {','    void branching(Graph& brG) {\n        StageFrame frame;')
edit('solutions/Solution.h','        int v = chooseBranchingVertex(brG);','        stageHint=false;\n        int v = chooseBranchingVertex(brG);')
edit('solutions/Solution.h','        Graph g2(brG);','        stageContinue(brG,v);\n    }\n\n    void stageContinue(Graph& brG, int v) {\n        StageDecision decision(this,brG,0,v,-1);\n        Graph g2(brG);')
edit('solutions/SolutionVariants.h','class Sol8 : public BranchingSolution {','class Sol8 : public BranchingSolution {\n    friend class StageC;')
# Only change the ICBranchingSolution selector (first occurrence).
p=SRC/'solutions/SolutionVariants.h';s=p.read_text();s=s.replace('if (brG.isNone(v))\n                return v;','if (brG.isNone(v)) { stageHint=true; return v; }',1);p.write_text(s)
edit('solutions/HalfIntBranching.h','class HalfIntBranching : public BranchingSolution {','class HalfIntBranching : public BranchingSolution {\n    friend class StageC;')
edit('solutions/HalfIntBranching.h','    void solve1(Graph &g);','    void solve1(Graph &g);\n    void stageRoot(Graph &g,int s);\n    void stageNeighbor(Graph &g,int s,int v);')
edit('solutions/HalfIntBranching.cpp','void HalfIntBranching::solve1(Graph& g) {','void HalfIntBranching::solve1(Graph& g) {\n    StageFrame frame;')
edit('solutions/HalfIntBranching.cpp','void HalfIntBranching::solve2(Graph& g, int s) {','void HalfIntBranching::solve2(Graph& g, int s) {\n    StageFrame frame;')
edit('solutions/HalfIntBranching.cpp','    Graph g2(g);\n\n    g.putInSolution(s);','    stageRoot(g,s);\n}\n\nvoid HalfIntBranching::stageRoot(Graph& g,int s) {\n    StageDecision decision(this,g,1,s,s);\n    Graph g2(g);\n\n    g.putInSolution(s);')
edit('solutions/HalfIntBranching.cpp','        Graph g2(g);\n\n        g.putInSolution(v);','        stageNeighbor(g,s,v);\n    }\n}\n\nvoid HalfIntBranching::stageNeighbor(Graph& g,int s,int v) {\n        StageDecision decision(this,g,2,v,s);\n        Graph g2(g);\n\n        g.putInSolution(v);')
p=SRC/'solutions/HalfIntBranching.cpp';s=p.read_text();assert s.endswith('    }\n}\n');p.write_text(s[:-8]+'}\n')
edit('Main.cpp','    t.read_input(&g);','    StageC::init(argc,argv);\n    if (StageC::isReplay()) return StageC::replay();\n    t.read_input(&g);\n    for(int i=0;i<g.getN();++i) g.stageNames[i]=t.getName(i);')
edit('Main.cpp','    vector<int> sol = s->solve(g);','    vector<int> sol;\n    try { sol=s->solve(g); }\n    catch(const StageStop& stop) { StageC::finish(stop.reason); delete s; return stop.code; }\n    StageC::finish("completed");')
edit('CMakeLists.txt','        Main.cpp','        Main.cpp\n        StageC.cpp')
for name in ['StageC.h','StageC.cpp']: shutil.copy2(ROOT/name,SRC/name)
print(SRC)
