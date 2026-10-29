# Mathematical conventions

The author confirmed that CFS classification allows complete join factors:
for `Gamma = Omega * K` with `K` complete, apply the square-component full-support
test to `Omega`. Preserve this convention when using the CFS check as a thickness
base case. The original import used all vertices; the subsequent fix excludes
universal vertices only from the classification target and requires an actual
square component.

Keep square-graph construction literal: enumerate the supplied graph's induced
squares and actual component supports. Do not add coverage or squares for clique
factor vertices. Keep this distinction explicit in the API, output, and tests.
Pure complete graphs and empty graphs require a separately established thickness
base-case convention.

# Validation guidance

The author prefers selected, representative 100-vertex graphs as studied,
reproducible benchmarks for both Square Graph Builder and the related thickness
algorithm. Exhaustively enumerating graphs on six vertices offers little
coverage of the structures those algorithms study and should not be the main
validation strategy.

Use structured examples and deterministic random samples with recorded
parameters and reference results. Keep small graphs for targeted regression
checks. Distinguish correctness checks from performance measurements and state
which structural cases a benchmark covers.
