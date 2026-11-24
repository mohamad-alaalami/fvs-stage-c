# Feature dictionary: extraction schema v1

These features are **our mechanism-motivated design for FVS branching**, not a published or validated feature set. Nothing here shows that they predict anything. Every feature is computed from the saved pre-decision snapshot and the validated candidate list, before any outcome is joined. Each is therefore available at decision time in the original solver's data structures. Live integration parity and overhead have **not** been established; that needs a separate integration task.

## Definitions

- Active vertex: status 0 (undecided, STATUS_NONE) or 1 (undeletable, STATUS_IN_SAFE), per the pinned `src/lib/Graph.h`. Status -1 is in the solution and -2 is deleted.
- N(v): distinct active vertices in v's adjacency array. Inactive vertex buffers are ignored, and an edge flagged in `neighDouble` has multiplicity 2 (the cap).
- w(v) = |N(v)| + (flagged edges from v to active neighbours). This equals upstream `degWithDouble` on validated states.
- D(v) = undecided neighbours of v; U(v) = undeletable neighbours of v.
- r: the saved LP solve2 root, never recomputed.

| Column | Formula | Motivation (hypothesis) | Cost per state |
|---|---|---|---|
| `f_cand_none_neighbors` | \|D(v)\| | How many open decisions the deletion or protection of v touches | O(deg v) |
| `f_cand_safe_neighbors` | \|U(v)\| | Interaction with protected vertices; Chen's primary selector key | O(deg v) |
| `f_cand_double_edges` | flagged edges at v | Double edges encode constraints that plain degree loses | O(deg v) |
| `f_nbr_none_wdeg_min/mean/max` | min / integer-sum÷count / max of w(u) over u in D(v); 0.0 when D(v) is empty | Separates candidates with equal own degree by how dense their open surroundings are | O(sum of neighbour degrees) |
| `f_state_none_vertices`, `f_state_safe_vertices` | active vertices with status 0 / 1 | Residual problem size | O(N) |
| `f_state_distinct_edges`, `f_state_double_edges` | unordered adjacent active pairs / flagged pairs | Residual density | O(adjacency) |
| `f_state_remaining_threshold` | size_cap − \|X\| (not clamped) | Remaining budget below the strict cutoff (an improving solution may delete threshold − 1 more) | O(1) |
| `f_state_candidate_count` | length of the eligible list | Size of the choice | O(1) |
| `f_lp_root_common_neighbors` (LP only) | \|N(v) ∩ N(r)\| | Merging v into r creates double edges and forced deletions at common neighbours | O(deg v) with a root-neighbour set |

Empty undecided neighbourhoods give 0.0 summaries, while `f_cand_none_neighbors = 0` keeps the emptiness explicit. A neighbour's weighted degree is its full active weighted degree. No feature depends on adjacency iteration order. Total cost: O(allocated N + active adjacency entries + sum of candidate degrees) per state, plus decoding. This is a complexity statement, not a runtime guarantee.

## Model-input allowlists (v1)

- 8 and 5: the first 12 columns.
- LP: 11 columns, excluding `f_cand_safe_neighbors` and `f_state_safe_vertices`. In this dataset, every saved LP state has exactly one SAFE vertex (the root) and every candidate neighbours it, which the extraction validates. These are observations about this dataset, not universal facts.

Not inputs, kept as metadata or diagnostics only:

- IDs, candidate order, the original-pivot flag, sampling kind and index, depth, isSub, solver history;
- allocated N and stored M, runner data, all outcomes, supplied optima;
- `diag_cand_distinct_degree`, `diag_cand_weighted_degree`, `classical_score_json`, `classical_rank`. The original scores are: Cao, w(v), tied across a state's candidates; Chen, (\|U(v)\|, w(v)); LP, w(v).

State-level columns repeat on every candidate row. A purely additive linear ranker cancels them in score differences, and appending them does not change that. Interactions or nonlinear models are a future training decision.

## Research grounding (context only)

None of these sources shows that these particular FVS features work.

- Khalil et al., *Learning to Branch in Mixed Integer Programming* (AAAI 2016): candidate ranking and decision-level weighting.
- Gupta et al., *Hybrid Models for Learning to Branch* (NeurIPS 2020): counting inference CPU cost.
- Gupta et al., *Lookback for Learning to Branch* (2022): prediction accuracy versus solver performance.
- Kiljan and Pilipczuk, *Experimental Evaluation of Parameterized Algorithms for Feedback Vertex Set* (SEA 2018), and the pinned SEA source: the solver mechanisms these features describe.
