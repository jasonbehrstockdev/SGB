# SGB 2024 source review

Reviewed October 28, 2026 (America/New_York).

This report describes [the unchanged original import](https://github.com/jasonbehrstockdev/SGB/tree/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3).
All source line references link to that version. A subsequent focused change
corrects **finding 11**, allowing complete join factors for CFS classification
while preserving the literal square graph and support measurements. All 15
100-vertex benchmarks now pass the intended CFS check; the other findings below
remain open. Original benchmark results are retained in
`benchmarks/results-original.json`, with updated results in `benchmarks/results.json`.

The most important defects are unchecked input indices, empty-graph handling,
CFS classification with complete join factors, and incorrect statistics.
The original import preserves the source as received; the findings below record
that version before fixes. Small-graph checks verified basic mechanics, but
provide little coverage of the structures relevant to this algorithm.

## Scope and validation

Reviewed all 1,198 lines of `main.cpp`, all 42 lines of `flags.h`, the empty
`SquareGraphBuilder.h`, the original README, and every supplied example record.
The added benchmark generator, runner, and independent reference source were
also reviewed; the original source is preserved byte-for-byte in the linked import.
The historical macOS executable was identified and preserved, but not run or
reverse engineered; equivalence between it and the source is not established.

| Area | Coverage |
| --- | --- |
| CLI and main control flow | All flag branches, file mode, ER mode, small-world mode, disconnected/empty cases, aggregate output |
| `square`, `FindSquares`, `checkSquareList` | Enumeration and deduplication checked against independent four-vertex cycle enumeration |
| `checkAdjacentSquares`, `buildSquareGraph` | Every derived edge checked against shared non-edge membership |
| `checkSupport`, `findComponents` | Support unions checked; unused component helper reviewed for empty input |
| `ErdosRenyi` | Edge construction, random-number use, parameter boundaries, printing |
| `convertline`, `printGraph` | Parsing, index validity, display, export and round trips |
| Headers, documentation, inputs | Complete inspection; all 13 supplied graph records executed |

Build environment: Linux, GCC 14.2.0, Boost 1.83, C++11. Boost is header-only
for the APIs used here. The normal build succeeded with 20 warnings: 18 signedness
comparisons, one bitwise-OR/precedence warning at `main.cpp:829`, and one unused
parameter at `main.cpp:968`.

```sh
mkdir -p build
c++ -std=c++11 -O2 -Wall -Wextra -Wpedantic main.cpp -o build/SGB
c++ -std=c++11 -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer main.cpp -o build/SGB-sanitize
c++ -std=c++11 -O0 -g -D_GLIBCXX_ASSERTIONS main.cpp -o build/SGB-assert
```

Add the Boost include path if needed. During this review it was
`-I/tmp/sgb-boost/usr/include`. Sanitizer checks used
`ASAN_OPTIONS=detect_leaks=0` where necessary; this review does not establish
absence of memory leaks.

| Supplied input | Graphs | Classified CFS | Result |
| --- | ---: | ---: | --- |
| `DJ_squareRAAG.txt` | 1 | 1 | 9 induced squares |
| `dt_examples.txt` | 8 | 1 | Completed |
| `randomexample.txt` | 4 | 0 | Completed |

All supplied records completed in normal and sanitizer builds without sanitizer
diagnostics. This does not validate their aggregate statistics; see finding 6.

An independent temporary C++ harness checked all **33,868 simple labeled graphs
on 0 through 6 vertices**. Exact induced-square sets, square-graph edges, and
component support sizes matched. A second run checked all **1,100 graphs on 0
through 5 vertices**, with duplicated edges and self-loops added, with the same
result. These tests exercised the core functions directly, not the CLI/parser.
They are bounded checks of basic mechanics, not meaningful coverage of the
larger structures of interest. Following the author's guidance, ongoing
validation should emphasize selected 100-vertex graphs for both SGB and the
related thickness algorithm. See [the benchmark set](benchmarks/README.md) for
reproducible larger examples and their studied results.

The 15-case 100-vertex benchmark set includes structured positive/negative cases,
the complete-join-factor distinction, and seeded random graphs. Reported square
counts, component counts, and largest supports matched the independent reference
for all 12 connected cases. The three disconnected samples omit these metrics in
the original executable. The K2 join case confirms finding 11; the square-free
C100 case still has the undefined behavior in finding 2 despite matching counts
in the optimized build.

## Confirmed findings

P1 means fix first because memory safety is affected. P2 means a reproducible
correctness, reliability, or output problem. Locations refer to the unchanged
imported source.

### 1. P1: Validate edge endpoints before calling Boost

Location: [main.cpp:1183](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L1183).

The parser subtracts the label offset and passes the result directly to
`add_edge`. With the file contents below, zero becomes a negative index, then an
unsigned vertex descriptor. AddressSanitizer reports a heap-buffer-overflow.

```text
[1,2] [(0,1)]
```

Run `./build/SGB-sanitize -t input.txt` to reproduce. Positive endpoints outside
the declared range also silently change the graph: `[1,2] [(1,4)]` becomes a
four-vertex graph. Parse and validate the vertex list and every endpoint before
allocation/insertion. Report invalid records with their line number and a
nonzero exit status.

### 2. P2: Handle an empty square graph without indexing an empty vector

Location: [main.cpp:316-318](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L316); related uses at lines 277 and 917.

A valid connected graph with no induced square, such as a triangle, produces an
empty component vector. `&temp_component[0]` has undefined behavior even if
Boost does not subsequently dereference the pointer. UBSan reports reference
binding to a null pointer; the assertions build aborts.

```text
[1,2,3] [(1,2),(2,3),(1,3)]
```

Run `./build/SGB-assert -tf input.txt`. The same case divides by zero in support
ratios at lines 353 and 389 and prints NaN in an ordinary build. Handle zero
vertices and zero squares explicitly, use valid storage access, and define the
zero-component statistics. The unused `findComponents` helper needs the same
storage fix.

### 3. P2: Validate argument counts and numeric ranges

Location: [main.cpp:144-146](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L144); small-world argument at line 261.

`./build/SGB` and `./build/SGB -s 10 .5 1` access missing arguments and crash.
`atoi`/`atof` also accept invalid values without reporting an error: `foo` becomes
zero, negative values can be assigned to unsigned counts, and invalid
probabilities are accepted. `./build/SGB foo .5 1` accepts a zero-vertex graph and
can report CFS with NaN ratios; zero trials also finish successfully.

Validate argument counts for each mode, parse complete numeric strings with
error checking, require meaningful vertex/trial counts, and check probability
ranges after alpha scaling. Reject incompatible modes such as file input plus
small-world generation, or define their behavior explicitly. Print usage and
return nonzero for invalid invocations.

### 4. P2: Accept valid singleton and edgeless input graphs

Location: [main.cpp:1166-1170](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L1166).

`[1] []` throws `std::invalid_argument` because the vertex parser passes `[1` to
`stoi`. `[1,2] []` throws `std::out_of_range` because the parser calls `substr`
with the missing `(` position. Both terminate with SIGABRT under `-t`.

Parse the two lists explicitly, allow empty edge lists, and handle singleton
vertices. Blank/malformed records and conversion exceptions should produce
controlled diagnostics rather than terminating the process unexpectedly.

### 5. P2: Check small-world generator boundary cases

Location: [main.cpp:261-266](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L261).

`./build/SGB -sf 5 1 1 4` did not terminate within a two-second test timeout.
With mean degree `n-1`, Boost's rewiring rejection loop has no eligible target.
`./build/SGB -sd 5 0 1 0` generates a complete graph with loops/duplicates even
though the requested mean degree is zero.

Validate the generator's supported vertex/degree/probability domain before
construction, and implement or reject boundary cases explicitly. Include zero
degree and complete-neighborhood cases in future regression checks.

### 6. P2: Normalize support statistics using each graph's size

Location: [main.cpp:389-391](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L389).

The summary accumulates raw support sizes but divides by the final input graph's
vertex count. Results therefore depend on input order and can exceed one.
Use this two-line file:

```text
[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]
[1,2,3,4,5] [(1,3),(1,4),(1,5),(2,3),(2,4),(2,5)]
```

`./build/SGB -t input.txt` reports both support ratios as `0.900000`. Reversing
the lines gives `1.125000`. Each graph has one square component supporting all
its vertices, so either ordering should give `1.0`. This also affects the
supplied mixed-size `dt_examples.txt`.

Accumulate per-graph normalized ratios, or explicitly define a weighted statistic
and accumulate its matching denominator. Define how disconnected graphs and
graphs with no squares contribute.

### 7. P2: Report input-file failures as errors

Location: [main.cpp:182-187](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L182).

`./build/SGB -t /tmp/nonexistent-sgb-file` exits 0, says it is running zero
graphs, and prints NaN summary values. The stream's open status is never checked
during the counting pass. An empty file similarly reaches zero denominators.

Check the input stream before reading, handle empty input deliberately, and
return nonzero on IO errors. Reading each graph once would also remove the
current repeated opening and full-file scanning at lines 243-250.

### 8. P2: Remove placeholder density and alpha values from file-mode output

Location: [main.cpp:253-254](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L253); output at lines 369 and 401.

File mode updates `n` but leaves `p` and `alpha` at their initial values. A C4
under `-tf` prints `4, 1, 1, ...`, despite density `4/6` and corresponding
`alpha = p * sqrt(n) = 4/3`.

Compute clearly defined statistics for each input graph, or mark the random
generator parameters as unavailable in file mode. A single global `n`, `p`, or
`alpha` is also misleading for mixed-size files.

### 9. P2: Emit a consistent full-output schema and header

Location: [main.cpp:284-289](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L284), [main.cpp:360-369](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L360).

Disconnected graphs produce five fields while connected graphs produce eight.
If the first record is disconnected, the header is never printed because the
loop continues before reaching the `curr_test == 0` header branch.

A file containing `[1,2,3] [(1,2)]` followed by the C4 above produces:

```text
3, 1, 1, 0, Disconnected.
4, 1, 1, 1, 1, 1, 1, 1
```

Print the header before processing records, keep a fixed column count, and add
an explicit status field or consistent missing-value representation.

### 10. P2: Honor export independently of verbose output

Location: [main.cpp:1188-1190](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L1188).

`./build/SGB -te input.txt` succeeds without creating `graphsanalyzed.txt`, while
`-tev` exports it. The parser calls `printGraph` only when verbose is enabled,
preventing the export and graph-display debug branches from running otherwise.

Invoke the requested output behavior independently of verbosity. Check export
file open/write failures as well; they are currently ignored at lines 888-898.

### 11. P2: Allow complete join factors in CFS classification

Location: [main.cpp:333](https://github.com/jasonbehrstockdev/SGB/blob/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3/main.cpp#L333).

The author confirmed during review that **CFS allows complete join factors**,
while **square-graph construction must remain literal**. The current comparison
requires support across every input vertex, so a C4 joined with a universal
vertex is incorrectly reported as not CFS:

```text
[1,2,3,4,5] [(1,2),(2,3),(3,4),(1,4),(1,5),(2,5),(3,5),(4,5)]
```

The square graph correctly has one square supported on the four cycle vertices.
For classification, write `Gamma = Omega * K` with `K` complete and compare the
component support to `Omega`; universal clique vertices cannot participate in an
induced square. Do not change the square list or its actual supports to simulate
coverage of those vertices.

This must be corrected before using the CFS check at the base level of a
thickness algorithm. Keep the square-graph and classification operations
distinct. Establish pure complete-graph and empty-graph thickness base cases
separately. The [README](README.md#important-square-graphs-and-cfs-use-different-conventions)
and [AGENTS.md](AGENTS.md) record the convention for future work.

## Further maintenance observations

- `printGraph` appends an artificial `(1,1)` self-loop when exporting (line 897).
  Every supplied `randomexample.txt` record contains it. The small-graph tests
  found no effect on square detection, but exports do not preserve simple-graph
  structure exactly. Fix comma handling and empty-edge parsing together before
  removing this historical workaround.
- Display output uses a backspace character to hide its final comma (lines 853
  and 878). Redirected output retains that control character. Emit separators
  between entries instead.
- Square deduplication scans the accumulated square list, square-graph building
  compares every pair of squares, and support checking rescans all squares for
  each component. Large graphs can become expensive; no large-input performance
  limit was established. Canonical square/diagonal keys and component-wise
  accumulation are candidates for measured optimization.
- `srand(time(NULL))` provides no user-controlled seed and can repeat a random
  sequence across runs started in the same second. Add an explicit seed option
  before relying on the program for reproducible experiments.
- The original project has no automated tests, CI, or declared license. This
  import adds documentation, ignore rules, and a reproducible benchmark set,
  without choosing a license or changing application behavior. Future fixes
  should use the 100-vertex benchmarks and targeted regression cases for the
  findings above.

## Review limits

The review includes static inspection, builds, sanitizer runs, examples, and
bounded exhaustive algorithm checks. It is not a formal proof or a guarantee
that every defect has been found. It did not validate scientific conclusions
derived from past runs, test the historical binary, or establish scalability
beyond the selected 100-vertex examples.
Basic credential-pattern scanning found no matches in the imported files.
