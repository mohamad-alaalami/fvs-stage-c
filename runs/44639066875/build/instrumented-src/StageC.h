#ifndef STAGE_C_H
#define STAGE_C_H
// Stage C, full-run edition: exact counters and histograms, sampled replay states.
#include <string>
#include <vector>
#include <cstdint>
#include <stdexcept>
class Graph;
class BranchingSolution;
struct StageStop { std::string reason; int code; };
// Classification of one actual branching decision (computed before the branch body runs).
struct StageAnalysis {
 int phase=0;                 // 0 cao_max_degree, 1 chen_hint, 2 chen_fallback, 3 lp_root, 4 lp_neighbor
 bool target=false, ambiguous=false;
 std::vector<int> candidates; // eligible pivots (local indices, ascending index order)
 bool pivotEligible=true;     // original pivot belongs to the eligible set / candidate domain
 // Chen fallback only: stricter disjoint-forest / component-merging measurement.
 bool chen=false, undecidedForest=true, undeletableForest=true, uniqueTouch=true, ufMatches=true, qualifying=false, strictA=false;
 std::vector<int> mergeCandidates; // undecided vertices touching >=2 distinct undeletable components (any score)
};
class StageC {
public:
 enum Outcome { OUT_BRANCH=0, OUT_LEAF, OUT_PRUNED, OUT_NO_PIVOT, OUT_DELEGATE_SOLVE1, OUT_REDUCTION_RECURSION, OUT_INTERRUPTED, OUT_UNCLASSIFIED, OUT_COUNT };
 static void init(int,char**);
 static void guard();
 static bool isReplay();
 static int replay();
 static void finish(const std::string&);
 static std::string state(BranchingSolution*,Graph&,int,int,int);
 static void restore(const std::string&,BranchingSolution*&,Graph&,int&,int&,int&);
 static StageAnalysis analyze(BranchingSolution*,Graph&,int phase,int pivot,int root);
 static void leaf(BranchingSolution*);
 static void noSolution(BranchingSolution*);
 static void outcome(int);
 static const char* phaseName(int);
};
struct StageFrame { StageFrame(int proc,BranchingSolution*); ~StageFrame(); };
struct StageDecision {
 BranchingSolution* solver; Graph& graph; int phase,pivot,root;
 uint64_t id,startHash,startCount; bool ambiguous; int saved; // saved: 0 none, 1 first-A, 2+slot
 StageDecision(BranchingSolution*,Graph&,int,int,int);
 ~StageDecision();
};
#endif
