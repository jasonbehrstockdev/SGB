#!/usr/bin/env python3
"""Audit a completed ensemble artifact without rerunning application timings."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import xml.etree.ElementTree as ET

from performance_large import validate_csv
from run import require, sha256


ROOT = Path(__file__).resolve().parent.parent
SIZES = (1000, 3000)
DENSITIES = (.0025, .005, .0075, .01, .0125, .015)


def compare(left, right, context):
    """Allow only floating-point evaluation-order differences in recomputation."""
    if isinstance(left, dict):
        require(left.keys() == right.keys(), context + ': different keys')
        for key in left:
            compare(left[key], right[key], context + '.' + key)
    elif isinstance(left, float):
        require(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), context + ': unequal numbers')
    else:
        require(left == right, context + ': unequal values')


def quantiles(observations, timeout):
    """Independently calculate inclusive quartile bounds from order statistics."""
    lower = [item['wall_seconds'] if item['status'] == 'ok' else timeout for item in observations]
    upper = sorted(item['wall_seconds'] if item['status'] == 'ok' else math.inf for item in observations)
    lower_quantiles = statistics.quantiles(lower, n=4, method='inclusive')
    result = {}
    for q, name, low in zip((.25, .5, .75), ('p25', 'median', 'p75'), lower_quantiles):
        position = (len(upper) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        if math.isinf(upper[hi]):
            result[name] = dict(kind='lower_bound', seconds=low, strict=True)
        else:
            high = upper[lo] * (hi - position) + upper[hi] * (position - lo) if lo != hi else upper[lo]
            require(math.isclose(low, high, rel_tol=1e-12, abs_tol=1e-12), 'Unexpected bounded interval')
            result[name] = dict(kind='exact', seconds=high)
    return result


def aggregate(members, timeout):
    group = dict(vertices=members[0]['vertices'], probability=members[0]['probability'], graphs=len(members))
    for label in ('before', 'after'):
        observations = [case[label] for case in members]
        values = [item['wall_seconds'] for item in observations if item['status'] == 'ok']
        counts = Counter(item['status'] for item in observations)
        completed = None
        if values:
            q25, _, q75 = statistics.quantiles(values, n=4, method='inclusive')
            completed = dict(median_seconds=statistics.median(values), p25_seconds=q25,
                             p75_seconds=q75, min_seconds=min(values), max_seconds=max(values))
        group[label] = dict(counts={key: counts[key] for key in
                           ('ok', 'timeout', 'allocation_failure_under_cap', 'error', 'other')},
                            completed_only=completed, quantiles=quantiles(observations, timeout))
    ratios = [case['before']['wall_seconds'] / case['after']['wall_seconds'] for case in members
              if case['before']['status'] == case['after']['status'] == 'ok']
    group['paired_complete_count'] = len(ratios)
    group['paired_speedup'] = (dict(median=statistics.median(ratios), geomean=statistics.geometric_mean(ratios),
                                    min=min(ratios), max=max(ratios)) if ratios else None)
    before, after = (group[label]['quantiles']['median'] for label in ('before', 'after'))
    group['ratio_of_full_sample_medians'] = (before['seconds'] / after['seconds']
        if before['kind'] == after['kind'] == 'exact' else None)
    return group


def verify(report_path, output_path):
    raw_bytes = report_path.read_bytes()
    raw_digest = hashlib.sha256(raw_bytes).hexdigest()
    report = json.loads(raw_bytes)
    require(report['completed'] and report['expected_graphs'] == 240, 'Experiment incomplete')
    provenance = report['provenance']
    require(provenance['timeout_seconds'] == 120 and provenance['samples_per_group'] == 20, 'Wrong budgets')
    require(provenance['address_space_limit_bytes'] == 4 * 1024**3, 'Wrong memory budget')
    require(provenance['worker_cpus'] == [1, 2, 3] and provenance['management_cpu'] == 0, 'Wrong CPU configuration')
    cases = report['cases']
    require(len(cases) == 240 and len({case['name'] for case in cases}) == 240, 'Duplicate/missing cases')
    require(len({case['input_sha256'] for case in cases}) == 240, 'Duplicate inputs')
    indexed = {(case['vertices'], case['probability'], case['sample_index']): case for case in cases}
    require(set(indexed) == set(itertools.product(SIZES, DENSITIES, range(20))), 'Wrong case matrix')
    expected_specs = [dict(name=f'er_n{n}_p{p:g}_sample{index + 1:02d}', vertices=n,
                          probability=p, sample_index=index, seed=202610300000 + n * 1000 + index)
                      for n, p, index in itertools.product(SIZES, DENSITIES, range(20))]
    require(provenance['case_specs'] == expected_specs, 'Wrong recorded specification')
    for spec in expected_specs:
        case = indexed[spec['vertices'], spec['probability'], spec['sample_index']]
        require(all(case[key] == value for key, value in spec.items()), 'Case/specification mismatch')

    verified_files = {}
    for label, base in (('before', ROOT / 'build/performance/baseline-source'), ('after', ROOT)):
        for name, digest in provenance['source_sha256'][label].items():
            path = base / name
            require(sha256(path) == digest, 'Current source hash mismatch: ' + str(path))
            committed = subprocess.run(['git', 'show', provenance[label + '_commit'] + ':' + name],
                                       cwd=ROOT, capture_output=True, check=True).stdout
            require(hashlib.sha256(committed).hexdigest() == digest, 'Committed source mismatch: ' + name)
            verified_files[str(path.relative_to(ROOT))] = digest
    files = {'build/performance/SGB-before': provenance['binary_sha256']['before'],
             'build/SGB': provenance['binary_sha256']['after'],
             'build/sgb-reference-large': provenance['reference_binary_sha256'],
             'benchmarks/reference_large.cpp': provenance['reference_source_sha256'],
             'benchmarks/performance_ensemble.py': provenance['runner_sha256']}
    files.update({'benchmarks/' + name: digest for name, digest in provenance['imported_runner_sha256'].items()})
    for name, digest in files.items():
        require(sha256(ROOT / name) == digest, 'Artifact hash mismatch: ' + name)
        verified_files[name] = digest

    regenerated = []
    for n, index in itertools.product(SIZES, range(20)):
        seed = 202610300000 + n * 1000 + index
        rng = random.Random(seed)
        edges = {probability: [] for probability in DENSITIES}
        for a, b in itertools.combinations(range(1, n + 1), 2):
            draw = rng.random()
            if draw < DENSITIES[-1]:
                edge = f'({a},{b})'
                for probability in DENSITIES:
                    if draw < probability:
                        edges[probability].append(edge)
        labels = '[' + ','.join(map(str, range(1, n + 1))) + '] '
        for probability in DENSITIES:
            case = indexed[n, probability, index]
            line = labels + '[' + ','.join(edges[probability]) + ']'
            digest = hashlib.sha256(line.encode()).hexdigest()
            count = len(edges[probability])
            require(case['input_sha256'] == digest and case['edges'] == count, 'Regenerated input mismatch')
            require(case['actual_density'] == 2 * count / (n * (n - 1)), 'Density mismatch')
            require(case['average_degree'] == 2 * count / n, 'Degree mismatch')
            regenerated.append(dict(name=case['name'], input_sha256=digest, edges=count))
        print(f'Input hashes verified: {len(regenerated)}/240', flush=True)

    counts = {label: Counter() for label in ('before', 'after')}
    paired = 0
    for case in cases:
        truth = case['reference']
        require((truth['vertices'], truth['edges']) == (case['vertices'], case['edges']), 'Reference size mismatch')
        histogram = truth['component_histogram']
        require(sum(row['components'] for row in histogram) == truth['components'], 'Component count mismatch')
        require(sum(row['components'] * row['squares'] for row in histogram) == truth['squares'], 'Square sum mismatch')
        require(sum(row['components'] * row['support'] for row in histogram) == truth['support_sum'], 'Support sum mismatch')
        require(max((row['support'] for row in histogram), default=0) == truth['largest_support'], 'Largest support mismatch')
        require(truth['intended_cfs'] == any(row['support'] == truth['vertices'] - truth['universal_vertices']
                                           for row in histogram), 'CFS/reference support mismatch')
        require(case['execution_order'] == (['before', 'after'] if case['sample_index'] % 2 == 0
                                           else ['after', 'before']), 'Pair execution order mismatch')
        require(case['cpu'] in provenance['worker_cpus'], 'Wrong worker CPU')
        for label in ('before', 'after'):
            observation = case[label]
            require(observation['status'] in ('ok', 'timeout'), 'Unexpected execution failure')
            require(not observation['stderr'], 'Unexpected execution diagnostic')
            require(math.isfinite(observation['wall_seconds']) and observation['wall_seconds'] > 0, 'Invalid elapsed time')
            counts[label][observation['status']] += 1
            if observation['status'] == 'ok':
                require(observation['returncode'] == 0 and observation['validated'], 'Invalid successful status')
                validate_csv(observation['stdout'], truth)
            else:
                require(observation['returncode'] == -9 and not observation['validated'], 'Invalid timeout status')
                require(observation['wall_seconds'] >= 120, 'Timeout before deadline')
        if case['before']['status'] == case['after']['status'] == 'ok':
            require(case['paired_csv_identical'] and case['before']['stdout'] == case['after']['stdout'], 'Paired CSV mismatch')
            paired += 1
        else:
            require(case['paired_csv_identical'] is None, 'Incomplete pair claimed equal')
    groups = [aggregate([case for case in cases if (case['vertices'], case['probability']) == (n, p)], 120)
              for n, p in itertools.product(SIZES, DENSITIES)]
    require(len(report['groups']) == 12, 'Wrong group count')
    for expected, recorded in zip(groups, report['groups']):
        compare(expected, recorded, 'group')
    require(report['all_completed_outputs_validated'] and report['execution_or_validation_failures'] == 0,
            'Incorrect completion flags')
    require(report['all_optimized_cases_validated'] == (counts['after']['ok'] == 240), 'Incorrect optimized validation flag')
    for cpu in provenance['worker_cpus']:
        selected = sorted((case for case in cases if case['cpu'] == cpu), key=lambda case: case['started_utc'])
        require(all(a['finished_utc'] <= b['started_utc'] for a, b in zip(selected, selected[1:])),
                'Overlapping graph pairs on a worker CPU')
    from report_ensemble import render_markdown
    markdown = ROOT / 'audit/performance-ensemble.md'
    svg = ROOT / 'audit/performance-ensemble.svg'
    require(markdown.read_text() == render_markdown(report), 'Markdown differs from the verified data rendering')
    plot = ET.parse(svg).getroot()
    require(sum(element.get('id', '').startswith('PathCollection_') for element in plot.iter()) == 480,
            'Plot does not contain all480 recorded observations')
    documented_artifacts = {str(path.relative_to(ROOT)): sha256(path) for path in
                            (markdown, svg, ROOT / 'benchmarks/report_ensemble.py')}
    require(sha256(report_path) == raw_digest, 'Raw report changed during validation')
    validation = dict(schema_version=1, completed=True, verified_utc=datetime.now(timezone.utc).isoformat(),
                      raw_report_sha256=raw_digest, verifier_sha256=sha256(Path(__file__)),
                      method='No application timings or reference analyses were rerun. Independently regenerated all inputs '
                             'with itertools.combinations and one RNG stream per size/seed; independently recomputed '
                             'quartiles with statistics.quantiles and paired speedups with statistics.geometric_mean. '
                             'Strict CSV validation used the tested existing validator against recorded reference results.',
                      checks=dict(matrix_12_groups_of_20=True, unique_graphs_240=True, input_hashes_and_metadata=True,
                                  current_and_committed_source_hashes=True, binary_reference_and_helper_hashes=True,
                                  completed_outputs_revalidated=True, paired_csv_identity=True, reference_histogram_consistency=True,
                                  execution_order_and_cpu_records=True, timeout_classification=True,
                                  independently_recomputed_aggregate_statistics=True, report_completion_flags=True,
                                  markdown_matches_verified_data=True, plot_contains_480_observations=True),
                      counts={label: dict(value) for label, value in counts.items()}, completed_pairs=paired,
                      all_optimized_cases_completed=counts['after']['ok'] == 240,
                      verified_files_sha256=verified_files, documented_artifacts_sha256=documented_artifacts,
                      regenerated_inputs=regenerated, independent_groups=groups)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(validation, indent=2, allow_nan=False) + '\n')
    print(f'Validated 240 graph inputs, {sum(counter["ok"] for counter in counts.values())} completed outputs, '
          f'{paired} completed pairs, and all 12 aggregate groups: {output_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT / 'audit/performance-ensemble-results.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'audit/performance-ensemble-validation.json')
    args = parser.parse_args()
    require(args.report.resolve() != args.output.resolve(), 'The validation output must not overwrite the raw report')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(schema_version=1, completed=False)) + '\n')
    verify(args.report, args.output)


if __name__ == '__main__':
    main()
