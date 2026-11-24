// Integration-v1 runtime: counters, cooperative CPU guard, policy attachment, summary record.
#include "FvsHooks.h"
#include "FvsPolicy.h"
#include "lib/Graph.h"
#include "solutions/Solution.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>

using std::string;
using std::vector;

namespace fvsb {

bool g_slow = false;
uint64_t g_nodes[3][2] = {{0, 0}, {0, 0}, {0, 0}};
uint64_t g_decisions = 0, g_target = 0, g_eligible = 0, g_scored = 0, g_departures = 0;
uint64_t g_trace = 14695981039346656037ULL;
int g_depth = -1;
int g_selPhase = -1;
bool g_timeParts = false;
double g_featureSeconds = 0, g_scoreSeconds = 0;

namespace {
const uint64_t P = 1099511628211ULL;
int kind = KIND_CAO;
string kindName = "8", policyName = "baseline", summaryPath, stopFile, modelPath, metaPath, dumpPath;
bool diag = false, randomTest = false, policyLearned = false;
double cpuLimit = 0, checkpointEvery = 60;
uint64_t componentDumped = 0, componentScored = 0, scoredAfterDeparture = 0, randomState = 0, anomalies = 0, lastCount = 0, stagecTrace = 0, dumpEvery = 0, dumpMax = 0, dumped = 0, dumpSeen = 0;
uint64_t lastTick = 0, lastCheckpointTick = 0, guardChecks = 0;
double selectSeconds = 0;
Policy* policy = nullptr;
void* rootSolution = nullptr;
LARGE_INTEGER qpcFreq, qpcStart;
double wInit = 0, wInput = 0, wAttach = 0, cInit = 0, cInput = 0, cAttach = 0;
std::ofstream dump;

double cpu() {
    FILETIME a, b, c, d;
    if (!GetProcessTimes(GetCurrentProcess(), &a, &b, &c, &d)) return -1;
    return ((uint64_t(c.dwHighDateTime) << 32) + c.dwLowDateTime + (uint64_t(d.dwHighDateTime) << 32) + d.dwLowDateTime) / 1e7;
}
double wall() { LARGE_INTEGER t; QueryPerformanceCounter(&t); return double(t.QuadPart - qpcStart.QuadPart) / double(qpcFreq.QuadPart); }
uint64_t mix(uint64_t x) { x += 0x9e3779b97f4a7c15ULL; x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL; x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL; return x ^ (x >> 31); }
uint64_t hashBytes(const void* p, size_t n, uint64_t h = 14695981039346656037ULL) { const unsigned char* c = (const unsigned char*)p; for (size_t i = 0; i < n; ++i) { h ^= c[i]; h *= P; } return h; }
string env(const char* k) { const char* v = getenv(k); return v ? string(v) : string(); }
string q(const string& s) { std::ostringstream o; o << '"'; for (unsigned char c : s) { if (c == '"' || c == '\\') o << '\\' << c; else if (c < 32) o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec; else o << c; } o << '"'; return o.str(); }
string hex64(uint64_t x) { char b[17]; snprintf(b, sizeof b, "%016llx", (unsigned long long)x); return b; }

string summaryJson(const string& status, int exitCode, const vector<int>* sol) {
    std::ostringstream o; o << std::setprecision(17);
    uint64_t total = 0; for (auto& r : g_nodes) total += r[0] + r[1];
    double c = cpu(), w = wall();
    o << "{\"schema\":\"fvsb-summary-1\",\"status\":" << q(status) << ",\"exit_code\":" << exitCode << ",\"solver\":" << q(kindName)
      << ",\"policy\":" << q(policyName) << ",\"diagnostic\":" << (diag ? "true" : "false") << ",\"cpu_limit_s\":" << cpuLimit;
    if (policy) o << ",\"model\":{\"family\":" << q(policy->family) << ",\"path\":" << q(policy->modelPath) << ",\"fnv1a64\":\"" << hex64(policy->modelFnv)
                  << "\",\"meta_path\":" << q(policy->metaPath) << ",\"meta_fnv1a64\":\"" << hex64(policy->metaFnv) << "\",\"trees\":" << policy->trees.size() << ",\"theta\":" << policy->theta.size() << "}";
    else o << ",\"model\":null";
    o << ",\"nodes\":{\"total\":" << total;
    const char* procs[3] = {"branching", "solve1", "solve2"};
    for (int p = 0; p < 3; ++p) o << ",\"" << procs[p] << "\":{\"main\":" << g_nodes[p][0] << ",\"component\":" << g_nodes[p][1] << "}";
    o << "},\"decisions\":" << g_decisions << ",\"target_decisions\":" << g_target;
    if (g_slow) o << ",\"eligible_decisions\":" << g_eligible; else o << ",\"eligible_decisions\":null";
    o << ",\"scored_decisions\":" << g_scored << ",\"departures\":" << g_departures
      << ",\"scored_in_component_subsolvers\":" << componentScored << ",\"scored_after_first_departure\":" << scoredAfterDeparture
      << ",\"pivot_trace_digest\":\"" << hex64(g_trace) << "\"";
    if (diag) o << ",\"stagec_trace_digest\":\"" << stagecTrace << "\",\"diag_original_pivot_not_eligible\":" << anomalies
                << ",\"diag_feature_s\":" << g_featureSeconds << ",\"diag_score_s\":" << g_scoreSeconds << ",\"diag_select_s\":" << selectSeconds << ",\"diag_states_dumped\":" << dumped;
    if (sol) o << ",\"solution_size\":" << sol->size();
    else o << ",\"solution_size\":null";
    if (rootSolution && !sol) { BranchingSolution* b = dynamic_cast<BranchingSolution*>((Solution*)rootSolution); if (b && b->solFound) o << ",\"root_incumbent_size_at_stop\":" << b->getCap(); }
    o << ",\"timing\":{\"definition\":\"in-process; wall from QueryPerformanceCounter at fvsb::init (first statement of main), CPU = GetProcessTimes kernel+user of the whole process\""
      << ",\"init_cpu_s\":" << cInit << ",\"after_input_wall_s\":" << wInput << ",\"after_input_cpu_s\":" << cInput
      << ",\"after_attach_wall_s\":" << wAttach << ",\"after_attach_cpu_s\":" << cAttach
      << ",\"finish_wall_s\":" << w << ",\"finish_cpu_s\":" << c << "},\"guard_checks\":" << guardChecks << "}\n";
    return o.str();
}
void atomicWrite(const string& path, const string& data) {
    if (path.empty()) return;
    string tmp = path + ".tmp";
    { std::ofstream f(tmp.c_str(), std::ios::binary); f.write(data.data(), data.size()); }
    MoveFileExA(tmp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING);
}
}  // namespace

double qpcSeconds() { return wall(); }

void init(int argc, char** argv) {
    QueryPerformanceFrequency(&qpcFreq); QueryPerformanceCounter(&qpcStart);
    cInit = cpu();
    kindName = argc > 1 ? argv[1] : "8";
    kind = kindName == "8" ? KIND_CAO : kindName == "5" ? KIND_CHEN : kindName == "LP" ? KIND_LP : -1;
    policyName = env("FVSB_POLICY"); if (policyName.empty()) policyName = "baseline";
    summaryPath = env("FVSB_SUMMARY"); stopFile = env("FVSB_STOP_FILE");
    modelPath = env("FVSB_MODEL"); metaPath = env("FVSB_MODEL_META");
    if (!env("FVSB_CPU_LIMIT").empty()) cpuLimit = atof(env("FVSB_CPU_LIMIT").c_str());
    if (!env("FVSB_CHECKPOINT_S").empty()) checkpointEvery = atof(env("FVSB_CHECKPOINT_S").c_str());
    diag = env("FVSB_DIAG") == "1";
    dumpPath = env("FVSB_DUMP_STATES");
    if (!env("FVSB_DUMP_EVERY").empty()) dumpEvery = strtoull(env("FVSB_DUMP_EVERY").c_str(), 0, 10);
    if (!env("FVSB_DUMP_MAX").empty()) dumpMax = strtoull(env("FVSB_DUMP_MAX").c_str(), 0, 10);
    policyLearned = policyName == "linear" || policyName == "boost";
    randomTest = policyName.compare(0, 12, "random-test:") == 0;
    if (randomTest) randomState = strtoull(policyName.c_str() + 12, 0, 10);
    bool known = policyName == "baseline" || policyLearned || randomTest;
    g_slow = policyLearned || randomTest || diag;
    g_timeParts = diag;
    lastTick = lastCheckpointTick = GetTickCount64();
    if (!known || kind < 0 || ((policyLearned || randomTest) && argc > 2)) {
        // An unknown policy, solver or a non-default upstream variant with a policy is an explicit error.
        policyName = known ? policyName : "invalid:" + policyName;
        atomicWrite(summaryPath, summaryJson("configuration_error", 78, nullptr));
        fprintf(stderr, "fvsb: configuration error (policy=%s solver=%s argc=%d)\n", policyName.c_str(), kindName.c_str(), argc);
        exit(78);
    }
    if (diag && !dumpPath.empty()) dump.open(dumpPath.c_str(), std::ios::binary);
}

void afterInput() { wInput = wall(); cInput = cpu(); }

void attach(void* s) {
    rootSolution = s;
    if (policyLearned) {
        policy = loadPolicy(kind, policyName, modelPath, metaPath);
        BranchingSolution* b = dynamic_cast<BranchingSolution*>((Solution*)s);
        if (!b) throw PolicyError{"solver_not_branching", 72};
        b->policy = policy;
    } else if (randomTest) {
        BranchingSolution* b = dynamic_cast<BranchingSolution*>((Solution*)s);
        if (!b) throw PolicyError{"solver_not_branching", 72};
    }
    wAttach = wall(); cAttach = cpu();
}

void guard() {
    uint64_t t = GetTickCount64();
    if (t - lastTick < 10) return;
    lastTick = t; ++guardChecks;
    if (!stopFile.empty() && GetFileAttributesA(stopFile.c_str()) != INVALID_FILE_ATTRIBUTES) throw Stop{"external_stop", 75};
    if (cpuLimit > 0 && cpu() >= cpuLimit) throw Stop{"cpu_timeout", 74};
    if (!summaryPath.empty() && double(t - lastCheckpointTick) >= 1000.0 * checkpointEvery) {
        lastCheckpointTick = t; atomicWrite(summaryPath + ".partial", summaryJson("running", -1, nullptr));
    }
}

void trace(int phase, int v) {
    uint64_t key[3] = {uint64_t(phase), uint64_t(int64_t(g_depth)), uint64_t(int64_t(v))};
    g_trace = g_trace * P + hashBytes(key, sizeof key);
    if (diag) {
        // Stage C trace digest (full/StageC.cpp): key {phase, level, pivot, candidate count}, count 0 off-target.
        uint64_t cnt = (phase == 0 || phase == 2 || phase == 4) ? lastCount : 0;
        uint64_t k4[4] = {uint64_t(phase), uint64_t(int64_t(g_depth)), uint64_t(int64_t(v)), cnt};
        stagecTrace = stagecTrace * P + hashBytes(k4, sizeof k4);
    }
}

static void dumpState(Graph& g, int root, int cap, int v0, const Selection& sel, BranchingSolution* s) {
    vector<vector<int> >& nb = g.getNeighbours(); vector<int>& st = g.getStatuses();
    std::ostringstream o; o << std::setprecision(17);
    o << "{\"decision\":" << g_decisions + 1 << ",\"scored_index\":" << g_scored << ",\"departures_before\":" << g_departures << ",\"depth\":" << g_depth
      << ",\"component_subsolver\":" << ((void*)static_cast<Solution*>(s) != rootSolution ? "true" : "false")
      << ",\"root\":" << root << ",\"size_cap\":" << cap << ",\"x_size\":" << g.getXSize() << ",\"original\":" << v0 << ",\"chosen\":" << sel.chosen << ",\"tied\":" << sel.tied
      << ",\"status\":[";
    for (int i = 0; i < g.getN(); ++i) o << (i ? "," : "") << st[i];
    o << "],\"neighbours\":[";
    for (int i = 0; i < g.getN(); ++i) { o << (i ? ",[" : "["); for (size_t j = 0; j < nb[i].size(); ++j) o << (j ? "," : "") << nb[i][j]; o << "]"; }
    o << "],\"neigh_double\":[";
    for (int i = 0; i < g.getN(); ++i) { o << (i ? ",[" : "["); for (size_t j = 0; j < nb[i].size(); ++j) o << (j ? "," : "") << (g.isDoubleEdge(i, int(j)) ? 1 : 0); o << "]"; }
    o << "],\"candidates\":[";
    for (size_t i = 0; i < sel.candidates.size(); ++i) o << (i ? "," : "") << sel.candidates[i];
    o << "],\"scores\":[";
    for (size_t i = 0; i < sel.scores.size(); ++i) o << (i ? "," : "") << sel.scores[i];
    o << "],\"features\":[";
    for (size_t i = 0; i < sel.features.size(); ++i) o << (i ? "," : "") << sel.features[i];
    o << "]}\n";
    dump << o.str(); dump.flush(); ++dumped;
}

static int slowSelect(int phase, BranchingSolution* s, Graph& g, int root, int v0) {
    g_selPhase = phase; lastCount = 0;
    if (v0 < 0) return v0;
    ++g_target;
    if (policyLearned && s->policy != policy) throw PolicyError{"policy_not_propagated", 71};
    double t0 = diag ? wall() : 0;
    bool elig = false; size_t cnt = 0; int chosen = v0;
    if (randomTest) {
        static vector<int> C;
        eligible(kind, g, root, C); cnt = C.size();
        bool found = false; for (int c : C) if (c == v0) found = true;
        if (!found) throw PolicyError{"original_pivot_not_eligible", 71};
        if (C.size() >= 2) { elig = true; randomState = mix(randomState); chosen = C[randomState % C.size()]; }
    } else {
        Selection sel; bool wantDump = diag && dump.is_open() && policy;
        Selection* detail = (diag ? &sel : nullptr);
        chosen = selectCore(kind, g, v0, root, s->getCap(), policy, detail, &elig, &cnt);
        if (diag && cnt > 0 && sel.originalPos < 0) ++anomalies;
        if (wantDump && sel.scored) {
            ++dumpSeen;
            bool sub = (void*)static_cast<Solution*>(s) != rootSolution;
            bool periodic = dumped < dumpMax && dumpEvery > 0 && (dumpSeen - 1) % dumpEvery == 0;
            bool component = sub && componentDumped < 20;          // always cover early component-subsolver decisions
            if ((periodic || component) && g.getN() <= 20000) { dumpState(g, root, s->getCap(), v0, sel, s); if (sub) ++componentDumped; }
        }
    }
    lastCount = cnt;
    if (elig) {
        ++g_eligible;
        if (policy || randomTest) {
            if (g_departures > 0) ++scoredAfterDeparture;
            if ((void*)static_cast<Solution*>(s) != rootSolution) ++componentScored;
            ++g_scored; if (chosen != v0) ++g_departures;
        }
    }
    if (diag) selectSeconds += wall() - t0;
    return chosen;
}

int caoSlow(BranchingSolution* s, Graph& g, int v0) { return slowSelect(0, s, g, -1, v0); }
int chenSlow(BranchingSolution* s, Graph& g, int v0) { return slowSelect(2, s, g, -1, v0); }
int lpSlow(BranchingSolution* s, Graph& g, int root, int v0) { return slowSelect(4, s, g, root, v0); }

void finish(const char* status, int exitCode, const vector<int>* sol) {
    atomicWrite(summaryPath, summaryJson(status, exitCode, sol));
    if (dump.is_open()) dump.close();
}

}  // namespace fvsb
