#!/usr/bin/env python3
"""Render the completed paired density study without treating timeouts as times."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics

from performance_ensemble import aggregate_cases
from performance_large import validate_csv


ROOT = Path(__file__).resolve().parent.parent


def number(value, significant=4, lower_bound=False):
    if lower_bound and value:
        scale = 10 ** (significant - 1 - math.floor(math.log10(abs(value))))
        value = math.floor(value * scale) / scale
    return f'{value:.{significant}g}'


def quantile_text(quantile):
    kind = quantile['kind']
    if kind == 'exact':
        return number(quantile['seconds'])
    if kind == 'lower_bound':
        sign = '>' if quantile.get('strict', True) else '≥'
        return sign + number(quantile['seconds'], lower_bound=True)
    return 'Unavailable'


def rows(report):
    return sorted(report['groups'], key=lambda item: (item['vertices'], item['probability']))


def verify_report(report):
    """Do not render an unfinished or internally inconsistent run as final evidence."""
    if not report.get('completed'):
        raise ValueError('The experiment has not finished')
    cases = report['cases']
    if len(cases) != 240 or len(rows(report)) != 12:
        raise ValueError('Expected the complete 240-graph, 12-group experiment')
    if len({case['input_sha256'] for case in cases}) != len(cases):
        raise ValueError('Graph inputs are not all distinct')
    provenance = report['provenance']
    if provenance['timeout_seconds'] != 120 or provenance['address_space_limit_bytes'] != 4 * 1024 ** 3:
        raise ValueError('The report requires the stated two-minute and 4 GiB limits')
    if provenance['worker_cpus'] != [1, 2, 3] or provenance['management_cpu'] != 0:
        raise ValueError('Update the documented CPU configuration for this experiment')
    expected_groups = {(n, p) for n in (1000, 3000)
                       for p in (.0025, .005, .0075, .01, .0125, .015)}
    if {(group['vertices'], group['probability']) for group in rows(report)} != expected_groups:
        raise ValueError('Unexpected size or density group')
    if report['groups'] != aggregate_cases(cases, provenance['timeout_seconds']):
        raise ValueError('Derived group statistics do not match the recorded measurements')
    for group in rows(report):
        selected = [case for case in cases if case['vertices'] == group['vertices']
                    and case['probability'] == group['probability']]
        if len(selected) != 20 or group['graphs'] != 20:
            raise ValueError('Every group must contain exactly 20 graphs')
        if len({case['seed'] for case in selected}) != 20:
            raise ValueError('Seeds must be distinct within each group')
        for case in selected:
            for label in ('before', 'after'):
                observation = case[label]
                if observation['status'] == 'ok' and not observation['validated']:
                    raise ValueError('A completed output was not validated')
                if observation['status'] not in ('ok', 'timeout'):
                    raise ValueError('Resolve execution errors before publishing this report')
                if observation['status'] == 'ok':
                    validate_csv(observation['stdout'], case['reference'])
            if all(case[label]['status'] == 'ok' for label in ('before', 'after')):
                if case['before']['stdout'] != case['after']['stdout']:
                    raise ValueError('Completed paired outputs differ')


def render_markdown(report):
    cases = report['cases']
    completed = {label: sum(case[label]['status'] == 'ok' for case in cases)
                 for label in ('before', 'after')}
    timed_out = {label: sum(case[label]['status'] == 'timeout' for case in cases)
                 for label in ('before', 'after')}
    fully_paired = [group for group in rows(report) if group['paired_complete_count'] == 20]
    interpretation = []
    if fully_paired:
        strongest = max(fully_paired, key=lambda group: group['paired_speedup']['median'])
        interpretation = [
            f"Among groups where all 20 pairs finished, the largest median paired",
            f"speedup was **{number(strongest['paired_speedup']['median'], 3)}×** at",
            f"**{strongest['vertices']:,} vertices and {100 * strongest['probability']:g}% edge probability**.",
        ]
    interpretation += [
        f"Across all densities, the before build finished {completed['before']}/240 runs",
        f"and the after build finished {completed['after']}/240 within two minutes.",
        'The table retains the unfinished runs as censored measurements. Small',
        'differences in the fastest groups remain sensitive to startup and scheduling',
        'noise; each graph was measured once per build.', '',
    ]
    censored_quantile_note = []
    for group in rows(report):
        after = group['after']
        if after['counts']['timeout'] and all(q['kind'] == 'exact' for q in after['quantiles'].values()):
            censored_quantile_note += [
                f"For the optimized {group['vertices']:,}-vertex, {100 * group['probability']:g}% group,",
                f"{after['counts']['ok']} runs finished and {after['counts']['timeout']} timed out.",
                'Its median and interquartile range remain identifiable from the',
                'completed order statistics of the full 20-graph sample. They are',
                'not statistics computed by discarding the timeouts.', '',
            ]
    dense_cfs = {p: sum(case['reference']['intended_cfs'] for case in cases
                        if case['vertices'] == 3000 and case['probability'] == p)
                 for p in (.0125, .015)}
    text = [
        '# Twenty-graph density comparisons', '',
        'This study measures **20 distinct graphs at each of six densities for both',
        '1,000 and 3,000 vertices**: 240 graphs and 480 measured application runs.',
        'Each before/after pair reads exactly the same graph. The per-run wall-time',
        'limit is **120 seconds**. The application source is unchanged from the',
        '[previous optimization](performance.md): the before build is the repaired',
        'baseline `cbdb90f`; the after build uses optimized source `1d780c2`.', '',
        'The [raw record](performance-ensemble-results.json) preserves every timing,',
        'outcome, seed, input hash, reference result, execution order, and build hash.',
        'Unlike the [earlier experiment](performance-large.md), which repeated one',
        'graph at each density, these medians describe variation across **20 graph',
        'instances, with one measured run per build per graph**.', '',
        *interpretation,
        '## Comparisons', '',
        'Times are **seconds per graph**, including process startup, input parsing,',
        'analysis, cleanup, and CSV output. Speedup is the median of the paired',
        'before/after ratios for graphs on which both builds finished. It is not',
        'the ratio of the two reported medians. Completion counts are out of 20.',
        'Where only some pairs finish, their speedup describes that subset only.', '',
        '| Vertices | ER probability | Before median (s) | After median (s) | Median paired speedup | Completed before / after (of 20) |',
        '| ---: | ---: | ---: | ---: | ---: | --- |',
    ]
    for group in rows(report):
        ratio = group['paired_speedup']
        speedup = f"{number(ratio['median'], 3)}×" if ratio else 'Unavailable'
        if ratio and group['paired_complete_count'] != 20:
            speedup += f" ({group['paired_complete_count']} pairs)"
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | "
                    f"{quantile_text(group['before']['quantiles']['median'])} | "
                    f"{quantile_text(group['after']['quantiles']['median'])} | {speedup} | "
                    f"{group['before']['counts']['ok']} / {group['after']['counts']['ok']} |")
    text += ['', 'A `>` value is a lower bound from censored observations, not a measured',
             'runtime. Timed-out runs are not assigned a runtime of 120 seconds when',
             'computing ordinary statistics. For example, if exactly half a group',
             'times out, the conventional sample median is bounded below by the',
             'average of the tenth completed time and 120 seconds; it is not',
             'automatically greater than 120 seconds. Bound values are rounded down.', '',
             *censored_quantile_note,
             '![Across-graph timing distributions, with timed-out runs marked at the deadline.](performance-ensemble.svg)', '',
             'Dots show individual completed measurements; upward triangles at 120',
             'seconds show timeouts. Black horizontal ticks mark exact sample medians',
             'where identifiable. The vertical scale is logarithmic. The timeout',
             'markers indicate censoring, not completed times.', '',
             '### Across-graph variation', '',
             'The 25th–75th percentile interval uses linear interpolation between',
             'sample order statistics. Bounds are shown when a required order',
             'statistic is censored. These intervals describe graph-to-graph variation',
             'together with runtime noise; they are not confidence intervals.', '',
             '| Vertices | ER probability | Before 25th–75th percentile (s) | After 25th–75th percentile (s) |',
             '| ---: | ---: | --- | --- |']
    for group in rows(report):
        intervals = []
        for label in ('before', 'after'):
            q = group[label]['quantiles']
            lo, hi = quantile_text(q['p25']), quantile_text(q['p75'])
            intervals.append(f'Both {lo}' if lo == hi and q['p25']['kind'] == 'lower_bound'
                             else f'{lo} to {hi}')
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | {intervals[0]} | {intervals[1]} |")
    text += ['', '## Inputs and structural coverage', '',
             'Each graph is an unconditioned Erdos–Renyi `G(n,p)` sample. The generator',
             'uses Python `random.Random(seed)` and visits unordered vertex pairs in',
             'lexicographic order. Twenty distinct seeds are used at each size; a',
             'seed is reused across probabilities to produce nested edge sets.',
             'Specifically, `seed = 202610300000 + n * 1000 + sample_index`, with',
             '`sample_index` from 0 through 19.',
             'Graphs within each density group are distinct; samples across densities',
             'are correlated. No graph was selected or excluded based on its runtime',
             'or CFS result. Input hashes allow exact regeneration to be checked.', '',
             '| Vertices | ER probability | Actual density range | Squares, median (range) | CFS graphs |',
             '| ---: | ---: | --- | --- | ---: |']
    for group in rows(report):
        selected = [case for case in cases if case['vertices'] == group['vertices']
                    and case['probability'] == group['probability']]
        densities = [100 * case['actual_density'] for case in selected]
        squares = [case['reference']['squares'] for case in selected]
        cfs = sum(case['reference']['intended_cfs'] for case in selected)
        text.append(f"| {group['vertices']:,} | {100 * group['probability']:g}% | "
                    f"{number(min(densities), 5)}%–{number(max(densities), 5)}% | "
                    f"{statistics.median(squares):,.1f}".removesuffix('.0') +
                    f" ({min(squares):,}–{max(squares):,}) | {cfs}/20 |")
    text += ['', 'CFS counts above come from the independent reference, including for graphs',
             'where an application build timed out. Such a reference result does not',
             'turn the timed-out application run into a correctness pass. This random',
             f"sample has {dense_cfs[.015]}/20 CFS graphs at 3,000 vertices and 1.5%,",
             f"compared with {dense_cfs[.0125]}/20 at 1.25%. These",
             'observations do not estimate the transition probability precisely. The',
             'sample does not cover all graph structures. The earlier',
             '[structured CFS controls](performance-large.md) and',
             '[100-vertex corpus](../benchmarks/README.md) provide complementary cases.', '',
             '## Validation and limits', '',
             f"The before build completed **{completed['before']}/240** runs and timed out",
             f"on **{timed_out['before']}**. The after build completed **{completed['after']}/240**",
             f"and timed out on **{timed_out['after']}**. Every completed application output",
             'matched the independent scalable reference. On every completed pair,',
             'before and after CSV outputs were byte-identical. No execution error or',
             'unexpected diagnostic occurred. Timeouts remain incomplete analyses.', '',
             'The [independent verification record](performance-ensemble-validation.json)',
             'checks every regenerated input hash, both application sources and binaries,',
             'completed CSV outputs, and the reported aggregates. The verifier uses',
             'separate statistical calculations to check the runner’s summaries.', '',
             'The reference uses bitset adjacency and components of the diagonal',
             'incidence graph, independently of SGB and Boost. Its enumeration and',
             'component results are checked by the existing small-graph and',
             '100-vertex oracle tests. Reference runs and graph generation are outside',
             'the measured application intervals. CFS continues to allow complete',
             'join factors; square supports remain literal.', '',
             'Each timed process has a 4 GiB virtual address-space cap. This is not a',
             'measurement of peak memory. A timeout kills and reaps the process group.',
             'The same timeout and memory cap apply to both builds. There are no',
             'per-graph measured repetitions or adaptive retries; the budget was',
             'allocated to distinct inputs. Small millisecond differences remain',
             'sensitive to process startup and scheduling noise.', '',
             'Three workers run concurrently, each pinned to its own CPU (1, 2, or 3);',
             'the supervisor uses CPU 0. Each pair runs sequentially on the same worker.',
             'Before/after order alternates by sample index, giving ten of each order',
             'per density group. This fits the container’s four-CPU quota but does not',
             'provide a dedicated machine: cache, memory bandwidth, and host resources',
             'are shared. Avoid interpreting small changes as portable guarantees or',
             'directly combining these times with the earlier serial experiment.', '',
             'The environment reports AMD EPYC 7763, Linux x86_64, a four-CPU quota,',
             'and a 16 GiB memory limit. Both application binaries use GCC 14.2.0,',
             'Boost 1.83, C++11, `-O2`, and warnings as errors. Exact provenance,',
             'commands, CPU assignments, and start/end timestamps are in the raw record.', '',
             '## Reproduce', '',
             'Build both application versions with the same compiler and flags:', '',
             '```sh',
             'mkdir -p build/performance/baseline-source',
             'git archive cbdb90fb17186288f6a77944f2ee84dee2c4f230 main.cpp flags.h input.h | \\',
             '  tar -x -C build/performance/baseline-source',
             'g++ -O2 -std=c++11 -Wall -Wextra -Wpedantic -Werror \\',
             '  build/performance/baseline-source/main.cpp -o build/performance/SGB-before',
             'make build/SGB build/sgb-reference-large',
             'python3 benchmarks/performance_ensemble.py \\',
             '  --before build/performance/SGB-before --after build/SGB \\',
             '  --reference build/sgb-reference-large \\',
             '  --before-source build/performance/baseline-source \\',
             '  --after-commit e125fc59280927b8a69d65bafb51431952a87ff7 \\',
             '  --boost-version 1.83 --samples 20 --vertices 1000 3000 \\',
             '  --probabilities .0025 .005 .0075 .01 .0125 .015 \\',
             '  --timeout 120 --memory-gib 4 --cpus 1 2 3 --management-cpu 0 \\',
             '  --output audit/performance-ensemble-results.json',
             '```', '',
             'Add the same Boost include path to both builds if necessary. CPU numbers',
             'must exist in the process affinity mask; adapt them on other machines',
             'and keep the changed configuration in the recorded provenance. Allow',
             'enough time for the entire suite: many independent runs can each consume',
             'the full two-minute budget.', '',
             'Use the recorded command and settings in the raw JSON to repeat the full',
             'experiment. The generator records every seed and graph hash; regenerating',
             'the corpus checks the exact paired inputs. The runner supports an atomic',
             'checkpoint and validates source, executable, input, and setting provenance',
             'before resuming with `--resume`; a partial report is explicitly incomplete.',
             'Add `--export-inputs build/performance-ensemble-graphs.txt` to save the',
             'exact graph records. Use `--help` for the complete interface.', '',
             'With the recorded commits and binaries still available locally, verify',
             'all input hashes, output comparisons, provenance, and summary statistics:', '',
             '```sh',
             'python3 benchmarks/verify_ensemble.py',
             '```', '',
             'The benchmark runner needs only the Python standard library. Rendering',
             'the SVG additionally requires Matplotlib (this report used 3.10.8).',
             'After the full run, regenerate this document and its standalone SVG with:', '',
             '```sh',
             'MPLCONFIGDIR=/tmp/sgb-mpl python3 benchmarks/report_ensemble.py',
             '```', '',
             'The raw JSON is the source of the tables and plot. Historical benchmark',
             'reports retain their original methods, inputs, and time limits.', '']
    return '\n'.join(text)


def render_plot(report, output, preview=None):
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/sgb-mpl')
    os.environ.setdefault('XDG_CACHE_HOME', '/tmp/sgb-plot-cache')
    Path(os.environ['XDG_CACHE_HOME']).mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.rcParams['svg.hashsalt'] = 'sgb-performance-ensemble'
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    colors = {'before': '#385d8a', 'after': '#d57722'}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), layout='constrained')
    for ax, vertices in zip(axes, (1000, 3000)):
        groups = [group for group in rows(report) if group['vertices'] == vertices]
        for group in groups:
            p = group['probability']
            selected = sorted((case for case in report['cases'] if case['vertices'] == vertices
                               and case['probability'] == p), key=lambda case: case['sample_index'])
            for label, offset in (('before', -.033), ('after', .033)):
                center = 100 * p + offset
                for index, case in enumerate(selected):
                    observation = case[label]
                    x = center + .0022 * (index - 9.5)
                    timed_out = observation['status'] == 'timeout'
                    ax.scatter(x, 120 if timed_out else observation['wall_seconds'],
                               marker='^' if timed_out else 'o', s=25 if timed_out else 15,
                               color=colors[label], alpha=.65, linewidths=0)
                median = group[label]['quantiles']['median']
                if median['kind'] == 'exact':
                    ax.plot([center - .024, center + .024], [median['seconds']] * 2,
                            color='black', linewidth=1.6)
        if any(case[label]['status'] == 'timeout' for case in report['cases']
               if case['vertices'] == vertices for label in ('before', 'after')):
            ax.axhline(120, color='#777777', linewidth=.8, linestyle='--')
        ax.set_yscale('log')
        ax.set_title(f'{vertices:,} vertices', fontsize=13, fontweight='bold')
        ax.set_xticks([100 * group['probability'] for group in groups])
        ax.set_xlabel('Edge probability (%)')
        ax.set_ylabel('Seconds per graph (log scale)')
        ax.grid(axis='y', alpha=.18)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('20 distinct graphs per density • identical before/after inputs', fontsize=14)
    handles = [Line2D([], [], marker='o', color=colors[label], linestyle='', label=label.capitalize())
               for label in ('before', 'after')]
    handles += [Line2D([], [], marker='^', color='#777777', linestyle='', label='Timeout: >120 s'),
                Line2D([], [], color='black', linewidth=1.6, label='Exact sample median')]
    fig.legend(handles=handles, loc='outside lower center', ncol=4, frameon=False)
    fig.savefig(output, format='svg', metadata={'Date': None,
                'Description': 'Measured before/after times on 20 distinct graphs per density; timeouts are censored at 120 seconds.'})
    if preview is not None:
        fig.savefig(preview, dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'audit/performance-ensemble-results.json')
    parser.add_argument('--markdown', type=Path, default=ROOT / 'audit/performance-ensemble.md')
    parser.add_argument('--plot', type=Path, default=ROOT / 'audit/performance-ensemble.svg')
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    verify_report(report)
    markdown = render_markdown(report)
    render_plot(report, args.plot)
    args.markdown.write_text(markdown)
    print(f'Wrote {args.markdown} and {args.plot}')


if __name__ == '__main__':
    main()
