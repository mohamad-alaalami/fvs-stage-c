// Replay acceptance tool (integration-v1): restore saved Stage C states (schema STAGEC1, byte layout of
// full/StageC.cpp) and run the SAME fvsb::selectCore used by the live solver with each frozen model.
// Usage: PolicyReplay <8|5|LP> <linear model.json> <boost model.json> <boost model_meta.json> < list.tsv > out.jsonl
// list.tsv rows: state_id \t samples.bin path \t state offset \t state bytes \t candidates offset \t candidate count
#include "FvsHooks.h"
#include "FvsPolicy.h"
#include "lib/Graph.h"
#include "solutions/HalfIntBranching.h"
#include "solutions/SolutionVariants.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace std;

struct Archive {
    const string& d; size_t pos = 0;
    explicit Archive(const string& s) : d(s) {}
    template <class V> void io(V& v) { if (pos + sizeof(V) > d.size()) throw runtime_error("truncated snapshot"); memcpy(&v, d.data() + pos, sizeof(V)); pos += sizeof(V); }
    void io(string& s) { uint64_t n; io(n); if (n > 1000000000ULL || pos + n > d.size()) throw runtime_error("bad string"); s = d.substr(pos, n); pos += n; }
    template <class V> void io(vector<V>& v) { uint64_t n; io(n); if (n > 1000000000ULL) throw runtime_error("bad vector length"); v.resize(n); for (uint64_t i = 0; i < n; ++i) { V x = V(); io(x); v[i] = x; } }
    void io(vector<bool>& v) { uint64_t n; io(n); if (n > 1000000000ULL) throw runtime_error("bad vector length"); v.resize(n); for (uint64_t i = 0; i < n; ++i) { bool x; io(x); v[i] = x; } }
    void io(queue<int>& q) { vector<int> v; io(v); q = queue<int>(); for (int x : v) q.push(x); }
};

struct Restored { string variant; int level, phase, pivot, root, sizeCap; vector<string> names; };

struct FvsReplayAccess {
    static Restored restore(const string& bytes, Graph& g) {
        Archive a(bytes); Restored r; string magic;
        a.io(magic); a.io(r.variant);
        if (magic != "STAGEC1") throw runtime_error("bad magic");
        a.io(r.level); a.io(r.phase); a.io(r.pivot); a.io(r.root);
        a.io(g.N); a.io(g.M); a.io(g.deleted); a.io(g.changeInU); a.io(g.neighbours); a.io(g.neighDouble); a.io(g.doubleNum); a.io(g.posAtNeigh);
        a.io(g.status); a.io(g.oldNumbers); a.io(g.X); a.io(g.selfLoops); a.io(g.deg2ToReduce); a.io(g.vis); a.io(g.ccNr); a.io(g.ccVertices);
        a.io(g.fuRepr); a.io(g.fuWeight); a.io(r.names);
        bool solFound, isSub, stageHint; vector<int> hints, sol; int depth;
        a.io(solFound); a.io(hints); a.io(sol); a.io(isSub); a.io(depth); a.io(r.sizeCap); a.io(stageHint);
        if (r.variant == "8") { int br2; a.io(br2); }
        if (r.variant == "LP") { bool ks; a.io(ks); }
        if (a.pos != bytes.size()) throw runtime_error("snapshot trailing bytes");
        return r;
    }
};

static string readSlice(const string& path, uint64_t off, uint64_t len) {
    static map<string, string> cache;
    auto it = cache.find(path);
    if (it == cache.end()) {
        if (cache.size() > 8) cache.clear();
        ifstream f(path.c_str(), ios::binary); if (!f) throw runtime_error("cannot open " + path);
        ostringstream ss; ss << f.rdbuf(); it = cache.emplace(path, ss.str()).first;
    }
    if (off + len > it->second.size()) throw runtime_error("slice out of range");
    return it->second.substr(off, len);
}

