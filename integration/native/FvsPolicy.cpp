// Frozen learned pivot policies (integration-v1). See FvsPolicy.h and integration/PROTOCOL.md.
#include "FvsPolicy.h"
#include "lib/Graph.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>

using std::string;
using std::vector;

namespace fvsb {

const char* const FEATURE_NAMES[F_COUNT] = {
    "f_cand_none_neighbors", "f_cand_safe_neighbors", "f_cand_double_edges",
    "f_nbr_none_wdeg_min", "f_nbr_none_wdeg_mean", "f_nbr_none_wdeg_max",
    "f_state_none_vertices", "f_state_safe_vertices", "f_state_distinct_edges", "f_state_double_edges",
    "f_state_remaining_threshold", "f_state_candidate_count", "f_lp_root_common_neighbors"};

uint64_t fnv1a(const string& b) {
    uint64_t h = 14695981039346656037ULL;
    for (unsigned char c : b) { h ^= c; h *= 1099511628211ULL; }
    return h;
}

// ---------------------------------------------------------------- minimal JSON reader -----------
// Numbers keep their source text so that each consumer converts with the right precision
// (strtod for float64 linear parameters, strtof for XGBoost float32 tree values).
namespace {
struct J {
    enum T { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
    bool b = false; string s;            // NUM: source text; STR: decoded string
    vector<J> a; vector<std::pair<string, J> > o;
    const J& operator[](const char* k) const {
        for (auto& kv : o) if (kv.first == k) return kv.second;
        throw PolicyError{"model_json_missing_key", 72};
    }
    bool has(const char* k) const { for (auto& kv : o) if (kv.first == k) return true; return false; }
};
struct Parser {
    const string& d; size_t p = 0;
    explicit Parser(const string& s) : d(s) {}
    [[noreturn]] void fail() { throw PolicyError{"model_json_syntax", 72}; }
    void ws() { while (p < d.size() && (d[p] == ' ' || d[p] == '\n' || d[p] == '\r' || d[p] == '\t')) ++p; }
    bool lit(const char* w) { size_t n = strlen(w); if (d.compare(p, n, w) == 0) { p += n; return true; } return false; }
    string str() {
        if (d[p] != '"') fail();
        ++p; string r;
        while (p < d.size() && d[p] != '"') {
            if (d[p] == '\\') {
                ++p; if (p >= d.size()) fail();
                char c = d[p++];
                if (c == 'u') { if (p + 4 > d.size()) fail(); unsigned v = strtoul(d.substr(p, 4).c_str(), 0, 16); p += 4; if (v >= 128) fail(); r += char(v); }
                else if (c == 'n') r += '\n'; else if (c == 't') r += '\t'; else if (c == 'r') r += '\r'; else if (c == 'b') r += '\b'; else if (c == 'f') r += '\f';
                else r += c;
            } else r += d[p++];
        }
        if (p >= d.size()) fail();
        ++p; return r;
    }
    J val() {
        ws(); if (p >= d.size()) fail();
        J v; char c = d[p];
        if (c == '{') {
            v.t = J::OBJ; ++p; ws();
            if (d[p] == '}') { ++p; return v; }
            for (;;) { ws(); string k = str(); ws(); if (d[p] != ':') fail(); ++p; J x = val(); v.o.emplace_back(k, std::move(x)); ws();
                       if (d[p] == ',') { ++p; continue; } if (d[p] == '}') { ++p; return v; } fail(); }
        }
        if (c == '[') {
            v.t = J::ARR; ++p; ws();
            if (d[p] == ']') { ++p; return v; }
            for (;;) { v.a.push_back(val()); ws(); if (d[p] == ',') { ++p; continue; } if (d[p] == ']') { ++p; return v; } fail(); }
        }
        if (c == '"') { v.t = J::STR; v.s = str(); return v; }
        if (lit("true")) { v.t = J::BOOL; v.b = true; return v; }
        if (lit("false")) { v.t = J::BOOL; return v; }
        if (lit("null")) return v;
        size_t q = p;
        while (q < d.size() && (isdigit((unsigned char)d[q]) || d[q] == '-' || d[q] == '+' || d[q] == '.' || d[q] == 'e' || d[q] == 'E')) ++q;
        if (q == p) fail();
        v.t = J::NUM; v.s = d.substr(p, q - p); p = q; return v;
    }
};
J parseFile(const string& path, uint64_t* fnv) {
    std::ifstream f(path.c_str(), std::ios::binary);
    if (!f) throw PolicyError{"model_file_unreadable", 72};
    std::ostringstream ss; ss << f.rdbuf(); string bytes = ss.str();
    *fnv = fnv1a(bytes);
    Parser ps(bytes); J v = ps.val(); ps.ws();
    if (ps.p != bytes.size()) throw PolicyError{"model_json_trailing", 72};
    return v;
}
double toD(const J& v) {
    if (v.t != J::NUM) throw PolicyError{"model_json_not_number", 72};
    char* e = 0; double x = strtod(v.s.c_str(), &e);
    if (*e) throw PolicyError{"model_json_bad_number", 72};
    return x;
}
float toF(const J& v) {          // XGBoost float32 text, or a quoted float string ("0E0")
    const string& s = v.s;
    if (v.t != J::NUM && v.t != J::STR) throw PolicyError{"model_json_not_number", 72};
    char* e = 0; float x = strtof(s.c_str(), &e);
    if (*e) throw PolicyError{"model_json_bad_number", 72};
    return x;
}
long toI(const J& v) {
    if (v.t == J::NUM || v.t == J::STR) { char* e = 0; long x = strtol(v.s.c_str(), &e, 10); if (*e || v.s.empty()) throw PolicyError{"model_json_bad_int", 72}; return x; }
    throw PolicyError{"model_json_not_int", 72};
}
const string& toS(const J& v) { if (v.t != J::STR) throw PolicyError{"model_json_not_string", 72}; return v.s; }
int featureIndex(const string& name) {
    for (int i = 0; i < F_COUNT; ++i) if (name == FEATURE_NAMES[i]) return i;
    throw PolicyError{"model_unknown_feature", 72};
}
const char* solverName(int kind) { return kind == KIND_CAO ? "8" : kind == KIND_CHEN ? "5" : "LP"; }
}  // namespace

// The allowlists of the extraction schema (learnability/schema.py ALLOWLISTS): first 12 columns for
// Cao and Chen; LP excludes f_cand_safe_neighbors and f_state_safe_vertices and adds the root column.
static vector<int> allowlist(int kind) {
    vector<int> r;
    for (int i = 0; i < F_COUNT; ++i) {
        if (kind != KIND_LP && i == F_LP_ROOT_COMMON_NEIGHBORS) continue;
        if (kind == KIND_LP && (i == F_CAND_SAFE_NEIGHBORS || i == F_STATE_SAFE_VERTICES)) continue;
        r.push_back(i);
    }
    return r;
}

Policy* loadPolicy(int kind, const string& family, const string& modelPath, const string& metaPath) {
    Policy* p = new Policy();
    p->kind = kind; p->family = family; p->modelPath = modelPath; p->metaPath = metaPath;
    if (family == "linear") {
        J m = parseFile(modelPath, &p->modelFnv);
        if (toS(m["format"]) != "fvs-pairwise-linear-v1" || toS(m["family"]) != "linear" || toS(m["solver"]) != solverName(kind))
            throw PolicyError{"model_identity_mismatch", 72};
        const J& t = m["transform"];
        const J& order = t["input_order"];
        for (auto& c : order.a) p->inputs.push_back(featureIndex(toS(c)));
        if (p->inputs != allowlist(kind)) throw PolicyError{"model_inputs_not_allowlist", 72};
        const J& base = t["base"];
        if (base.a.size() != p->inputs.size()) throw PolicyError{"model_base_length", 72};
        for (size_t i = 0; i < base.a.size(); ++i) {
            if (toS(base.a[i]["column"]) != toS(order.a[i])) throw PolicyError{"model_base_order", 72};
            p->baseMean.push_back(toD(base.a[i]["mean"])); p->baseStd.push_back(toD(base.a[i]["std"]));
        }
        auto pos = [&](const string& name) { for (size_t i = 0; i < order.a.size(); ++i) if (toS(order.a[i]) == name) return int(i); throw PolicyError{"model_column_unknown", 72}; };
        vector<int> ctx;
        for (auto& c : t["candidate_columns"].a) p->candIdx.push_back(pos(toS(c)));
        for (auto& c : t["context_columns"].a) ctx.push_back(pos(toS(c)));
        if (p->candIdx.size() + ctx.size() != order.a.size()) throw PolicyError{"model_role_split", 72};
        // products: candidate-major, context-minor (transforms.py LinearTransform._products)
        const J& prods = t["products"]; size_t k = 0;
        for (int c : p->candIdx) for (int x : ctx) {
            if (k >= prods.a.size()) throw PolicyError{"model_products_length", 72};
            const J& q = prods.a[k++];
            if (pos(toS(q["candidate"])) != c || pos(toS(q["context"])) != x) throw PolicyError{"model_products_order", 72};
            p->products.emplace_back(c, x); p->prodMean.push_back(toD(q["mean"])); p->prodStd.push_back(toD(q["std"]));
        }
        if (k != prods.a.size()) throw PolicyError{"model_products_length", 72};
        // phi order check: candidate columns, then "c*k" products
        const J& phi = t["phi_order"]; size_t n = p->candIdx.size() + p->products.size();
        if (phi.a.size() != n) throw PolicyError{"model_phi_length", 72};
        for (size_t i = 0; i < p->candIdx.size(); ++i) if (toS(phi.a[i]) != toS(order.a[p->candIdx[i]])) throw PolicyError{"model_phi_order", 72};
        for (size_t i = 0; i < p->products.size(); ++i)
            if (toS(phi.a[p->candIdx.size() + i]) != toS(order.a[p->products[i].first]) + "*" + toS(order.a[p->products[i].second])) throw PolicyError{"model_phi_order", 72};
        for (auto& x : m["theta"].a) p->theta.push_back(toD(x));
        if (p->theta.size() != n) throw PolicyError{"model_theta_length", 72};
        for (double x : p->theta) if (!std::isfinite(x)) throw PolicyError{"model_theta_nonfinite", 72};
    } else if (family == "boost") {
        J meta = parseFile(metaPath, &p->metaFnv);
        if (toS(meta["format"]) != "xgboost-json-margin" || toS(meta["family"]) != "boost" || toS(meta["solver"]) != solverName(kind) || toD(meta["base_score"]) != 0.0)
            throw PolicyError{"model_identity_mismatch", 72};
        for (auto& c : meta["input_order"].a) p->inputs.push_back(featureIndex(toS(c)));
        if (p->inputs != allowlist(kind)) throw PolicyError{"model_inputs_not_allowlist", 72};
        J m = parseFile(modelPath, &p->modelFnv);
        const J& L = m["learner"];
        const J& lp = L["learner_model_param"];
        p->baseScore = toF(lp["base_score"]);
        if (p->baseScore != 0.0f) throw PolicyError{"model_base_score_nonzero", 72};
        if (toI(lp["num_feature"]) != long(p->inputs.size()) || toI(lp["num_target"]) != 1 || toI(lp["num_class"]) != 0) throw PolicyError{"model_shape", 72};
        const J& gb = L["gradient_booster"];
        if (toS(gb["name"]) != "gbtree") throw PolicyError{"model_not_gbtree", 72};
        const J& mod = gb["model"];
        if (toI(mod["gbtree_model_param"]["num_parallel_tree"]) != 1) throw PolicyError{"model_parallel_tree", 72};
        long nt = toI(mod["gbtree_model_param"]["num_trees"]);
        const J& trees = mod["trees"];
        if (long(trees.a.size()) != nt) throw PolicyError{"model_tree_count", 72};
        for (auto& ti : mod["tree_info"].a) if (toI(ti) != 0) throw PolicyError{"model_tree_group", 72};
        for (auto& tj : trees.a) {
            Policy::Tree tr;
            for (auto& x : tj["left_children"].a) tr.left.push_back(int(toI(x)));
            for (auto& x : tj["right_children"].a) tr.right.push_back(int(toI(x)));
            for (auto& x : tj["split_indices"].a) tr.feat.push_back(int(toI(x)));
            for (auto& x : tj["split_conditions"].a) tr.cond.push_back(toF(x));
            size_t nn = tr.left.size();
            if (toI(tj["tree_param"]["num_nodes"]) != long(nn) || tr.right.size() != nn || tr.feat.size() != nn || tr.cond.size() != nn || nn == 0)
                throw PolicyError{"model_tree_arrays", 72};
            if (toI(tj["tree_param"]["size_leaf_vector"]) > 1) throw PolicyError{"model_leaf_vector", 72};
            for (auto& x : tj["split_type"].a) if (toI(x) != 0) throw PolicyError{"model_categorical_split", 72};
            if (!tj["categories"].a.empty()) throw PolicyError{"model_categorical_split", 72};
            for (size_t i = 0; i < nn; ++i) {
                bool leaf = tr.left[i] == -1;
                if (leaf != (tr.right[i] == -1)) throw PolicyError{"model_tree_shape", 72};
                if (!leaf && (tr.left[i] <= int(i) || tr.right[i] <= int(i) || tr.left[i] >= int(nn) || tr.right[i] >= int(nn) || tr.feat[i] < 0 || tr.feat[i] >= int(p->inputs.size())))
                    throw PolicyError{"model_tree_shape", 72};
                if (!std::isfinite(tr.cond[i])) throw PolicyError{"model_tree_nonfinite", 72};
            }
            p->trees.push_back(std::move(tr));
        }
    } else throw PolicyError{"unknown_policy_family", 72};
    return p;
}

// ---------------------------------------------------------------- candidates and features --------
static inline bool active(int s) { return s == STATUS_NONE || s == STATUS_IN_SAFE; }

void eligible(int kind, Graph& g, int root, vector<int>& out) {
    out.clear();
    int N = g.getN();
    if (kind == KIND_CAO) {
        int best = 0;
        for (int i = 0; i < N; ++i) if (g.isNone(i) && g.degWithDouble(i) > best) best = g.degWithDouble(i);
        for (int i = 0; i < N; ++i) if (g.isNone(i) && g.degWithDouble(i) == best) out.push_back(i);
    } else if (kind == KIND_CHEN) {
        for (int i = 0; i < N; ++i) if (g.isNone(i)) out.push_back(i);
    } else {
        static vector<uint64_t> seen; static uint64_t gen = 0;
        if (seen.size() < size_t(N)) seen.resize(N, 0);
        ++gen;
        for (int v : g.getNeighbours()[root]) if (g.isNone(v) && seen[v] != gen) { seen[v] = gen; out.push_back(v); }
    }
}

// Exactly learnability/features.py compute_features (extraction schema v1):
//   N(v) = DISTINCT active neighbours u != v (status 0 or 1); an entry flagged in neighDouble counts 2
//   w(v) = |N(v)| + flagged distinct neighbours; neighbour summaries over undecided neighbours only
//   (min / integer-sum / count / max, 0.0 when empty); state counts over active vertices;
//   remaining threshold = size_cap - |X|; LP root common neighbours = |N(v) & N(root)|.
void computeFeatures(int kind, Graph& g, const vector<int>& cands, int root, int cap, vector<double>& out) {
    const int N = g.getN();
    vector<vector<int> >& nb = g.getNeighbours();
    vector<int>& st = g.getStatuses();
    static vector<uint64_t> seen, rootMark; static vector<char> dfl; static vector<long long> wdeg; static uint64_t gen = 0;
    if (seen.size() < size_t(N)) { seen.resize(N, 0); rootMark.resize(N, 0); dfl.resize(N, 0); wdeg.resize(N, 0); }
    long long none = 0, safe = 0, degSum = 0, dblSum = 0;
    for (int v = 0; v < N; ++v) {
        if (!active(st[v])) continue;
        ++gen; long long d = 0, dd = 0;
        const vector<int>& a = nb[v];
        for (size_t j = 0; j < a.size(); ++j) {
            int u = a[j];
            if (u < 0 || u >= N || u == v || !active(st[u])) continue;
            bool f = g.isDoubleEdge(v, int(j));
            if (seen[u] != gen) { seen[u] = gen; dfl[u] = f; ++d; dd += f; }
            else if (f && !dfl[u]) { dfl[u] = 1; ++dd; }
        }
        wdeg[v] = d + dd; degSum += d; dblSum += dd;
        if (st[v] == STATUS_NONE) ++none; else ++safe;
    }
    uint64_t rgen = 0;
    if (kind == KIND_LP) {
        rgen = ++gen;
        if (root >= 0 && root < N && active(st[root]))
            for (int u : nb[root]) if (u >= 0 && u < N && u != root && active(st[u])) rootMark[u] = rgen;
    }
    const size_t n = cands.size();
    out.assign(n * F_COUNT, 0.0);
    for (size_t c = 0; c < n; ++c) {
        double* r = &out[c * F_COUNT];
        r[F_STATE_NONE_VERTICES] = double(none); r[F_STATE_SAFE_VERTICES] = double(safe);
        r[F_STATE_DISTINCT_EDGES] = double(degSum / 2); r[F_STATE_DOUBLE_EDGES] = double(dblSum / 2);
        r[F_STATE_REMAINING_THRESHOLD] = double(cap - g.getXSize()); r[F_STATE_CANDIDATE_COUNT] = double(n);
        int v = cands[c];
        ++gen;
        long long noneN = 0, safeN = 0, dbl = 0, wsum = 0, wmin = 0, wmax = 0, common = 0;
        if (active(st[v])) {
            const vector<int>& a = nb[v];
            for (size_t j = 0; j < a.size(); ++j) {
                int u = a[j];
                if (u < 0 || u >= N || u == v || !active(st[u])) continue;
                bool f = g.isDoubleEdge(v, int(j));
                if (seen[u] != gen) {
                    seen[u] = gen; dfl[u] = f; dbl += f;
                    if (st[u] == STATUS_NONE) {
                        long long w = wdeg[u];
                        if (noneN == 0 || w < wmin) wmin = w;
                        if (noneN == 0 || w > wmax) wmax = w;
                        wsum += w; ++noneN;
                    } else ++safeN;
                    if (kind == KIND_LP && rootMark[u] == rgen) ++common;
                } else if (f && !dfl[u]) { dfl[u] = 1; ++dbl; }
            }
        }
        r[F_CAND_NONE_NEIGHBORS] = double(noneN); r[F_CAND_SAFE_NEIGHBORS] = double(safeN); r[F_CAND_DOUBLE_EDGES] = double(dbl);
        r[F_NBR_NONE_WDEG_MIN] = noneN ? double(wmin) : 0.0;
        r[F_NBR_NONE_WDEG_MEAN] = noneN ? double(wsum) / double(noneN) : 0.0;   // integer sum, float64 division
        r[F_NBR_NONE_WDEG_MAX] = noneN ? double(wmax) : 0.0;
        r[F_LP_ROOT_COMMON_NEIGHBORS] = kind == KIND_LP ? double(common) : 0.0;
    }
}

// ---------------------------------------------------------------- scoring ------------------------
void score(const Policy& p, const vector<double>& F, int n, vector<double>& out) {
    out.assign(n, 0.0);
    const size_t m = p.inputs.size();
    vector<double> x(m), z(m);
    vector<float> xf(m);
    for (int c = 0; c < n; ++c) {
        const double* r = &F[size_t(c) * F_COUNT];
        for (size_t i = 0; i < m; ++i) x[i] = r[p.inputs[i]];
        if (p.family == "linear") {
            // transforms.py: z = (x - mean)/std for std > 0, else 0; products z_c*z_k standardised again;
            // s = sum_j theta_j * phi_j accumulated left to right in phi order.
            for (size_t i = 0; i < m; ++i) z[i] = p.baseStd[i] > 0 ? (x[i] - p.baseMean[i]) / p.baseStd[i] : 0.0;
            double s = 0.0; size_t j = 0;
            for (int ci : p.candIdx) s += p.theta[j++] * z[ci];
            for (size_t k = 0; k < p.products.size(); ++k) {
                double y = z[p.products[k].first] * z[p.products[k].second];
                double phi = p.prodStd[k] > 0 ? (y - p.prodMean[k]) / p.prodStd[k] : 0.0;
                s += p.theta[j++] * phi;
            }
            out[c] = s;
        } else {
            // XGBoost: inputs converted to float32; numerical split goes left iff x < condition;
            // margin = base_score + leaf values accumulated in float32 in tree order.
            for (size_t i = 0; i < m; ++i) xf[i] = float(x[i]);
            float acc = p.baseScore;
            for (const Policy::Tree& t : p.trees) {
                int node = 0;
                while (t.left[node] != -1) node = xf[t.feat[node]] < t.cond[node] ? t.left[node] : t.right[node];
                acc += t.cond[node];
            }
            out[c] = double(acc);
        }
        if (!std::isfinite(out[c])) throw PolicyError{"nonfinite_score", 71};
    }
}

int choose(const vector<int>& cands, const vector<double>& s, int original, int* tied) {
    double m = s[0];
    for (size_t i = 1; i < s.size(); ++i) if (s[i] > m) m = s[i];
    int first = -1, nt = 0; bool orig = false;
    for (size_t i = 0; i < s.size(); ++i) if (s[i] == m) { ++nt; if (first < 0) first = cands[i]; if (cands[i] == original) orig = true; }
    if (tied) *tied = nt;
    return orig ? original : first;
}

int selectCore(int kind, Graph& g, int v0, int root, int cap, const Policy* p, Selection* detail, bool* elig, size_t* count) {
    static vector<int> C; static vector<double> F, S;
    if (elig) *elig = false;
    if (count) *count = 0;
    if (v0 < 0) return v0;
    eligible(kind, g, root, C);
    if (count) *count = C.size();
    int pos = -1;
    for (size_t i = 0; i < C.size(); ++i) if (C[i] == v0) { pos = int(i); break; }
    if (detail) { detail->candidates = C; detail->original = v0; detail->originalPos = pos; detail->chosen = v0; detail->scored = false; detail->tied = 0; }
    if (pos < 0) {
        if (p) throw PolicyError{"original_pivot_not_eligible", 71};
        return v0;
    }
    if (C.size() < 2) return v0;
    if (elig) *elig = true;
    if (!p) return v0;
    double t0 = g_timeParts ? qpcSeconds() : 0;
    computeFeatures(kind, g, C, root, cap, F);
    double t1 = g_timeParts ? qpcSeconds() : 0;
    score(*p, F, int(C.size()), S);
    if (g_timeParts) { double t2 = qpcSeconds(); g_featureSeconds += t1 - t0; g_scoreSeconds += t2 - t1; }
    int tied = 0;
    int chosen = choose(C, S, v0, &tied);
    if (detail) { detail->features = F; detail->scores = S; detail->chosen = chosen; detail->tied = tied; detail->scored = true; }
    return chosen;
}

}  // namespace fvsb
