#!/usr/bin/env python3
"""Measure search work on fixed-alpha and sparse-complement graph families."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile

from performance import environment, positive_integer, source_hashes
from performance_ensemble import atomic_write, canonical_hash
from performance_large import bounded_run
from run import positive_timeout, require, sha256


ROOT = Path(__file__).resolve().parent.parent


def choose_two(value):
    return value * (value - 1) // 2


def count_sparse_squares(n, edges):
    """Independent bitset common-neighbor count; each square has two diagonals."""
    rows = [0] * n
    for a, b in edges:
        rows[a] |= 1 << b
        rows[b] |= 1 << a
    twice = 0
    for a in range(n):
        for b in range(a + 1, n):
            if rows[a] >> b & 1:
                continue
            common = rows[a] & rows[b]
            while common:
                bit = common & -common
                c = bit.bit_length() - 1
                common ^= bit
                twice += (common & ~rows[c]).bit_count()
    require(twice % 2 == 0, 'Independent square count is not even before dividing by two')
    return twice // 2


def count_dense_squares(n, missing_edges):
    """Count induced 2K2s in the complement without testing all missing-edge pairs.

    From every pair of complement edges, subtract pairs sharing an endpoint and
    disjoint pairs with a complement cross edge. A set deduplicates bad disjoint
    pairs discovered through multiple cross edges.
    """
    incident = [[] for _ in range(n)]
    for edge_id, (a, b) in enumerate(missing_edges):
        incident[a].append((edge_id, b))
        incident[b].append((edge_id, a))
    shared_endpoint_pairs = sum(choose_two(len(row)) for row in incident)
    forbidden = set()
    for bridge_id, (u, v) in enumerate(missing_edges):
        for first_id, a in incident[u]:
            if first_id == bridge_id:
                continue
            for second_id, b in incident[v]:
                if second_id == bridge_id or a == b:
                    continue
                forbidden.add((min(first_id, second_id), max(first_id, second_id)))
    result = choose_two(len(missing_edges)) - shared_endpoint_pairs - len(forbidden)
    require(result >= 0, 'Independent dense square count is negative')
    return result


def make_specs(vertices, samples, alpha, complement_degree):
    require(samples > 0, 'Sample count must be positive')
    require(len(vertices) == len(set(vertices)), 'Duplicate vertex counts')
    require(math.isfinite(alpha) and alpha > 0, 'Alpha must be finite and positive')
    require(math.isfinite(complement_degree) and complement_degree > 0,
            'Complement mean degree must be finite and positive')
    cases = []
    for family, family_offset in (('fixed_alpha', 0), ('fixed_complement_degree', 100000000)):
        for n in vertices:
            require(n > 1, 'At least two vertices are required')
            listed_probability = alpha / math.sqrt(n) if family == 'fixed_alpha' else complement_degree / (n - 1)
            require(0 < listed_probability < 1, 'Requested parameters give a probability outside (0,1)')
            for sample in range(samples):
                cases.append(dict(name=f'{family}_n{n}_sample{sample + 1:02d}', family=family,
                                  vertices=n, sample_index=sample,
                                  seed=202611020000 + family_offset + n * 1000 + sample,
                                  listed_probability=listed_probability,
                                  probability=listed_probability if family == 'fixed_alpha' else 1 - listed_probability))
    return cases


def generate(spec):
    n, probability = spec['vertices'], spec['listed_probability']
    rng = random.Random(spec['seed'])
    listed = [(a, b) for a in range(n) for b in range(a + 1, n) if rng.random() < probability]
    complement = spec['family'] == 'fixed_complement_degree'
    data = (f'{n} {int(complement)}\n' + ''.join(f'{a} {b}\n' for a, b in listed)).encode()
    edges = choose_two(n) - len(listed) if complement else len(listed)
    oracle = count_dense_squares(n, listed) if complement else count_sparse_squares(n, listed)
    metadata = dict(spec, input_sha256=hashlib.sha256(data).hexdigest(), input_bytes=len(data),
                    input_is_complement=complement, listed_pairs=len(listed), edges=edges,
                    actual_density=edges / choose_two(n), expected_squares=oracle,
                    oracle='complement edge-pair inclusion/exclusion' if complement else 'bitset common-neighbor count')
    return data, metadata


def aggregate(cases):
    groups = []
    for family, n in sorted({(case['family'], case['vertices']) for case in cases}):
        members = [case for case in cases if (case['family'], case['vertices']) == (family, n)]
        valid = [case for case in members if case['status'] == 'ok' and case['validated']]
        group = dict(family=family, vertices=n, graphs=len(members), completed=len(valid),
                     outcomes=dict(Counter(case['status'] for case in members)))
        if valid:
            observations = [case['observation'] for case in valid]
            work = [item['wedge_visits'] + item['wedge_pairs'] + item['missing_edge_pairs'] for item in observations]
            group.update(strategies=dict(Counter(item['strategy'] for item in observations)),
                         search_seconds_median=statistics.median(item['search_seconds'] for item in observations),
                         enumeration_checks_median=statistics.median(work),
                         enumeration_checks_per_n_squared_median=statistics.median(work) / n ** 2,
                         squares_median=statistics.median(item['squares'] for item in observations),
                         squares_per_n_squared_median=statistics.median(item['squares'] for item in observations) / n ** 2,
                         search_seconds_range=[min(item['search_seconds'] for item in observations),
                                               max(item['search_seconds'] for item in observations)])
        groups.append(group)
    for family in {group['family'] for group in groups}:
        family_groups = sorted((group for group in groups if group['family'] == family), key=lambda group: group['vertices'])
        for previous, current in zip(family_groups, family_groups[1:]):
            if previous['completed'] != previous['graphs'] or current['completed'] != current['graphs']:
                continue
            current['previous_vertices'] = previous['vertices']
            current['vertex_ratio'] = current['vertices'] / previous['vertices']
            for key in ('enumeration_checks_median', 'search_seconds_median', 'squares_median'):
                current[key + '_ratio'] = current[key] / previous[key] if previous[key] else None
    return groups


def provenance(args, specs):
    return dict(case_specs=specs, source_sha256=source_hashes(ROOT), application_commit=args.application_commit,
                parameters=dict(alpha=args.alpha, complement_mean_degree=args.complement_degree,
                                vertices=args.vertices, samples_per_group=args.samples),
                harness_binary_sha256=sha256(args.binary), harness_source_sha256=sha256(ROOT / 'benchmarks/adaptive_scaling.cpp'),
                runner_sha256=sha256(Path(__file__)),
                imported_helper_sha256={name: sha256(ROOT / 'benchmarks' / name)
                                        for name in ('performance.py', 'performance_large.py', 'performance_ensemble.py', 'run.py')},
                environment=environment(), cpu=args.cpu, management_cpu=args.management_cpu,
                timeout_seconds=args.timeout, address_space_limit_bytes=args.memory_gib * 1024 ** 3,
                compiler_version=subprocess.run([args.compiler, '--version'], capture_output=True, text=True,
                                                check=True).stdout.splitlines()[0],
                compiler_flags=args.compiler_flags, boost_version=args.boost_version,
                input_format='Header: vertex_count and complement flag 0/1. Remaining lines: sorted unique 0-based a<b pairs. '
                             'Pairs are original edges when flag=0 and missing edges when flag=1.',
                generator='Python random.Random(seed).random() in lexicographic a<b order; listed pair iff draw<listed_probability.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--application-commit', required=True)
    parser.add_argument('--vertices', nargs='+', type=positive_integer, default=[250, 500, 1000, 2000])
    parser.add_argument('--samples', type=positive_integer, default=20)
    parser.add_argument('--alpha', type=float, default=.5)
    parser.add_argument('--complement-degree', type=float, default=2)
    parser.add_argument('--cpu', type=int, default=1)
    parser.add_argument('--management-cpu', type=int, default=0)
    parser.add_argument('--timeout', type=positive_timeout, default=120)
    parser.add_argument('--memory-gib', type=positive_integer, default=4)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--compiler-flags', default='-O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror')
    parser.add_argument('--boost-version', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'audit/performance-adaptive-scaling.json')
    args = parser.parse_args()
    original_affinity = os.sched_getaffinity(0)
    report = dict(schema_version=1, completed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                  command=[sys.executable, *sys.argv], cases=[], groups=[])
    atomic_write(args.output, report)
    try:
        specs = make_specs(args.vertices, args.samples, args.alpha, args.complement_degree)
        require(args.cpu in original_affinity and args.management_cpu in original_affinity and args.cpu != args.management_cpu,
                'Select distinct available measurement and management CPUs')
        args.binary = args.binary.resolve()
        require(args.binary.is_file() and os.access(args.binary, os.X_OK), 'Scaling probe is not executable')
        report['provenance'] = provenance(args, specs)
        report['expected_graphs'] = len(specs)
        report['methodology'] = (
            'One instrumented findSquares call on each distinct graph, including adaptive membership/index setup and ordering. '
            'Graph generation, input parsing, Boost graph construction, and output verification are excluded from the internal '
            'search timer and separately reported where applicable. The search runs on one pinned CPU; no other performance '
            'suite should run concurrently. Counters add instrumentation overhead, so these times are diagnostic and are not '
            'additional end-to-end speedup measurements. Enumeration_checks sums wedge visits, wedge pair tests, and missing-edge '
            'pair tests; it excludes ordering, adjacency-structure setup, and support/component analysis. Every returned square '
            'is checked for validity and uniqueness; the count is checked using an independently implemented oracle. Sparse '
            'counts use bitset common-neighbor intersections. Dense counts use complement edge-pair inclusion/exclusion without '
            'enumerating all candidate missing-edge pairs. Fixed-alpha samples use p=alpha/sqrt(n); dense samples use '
            'p=1-complement_degree/(n-1). The experiment describes these families and supports, but does not prove, asymptotic '
            'claims. Those claims require separate mathematical analysis. All raw observations and input/build hashes are retained.')
        atomic_write(args.output, report)
        shuffled = list(specs)
        random.Random(20261102).shuffle(shuffled)
        os.sched_setaffinity(0, {args.management_cpu})
        seen = set()
        with tempfile.TemporaryDirectory(prefix='sgb-adaptive-scaling-') as directory:
            path = Path(directory) / 'compact.txt'
            for spec in shuffled:
                data, case = generate(spec)
                require(case['input_sha256'] not in seen, 'Two scaling cases generated identical inputs')
                seen.add(case['input_sha256'])
                path.write_bytes(data)
                observation = bounded_run(['taskset', '-c', str(args.cpu), str(args.binary), str(path)],
                                          args.timeout, args.memory_gib * 1024 ** 3)
                case.update(status=observation['status'], validated=False, process_wall_seconds=observation['wall_seconds'],
                            returncode=observation['returncode'], stderr=observation['stderr'])
                if observation['status'] == 'ok':
                    observed = json.loads(observation['stdout'])
                    for key in ('vertices', 'edges', 'listed_pairs', 'input_is_complement'):
                        require(observed[key] == case[key], f"{case['name']}: {key} mismatch")
                    require(observed['strategy'] in ('wedges', 'missing_edges'), 'Unknown selected strategy')
                    for key in ('active_vertices', 'nonedges', 'wedge_visits', 'wedge_pairs',
                                'missing_edge_pairs', 'squares', 'radix_passes'):
                        require(type(observed[key]) is int and observed[key] >= 0, f'Invalid counter: {key}')
                    require(observed['nonedges'] == choose_two(case['vertices']) - case['edges'],
                            'Missing-edge metric mismatch')
                    require(observed['active_vertices'] <= case['vertices'], 'Too many active vertices')
                    if (observed['active_vertices'] >= 4 and observed['nonedges'] >= 2 and
                            observed['estimated_wedge_work'] > 0):
                        if observed['strategy'] == 'missing_edges':
                            require(observed['missing_edge_pairs'] == choose_two(observed['nonedges']),
                                    'Missing-edge candidate counter mismatch')
                        else:
                            require(observed['wedge_visits'] == observed['estimated_wedge_work'],
                                    'Wedge visit counter mismatch')
                    require(observed['squares'] == case['expected_squares'], f"{case['name']}: square count mismatch")
                    require(observed['every_square_valid_and_unique'], f"{case['name']}: invalid square output")
                    require(math.isfinite(observed['search_seconds']) and observed['search_seconds'] >= 0,
                            f"{case['name']}: invalid measured interval")
                    case.update(observation=observed, validated=True)
                else:
                    case['stdout'] = observation['stdout']
                report['cases'].append(case)
                report['cases'].sort(key=lambda item: (item['family'], item['vertices'], item['sample_index']))
                report['groups'] = aggregate(report['cases'])
                atomic_write(args.output, report)
                print(f"{len(report['cases'])}/{len(specs)} {case['name']} {case['status']} "
                      f"squares={case['expected_squares']} search={case.get('observation', {}).get('search_seconds')}", flush=True)
        os.sched_setaffinity(0, original_affinity)
        require(canonical_hash(report['provenance']) == canonical_hash(provenance(args, specs)),
                'Code, binary, or environment changed during the scaling study')
        report.update(completed=True, all_cases_validated=all(case['validated'] for case in report['cases']),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        atomic_write(args.output, report)
        require(report['all_cases_validated'], 'Some scaling cases did not finish or validate')
        print(f'Validated scaling study: {args.output}', flush=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    finally:
        os.sched_setaffinity(0, original_affinity)


if __name__ == '__main__':
    main()
