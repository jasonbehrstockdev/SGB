#!/usr/bin/env python3
"""Check exact CSV/debug-output compatibility on the 28 established records."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks'))
from run import check_diagnostics, parse_sgb, positive_timeout, require

CORPORA = (('benchmarks/graphs.txt', 15), ('dt_examples.txt', 8),
           ('randomexample.txt', 4), ('DJ_squareRAAG.txt', 1))
SOURCE_FILES = ('main.cpp', 'flags.h', 'input.h')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes(directory):
    return {name: digest((directory / name).read_bytes()) for name in SOURCE_FILES}


def atomic_write(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent,
                                         prefix=path.name + '.', delete=False) as output:
            temporary = Path(output.name)
            json.dump(report, output, indent=2, allow_nan=False)
            output.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def invoke(binary, path, directory, timeout):
    environment = os.environ.copy()
    environment.setdefault('ASAN_OPTIONS', 'detect_leaks=0:halt_on_error=1')
    environment.setdefault('UBSAN_OPTIONS', 'halt_on_error=1:print_stacktrace=1')
    started = time.perf_counter()
    process = subprocess.Popen([str(binary), '-tdf', str(path)], cwd=directory,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, env=environment)
    status = 'ok'
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            status = 'timeout'
            stop(process)
            stdout, stderr = process.communicate()
    except BaseException:
        stop(process)
        process.communicate()
        raise
    if status == 'ok' and process.returncode != 0:
        status = 'error'
    result = dict(status=status, returncode=process.returncode,
                  incidental_wall_seconds=time.perf_counter() - started,
                  stdout_bytes=len(stdout), stderr_bytes=len(stderr),
                  stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
    if status == 'ok':
        try:
            check_diagnostics(stderr.decode(errors='replace'))
            result['csv'] = parse_sgb(stdout.decode())
            require(b'Graph: ' in stderr and b'Square graph: ' in stderr,
                    'Missing requested verbose/debug graph output')
        except (UnicodeError, ValueError) as error:
            result.update(status='error', diagnostic=str(error))
    if result['status'] != 'ok':
        result['stderr_tail'] = stderr[-4000:].decode(errors='replace')
    return result, stdout, stderr


def run(args):
    binaries = {label: getattr(args, label).resolve() for label in ('before', 'after')}
    sources = {label: getattr(args, label + '_source').resolve() for label in binaries}
    protected = {Path(__file__).resolve(), *binaries.values(),
                 *(ROOT / name for name, _ in CORPORA),
                 *(directory / name for directory in sources.values() for name in SOURCE_FILES)}
    require(args.output.resolve() not in protected, 'Output would overwrite an input, source, or executable')
    report = dict(schema_version=1, completed=False, expected_records=28, records=[],
                  started_utc=datetime.now(timezone.utc).isoformat(),
                  method='One record per process in -tdf mode. Require valid one-row CSV and '
                         'requested graph descriptions, then compare stdout and stderr bytes '
                         'exactly. Reject execution errors, sanitizer diagnostics, and timeouts. '
                         'This is compatibility validation, not an independent mathematical '
                         'oracle or a performance measurement. Timeouts kill and reap process '
                         'groups; incomplete runs never become passing reports.',
                  timeout_seconds_per_process=args.timeout,
                  checker_sha256=digest(Path(__file__).read_bytes()),
                  validator_sha256=digest((ROOT / 'benchmarks/run.py').read_bytes()))
    # Invalidate a previous completed report before path checks or execution.
    atomic_write(args.output, report)
    try:
        for path in binaries.values():
            require(path.is_file() and os.access(path, os.X_OK), f'Not executable: {path}')
        report['binary_sha256'] = {label: digest(path.read_bytes()) for label, path in binaries.items()}
        report['source_sha256'] = {label: source_hashes(path) for label, path in sources.items()}
        report['corpus_sha256'] = {}
        records = []
        for name, expected in CORPORA:
            data = (ROOT / name).read_bytes()
            lines = data.splitlines()
            require(len(lines) == expected and all(line.strip() for line in lines),
                    f'{name}: expected {expected} nonempty records')
            report['corpus_sha256'][name] = digest(data)
            records.extend((name, number, line) for number, line in enumerate(lines, 1))
        require(len(records) == report['expected_records'], 'Missing comparison records')
        atomic_write(args.output, report)
        with tempfile.TemporaryDirectory(prefix='sgb-version-equivalence-') as temporary:
            directory = Path(temporary)
            path = directory / 'graph.txt'
            for source, number, line in records:
                path.write_bytes(line + b'\n')
                record = dict(source=source, record=number, input_sha256=digest(line),
                              passed=False, equal_stdout=False, equal_stderr=False)
                report['records'].append(record)
                outputs = {}
                for label, binary in binaries.items():
                    observation, stdout, stderr = invoke(binary, path, directory, args.timeout)
                    record[label] = observation
                    outputs[label] = (stdout, stderr)
                    atomic_write(args.output, report)
                    require(observation['status'] == 'ok',
                            f'{source}:{number} {label}: {observation["status"]}')
                record['equal_stdout'] = outputs['before'][0] == outputs['after'][0]
                record['equal_stderr'] = outputs['before'][1] == outputs['after'][1]
                require(record['equal_stdout'] and record['equal_stderr'],
                        f'{source}:{number}: output differs')
                record['passed'] = True
                atomic_write(args.output, report)
        require(report['binary_sha256'] == {label: digest(path.read_bytes())
                                            for label, path in binaries.items()}, 'Binary changed during check')
        require(report['source_sha256'] == {label: source_hashes(path)
                                            for label, path in sources.items()}, 'Source changed during check')
        require(report['corpus_sha256'] == {name: digest((ROOT / name).read_bytes())
                                            for name, _ in CORPORA}, 'Corpus changed during check')
        report['completed'] = len(report['records']) == 28 and all(record['passed'] for record in report['records'])
        require(report['completed'], 'Incomplete equivalence result')
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_write(args.output, report)
        print(f'PASS: all 28 records have identical CSV and debug output; saved {args.output}')
    except BaseException as error:
        report.update(completed=False, error_type=type(error).__name__, error=str(error))
        atomic_write(args.output, report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--before-source', type=Path, default=ROOT / 'build/performance-adaptive/before-source')
    parser.add_argument('--after-source', type=Path, default=ROOT)
    parser.add_argument('--timeout', type=positive_timeout, default=120)
    parser.add_argument('--output', type=Path, default=ROOT / 'audit/performance-adaptive-equivalence.json')
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
