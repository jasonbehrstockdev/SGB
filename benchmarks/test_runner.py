#!/usr/bin/env python3
"""Regression checks for false benchmark passes and historical-output limits."""

import argparse
import unittest

from run import HEADER, check_diagnostics, compare_observed, parse_sgb, positive_timeout


def output(row):
    return ','.join(HEADER) + '\n' + row + '\n'


def square_truth(n=4, original_components=1):
    return dict(vertices=n, edges=4, original_components=original_components,
                squares=1, components=1, largest_support=4, support_sum=4,
                legacy_cfs=n == 4, intended_cfs=n == 4, universal_vertices=0)


class RunnerChecks(unittest.TestCase):
    def test_recovering_sanitizer_diagnostics_fail(self):
        check_diagnostics('')
        for diagnostic in ('AddressSanitizer', 'UndefinedBehaviorSanitizer', 'LeakSanitizer', 'runtime error: overflow'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                check_diagnostics(diagnostic)

    def test_correct_connected_row(self):
        row = parse_sgb(output('4,0.666667,1.33333,1,1,1,1,1,connected'))
        result = compare_observed(row, square_truth())
        self.assertTrue(result['matches_intended_reference'])
        self.assertTrue(result['full_validation'])

    def test_all_reported_ratios_are_compared(self):
        for row, field in (
            ('4,0.5,1.33333,1,1,1,1,1,connected', 'density'),
            ('4,0.666667,1,1,1,1,1,1,connected', 'alpha'),
            ('4,0.666667,1.33333,1,1,1,0.9,1,connected', 'average_support_ratio'),
            ('4,0.666667,1.33333,1,1,1,1,0.999,connected', 'largest_support_ratio'),
        ):
            with self.subTest(field=field):
                result = compare_observed(parse_sgb(output(row)), square_truth())
                self.assertFalse(result['matches_intended_reference'])
                self.assertIn(field, result['mismatched_fields'])

    def test_disconnected_square_metrics_are_checked(self):
        truth = square_truth(n=100, original_components=97)
        row = '100,0.000808081,0.00808081,0,1,1,0.04,0.04,disconnected'
        self.assertTrue(compare_observed(parse_sgb(output(row)), truth)['matches_intended_reference'])
        bad = row.replace(',0,1,1,', ',0,2,1,')
        self.assertFalse(compare_observed(parse_sgb(output(bad)), truth)['matches_intended_reference'])

    def test_wrong_connectivity_cannot_hide_square_metrics(self):
        row = parse_sgb('4,1,1,0,Disconnected.\n', legacy_output=True)
        result = compare_observed(row, square_truth(), legacy_output=True)
        self.assertFalse(result['matches_legacy_reference'])
        self.assertFalse(result['connectivity_matches_reference'])

    def test_historical_rows_never_claim_full_validation(self):
        row = parse_sgb('100,1,1,0,Disconnected.\n', legacy_output=True)
        result = compare_observed(row, square_truth(n=100, original_components=97), legacy_output=True)
        self.assertTrue(result['matches_legacy_reference'])
        self.assertFalse(result['full_validation'])
        self.assertFalse(result['square_metrics_complete'])

    def test_historical_nan_exception_is_narrow(self):
        row = parse_sgb('100,1,1,0,0,0,-nan,0\n', legacy_output=True)
        self.assertTrue(row['nonfinite_support_ratio'])
        for bad in ('100,1,1,0,1,1,nan,0', '100,1,1,0,0,0,inf,0', '100,1,1,0,0,0,nan,nan'):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                parse_sgb(bad, legacy_output=True)

    def test_corrected_square_free_row_requires_finite_zero(self):
        truth = dict(vertices=100, edges=100, original_components=1, squares=0, components=0,
                     largest_support=0, support_sum=0, legacy_cfs=False, intended_cfs=False,
                     universal_vertices=0)
        good = '100,0.020202,0.20202,0,0,0,0,0,connected'
        self.assertTrue(compare_observed(parse_sgb(output(good)), truth)['matches_intended_reference'])
        with self.assertRaises(ValueError):
            parse_sgb(output('100,0.020202,0.20202,0,0,0,nan,0,connected'))

    def test_legacy_schema_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            parse_sgb('4,1,1,1,1,1,1,1\n')

    def test_invalid_csv_status_or_cfs_is_rejected(self):
        for row in ('4,0.666667,1.33333,2,1,1,1,1,connected',
                    '4,0.666667,1.33333,1,1,1,1,1,unknown',
                    '4,0.666667,1.33333,1,1,1,1,1,"connected'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                parse_sgb(output(row))

    def test_positive_finite_timeout(self):
        self.assertEqual(positive_timeout('0.1'), 0.1)
        for value in ('0', '-1', 'nan', 'inf', 'no'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_timeout(value)


if __name__ == '__main__':
    unittest.main()
