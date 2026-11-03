#!/usr/bin/env python3
"""Verify and summarize the paired SGB comparison at p = 0.6 / sqrt(n)."""

import hashlib
import itertools
import json
import math
from pathlib import Path
import random

from verify_adaptive import atomic_write, verify_paired
from run import require, sha256


ROOT = Path(__file__).resolve().parent.parent


def regenerate(case):
    n = case['vertices']
    rng = random.Random(case['seed'])
    edges = [f'({a},{b})' for a, b in itertools.combinations(range(1, n + 1), 2)
             if rng.random() < .6 / math.sqrt(n)]
    line = '[' + ','.join(map(str, range(1, n + 1))) + '] [' + ','.join(edges) + ']'
    digest = hashlib.sha256(line.encode()).hexdigest()
    require(digest == case['input_sha256'] and len(edges) == case['edges'],
            'Independent input regeneration mismatch: ' + case['name'])
    require(case['actual_density'] == 2 * len(edges) / (n * (n - 1)) and
            case['average_degree'] == 2 * len(edges) / n, 'Input metadata mismatch')
    return dict(name=case['name'], input_sha256=digest, edges=len(edges))


def main():
    destination = ROOT / 'audit/performance-alpha06-validation.json'
    evidence = dict(completed=False, verifier_sha256=sha256(Path(__file__)))
    atomic_write(destination, evidence)
    try:
        reports, verified = [], {}
        evidence['studies'] = []
        for n in (1000, 3000):
            path = ROOT / f'audit/performance-alpha06-n{n}.json'
            digest = sha256(path)
            report = json.loads(path.read_text())
            checked = verify_paired(report, ((n, .6 / math.sqrt(n)),), verified)
            checked['regenerated_inputs'] = [regenerate(case) for case in report['cases']]
            checked['report_sha256'] = digest
            checked['vertices'] = n
            require(sha256(path) == digest, 'Raw report changed during verification')
            evidence['studies'].append(checked)
            reports.append(report)
        require(len({case['input_sha256'] for report in reports for case in report['cases']}) == 40,
                'Expected 40 distinct input graphs')
        for key in ('before_commit', 'after_commit', 'source_sha256', 'binary_sha256',
                    'compiler_version', 'compiler_flags', 'boost_version',
                    'reference_binary_sha256', 'reference_source_sha256',
                    'runner_sha256', 'imported_runner_sha256'):
            require(reports[0]['provenance'][key] == reports[1]['provenance'][key],
                    'Study provenance mismatch: ' + key)
        evidence.update(completed=True, verified_files_sha256=verified,
                        verifier_helper_sha256={name: sha256(ROOT / 'benchmarks' / name)
                            for name in ('verify_adaptive.py', 'verify_ensemble.py',
                                         'performance_large.py', 'run.py')})
        atomic_write(destination, evidence)
        text = [
            '# SGB at the thickness benchmark density', '',
            'This comparison fixes **alpha = 0.6**, so `p = 0.6 / sqrt(n)`, at',
            '1,000 and 3,000 vertices. Each size uses 20 distinct deterministic graphs,',
            'with identical inputs for the before and after versions. The baseline is',
            'the previously optimized `0ebc8fe`; the adaptive implementation is `3797211`.',
            'Application sources and executables are unchanged from the earlier',
            '[adaptive-search comparison](performance-adaptive.md). These are new',
            'measurements at the requested probabilities, not interpolated results.', '',
            '| Vertices | Edge probability | Before median (s) | After median (s) | Median paired speedup | Completed before / after |',
            '| ---: | ---: | ---: | ---: | ---: | --- |',
        ]
        for report in reports:
            g = report['groups'][0]
            require(all(g[label]['counts']['ok'] == 20 for label in ('before', 'after')),
                    'This report template requires all runs to complete; revise censoring presentation')
            text.append(f"| {g['vertices']:,} | {100*g['probability']:.6f}% | "
                        f"{g['before']['completed_only']['median_seconds']:.6g} | "
                        f"{g['after']['completed_only']['median_seconds']:.6g} | "
                        f"{g['paired_speedup']['median']:.4g}x | 20 / 20 |")
        text += ['', 'All 80 runs finished within the two-minute budget and matched the independent',
                 'reference; all 40 pairs had identical CSV. Speedup is the median of the',
                 '20 within-graph ratios, which can differ from the ratio of group medians.', '',
                 '## Interpretation', '',
                 'This density is precisely in the fixed-alpha regime where the old adjacency-list',
                 'walk had cubic leading expected search work and the new common-neighbor search',
                 'has quadratic expected enumeration work. The missing-edge search is intended',
                 'for nearly complete graphs. See the [algorithm analysis](adaptive-search.md)',
                 'for the proof, selector heuristic, and component/support costs.', '',
                 'These two whole-program timing groups measure practical speed at the requested',
                 'density. They do not independently prove an asymptotic exponent. The earlier',
                 'instrumented scaling study used alpha=0.5; the mathematical fixed-alpha bound',
                 'also applies at alpha=0.6. Arbitrary fixed positive densities can have',
                 'quartically many induced squares.', '',
                 '## Protocol and evidence', '',
                 'Each build has one fresh-process `-tf` measurement per graph, including startup,',
                 'parsing, analysis, output, and cleanup. The limit is 120 seconds and 4 GiB',
                 'of virtual address space per process. Workers use CPUs 1, 2, and 3; the',
                 'supervisor uses CPU 0. Before/after order alternates by sample index.',
                 'Graph generation and reference analysis are outside the measured interval.',
                 'The shared host and one timing per graph limit precision and portability.', '',
                 '- [1,000-vertex raw results](performance-alpha06-n1000.json).',
                 '- [3,000-vertex raw results](performance-alpha06-n3000.json).',
                 '- [Independent artifact verification](performance-alpha06-validation.json).', '',
                 'The raw records retain exact probabilities, actual densities, seeds, hashes,',
                 'all timings, reference structures, and build provenance. Verification',
                 'independently regenerates all 40 inputs, revalidates every output, checks',
                 'current and committed sources and executable hashes, and recomputes summary',
                 'statistics. Existing normal/sanitizer validation remains applicable because',
                 'the measured application and test sources have not changed.', '',
                 '## Reproduce', '',
                 'Use the builds and common runner arguments from the earlier adaptive report.',
                 'Run each size separately, with these vertex/probability/output arguments:', '',
                 '```sh',
                 '--vertices 1000 --probabilities 0.018973665961010275 --samples 20 --output audit/performance-alpha06-n1000.json',
                 '--vertices 3000 --probabilities 0.01095445115010332 --samples 20 --output audit/performance-alpha06-n3000.json',
                 '```', '', 'After both studies finish, verify and render this report:', '',
                 '```sh', 'python3 benchmarks/report_alpha06.py', '```', '']
        (ROOT / 'audit/performance-alpha06.md').write_text('\n'.join(text))
        print('PASS: 40 independently regenerated graphs, 80 outputs, paired statistics and provenance')
    except BaseException as error:
        evidence.update(completed=False, error=str(error))
        atomic_write(destination, evidence)
        raise


if __name__ == '__main__':
    main()
