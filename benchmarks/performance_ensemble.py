#!/usr/bin/env python3
"""Paired timings on distinct deterministic G(n,p) graphs, retaining censoring."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import signal
import statistics
import subprocess
import sys
import tempfile

from performance import environment, positive_integer, source_hashes
from performance_large import bounded_run, compact_reference, validate_csv
from run import positive_timeout, require, sha256

ROOT = Path(__file__).resolve().parent
DEFAULT_VERTICES = (1000, 3000)
DEFAULT_PROBABILITIES = (.0025, .005, .0075, .01, .0125, .015)
WORKER = None


def make_cases(samples=20, vertices=DEFAULT_VERTICES, probabilities=DEFAULT_PROBABILITIES):
    """Distinct seeds within each group; same seed across p gives nested graphs."""
    require(samples > 0, 'Sample count must be positive')
    require(len(set(vertices)) == len(vertices), 'Duplicate vertex counts')
    require(len(set(probabilities)) == len(probabilities), 'Duplicate probabilities')
    cases = []
    for n in vertices:
        require(n > 1, 'At least two vertices are required')
        for probability in probabilities:
            require(0 < probability < 1, 'Probability must lie strictly between zero and one')
            for index in range(samples):
                seed = 202610300000 + n * 1000 + index
                cases.append(dict(name=f'er_n{n}_p{probability:g}_sample{index + 1:02d}',
                                  vertices=n, probability=probability, sample_index=index,
                                  seed=seed))
    return cases


def generate_case(case):
    """Generate lexicographic Bernoulli edges and an exact one-line input record."""
    n, probability = case['vertices'], case['probability']
    rng = random.Random(case['seed'])
    edges = [(a, b) for a in range(n) for b in range(a + 1, n)
             if rng.random() < probability]
    line = '[' + ','.join(str(vertex + 1) for vertex in range(n)) + '] ['
    line += ','.join(f'({a + 1},{b + 1})' for a, b in edges) + ']'
    metadata = dict(case, edges=len(edges), actual_density=2 * len(edges) / (n * (n - 1)),
                    average_degree=2 * len(edges) / n,
                    input_sha256=hashlib.sha256(line.encode()).hexdigest())
    return line, metadata


def linear_quantile(values, q):
    require(bool(values), 'Cannot compute a quantile of an empty sequence')
    require(0 <= q <= 1, 'Quantile must lie between zero and one')
    values = sorted(values)
    position = (len(values) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    fraction = position - lower
    if lower == upper:
        return values[lower]
    if math.isinf(values[upper]):
        return math.inf
    return values[lower] + fraction * (values[upper] - values[lower])


def censored_quantile(observations, q, timeout):
    """Type-7 quantile interval for exact times and right-censored timeouts.

    A timeout's unobserved completion time is strictly greater than its budget.
    Do not use time spent killing/reaping it as a completed run time. Other
    execution failures have no defensible time interval and invalidate quantiles.
    """
    if not observations or any(item['status'] not in ('ok', 'timeout') or
                               (item['status'] == 'ok' and not item.get('validated', False))
                               for item in observations):
        return dict(kind='unavailable', seconds=None)
    bounds = sorted((item['wall_seconds'], False) if item['status'] == 'ok'
                    else (timeout, True) for item in observations)
    lower = linear_quantile([item[0] for item in bounds], q)
    upper = linear_quantile([item['wall_seconds'] if item['status'] == 'ok' else math.inf
                             for item in observations], q)
    if lower == upper:
        return dict(kind='exact', seconds=lower)
    position = (len(bounds) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    strict = bounds[lo][1] if lo == hi else bounds[lo][1] or bounds[hi][1]
    return dict(kind='lower_bound', seconds=lower, strict=strict)


def summarize_observations(observations, timeout):
    observations = [dict(item, status='error') if item['status'] == 'ok' and not item.get('validated', False)
                    else item for item in observations]
    counts = {key: sum(item['status'] == key for item in observations)
              for key in ('ok', 'timeout', 'allocation_failure_under_cap', 'error')}
    counts['other'] = len(observations) - sum(counts.values())
    successful = [item['wall_seconds'] for item in observations if item['status'] == 'ok']
    complete = None
    if successful:
        complete = dict(median_seconds=statistics.median(successful),
                        p25_seconds=linear_quantile(successful, .25),
                        p75_seconds=linear_quantile(successful, .75),
                        min_seconds=min(successful), max_seconds=max(successful))
    return dict(counts=counts, completed_only=complete,
                quantiles={name: censored_quantile(observations, q, timeout)
                           for name, q in (('p25', .25), ('median', .5), ('p75', .75))})


def aggregate_cases(cases, timeout):
    groups = []
    for n, probability in sorted({(case['vertices'], case['probability']) for case in cases}):
        members = [case for case in cases if (case['vertices'], case['probability']) == (n, probability)]
        group = dict(vertices=n, probability=probability, graphs=len(members))
        for label in ('before', 'after'):
            group[label] = summarize_observations([case[label] for case in members], timeout)
        pairs = [case for case in members if all(case[label]['status'] == 'ok' and
                 case[label].get('validated', False) for label in ('before', 'after'))]
        ratios = [case['before']['wall_seconds'] / case['after']['wall_seconds'] for case in pairs]
        group['paired_complete_count'] = len(pairs)
        group['paired_speedup'] = (dict(median=statistics.median(ratios),
                                       geomean=math.exp(statistics.mean(math.log(value) for value in ratios)),
                                       min=min(ratios), max=max(ratios)) if ratios else None)
        bm, am = (group[label]['quantiles']['median'] for label in ('before', 'after'))
        group['ratio_of_full_sample_medians'] = (bm['seconds'] / am['seconds']
                                                if bm['kind'] == am['kind'] == 'exact' else None)
        groups.append(group)
    return groups


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def provenance_equal(expected, actual):
    return canonical_hash(expected) == canonical_hash(actual)


def resume_report(path, provenance):
    report = json.loads(Path(path).read_text())
    require(provenance_equal(provenance, report.get('provenance')), 'Resume provenance mismatch')
    expected_cases = {case['name']: case for case in provenance['case_specs']}
    seen_names, seen_inputs = set(), set()
    for case in report['cases']:
        require(case['name'] in expected_cases and case['name'] not in seen_names,
                'Unknown or duplicated case in resume checkpoint')
        spec = expected_cases[case['name']]
        require(all(case.get(key) == value for key, value in spec.items()), 'Resume case specification mismatch')
        _, metadata = generate_case(spec)
        require(all(case.get(key) == value for key, value in metadata.items()), 'Resume input hash/metadata mismatch')
        require(case['input_sha256'] not in seen_inputs, 'Duplicate graph in resume checkpoint')
        require(all(label in case for label in ('before', 'after')), 'Incomplete case in resume checkpoint')
        seen_names.add(case['name'])
        seen_inputs.add(case['input_sha256'])
    return report


def atomic_write(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as output:
        temporary = Path(output.name)
        json.dump(report, output, indent=2, allow_nan=False)
        output.write('\n')
    os.replace(temporary, path)


def terminate_worker(signum, frame):
    # Pool.terminate() must unwind bounded_run so its child process group is reaped.
    raise SystemExit(128 + signum)


def worker_init(cpu_queue, settings):
    global WORKER
    signal.signal(signal.SIGTERM, terminate_worker)
    cpu = cpu_queue.get()
    os.sched_setaffinity(0, {cpu})
    WORKER = dict(settings, cpu=cpu)


def measure_case(case):
    settings = WORKER
    line, result = generate_case(case)
    result.update(cpu=settings['cpu'], started_utc=datetime.now(timezone.utc).isoformat())
    order = ['before', 'after'] if case['sample_index'] % 2 == 0 else ['after', 'before']
    result['execution_order'] = order
    with tempfile.TemporaryDirectory(prefix='sgb-ensemble-') as directory:
        path = Path(directory) / 'graph.txt'
        path.write_text(line + '\n')
        reference_run = bounded_run([settings['reference'], str(path)], settings['timeout'], settings['memory_bytes'])
        require(reference_run['status'] == 'ok', f"{case['name']}: reference failed: {reference_run}")
        truths = [json.loads(record) for record in reference_run['stdout'].splitlines()]
        require(len(truths) == 1, f"{case['name']}: expected exactly one reference record")
        truth = truths[0]
        require(truth['vertices'] == result['vertices'] and truth['edges'] == result['edges'],
                f"{case['name']}: reference/input size mismatch")
        result['reference'] = compact_reference(truth)
        result['reference_wall_seconds'] = reference_run['wall_seconds']
        result['reference_stdout_sha256'] = hashlib.sha256(reference_run['stdout'].encode()).hexdigest()
        expected_output = None
        for label in order:
            observation = bounded_run([settings[label], '-tf', str(path)], settings['timeout'], settings['memory_bytes'])
            observation['validated'] = False
            if observation['status'] == 'ok':
                try:
                    validate_csv(observation['stdout'], truth)
                    if expected_output is not None:
                        require(observation['stdout'] == expected_output, 'Before/after CSV mismatch')
                    expected_output = observation['stdout']
                    observation['validated'] = True
                except (ValueError, KeyError, TypeError) as error:
                    observation['status'] = 'error'
                    observation['validation_error'] = str(error)
            result[label] = observation
        result['paired_csv_identical'] = (result['before']['stdout'] == result['after']['stdout']
                                         if all(result[label]['status'] == 'ok' for label in order) else None)
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    return result


def verify_cpu_selection(cpus, management_cpu):
    allowed = os.sched_getaffinity(0)
    require(len(cpus) == len(set(cpus)) and bool(cpus), 'Worker CPUs must be distinct')
    require(set(cpus) <= allowed and management_cpu in allowed, 'CPU not in allowed affinity')
    require(management_cpu not in cpus, 'Management CPU must not be a worker CPU')
    cores = []
    for cpu in cpus:
        topology = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        package, core = topology / 'physical_package_id', topology / 'core_id'
        require(package.exists() and core.exists(), 'Cannot verify distinct physical CPU cores')
        cores.append((package.read_text().strip(), core.read_text().strip()))
    require(len(set(cores)) == len(cpus), 'Worker CPUs share a physical core')


def make_provenance(args, cases):
    return dict(case_specs=cases, samples_per_group=args.samples,
                generator='Python random.Random(seed).random(), one call for every lexicographic unordered a<b pair; edge iff draw<p. '
                          'Seeds are 202610300000+n*1000+sample_index. Same seed at different densities produces nested graphs.',
                case_execution_seed=20261030, timeout_seconds=args.timeout,
                address_space_limit_bytes=args.memory_gib * 1024 ** 3, worker_cpus=args.cpus,
                management_cpu=args.management_cpu, environment=environment(),
                before_commit=args.before_commit, after_commit=args.after_commit,
                compiler_version=subprocess.run([args.compiler, '--version'], text=True, capture_output=True,
                                                check=True).stdout.splitlines()[0],
                compiler_flags=args.compiler_flags, boost_version=args.boost_version,
                source_sha256=dict(before=source_hashes(args.before_source), after=source_hashes(args.after_source)),
                binary_sha256=dict(before=sha256(args.before), after=sha256(args.after)),
                reference_binary_sha256=sha256(args.reference),
                reference_source_sha256=sha256(ROOT / 'reference_large.cpp'),
                runner_sha256=sha256(Path(__file__)),
                imported_runner_sha256={name: sha256(ROOT / name) for name in ('performance_large.py', 'performance.py', 'run.py')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--before-source', required=True, type=Path)
    parser.add_argument('--after-source', type=Path, default=ROOT.parent)
    parser.add_argument('--before-commit', default='cbdb90fb17186288f6a77944f2ee84dee2c4f230')
    parser.add_argument('--after-commit', required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--compiler-flags', default='-O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror')
    parser.add_argument('--boost-version', required=True)
    parser.add_argument('--samples', type=positive_integer, default=20)
    parser.add_argument('--vertices', type=positive_integer, nargs='+', default=list(DEFAULT_VERTICES))
    parser.add_argument('--probabilities', type=float, nargs='+', default=list(DEFAULT_PROBABILITIES))
    parser.add_argument('--timeout', type=positive_timeout, default=120)
    parser.add_argument('--memory-gib', type=positive_integer, default=4)
    parser.add_argument('--cpus', type=int, nargs='+', default=[1, 2, 3])
    parser.add_argument('--management-cpu', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--export-inputs', type=Path, help='Write exact input records after checking provenance; optional')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'audit/performance-ensemble-results.json')
    args = parser.parse_args()
    original_affinity = os.sched_getaffinity(0)
    try:
        cases = make_cases(args.samples, tuple(args.vertices), tuple(args.probabilities))
        verify_cpu_selection(args.cpus, args.management_cpu)
        for key in ('before', 'after', 'reference'):
            path = getattr(args, key).resolve()
            require(path.is_file() and os.access(path, os.X_OK), f'Not executable: {path}')
            setattr(args, key, path)
        provenance = make_provenance(args, cases)
        if args.resume:
            report = resume_report(args.output, provenance)
        else:
            report = dict(schema_version=1, completed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                          provenance=provenance, command=[sys.executable, *sys.argv], cases=[], groups=[])
        report.update(completed=False, all_completed_outputs_validated=False, all_optimized_cases_validated=False,
                      expected_graphs=len(cases), methodology=
                      'One fresh-process timing per build on each distinct graph, with the same input file used for both. '
                      f'{(args.samples + 1) // 2} before-first and {args.samples // 2} after-first graphs per '
                      f'{args.samples}-sample group. Graphs are shuffled deterministically; '
                      f'{len(args.cpus)} worker processes run on distinct pinned physical cores, each completing its reference check and '
                      'paired application runs sequentially. Other workers share machine resources. No per-graph warmup or '
                      'within-graph repetitions. Wall time includes launch, parsing, analysis, output, cleanup, and limit setup. '
                      'Reference generation and checking are outside each application timing. Successful outputs must agree with '
                      'the independent reference and completed pairs must have byte-identical CSV. Timeouts remain censored: '
                      'they are not successful outputs, negative CFS results, or observed completion times. Group quantiles '
                      'use linear interpolation at (N-1)q, with intervals for right-censored observations. Complete-pair '
                      'speedup statistics exclude censored pairs and may be selection-biased. Source/binary hashes and exact '
                      'deterministic input hashes are retained. No claim of exclusive physical host access is made.')
        report.pop('finished_utc', None)
        atomic_write(args.output, report)
        if args.export_inputs:
            args.export_inputs.parent.mkdir(parents=True, exist_ok=True)
            with args.export_inputs.open('w') as output:
                for case in cases:
                    line, _ = generate_case(case)
                    output.write(line + '\n')
        finished = {case['name'] for case in report['cases']}
        pending = [case for case in cases if case['name'] not in finished]
        random.Random(20261030).shuffle(pending)
        settings = {label: str(getattr(args, label)) for label in ('before', 'after', 'reference')}
        settings.update(timeout=args.timeout, memory_bytes=args.memory_gib * 1024 ** 3)
        os.sched_setaffinity(0, {args.management_cpu})
        context = multiprocessing.get_context('spawn')
        cpu_queue = context.Queue()
        for cpu in args.cpus:
            cpu_queue.put(cpu)
        if pending:
            with context.Pool(len(args.cpus), initializer=worker_init, initargs=(cpu_queue, settings)) as pool:
                for result in pool.imap_unordered(measure_case, pending, chunksize=1):
                    require(result['input_sha256'] not in {case['input_sha256'] for case in report['cases']},
                            'Two cases generated the same graph')
                    report['cases'].append(result)
                    report['cases'].sort(key=lambda case: (case['vertices'], case['probability'], case['sample_index']))
                    report['groups'] = aggregate_cases(report['cases'], args.timeout)
                    atomic_write(args.output, report)
                    times = ' '.join(f"{label}={result[label]['status']}:{result[label]['wall_seconds']:.3f}s"
                                     for label in ('before', 'after'))
                    print(f"{len(report['cases'])}/{len(cases)} cpu={result['cpu']} {result['name']} {times}", flush=True)
        os.sched_setaffinity(0, original_affinity)
        require(provenance_equal(provenance, make_provenance(args, cases)), 'Code, binary, or environment changed during run')
        require(len(report['cases']) == len(cases), 'Missing graph results')
        report['completed'] = True
        report['all_completed_outputs_validated'] = all(case[label]['validated']
            for case in report['cases'] for label in ('before', 'after') if case[label]['status'] == 'ok')
        report['all_optimized_cases_validated'] = all(case['after']['status'] == 'ok' and case['after']['validated']
                                                     for case in report['cases'])
        report['execution_or_validation_failures'] = sum(case[label]['status'] not in ('ok', 'timeout')
            for case in report['cases'] for label in ('before', 'after'))
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_write(args.output, report)
        require(report['execution_or_validation_failures'] == 0, 'Some runs failed execution or correctness validation')
        print(f'Completed {len(cases)} paired graphs; results: {args.output}', flush=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    finally:
        os.sched_setaffinity(0, original_affinity)


if __name__ == '__main__':
    main()
