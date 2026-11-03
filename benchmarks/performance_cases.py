#!/usr/bin/env python3
"""Extend the correctness corpus with bounded, deterministic 100-vertex workloads."""

import hashlib
import json
import random
from pathlib import Path

from generate import pair_path


ROOT = Path(__file__).resolve().parent


def erdos_renyi(probability, seed):
    rng = random.Random(seed)
    return {(a, b) for a in range(100) for b in range(a + 1, 100)
            if rng.random() < probability}


def small_world(degree, probability, seed):
    """Rewire clockwise lattice edges to sorted eligible nonneighbors."""
    rng = random.Random(seed)
    original = [(a, (a + offset) % 100) for a in range(100)
                for offset in range(1, degree // 2 + 1)]
    edges = {tuple(sorted(edge)) for edge in original}
    for a, b in original:
        if rng.random() >= probability:
            continue
        eligible = [c for c in range(100) if c != a and tuple(sorted((a, c))) not in edges]
        if eligible:
            edges.remove(tuple(sorted((a, b))))
            edges.add(tuple(sorted((a, rng.choice(eligible)))))
    return edges


def main():
    lines = (ROOT / 'graphs.txt').read_text().splitlines()
    existing = json.loads((ROOT / 'metadata.json').read_text())
    assert hashlib.sha256((ROOT / 'graphs.txt').read_bytes()).hexdigest() == existing['graphs_sha256']
    cases = existing['cases'].copy()
    extras = [
        ('er_p0.18_seed20261030', erdos_renyi(.18, 20261030),
         'Denser Erdos-Renyi graph; many overlapping induced squares.',
         dict(probability=.18, seed=20261030)),
        ('er_p0.25_seed20261031', erdos_renyi(.25, 20261031),
         'Erdos-Renyi graph with a larger square set; bounded alternative to very dense bipartite graphs.',
         dict(probability=.25, seed=20261031)),
        ('near_complete_p0.98_seed20261032', erdos_renyi(.98, 20261032),
         'Chord-rich near-complete graph with an independently checked universal clique factor.',
         dict(probability=.98, seed=20261032)),
        ('K10_10_with_tail_100', {(a, b) for a in range(10) for b in range(10, 20)} |
         {(0, 20)} | {(a, a + 1) for a in range(20, 99)},
         'K10,10 plus an 80-vertex pendant path; 2025 squares, one component supported on 20 vertices.',
         dict(bipartition=[10, 10], tail_vertices=80)),
        ('pair_path_join_K20_100', pair_path(40) |
         {(a, b) for a in range(80) for b in range(80, 100)} |
         {(a, b) for a in range(80, 100) for b in range(a + 1, 100)},
         '80-vertex pair path joined with K20; 191 squares supported on 80 vertices and CFS=true.',
         dict(pairs=40, universal_clique_vertices=20)),
        ('small_world_k12_p0.25_seed20261033', small_world(12, .25, 20261033),
         'Degree-12 ring lattice with seeded clockwise-edge rewiring; 600 simple edges.',
         dict(initial_degree=12, rewire_probability=.25, seed=20261033)),
    ]
    labels = '[' + ','.join(str(i + 1) for i in range(100)) + ']'
    for name, edges, description, parameters in extras:
        assert all(0 <= a < b < 100 for a, b in edges)
        line = labels + ' [' + ','.join(f'({a + 1},{b + 1})' for a, b in sorted(edges)) + ']'
        lines.append(line)
        cases.append(dict(name=name, line=len(lines), vertices=100, edges=len(edges),
                          description=description, parameters=parameters,
                          input_sha256=hashlib.sha256(line.encode()).hexdigest()))
    data = ('\n'.join(lines) + '\n').encode()
    (ROOT / 'performance-graphs.txt').write_bytes(data)
    metadata = dict(schema_version=1, graphs_sha256=hashlib.sha256(data).hexdigest(),
                    original_corpus_sha256=existing['graphs_sha256'],
                    generator='Python random.Random; exact graph records are committed.',
                    selection='Original 15 studied cases plus six deliberately selected workloads; '
                              'all 100 vertices. This is not a random sample of all graphs.', cases=cases)
    (ROOT / 'performance-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Wrote {len(cases)} 100-vertex performance inputs.')


if __name__ == '__main__':
    main()
