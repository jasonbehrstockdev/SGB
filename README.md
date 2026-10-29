# Square Graph Builder (SGB)

SGB constructs the graph of induced squares of an input graph and computes its
connected components and their supports. Two squares are adjacent when they
share a diagonal, which is a non-edge of the input graph.

## Important: square graphs and CFS use different conventions

**Square-graph construction uses the supplied graph literally.** Enumerate its
induced squares and their actual supports. Do not treat vertices in a complete
join factor as square-covered or add artificial squares for them.

**CFS classification allows complete join factors.** If the graph is
`Gamma = Omega * K`, where `K` is a complete graph (possibly empty), the CFS
support test applies to `Omega`. Vertices in `K` are adjacent to every other
vertex and cannot lie in an induced square.

The CFS check excludes universal vertices from its support target and requires
an actual square component. A square joined with a universal vertex therefore
reports CFS while retaining its literal support of four vertices. This distinction
is important when using SGB at the base level of a thickness algorithm. Pure
complete graphs have no square component and continue to report non-CFS; their
thickness base case, and the empty-graph case, need separate conventions.

## Import provenance

The unchanged program from `SGB_2024build.zip` was first saved in
[the original import](https://github.com/jasonbehrstockdev/SGB/tree/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3).
macOS archive metadata (`.DS_Store` and `__MACOSX`) was excluded. This subsequent
change corrects CFS classification; the square-building algorithm, example
inputs, and historical executable are preserved.

## Build

Use a C++11 or newer compiler and the Boost headers (Boost Graph and Boost
Random). These uses of Boost are header-only; no Boost library link flags are
needed.

```sh
# Debian/Ubuntu prerequisites: g++ and libboost-dev
# macOS prerequisites: Xcode command-line tools and Boost
mkdir -p build
c++ -std=c++11 -O2 -Wall -Wextra -pedantic main.cpp -o build/SGB
```

If Boost is installed outside the compiler's search path, add
`-I/path/to/boost/include` to the command.

## Run

Run from the repository directory:

```sh
./build/SGB -t DJ_squareRAAG.txt
./build/SGB -tv dt_examples.txt
./build/SGB -tf randomexample.txt
```

Input files contain one graph per line, for example:

```text
[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]
```

Use contiguous vertex labels starting at 0 or 1. The legacy parser has limitations
on empty edge lists, single-vertex graphs, and malformed inputs; it is not a
validated input format implementation.

Random graph modes:

```sh
# Erdos-Renyi: vertex count, edge probability, trial count
./build/SGB 20 0.3 10

# Scale edge probability as alpha / sqrt(vertex count)
./build/SGB -a 20 1.0 10

# Small-world: vertex count, rewiring probability, trial count, mean degree
./build/SGB -s 20 0.1 10 4
```

All flags must be combined in the first argument (for example, `-tdv`).

| Flag | Behavior |
| --- | --- |
| `t` | Read graphs from the next argument, a file path. |
| `v` | Print graphs and component supports. |
| `d` | Print algorithm debugging details. |
| `f` | Print individual trial results. |
| `a` | Interpret the probability argument as alpha. |
| `s` | Generate small-world graphs; requires mean degree as a fourth value. |
| `e` | Append input graphs to `graphsanalyzed.txt`; file-input mode currently also requires `v`. |

## Original files

- `main.cpp`, `flags.h`: complete program source.
- `SquareGraphBuilder.h`: empty header included in the original archive.
- `DJ_squareRAAG.txt`, `dt_examples.txt`, `randomexample.txt`: example inputs.
- `SGB_readme.txt`: original usage notes.
- `SGB_2024.executable.txt`: original Intel macOS Mach-O executable despite its
  `.txt` suffix. It is preserved as a historical artifact and was not executed
  during the Linux source review. Rebuild from source for your platform.

See [CODE_REVIEW.md](CODE_REVIEW.md) for the original review findings,
reproduction steps, and limitations. Finding 11 (CFS with complete join factors)
has been corrected; the other findings remain open.

See [benchmarks/README.md](benchmarks/README.md) for reproducible 100-vertex
benchmarks, independent reference results, and measured runs.
