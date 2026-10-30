#!/usr/bin/env python3
"""Collect exploratory phase probes separately from end-to-end speed measurements."""

import argparse
import json
import math
import statistics
import subprocess
import tempfile
from pathlib import Path

from run import check_diagnostics, require, sha256


ROOT = Path(__file__).resolve().parent
NAMES = ['pair_path_100', 'er_p0.12_seed202402', 'er_p0.25_seed20261031',
         'K10_10_with_tail_100', 'pair_path_join_K20_100']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--results', type=Path, default=ROOT.parent / 'audit/performance-results.json')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'audit/performance-phases.json')
    args = parser.parse_args()
    try:
        evidence = json.loads(args.results.read_text())
        require(evidence['completed'], 'End-to-end results must be complete')
        metadata = json.loads((ROOT / 'performance-metadata.json').read_text())
        graph_file = ROOT / 'performance-graphs.txt'
        require(sha256(graph_file) == evidence['graphs_sha256'] == metadata['graphs_sha256'], 'Corpus hash mismatch')
        lines = graph_file.read_text().splitlines()
        selected = [(case, line) for case, line in zip(metadata['cases'], lines) if case['name'] in NAMES]
        require(len(selected) == len(NAMES), 'Missing selected graph')
        expected = {case['name']: case['reference'] for case in evidence['cases']}
        binaries = dict(before=args.before.resolve(), after=args.after.resolve())
        report = dict(schema_version=1, completed=False, cases=[],
                      methodology='Three alternating before/after process pairs, no warmup, five graphs per process. '
                                  'C++ steady_clock measures square enumeration and connectivity only. '
                                  'Before connectivity includes explicit square-graph construction plus Boost connected_components; '
                                  'after connectivity includes diagonal indexing plus disjoint sets. '
                                  'Parsing, support accumulation, classification, output, and graph destruction after the timer '
                                  'are excluded. Exploratory attribution only; use performance-results.json for speed claims.',
                      environment=evidence['environment'], compiler_version=evidence['compiler_version'],
                      compiler_flags=evidence['compiler_flags'], boost_version=evidence['boost_version'],
                      source_sha256=evidence['source_sha256'], before_commit=evidence['before_commit'],
                      probe_source_sha256=sha256(ROOT / 'profile.cpp'), runner_sha256=sha256(Path(__file__)),
                      binary_sha256={label: sha256(binary) for label, binary in binaries.items()},
                      graphs_sha256=metadata['graphs_sha256'], execution_order=[], raw_runs=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        collected = {label: {name: [] for name in NAMES} for label in binaries}
        with tempfile.TemporaryDirectory(prefix='sgb-profile-') as directory:
            graph_path = Path(directory) / 'graphs.txt'
            graph_path.write_text('\n'.join(line for _, line in selected) + '\n')
            for repeat in range(3):
                labels = ['before', 'after'] if repeat % 2 == 0 else ['after', 'before']
                report['execution_order'].append(labels)
                for label in labels:
                    process = subprocess.run([str(binaries[label]), str(graph_path), '1'], text=True,
                                             capture_output=True, timeout=30, check=True)
                    check_diagnostics(process.stderr)
                    require(not process.stderr, 'Unexpected phase probe diagnostics')
                    rows = [json.loads(line) for line in process.stdout.splitlines()]
                    require(len(rows) == len(selected), 'Phase probe row count mismatch')
                    for number, ((case, _), row) in enumerate(zip(selected, rows)):
                        require(row['case'] == number and row['repeat'] == 0, 'Phase probe row order mismatch')
                        truth = expected[case['name']]
                        require(row['squares'] == truth['squares'] and row['components'] == truth['components'],
                                'Phase probe differs from independent reference')
                        require(all(math.isfinite(row[key]) and row[key] >= 0
                                    for key in ('enumeration_seconds', 'connectivity_seconds')), 'Invalid phase time')
                        collected[label][case['name']].append(row)
                    report['raw_runs'].append(dict(repeat=repeat, build=label, rows=rows))
        for case, _ in selected:
            item = dict(name=case['name'], input_sha256=case['input_sha256'])
            for label in binaries:
                rows = collected[label][case['name']]
                item[label] = {phase: dict(samples_seconds=[row[phase] for row in rows],
                                           median_seconds=statistics.median(row[phase] for row in rows))
                               for phase in ('enumeration_seconds', 'connectivity_seconds')}
            report['cases'].append(item)
            print(case['name'], item['before'], item['after'], flush=True)
        report['completed'] = True
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
