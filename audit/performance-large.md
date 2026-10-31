# Performance at 1,000 and 3,000 vertices

The newer [20-graph density comparison](performance-ensemble.md) expands this
study to 20 graphs per density and size, six densities, and a two-minute timeout.
The measurements and 30-second limit below describe the earlier experiment.

This extends the [100-vertex comparison](performance.md) using the same two
application versions: repaired baseline `cbdb90f` and optimized source `1d780c2`.
The application algorithm has not changed during this measurement pass.

The primary corpus has eight fixed graphs: Erdos-Renyi samples at probabilities
0.005, 0.0075, and 0.01 for each vertex count, plus a pair-path CFS control at
each size. There is one seed per size, reused across probabilities so the random
edge sets are nested. These are comparisons of specific examples, not estimates
of average performance over all random graphs.

The [compressed graph records](../benchmarks/large-graphs.txt.gz) preserve the
exact inputs. [Metadata](../benchmarks/large-metadata.json) records generation
probabilities, actual edge densities, average degrees, seeds, and input hashes.
`python3 benchmarks/large_cases.py` regenerates the corpus and writes a plain
copy to `build/performance-large/graphs.txt`.

## Speed comparisons

Times below are **seconds per graph**, the median of five fresh-process runs
after one warmup per build. Each process reads one graph; unlike the small-case
100-vertex measurements, these inputs are not batched. Runs alternate before/
after order when both builds finish. The full [measurement record](performance-large-results.json)
retains every sample, min/max values, commands, hashes, and resource outcomes.

| Vertices | Input | Target probability | Before (s) | After (s) | Before / after |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,000 | ER | 0.5% | 0.005942 | 0.006068 | 0.98× |
| 1,000 | ER | 0.75% | 0.015105 | 0.015704 | 0.96× |
| 1,000 | ER | 1% | 0.043907 | 0.040417 | 1.09× |
| 1,000 | Pair path | — | 0.031417 | 0.005400 | 5.82× |
| 3,000 | ER | 0.5% | 0.833246 | 0.674308 | 1.24× |
| 3,000 | ER | 0.75% | 8.465644 | 4.787671 | 1.77× |
| 3,000 | ER | 1% | >30, one timed-out attempt | 17.800674 | No exact ratio |
| 3,000 | Pair path | — | 0.224060 | 0.010056 | 22.28× |

The two sparse 1,000-vertex random examples are slightly slower after the change
in this run, by approximately 0.13 ms and 0.60 ms. Their before/after timing
ranges overlap, so these small differences do not establish a robust change.
The improvement is stronger for the structured examples and the denser
3,000-vertex random cases.

The baseline's 3,000-vertex, 1% attempt exceeded its 30-second deadline and was
stopped. It was not retried five times. Dividing that cutoff by the optimized
median gives a **timeout-qualified lower bound greater than 1.68× for that observation**;
it is not a measured baseline-median-to-optimized-median speedup. The optimized
five samples ranged from 17.24 to 18.16 seconds. No overall mean speedup is
reported for this suite because one baseline measurement is censored.

The actual graph densities and square counts help identify the workloads:

| Vertices | Target ER probability | Actual edge density | Edges | Induced squares |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.5% | 0.51051% | 2,550 | 69 |
| 1,000 | 0.75% | 0.76196% | 3,806 | 377 |
| 1,000 | 1% | 1.01161% | 5,053 | 1,215 |
| 3,000 | 0.5% | 0.50381% | 22,664 | 6,370 |
| 3,000 | 0.75% | 0.75067% | 33,769 | 31,626 |
| 3,000 | 1% | 1.00229% | 45,088 | 99,858 |

All six random samples are non-CFS; their largest square-component supports
range from 4 to 51 vertices. The first two 1,000-vertex samples are disconnected.
The pair-path controls are CFS, with 2,491 and 7,491 squares respectively and
full literal support. This suite therefore does not characterize performance
near a random-graph CFS transition, or for every graph family at these sizes.

### Budgets and higher-density pilot

Each timing subprocess has a **30-second wall-time limit and 4 GiB virtual
address-space cap**. This is an address-space budget, not a measured peak-RAM
value. Timed-out process groups are killed and reaped; allocation failures and
other errors are recorded separately. Every optimized primary case completed
all five validated measurements within the budget.

An earlier [exploratory pilot](performance-large-pilot.json) also included 1.5%
probability. Its optimized 3,000-vertex case, with 67,716 edges, exceeded 30
seconds; no completed analysis or speedup is claimed for it. The repeated
comparison consequently covers 0.5%, 0.75%, and 1%. The pilot records its seed,
generation rule, input hash, and incomplete outcome separately. It was not a
correctness pass for the timed-out graph.

