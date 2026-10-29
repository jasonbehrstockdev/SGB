# Optimization and improvement plan

These are proposals for work after the correctness repairs. They are not claims
that a particular speedup has already been measured. Keep the current version
and the independent reference available while changing representations or
algorithms. The [code-base assessment](strengths-and-weaknesses.md) explains the
tradeoffs behind this plan.

## Rules that optimizations must preserve

- Enumerate induced squares: both diagonals must remain nonedges.
- Keep the literal square graph and its actual original-vertex supports.
- For CFS only, allow complete join factors. A CFS graph need not have literal
  square support equal to the total input vertex count.
- Treat empty/square-free cases, disconnected input, duplicate-edge normalization,
  and historical self-loop input consistently with the documented interface.
- Preserve vertex identities in any data returned to a future thickness algorithm.

Use selected 100-vertex graphs with studied structure as the main validation
corpus. Add targeted small regressions for a specific failure; do not make
exhaustive enumeration of six-vertex graphs the primary validation strategy.

## Suggested order

| Order | Change | Expected benefit | Main cost or risk |
| --- | --- | --- | --- |
| 1 | Measure analysis phases and resource use | Identifies the actual bottleneck for relevant graphs | Measurement overhead and misleading single-run timings |
| 2 | Canonical square keys for deduplication | Avoids repeatedly scanning every previously found square | Canonicalization mistakes; hash-table memory |
| 3 | Index squares by diagonal | Avoids testing unrelated pairs; can avoid storing square edges for component-only work | Confusing a component representation with the literal square graph |
| 4 | Profile adjacency matrices/bitsets against lists | Faster edge tests and common-neighbor operations where appropriate | Quadratic input-graph storage; maintaining consistent representations |
| 5 | Expose a reusable analysis result/API | Supports thickness work and richer verification | Requires explicit mathematical and compatibility contracts |
| 6 | Strengthen experiment and build automation | Makes regressions and scientific comparisons easier to reproduce | Maintenance across platforms and toolchain versions |

The order is a starting point. If phase measurements show a different dominant
cost, change the order instead of optimizing a function merely because it is
easy to rewrite.

## 1. Establish a useful performance baseline

Measure parsing, graph generation, square enumeration/deduplication, square
connectivity, support accumulation, and serialization separately. Record input
vertices/edges, square count, square-graph edges when materialized, component
count, elapsed time, and peak memory where the platform supports it.

Use repeated runs and report a distribution or median, with compiler,
optimization flags, Boost version, hardware, and input hashes. Run with verbose
output disabled when measuring computation. Keep end-to-end timings as well;
they answer a different question from time spent in the mathematical core.

Extend the existing 100-vertex set deliberately: near-complete chord-rich
graphs, controlled bipartite examples, multiple overlapping square components,
larger complete join factors, and selected small-world graphs. Choose sizes
within a declared resource budget; do not start with K50,50 merely because it
has only 100 vertices. Its 1,500,625 squares already make the current all-pairs
construction a severe workload.

The present random samples at different densities use the same seeds and have
nested edge sets. That is useful for paired structural comparisons. Add distinct
seeds if the goal becomes estimating frequencies or a transition threshold,
and keep those statistical experiments separate from regression tests.

## 2. Deduplicate with a canonical square key

Normalize each diagonal `(u,v)` to `(min(u,v), max(u,v))`, then order the two
diagonals lexicographically. The resulting four integers give one representation
for all orientations of the same square.

Keep a hash set or ordered set of these keys while retaining a vector if stable
square indices are needed. If `r` candidate occurrences are found and `s`
distinct squares are retained, repeated linear membership checks can require
work proportional to `r*s`. Hashing offers expected constant-time membership;
an ordered set provides logarithmic membership without relying on hash quality.
Either choice has allocation and memory costs that should be measured.

Check equality against the full key even when hashes match. Verify that vertex
relabeling, diagonal reversal, and swapping the two diagonals do not change the
square count or component/support results. Preserve deterministic presentation
by sorting at an output boundary if hash iteration changes ordering. Do not
mistake a new enumeration order for a mathematical difference.

## 3. Use diagonal incidences to find square connectivity

Build a map from each canonical nonedge diagonal to the squares containing it.
Each square contributes exactly two incidences. All squares in one diagonal
bucket form a clique in the square graph.

