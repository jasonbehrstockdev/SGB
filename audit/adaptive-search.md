# Adaptive square search

SGB can remove a cubic source of work in the sparse random-graph regime
`p = alpha / sqrt(n)`. A second search, which pairs missing edges, is quadratic
when their number is linear in `n`. The program selects between these exact
searches with a work heuristic. The improvement comes from changing how induced
squares are found. It preserves the square graph, its component supports, and
the CFS convention allowing complete join factors.

These are bounds for the search under stated conditions. An arbitrary graph
can contain quartically many induced squares, so a program that explicitly
lists all of them cannot have a general quadratic running time.

## Two exact searches

Use `n`, `m`, `N(v)`, and `d(v)` for the original graph's vertex count, edge
count, neighbor lists, and degrees.

The search first excludes universal vertices, since none can belong to an
induced square. This removes only irrelevant search candidates; original
vertex labels and neighbor positions are retained. Write `A` for the remaining
vertices, `r = |A|`, and `N_A(v)` and `d_A(v)` for their neighbor lists and degrees
in the induced graph on `A`. Write `m_A` for its edge count and
`q = r(r-1)/2 - m_A` for its number of missing edges. Every original missing edge
has both endpoints in `A`, so this is also the original number of missing edges.
When no vertices are universal, `r=n` and these are the original graph's values.

Adjacency tests use a bounded bit matrix when it fits, with a hash-based
fallback for larger graphs. Bit lookup has constant cost; hash lookup has
expected constant cost.
This replaces repeated scans through Boost's adjacency lists.

### Sparse search: group two-edge paths by their endpoints

For each vertex `u` in `A`, consider only squares whose smallest vertex is `u`:

1. For each remaining neighbor `w > u`, visit the remaining neighbors `v` of `w`.
2. If `v > u` and `uv` is a missing edge, put `w` in the bucket for `v`.
3. In each bucket, test pairs of its members `a, b`. If `ab` is a missing edge,
   emit the square with diagonals `uv` and `ab`.
4. Clear the touched buckets before moving to the next `u`.

Every bucket contains common neighbors of `u` and `v`. Thus the four perimeter
edges of an emitted square exist and both diagonals are absent. Conversely,
every induced square has a unique smallest vertex `u` and opposite vertex `v`;
its other two vertices appear together in that bucket. It is emitted exactly
once, so a hash table of previously discovered squares is unnecessary.

The buckets are reused one vertex at a time. A bucket for `v` never needs more
than `d_A(v)` entries, so their aggregate capacity is proportional to `n + m_A`
with ordinary geometric vector growth. The search does not retain all
two-edge paths of the graph simultaneously.

### Dense search: pair the missing edges

First list the missing edges. For each unordered pair of them, test whether
they have four distinct endpoints and all four cross edges exist. If so, these
two missing edges are the diagonals of an induced square.

Every induced square has exactly two diagonals, so this search also emits each
square exactly once. Its work is `O(n^2 + q^2)`, including the scan that builds
the missing-edge list. It is especially useful when `q` is small even though
the original graph has many edges.

## Selecting a search

The choice uses graph structure, rather than assuming that one fixed density
cutoff works for every size. It compares the actual number of forward neighbor
visits in the sparse search,

`F = sum_{u in A} sum_{w in N_A(u), w > u} d_A(w)`,

with an estimate for scanning vertex pairs and testing pairs of missing edges:

`r(r-1)/2 + 4 * q(q-1)/2`.

This is a cost heuristic, not a guarantee that the selected path is always the
fastest. In particular, `F` does not include the subsequent pairs tested inside
common-neighbor buckets. The estimate deliberately avoids running an expensive
search merely to select a search. Both paths are exact, so the choice changes
performance rather than results. Work estimates must avoid integer overflow,
and the missing-edge list is allocated only if that path is selected.

The adjacency bit matrix has a 64 MiB allocation cap; larger instances use the
sparse hash representation. The matrix requires
`n * ceil(n/64)` machine words, while the fallback uses `O(n+m)` storage.
This prevents an unconditional quadratic matrix allocation on a very large,
sparse graph.

## Why the sparse search can be quadratic

Let `S` be the number of induced squares and `D` the number of induced diamonds
(four vertices inducing exactly five edges). The forward neighbor visits are
bounded by `sum_v d(v)^2`. Every pair tested inside a common-neighbor bucket
forms either a square or a diamond. The smallest-vertex rule counts every
square once and a subset of diamonds once. Consequently, the search takes

`O(n + m + sum_v d(v)^2 + S + D)`

expected work, in addition to initializing the optional bit matrix. The
expectation here concerns hash lookup when the fallback is used. The combinatorial
visit counts themselves are deterministic for a supplied graph.

For an Erdos-Renyi graph `G(n,p)` with fixed `alpha > 0` and
`p = alpha / sqrt(n)`, the relevant expectations are:

| Quantity | Expected order |
| --- | --- |
| `sum_v d(v)^2` | `Theta(n^2)` |
| Induced squares `S` | `Theta(n^2)` |
| Induced diamonds `D` | `Theta(n^(3/2))` |

The exact expectations for the last two rows are
`E[S] = 3 * C(n,4) * p^4 * (1-p)^2` and
`E[D] = 6 * C(n,4) * p^5 * (1-p)`.
The new enumeration therefore has expected quadratic cost in this regime.

The previous neighbor walk repeatedly searched another neighbor list to test
adjacency. It makes on the order of `n^4 p^3` inner visits in this sparse random
regime, and the negative adjacency tests scan on the order of `np` entries.
The resulting leading expected work is on the order of `n^5 p^4`, which is
cubic when `p = alpha / sqrt(n)`.

