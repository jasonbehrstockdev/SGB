# Studied 100-vertex benchmarks

This set follows the author's preference for representative 100-vertex examples
when validating SGB and planning a thickness algorithm. It contains 15 fixed
graphs: six structured cases and nine deterministic Erdos-Renyi samples. The
thickness algorithm itself is not present in this repository or tested here.

**CFS allows complete join factors; square-graph construction remains literal.**
The `pair_path_join_K2_100` case demonstrates the distinction. Its two universal
vertices do not belong to any square: its square support is 98, and its intended
CFS classification is true. The original import reports false; the focused CFS
fix reports true while preserving that literal support of 98.

## Cases and reference results

Every graph has vertices 1 through 100. These counts come from the independent
reference, including cases where the original executable omits square metrics.

| Case | Edges | Squares | Square components | Largest support | Intended CFS |
| --- | ---: | ---: | ---: | ---: | --- |
| Pair path | 196 | 241 | 1 | 100 | Yes |
| Pair ring | 200 | 250 | 1 | 100 | Yes |
| Two pair paths joined by a bridge | 193 | 232 | 2 | 50 | No |
| Pair path with two leaves | 194 | 236 | 1 | 98 | No |
| Pair path joined with K2 | 389 | 236 | 1 | 98 | **Yes; original reports No** |
| ER p=0.04, seed 202401 | 195 | 20 | 14 | 6 | No |
| ER p=0.04, seed 202402 | 177 | 17 | 10 | 7 | No |
| ER p=0.04, seed 202403 | 202 | 34 | 27 | 6 | No |
| ER p=0.08, seed 202401 | 399 | 378 | 161 | 30 | No |
| ER p=0.08, seed 202402 | 377 | 316 | 131 | 24 | No |
| ER p=0.08, seed 202403 | 394 | 381 | 172 | 16 | No |
| ER p=0.12, seed 202401 | 594 | 1,794 | 158 | 100 | Yes |
| ER p=0.12, seed 202402 | 583 | 1,730 | 137 | 100 | Yes |
| ER p=0.12, seed 202403 | 563 | 1,503 | 154 | 100 | Yes |
| Cycle C100 | 100 | 0 | 0 | 0 | No |

A pair path replaces each vertex of a path with two nonadjacent vertices and
joins consecutive pairs by all four edges. For `m >= 2` pairs it has
`(m - 1) + 4(m - 2) = 5m - 9` squares. A pair ring with at least five pairs has
`5m` squares. Bridges and pendant edges add no cycles. Universal vertices create
chords in any four-cycle containing them, so joining with K2 adds no induced
squares. These constructions give independently derived expected results.

The random samples are unconditioned: all three p=0.04 graphs have three original
connected components, and SGB skips their square calculations. Only vertex
counts, connectivity, and classification can be checked against their output.
The p=0.08 samples have fragmented square components; the p=0.12 samples have a
component with full support. These samples illustrate cases, not a statistical
threshold estimate. Reusing seeds across densities produces nested edge sets,
not nine independent samples.

All square counts, component counts, and largest supports reported by the
original optimized executable on the 12 connected cases matched the reference.
The K2 case exposed the original CFS false negative; the corrected executable
passes all 15 intended-classification cases with unchanged square/support
measurements. C100 still reaches the known
empty-vector undefined behavior and prints a NaN support ratio: its normal-build
output matching the reference does not make that execution path safe.

## Reproduce

From the repository root, with a C++11 compiler, Boost headers, and Python 3:

```sh
mkdir -p build
c++ -std=c++11 -O2 main.cpp -o build/SGB
c++ -std=c++11 -O2 -Wall -Wextra -pedantic benchmarks/reference.cpp -o build/sgb-reference
python3 benchmarks/generate.py
python3 benchmarks/run.py --sgb build/SGB --reference build/sgb-reference
```

Add `-I/path/to/boost/include` when building SGB if necessary. The reference
depends on neither Boost nor SGB source. It enumerates every four-vertex subset
using an adjacency matrix, recognizes induced squares by degree two at each
vertex, and joins square components through shared diagonals using disjoint
sets. Its parser is for the generated benchmark format, not general user input.

By default, the runner requires the intended CFS convention and records both
classifications. The mode can also be selected explicitly:

```sh
python3 benchmarks/run.py --sgb build/SGB --reference build/sgb-reference \
  --cfs-mode intended --output build/results-intended.json
```

This passes with the corrected executable. For an executable built from the
original import, `--cfs-mode legacy` reproduces the historical behavior; intended
mode fails only on the K2 case. Its literal support remains 98 in both versions.

## Files and measurement limits

- `generate.py`: deterministic standard-library generator.
- `graphs.txt`: actual benchmark inputs, one graph per line.
- `metadata.json`: parameters, construction expectations, and input hashes.
- `reference.cpp`: independent reference computation.
- `run.py`: bounded subprocess runner and reference comparison.
- `results-original.json`: preserved measurements of the unchanged original import.
- `results.json`: updated measurements, stdout, timings, environment,
  source/input hashes, and both CFS interpretations.

Recorded runs used GCC 14.2.0, Boost 1.83, C++11, and `-O2` on Linux x86_64. Each
graph was run once in a fresh process; timings include startup and file IO.
These are an initial baseline, not stable performance guarantees. Repeated runs
and recorded hardware details are needed before drawing speed conclusions.
The focused classification fix leaves the other reviewed defects open.
