#!/usr/bin/env python3
"""Render validated adaptive-search measurements with their recorded provenance."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from report_ensemble import number, quantile_text, render_plot, rows, verify_report


ROOT = Path(__file__).resolve().parent.parent
BEFORE_COMMIT = '0ebc8fe1460e278edb52fcdf183af57747718d03'


def verify_adaptive_report(report):
    verify_report(report)
    provenance = report['provenance']
    if provenance['before_commit'] != BEFORE_COMMIT:
        raise ValueError('Expected the existing optimized SGB baseline, commit 0ebc8fe')
    if provenance['source_sha256']['before'] == provenance['source_sha256']['after']:
        raise ValueError('The adaptive comparison must use different application sources')
    if not report.get('all_completed_outputs_validated'):
        raise ValueError('The report does not certify its completed outputs')
    if report.get('execution_or_validation_failures') != 0:
        raise ValueError('Resolve execution or correctness failures before reporting results')
    expected_after = all(case['after']['status'] == 'ok' and case['after']['validated']
                         for case in report['cases'])
    if report.get('all_optimized_cases_validated') != expected_after:
        raise ValueError('Optimized-completion flag is inconsistent')


def counts(report, label):
    return {status: sum(case[label]['status'] == status for case in report['cases'])
            for status in ('ok', 'timeout')}


def commit_link(commit):
    return f'[`{commit[:7]}`](https://github.com/jasonbehrstockdev/SGB/tree/{commit})'


def paired_text(group):
    paired = group['paired_speedup']
    if paired is None:
        return 'Unavailable'
    result = f"{number(paired['median'], 3)}×"
    if group['paired_complete_count'] != group['graphs']:
        result += f" ({group['paired_complete_count']} pairs)"
    return result


def verify_scaling(report):
    if not report.get('completed') or not report.get('all_cases_validated'):
        raise ValueError('The scaling study is incomplete or has unvalidated cases')
    if len(report['cases']) != 160 or len(report['groups']) != 8:
        raise ValueError('Expected 160 scaling cases in eight groups')
    if any(group['graphs'] != 20 or group['completed'] != 20 for group in report['groups']):
        raise ValueError('Every scaling group must have 20 completed cases')
    if len({case['input_sha256'] for case in report['cases']}) != 160:
        raise ValueError('Scaling inputs are not distinct')
    expected = {(family, n) for family in ('fixed_alpha', 'fixed_complement_degree')
                for n in (250, 500, 1000, 2000)}
    if {(group['family'], group['vertices']) for group in report['groups']} != expected:
        raise ValueError('Unexpected scaling study matrix')
    for group in report['groups']:
        selected = [case for case in report['cases'] if case['family'] == group['family']
                    and case['vertices'] == group['vertices']]
        if len(selected) != 20 or len({case['seed'] for case in selected}) != 20:
            raise ValueError('Scaling groups must contain 20 distinct seeds')
        for case in selected:
            if case['status'] != 'ok' or not case['validated']:
                raise ValueError('Unvalidated scaling output')
            observed = case['observation']
            if not observed['every_square_valid_and_unique'] or observed['squares'] != case['expected_squares']:
                raise ValueError('Scaling square output failed verification')
            if not math.isfinite(observed['search_seconds']) or observed['search_seconds'] < 0:
                raise ValueError('Invalid scaling interval')
        observations = [case['observation'] for case in selected]
        work = [item['wedge_visits'] + item['wedge_pairs'] + item['missing_edge_pairs'] for item in observations]
        n = group['vertices']
        values = dict(search_seconds_median=statistics.median(item['search_seconds'] for item in observations),
                      enumeration_checks_median=statistics.median(work),
                      enumeration_checks_per_n_squared_median=statistics.median(work) / n ** 2,
                      squares_median=statistics.median(item['squares'] for item in observations),
                      squares_per_n_squared_median=statistics.median(item['squares'] for item in observations) / n ** 2,
                      strategies=dict(Counter(item['strategy'] for item in observations)))
        if any(group[key] != value for key, value in values.items()):
            raise ValueError('Scaling summary does not match its observations')


def scaling_section(report):
    text = [
        '## Search scaling', '',
        'A [separate instrumented study](performance-adaptive-scaling.json) measures',
        '20 graphs at each of four sizes in two parameter regimes. Its timer covers',
        '`findSquares`, including adjacency-cache construction and restoring square',
        'order. It excludes graph construction, CLI parsing, component discovery,',
        'support accumulation, and output. These are search measurements, not extra',
        'end-to-end speedup claims.', '',
        'The sparse family fixes `alpha = p * sqrt(n) = 0.5`; the dense family fixes',
        'the expected complement degree at 2. Enumeration checks count wedge visits,',
        'pairs within a common-neighbor bucket, or pairs of missing edges. They exclude',
        'cache setup and ordering work. The normalized counts test the predicted',
        'quadratic enumeration growth directly; elapsed times also include allocation',
        'and instrumentation costs.', '',
        '| Family | Vertices | Graphs | Median search (s) | Median enumeration checks / n² | Median squares / n² | Selected strategies |',
        '| --- | ---: | ---: | ---: | ---: | ---: | --- |',
    ]
    for group in sorted(report['groups'], key=lambda group: (group['family'], group['vertices'])):
        strategies = ', '.join(f'{name}: {count}' for name, count in sorted(group['strategies'].items()))
        text.append(f"| {group['family']} | {group['vertices']:,} | {group['graphs']} | "
                    f"{number(group['search_seconds_median'])} | "
                    f"{number(group['enumeration_checks_per_n_squared_median'])} | "
                    f"{number(group['squares_per_n_squared_median'])} | {strategies} |")
    text += ['', 'Each case has an independently derived square count and checks the',
             'returned squares for valid induced-cycle adjacencies and duplicate keys.',
             'The raw scaling artifact records its exact source/binary/input hashes,',
             'parameters, observations, and separate construction/validation timings.', '']
    return text


def render_markdown(report, raw_sha256, scaling=None):
    provenance = report['provenance']
    before, after = counts(report, 'before'), counts(report, 'after')
    paired_count = sum(all(case[label]['status'] == 'ok' for label in ('before', 'after'))
                       for case in report['cases'])
    fully_paired = [group for group in rows(report) if group['paired_complete_count'] == 20]
    text = [
        '# Adaptive square-search performance', '',
        'The adaptive search replaces repeated neighborhood walks with streamed',
        'common-neighbor buckets, and uses pairs of missing edges when that search',
        'is estimated to be cheaper. The [algorithm analysis](adaptive-search.md)',
        'explains the selection rule, exact square enumeration, output ordering,',
        'memory tradeoffs, and complexity bounds.', '',
        f"This experiment compares **{commit_link(provenance['before_commit'])} before**",
        f"with **{commit_link(provenance['after_commit'])} after**.",
        'The before build already includes canonical square hashing and shared-diagonal',
        'component discovery from the earlier optimization. Its CFS rule already allows',
        'complete join factors. The measurements isolate the subsequent adaptive-search',
        'changes, rather than comparing against the original 2024 import.', '',
        'There are **20 distinct graphs per size and density**: 240 graphs at 1,000',
        'and 3,000 vertices, six edge probabilities, and 480 measured application runs.',
        'Each before/after pair reads the same input file. There is one fresh-process',
        'measurement per build per graph, with a **120-second wall-time limit**.',
        'The [raw results](performance-adaptive-results.json) retain every outcome,',
        'timing, seed, input hash, reference result, execution order, and build hash.', '',
    ]
    if fully_paired:
        strongest = max(fully_paired, key=lambda group: group['paired_speedup']['median'])
        text += [
            'Among groups with all 20 pairs completed, the largest median paired',
            f"speedup was **{number(strongest['paired_speedup']['median'], 3)}×** at",
            f"**{strongest['vertices']:,} vertices and {100 * strongest['probability']:g}% edge probability**.",
        ]
    text += [f"The before build completed **{before['ok']}/240** runs and the adaptive build",
             f"completed **{after['ok']}/240**. Their timeout counts were **{before['timeout']}**",
             f"and **{after['timeout']}**, respectively. Each timeout remains an incomplete",
             'analysis, and every completed result matched the reference.', '',
             '## Paired CLI comparison', '',
             'Times are **seconds per graph**, including process startup, parsing,',
             'analysis, output, and cleanup. The speedup column is the median of the',
             'within-graph before/after ratios among completed pairs. It can differ',
             'from the ratio of the two group medians. When fewer than 20 pairs finish,',
             'the paired statistic describes only that completed subset.', '',
             '| Vertices | Edge probability | Before median (s) | After median (s) | Median paired speedup | Completed before / after (of 20) |',
             '| ---: | ---: | ---: | ---: | ---: | --- |']
    for group in rows(report):
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | "
                    f"{quantile_text(group['before']['quantiles']['median'])} | "
                    f"{quantile_text(group['after']['quantiles']['median'])} | {paired_text(group)} | "
                    f"{group['before']['counts']['ok']} / {group['after']['counts']['ok']} |")
    text += ['', 'A `>` value is a lower bound from right-censored observations. A timed-out',
             'run is not assigned a completed runtime of 120 seconds. Quantiles use the',
             'whole 20-graph sample; when the required order statistics are completed,',
             'a quantile can still be identified despite slower timed-out observations.',
             'Bounds are rounded downward. No exact speedup is inferred from a timeout.', '',
             '![Individual paired timings and censored outcomes.](performance-adaptive.svg)', '',
             'Each dot is one completed run. Upward triangles at the two-minute deadline',
             'mark timeouts; they are not completed times. Black ticks mark identifiable',
             'sample medians. The vertical scale is logarithmic.', '',
             '### Variation across graphs', '',
             'These 25th–75th percentile intervals combine graph-to-graph variation and',
             'runtime noise. They are not confidence intervals. Censored bounds are',
             'shown where a percentile cannot be measured exactly.', '',
             '| Vertices | Edge probability | Before 25th–75th percentile (s) | After 25th–75th percentile (s) |',
             '| ---: | ---: | --- | --- |']
    for group in rows(report):
        intervals = []
        for label in ('before', 'after'):
            quantiles = group[label]['quantiles']
            low, high = quantile_text(quantiles['p25']), quantile_text(quantiles['p75'])
            intervals.append(f'Both {low}' if low == high and quantiles['p25']['kind'] == 'lower_bound'
                             else f'{low} to {high}')
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | {intervals[0]} | {intervals[1]} |")
    text += ['', '## Inputs and structural coverage', '',
             'The inputs are the same deterministic `G(n,p)` graph instances as the',
             '[previous ensemble study](performance-ensemble.md). Every density has',
             '20 distinct seeds. Reusing each seed across probabilities gives nested',
             'edge sets, so the groups at different densities are correlated.',
             'The measured runs themselves are new; earlier timings are not reused.', '',
             'The generator uses `seed = 202610300000 + n * 1000 + sample_index`, with',
             '`sample_index` from 0 to 19. Python `random.Random(seed).random()` is called',
             'once per unordered vertex pair in lexicographic order; an edge is added',
             'when the draw is below `p`. Exact input hashes are retained.', '',
             '| Vertices | Edge probability | Actual density range | Squares, median (range) | Reference CFS graphs |',
             '| ---: | ---: | --- | --- | ---: |']
    for group in rows(report):
        selected = [case for case in report['cases'] if case['vertices'] == group['vertices']
                    and case['probability'] == group['probability']]
        densities = [100 * case['actual_density'] for case in selected]
        squares = [case['reference']['squares'] for case in selected]
        median = f'{statistics.median(squares):,.1f}'.removesuffix('.0')
        cfs = sum(case['reference']['intended_cfs'] for case in selected)
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | "
                    f"{number(min(densities), 5)}%–{number(max(densities), 5)}% | "
                    f"{median} ({min(squares):,}–{max(squares):,}) | {cfs}/20 |")
    text += ['', 'CFS counts in this table come from the independent reference, including',
             'where a timed application run did not finish. They do not turn timeouts',
             'into correctness passes. Complete join factors remain allowed for CFS;',
             'the square graph and its actual supports retain their literal meaning.', '']
    if scaling is not None:
        text += scaling_section(scaling)
    text += [
        '## Scope of the complexity improvement', '',
        'For bounded `alpha` with `p = alpha / sqrt(n)`, the streamed-wedge method',
        'has expected quadratic **enumeration** work. For dense graphs with only',
        '`O(n)` missing edges, testing their pairs also uses quadratic enumeration',
        'work. These are parameter-dependent statements; a fixed positive density',
        'can produce quartically many induced squares.', '',
        'The program still stores its squares, performs disjoint-set component',
        'operations, and builds ordered support sets. Their inverse-Ackermann and',
        'logarithmic factors belong to the full-pipeline analysis. Requested literal',
        'square-graph output also has its own edge-output cost. The theory document',
        'gives these qualifications explicitly. The paired table measures the whole',
        'ordinary `-tf` CLI path, while the separate scaling study concerns search.', '',
        '## Validation and measurement limits', '',
        f"All **{before['ok'] + after['ok']} completed application outputs** matched the",
        f"scalable reference, and all **{paired_count} completed pairs** had identical CSV.",
        'The runner validated square/component counts, literal support ratios, graph',
        'connectivity, density, alpha, and the CFS result. The report generator',
        'revalidates completed CSV records and recomputes group summaries before',
        'rendering. No execution or validation failure is present in this artifact.', '',
        'The independent reference uses bitset common-neighbor intersections and',
        'components of diagonal nodes. The application uses its own streamed wedge',
        'or missing-edge-pair search. The existing four-vertex-subset structural',
        'oracle and targeted regressions provide an additional, different check.',
        'Graph generation and reference work occur outside each application timer.', '',
        'Each process has a 4 GiB virtual address-space cap; this is a configured',
        'limit, not a peak-memory measurement. Three workers run on distinct pinned',
        'CPUs 1, 2, and 3, with the supervisor on CPU 0. A pair runs sequentially',
        'on one worker; order alternates by sample index, ten before-first and ten',
        'after-first per group. Other workers share the host, cache, and memory',
        'bandwidth. Small differences remain sensitive to startup and scheduling.', '',
        'The exact compiler, Boost version, flags, hardware report, source/binary',
        'hashes, command, and timestamps are in the raw record. The old and new',
        'application builds use the same recorded compilation settings. This study',
        'does not establish a portable speedup for every graph family or machine.', '',
        f'Raw result SHA-256: `{raw_sha256}`.', '',
        '## Reproduce', '',
        'Run from the measured after commit shown above. Build the baseline source',
        'separately with the same compiler and flags:', '',
        '```sh',
        'mkdir -p build/performance-adaptive/before-source',
        f"git archive {provenance['before_commit']} main.cpp flags.h input.h | \\",
        '  tar -x -C build/performance-adaptive/before-source',
        'g++ -O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror \\',
        '  build/performance-adaptive/before-source/main.cpp -o build/performance-adaptive/SGB-before',
        'make build/SGB build/sgb-reference-large',
        'python3 benchmarks/performance_ensemble.py \\',
        '  --before build/performance-adaptive/SGB-before --after build/SGB \\',
        '  --reference build/sgb-reference-large \\',
        '  --before-source build/performance-adaptive/before-source \\',
        f"  --before-commit {provenance['before_commit']} \\",
        f"  --after-commit {provenance['after_commit']} \\",
        f"  --boost-version {provenance['boost_version']} --samples 20 --vertices 1000 3000 \\",
        '  --probabilities .0025 .005 .0075 .01 .0125 .015 \\',
        '  --timeout 120 --memory-gib 4 --cpus 1 2 3 --management-cpu 0 \\',
        '  --output audit/performance-adaptive-results.json',
        '```', '',
        'Add the same Boost include directory to both builds where needed. Adapt',
        'the CPU choices to the available affinity mask and retain those choices',
        'in the new provenance. An interrupted run can resume with `--resume` only',
        'when the saved input, executable, source, and settings provenance matches.', '',
        'After the full experiment, render this report and plot:', '',
        '```sh',
        'MPLCONFIGDIR=/tmp/sgb-mpl python3 benchmarks/report_adaptive.py',
        '```', '',
        'The timing runner uses the Python standard library. Plot rendering requires',
        'Matplotlib. Historical reports retain their original measurements and methods.', '',
    ]
    return '\n'.join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'audit/performance-adaptive-results.json')
    parser.add_argument('--markdown', type=Path, default=ROOT / 'audit/performance-adaptive.md')
    parser.add_argument('--plot', type=Path, default=ROOT / 'audit/performance-adaptive.svg')
    parser.add_argument('--preview', type=Path)
    parser.add_argument('--scaling', type=Path, default=ROOT / 'audit/performance-adaptive-scaling.json')
    args = parser.parse_args()
    raw = args.input.read_bytes()
    report = json.loads(raw)
    verify_adaptive_report(report)
    scaling = None
    if args.scaling.exists():
        scaling = json.loads(args.scaling.read_text())
        verify_scaling(scaling)
        if scaling['provenance']['source_sha256'] != report['provenance']['source_sha256']['after']:
            raise ValueError('The scaling study and paired comparison use different application sources')
    markdown = render_markdown(report, hashlib.sha256(raw).hexdigest(), scaling)
    for path in (args.markdown, args.plot, args.preview):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
    render_plot(report, args.plot, preview=args.preview)
    args.markdown.write_text(markdown)
    print(f'Wrote {args.markdown} and {args.plot}')


if __name__ == '__main__':
    main()
