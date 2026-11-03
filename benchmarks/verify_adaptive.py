#!/usr/bin/env python3
"""Audit adaptive-search artifacts without executing measured application builds."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import tempfile

from performance_large import validate_csv
from run import require, sha256
from verify_ensemble import aggregate as independent_paired_aggregate, compare


ROOT = Path(__file__).resolve().parent.parent
BEFORE = '0ebc8fe1460e278edb52fcdf183af57747718d03'
AFTER = '3797211c38ca70c52890943c5a28b5c575040d47'
MAIN_MATRIX = tuple(itertools.product((1000, 3000), (.0025, .005, .0075, .01, .0125, .015)))
DENSE_MATRIX = tuple(itertools.product((100,), (.5, .9, .98)))
SOURCE_FILES = ('main.cpp', 'flags.h', 'input.h')


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix=path.name + '.', delete=False) as output:
        temporary = Path(output.name)
        json.dump(data, output, indent=2, allow_nan=False)
        output.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def committed(commit, name):
    return subprocess.run(['git', 'show', commit + ':' + name], cwd=ROOT,
                          capture_output=True, check=True).stdout


def check_file(name, expected, verified):
    require(sha256(ROOT / name) == expected, 'Current file hash mismatch: ' + name)
    verified[name] = expected


def validate_sources(provenance, verified):
    require(provenance['before_commit'] == BEFORE and provenance['after_commit'] == AFTER,
            'Unexpected application commits')
    for label, base, commit in (('before', 'build/performance-adaptive/before-source/', BEFORE),
                                ('after', '', AFTER)):
        hashes = provenance['source_sha256'][label]
        require(set(hashes) == set(SOURCE_FILES), 'Missing application source hashes')
        for name, digest in hashes.items():
            check_file(base + name, digest, verified)
            require(hashlib.sha256(committed(commit, name)).hexdigest() == digest,
                    'Committed source mismatch: ' + commit + ':' + name)
    files = {
        'build/performance-adaptive/SGB-before': provenance['binary_sha256']['before'],
        'build/SGB': provenance['binary_sha256']['after'],
        'build/sgb-reference-large': provenance['reference_binary_sha256'],
        'benchmarks/reference_large.cpp': provenance['reference_source_sha256'],
        'benchmarks/performance_ensemble.py': provenance['runner_sha256'],
    }
    files.update({'benchmarks/' + name: digest for name, digest in provenance['imported_runner_sha256'].items()})
    for name, digest in files.items():
        check_file(name, digest, verified)


def verify_histogram(case):
    truth = case['reference']
    require((truth['vertices'], truth['edges']) == (case['vertices'], case['edges']), 'Reference size mismatch')
    rows = truth['component_histogram']
    for row in rows:
        require(all(type(row[key]) is int for key in ('support', 'squares', 'components')),
                'Noninteger histogram entry')
        require(row['components'] > 0 and row['squares'] > 0 and 4 <= row['support'] <= truth['vertices'],
                'Invalid nonempty square component')
    require(sum(row['components'] for row in rows) == truth['components'], 'Component sum mismatch')
    require(sum(row['components'] * row['squares'] for row in rows) == truth['squares'], 'Square sum mismatch')
    require(sum(row['components'] * row['support'] for row in rows) == truth['support_sum'], 'Support sum mismatch')
    require(max((row['support'] for row in rows), default=0) == truth['largest_support'], 'Largest support mismatch')
    target = truth['vertices'] - truth['universal_vertices']
    require(all(row['support'] <= target for row in rows), 'Universal vertex included in literal support')
    intended = truth['original_components'] == 1 and any(row['support'] == target for row in rows)
    require(truth['intended_cfs'] == intended, 'CFS/reference support mismatch')


def verify_paired(report, matrix, verified):
    expected_specs = [dict(name=f'er_n{n}_p{p:g}_sample{index + 1:02d}', vertices=n,
                           probability=p, sample_index=index, seed=202610300000 + n * 1000 + index)
                      for n, p in matrix for index in range(20)]
    expected_count = len(expected_specs)
    require(report['completed'] and report['expected_graphs'] == expected_count, 'Incomplete paired study')
    provenance = report['provenance']
    require(provenance['case_specs'] == expected_specs, 'Paired specification matrix mismatch')
    require(provenance['timeout_seconds'] == 120 and provenance['samples_per_group'] == 20,
            'Unexpected sample count or deadline')
    require(provenance['address_space_limit_bytes'] == 4 * 1024**3, 'Unexpected address-space budget')
    require(provenance['worker_cpus'] == [1, 2, 3] and provenance['management_cpu'] == 0,
            'Unexpected measured CPU configuration')
    validate_sources(provenance, verified)
    cases = report['cases']
    require(len(cases) == expected_count and len({case['name'] for case in cases}) == expected_count,
            'Duplicate or missing paired records')
    require(len({case['input_sha256'] for case in cases}) == expected_count, 'Duplicate paired input graphs')
    by_name = {case['name']: case for case in cases}
    counts = {label: Counter() for label in ('before', 'after')}
    paired = 0
    for spec in expected_specs:
        require(spec['name'] in by_name, 'Missing paired graph')
        case = by_name[spec['name']]
        require(all(case[key] == value for key, value in spec.items()), 'Graph specification mismatch')
        verify_histogram(case)
        require(case['execution_order'] == (['before', 'after'] if case['sample_index'] % 2 == 0
                                           else ['after', 'before']), 'Wrong paired execution order')
        require(case['cpu'] in provenance['worker_cpus'], 'Unexpected worker CPU')
        require(case['started_utc'] < case['finished_utc'], 'Invalid case timestamps')
        for label in counts:
            item = case[label]
            require(item['status'] in ('ok', 'timeout') and not item['stderr'], 'Execution/diagnostic failure')
            require(math.isfinite(item['wall_seconds']) and item['wall_seconds'] > 0, 'Invalid measured time')
            counts[label][item['status']] += 1
            if item['status'] == 'ok':
                require(item['returncode'] == 0 and item['validated'], 'Invalid successful-run flags')
                validate_csv(item['stdout'], case['reference'])
            else:
                require(item['returncode'] == -9 and not item['validated'] and item['wall_seconds'] >= 120,
                        'Invalid timeout flags or deadline')
        complete_pair = all(case[label]['status'] == 'ok' for label in counts)
        if complete_pair:
            require(case['paired_csv_identical'] and case['before']['stdout'] == case['after']['stdout'],
                    'Paired output mismatch')
            paired += 1
        else:
            require(case['paired_csv_identical'] is None, 'Incomplete pair marked identical')
    groups = [independent_paired_aggregate([case for case in cases
              if (case['vertices'], case['probability']) == (n, p)], 120) for n, p in matrix]
    require(len(report['groups']) == len(groups), 'Wrong paired group count')
    for expected, recorded in zip(groups, report['groups']):
        compare(expected, recorded, 'independent paired group')
    require(report['all_completed_outputs_validated'] and report['execution_or_validation_failures'] == 0,
            'Incorrect paired completion flags')
    require(report['all_optimized_cases_validated'] == (counts['after']['ok'] == expected_count),
            'Incorrect optimized completion flag')
    for cpu in provenance['worker_cpus']:
        ordered = sorted((case for case in cases if case['cpu'] == cpu), key=lambda case: case['started_utc'])
        require(all(a['finished_utc'] <= b['started_utc'] for a, b in zip(ordered, ordered[1:])),
                'Overlapping paired runs on one worker')
    return dict(graphs=expected_count, counts={label: dict(value) for label, value in counts.items()},
                completed_pairs=paired, independent_groups=groups)


def verify_main_inputs(report):
    raw = committed(BEFORE, 'audit/performance-ensemble-results.json')
    prior = json.loads(raw)
    verification_raw = committed(BEFORE, 'audit/performance-ensemble-validation.json')
    verification = json.loads(verification_raw)
    require(verification['completed'] and all(verification['checks'].values()), 'Historical corpus was not verified')
    require(verification['raw_report_sha256'] == hashlib.sha256(raw).hexdigest(), 'Historical corpus hash mismatch')
    indexed = {case['name']: case for case in prior['cases']}
    regenerated = {case['name']: case for case in verification['regenerated_inputs']}
    require(len(indexed) == len(regenerated) == len(report['cases']) == 240, 'Historical matrix mismatch')
    for case in report['cases']:
        old, evidence = indexed[case['name']], regenerated[case['name']]
        for key in ('vertices', 'probability', 'sample_index', 'seed', 'edges', 'actual_density',
                    'average_degree', 'input_sha256', 'reference'):
            require(case[key] == old[key], 'Historical input/reference mismatch: ' + case['name'] + ':' + key)
        require(case['input_sha256'] == evidence['input_sha256'] and case['edges'] == evidence['edges'],
                'Historical independently regenerated input mismatch')
    return dict(method='Matched all 240 inputs and references against the committed prior corpus and its '
                       'independently regenerated input hashes; no graph-generation or mathematical analysis rerun.',
                commit=BEFORE, historical_raw_sha256=hashlib.sha256(raw).hexdigest(),
                historical_verification_sha256=hashlib.sha256(verification_raw).hexdigest(), inputs=240)


def regenerate_dense(report):
    indexed = {(case['vertices'], case['probability'], case['sample_index']): case for case in report['cases']}
    evidence = []
    for index in range(20):
        n = 100
        rng = random.Random(202610300000 + n * 1000 + index)
        edges = {p: [] for p in (.5, .9, .98)}
        for a, b in itertools.combinations(range(1, n + 1), 2):
            draw = rng.random()
            for p, values in edges.items():
                if draw < p:
                    values.append(f'({a},{b})')
        labels = '[' + ','.join(map(str, range(1, n + 1))) + '] '
        for p, values in edges.items():
            case = indexed[n, p, index]
            digest = hashlib.sha256((labels + '[' + ','.join(values) + ']').encode()).hexdigest()
            require(case['input_sha256'] == digest and case['edges'] == len(values), 'Dense input regeneration mismatch')
            require(case['actual_density'] == 2 * len(values) / (n * (n - 1)), 'Dense density mismatch')
            require(case['average_degree'] == 2 * len(values) / n, 'Dense average-degree mismatch')
            evidence.append(dict(name=case['name'], input_sha256=digest, edges=len(values)))
    return evidence


def independent_scaling_groups(cases):
    groups = []
    for family in ('fixed_alpha', 'fixed_complement_degree'):
        previous = None
        for n in (250, 500, 1000, 2000):
            members = [case for case in cases if (case['family'], case['vertices']) == (family, n)]
            observed = [case['observation'] for case in members]
            work = [row['wedge_visits'] + row['wedge_pairs'] + row['missing_edge_pairs'] for row in observed]
            times = [row['search_seconds'] for row in observed]
            squares = [row['squares'] for row in observed]
            group = dict(family=family, vertices=n, graphs=len(members), completed=len(members), outcomes={'ok': len(members)},
                         strategies=dict(Counter(row['strategy'] for row in observed)),
                         search_seconds_median=statistics.median(times), enumeration_checks_median=statistics.median(work),
                         enumeration_checks_per_n_squared_median=statistics.median(work) / n**2,
                         squares_median=statistics.median(squares), squares_per_n_squared_median=statistics.median(squares) / n**2,
                         search_seconds_range=[min(times), max(times)])
            if previous is not None:
                group['previous_vertices'] = previous['vertices']
                group['vertex_ratio'] = n / previous['vertices']
                for key in ('enumeration_checks_median', 'search_seconds_median', 'squares_median'):
                    group[key + '_ratio'] = group[key] / previous[key] if previous[key] else None
            groups.append(group)
            previous = group
    return groups


def verify_scaling(report, main, verified):
    require(report['completed'] and report['all_cases_validated'] and report['expected_graphs'] == 160,
            'Incomplete scaling experiment')
    provenance = report['provenance']
    require(provenance['application_commit'] == AFTER, 'Scaling application commit mismatch')
    require(provenance['source_sha256'] == main['provenance']['source_sha256']['after'], 'Scaling application source mismatch')
    require(provenance['parameters'] == dict(alpha=.5, complement_mean_degree=2,
                                           vertices=[250, 500, 1000, 2000], samples_per_group=20), 'Scaling parameters mismatch')
    require(provenance['timeout_seconds'] == 120 and provenance['address_space_limit_bytes'] == 4 * 1024**3,
            'Scaling resource budgets mismatch')
    require(provenance['cpu'] == 1 and provenance['management_cpu'] == 0, 'Scaling CPU assignments mismatch')
    files = {'build/adaptive-scaling': provenance['harness_binary_sha256'],
             'benchmarks/adaptive_scaling.cpp': provenance['harness_source_sha256'],
             'benchmarks/adaptive_scaling.py': provenance['runner_sha256']}
    files.update({'benchmarks/' + name: digest for name, digest in provenance['imported_helper_sha256'].items()})
    for name, digest in files.items():
        check_file(name, digest, verified)
    expected_specs = []
    for family, offset in (('fixed_alpha', 0), ('fixed_complement_degree', 100000000)):
        for n in (250, 500, 1000, 2000):
            probability = .5 / math.sqrt(n) if family == 'fixed_alpha' else 2 / (n - 1)
            for index in range(20):
                expected_specs.append(dict(name=f'{family}_n{n}_sample{index + 1:02d}', family=family,
                    vertices=n, sample_index=index, seed=202611020000 + offset + n * 1000 + index,
                    listed_probability=probability, probability=probability if family == 'fixed_alpha' else 1 - probability))
    require(provenance['case_specs'] == expected_specs, 'Scaling specification matrix mismatch')
    cases = report['cases']
    require(len(cases) == len({case['name'] for case in cases}) == len({case['input_sha256'] for case in cases}) == 160,
            'Duplicate or missing scaling cases')
    indexed = {case['name']: case for case in cases}
    regenerated = []
    for spec in expected_specs:
        case = indexed[spec['name']]
        require(all(case[key] == value for key, value in spec.items()), 'Scaling case/specification mismatch')
        require(case['status'] == 'ok' and case['validated'] and case['returncode'] == 0 and not case['stderr'],
                'Scaling execution/validation failure')
        n = case['vertices']
        rng = random.Random(case['seed'])
        listed = [(a, b) for a, b in itertools.combinations(range(n), 2) if rng.random() < case['listed_probability']]
        complement = case['family'] == 'fixed_complement_degree'
        data = (f'{n} {int(complement)}\n' + ''.join(f'{a} {b}\n' for a, b in listed)).encode()
        pairs = n * (n - 1) // 2
        edges = pairs - len(listed) if complement else len(listed)
        require(case['input_sha256'] == hashlib.sha256(data).hexdigest() and case['input_bytes'] == len(data),
                'Scaling input regeneration mismatch')
        require(case['listed_pairs'] == len(listed) and case['input_is_complement'] == complement and case['edges'] == edges,
                'Scaling edge metadata mismatch')
        require(case['actual_density'] == edges / pairs, 'Scaling density mismatch')
        observed = case['observation']
        for key in ('vertices', 'edges', 'listed_pairs', 'input_is_complement'):
            require(observed[key] == case[key], 'Scaling input/observation mismatch: ' + key)
        require(observed['squares'] == case['expected_squares'] and observed['every_square_valid_and_unique'],
                'Scaling square-oracle validation flag/count mismatch')
        require(0 <= observed['squares'] <= math.comb(n, 4), 'Impossible scaling square count')
        for key in ('active_vertices', 'nonedges', 'wedge_visits', 'wedge_pairs', 'missing_edge_pairs', 'squares', 'radix_passes'):
            require(type(observed[key]) is int and observed[key] >= 0, 'Invalid scaling counter: ' + key)
        require(observed['nonedges'] == pairs - edges, 'Scaling missing-edge count mismatch')
        degree = [0] * n
        for a, b in listed:
            degree[a] += 1
            degree[b] += 1
        original_degree = [n - 1 - value for value in degree] if complement else degree
        active = [vertex for vertex in range(n) if original_degree[vertex] != n - 1]
        active_set = set(active)
        if complement:
            lower_missing = [0] * n
            for a, b in listed:
                lower_missing[b] += 1
            wedge_work = sum((len(active) - 1 - degree[v]) * (index - lower_missing[v])
                             for index, v in enumerate(active))
        else:
            active_edges = [(a, b) for a, b in listed if a in active_set and b in active_set]
            active_degree = [0] * n
            for a, b in active_edges:
                active_degree[a] += 1
                active_degree[b] += 1
            wedge_work = sum(active_degree[b] for a, b in active_edges)
        missing = pairs - edges
        missing_work = len(active) * (len(active) - 1) // 2 + 2 * missing * (missing - 1)
        expected_strategy = 'missing_edges' if missing_work < wedge_work else 'wedges'
        require(observed['strategy'] == expected_strategy and observed['active_vertices'] == len(active),
                'Adaptive strategy/input-metric mismatch')
        require(observed['estimated_wedge_work'] == wedge_work and observed['estimated_missing_edge_work'] == missing_work,
                'Adaptive work-estimate mismatch')
        if len(active) >= 4 and missing >= 2 and wedge_work > 0:
            if expected_strategy == 'wedges':
                require(observed['wedge_visits'] == wedge_work and observed['missing_edge_pairs'] == 0,
                        'Scaling wedge-work counter mismatch')
                require(observed['wedge_pairs'] >= observed['squares'], 'Too few wedge candidates')
            else:
                require(observed['missing_edge_pairs'] == missing * (missing - 1) // 2 and
                        observed['wedge_visits'] == observed['wedge_pairs'] == 0, 'Scaling complement-work counter mismatch')
        require(observed['radix_passes'] == (4 if observed['squares'] >= 2 else 0), 'Ordering counter mismatch')
        for key in ('search_seconds', 'construction_seconds', 'validation_seconds'):
            require(math.isfinite(observed[key]) and observed[key] >= 0, 'Invalid scaling interval')
        require(math.isfinite(case['process_wall_seconds']) and case['process_wall_seconds'] > 0,
                'Invalid scaling process wall time')
        regenerated.append(dict(name=case['name'], input_sha256=case['input_sha256'],
                                listed_pairs=len(listed), selected_strategy=expected_strategy))
    groups = independent_scaling_groups(cases)
    require(len(report['groups']) == len(groups) == 8, 'Scaling group count mismatch')
    for expected, recorded in zip(groups, report['groups']):
        require(expected['graphs'] == 20, 'Scaling group does not contain 20 graphs')
        compare(expected, recorded, 'independent scaling group')
    return dict(graphs=160, completed=160, regenerated_inputs=regenerated, independent_groups=groups,
                square_validation='Verified the recorded independent count-oracle and per-square validity/uniqueness '
                                  'results; this artifact verifier does not rerun mathematical square analysis.')


def verify_equivalence(report, main, verified):
    require(report['completed'] and report['expected_records'] == len(report['records']) == 28,
            'Incomplete output-equivalence report')
    require(report['binary_sha256'] == main['provenance']['binary_sha256'] and
            report['source_sha256'] == main['provenance']['source_sha256'], 'Equivalence/application provenance mismatch')
    check_file('tests/compare_versions.py', report['checker_sha256'], verified)
    check_file('benchmarks/run.py', report['validator_sha256'], verified)
    sources = {'benchmarks/graphs.txt': 15, 'dt_examples.txt': 8, 'randomexample.txt': 4, 'DJ_squareRAAG.txt': 1}
    require(set(report['corpus_sha256']) == set(sources), 'Wrong equivalence corpora')
    indexed = {(record['source'], record['record']): record for record in report['records']}
    require(len(indexed) == 28, 'Duplicate equivalence record')
    for name, count in sources.items():
        check_file(name, report['corpus_sha256'][name], verified)
        lines = (ROOT / name).read_bytes().splitlines()
        require(len(lines) == count, 'Equivalence corpus size mismatch')
        for number, line in enumerate(lines, 1):
            record = indexed[name, number]
            require(record['input_sha256'] == hashlib.sha256(line).hexdigest() and record['passed'] and
                    record['equal_stdout'] and record['equal_stderr'], 'Equivalence input/output flags mismatch')
            for label in ('before', 'after'):
                require(record[label]['status'] == 'ok' and record[label]['returncode'] == 0, 'Equivalence process failed')
            for key in ('stdout_sha256', 'stderr_sha256', 'stdout_bytes', 'stderr_bytes', 'csv'):
                require(record['before'][key] == record['after'][key], 'Equivalence digest/size mismatch')
    return dict(records=28, exact_stdout_and_stderr=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main-report', type=Path, default=ROOT / 'audit/performance-adaptive-results.json')
    parser.add_argument('--dense-report', type=Path, default=ROOT / 'audit/performance-adaptive-dense-results.json')
    parser.add_argument('--scaling-report', type=Path, default=ROOT / 'audit/performance-adaptive-scaling.json')
    parser.add_argument('--equivalence-report', type=Path, default=ROOT / 'audit/performance-adaptive-equivalence.json')
    parser.add_argument('--test-log', type=Path, default=ROOT / 'build/performance-adaptive/preflight.log')
    parser.add_argument('--output', type=Path, default=ROOT / 'audit/performance-adaptive-validation.json')
    args = parser.parse_args()
    paths = dict(main=args.main_report, dense=args.dense_report, scaling=args.scaling_report,
                 equivalence=args.equivalence_report)
    protected = {path.resolve() for path in (*paths.values(), args.test_log, Path(__file__),
        ROOT / 'build/SGB', ROOT / 'build/performance-adaptive/SGB-before',
        *(ROOT / name for name in SOURCE_FILES))}
    require(args.output.resolve() not in protected, 'Validation output would overwrite an input or executable')
    validation = dict(schema_version=1, completed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                      verifier_sha256=sha256(Path(__file__)), method=
                      'No application timings or mathematical square analyses are rerun. The 240 main inputs are '
                      'anchored to the committed independently regenerated prior corpus; 60 dense and 160 compact '
                      'scaling inputs are independently regenerated. Completed CSV outputs, reference histograms, '
                      'source/binary provenance, execution flags, and output-equivalence records are rechecked. '
                      'Paired quantiles/speedups and scaling summaries are independently recomputed with statistics. '
                      'Scaling input degrees independently check strategy estimates and applicable operation counters.')
    atomic_write(args.output, validation)
    try:
        raw_hashes = {name: sha256(path) for name, path in paths.items()}
        reports = {name: json.loads(path.read_text()) for name, path in paths.items()}
        require(all(report.get('completed') for report in reports.values()), 'A required experiment is incomplete')
        verified = {}
        validation['main'] = verify_paired(reports['main'], MAIN_MATRIX, verified)
        validation['main']['input_verification'] = verify_main_inputs(reports['main'])
        validation['dense'] = verify_paired(reports['dense'], DENSE_MATRIX, verified)
        for key in ('before_commit', 'after_commit', 'source_sha256', 'binary_sha256', 'compiler_version',
                    'compiler_flags', 'boost_version', 'reference_binary_sha256', 'reference_source_sha256',
                    'runner_sha256', 'imported_runner_sha256'):
            require(reports['dense']['provenance'][key] == reports['main']['provenance'][key], 'Dense/main provenance mismatch')
        require(len({case['input_sha256'] for label in ('main', 'dense') for case in reports[label]['cases']}) == 300,
                'Cross-study duplicate input')
        validation['dense']['regenerated_inputs'] = regenerate_dense(reports['dense'])
        validation['scaling'] = verify_scaling(reports['scaling'], reports['main'], verified)
        validation['equivalence'] = verify_equivalence(reports['equivalence'], reports['main'], verified)
        log = args.test_log.read_text()
        require(log.count('PASS: 75 structural analyses') == 2 and
                '108 forced strategy/adjacency checks' in log and 'SGB-sanitize' in log,
                'Missing normal/sanitizer structural test evidence')
        require('FAILED' not in log and 'make: ***' not in log and 'AddressSanitizer:' not in log,
                'Failure diagnostic in preflight log')
        validation['preflight_tests'] = dict(
            command='make CPPFLAGS=-I/tmp/sgb-boost/usr/include check check-sanitize build/adaptive-scaling',
            exit_code=0, evidence='The parent task recorded exit 0 from exec session 24802; this verifier '
                                  'checks the saved log and does not rerun the test command.',
            log_sha256=sha256(args.test_log), structural_cases=75, forced_strategy_adjacency_checks=108,
            normal_and_sanitizer_runs=True)
        for name, path in paths.items():
            require(sha256(path) == raw_hashes[name], 'Report changed during artifact validation')
        validation.update(completed=True, finished_utc=datetime.now(timezone.utc).isoformat(),
                          report_sha256=raw_hashes, verified_files_sha256=verified,
                          verifier_helper_sha256={name: sha256(ROOT / 'benchmarks' / name)
                                                 for name in ('verify_ensemble.py', 'performance_large.py', 'run.py')},
                          checks=dict(twenty_graphs_per_group=True, all_input_hashes_verified=True,
                                      current_and_committed_sources=True, binaries_and_helpers=True,
                                      completed_csv_and_reference_histograms=True, timeout_classification=True,
                                      independent_paired_statistics=True, independent_scaling_statistics=True,
                                      scaling_strategy_and_counter_consistency=True, exact_output_equivalence=True,
                                      preflight_log_evidence=True))
        atomic_write(args.output, validation)
        print(f'PASS: 300 paired graph inputs, 160 scaling inputs, 28 exact-output records and all summaries: {args.output}')
    except BaseException as error:
        validation.update(completed=False, error_type=type(error).__name__, error=str(error))
        atomic_write(args.output, validation)
        raise


if __name__ == '__main__':
    main()
