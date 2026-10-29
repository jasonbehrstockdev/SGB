# Post-repair code audit

All eleven numbered findings from the [initial review](original-review.md) have
been addressed. A complete rereview of the repaired application and its checking
tools found **no additional confirmed correctness errors remaining**. This is a
bounded engineering assessment, not a proof that no defect exists on any input.

The unchanged 2024 program remains available in
[the initial import](https://github.com/jasonbehrstockdev/SGB/tree/9b02b7938c2a5ed766b3986af51a53c9a7e50bc3).
The repairs preserve the mathematical distinction requested by the author:
square graphs and their supports are literal; CFS classification allows a
complete join factor. No thickness algorithm or thickness base-case convention
has been inferred or implemented.

## Resolution of the original findings

| Finding | Repair | Verification |
| --- | --- | --- |
| 1. Unchecked endpoints caused memory errors | Parse complete records and verify every endpoint before constructing a Boost graph. Reject out-of-range labels with file/line/column diagnostics. | Negative, zero-in-1-based, oversized, and undeclared endpoints fail cleanly under sanitizers. |
| 2. Empty square vectors and zero denominators | Component discovery bypasses Boost for empty storage; all no-square and empty-input-graph ratios are defined as zero. | Triangle, path, singleton, empty graph, and 100-cycle cases pass without undefined-behavior diagnostics or NaN. |
| 3. Missing arguments and invalid numbers | Validated options object, checked integer/real conversions, exact positional counts, compatible modes, effective probability checks. | Missing arguments, overflow, trailing garbage, nonfinite values, invalid counts/probabilities, and incompatible flags are rejected. |
| 4. Singleton and edgeless graphs failed parsing | Explicit grammar for vertex and edge lists, including `[] []`, `[1] []`, and zero-based input. | Parsing, analysis, export, and reimport work for these cases. |
| 5. Small-world boundary hangs/wrong graphs | Replace the iterator with bounded simple-graph Watts-Strogatz generation; handle zero degree and complete graphs directly. | Boundary regressions, deterministic 100-vertex cases, and saturated-source probes terminate with the expected edge counts and no loops/duplicates. |
| 6. Mixed-size summary ratios were wrong | Compute ratios per graph, then average with equal graph weight. Use floating arithmetic without overflowing an integer denominator. | Reordering C4 and K2,3 leaves both means at 1; mixed square-free/disconnected batches have their expected finite means. |
| 7. File failures appeared successful | Check opening, reading, empty files, and malformed records; return nonzero with an error. Read input once. | Missing files, directories, empty files, and malformed later records fail with useful diagnostics. |
| 8. File density and alpha were placeholders | Use actual normalized simple-edge density and `alpha = p * sqrt(n)` for file input; label varying summary values `mixed`. | C4 gives density 2/3 and alpha 4/3; all 15 reference cases compare these fields. |
| 9. Full output had inconsistent rows/header | Emit a fixed nine-column CSV header once and a status column for every record. Compute square metrics for disconnected inputs too. | First-disconnected and mixed batches parse consistently; all fields of the three disconnected 100-vertex samples are now checked. |
| 10. Export depended on verbosity | Export independently of display flags; check open/write/close errors and reject input/output aliases. | `-te` works, round trips preserve graphs, `/dev/full` failures are detected, hardlinked input/output is rejected. |
| 11. CFS omitted complete join factors | Remove universal vertices only from the classification target, require an actual square component, and retain literal supports. | C4 joined with K1/K2 and the 100-vertex K2 benchmark classify correctly; pendant/non-CFS controls remain negative. |

The original square-enumeration logic remains recognizable: choose two
nonadjacent neighbors of a vertex, find the opposite vertex with the required
perimeter edges and absent diagonal, and deduplicate the resulting squares.
The repaired code separates this calculation from parsing and presentation.
Component supports are accumulated once per square instead of rescanning all
squares for each component.

## Additional issues found and corrected in this pass

These were corrected rather than left as an outstanding-error list:

1. **The benchmark checker could miss wrong output.** It previously did not
   compare average support, file density, or alpha, and omitted square metrics
   for disconnected inputs. Strict corrected-output validation now checks these
   fields, connectivity, both support ratios, all counts, and classification.
   Legacy output requires explicit opt-in and is marked incompletely validated.
2. **Recoverable sanitizer diagnostics could be accepted.** During the second
   review, a process returning zero with sanitizer errors on stderr could pass
   the checker. Sanitizer diagnostics now fail validation regardless of exit
   status, with a dedicated checker regression.
3. **Display/export serialization was not faithful.** The artificial `(1,1)`
   export edge, trailing-comma backspaces, and missing empty-edge representation
   were removed. Historical self-loops remain accepted as ignored markers;
   duplicate input edges are normalized. CSV mode sends verbose/debug text to
   stderr so diagnostics do not corrupt data rows.
4. **Random experiments were hard to reproduce and probability boundaries were
   fragile.** An explicit 64-bit seed, a standard random engine, and Bernoulli
   sampling replace second-resolution `srand`/`rand` use. The chosen seed is
   reported; probability zero/one behavior and repeatability are tested.
5. **Counter types and obsolete code obscured reliability.** Descriptor-sized
   counters and checked numeric input replace signed/unsigned loop mismatches.
   Obsolete commented implementations and the unused unsafe component helper
   were removed. The build now has zero warnings under strict warning flags.

## Full rereview coverage

Separate implementation and review passes inspected every application function
and the checking infrastructure after the repairs, including independent edge
probes rather than only rerunning the implementation's own assertions.

| Files | Areas reviewed |
| --- | --- |
| [main.cpp](../main.cpp) | Square enumeration/deduplication, shared-diagonal adjacency, components/supports, complete join factors, ER/WS generation, finite statistics, output, export identity checks, and error propagation. |
| [flags.h](../flags.h), [input.h](../input.h) | Argument arity, modes, integer bounds, nonfinite values, input grammar, label ranges, empty records/graphs, normalization, and diagnostics. |
| [benchmarks/generate.py](../benchmarks/generate.py), [reference.cpp](../benchmarks/reference.cpp) | Deterministic fixtures, structured expectations, independent four-vertex enumeration, diagonal-incidence connectivity, and literal versus CFS support. |
| [benchmarks/run.py](../benchmarks/run.py), [test_runner.py](../benchmarks/test_runner.py) | Strict CSV, reference comparisons, sanitizer/error detection, timeouts, source hashes, and explicit historical-output limitations. |
| [tests/regression.py](../tests/regression.py), [Makefile](../Makefile) | Test isolation, failure detection, case coverage, normal/sanitizer build recipes, and reproducible test entry points. |

All original sample inputs and the 100-vertex corpus were exercised. The empty
historical `SquareGraphBuilder.h` has no executable content. The preserved
Mach-O binary was identified but not executed or reverse engineered; its
equivalence to any source version is not claimed.

## Validation results

Environment: Linux x86_64, GCC 14.2.0, Boost 1.83, C++11, Python 3.12.14.
The optimized build used `-O2`; sanitizer builds used `-O1 -g` with
AddressSanitizer and UndefinedBehaviorSanitizer. Both compile with
`-Wall -Wextra -Wpedantic -Werror`.

| Check | Result |
| --- | --- |
| Application regression groups | 20 passed in each of optimized and sanitizer builds; groups include multiple parameterized cases. |
| Benchmark-checker regressions | 11 passed. |
| Selected 100-vertex graphs | 15/15 passed in each build, with all reported metrics checked, including disconnected and square-free cases. |
| Original supplied examples | All 13 records passed in each build; CFS counts remain 1/1, 1/8, and 0/4 across the three files. |
| Independent small-world probes | 186 generator-invariant cases: all valid degrees for n=1,2,3,10,100 at probabilities 0, 0.5, and 1, with seed 20260401, preserved the expected edge count and produced simple graphs. These do not test the probability distribution. |
| Saturated rewiring probe | A 100-vertex, degree-98, probability-1 case terminates with 4,900 unique loop-free edges. |
| Input/export identity | A hardlink alias is rejected without altering the input. |
| Sanitizer diagnostics | None in the successful application runs; checker tests deliberately reject simulated sanitizer reports. |

See [optimized results](../benchmarks/results.json),
[sanitizer results](validation-sanitize.json), and
[example results](validation-examples.json). The benchmark results contain
source/input hashes and executable hashes. The [original baseline](../benchmarks/results-original.json)
is retained unchanged. LeakSanitizer was disabled for sandbox compatibility;
this audit does not establish absence of leaks on every path or platform.

Reproduce from the repository root:

```sh
make check
make sanitize
```

If Boost is outside the normal compiler search path, append
`CPPFLAGS=-I/path/to/boost/include`. These commands write fresh benchmark reports
under `build/` rather than replacing the committed audit evidence.

## Outstanding errors and remaining limits

**Outstanding confirmed correctness errors after this rereview: none.** The
following limits remain and should guide future work:

- **Dense inputs can be expensive.** There is no enforced time/memory budget.
  K50,50 already contains 1,500,625 squares; explicit all-pairs construction is
  impractical at that scale. The selected 100-vertex corpus does not promise
  cheap processing for every graph with 100 vertices.
- **Streaming batches are not transactional.** A later error returns nonzero,
  but earlier valid CSV rows and appended exports remain. Callers must check
  exit status and decide whether to retain partial batch results.
- **Portability is tested only on Linux.** File identity checking uses POSIX
  `stat`; other platforms and compiler/library combinations need validation.
  A seed alone is not a guarantee of identical distribution output across
  standard-library implementations.
- **Thickness remains separate work.** Complete-only and empty-graph thickness
  base cases, recursive vertex identity, and the reusable result interface are
  not defined by this CFS implementation.
- **The reference is for the pinned benchmark corpus.** It is an independent
  checker, not a production parser for arbitrary external graphs or a proof for
  all graph families.

The [assessment](strengths-and-weaknesses.md) and
[improvement plan](improvement-plan.md) develop these tradeoffs and proposed next
steps without treating unmeasured speedups as established results.
