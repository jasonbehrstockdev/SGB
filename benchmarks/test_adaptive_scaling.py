#!/usr/bin/env python3
"""Cross-check the scaling study's independent square-count oracles."""

from itertools import combinations
import random
import unittest

from adaptive_scaling import count_dense_squares, count_sparse_squares, generate, make_specs


def four_subset_count(n, edges):
    edges = set(edges)
    return sum(all(sum(tuple(sorted((u, v))) in edges for v in vertices if u != v) == 2
                   for u in vertices)
               for vertices in combinations(range(n), 4))


class ScalingOracleTests(unittest.TestCase):
    def test_both_oracles_match_four_subset_definition(self):
        rng = random.Random(20261102)
        # Selected cases cover square-free, sparse, intermediate, and nearly
        # complete inputs. This is not exhaustive enumeration of tiny graphs.
        for n in (0, 1, 4, 9, 13):
            pairs = list(combinations(range(n), 2))
            for probability in (0, .08, .25, .5, .85, 1):
                edges = [pair for pair in pairs if rng.random() < probability]
                expected = four_subset_count(n, edges)
                missing = sorted(set(pairs) - set(edges))
                with self.subTest(n=n, probability=probability):
                    self.assertEqual(count_sparse_squares(n, edges), expected)
                    self.assertEqual(count_dense_squares(n, missing), expected)

    def test_complement_cross_edges_are_deduplicated(self):
        # In the complement C4, the opposite edge pairs have two cross edges;
        # in K4 they have four. Each forbidden pair must be subtracted once.
        for missing in ([(0, 1), (1, 2), (2, 3), (0, 3)], list(combinations(range(4), 2))):
            self.assertEqual(count_dense_squares(4, missing), 0)

    def test_complete_graph_minus_matching_has_exact_square_count(self):
        missing = [(v, v + 1) for v in range(0, 100, 2)]
        self.assertEqual(count_dense_squares(100, missing), 50 * 49 // 2)

    def test_twenty_distinct_reproducible_cases_per_family(self):
        specs = make_specs([40], 20, .5, 2)
        self.assertEqual(len(specs), 40)
        hashes = set()
        for spec in specs:
            first, metadata = generate(spec)
            second, repeated = generate(spec)
            self.assertEqual(first, second)
            self.assertEqual(metadata, repeated)
            hashes.add(metadata['input_sha256'])
        self.assertEqual(len(hashes), 40)

    def test_parameter_rejection(self):
        for vertices, alpha, degree in (([1], .5, 2), ([4, 4], .5, 2), ([4], 4, 2),
                                         ([4], .5, 5), ([4], float('nan'), 2),
                                         ([4], .5, float('inf'))):
            with self.assertRaises(ValueError):
                make_specs(vertices, 20, alpha, degree)


if __name__ == '__main__':
    unittest.main()
