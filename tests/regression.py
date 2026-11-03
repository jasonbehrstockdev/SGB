#!/usr/bin/env python3
"""Targeted CLI regressions; the 100-vertex corpus is checked separately."""

import argparse
import ast
import csv
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


HEADER = ["n", "p", "alpha", "CFS", "num_squares", "num_comp",
          "ratio_comp_avg", "ratio_largest_comp", "status"]
C4 = "[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]"
K23 = "[1,2,3,4,5] [(1,3),(1,4),(1,5),(2,3),(2,4),(2,5)]"
TRIANGLE = "[1,2,3] [(1,2),(2,3),(1,3)]"
TWO_SQUARES = ("[1,2,3,4,5,6,7,8] "
               "[(1,2),(2,3),(3,4),(1,4),(5,6),(6,7),(7,8),(5,8)]")
BINARY = None
TIMEOUT = 10.0


def environment():
    env = os.environ.copy()
    # LeakSanitizer is unavailable in some sandboxed execution environments.
    # Callers may override this to enable leak checking on supported hosts.
    env.setdefault("ASAN_OPTIONS", "detect_leaks=0")
    env.setdefault("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=1")
    return env


def decoded_graph(line):
    match = re.fullmatch(r"(\[[^\]]*\])\s+(\[[^\]]*\])", line.strip())
    if not match:
        raise AssertionError(f"Export is not a graph record: {line!r}")
    return ast.literal_eval(match[1]), ast.literal_eval(match[2])


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sgb-regression-")
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args, success=True, cwd=None):
        process = subprocess.run(
            [str(BINARY), *map(str, args)], cwd=cwd or self.directory,
            capture_output=True, text=True, timeout=TIMEOUT, env=environment())
        self.assertNotIn("AddressSanitizer", process.stderr, process.stderr)
        self.assertNotIn("UndefinedBehaviorSanitizer", process.stderr, process.stderr)
        self.assertNotIn("runtime error:", process.stderr, process.stderr)
        if success:
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            self.assertGreater(process.returncode, 0, process.stderr)
            self.assertTrue(process.stderr.strip(), "Errors need a diagnostic on stderr")
        return process

    def source(self, text):
        path = self.directory / "input.txt"
        path.write_text(text)
        return path

    def graphs(self, text, flags="-tf"):
        return self.invoke(flags, self.source(text.rstrip("\n") + "\n"))

    def rows(self, output):
        records = list(csv.reader(output.splitlines(), skipinitialspace=True))
        self.assertTrue(records, "Missing CSV output")
        self.assertEqual(records[0], HEADER)
        self.assertGreater(len(records), 1)
        result = []
        for row in records[1:]:
            self.assertEqual(len(row), len(HEADER), row)
            item = dict(zip(HEADER, (value.strip() for value in row)))
            for field in HEADER[:-1]:
                self.assertTrue(math.isfinite(float(item[field])), item)
            for field in ("n", "CFS", "num_squares", "num_comp"):
                item[field] = int(item[field])
            for field in ("p", "alpha", "ratio_comp_avg", "ratio_largest_comp"):
                item[field] = float(item[field])
            self.assertIn(item["status"], ("connected", "disconnected", "empty"))
            result.append(item)
        return result

    def assert_metrics(self, row, *, n, squares, components, largest, cfs,
                       average=None, status="connected"):
        self.assertEqual(row["n"], n)
        self.assertEqual(row["num_squares"], squares)
        self.assertEqual(row["num_comp"], components)
        self.assertEqual(row["CFS"], int(cfs))
        self.assertEqual(row["status"], status)
        self.assertAlmostEqual(row["ratio_largest_comp"], largest / n if n else 0,
                               delta=1e-5)
        if average is not None:
            self.assertAlmostEqual(row["ratio_comp_avg"], average, delta=1e-5)

    def test_help(self):
        for option in ("--help", "-h"):
            with self.subTest(option=option):
                result = self.invoke(option)
                self.assertIn("usage", result.stdout.lower())

    def test_missing_arguments_and_invalid_numbers(self):
        cases = [(), ("-t",), ("-s", "10", ".5", "1"),
                 ("foo", ".5", "1"), ("0", ".5", "1"),
                 ("-1", ".5", "1"), ("1.5", ".5", "1"),
                 ("10", ".5", "0"), ("10", ".5", "-1"),
                 ("10", "nan", "1"), ("10", "inf", "1"),
                 ("10", "-.1", "1"), ("10", "1.1", "1"),
                 ("10", "0.5junk", "1"), ("10x", ".5", "1"),
                 ("184467440737095516160", ".5", "1"),
                 ("10", ".5", "184467440737095516160"),
                 ("-a", "4", "3", "1"), ("-a", "4", "-1", "1"),
                 ("-x", "10", ".5", "1"),
                 ("10", ".5", "1", "unexpected")]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.invoke(*arguments, success=False)

    def test_mode_and_seed_validation(self):
        path = self.source(C4 + "\n")
        for arguments in (("-ts", path), ("-ta", path),
                          ("-as", "10", ".5", "1", "4"),
                          ("-t", path, "--seed", "1"),
                          ("--seed",), ("--seed", "-1", "10", ".5", "1"),
                          ("--seed", "18446744073709551616", "10", ".5", "1")):
            with self.subTest(arguments=arguments):
                self.invoke(*arguments, success=False)
        self.invoke("-f", "--seed", "18446744073709551615", "4", "1", "1")

    def test_input_open_and_empty_file_errors(self):
        self.invoke("-t", self.directory / "absent.txt", success=False)
        self.invoke("-t", self.directory, success=False)
        self.invoke("-t", self.source(""), success=False)

    def test_invalid_graphs_reject_without_memory_errors(self):
        invalid = ["[1,2] [(0,1)]", "[1,2] [(-1,1)]", "[1,2] [(1,4)]",
                   "[1,2] [(1,184467440737095516160)]", "[] [(1,1)]",
                   "[1,3] []", "[2,3] []", "[1,1] []", "[0,2] []",
                   "[1,2] [(1,2)", "[1,2] [(1,2),]", "[1,2] [(1)]",
                   "[1,2] [(1,2,1)]", "[1,2] [(1x,2)]", "[1,2] [] junk",
                   "[1,2", "[1,2]", "not a graph", "", "   "]
        for line in invalid:
            with self.subTest(line=line):
                result = self.invoke("-tf", self.source(C4 + "\n" + line + "\n"),
                                     success=False)
                self.assertIn("input.txt", result.stderr)
                self.assertRegex(result.stderr.lower(), r"(?:line\s*|:)2\b")

    def test_empty_singleton_edgeless_and_square_free(self):
        cases = [("[] []", 0, "empty"), ("[1] []", 1, "connected"),
                 ("[0] []", 1, "connected"), ("[1,2] []", 2, "disconnected"),
                 (TRIANGLE, 3, "connected"),
                 ("[1,2,3] [(1,2),(2,3)]", 3, "connected")]
        for graph, n, status in cases:
            with self.subTest(graph=graph):
                row = self.rows(self.graphs(graph).stdout)[0]
                self.assert_metrics(row, n=n, squares=0, components=0, largest=0,
                                    cfs=False, average=0, status=status)

    def test_file_density_alpha_and_c4(self):
        row = self.rows(self.graphs(C4).stdout)[0]
        self.assert_metrics(row, n=4, squares=1, components=1, largest=4,
                            cfs=True, average=1)
        self.assertAlmostEqual(row["p"], 2 / 3, delta=1e-5)
        self.assertAlmostEqual(row["alpha"], 4 / 3, delta=1e-5)

    def test_zero_based_and_whitespace_input(self):
        graph = " [ 0, 1, 2, 3 ] \t[ (0,1), (1,2), (2,3), (0,3) ] "
        row = self.rows(self.graphs(graph).stdout)[0]
        self.assert_metrics(row, n=4, squares=1, components=1, largest=4,
                            cfs=True, average=1)

    def test_disconnected_square_metrics_and_header(self):
        rows = self.rows(self.graphs(TWO_SQUARES + "\n" + C4).stdout)
        self.assertEqual(len(rows), 2)
        self.assert_metrics(rows[0], n=8, squares=2, components=2, largest=4,
                            cfs=False, average=.5, status="disconnected")
        self.assertEqual(rows[1]["CFS"], 1)

    def test_complete_join_factors_keep_literal_support(self):
        for universal_count in (1, 2):
            with self.subTest(universal_count=universal_count):
                n = 4 + universal_count
                edges = [(1, 2), (2, 3), (3, 4), (1, 4)]
                edges += [(i, j) for j in range(5, n + 1) for i in range(1, j)]
                graph = str(list(range(1, n + 1))) + " " + str(edges)
                row = self.rows(self.graphs(graph).stdout)[0]
                self.assert_metrics(row, n=n, squares=1, components=1, largest=4,
                                    cfs=True, average=4 / n)

    def test_leaves_and_duplicate_degree_do_not_become_join_factors(self):
        graphs = ["[1,2,3,4,5] [(1,2),(2,3),(3,4),(1,4),(1,5)]",
                  "[1,2,3,4,5] [(1,2),(2,3),(3,4),(1,4),(1,2),(1,2),(1,1)]"]
        for graph in graphs:
            with self.subTest(graph=graph):
                row = self.rows(self.graphs(graph).stdout)[0]
                self.assertEqual(row["CFS"], 0)
                self.assertEqual(row["num_squares"], 1)
                self.assertAlmostEqual(row["ratio_largest_comp"], .8)
        joined_non_cfs = ("[1,2,3,4,5,6] [(1,2),(2,3),(3,4),(1,4),(1,5),"
                          "(1,6),(2,6),(3,6),(4,6),(5,6)]")
        row = self.rows(self.graphs(joined_non_cfs).stdout)[0]
        self.assert_metrics(row, n=6, squares=1, components=1, largest=4,
                            cfs=False, average=4 / 6)

    def test_loops_duplicates_normalize_to_simple_graph(self):
        graph = "[1,2,3,4] [(1,2),(2,1),(2,3),(3,4),(1,4),(1,1),(3,3)]"
        actual = self.rows(self.graphs(graph).stdout)[0]
        expected = self.rows(self.graphs(C4).stdout)[0]
        self.assertEqual(actual, expected)

    def test_mixed_size_summary_is_order_independent(self):
        values = []
        for graphs in ((C4, K23), (K23, C4)):
            output = self.graphs("\n".join(graphs), flags="-t").stdout
            self.assertRegex(output, r"\bn\s*=\s*mixed\b")
            values.append(self.support_summary(output))
        self.assertEqual(values[0], values[1])
        self.assertEqual(values[0], (1.0, 1.0))
        self.assertEqual(self.support_summary(self.graphs(C4 + "\n" + TRIANGLE,
                                                        flags="-t").stdout), (.5, .5))
        self.assertEqual(self.support_summary(self.graphs(C4 + "\n" + TWO_SQUARES,
                                                        flags="-t").stdout), (.75, .75))

    def support_summary(self, output):
        values = []
        for name in ("AvgSupport", "LargestSupport"):
            match = re.search(r"\b" + name + r"\s*=\s*([^,\s]+)", output)
            self.assertIsNotNone(match, output)
            value = float(match[1])
            self.assertTrue(math.isfinite(value))
            values.append(value)
        return tuple(values)

    def test_export_without_verbose_and_round_trip(self):
        records = [C4, "[] []", "[1] []", "[1,2] []", TRIANGLE]
        original = self.graphs("\n".join(records), flags="-tef")
        export = self.directory / "graphsanalyzed.txt"
        self.assertTrue(export.exists())
        exported_lines = export.read_text().splitlines()
        self.assertEqual(len(exported_lines), len(records))
        for line in exported_lines:
            vertices, edges = decoded_graph(line)
            self.assertEqual(vertices, list(range(1, len(vertices) + 1)))
            self.assertEqual(len(edges), len(set(tuple(sorted(e)) for e in edges)))
            self.assertTrue(all(a != b and a in vertices and b in vertices for a, b in edges))
        replay = self.invoke("-tf", export)
        self.assertEqual(self.rows(replay.stdout), self.rows(original.stdout))
        self.invoke("-te", self.source(C4 + "\n"))
        self.assertEqual(len(export.read_text().splitlines()), len(records) + 1)

    def test_verbose_debug_does_not_corrupt_csv(self):
        for flags in ("-tvf", "-tdf", "-tdvf"):
            with self.subTest(flags=flags):
                result = self.graphs(C4, flags=flags)
                self.assertEqual(len(self.rows(result.stdout)), 1)
                self.assertTrue(result.stderr.strip())
                self.assertNotIn("\b", result.stdout + result.stderr)

    def test_export_open_failure(self):
        (self.directory / "graphsanalyzed.txt").mkdir()
        self.invoke("-te", self.source(C4 + "\n"), success=False)

    @unittest.skipUnless(Path("/dev/full").exists(), "/dev/full unavailable")
    def test_export_and_stdout_write_failures(self):
        export = self.directory / "graphsanalyzed.txt"
        export.symlink_to("/dev/full")
        self.invoke("-te", self.source(C4 + "\n"), success=False)
        with open("/dev/full", "w") as sink:
            result = subprocess.run([str(BINARY), "-tf", str(self.source(C4 + "\n"))],
                                    cwd=self.directory, stdout=sink, stderr=subprocess.PIPE,
                                    text=True, timeout=TIMEOUT, env=environment())
        self.assertGreater(result.returncode, 0, result.stderr)
        self.assertTrue(result.stderr.strip())

    def test_seed_reproducibility_and_probability_boundaries(self):
        output = []
        for attempt in range(2):
            directory = self.directory / str(attempt)
            directory.mkdir()
            result = self.invoke("-ef", "--seed", "123", "12", ".3", "4", cwd=directory)
            self.assertRegex(result.stderr.lower(), r"seed[^\n]*123")
            self.assertEqual(len(self.rows(result.stdout)), 4)
            output.append((result.stdout, (directory / "graphsanalyzed.txt").read_text()))
        self.assertEqual(output[0], output[1])
        for probability, status in (("0", "disconnected"), ("1", "connected")):
            row = self.rows(self.invoke("-f", "--seed", "0", "6", probability, "1").stdout)[0]
            self.assert_metrics(row, n=6, squares=0, components=0, largest=0,
                                cfs=False, average=0, status=status)
        scaled = self.rows(self.invoke("-af", "--seed", "0", "4", "2", "1").stdout)[0]
        self.assertEqual(scaled["p"], 1)
        self.assertEqual(scaled["alpha"], 2)

    def test_small_world_boundaries(self):
        for n, degree, expected_edges, status in ((5, 0, 0, "disconnected"),
                                                 (5, 4, 10, "connected"),
                                                 (6, 5, 15, "connected"),
                                                 (1, 0, 0, "connected")):
            with self.subTest(n=n, degree=degree):
                directory = self.directory / f"{n}-{degree}"
                directory.mkdir()
                process = self.invoke("-sef", "--seed", "99", n, "1", "1", degree,
                                      cwd=directory)
                row = self.rows(process.stdout)[0]
                self.assert_metrics(row, n=n, squares=0, components=0, largest=0,
                                    cfs=False, average=0, status=status)
                vertices, edges = decoded_graph((directory / "graphsanalyzed.txt").read_text())
                self.assertEqual(len(vertices), n)
                self.assertEqual(len(edges), expected_edges)
        for arguments in (("10", ".5", "1", "3"), ("5", ".5", "1", "5"),
                          ("5", ".5", "1", "-1")):
            self.invoke("-s", *arguments, success=False)

    def test_small_world_100_vertex_simple_graph_invariants(self):
        for probability in ("0", "1"):
            directory = self.directory / probability
            directory.mkdir()
            result = self.invoke("-sef", "--seed", "1234", "100", probability, "1", "4",
                                 cwd=directory)
            self.assertEqual(self.rows(result.stdout)[0]["n"], 100)
            vertices, edges = decoded_graph((directory / "graphsanalyzed.txt").read_text())
            self.assertEqual(len(vertices), 100)
            self.assertEqual(len(edges), 200)
            self.assertEqual(len(set(tuple(sorted(edge)) for edge in edges)), 200)
            degree = dict.fromkeys(vertices, 0)
            for a, b in edges:
                self.assertNotEqual(a, b)
                degree[a] += 1
                degree[b] += 1
            if probability == "0":
                self.assertEqual(set(degree.values()), {4})
            else:
                replay_directory = self.directory / "rewired-replay"
                replay_directory.mkdir()
                replay = self.invoke("-sef", "--seed", "1234", "100", probability, "1", "4",
                                     cwd=replay_directory)
                self.assertEqual(result.stdout, replay.stdout)
                self.assertEqual((directory / "graphsanalyzed.txt").read_text(),
                                 (replay_directory / "graphsanalyzed.txt").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    options = parser.parse_args()
    BINARY = options.binary.resolve()
    TIMEOUT = options.timeout
    if not BINARY.is_file():
        parser.error(f"Binary does not exist: {BINARY}")
    if not math.isfinite(TIMEOUT) or TIMEOUT <= 0:
        parser.error("Timeout must be positive and finite")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
