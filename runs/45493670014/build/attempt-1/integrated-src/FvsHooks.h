#ifndef FVS_HOOKS_H
#define FVS_HOOKS_H
// End-to-end integration hooks (integration-v1). Included by the prepared copy of the pinned
// SEA solver source; the pinned checkout itself is never edited.
//
// Every variant (baseline, linear, boost) runs the SAME executable. The policy is chosen at process
// start from the environment (FVSB_POLICY). In the timed baseline the selector hooks reduce to
// "count the decision, return the original pivot": no candidate enumeration, no features, no model.
//
// Counting definitions (identical in every variant):
//   node     = one entry to branching() (Sol8/Sol5) or solve1()/solve2() (LP), component subsolvers included
//   decision = an actual two-child branch about to run (B)
//   target   = a decision at the selector under study (T): every Sol8 pivot; a Sol5 fallback after the
//              compression hints are exhausted; an LP solve2 neighbour branch
//   eligible = a target decision with >= 2 distinct eligible pivots (A); measured only when the policy
//              or the diagnostic mode enumerates candidates (never in the timed baseline)
//   scored   = a model invocation (learned variants only); departure = scored and chosen != original pivot
#include <cstdint>
#include <vector>

class Graph;
class BranchingSolution;

namespace fvsb {

struct Stop { const char* reason; int code; };          // cooperative stop (CPU limit, external stop)
struct PolicyError { const char* reason; int code; };   // explicit learned-policy error (never a fallback)

struct Policy;                                          // opaque; defined in FvsPolicy.cpp

enum Kind { KIND_CAO = 0, KIND_CHEN = 1, KIND_LP = 2 };

extern bool g_slow;                 // true when the learned policy or the diagnostic mode is active
extern uint64_t g_nodes[3][2];      // [branching, solve1, solve2][main, component]
extern uint64_t g_decisions, g_target, g_eligible, g_scored, g_departures;
extern uint64_t g_trace;            // FNV-1a chain over (phase, depth, local pivot) of every decision
extern int g_depth;                 // enclosing search frames; root call = 0
extern int g_selPhase;              // phase of the decision being formed (-1: not a studied selector)
extern bool g_timeParts;           // diagnostic mode: time feature computation and scoring separately
extern double g_featureSeconds, g_scoreSeconds;
double qpcSeconds();

void guard();                       // cheap tick check; CPU/stop checks at most every 10 ms of wall

struct Frame {
    Frame(int proc, bool sub) { ++g_depth; ++g_nodes[proc][sub ? 1 : 0]; guard(); }
    ~Frame() { --g_depth; }
};

void trace(int phase, int v);
inline void preSelect() { g_selPhase = -1; }
// phase: 0 cao, 1 chen hint, 2 chen fallback, 3 lp root, 4 lp neighbour (Stage C numbering).
// branching() passes -2: the phase is then the one set by its selector hook (0 or 2), or 1 when
// Sol5 returned a compression hint (no hook ran after preSelect()).
inline void decision(int phase, int v) {
    ++g_decisions;
    if (phase == -2) phase = g_selPhase >= 0 ? g_selPhase : 1;
    trace(phase, v);
}

int caoSlow(BranchingSolution* s, Graph& g, int v0);
int chenSlow(BranchingSolution* s, Graph& g, int v0);
int lpSlow(BranchingSolution* s, Graph& g, int root, int v0);

// Selector hooks. v0 is the original pivot, computed by the pinned selector code before the hook.
inline int caoSelect(BranchingSolution* s, Graph& g, int v0) {
    if (!g_slow) { if (v0 >= 0) ++g_target; g_selPhase = 0; return v0; }
    return caoSlow(s, g, v0);
}
inline int chenSelect(BranchingSolution* s, Graph& g, int v0) {
    if (!g_slow) { if (v0 >= 0) ++g_target; g_selPhase = 2; return v0; }
    return chenSlow(s, g, v0);
}
inline int lpSelect(BranchingSolution* s, Graph& g, int root, int v0) {
    if (!g_slow) { if (v0 >= 0) ++g_target; g_selPhase = 4; return v0; }
    return lpSlow(s, g, root, v0);
}

void init(int argc, char** argv);   // reads FVSB_* environment; never changes argv
void afterInput();
void attach(void* solution);        // Solution* created by the pinned Main.cpp
void finish(const char* status, int exitCode, const std::vector<int>* sol);

}  // namespace fvsb
#endif
