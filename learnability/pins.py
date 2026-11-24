"""Immutable experiment-of-record identifiers (do not substitute newer runs)."""
SEA_UPSTREAM = 'https://github.com/karek/FeedbackVertexSet-Experiments'
SEA_COMMIT = 'c0290698f6dfcc48b19b55e1aa915d8ecf61b0a4'
REPOSITORY = 'https://github.com/mohamad-alaalami/fvs-stage-c'
STAGE_C_RUN = '44639720515'
STAGE_C_EXPERIMENT_COMMIT = '3244862ea2905ce24c811b962084c2b8a13310bd'
STAGE_C_RECORDS_COMMIT = 'eece4cfe803a97c47ca178c14caa6b71b1e962c3'   # branch full-results
STAGE_D_RUN = '45059940845'
STAGE_D_EXPERIMENT_COMMIT = '4cf65df9de3af1aacbece3820e2986c0fd2b5620'
STAGE_D_RESULTS_COMMIT = 'a5dbb1eb87ea1052a0240bf4b4da8d364b37a890'    # branch stage-d-results
CPU_BUDGET_S = 10
EXPECTED = {'8': dict(states=1983, candidates=12684), '5': dict(states=2212, candidates=43773), 'LP': dict(states=2307, candidates=14581)}
EXPECTED_STATES = 6502
EXPECTED_CANDIDATES = 71038
EXPECTED_CHUNKS = 555
# Files read from the Stage D experiment commit (path -> purpose).
EXPERIMENT_FILES = {
    'staged/index.json.zz': 'candidate universe (zlib JSON)',
    'staged/validation.json.zz': 'archived native SampleCheck results',
    'stagec/snapshot.py': 'pinned STAGEC1 decoder',
    'staged/PROTOCOL.md': 'Stage D protocol', 'staged/inventory.py': 'eligibility/order definition',
    'staged/run.py': 'record field definitions', 'staged/report.py': 'comparison rule', 'staged/continuation.cpp.inc': 'arm accounting',
    'full/PROTOCOL.md': 'Stage C protocol', 'full/RESULTS.md': 'Stage C results',
}
