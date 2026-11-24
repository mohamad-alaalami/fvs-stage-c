"""Create the integration-v1 solver source from the pinned SEA source; never edit the pinned checkout.

Usage: python prepare.py <pinned upstream src dir> <destination dir>

Every edit is an exact, asserted single-occurrence text substitution (line endings normalised to LF).
Only three selector sites become policy-controlled; everything else is counting or plumbing:

  Solution.h          + policy pointer (null = original selector), propagated to component subsolvers
                        created by reduceConnectedComponents (the only place solvers are cloned);
                        node frame / decision counter in branching(); CPU guard in reduce()
  SolutionVariants.h  Sol8::chooseBranchingVertex    -> fvsb::caoSelect(original getMaxDegVWDouble pivot)
                      ICBranchingSolution fallback   -> fvsb::chenSelect(original getMaxDegToUndeletable pivot)
                        (compression hints are untouched; only the fallback after they run out)
  HalfIntBranching    solve2 neighbour branch        -> fvsb::lpSelect(root, original getMaxDegNeigh pivot)
                        (root selection in solve1, relaxation reductions and child bodies untouched)
  Main.cpp            fvsb::init / attach / finish around the unchanged solve and output
  friend declarations for the replay tool only (no code generated)

Reductions, pruning, incumbent updates, component handling, recursion, child construction and child
order are the pinned code. In the baseline policy each hook returns the original pivot unchanged.
"""
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
NATIVE = ['FvsHooks.h', 'FvsHooks.cpp', 'FvsPolicy.h', 'FvsPolicy.cpp']