For component and CFS calculations, union each square with the first square
seen for its diagonal. This computes exactly the same connected components
without comparing every pair of squares or storing every square-graph edge.
It uses at most a constant number of union operations per square, plus map
operations and support processing. The independent benchmark reference already
uses this approach and provides a useful comparison implementation.

For callers requesting the explicit square graph, materialize the pairs within
each diagonal bucket. This avoids unrelated pair comparisons, but it cannot
avoid the cost of emitting the actual edges. A bucket with `b` squares itself
contributes `b(b-1)/2` edges. Keep this explicit mode separate from a
component-only mode; a disjoint-set structure is not the literal square graph.

The repair already accumulates original-vertex support once per square after
component labels are final. Preserve that improvement. A possible smaller
follow-up is inserting the four endpoints directly, avoiding a temporary
four-element `std::set` for every square. Compare that with support bitsets if
profiling identifies allocations as significant. If support is instead merged
during union operations, check that changes of representative do not lose or
duplicate state; a separate final pass is simpler to verify.

Validate full component partitions and support sets, not only the final CFS
boolean or largest support. Two incorrect partitions can share those summary
statistics. Keep the complete-join-factor exclusion in classification, outside
the literal support data.

## 4. Consider adjacency bitsets and common-neighbor enumeration

For graph families where edge lookup is frequent, a matrix or bitset row for
each vertex can provide direct adjacency tests. For a nonedge `(u,v)`, intersect
their neighbor sets; every nonadjacent pair inside that intersection completes
an induced square with `(u,v)` as one diagonal.

This supplies a possible enumeration strategy as well as a storage change.
It must check that the second pair is a nonedge, and must either enforce an
ordering between the two diagonals or deduplicate because each square has two
diagonals. Keep the old enumerator as a differential check while introducing it.

The storage tradeoff is significant: bitsets need roughly `n^2` bits, while a
plain boolean matrix can use more depending on representation. Sparse graphs
with very many vertices may favor sorted adjacency lists or a hybrid. At 100
vertices, test both on representative structures; do not assume the best choice
there will remain best for much larger inputs.

## 5. Prepare a small library interface for thickness

Promote the repaired separation of parsing, generation, analysis, and formatting
into an interface usable outside the executable. The existing private `Analysis`
type already holds squares, component membership, literal supports, and the CFS
decision. An exported result should also expose the actual complete-join-factor
vertices rather than only their count. Allow callers to request only the
information they need, especially whether the explicit square-graph edge set
must be constructed.

Before integrating thickness, document complete-graph and empty-graph base
cases, the meaning of graph restriction, and how original vertex IDs survive
recursion. Tests should demonstrate the distinction between "the square
component has support 98" and "the 100-vertex graph is CFS after allowing K2."
Do not encode that distinction only in CLI text.

Once these contracts are stable, pure analysis functions become easier to test
with relabelings, disjoint unions, and complete joins. For example, joining a
graph with a complete universal factor adds no induced squares; it must not
enlarge a literal square support. These structural checks can expose bugs that
a table of scalar outputs misses.

## 6. Improve reproducibility and operational use

Add continuous integration that builds with strict warnings, runs the targeted
regressions, and checks the 100-vertex reference results. Include sanitizer runs
where the platform supports them. Test another compiler or operating system
before claiming broad portability. Keep benchmark performance measurements out
of ordinary pass/fail CI unless their environment and tolerance are controlled.

For research batches, save input graphs or hashes, the complete invocation,
random seed, generator model/version, source revision, toolchain, and result
schema. A seed by itself may not reproduce standard-library distribution
results across different implementations. Consider a versioned JSON result
format if future consumers need component membership and supports, while
retaining a stable CSV summary for simple analyses.

Expose optional time/memory or square-count limits for batch processing. A
limit should produce a distinct incomplete/error result, never a false CFS
classification. A checkpoint or per-graph result file can keep a long batch
from losing completed work if a later graph exceeds its budget.

Choose a license if the repository is intended for redistribution or reuse;
this is an author decision, not an implementation fix. Document supported
compiler/Boost versions and how the historical binary differs from source-built
executables.

## Completion criteria for each proposed change

Require agreement with the reference and structured expectations, preservation
of literal supports and CFS conventions, and no regression in error handling.
For a performance claim, retain before/after phase timings and memory results
on the same inputs and environment. Keep an optimization only when its benefit
justifies its added code, memory, and maintenance cost.