The regime matters: holding `p` fixed while increasing `n` generally makes
`E[S]` quartic, not quadratic. Timings at one fixed size and several densities
measure practical speed; a scaling study holding `alpha` fixed is needed to
assess the claimed change of growth rate.

## Dense graphs with few missing edges

When `q = O(n)`, the **missing-edge-pair search** takes `O(n^2)` work. This
includes graph families with bounded average degree in the complement.
Scanning the dense input itself already requires quadratic work.

This is a bound for that search path, not a guarantee that the automatic
heuristic chooses it on every such graph. For example, consider an active core
of size `r = Theta(n^(2/3))` with `q = Theta(n)` missing edges, joined to the
remaining universal vertices. The estimates for forward wedge visits and
missing-edge pairs can both be quadratic in the original `n`, so the heuristic
can select wedges. Their subsequent diamond checks can nevertheless have order
`q*r^2 = Theta(n^(7/3))`. The selector's omitted candidate-pair term matters.

For the measured random family with constant positive expected complement
degree, `q = Theta(n)` and `r = Theta(n)` with high probability. The dense
estimate is then quadratic while the forward-wedge estimate is cubic, so the
automatic choice selects missing-edge pairs for sufficiently large graphs with
high probability. This supports that specific scaling study without extending
the claim to all graphs of the same density.

Universal vertices are recognized by `d(v) == n-1`, using the simple-graph
invariant. This removes the old nested adjacency scans from CFS classification;
those scans could otherwise remain cubic near complete graphs. The CFS coverage
target excludes universal vertices. Skipping them during search is exact
because no induced square contains one; computed support sets remain literal.

## Preserving the existing output

The search can visit squares in a different order, but the result is reordered
to match the previous neighbor walk. A square's first discovery was determined
by its smallest vertex `u`, the original positions of its two adjacent vertices
in `N(u)`, and the position of its opposite vertex in the later neighbor's list.
These integer keys restore the former square labels and diagonal orientation.
Each key field is in `[0,n)`, so four stable counting-sort passes take
`O(n+S)` time and avoid adding a comparison-sort `S log S` term.

The subsequent diagonal index, union-find components, and literal support
calculation retain their meanings. When verbose/debug output requests the
square graph, every actual square-graph edge is still built. CFS requires an
actual square component covering all non-universal vertices of a connected
input graph. Complete-only and empty-graph conventions for a future thickness
base case remain separate.

## Bounds for the whole program

The component stage has expected `O(S * alpha_UF(S))` work, where `alpha_UF` is
the inverse Ackermann function used in union-find analysis. It is distinct
from the graph-density parameter `alpha`. Support accumulation still uses
ordered sets and can require `O(S log n)` work. Input parsing and requested
output also have their own costs. Thus a quadratic enumeration result should
be described as a near-quadratic analysis pipeline with these additional
factors, not as a proved quadratic bound for every end-to-end execution.

For example, the balanced complete bipartite graph has
`C(n/2,2)^2 = Theta(n^4)` induced squares. Its full square graph has
`Theta(n^6)` edges. These are unavoidable output costs when listing those
objects. They do not establish the same lower bounds for a future algorithm
that only decides CFS using a compressed representation; that would require a
separate algorithm and proof.

## Measurements

The [paired density study](performance-adaptive-results.json) uses the existing
240-graph corpus: 20 distinct graphs at each of six densities for 1,000 and
3,000 vertices, identical before/after inputs, and a two-minute limit. Its
baseline is the previously optimized version at `0ebc8fe`, so this measures
the additional search changes in `3797211`.

The baseline completed 237/240 runs and the new version completed all 240.
Every completed output matched the independent reference; all 237 completed
pairs had identical CSV. At 3,000 vertices and 1% density, median elapsed time
fell from 17.894 seconds to 0.1294 seconds, with a median paired speedup of
139.05 times. The three baseline timeouts occur in the 1.5% group and remain
censored measurements. A [separate dense study](performance-adaptive-dense-results.json)
adds 20 graphs at each of 50%, 90%, and 98% density on 100 vertices; both builds
completed all 60 pairs.

The [scaling study](performance-adaptive-scaling.json) holds `alpha=0.5` fixed
for the sparse family and expected complement degree 2 fixed for the dense
family. It uses 20 graphs at each of 250, 500, 1,000, and 2,000 vertices in each
family, for 160 cases. Every sparse case selected the wedge search, and every
dense case selected the missing-edge search.

| Doubling the vertex count | Sparse median candidate-count ratio | Dense median candidate-count ratio |
| --- | ---: | ---: |
| 250 to 500 | 3.865 | 3.881 |
| 500 to 1,000 | 3.863 | 4.069 |
| 1,000 to 2,000 | 3.950 | 4.085 |

Ratios near four agree with the quadratic candidate growth predicted above.
These counters sum forward wedge visits, pairs inside wedge buckets, and pairs
of missing edges; they exclude setup, allocation, rank lookup, and ordering.
The scaling timer measures `findSquares`, including its setup and ordering,
while excluding input-graph construction, result validation, component/support
analysis, and output. It is separate from the complete CLI timings in the
paired studies.

Sparse median search times grew by factors 3.165, 3.746, and 3.636 when doubling
the vertex count. Dense median search times grew by 4.600, 6.082, and 4.862.
The larger dense time factors show that candidate counts alone do not describe
the wall-time growth over these sizes. The experiment supports the quadratic
enumeration argument through its operation counts; it does not establish a
quadratic measured wall-time law for the full program.

The [artifact verification record](performance-adaptive-validation.json)
checks input and build identities, completed outputs, independent summary
statistics, scaling strategy estimates and counters, and exact-output
equivalence. It also records the normal and sanitizer test evidence.
