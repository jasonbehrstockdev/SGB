#!/usr/bin/env python3
"""Generate deterministic 100-vertex benchmark inputs using only the stdlib."""

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
N = 100


def pair_path(pairs, offset=0, ring=False):
    edges = set()
    links = [(i, i + 1) for i in range(pairs - 1)]
    if ring:
        links.append((pairs - 1, 0))
    for a, b in links:
        for x in (offset + 2 * a, offset + 2 * a + 1):
            for y in (offset + 2 * b, offset + 2 * b + 1):
                edges.add(tuple(sorted((x, y))))
    return edges


def expected(squares, components, support, legacy_cfs, intended_cfs=None, universal=0):
    return dict(squares=squares, components=components,
                largest_support=support, legacy_cfs=legacy_cfs,
                intended_cfs=legacy_cfs if intended_cfs is None else intended_cfs,
                universal_vertices=universal)


def main():
    cases = [
        ("pair_path_100", pair_path(50),
         "50 independent vertex pairs along a path; consecutive pairs joined by K2,2.",
         expected(241, 1, 100, True), {}),
        ("pair_ring_100", pair_path(50, ring=True),
         "50 independent vertex pairs around a ring; consecutive pairs joined by K2,2.",
         expected(250, 1, 100, True), {}),
        ("two_pair_paths_bridge_100", pair_path(25) | pair_path(25, 50) | {(49, 50)},
         "Two 50-vertex pair paths joined by one bridge edge.",
         expected(232, 2, 50, False), {}),
        ("pair_path_with_leaves_100", pair_path(49) | {(0, 98), (0, 99)},
         "A 98-vertex pair path with two pendant leaves at vertex 1.",
         expected(236, 1, 98, False), {}),
        ("pair_path_join_K2_100", pair_path(49) | {(i, j) for i in range(98) for j in (98, 99)} | {(98, 99)},
         "A 98-vertex pair path joined with K2: vertices 99 and 100 are universal. "
         "The literal square graph has support 98; intended CFS permits this complete join factor.",
         expected(236, 1, 98, False, intended_cfs=True, universal=2), {}),
    ]
    for probability in (0.04, 0.08, 0.12):
        for seed in (202401, 202402, 202403):
            rng = random.Random(seed)
            edges = {(i, j) for i in range(N) for j in range(i + 1, N)
                     if rng.random() < probability}
            cases.append((f"er_p{probability:.2f}_seed{seed}", edges,
                          "Unconditioned seeded Erdos-Renyi G(100,p); disconnected samples retained.",
                          None, dict(probability=probability, seed=seed)))
    cases.append(("cycle_100_square_free",
                  {(i, i + 1) for i in range(N - 1)} | {(0, N - 1)},
                  "C100: connected and square-free; exercises the known empty-square-vector bug.",
                  expected(0, 0, 0, False), {}))

    lines, metadata = [], []
    vertices = "[" + ",".join(str(i + 1) for i in range(N)) + "]"
    for line_number, (name, edges, description, known, parameters) in enumerate(cases, 1):
        assert all(0 <= a < b < N for a, b in edges)
        line = vertices + " [" + ",".join(f"({a+1},{b+1})" for a, b in sorted(edges)) + "]"
        lines.append(line)
        metadata.append(dict(name=name, line=line_number, vertices=N, edges=len(edges),
                             description=description, parameters=parameters,
                             construction_expectation=known,
                             input_sha256=hashlib.sha256(line.encode()).hexdigest()))
    graph_bytes = ("\n".join(lines) + "\n").encode()
    (ROOT / "graphs.txt").write_bytes(graph_bytes)
    (ROOT / "metadata.json").write_text(json.dumps(dict(
        format="SGB TEA, one graph per line; vertex labels 1 through 100",
        cfs_definitions=dict(
            legacy_cfs="Original executable: a square-graph component supports every original vertex.",
            intended_cfs="A square-graph component supports every nonuniversal vertex; a complete join factor is allowed. "
                         "Universal vertices are never added to literal square support. "
                         "Complete-only and empty-graph base cases are unestablished and are not benchmarked."),
        expectation_derivation="An m-pair path has 5m-9 squares; a pair ring (m>=5) has 5m. "
                               "Bridges and pendant edges introduce no cycles.",
        random_generator="Python random.Random(seed).random(), lexicographic pairs i<j; "
                         "the same seeds across densities give nested edge sets, not independent samples.",
        graphs_sha256=hashlib.sha256(graph_bytes).hexdigest(), cases=metadata), indent=2) + "\n")
    print(f"Generated {len(cases)} graphs, each with {N} vertices, in {ROOT / 'graphs.txt'}")


if __name__ == "__main__":
    main()
