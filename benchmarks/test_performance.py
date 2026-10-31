#!/usr/bin/env python3
"""Prevent a failed rerun from leaving stale performance evidence marked complete."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PerformanceCheckpointTests(unittest.TestCase):
    def test_reference_failure_invalidates_previous_complete_report(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix='sgb-performance-test-') as directory:
            output = Path(directory) / 'results.json'
            output.write_text(json.dumps(dict(completed=True, cases=['stale'])))
            # Python is executable but cannot interpret graph records as a
            # program. This fails in the reference step, before case 1 starts.
            process = subprocess.run([
                sys.executable, str(root / 'performance.py'),
                '--before', sys.executable, '--after', sys.executable,
                '--reference', sys.executable, '--before-source', str(root.parent),
                '--before-commit', 'test', '--boost-version', 'test',
                '--output', str(output)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(process.returncode, 0)
            report = json.loads(output.read_text())
            self.assertFalse(report['completed'])
            self.assertEqual(report['cases'], [])


if __name__ == '__main__':
    unittest.main()
