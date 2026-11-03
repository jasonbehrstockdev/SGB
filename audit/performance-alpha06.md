# SGB at the thickness benchmark density

This comparison fixes **alpha = 0.6**, so `p = 0.6 / sqrt(n)`, at
1,000 and 3,000 vertices. Each size uses 20 distinct deterministic graphs,
with identical inputs for the before and after versions. The baseline is
the previously optimized `0ebc8fe`; the adaptive implementation is `3797211`.
Application sources and executables are unchanged from the earlier
[adaptive-search comparison](performance-adaptive.md). These are new
measurements at the requested probabilities, not interpolated results.

| Vertices | Edge probability | Before median (s) | After median (s) | Median paired speedup | Completed before / after |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1,000 | 1.897367% | 0.602516 | 0.019397 | 31.36x | 20 / 20 |
| 3,000 | 1.095445% | 25.6623 | 0.187043 | 138.9x | 20 / 20 |

All 80 runs finished within the two-minute budget and matched the independent
reference; all 40 pairs had identical CSV. Speedup is the median of the
20 within-graph ratios, which can differ from the ratio of group medians.

## Interpretation

This density is precisely in the fixed-alpha regime where the old adjacency-list
walk had cubic leading expected search work and the new common-neighbor search
has quadratic expected enumeration work. The missing-edge search is intended
for nearly complete graphs. See the [algorithm analysis](adaptive-search.md)
for the proof, selector heuristic, and component/support costs.

These two whole-program timing groups measure practical speed at the requested
density. They do not independently prove an asymptotic exponent. The earlier
instrumented scaling study used alpha=0.5; the mathematical fixed-alpha bound
also applies at alpha=0.6. Arbitrary fixed positive densities can have
quartically many induced squares.

## Protocol and evidence

Each build has one fresh-process `-tf` measurement per graph, including startup,
parsing, analysis, output, and cleanup. The limit is 120 seconds and 4 GiB
of virtual address space per process. Workers use CPUs 1, 2, and 3; the
supervisor uses CPU 0. Before/after order alternates by sample index.
Graph generation and reference analysis are outside the measured interval.
The shared host and one timing per graph limit precision and portability.

- [1,000-vertex raw results](performance-alpha06-n1000.json).
- [3,000-vertex raw results](performance-alpha06-n3000.json).
- [Independent artifact verification](performance-alpha06-validation.json).

The raw records retain exact probabilities, actual densities, seeds, hashes,
all timings, reference structures, and build provenance. Verification
independently regenerates all 40 inputs, revalidates every output, checks
current and committed sources and executable hashes, and recomputes summary
statistics. Existing normal/sanitizer validation remains applicable because
the measured application and test sources have not changed.

## Reproduce

Use the builds and common runner arguments from the earlier adaptive report.
Run each size separately, with these vertex/probability/output arguments:

```sh
--vertices 1000 --probabilities 0.018973665961010275 --samples 20 --output audit/performance-alpha06-n1000.json
--vertices 3000 --probabilities 0.01095445115010332 --samples 20 --output audit/performance-alpha06-n3000.json
```

After both studies finish, verify and render this report:

```sh
python3 benchmarks/report_alpha06.py
```
