# Code-base assessment

This assessment records the repaired implementation at commit `cbdb90f`.
The subsequent [performance work](performance.md) addresses the linear square
deduplication and all-pairs square comparisons discussed below; the broader
library, portability, resource-budget, and thickness recommendations remain.

This assessment concerns the repaired source and its supporting tests. The
original 2024 import remains a useful historical baseline; the archived macOS
executable is not evidence that a current source build behaves identically.
The audit's findings report records defects and their resolution. The points
below assess the design and its suitability for further mathematical work.

## Overall assessment

SGB has a clear mathematical core: identify induced squares, connect squares
that share a diagonal, and compute the original-vertex support of each square
component. This makes it a useful foundation for studying examples and checking
conjectures. Its main remaining constraint is the cost of explicitly enumerating
and connecting squares. Reliable handling of inputs and outputs makes the
program easier to trust, but does not remove that combinatorial growth.

The distinction between square graphs and CFS is now essential to the design.
The square graph records the supplied graph literally. CFS may ignore a complete
join factor when deciding whether a square component has full support. For
example, the 100-vertex pair-path joined with K2 is CFS while its actual largest
square support is 98. A support fraction of 0.98 and a true CFS result are
consistent; changing the support to 100 would lose information.

## Strengths

### The representation closely follows the mathematics

Representing a square by its two nonedge diagonals exposes the adjacency rule
directly. Component supports are explicit sets of original vertices, rather
than an opaque scalar derived from the final classification. These choices
make intermediate results inspectable and give future thickness work something
more informative than a yes/no answer.

The original design separates several mathematical operations into functions.
That separation made it possible to test square enumeration, square adjacency,
and support calculations independently of the command-line interface. The
repair makes those boundaries clearer: an `Analysis` value collects squares,
components, supports, and classification before formatting. It also accumulates
component supports in one pass through the squares, avoiding the original
repeated scan for every component.

### Established graph operations are reused

Boost supplies graph storage and connected-component computation. The project
does not need to maintain its own general graph traversal framework. The
application remains a small C++11 program with header-only Boost dependencies,
and the benchmark tooling uses standard C++ and Python facilities. This keeps
the build understandable and avoids a large dependency stack.

### Results can be inspected and reproduced

Graph export, component-support output, and per-graph statistics make it possible
to investigate unexpected classifications. The repair work strengthens that
original intent with validated input, explicit errors, consistent machine-readable
output, and controlled random seeds. Saving the actual generated graph is still
the strongest way to reproduce an experiment across compiler/library versions.

The unchanged original import and original benchmark results are retained. A
future mathematical or implementation change can therefore be compared with a
known version instead of relying on recollection of earlier runs.

### The validation now has a useful structural basis

The 100-vertex benchmark set includes full square support, multiple square
components, pendant vertices, a complete join factor, disconnected graphs,
square-free input, and seeded random samples. Several structured examples have
counts derived directly from their construction. The independent reference
enumerates four-vertex subsets and computes square components through diagonal
incidences, providing a different implementation from SGB's main algorithm.

Targeted small regressions remain useful for parser boundaries and previously
observed failures. They complement the representative 100-vertex examples;
they do not replace those examples as evidence about the structures of interest.
The repair pass ran 20 regression groups and all 15 benchmark cases in normal
and address/undefined-behavior sanitizer builds, and the strict-warning build
completed without warnings. These are reproducible checks of the audited
implementation, with the remaining limits described below.

## Weaknesses and limitations

### The number of squares matters more than vertex count alone

Let `n` be the input vertex count, `s` the number of induced squares, and `q`
the number of square-graph edges. Explicit square-graph construction tests
every pair of squares, requiring `s(s-1)/2` adjacency comparisons, and storing
the resulting graph costs at least space proportional to `s + q`.

The same 100-vertex size can therefore describe very different workloads.
The balanced complete bipartite graph K50,50 has
`choose(50,2)^2 = 1,500,625` induced squares. Testing every pair would require
more than a trillion comparisons. The current benchmark set is useful for
correctness and initial measurements; it does not establish that arbitrary
100-vertex inputs will be inexpensive.

### Some data structures favor clarity over repeated queries

Square deduplication searches the accumulated list, and the adjacency-list
representation repeatedly answers edge-membership queries during enumeration.
These operations can dominate before connected-component computation begins.
They are reasonable candidates for optimization, but an alternative should be
selected using measurements on relevant graph families, not asymptotic notation
alone. Maintaining two graph representations also introduces consistency and
memory costs.

### The application is still primarily an executable

The repaired parsers and `Analysis` result provide clear internal boundaries,
but the mathematical types and functions still live in the executable's private
implementation. A stable library interface would make it easier for a thickness
implementation to reuse those results without parsing text, including the
program source, or duplicating conventions. Such an interface should expose
literal supports, the actual complete-join-factor vertices, and classification
separately.

### Evidence and operational limits remain bounded

The selected benchmarks cover useful cases, but fifteen examples are not a
comprehensive sample of graph structure. The random samples reuse seeds across
densities, giving nested edge sets rather than independent samples. Small-world
boundary regressions check implementation behavior; they do not establish the
statistical properties of large generated collections.

Passing tests and sanitizer checks does not prove the implementation correct
for every graph. There is also no established general input-size/time/memory
budget for scientific batches. Large explicit square graphs can exhaust
resources even when the input is valid. Record failures as failed computations,
not as negative CFS results.

Portability also needs evidence: this audit's runtime validation is on Linux.
The mathematical code uses C++11 and Boost, while file-identity protection uses
the operating system's `stat` information. Build and test the complete program
on another platform before treating portability as established.

### Thickness requires additional mathematical contracts

SGB does not implement the thickness algorithm. Allowing complete join factors
fixes an important CFS convention, but the thickness base cases for complete
graphs and the empty graph still require a separate definition. Any recursive
use also needs a clear account of vertex identity, subgraph restrictions,
component supports, and when results may be reused. Those questions should be
settled before treating the executable's CFS boolean as a complete thickness
base-case API.

## Best next investment

Preserve the readable implementation and independent reference as comparison
points. Establish measurements by phase, then optimize square deduplication and
shared-diagonal processing. In parallel, define the result interface needed by
the thickness algorithm. The [improvement plan](improvement-plan.md) gives a
proposed order and checks for each change.
