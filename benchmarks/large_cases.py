#!/usr/bin/env python3
"""Generate the fixed 1,000/3,000-vertex density comparison corpus."""

import hashlib
import gzip
import io
import json
import random
from pathlib import Path

from generate import pair_path


ROOT = Path(__file__).resolve().parent


def erdos_renyi(n, probability, seed):
    rng = random.Random(seed)
    return {(a, b) for a in range(n) for b in range(a + 1, n)
            if rng.random() < probability}


def main():
    lines, cases = [], []
    for n, seed in ((1000, 20261041), (3000, 20261043)):
        examples = []
        for probability in (.005, .0075, .01):
            edges = erdos_renyi(n, probability, seed)
            examples.append((f'er_n{n}_p{probability:g}_seed{seed}', edges,
                             dict(model='Erdos-Renyi', probability=probability, seed=seed),
                             'Unconditioned G(n,p); same seed across densities gives nested edge sets.'))
        examples.append((f'pair_path_{n}', pair_path(n // 2), dict(model='pair_path', pairs=n // 2),
                         'Independent vertex pairs along a path; consecutive pairs joined by K2,2. '
                         f'Exactly {5 * (n // 2) - 9} squares, one square component, full support, CFS=true.'))
        labels = '[' + ','.join(str(vertex + 1) for vertex in range(n)) + ']'
        for name, edges, parameters, description in examples:
            assert all(0 <= a < b < n for a, b in edges)
            line = labels + ' [' + ','.join(f'({a + 1},{b + 1})' for a, b in sorted(edges)) + ']'
            lines.append(line)
            cases.append(dict(name=name, line=len(lines), vertices=n, edges=len(edges),
                              actual_density=2 * len(edges) / (n * (n - 1)),
                              average_degree=2 * len(edges) / n,
                              parameters=parameters, description=description,
                              input_sha256=hashlib.sha256(line.encode()).hexdigest()))
    data = ('\n'.join(lines) + '\n').encode()
    compressed = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=compressed, mtime=0) as output:
        output.write(data)
    (ROOT / 'large-graphs.txt.gz').write_bytes(compressed.getvalue())
    working = ROOT.parent / 'build/performance-large'
    working.mkdir(parents=True, exist_ok=True)
    (working / 'graphs.txt').write_bytes(data)
    (ROOT / 'large-metadata.json').write_text(json.dumps(dict(
        schema_version=1, graphs_sha256=hashlib.sha256(data).hexdigest(),
        compressed_graphs_sha256=hashlib.sha256(compressed.getvalue()).hexdigest(),
        generator='Python random.Random(seed).random() in lexicographic a<b order; exact graph records committed.',
        selection='Selected 1,000- and 3,000-vertex graphs at the same three densities, plus pair-path controls. '
                  'One seed per vertex count, reused across densities for nested edge sets. '
                  'This studies specific examples and does not estimate a population-average speedup.',
        cases=cases), indent=2) + '\n')
    print(f'Wrote {len(cases)} graphs, {len(data):,} bytes ({len(compressed.getvalue()):,} compressed).')


if __name__ == '__main__':
    main()
