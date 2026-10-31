# Square Graph Builder (SGB)

SGB enumerates induced squares, connects squares that share a nonedge diagonal,
and computes the original-vertex support of each square-graph component.

## Important: square graphs and CFS use different conventions

**Square-graph construction uses the supplied graph literally.** Vertices in a
complete join factor do not gain artificial squares or square support.

**CFS classification allows complete join factors.** For `Gamma = Omega * K`,
where `K` is complete (possibly empty), test full square-component support on
`Omega`. Universal vertices cannot lie in an induced square. The implementation
requires an actual square component: a square joined with K2 reports CFS while
retaining support four in its six-vertex input graph.

Empty and complete graphs have no square component and report non-CFS with zero
support statistics. Their thickness base cases require separate mathematical
conventions; SGB does not implement a thickness algorithm.

## Build and verify

Use a C++11 compiler, Boost headers, Python 3, and Make on Linux or another
compatible POSIX system. Boost Graph is header-only for this program.

```sh
# Debian/Ubuntu prerequisites: g++, make, libboost-dev, python3
make
make check
make sanitize
```

For a nonstandard Boost location, add `CPPFLAGS=-I/path/to/boost/include` to Make.
The default build treats compiler warnings as errors. `make check` runs the
application regressions, benchmark-checker tests, 15 studied 100-vertex
benchmarks, and structural checks of every square, connection, component, and
support in both analysis modes. `make sanitize` repeats the application checks with AddressSanitizer
and UndefinedBehaviorSanitizer. Leak detection defaults to disabled for sandbox
compatibility; enable it through `ASAN_OPTIONS` on a supported host.

To build without Make:

```sh
mkdir -p build
c++ -std=c++11 -O2 -Wall -Wextra -Wpedantic main.cpp -o build/SGB
```

## Run

```sh
./build/SGB -t DJ_squareRAAG.txt
./build/SGB -tv dt_examples.txt
./build/SGB -tf randomexample.txt
./build/SGB --help
```

Files contain one graph per line:

```text
[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]
[0,1,2] []
[1] []
[] []
```

Vertex labels must be contiguous, ascending, and start at 0 or 1. Whitespace is
allowed between tokens. Inputs represent simple undirected graphs: duplicate
edges are collapsed and self-loops are ignored after validating their endpoints.
This accepts the old exporter's `(1,1)` marker without treating it as an edge.
Export and displayed vertex labels are normalized to 1-based labels.

Malformed records, unknown endpoints, blank records, empty files, and IO errors
produce a diagnostic and nonzero exit status. Input diagnostics include a file,
line, and parser column. Graphs are processed once in input order. If a later
record fails, output/export for earlier valid records can remain; a nonzero exit
status means the batch did not finish successfully.

Random modes:

```sh
# Erdos-Renyi: vertices, edge probability, trials
./build/SGB -f --seed 123 100 0.08 10

# Interpret alpha as p * sqrt(n)
./build/SGB -af --seed 123 100 0.8 10

# Watts-Strogatz: vertices, rewiring probability, trials, initial mean degree
./build/SGB -sf --seed 123 100 0.1 10 4
```

Probabilities must be in `[0,1]`, including after alpha scaling. Random vertex
and trial counts must be positive integers. Small-world degree must be below
`n` and even, except that `n-1` is allowed for a complete graph. Degree zero gives
an edgeless graph. Complete graphs remain complete regardless of rewiring
probability. Rewiring preserves the edge count, avoids loops/duplicate edges,
and retains an edge if its source has no available new neighbor.

The seed is printed to stderr. Without `--seed`, a seed is obtained from the
system's random device. A seed reproduces runs with the same implementation and
toolchain; save the actual graphs for reproduction across library versions.

| Option | Behavior |
| --- | --- |
| `-t` | Read graphs from a file; cannot combine with `-a`, `-s`, or `--seed`. |
| `-v` | Show input/square graphs and component supports. |
| `-d` | Also show each square's diagonals. |
| `-f` | Print one fixed-schema CSV row per input graph or trial. |
| `-e` | Append input graphs to `graphsanalyzed.txt`, independently of verbosity. |
| `-a` | Interpret the ER parameter as alpha; cannot combine with `-s`. |
| `-s` | Generate small-world graphs. |
| `--seed N` | Use an unsigned 64-bit random seed. |
| `-h`, `--help` | Show usage. |

Short flags can be combined or separate. Use `--` before a filename beginning
with `-`. Exporting into the same file as the input, including hard/symlink
aliases, is rejected. Exports use canonical graph syntax without artificial
self-loops, trailing commas, or terminal control characters.

## Results and statistics

`-f` always prints this header, including when the first graph is disconnected:

```text
n,p,alpha,CFS,num_squares,num_comp,ratio_comp_avg,ratio_largest_comp,status
```

`status` is `connected`, `disconnected`, or `empty`. Disconnected inputs receive
complete square metrics. Verbose/debug information goes to stderr in CSV mode.

For file input, `p` is the actual simple-edge density `2m/(n(n-1))`, or zero for
fewer than two vertices, and `alpha = p * sqrt(n)`. In ER mode, `p` is the
configured edge probability; in small-world mode it is the rewiring probability.
For either random mode, `alpha` is the configured `p * sqrt(n)`, not an empirical
statistic of the sampled graph.

For each graph, `ratio_comp_avg` is the mean component support size divided by
`n`; `ratio_largest_comp` is the largest literal support divided by `n`. Both are
zero when there are no squares. Summary `AvgSupport` and `LargestSupport` are
arithmetic means of these per-graph ratios, with every input graph weighted
equally. Varying summary values for `n`, `p`, or `alpha` are labeled `mixed`.
A complete join factor can make CFS true while literal support ratios stay below
one; this is intentional.

The CSV now has a ninth status column. Consumers of the old eight-column output
must update their schema; old five-field disconnected rows are no longer emitted.

## Audit, benchmarks, and provenance

See [audit/README.md](audit/README.md) for the completed repair audit,
strengths/weaknesses assessment, improvement plan, and validation evidence.
See [benchmarks/README.md](benchmarks/README.md) for the studied 100-vertex corpus.
See [the performance report](audit/performance.md) for repeated before/after
measurements and reproduction commands.
The [20-graph density comparison](audit/performance-ensemble.md) measures 20
different graphs at each of six densities for 1,000 and 3,000 vertices, using
identical before/after inputs and a two-minute per-run timeout. The earlier
[single-graph comparison](audit/performance-large.md) remains available.

Square deduplication uses canonical diagonal keys. Ordinary analysis computes
square components through shared diagonals without storing square-graph edges.
`-v` and `-d` still construct and display the full literal square graph, connecting
every pair of squares sharing a diagonal. Both modes compute the same component
supports and CFS result. Complete join factors affect classification only.

Graphs with many induced squares can still be expensive, especially when the
full square graph is requested. There is no enforced time/memory budget.

The unchanged program was posted first in
[commit 9b02b79](https://github.com/jasonbehrstockdev/SGB/tree/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3).
Subsequent repairs are separate history. All original sample files, usage notes,
and the historical executable remain preserved. macOS archive metadata was
excluded. `SGB_2024.executable.txt` is an Intel macOS Mach-O binary despite its
suffix; it was not executed during this Linux source audit. Build from source
for the repaired program. `SquareGraphBuilder.h` is an unused empty historical
header. No license was chosen on the author's behalf.
