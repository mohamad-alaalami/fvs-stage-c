"""Create the full-run instrumented source copy; never edit the pinned checkout.
Usage: python prepare.py <pinned upstream src dir> <destination dir>

1. Apply the smoke-test edits unchanged (stagec/prepare.py): decision hooks at the three branch
   sites, hint flag, StageC::guard in reduce(), input-label map, Main.cpp wrapper.
2. Add search-node hooks. Each entry to branching()/solve1()/solve2() is one node with exactly one
   outcome: branch, leaf_solution, pruned, no_pivot, delegate_to_solve1, reduction_recursion
   (or interrupted by a CPU/disk/external stop). The hooks only count; no control flow changes.
3. Replace StageC.h/.cpp with the full-run edition (counters, histograms, sampled states).
"""
import pathlib, shutil, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
base_src, dest = sys.argv[1], pathlib.Path(sys.argv[2]).resolve()
subprocess.run([sys.executable, '-I', str(HERE.parent / 'stagec/prepare.py'), base_src, str(dest)], check=True)


def edit(file, old, new):
    p = dest / file; s = p.read_text(); assert s.count(old) == 1, (file, old, s.count(old)); p.write_text(s.replace(old, new))


S = 'solutions/Solution.h'
edit(S, '    friend class StageC;', '    friend class StageC;\n    friend struct StageDecision;\n    friend struct StageFrame;')
edit(S, '        StageFrame frame;\n        if (reduce(brG) == RED_NOSOLUTION)\n            return;',
        '        StageFrame frame(0,this);\n        if (reduce(brG) == RED_NOSOLUTION) { StageC::noSolution(this); return; }')
edit(S, '        if (v < 0)\n            return;\n\n        stageContinue(brG,v);',
        '        if (v < 0) { StageC::outcome(StageC::OUT_NO_PIVOT); return; }\n\n        stageContinue(brG,v);')
edit(S, '    void trySolUpdate(Graph& brG) {', '    void trySolUpdate(Graph& brG) {\n        StageC::leaf(this);')
H = 'solutions/HalfIntBranching.cpp'
edit(H, '    StageFrame frame;\n    ReductionResult r = reduce(g);\n    if (r == RED_NOSOLUTION)\n        return;',
        '    StageFrame frame(1,this);\n    ReductionResult r = reduce(g);\n    if (r == RED_NOSOLUTION) { StageC::noSolution(this); return; }')
edit(H, '    if (s == -1) \n        return;', '    if (s == -1) { StageC::outcome(StageC::OUT_NO_PIVOT); return; }')
edit(H, '    StageFrame frame;\n    kernelize_switch = false;\n    ReductionResult r = reduce(g);\n    kernelize_switch = true;\n    if (r == RED_NOSOLUTION)\n        return;\n\n    if (!g.degree(s)) {\n        solve1(g);',
        '    StageFrame frame(2,this);\n    kernelize_switch = false;\n    ReductionResult r = reduce(g);\n    kernelize_switch = true;\n    if (r == RED_NOSOLUTION) { StageC::noSolution(this); return; }\n\n    if (!g.degree(s)) {\n        StageC::outcome(StageC::OUT_DELEGATE_SOLVE1);\n        solve1(g);')
edit(H, '            g.merge(s, toMerge[i]); \n\n        solve2(g, s);', '            g.merge(s, toMerge[i]); \n\n        StageC::outcome(StageC::OUT_REDUCTION_RECURSION);\n        solve2(g, s);')
edit(H, '        if (v == -1)\n            return;', '        if (v == -1) { StageC::outcome(StageC::OUT_NO_PIVOT); return; }')
for name in ['StageC.h', 'StageC.cpp']:
    shutil.copy2(HERE / name, dest / name)
print(dest)
