# SGB audit

The original 2024 program was imported before any source edits. This folder
records the subsequent repairs, full rereview, and recommendations.

- [Performance improvements](performance.md): implemented optimizations,
  repeated before/after speed measurements, and structural correctness checks.
- [Post-repair review](review.md): resolution of all eleven original findings,
  additional issues corrected, validation, and remaining limitations.
- [Strengths and weaknesses](strengths-and-weaknesses.md): assessment of the
  mathematical representation, implementation, and suitability for future work.
- [Improvement plan](improvement-plan.md): prioritized optimization and design
  suggestions, with tradeoffs and checks needed before accepting changes.
- [Original review](original-review.md): historical findings against the
  unchanged import, retained for comparison.

The original repair assessments and their evidence below refer to commit
`cbdb90f`, before the performance changes. The performance report records the
subsequent changes and their validation separately.

Validation evidence from the repair pass:

- [Optimized 100-vertex results](../benchmarks/results.json).
- [Sanitizer 100-vertex results](validation-sanitize.json).
- [Supplied-example results](validation-examples.json).
- [Original benchmark baseline](../benchmarks/results-original.json).

Reproduce the application and checker tests with `make check` and `make sanitize`
from the repository root. Add `CPPFLAGS=-I/path/to/boost/include` if necessary.
The historical macOS executable is preserved but was not part of runtime testing.