int main(int argc, char** argv) {
    if (argc != 5) { cerr << "usage: PolicyReplay <8|5|LP> <linear model> <boost model> <boost meta>\n"; return 2; }
    string solver = argv[1];
    int kind = solver == "8" ? fvsb::KIND_CAO : solver == "5" ? fvsb::KIND_CHEN : fvsb::KIND_LP;
    fvsb::Policy *lin = nullptr, *bst = nullptr;
    try { lin = fvsb::loadPolicy(kind, "linear", argv[2], ""); bst = fvsb::loadPolicy(kind, "boost", argv[3], argv[4]); }
    catch (const fvsb::PolicyError& e) { cerr << "model load failed: " << e.reason << "\n"; return 3; }
    cout << setprecision(17);
    cout << "{\"header\":true,\"solver\":\"" << solver << "\",\"linear_fnv1a64\":\"" << hex << lin->modelFnv << "\",\"boost_fnv1a64\":\"" << bst->modelFnv
         << "\",\"boost_meta_fnv1a64\":\"" << bst->metaFnv << dec << "\",\"trees\":" << bst->trees.size() << ",\"theta\":" << lin->theta.size() << "}\n";
    string line; long rows = 0, errors = 0;
    while (getline(cin, line)) {
        if (line.empty()) continue;
        istringstream ls(line); string id, path, so, sl, co, cc;
        getline(ls, id, '\t'); getline(ls, path, '\t'); getline(ls, so, '\t'); getline(ls, sl, '\t'); getline(ls, co, '\t'); getline(ls, cc, '\t');
        ostringstream o; o << setprecision(17);
        o << "{\"state_id\":\"" << id << "\"";
        try {
            string bytes = readSlice(path, stoull(so), stoull(sl));
            string cbytes = readSlice(path, stoull(co), 4 * stoull(cc));
            vector<int> archived(stoull(cc)); if (!archived.empty()) memcpy(&archived[0], cbytes.data(), cbytes.size());
            Graph g; Restored r = FvsReplayAccess::restore(bytes, g);
            if (r.variant != solver) throw runtime_error("variant mismatch");
            int v0 = kind == fvsb::KIND_CAO ? g.getMaxDegVWDouble().first : kind == fvsb::KIND_CHEN ? g.getMaxDegToUndeletable().first : g.getMaxDegNeigh(r.root).first;
            int root = kind == fvsb::KIND_LP ? r.root : -1;
            fvsb::Selection sl1, sl2; bool e1, e2; size_t n1, n2;
            int c1 = fvsb::selectCore(kind, g, v0, root, r.sizeCap, lin, &sl1, &e1, &n1);
            int c2 = fvsb::selectCore(kind, g, v0, root, r.sizeCap, bst, &sl2, &e2, &n2);
            o << ",\"recorded_pivot\":" << r.pivot << ",\"recorded_phase\":" << r.phase << ",\"root\":" << r.root << ",\"original\":" << v0
              << ",\"size_cap\":" << r.sizeCap << ",\"x_size\":" << g.getXSize() << ",\"archived_candidates_match\":" << (archived == sl1.candidates ? "true" : "false")
              << ",\"candidates\":[";
            for (size_t i = 0; i < sl1.candidates.size(); ++i) o << (i ? "," : "") << sl1.candidates[i];
            o << "],\"features\":[";
            for (size_t i = 0; i < sl1.features.size(); ++i) o << (i ? "," : "") << sl1.features[i];
            o << "],\"linear\":{\"chosen\":" << c1 << ",\"tied\":" << sl1.tied << ",\"scored\":" << (sl1.scored ? "true" : "false") << ",\"scores\":[";
            for (size_t i = 0; i < sl1.scores.size(); ++i) o << (i ? "," : "") << sl1.scores[i];
            o << "]},\"boost\":{\"chosen\":" << c2 << ",\"tied\":" << sl2.tied << ",\"scored\":" << (sl2.scored ? "true" : "false") << ",\"scores\":[";
            for (size_t i = 0; i < sl2.scores.size(); ++i) o << (i ? "," : "") << sl2.scores[i];
            o << "]},\"features_equal_across_families\":" << (sl1.features == sl2.features ? "true" : "false") << ",\"error\":null}";
        } catch (const fvsb::PolicyError& e) { ++errors; o << ",\"error\":\"policy:" << e.reason << "\"}"; }
        catch (const exception& e) { ++errors; o << ",\"error\":\"" << e.what() << "\"}"; }
        cout << o.str() << "\n"; ++rows;
    }
    cerr << "rows " << rows << " errors " << errors << "\n";
    return errors ? 1 : 0;
}