EDITS = [
    ('solutions/Solution.h', '#include <cassert>\n', '#include <cassert>\n#include "../FvsHooks.h"\n'),
    ('solutions/Solution.h', 'class BranchingSolution : public Solution {\npublic:\n',
     'class BranchingSolution : public Solution {\n    friend struct FvsReplayAccess;  // integration-v1 replay tool only\npublic:\n'
     '    fvsb::Policy* policy = nullptr;   // integration-v1: frozen learned policy; null = original selector\n'),
    ('solutions/Solution.h', '        while(true) {\n            if (brG.getXSize() >= size_cap || this->impossible(brG))',
     '        while(true) {\n            fvsb::guard();\n            if (brG.getXSize() >= size_cap || this->impossible(brG))'),
    ('solutions/Solution.h', '            BranchingSolution *s = (BranchingSolution *)clone(size_cap - brG.getXSize());\n',
     '            BranchingSolution *s = (BranchingSolution *)clone(size_cap - brG.getXSize());\n'
     '            s->policy = policy;   // integration-v1: component subsolvers use the same frozen policy\n'),
    ('solutions/Solution.h',
     '    void branching(Graph& brG) {\n        if (reduce(brG) == RED_NOSOLUTION)\n            return;\n\n'
     '        int v = chooseBranchingVertex(brG);\n        if (v < 0)\n            return;\n\n        Graph g2(brG);\n',
     '    void branching(Graph& brG) {\n        fvsb::Frame fvsbFrame(0, isSub);\n        if (reduce(brG) == RED_NOSOLUTION)\n            return;\n\n'
     '        fvsb::preSelect();\n        int v = chooseBranchingVertex(brG);\n        if (v < 0)\n            return;\n        fvsb::decision(-2, v);\n\n        Graph g2(brG);\n'),
    ('solutions/SolutionVariants.h', 'class Sol8 : public BranchingSolution {\npublic:\n',
     'class Sol8 : public BranchingSolution {\n    friend struct FvsReplayAccess;  // integration-v1 replay tool only\npublic:\n'),
    ('solutions/SolutionVariants.h',
     '    virtual int chooseBranchingVertex(Graph &brG) {\n        return chooseMaxDeg2(brG);\n    }\n\nprotected:\n    int br2;\n',
     '    virtual int chooseBranchingVertex(Graph &brG) {\n        return fvsb::caoSelect(this, brG, chooseMaxDeg2(brG));\n    }\n\nprotected:\n    int br2;\n'),
    ('solutions/SolutionVariants.h',
     '    virtual Solution *clone(int cap) { return new ICBranchingSolution(cap); }\n\n'
     '    virtual int chooseBranchingVertex(Graph &brG) {\n        while (!branching_hints.empty()) {\n'
     '            int v = branching_hints.back();\n            branching_hints.pop_back();\n            if (brG.isNone(v))\n'
     '                return v;\n        }\n        return chooseMaxDegToUndeletable(brG);\n    }\n',
     '    virtual Solution *clone(int cap) { return new ICBranchingSolution(cap); }\n\n'
     '    virtual int chooseBranchingVertex(Graph &brG) {\n        while (!branching_hints.empty()) {\n'
     '            int v = branching_hints.back();\n            branching_hints.pop_back();\n            if (brG.isNone(v))\n'
     '                return v;\n        }\n        return fvsb::chenSelect(this, brG, chooseMaxDegToUndeletable(brG));\n    }\n'),
    ('solutions/HalfIntBranching.h', 'class HalfIntBranching : public BranchingSolution {\n',
     'class HalfIntBranching : public BranchingSolution {\n    friend struct FvsReplayAccess;  // integration-v1 replay tool only\n'),
    ('solutions/HalfIntBranching.cpp', 'void HalfIntBranching::solve1(Graph& g) {\n',
     'void HalfIntBranching::solve1(Graph& g) {\n    fvsb::Frame fvsbFrame(1, isSub);\n'),
    ('solutions/HalfIntBranching.cpp', 'void HalfIntBranching::solve2(Graph& g, int s) {\n',
     'void HalfIntBranching::solve2(Graph& g, int s) {\n    fvsb::Frame fvsbFrame(2, isSub);\n'),
    ('solutions/HalfIntBranching.cpp', '    if (s == -1) \n        return;\n',
     '    if (s == -1) \n        return;\n    fvsb::decision(3, s);\n'),
    ('solutions/HalfIntBranching.cpp',
     '        pair<int, int> md = g.getMaxDegNeigh(s);\n        int v = md.first;\n        if (v == -1)\n            return;\n',
     '        pair<int, int> md = g.getMaxDegNeigh(s);\n        int v = fvsb::lpSelect(this, g, s, md.first);\n        if (v == -1)\n            return;\n        fvsb::decision(4, v);\n'),
    ('lib/Graph.h', 'class Graph {\n', 'class Graph {\n    friend struct FvsReplayAccess;  // integration-v1 replay tool only\n'),
    ('Main.cpp', '#include "solutions/SolutionVariants.h"\n', '#include "solutions/SolutionVariants.h"\n#include "FvsHooks.h"\n'),
    ('Main.cpp', '    t.read_input(&g);\n', '    fvsb::init(argc, argv);\n    t.read_input(&g);\n    fvsb::afterInput();\n'),
    ('Main.cpp', '    vector<int> sol = s->solve(g);\n    delete s;\n',
     '    vector<int> sol;\n'
     '    try { fvsb::attach(s); sol = s->solve(g); }\n'
     '    catch (const fvsb::Stop& stop) { fvsb::finish(stop.reason, stop.code, nullptr); return stop.code; }\n'
     '    catch (const fvsb::PolicyError& e) { fvsb::finish(e.reason, e.code, nullptr); return e.code; }\n'
     '    delete s;\n'),
    ('Main.cpp', '    t.printNames(sol);\n\n    return 0;\n',
     '    t.printNames(sol);\n    cout.flush();\n    fvsb::finish("completed", 0, &sol);\n\n    return 0;\n'),
]


def prepare(base, dest):
    base = pathlib.Path(base).resolve(); dest = pathlib.Path(dest).resolve()
    if dest.exists():
        raise SystemExit(f'destination {dest} exists; preserve it')
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns('build', 'a.err'))
    touched = set()
    for rel, old, new in EDITS:
        p = dest / rel
        text = p.read_bytes().decode('utf-8').replace('\r\n', '\n')
        n = text.count(old)
        assert n == 1, (rel, old[:80], n)
        p.write_bytes(text.replace(old, new).encode('utf-8')); touched.add(rel)
    for rel in sorted(set(r for r, _, _ in EDITS)):
        assert (dest / rel).read_bytes().count(b'\r') == 0, rel
    for name in NATIVE:
        shutil.copyfile(HERE / 'native' / name, dest / name)
    return dest, sorted(touched)


if __name__ == '__main__':
    d, t = prepare(sys.argv[1], sys.argv[2])
    print(d, t)
