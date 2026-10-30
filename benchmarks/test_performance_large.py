#!/usr/bin/env python3
"""Protect large-graph verification and timeout reporting against false success."""

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from performance_large import bounded_run, validate_csv
from run import HEADER


class LargePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.truth = dict(vertices=3000, edges=45000, squares=64000, components=64000,
                          original_components=1, largest_support=4, support_sum=256000,
                          intended_cfs=False)

    def csv(self, edges=None, support_sum=None):
        truth = self.truth
        n = truth['vertices']
        density = 2 * (truth['edges'] if edges is None else edges) / (n * (n - 1))
        average = (truth['support_sum'] if support_sum is None else support_sum) / (n * truth['components'])
        values = [n, density, density * math.sqrt(n), 0, truth['squares'], truth['components'],
                  average, truth['largest_support'] / n, 'connected']
        return ','.join(HEADER) + '\n' + ','.join(format(value, '.12g') if isinstance(value, float)
                                                 else str(value) for value in values) + '\n'

    def test_correct_twelve_digit_csv_passes(self):
        validate_csv(self.csv(), self.truth)

    def test_one_edge_density_error_is_detected(self):
        with self.assertRaises(ValueError):
            validate_csv(self.csv(edges=45001), self.truth)

    def test_one_vertex_support_sum_error_is_detected(self):
        with self.assertRaises(ValueError):
            validate_csv(self.csv(support_sum=256001), self.truth)

    def test_timeout_is_censored_and_child_is_reaped(self):
        result = bounded_run([sys.executable, '-c', 'import time; time.sleep(10)'], .05, 256 * 1024**2)
        self.assertEqual(result['status'], 'timeout')
        self.assertLess(result['returncode'], 0)
        self.assertNotIn('CFS', result)

    def test_recoverable_sanitizer_error_is_failure(self):
        result = bounded_run([sys.executable, '-c',
                              'import sys; sys.stderr.write("runtime error: overflow\\n")'],
                             5, 256 * 1024**2)
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(result['status'], 'error')

    def test_reference_failure_invalidates_stale_report(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'results.json'
            output.write_text(json.dumps(dict(completed=True, cases=['stale'])))
            process = subprocess.run([
                sys.executable, str(root / 'performance_large.py'), '--before', sys.executable,
                '--after', sys.executable, '--reference', sys.executable,
                '--before-source', str(root.parent), '--after-commit', 'test',
                '--boost-version', 'test', '--output', str(output)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(process.returncode, 0)
            report = json.loads(output.read_text())
            self.assertFalse(report['completed'])
            self.assertEqual(report['cases'], [])


if __name__ == '__main__':
    unittest.main()
