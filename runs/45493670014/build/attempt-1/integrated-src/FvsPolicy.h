#ifndef FVS_POLICY_H
#define FVS_POLICY_H
// Frozen learned pivot policies (integration-v1): live features, frozen-model scoring, tie rule.
// Used by the live solver hooks AND by the replay acceptance tool, so the replay exercises the
// same translation unit as the timed solver.
#include <cstdint>
#include <string>
#include <vector>
#include "FvsHooks.h"

class Graph;

namespace fvsb {

// Extraction schema v1 feature columns, in schema order (learnability/features.py FEATURE_COLUMNS).
enum Feature {
    F_CAND_NONE_NEIGHBORS = 0, F_CAND_SAFE_NEIGHBORS, F_CAND_DOUBLE_EDGES,
    F_NBR_NONE_WDEG_MIN, F_NBR_NONE_WDEG_MEAN, F_NBR_NONE_WDEG_MAX,
    F_STATE_NONE_VERTICES, F_STATE_SAFE_VERTICES, F_STATE_DISTINCT_EDGES, F_STATE_DOUBLE_EDGES,
    F_STATE_REMAINING_THRESHOLD, F_STATE_CANDIDATE_COUNT, F_LP_ROOT_COMMON_NEIGHBORS, F_COUNT
};
extern const char* const FEATURE_NAMES[F_COUNT];

struct Selection {                 // optional per-decision detail (replay tool and tests only)
    std::vector<int> candidates;   // eligible pivots, archived order
    std::vector<double> features;  // candidates.size() x F_COUNT, schema order
    std::vector<double> scores;    // model scores (boost: float32 margins widened exactly)
    int original = -1, chosen = -1, tied = 0, originalPos = -1;
    bool scored = false;
};

struct Policy {
    int kind = 0;                  // Kind
    std::string family;            // "linear" | "boost"
    std::string modelPath, metaPath;
    uint64_t modelFnv = 0, metaFnv = 0;   // FNV-1a 64 of the exact bytes loaded
    std::vector<int> inputs;       // model input order -> Feature index
    // linear
    std::vector<double> baseMean, baseStd;        // per input
    std::vector<int> candIdx;                     // positions in `inputs` of candidate columns
    std::vector<std::pair<int,int> > products;    // (candidate position, context position) in phi order
    std::vector<double> prodMean, prodStd, theta;
    // boost (XGBoost 2.1.3 JSON, numerical splits, one output)
    struct Tree { std::vector<int> left, right, feat; std::vector<float> cond; };
    std::vector<Tree> trees;
    float baseScore = 0.0f;
};

Policy* loadPolicy(int kind, const std::string& family, const std::string& modelPath, const std::string& metaPath);

// Eligible pivots in archived order (Stage C StageC::analyze):
//   Cao  : STATUS_NONE vertices with degWithDouble equal to the maximum, ascending index
//   Chen : every STATUS_NONE vertex, ascending index
//   LP   : distinct STATUS_NONE neighbours of root, root adjacency order
void eligible(int kind, Graph& g, int root, std::vector<int>& out);

// Features of every candidate (schema order, row-major) from the live state.
void computeFeatures(int kind, Graph& g, const std::vector<int>& cands, int root, int cap, std::vector<double>& out);

// Scores of every candidate under the frozen model (throws PolicyError on a non-finite score).
void score(const Policy& p, const std::vector<double>& features, int n, std::vector<double>& out);

// Higher score wins; exact tie -> the original pivot if among the maxima, else the earliest maximum.
int choose(const std::vector<int>& cands, const std::vector<double>& scores, int original, int* tied);

// Complete selection at one target decision. v0 = original pivot. Returns the pivot to branch on.
// With p == nullptr (diagnostic baseline) the candidates are enumerated but v0 is always returned.
// Throws PolicyError when v0 is not eligible and a policy is active.
int selectCore(int kind, Graph& g, int v0, int root, int cap, const Policy* p, Selection* detail, bool* eligibleOut, size_t* countOut);

uint64_t fnv1a(const std::string& bytes);

}  // namespace fvsb
#endif
