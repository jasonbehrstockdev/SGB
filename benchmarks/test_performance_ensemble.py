#!/usr/bin/env python3
"""Protect paired graph sampling and honest summaries of censored timings."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from performance_ensemble import (aggregate_cases, censored_quantile,
                                  generate_case, make_cases, measure_case,
                                  provenance_equal, resume_report)


def observations(completed, timeouts=0, errors=0):
    return ([dict(status='ok', wall_seconds=float(value), validated=True)
             for value in completed]
            + [dict(status='timeout', wall_seconds=120.01, validated=False)
               for _ in range(timeouts)]
            + [dict(status='error', wall_seconds=1, validated=False)
               for _ in range(errors)])


class EnsembleTests(unittest.TestCase):
    def test_default_matrix_has_twenty_distinct_seeds_per_cell(self):
        cases = make_cases()
        self.assertEqual(len(cases), 240)
        groups = {}
        for case in cases:
            groups.setdefault((case['vertices'], case['probability']), []).append(case)
        self.assertEqual(len(groups), 12)
        self.assertEqual(len({case['name'] for case in cases}), 240)
        for group in groups.values():
            self.assertEqual(len(group), 20)
            self.assertEqual(len({case['seed'] for case in group}), 20)

    def test_generated_graphs_are_distinct_and_reproducible(self):
        cases = make_cases(samples=20, vertices=(40,), probabilities=(.1,))
        hashes = set()
        for case in cases:
            first_line, first_metadata = generate_case(case)
            second_line, second_metadata = generate_case(case)
            self.assertEqual(first_line, second_line)
            self.assertEqual(first_metadata, second_metadata)
            digest = hashlib.sha256(first_line.encode()).hexdigest()
            self.assertEqual(first_metadata['input_sha256'], digest)
            hashes.add(digest)
        self.assertEqual(len(hashes), 20)

    def test_nine_timeouts_leave_twenty_sample_median_exact(self):
        result = censored_quantile(observations(range(1, 12), 9), .5, 120)
        self.assertEqual(result['kind'], 'exact')
        self.assertEqual(result['seconds'], 10.5)

    def test_exactly_ten_timeouts_have_midpoint_lower_bound(self):
        result = censored_quantile(observations(range(1, 11), 10), .5, 120)
        self.assertEqual(result['kind'], 'lower_bound')
        self.assertEqual(result['seconds'], 65)
        self.assertTrue(result['strict'])

    def test_eleven_timeouts_put_median_strictly_above_cutoff(self):
        result = censored_quantile(observations(range(1, 10), 11), .5, 120)
        self.assertEqual(result['kind'], 'lower_bound')
        self.assertEqual(result['seconds'], 120)
        self.assertTrue(result['strict'])

    def test_all_timeouts_are_not_reported_as_measured_runtime(self):
        result = censored_quantile(observations([], 20), .25, 120)
        self.assertEqual(result['kind'], 'lower_bound')
        self.assertTrue(result['strict'])

    def test_runtime_failure_does_not_imply_censored_lower_bound(self):
        result = censored_quantile(observations(range(1, 20), errors=1), .5, 120)
        self.assertEqual(result['kind'], 'unavailable')

    def test_provenance_comparison_ignores_dict_order_but_not_settings(self):
        expected = dict(timeout_seconds=120, cases=['a', 'b'], binary_sha256={'before': 'x', 'after': 'y'})
        reordered = dict(binary_sha256={'after': 'y', 'before': 'x'}, cases=['a', 'b'], timeout_seconds=120)
        self.assertTrue(provenance_equal(expected, reordered))
        self.assertFalse(provenance_equal(expected, dict(reordered, timeout_seconds=30)))
        self.assertFalse(provenance_equal(expected, dict(reordered, cases=['a', 'c'])))

    def test_censored_pairs_are_excluded_from_exact_speedups(self):
        before = observations([10], timeouts=1)
        after = observations([5, 4])
        cases = [dict(vertices=1000, probability=.01, before=b, after=a)
                 for b, a in zip(before, after)]
        group, = aggregate_cases(cases, 120)
        self.assertEqual(group['graphs'], 2)
        self.assertEqual(group['before']['counts']['timeout'], 1)
        self.assertEqual(group['before']['completed_only']['median_seconds'], 10)
        self.assertEqual(group['before']['quantiles']['median']['kind'], 'lower_bound')
        self.assertEqual(group['paired_complete_count'], 1)
        self.assertEqual(group['paired_speedup']['median'], 2)
        self.assertIsNone(group['ratio_of_full_sample_medians'])

    def test_unvalidated_output_cannot_count_as_success(self):
        item = dict(status='ok', wall_seconds=10, validated=False)
        result = censored_quantile([item], .5, 120)
        self.assertEqual(result['kind'], 'unavailable')
        group, = aggregate_cases([dict(vertices=1000, probability=.01, before=item,
                                      after=observations([5])[0])], 120)
        self.assertEqual(group['before']['counts']['ok'], 0)
        self.assertIsNone(group['before']['completed_only'])
        self.assertEqual(group['paired_complete_count'], 0)

    def test_resume_rejects_changed_settings_and_corrupt_input(self):
        spec, = make_cases(samples=1, vertices=(8,), probabilities=(.2,))
        _, metadata = generate_case(spec)
        case = dict(metadata, before=observations([1])[0], after=observations([1])[0])
        provenance = dict(case_specs=[spec], timeout_seconds=120)
        report = dict(provenance=provenance, cases=[case], completed=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text(json.dumps(report))
            self.assertEqual(resume_report(path, provenance), report)
            with self.assertRaisesRegex(ValueError, 'provenance'):
                resume_report(path, dict(provenance, timeout_seconds=30))
            case['input_sha256'] = 'corrupted'
            path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'hash/metadata'):
                resume_report(path, provenance)

    def test_same_graph_is_passed_to_both_builds_even_if_one_times_out(self):
        spec, = make_cases(samples=1, vertices=(4,), probabilities=(.5,))
        line = '[1,2,3,4] [(1,2),(1,4),(2,3),(3,4)]'
        metadata = dict(spec, edges=4, input_sha256=hashlib.sha256(line.encode()).hexdigest())
        truth = dict(vertices=4, edges=4, squares=1, components=1, original_components=1,
                     support_sum=4, largest_support=4, intended_cfs=True,
                     component_details=[dict(support=4, squares=1)])
        csv = ('n,p,alpha,CFS,num_squares,num_comp,ratio_comp_avg,ratio_largest_comp,status\n'
               '4,0.666666666667,1.33333333333,1,1,1,1,1,connected\n')
        settings = dict(cpu=1, reference='reference', before='before', after='after',
                        timeout=120, memory_bytes=4 * 1024**3)
        invoked = []

        def run(command, timeout, memory_bytes):
            invoked.append((command[0], Path(command[-1]).read_text()))
            if command[0] == 'before':
                return dict(status='timeout', wall_seconds=120.01, returncode=-9, stdout='', stderr='')
            return dict(status='ok', wall_seconds=1, returncode=0, stderr='',
                        stdout=json.dumps(truth) + '\n' if command[0] == 'reference' else csv)

        with patch('performance_ensemble.WORKER', settings), \
                patch('performance_ensemble.generate_case', return_value=(line, metadata)), \
                patch('performance_ensemble.bounded_run', side_effect=run):
            result = measure_case(spec)
        self.assertEqual([name for name, _ in invoked], ['reference', 'before', 'after'])
        self.assertTrue(all(data == line + '\n' for _, data in invoked))
        self.assertFalse(result['before']['validated'])
        self.assertTrue(result['after']['validated'])
        self.assertIsNone(result['paired_csv_identical'])

    def test_terminating_worker_kills_and_reaps_active_child(self):
        program = '''
import os
from queue import SimpleQueue
import sys
from performance_ensemble import bounded_run, worker_init
queue = SimpleQueue()
queue.put(min(os.sched_getaffinity(0)))
worker_init(queue, {})
child = ('import os, pathlib, sys, time; '
         'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)')
bounded_run([sys.executable, '-c', child, sys.argv[1]], 120, 256 * 1024**2)
'''
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'child.pid'
            process = subprocess.Popen([sys.executable, '-c', program, str(pid_file)],
                                       cwd=Path(__file__).resolve().parent,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and process.poll() is None:
                    if pid_file.exists() and pid_file.read_text():
                        child_pid = int(pid_file.read_text())
                        break
                    time.sleep(.01)
                self.assertIsNotNone(child_pid, 'Worker did not launch its child')
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 128 + signal.SIGTERM, stderr)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
                if child_pid is not None:
                    try:
                        os.killpg(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == '__main__':
    unittest.main()