Timing used GCC 14.2.0, Boost 1.83, C++11, `-O2`, and strict warnings on Linux
x86_64. The container reported an AMD EPYC 7763, a four-CPU quota, and a 16 GiB
memory limit. Builds and sanitizer tests were paused during timing. Compiler
and source metadata identify the recorded builds; exact build and invocation
commands are included in the raw results. The application source hashes match
the previous optimized version.

## Correctness and interpretation

The previous four-vertex-subset reference is impractical at these sizes. The new
standalone checker intersects bitset neighborhoods for each nonedge and tests
nonadjacent pairs of common neighbors. Ordering the two diagonals counts each
induced square once. It computes components in a graph whose vertices are
diagonals and whose edges are the actual squares, then accumulates literal
original-vertex supports. This representation gives the same square components
without sharing the application's neighbor-walk enumeration or square-index
union-find implementation.

The new checker is itself checked against the original four-vertex reference on
all 21 existing 100-vertex performance graphs, a separate Python subset/traversal
oracle on 16 targeted small cases, and exact pair-path counts at 1,000 and 3,000
vertices. It also rejects 12 malformed-record examples. These checks run in
normal and AddressSanitizer/UndefinedBehaviorSanitizer builds.

`make check` and `make check-sanitize` both passed after adding this work:
20 application regression groups, 57 structural cases in both analysis modes,
15 original 100-vertex reference comparisons, the existing 12 checker/report
tests, six new strict-output/timeout/report tests, and the new reference checks
described above. Warning-as-error builds succeeded.

All eight large graphs also passed the optimized timing runner's reference
checks on every completed measurement and a separate ASan/UBSan application
run; see [large sanitizer validation](performance-large-validation.json).
The latter uses a 300-second per-process timeout and no address-space cap,
because ASan requires a large virtual shadow mapping. All eight finished with
no sanitizer diagnostics; the largest case took approximately 41.9 seconds in
that validation run. Sanitizer elapsed times are not performance measurements.
Leak detection was disabled for sandbox compatibility. Independent review found
no additional correctness error in the application at these sizes.

For each completed large application run, validation checks square/component
counts, CFS, connectivity, density, alpha, and both literal support ratios.
Floating comparisons use tolerances suitable for the corrected program's
12-significant-digit output. Completed before/after CSV rows must also agree
byte for byte. A timeout or memory-limit event supplies no mathematical result;
it is never interpreted as non-CFS or a passing correctness test.

The pair-path controls ensure that the larger suite includes known CFS graphs.
For `n` vertices, they have `5n/2 - 9` squares in one component supported on all
`n` vertices. Complete join factors retain the previously established convention:
excluded only from the CFS target, never added to actual square support.

## Reproduce

Build the baseline executable and current optimized executable using the same
compiler/options, as described in [the original performance report](performance.md#reproduce).
For a checkout containing this update, with Boost in the normal include path:

```sh
make CXX=g++ build/SGB build/sgb-reference-large
python3 benchmarks/performance_large.py --before build/performance/SGB-before --after build/SGB --reference build/sgb-reference-large --before-source build/performance/baseline-source --after-commit 1d780c2673e744152c49ec7337623e06f7a5ce59 --boost-version 1.83 --output build/performance-large-results.json
make check
make check-sanitize
make check-large
make check-large-sanitize
```

The `--after-commit` value above identifies the unchanged optimized application
source used for this comparison. Use the actual source version and installed
Boost version when benchmarking a later build. For a nonstandard Boost location,
give Make `CPPFLAGS=-I/path/to/boost/include`, use the same include option when
building the baseline, and record it through `--compiler-flags`. The recorded
run used `-I/tmp/sgb-boost/usr/include`.

The optional `check-large` targets run correctness validation separately from
performance measurements. They can take substantially longer than the standard
test suite. Their output goes under `build/`, leaving committed evidence intact.
The reference uses GCC/Clang's `__builtin_ctzll`; the bounded timing runner uses
POSIX process groups and `resource.RLIMIT_AS`. This workflow was tested on Linux.

## Limits

These timings concern ordinary `-tf` analysis and include startup, file parsing,
computation, cleanup, and CSV output. They do not measure full verbose square
graph construction or printing. The square enumeration stage still uses
adjacency-list searches and retains every square, so higher density can be much
more expensive even with the optimized deduplication and component discovery.

The machine is a shared Linux container, not a dedicated timing host. Exact
input/source/binary hashes, compiler flags, process ordering, raw timings, and
resource limits are recorded with the measurements. Repeated runs characterize
these examples on this machine; they do not establish a universal runtime bound.
