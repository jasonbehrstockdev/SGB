#!/usr/bin/env python3
"""Cross-check the scalable benchmark oracle against independent small oracles."""

import argparse
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def record(n, edges):
    return ('[' + ','.join(str(vertex + 1) for vertex in range(n)) + '] [' +
            ','.join(f'({a + 1},{b + 1})' for a, b in sorted(edges)) + ']')


def labels(neighbors):
    result = [None] * len(neighbors)
    count = 0
    for start in range(len(neighbors)):
        if result[start] is not None:
            continue
        pending = [start]
        result[start] = count
        while pending:
            current = pending.pop()
            for other in neighbors[current]:
                if result[other] is None:
                    result[other] = count
                    pending.append(other)
        count += 1
    return result, count


def small_oracle(n, edges):
    """Four-subset enumeration, all-pair square adjacency, graph traversal."""
    neighbors = [set() for _ in range(n)]
    for a, b in edges:
        neighbors[a].add(b)
        neighbors[b].add(a)
    _, original_components = labels(neighbors)
    squares = []
    for vertices in itertools.combinations(range(n), 4):
        chosen = set(vertices)
        if all(len(neighbors[vertex] & chosen) == 2 for vertex in vertices):
            squares.append(frozenset((a, b) for a, b in itertools.combinations(vertices, 2)
                                     if b not in neighbors[a]))
    square_neighbors = [set() for _ in squares]
    for a, b in itertools.combinations(range(len(squares)), 2):
        if squares[a] & squares[b]:
            square_neighbors[a].add(b)
            square_neighbors[b].add(a)
    square_labels, count = labels(square_neighbors)
    supports = [set() for _ in range(count)]
    square_counts = [0] * count
    for square, component in zip(squares, square_labels):
        supports[component].update(vertex for diagonal in square for vertex in diagonal)
        square_counts[component] += 1
    sizes = [len(support) for support in supports]
    largest = max(sizes, default=0)
    universal = sum(len(adjacent) == n - 1 for adjacent in neighbors)
    eligible = original_components == 1 and bool(squares)
    details = sorted(zip(sizes, square_counts), reverse=True)
    return dict(vertices=n, edges=len(edges), original_components=original_components,
                squares=len(squares), components=count, largest_support=largest,
                support_sum=sum(sizes), universal_vertices=universal,
                legacy_cfs=eligible and largest == n,
                intended_cfs=eligible and largest == n - universal,
                component_details=[dict(support=support, squares=square_count)
                                   for support, square_count in details])


def invoke(binary, path, success=True):
    environment = os.environ.copy()
    environment.setdefault('ASAN_OPTIONS', 'detect_leaks=0')
    environment.setdefault('UBSAN_OPTIONS', 'halt_on_error=1:print_stacktrace=1')
    result = subprocess.run([str(binary), str(path)], capture_output=True, text=True,
                            timeout=30, env=environment)
    for marker in ('AddressSanitizer', 'UndefinedBehaviorSanitizer', 'LeakSanitizer', 'runtime error:'):
        require(marker not in result.stderr, f'{binary.name}: {result.stderr}')
    if success:
        require(result.returncode == 0 and not result.stderr,
                f'{binary.name}: exit {result.returncode}, {result.stderr}')
        return [json.loads(line) for line in result.stdout.splitlines()]
    require(result.returncode != 0 and result.stderr, f'Invalid input was accepted: {path.read_text()}')
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-large', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    large, original = args.reference_large.resolve(), args.reference.resolve()
    corpus = ROOT / 'benchmarks/performance-graphs.txt'
    expected = invoke(original, corpus)
    actual = invoke(large, corpus)
    require(actual == expected, 'Scalable oracle differs from four-subset oracle on 100-vertex corpus')

    c4 = {(0, 1), (1, 2), (2, 3), (0, 3)}
    small = [(0, set()), (1, set()), (4, set()), (4, c4),
             (4, c4 | {(0, 2)}), (4, set(itertools.combinations(range(4), 2))),
             (5, {(a, b) for a in range(2) for b in range(2, 5)}),
             (6, c4 | {(a, b) for a in range(4) for b in (4, 5)} | {(4, 5)}),
             (8, c4 | {(a + 4, b + 4) for a, b in c4}),
             (6, c4 | {(1, 4), (4, 5), (0, 5)})]
    for n in (9, 15):
        for probability in (.1, .3, .8):
            rng = random.Random(20261030 + n)
            small.append((n, {edge for edge in itertools.combinations(range(n), 2)
                              if rng.random() < probability}))
    invalid = ['[0,1] []', '[1,3] []', '[1,2] [(0,1)]', '[1,2] [(1,3)]',
               '[1,2] [(1,1)]', '[1,2] [(1,2),(2,1)]', '[1,2] [(1,2)] junk',
               '[1,2] [(1,2),]', '[1] [(4294967296,1)]', '[1] [(-1,1)]', '', '[] [(1,1)]']
    with tempfile.TemporaryDirectory(prefix='sgb-large-reference-') as directory:
        path = Path(directory) / 'cases.txt'
        path.write_text('\n'.join(record(n, edges) for n, edges in small) + '\n')
        require(invoke(large, path) == [small_oracle(n, edges) for n, edges in small],
                'Scalable oracle differs from independent Python subset/BFS oracle')
        for bad in invalid:
            path.write_text(bad + '\n')
            invoke(large, path, success=False)
        large_controls = []
        for n in (1000, 3000):
            pairs = n // 2
            edges = {(2 * pair + a, 2 * (pair + 1) + b)
                     for pair in range(pairs - 1) for a in (0, 1) for b in (0, 1)}
            squares = 5 * pairs - 9
            large_controls.append((n, edges, dict(
                vertices=n, edges=2 * n - 4, original_components=1,
                squares=squares, components=1, largest_support=n, support_sum=n,
                universal_vertices=0, legacy_cfs=True, intended_cfs=True,
                component_details=[dict(support=n, squares=squares)])))
        path.write_text('\n'.join(record(n, edges) for n, edges, _ in large_controls) + '\n')
        require(invoke(large, path) == [expected for _, _, expected in large_controls],
                'Scalable oracle differs from exact 1000/3000 pair-path counts')
    print(f'PASS: large reference matches {len(expected)} 100-vertex cases, '
          f'{len(small)} independent small cases, 2 exact large controls; '
          f'{len(invalid)} malformed records rejected')


if __name__ == '__main__':
    main()
