#!/usr/bin/env python3
"""Check selected 1,000/3,000-vertex graphs against the scalable reference.

This is optional correctness validation, not a speed benchmark. Select an
ASan/UBSan executable to check the same cases with instrumentation enabled.
"""

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks'))
from run import check_diagnostics, parse_sgb, positive_timeout


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compare(observed, truth):
    """Use tolerances suitable for SGB's twelve-significant-digit CSV."""
    n, components = truth['vertices'], truth['components']
    density = 2 * truth['edges'] / (n * (n - 1)) if n > 1 else 0.0
    expected = dict(
        vertices=n, squares=truth['squares'], components=components,
        largest_support=truth['largest_support'], reported_cfs=truth['intended_cfs'],
        status='empty' if n == 0 else 'connected' if truth['original_components'] == 1 else 'disconnected',
        density=density, alpha=density * math.sqrt(n),
        largest_support_ratio=truth['largest_support'] / n if n else 0.0,
        average_support_ratio=truth['support_sum'] / (components * n) if components and n else 0.0)
    mismatches = [key for key, value in expected.items() if not (
        math.isclose(observed[key], value, rel_tol=1e-11, abs_tol=1e-12)
        if isinstance(value, float) else observed[key] == value)]
    return dict(compared_fields=list(expected), mismatched_fields=mismatches,
                matches_reference=not mismatches)


def decoded(value):
    return value.decode(errors='replace') if isinstance(value, bytes) else value or ''


