#!/usr/bin/env python3
"""Bounded before/after measurements on selected 1,000/3,000-vertex graphs."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import statistics
import subprocess
import tempfile
import time

from performance import environment, source_hashes, summary
from run import check_diagnostics, parse_sgb, positive_timeout, require, sha256


ROOT = Path(__file__).resolve().parent


def bounded_run(command, timeout, memory_bytes):
    """Linux/POSIX child only: cap address space; kill the whole group on timeout."""
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, preexec_fn=limits)
    status = 'ok'
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            status = 'timeout'
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    elapsed = time.perf_counter() - started
    if status == 'ok' and process.returncode != 0:
        status = 'allocation_failure_under_cap' if 'bad_alloc' in stderr else 'error'
    try:
        check_diagnostics(stderr)
    except ValueError:
        status = 'error'
    if status == 'ok' and stderr:
        status = 'error'
    return dict(status=status, wall_seconds=elapsed, returncode=process.returncode,
                stdout=stdout, stderr=stderr)


def validate_csv(output, truth):
    """Use corrected 12-significant-digit tolerances, not historical CSV tolerances."""
    observed = parse_sgb(output)
    n, components = truth['vertices'], truth['components']
    expected = dict(vertices=n, squares=truth['squares'], components=components,
                    largest_support=truth['largest_support'], reported_cfs=truth['intended_cfs'],
                    status='empty' if n == 0 else 'connected' if truth['original_components'] == 1 else 'disconnected')
    for key, value in expected.items():
        require(observed[key] == value, f'{key}: observed {observed[key]}, expected {value}')
    density = 2 * truth['edges'] / (n * (n - 1)) if n > 1 else 0
    numeric = dict(density=density, alpha=density * math.sqrt(n),
                   largest_support_ratio=truth['largest_support'] / n if n else 0,
                   average_support_ratio=truth['support_sum'] / (n * components) if n and components else 0)
    for key, value in numeric.items():
        require(math.isclose(observed[key], value, rel_tol=1e-11, abs_tol=1e-12),
                f'{key}: observed {observed[key]}, expected {value}')
    return observed


def compact_reference(truth):
    details = truth['component_details']
    require(len(details) == truth['components'], 'Reference component detail count mismatch')
    require(sum(item['squares'] for item in details) == truth['squares'], 'Reference square count mismatch')
    require(sum(item['support'] for item in details) == truth['support_sum'], 'Reference support sum mismatch')
    require(max((item['support'] for item in details), default=0) == truth['largest_support'],
            'Reference largest support mismatch')
    result = {key: value for key, value in truth.items() if key != 'component_details'}
    histogram = Counter((item['support'], item['squares']) for item in details)
    result['component_histogram'] = [dict(support=support, squares=squares, components=count)
                                    for (support, squares), count in sorted(histogram.items())]
    result['component_details_sha256'] = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
    return result


def measure_case(case, line, truth, binaries, args, directory, case_number):
    path = directory / 'graph.txt'
    path.write_text(line + '\n')
    result = dict(case, reference=compact_reference(truth), warmups={}, samples=dict(before=[], after=[]),
                  execution_order=[], identical_completed_csv=True, all_completed_outputs_match_reference=True)
    expected_output = None

    def invoke(label):
        nonlocal expected_output
        observation = bounded_run([str(binaries[label]), '-tf', str(path)], args.timeout, args.memory_bytes)
        if observation['status'] == 'ok':
            validate_csv(observation['stdout'], truth)
            if expected_output is None:
                expected_output = observation['stdout']
            require(observation['stdout'] == expected_output, f"{case['name']}: CSV differs between completed runs")
            observation['validated'] = True
        else:
            observation['validated'] = False
            require(observation['status'] in ('timeout', 'allocation_failure_under_cap'),
                    f"{case['name']} {label}: execution error: {observation['stderr']}")
        return observation

    # Warmups also decide which build is feasible within the declared budget.
    # Do not repeat a known timed-out baseline five more times.
    for label in ('before', 'after'):
        result['warmups'][label] = invoke(label)
    active = [label for label in binaries if result['warmups'][label]['status'] == 'ok']
    for repeat in range(args.repeats):
        labels = ['before', 'after'] if (repeat + case_number) % 2 == 0 else ['after', 'before']
        labels = [label for label in labels if label in active]
        result['execution_order'].append(labels)
        for label in labels:
            observation = invoke(label)
            result['samples'][label].append(observation)
            if observation['status'] != 'ok':
                active.remove(label)
    for label in binaries:
        observations = result['samples'][label]
        successful = [sample['wall_seconds'] for sample in observations if sample['status'] == 'ok']
        complete = len(successful) == args.repeats
        result[label] = dict(completed_samples=len(successful), complete=complete,
                             statistics=summary(successful) if successful else None)
    if result['before']['complete'] and result['after']['complete']:
        result['comparison'] = dict(kind='ratio_of_medians', speedup=
                                    result['before']['statistics']['median_seconds'] /
                                    result['after']['statistics']['median_seconds'])
    elif (result['warmups']['before']['status'] == 'timeout' and result['after']['complete']):
        result['comparison'] = dict(kind='timeout_qualified_lower_bound',
                                    speedup_greater_than=args.timeout / result['after']['statistics']['median_seconds'],
                                    explanation='One baseline attempt exceeded the wall-time budget; this is a censored '
                                                'observation divided by the optimized median, not a measured median-to-median ratio.')
    else:
        result['comparison'] = dict(kind='unavailable', explanation='Incomplete timing samples or address-space limit; no exact speedup claimed.')
    result['optimized_correctness_validated'] = result['after']['complete']
    print(f"{case['name']}: before={result['before']} after={result['after']} "
          f"comparison={result['comparison']}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--before-source', type=Path, required=True)
    parser.add_argument('--after-source', type=Path, default=ROOT.parent)
    parser.add_argument('--before-commit', default='cbdb90fb17186288f6a77944f2ee84dee2c4f230')
    parser.add_argument('--after-commit', required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--timeout', type=positive_timeout, default=30)
    parser.add_argument('--memory-gib', type=int, default=4)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--compiler-flags', default='-O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror')
    parser.add_argument('--boost-version', required=True)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'audit/performance-large-results.json')
    args = parser.parse_args()
    try:
        require(args.repeats >= 3, 'At least three repetitions are required')
        require(args.memory_gib > 0, 'Address-space limit must be positive')
        args.memory_bytes = args.memory_gib * 1024 ** 3
        binaries = dict(before=args.before.resolve(), after=args.after.resolve())
        for binary in (*binaries.values(), args.reference):
            require(binary.is_file() and os.access(binary, os.X_OK), f'Not executable: {binary}')
        report = dict(schema_version=1, completed=False, started_utc=datetime.now(timezone.utc).isoformat(), cases=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        compressed = ROOT / 'large-graphs.txt.gz'
        metadata = json.loads((ROOT / 'large-metadata.json').read_text())
        require(sha256(compressed) == metadata['compressed_graphs_sha256'], 'Compressed corpus hash mismatch')
        data = gzip.decompress(compressed.read_bytes())
        require(hashlib.sha256(data).hexdigest() == metadata['graphs_sha256'], 'Corpus hash mismatch')
        lines = data.decode().splitlines()
        require(len(lines) == len(metadata['cases']), 'Corpus case count mismatch')
        report.update(methodology='Five fresh-process single-graph measurements per feasible build, after one warmup. '
                      'Before/after order alternates when both builds finish. Each subprocess has a wall-time and Linux '
                      'RLIMIT_AS address-space cap; timed-out process groups are killed and reaped. A build exceeding a '
                      'budget is not repeatedly rerun. Timeout is not a mathematical result. Every completed output '
                      'is checked against an independent scalable oracle using strict 12-significant-digit CSV tolerances and is '
                      'byte-identical to other completed outputs. Reference checks are outside the timed measurements. '
                      'Wall times include launch, parsing, analysis, cleanup, CSV output, and limit setup; no batching. '
                      'Exact speedup is a ratio of medians; a censored baseline yields only a labeled timeout-qualified bound.',
                      environment=environment(), before_commit=args.before_commit, after_commit=args.after_commit,
                      compiler_version=subprocess.run([args.compiler, '--version'], capture_output=True, text=True,
                                                      check=True).stdout.splitlines()[0],
                      compiler_flags=args.compiler_flags, boost_version=args.boost_version,
                      source_sha256=dict(before=source_hashes(args.before_source), after=source_hashes(args.after_source)),
                      binary_sha256={label: sha256(binary) for label, binary in binaries.items()},
                      reference_binary_sha256=sha256(args.reference), reference_source_sha256=sha256(ROOT / 'reference_large.cpp'),
                      runner_sha256=sha256(Path(__file__)), graphs_sha256=metadata['graphs_sha256'],
                      compressed_graphs_sha256=metadata['compressed_graphs_sha256'], repeats=args.repeats,
                      timeout_seconds=args.timeout, address_space_limit_bytes=args.memory_bytes,
                      float_comparison_tolerance=dict(relative=1e-11, absolute=1e-12))
        with tempfile.TemporaryDirectory(prefix='sgb-large-performance-') as directory:
            path = Path(directory) / 'corpus.txt'
            path.write_bytes(data)
            reference = bounded_run([str(args.reference.resolve()), str(path)], args.timeout, args.memory_bytes)
            require(reference['status'] == 'ok', f'Reference failed: {reference}')
            truths = [json.loads(line) for line in reference['stdout'].splitlines()]
            require(len(truths) == len(lines), 'Reference case count mismatch')
            report['reference_check_wall_seconds'] = reference['wall_seconds']
            report['reference_stdout_sha256'] = hashlib.sha256(reference['stdout'].encode()).hexdigest()
            for number, (case, line, truth) in enumerate(zip(metadata['cases'], lines, truths)):
                require(case['vertices'] == truth['vertices'] and case['edges'] == truth['edges'], 'Reference/input size mismatch')
                require(hashlib.sha256(line.encode()).hexdigest() == case['input_sha256'], 'Input record hash mismatch')
                report['cases'].append(measure_case(case, line, truth, binaries, args, Path(directory), number))
                args.output.write_text(json.dumps(report, indent=2) + '\n')
        report['completed'] = True
        report['all_optimized_cases_validated'] = all(case['optimized_correctness_validated'] for case in report['cases'])
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        require(report['all_optimized_cases_validated'], 'Some optimized cases did not complete all validated repetitions')
        print(f'Saved complete validated results: {args.output}', flush=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
