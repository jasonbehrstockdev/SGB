#!/usr/bin/env python3
"""Compare an existing SGB binary with the independent benchmark reference."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEADER = ['n', 'p', 'alpha', 'CFS', 'num_squares', 'num_comp',
          'ratio_comp_avg', 'ratio_largest_comp', 'status']


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive_timeout(value):
    try:
        timeout = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError('timeout must be a positive finite number')
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError('timeout must be a positive finite number')
    return timeout


def check_diagnostics(stderr):
    for marker in ('AddressSanitizer', 'UndefinedBehaviorSanitizer', 'LeakSanitizer', 'runtime error:'):
        require(marker not in stderr, f'Sanitizer diagnostic detected: {marker}')


def parse_sgb(output, legacy_output=False):
    try:
        rows = [[field.strip() for field in row]
                for row in csv.reader(io.StringIO(output), strict=True) if row]
    except csv.Error as error:
        raise ValueError(f'Malformed CSV: {error}') from error
    if legacy_output:
        if rows and rows[0] == HEADER[:-1]:
            rows = rows[1:]
        require(len(rows) == 1 and len(rows[0]) in (5, 8), 'Expected one historical 5- or 8-column row')
    else:
        require(len(rows) == 2 and rows[0] == HEADER, 'Expected the 9-column header and one data row')
        rows = rows[1:]
        require(len(rows[0]) == 9, 'Expected a 9-column data row')
    fields = rows[0]
    n, cfs = int(fields[0]), int(fields[3])
    density, alpha = float(fields[1]), float(fields[2])
    require(n >= 0 and cfs in (0, 1), 'Invalid vertex count or CFS value')
    require(math.isfinite(density) and math.isfinite(alpha), 'Nonfinite density or alpha')
    require(0 <= density <= 1 and alpha >= 0, 'Invalid density or alpha')
    observed = dict(vertices=n, reported_cfs=bool(cfs), density=density, alpha=alpha,
                    square_metrics_unavailable=False, nonfinite_support_ratio=False)
    if len(fields) == 5:
        require(fields[4] == 'Disconnected.', 'Unrecognized historical status')
        observed.update(status='disconnected', disconnected=True, square_metrics_unavailable=True)
        return observed
    squares, components = int(fields[4]), int(fields[5])
    average, largest = float(fields[6]), float(fields[7])
    require(squares >= 0 and 0 <= components <= squares, 'Invalid square/component count')
    require(math.isfinite(largest) and 0 <= largest <= 1, 'Invalid largest-support ratio')
    if not math.isfinite(average):
        require(legacy_output and math.isnan(average) and squares == components == 0 and largest == 0,
                'Nonfinite average-support ratio')
        observed['nonfinite_support_ratio'] = True
    else:
        require(0 <= average <= 1, 'Invalid average-support ratio')
    status = 'connected' if legacy_output else fields[8]
    require(status in ('connected', 'disconnected', 'empty'), 'Unrecognized graph status')
    observed.update(squares=squares, components=components,
                    average_support_ratio=average if math.isfinite(average) else None,
                    largest_support_ratio=largest, largest_support=round(largest * n),
                    status=status, disconnected=status == 'disconnected')
    return observed


def compare_observed(observed, truth, legacy_output=False):
    n, components = truth['vertices'], truth['components']
    status = 'empty' if n == 0 else 'connected' if truth['original_components'] == 1 else 'disconnected'
    expected = dict(vertices=n, status=status, squares=truth['squares'], components=components,
                    largest_support=truth['largest_support'],
                    largest_support_ratio=truth['largest_support'] / n if n else 0,
                    average_support_ratio=truth['support_sum'] / (components * n) if components and n else 0,
                    density=2 * truth['edges'] / (n * (n - 1)) if n > 1 else 0)
    expected['alpha'] = expected['density'] * math.sqrt(n)
    keys = ['vertices', 'status']
    if not observed['square_metrics_unavailable']:
        keys += ['squares', 'components', 'largest_support', 'largest_support_ratio']
        if not observed['nonfinite_support_ratio']:
            keys.append('average_support_ratio')
    if not legacy_output:
        keys += ['density', 'alpha']
    # Six-significant-digit historical output needs a small rounding tolerance;
    # it is much smaller than one edge or vertex in these 100-vertex graphs.
    mismatches = [key for key in keys if not (
        math.isclose(observed[key], expected[key], rel_tol=1e-5, abs_tol=1e-6)
        if isinstance(expected[key], float) else observed[key] == expected[key])]
    metrics_match = not mismatches
    result = dict(compared_fields=keys, mismatched_fields=mismatches,
                  connectivity_matches_reference=observed['status'] == status,
                  matches_legacy_reference=metrics_match and observed['reported_cfs'] == truth['legacy_cfs'],
                  matches_intended_cfs=observed['reported_cfs'] == truth['intended_cfs'],
                  matches_intended_reference=metrics_match and observed['reported_cfs'] == truth['intended_cfs'],
                  square_metrics_complete=not observed['square_metrics_unavailable'] and not observed['nonfinite_support_ratio'],
                  full_validation=not legacy_output)
    if legacy_output:
        result['validation_limitations'] = ['Historical output: density and alpha are not validated.']
        if observed['square_metrics_unavailable']:
            result['validation_limitations'].append('Historical disconnected row omits all square metrics.')
        if observed['nonfinite_support_ratio']:
            result['validation_limitations'].append('Historical square-free row has NaN average support; that field is not validated.')
    if (result['matches_legacy_reference'] and truth['universal_vertices'] > 0 and
            truth['legacy_cfs'] != truth['intended_cfs']):
        result['known_definition_mismatch'] = 'Reported CFS uses full square support; intended CFS permits the universal complete join factor. Checked square metrics agree.'
    elif not result['matches_intended_cfs']:
        result['unexpected_classification_mismatch'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sgb', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--timeout', type=positive_timeout, default=30.0)
    parser.add_argument('--cfs-mode', choices=('legacy', 'intended'), default='intended',
                        help='CFS definition used for pass/fail; both classifications are recorded')
    parser.add_argument('--output', type=Path, default=ROOT / 'results.json')
    parser.add_argument('--legacy-output', action='store_true',
                        help='Permit original 8/5-column output with explicitly incomplete validation; independent of --cfs-mode')
    args = parser.parse_args()
    for path in (args.sgb, args.reference):
        if not path.is_file() or not os.access(path, os.X_OK):
            parser.error(f'not an executable file: {path}')
    if args.output.resolve() == (ROOT / 'results-original.json').resolve():
        parser.error('results-original.json is the preserved historical baseline; choose another output')
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


def run(args):
    binary, reference = args.sgb.resolve(), args.reference.resolve()
    graph_file = ROOT / 'graphs.txt'
    metadata = json.loads((ROOT / 'metadata.json').read_text())
    lines = graph_file.read_text().splitlines()
    require(sha256(graph_file) == metadata['graphs_sha256'], 'Graph file hash differs from metadata; regenerate inputs')
    require(len(lines) == len(metadata['cases']), 'Graph and metadata case counts differ')
    started = time.perf_counter()
    checked = subprocess.run([str(reference), str(graph_file)], text=True,
                             capture_output=True, timeout=args.timeout, check=True)
    reference_seconds = time.perf_counter() - started
    expected = [json.loads(line) for line in checked.stdout.splitlines()]
    require(len(expected) == len(lines), 'Reference output case count differs from inputs')
    results = []
    with tempfile.TemporaryDirectory(prefix='sgb-bench-') as temp:
        for case, line, truth in zip(metadata['cases'], lines, expected):
            require(truth['vertices'] == case['vertices'] == 100, f"{case['name']}: expected 100 vertices")
            require(truth['edges'] == case['edges'], f"{case['name']}: reference edge count differs")
            require(hashlib.sha256(line.encode()).hexdigest() == case['input_sha256'], f"{case['name']}: input hash differs")
            known = case['construction_expectation']
            if known is not None:
                require(all(truth[key] == value for key, value in known.items()), f"{case['name']}: construction expectation differs")
            path = Path(temp) / 'graph.txt'
            path.write_text(line + '\n')
            result = dict(name=case['name'], reference=truth, matches_legacy_reference=False,
                          matches_intended_reference=False, full_validation=False)
            started = time.perf_counter()
            try:
                process = subprocess.run([str(binary), '-tf', str(path)], cwd=temp,
                                         capture_output=True, text=True, timeout=args.timeout)
                result.update(wall_seconds=round(time.perf_counter() - started, 6),
                              returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
                check_diagnostics(process.stderr)
                if process.returncode == 0:
                    observed = parse_sgb(process.stdout, args.legacy_output)
                    result['observed'] = observed
                    result.update(compare_observed(observed, truth, args.legacy_output))
            except subprocess.TimeoutExpired:
                result.update(wall_seconds=round(time.perf_counter() - started, 6),
                              timed_out=True, matches_legacy_reference=False, matches_intended_reference=False)
            except (OSError, ValueError) as error:
                result.update(parse_error=str(error), matches_legacy_reference=False, matches_intended_reference=False)
            result['wall_seconds'] = round(time.perf_counter() - started, 6)
            result['matches_selected_reference'] = result[f'matches_{args.cfs_mode}_reference']
            results.append(result)
            print(f"{case['name']}: {result['wall_seconds']:.4f}s; legacy matches={result['matches_legacy_reference']}; "
                  f"intended CFS matches={result.get('matches_intended_cfs')}", flush=True)
    source_hashes = {name: sha256(ROOT.parent / name) for name in ('main.cpp', 'flags.h', 'input.h')}
    report = dict(schema_version=2,
        methodology='One fresh SGB process per graph, -tf mode, one timed run; wall time includes process startup. '
                    'Reference independently enumerates all 4-vertex subsets using an adjacency matrix. '
                    'Square components are formed by shared-diagonal union-find. '
                    'Corrected output is checked for all square metrics, density, alpha, and connectivity, including disconnected inputs. '
                    'Explicit legacy-output mode permits missing historical fields and marks validation incomplete. '
                    'Intended CFS allows a complete join factor, with square support kept literal; '
                    'its mismatch is reported separately from legacy-reference agreement. '
                    'C100 tests finite zero-support output for an empty square graph.',
        environment=dict(platform=platform.platform(), machine=platform.machine(),
                         python=platform.python_version()),
        source_files_sha256=source_hashes,
        source_tree_sha256=hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest(),
        sgb_binary_sha256=sha256(binary), reference_binary_sha256=sha256(reference),
        reference_source_sha256=sha256(ROOT / 'reference.cpp'),
        graphs_sha256=metadata['graphs_sha256'], timeout_seconds=args.timeout,
        selected_cfs_mode=args.cfs_mode,
        output_mode='historical' if args.legacy_output else 'corrected',
        reference_total_seconds=round(reference_seconds, 6), cases=results)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(f"Saved {args.output}")
    return 0 if all(case['matches_selected_reference'] for case in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
