#!/usr/bin/env python3
"""Compare an existing SGB binary with the independent benchmark reference."""

import argparse
import hashlib
import json
import math
import platform
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_sgb(output):
    rows = [line for line in output.splitlines() if line and line[0].isdigit()]
    if len(rows) != 1:
        raise ValueError(f"Expected one data row, got {len(rows)}")
    fields = [field.strip() for field in rows[0].split(',')]
    if len(fields) == 5 and fields[4] == "Disconnected.":
        return dict(vertices=int(fields[0]), reported_cfs=bool(int(fields[3])),
                    disconnected=True, square_metrics_unavailable=True)
    if len(fields) != 8:
        raise ValueError(f"Unexpected data row: {rows[0]}")
    average, largest = float(fields[6]), float(fields[7])
    return dict(vertices=int(fields[0]), reported_cfs=bool(int(fields[3])),
                squares=int(fields[4]), components=int(fields[5]),
                average_support_ratio=average if math.isfinite(average) else None,
                largest_support=round(largest * int(fields[0])) if math.isfinite(largest) else None,
                nonfinite_support_ratio=not (math.isfinite(average) and math.isfinite(largest)),
                disconnected=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sgb', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--timeout', type=float, default=30.0)
    parser.add_argument('--cfs-mode', choices=('legacy', 'intended'), default='intended',
                        help='CFS definition used for pass/fail; both classifications are recorded')
    parser.add_argument('--output', type=Path, default=ROOT / 'results.json')
    args = parser.parse_args()
    binary, reference = args.sgb.resolve(), args.reference.resolve()
    graph_file = ROOT / 'graphs.txt'
    metadata = json.loads((ROOT / 'metadata.json').read_text())
    lines = graph_file.read_text().splitlines()
    assert sha256(graph_file) == metadata['graphs_sha256']
    assert len(lines) == len(metadata['cases'])
    started = time.perf_counter()
    checked = subprocess.run([str(reference), str(graph_file)], text=True,
                             capture_output=True, timeout=args.timeout, check=True)
    reference_seconds = time.perf_counter() - started
    expected = [json.loads(line) for line in checked.stdout.splitlines()]
    assert len(expected) == len(lines)
    results = []
    with tempfile.TemporaryDirectory(prefix='sgb-bench-') as temp:
        for case, line, truth in zip(metadata['cases'], lines, expected):
            assert truth['vertices'] == case['vertices'] == 100
            assert truth['edges'] == case['edges']
            assert hashlib.sha256(line.encode()).hexdigest() == case['input_sha256']
            known = case['construction_expectation']
            if known is not None:
                assert all(truth[key] == value for key, value in known.items()), case['name']
            path = Path(temp) / 'graph.txt'
            path.write_text(line + '\n')
            result = dict(name=case['name'], reference=truth)
            started = time.perf_counter()
            try:
                process = subprocess.run([str(binary), '-tf', str(path)], cwd=temp,
                                         capture_output=True, text=True, timeout=args.timeout)
                result.update(wall_seconds=round(time.perf_counter() - started, 6),
                              returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
                if process.returncode == 0:
                    observed = parse_sgb(process.stdout)
                    result['observed'] = observed
                    keys = ('vertices',) if observed.get('disconnected') else (
                        'vertices', 'squares', 'components', 'largest_support')
                    result['compared_fields'] = list(keys)
                    result['connectivity_matches_reference'] = observed['disconnected'] == (truth['original_components'] > 1)
                    metrics_match = (result['connectivity_matches_reference'] and
                                     all(observed[key] == truth[key] for key in keys))
                    result['matches_legacy_reference'] = metrics_match and observed['reported_cfs'] == truth['legacy_cfs']
                    result['matches_intended_cfs'] = observed['reported_cfs'] == truth['intended_cfs']
                    result['matches_intended_reference'] = metrics_match and result['matches_intended_cfs']
                    if (result['matches_legacy_reference'] and truth['universal_vertices'] > 0 and
                            truth['legacy_cfs'] != truth['intended_cfs']):
                        result['known_definition_mismatch'] = 'Original executable requires full square support; intended CFS permits the universal complete join factor. Literal square metrics still agree.'
                    elif not result['matches_intended_cfs']:
                        result['unexpected_classification_mismatch'] = True
                    result['square_metrics_complete'] = not observed.get('disconnected', False)
                    if observed.get('nonfinite_support_ratio'):
                        result['known_limitation'] = 'Empty square graph: original source has empty-vector undefined behavior and prints NaN support ratio.'
                else:
                    result['matches_legacy_reference'] = False
                    result['matches_intended_reference'] = False
            except subprocess.TimeoutExpired:
                result.update(wall_seconds=round(time.perf_counter() - started, 6),
                              timed_out=True, matches_legacy_reference=False, matches_intended_reference=False)
            except ValueError as error:
                result.update(parse_error=str(error), matches_legacy_reference=False, matches_intended_reference=False)
            result['matches_selected_reference'] = result[f'matches_{args.cfs_mode}_reference']
            results.append(result)
            print(f"{case['name']}: {result['wall_seconds']:.4f}s; legacy matches={result['matches_legacy_reference']}; "
                  f"intended CFS matches={result.get('matches_intended_cfs')}", flush=True)
    report = dict(
        methodology='One fresh SGB process per graph, -tf mode, one timed run; wall time includes process startup. '
                    'Reference independently enumerates all 4-vertex subsets using an adjacency matrix. '
                    'Square components are formed by shared-diagonal union-find. '
                    'Disconnected original graphs omit square metrics in SGB; only n/legacy CFS can then be compared. '
                    'Intended CFS allows a complete join factor, with square support kept literal; '
                    'its mismatch is reported separately from legacy-reference agreement. '
                    'C100 is a known undefined-behavior probe, not evidence the empty-square path is safe.',
        environment=dict(platform=platform.platform(), machine=platform.machine(),
                         python=platform.python_version()),
        source_sha256=sha256(ROOT.parent / 'main.cpp'), sgb_binary_sha256=sha256(binary),
        reference_source_sha256=sha256(ROOT / 'reference.cpp'),
        graphs_sha256=metadata['graphs_sha256'], timeout_seconds=args.timeout,
        selected_cfs_mode=args.cfs_mode,
        reference_total_seconds=round(reference_seconds, 6), cases=results)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(f"Saved {args.output}")
    return 0 if all(case['matches_selected_reference'] for case in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