def run(args):
    binary, reference = args.binary.resolve(), args.reference.resolve()
    for path in (binary, reference):
        require(path.is_file() and os.access(path, os.X_OK), f'Not an executable file: {path}')
    metadata_path = ROOT / 'benchmarks/large-metadata.json'
    compressed_path = ROOT / 'benchmarks/large-graphs.txt.gz'
    compressed = compressed_path.read_bytes()
    metadata = json.loads(metadata_path.read_text())
    require(sha256(compressed) == metadata['compressed_graphs_sha256'], 'Compressed input hash mismatch')
    corpus = gzip.decompress(compressed)
    require(sha256(corpus) == metadata['graphs_sha256'], 'Uncompressed input hash mismatch')
    lines = corpus.decode().splitlines()
    require(len(lines) == len(metadata['cases']), 'Input and metadata case counts differ')
    names = [case['name'] for case in metadata['cases']]
    require(len(set(names)) == len(names), 'Duplicate benchmark case names')
    selected = set(args.case or names)
    require(selected <= set(names), 'Unknown case: ' + ', '.join(sorted(selected - set(names))))
    for line, case in zip(lines, metadata['cases']):
        require(sha256(line.encode()) == case['input_sha256'], f"{case['name']}: input hash mismatch")

    environment = os.environ.copy()
    # ASan needs its large virtual shadow mapping; do not impose RLIMIT_AS.
    # Leak checking is unsupported in some sandboxes and is explicitly separate.
    environment.setdefault('ASAN_OPTIONS', 'detect_leaks=0:halt_on_error=1')
    environment.setdefault('UBSAN_OPTIONS', 'halt_on_error=1:print_stacktrace=1')
    report = dict(
        schema_version=1,
        methodology='One application process per selected graph in -tf mode; complete CSV is compared '
                    'with the independent scalable reference. Successful checks require zero exit, '
                    'no stderr, and equality of every reported metric within the declared floating tolerances. '
                    'Timeouts are incomplete validation, never passing checks. Elapsed times are incidental '
                    'correctness observations, not speed measurements. Sanitizer instrumentation depends '
                    'on the selected executable; no leak-checking claim is made.',
        binary_path=str(binary.relative_to(ROOT)) if binary.is_relative_to(ROOT) else str(binary),
        binary_sha256=sha256(binary.read_bytes()),
        reference_binary_sha256=sha256(reference.read_bytes()),
        reference_source_sha256=sha256((ROOT / 'benchmarks/reference_large.cpp').read_bytes()),
        validation_script_sha256=sha256(Path(__file__).read_bytes()),
        source_files_sha256={name:sha256((ROOT / name).read_bytes())
                             for name in ('main.cpp', 'flags.h', 'input.h')},
        graphs_sha256=sha256(corpus), metadata_sha256=sha256(metadata_path.read_bytes()),
        timeout_seconds_per_process=args.timeout,
        floating_tolerances=dict(relative=1e-11, absolute=1e-12),
        environment=dict(platform=platform.platform(), machine=platform.machine(), python=platform.python_version()),
        sanitizer_options={key:environment[key] for key in ('ASAN_OPTIONS', 'UBSAN_OPTIONS')},
        virtual_address_space_limit='Not imposed by this runner',
        corpus_case_count=len(names), selected_cases=[name for name in names if name in selected],
        all_selected_cases_passed=False, full_corpus_passed=False, cases=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report['all_selected_cases_passed'] = (len(report['cases']) == len(selected) and
                                             all(case['status'] == 'passed' for case in report['cases']))
        report['full_corpus_passed'] = len(selected) == len(names) and report['all_selected_cases_passed']
        args.output.write_text(json.dumps(report, indent=2) + '\n')

    save()
    with tempfile.TemporaryDirectory(prefix='sgb-large-validation-') as directory:
        input_path = Path(directory) / 'graphs.txt'
        chosen = [(case, line) for case, line in zip(metadata['cases'], lines) if case['name'] in selected]
        input_path.write_text('\n'.join(line for _, line in chosen) + '\n')
        started = time.perf_counter()
        try:
            oracle = subprocess.run([str(reference), str(input_path)], capture_output=True, text=True,
                                    timeout=args.timeout, env=environment)
            require(oracle.returncode == 0, f'Reference exited {oracle.returncode}: {oracle.stderr}')
            check_diagnostics(oracle.stderr)
            require(not oracle.stderr, f'Unexpected reference diagnostic: {oracle.stderr}')
            truths = [json.loads(line) for line in oracle.stdout.splitlines()]
            require(len(truths) == len(chosen), 'Reference output case count differs')
            report['reference_results_sha256'] = sha256(oracle.stdout.encode())
            report['reference_elapsed_seconds'] = time.perf_counter() - started
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['reference_error'] = str(error)
            save()
            print(f'Reference validation failed: {error}', file=sys.stderr)
            return 1
        for (case, line), truth in zip(chosen, truths):
            require(truth['vertices'] == case['vertices'] and truth['edges'] == case['edges'],
                    f"{case['name']}: reference graph size differs from metadata")
            input_path.write_text(line + '\n')
            result = dict(name=case['name'], input_sha256=case['input_sha256'],
                          command=[str(args.binary), '-tf', '<single-record input>'],
                          reference={key:value for key,value in truth.items() if key != 'component_details'})
            print(f"Checking {case['name']}...", flush=True)
            started = time.perf_counter()
            try:
                process = subprocess.run([str(binary), '-tf', str(input_path)], cwd=directory,
                                         capture_output=True, text=True, timeout=args.timeout, env=environment)
                result.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
                if process.returncode != 0:
                    result['status'] = 'failed_exit_status'
                else:
                    check_diagnostics(process.stderr)
                    result['observed'] = parse_sgb(process.stdout)
                    result['comparison'] = compare(result['observed'], truth)
                    if process.stderr:
                        result['status'] = 'unexpected_stderr'
                    elif not result['comparison']['matches_reference']:
                        result['status'] = 'reference_mismatch'
                    else:
                        result['status'] = 'passed'
            except subprocess.TimeoutExpired as error:
                result.update(status='timeout_incomplete', stdout=decoded(error.stdout), stderr=decoded(error.stderr))
            except (OSError, ValueError, KeyError, TypeError) as error:
                result.update(status='failed_validation', error=str(error))
            result['elapsed_seconds'] = time.perf_counter() - started
            report['cases'].append(result)
            save()
            print(f"{case['name']}: {result['status']} ({result['elapsed_seconds']:.3f}s)", flush=True)
    save()
    print(f'Saved {args.output}', flush=True)
    return 0 if report['all_selected_cases_passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--timeout', type=positive_timeout, default=120.0)
    parser.add_argument('--case', action='append', help='Select a named case; repeat to select several (default: all)')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/performance-large/validation.json')
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    sys.exit(main())
