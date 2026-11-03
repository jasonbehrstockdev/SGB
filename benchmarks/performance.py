#!/usr/bin/env python3
"""Compare two SGB builds on the same studied graphs, retaining every timing."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from run import check_diagnostics, compare_observed, parse_sgb, positive_timeout, require, sha256


ROOT = Path(__file__).resolve().parent


def positive_integer(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return result


def timed(binary, path, timeout, mode='-tf'):
    start = time.perf_counter()
    result = subprocess.run([str(binary), mode, str(path)], capture_output=True,
                            text=True, timeout=timeout)
    elapsed = time.perf_counter() - start
    check_diagnostics(result.stderr)
    require(result.returncode == 0, f'{binary.name} exited {result.returncode}: {result.stderr}')
    require(not result.stderr, f'{binary.name} produced unexpected stderr: {result.stderr}')
    return elapsed, result.stdout


def source_hashes(directory):
    return {name: sha256(directory / name) for name in ('main.cpp', 'flags.h', 'input.h')}


def environment():
    info = dict(platform=platform.platform(), machine=platform.machine(),
                python=platform.python_version(), logical_cpus=os.cpu_count())
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        info['cpu_model'] = next((line.split(':', 1)[1].strip()
                                  for line in cpuinfo.read_text().splitlines()
                                  if line.startswith('model name')), 'unknown')
    for name in ('cpu.max', 'memory.max'):
        path = Path('/sys/fs/cgroup') / name
        if path.exists():
            info['cgroup_' + name] = path.read_text().strip()
    if hasattr(os, 'sched_getaffinity'):
        info['cpu_affinity'] = sorted(os.sched_getaffinity(0))
    return info


def summary(samples):
    return dict(median_seconds=statistics.median(samples), min_seconds=min(samples),
                max_seconds=max(samples), samples_seconds=samples)


def measure_case(case, line, truth, binaries, args, directory, case_number):
    path = directory / 'case.txt'
    path.write_text(line + '\n')
    singles = {}
    for label, binary in binaries.items():
        elapsed, output = timed(binary, path, args.timeout)
        comparison = compare_observed(parse_sgb(output), truth)
        require(comparison['matches_intended_reference'],
                f"{case['name']} {label}: reference mismatch: {comparison}")
        singles[label] = dict(seconds=elapsed, output=output)
    require(singles['before']['output'] == singles['after']['output'],
            f"{case['name']}: before/after CSV differs")
    # Calibrate a common input batch. Cap slow-build work so a dramatic speedup
    # does not make each baseline sample unnecessarily long.
    pilot_count = min(8, max(1, int(.2 / max(item['seconds'] for item in singles.values()))))
    path.write_text((line + '\n') * pilot_count)
    pilot = {}
    for label, binary in binaries.items():
        elapsed, output = timed(binary, path, args.timeout)
        pilot[label] = elapsed / pilot_count
        require(output == expected_batch(singles[label]['output'], pilot_count), 'Pilot output differs')
    count = max(1, min(args.max_batch, math.ceil(args.target_seconds / min(pilot.values())),
                       max(1, math.floor(args.slow_batch_seconds / max(pilot.values())))))
    path.write_text((line + '\n') * count)
    expected = expected_batch(singles['before']['output'], count)
    warmups = {}
    for label, binary in binaries.items():
        elapsed, output = timed(binary, path, args.timeout)
        require(output == expected, f"{case['name']}: warmup output differs")
        warmups[label] = elapsed
    samples = dict(before=[], after=[])
    order = []
    for repeat in range(args.repeats):
        labels = ['before', 'after'] if (repeat + case_number) % 2 == 0 else ['after', 'before']
        order.append(labels)
        for label in labels:
            elapsed, output = timed(binaries[label], path, args.timeout)
            require(output == expected, f"{case['name']} {label}: timed output differs")
            samples[label].append(elapsed)
    before, after = (summary([elapsed / count for elapsed in samples[label]])
                     for label in ('before', 'after'))
    result = dict(name=case['name'], vertices=100, edges=case['edges'],
                  input_sha256=case['input_sha256'], reference=truth,
                  csv_output=singles['before']['output'], identical_csv=True,
                  matches_independent_reference=True, records_per_process=count,
                  repeats=args.repeats, execution_order=order,
                  single_run_seconds={label: item['seconds'] for label, item in singles.items()},
                  pilot_records=pilot_count, pilot_per_graph_seconds=pilot,
                  warmup_batch_seconds=warmups, batch_samples_seconds=samples,
                  before=before, after=after,
                  speedup=before['median_seconds'] / after['median_seconds'])
    print(f"{case['name']}: {1000 * before['median_seconds']:.3f} -> "
          f"{1000 * after['median_seconds']:.3f} ms/graph, {result['speedup']:.2f}x "
          f"({count} records/process)", flush=True)
    return result


def expected_batch(single, count):
    lines = single.splitlines(keepends=True)
    require(len(lines) == 2, 'Expected header and one CSV data row')
    return lines[0] + lines[1] * count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--before-source', type=Path, required=True)
    parser.add_argument('--after-source', type=Path, default=ROOT.parent)
    parser.add_argument('--before-commit', required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--compiler-flags', default='-O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror')
    parser.add_argument('--boost-version', required=True)
    parser.add_argument('--repeats', type=positive_integer, default=7)
    parser.add_argument('--target-seconds', type=positive_timeout, default=.05)
    parser.add_argument('--slow-batch-seconds', type=positive_timeout, default=.5)
    parser.add_argument('--max-batch', type=positive_integer, default=256)
    parser.add_argument('--timeout', type=positive_timeout, default=30)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'audit/performance-results.json')
    args = parser.parse_args()
    try:
        require(args.repeats >= 3, 'Use at least three repeats')
        binaries = dict(before=args.before.resolve(), after=args.after.resolve())
        for path in (*binaries.values(), args.reference):
            require(path.is_file() and os.access(path, os.X_OK), f'Not executable: {path}')
        # Invalidate a previous complete result before reference/calibration can
        # fail. A partially executed rerun must never look like fresh success.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        started_utc = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(dict(schema_version=1, completed=False,
                                               started_utc=started_utc, cases=[]), indent=2) + '\n')
        graph_path = ROOT / 'performance-graphs.txt'
        metadata = json.loads((ROOT / 'performance-metadata.json').read_text())
        lines = graph_path.read_text().splitlines()
        require(sha256(graph_path) == metadata['graphs_sha256'], 'Corpus hash mismatch')
        require(len(lines) == len(metadata['cases']), 'Case count mismatch')
        reference = subprocess.run([str(args.reference.resolve()), str(graph_path)],
                                   text=True, capture_output=True, timeout=args.timeout, check=True)
        check_diagnostics(reference.stderr)
        require(not reference.stderr, 'Unexpected reference diagnostics')
        truth = [json.loads(line) for line in reference.stdout.splitlines()]
        require(len(truth) == len(lines), 'Reference case count mismatch')
        report = dict(schema_version=1, started_utc=started_utc,
                      methodology='Seven (by default) alternating before/after fresh-process runs per case, '
                                  'after calibration and one warmup per build. Each process reads a common batch '
                                  'of identical graph records in -tf mode. Wall time includes startup, parsing, '
                                  'analysis, cleanup and CSV output. Per-graph time is elapsed/batch size. '
                                  'Calibration targets the faster build for at least target_seconds, capped by '
                                  'max_batch and a slow-build batch budget; those bounds can leave short samples. '
                                  'Comparison is ratio of medians, not maximum speedup. Every output is checked '
                                  'byte-for-byte and each case against the independent reference. '
                                  'No performance claim is made about unmeasured graph families or machines.',
                      environment=environment(), before_commit=args.before_commit,
                      compiler_version=subprocess.run([args.compiler, '--version'], capture_output=True,
                                                      text=True, check=True).stdout.splitlines()[0],
                      compiler_flags=args.compiler_flags, boost_version=args.boost_version,
                      source_sha256=dict(before=source_hashes(args.before_source),
                                         after=source_hashes(args.after_source)),
                      binary_sha256={label: sha256(path) for label, path in binaries.items()},
                      reference_source_sha256=sha256(ROOT / 'reference.cpp'),
                      reference_binary_sha256=sha256(args.reference),
                      runner_sha256=sha256(Path(__file__)),
                      graphs_sha256=metadata['graphs_sha256'], repeats=args.repeats,
                      target_seconds=args.target_seconds, slow_batch_seconds=args.slow_batch_seconds,
                      max_batch=args.max_batch, timeout_seconds=args.timeout, cases=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='sgb-performance-') as directory:
            for number, (case, line, expected) in enumerate(zip(metadata['cases'], lines, truth)):
                require(expected['vertices'] == case['vertices'] == 100, 'Expected 100 vertices')
                require(expected['edges'] == case['edges'], 'Edge count mismatch')
                require(hashlib.sha256(line.encode()).hexdigest() == case['input_sha256'], 'Input hash mismatch')
                report['cases'].append(measure_case(case, line, expected, binaries, args,
                                                     Path(directory), number))
                # A timeout or later mismatch must not turn partial evidence into
                # an apparently complete run. Keep its explicitly incomplete checkpoint.
                report['completed'] = False
                args.output.write_text(json.dumps(report, indent=2) + '\n')
        report['completed'] = True
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report['aggregate'] = dict(
            equal_case_geometric_mean_speedup=math.exp(statistics.mean(math.log(c['speedup']) for c in report['cases'])),
            equal_case_total_before_seconds=sum(c['before']['median_seconds'] for c in report['cases']),
            equal_case_total_after_seconds=sum(c['after']['median_seconds'] for c in report['cases']))
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(f'Saved complete measurements: {args.output}', flush=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
