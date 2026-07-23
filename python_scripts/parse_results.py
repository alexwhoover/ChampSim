#!/usr/bin/env python3
"""Parse ChampSim output files and report key performance metrics."""

import re
import sys
from pathlib import Path

# Caches to report, in order. TLBs excluded — no prefetcher and not the focus.
CACHE_ORDER = ['cpu0_L1I', 'cpu0_L1D', 'cpu0_L2C', 'LLC']
DISPLAY_NAMES = {
    'cpu0_L1I': 'L1I',
    'cpu0_L1D': 'L1D',
    'cpu0_L2C': 'L2C',
    'LLC':      'LLC',
}

ACCESS_RE = re.compile(
    r'cpu\d+->([\w]+)\s+(TOTAL|LOAD|RFO|PREFETCH|WRITE|TRANSLATION)\s+'
    r'ACCESS:\s+(\d+)\s+HIT:\s+(\d+)\s+MISS:\s+(\d+)'
)
PREFETCH_RE = re.compile(
    r'cpu\d+->([\w]+)\s+PREFETCH REQUESTED:\s+\d+\s+ISSUED:\s+\d+\s+'
    r'USEFUL:\s+(\d+)\s+USELESS:\s+(\d+)'
)
LATENCY_RE = re.compile(
    r'cpu\d+->([\w]+)\s+AVERAGE MISS LATENCY:\s+([\d.]+)\s+cycles'
)
SIM_COMPLETE_RE = re.compile(
    r'Simulation complete CPU \d+ instructions:\s+(\d+)\s+cycles:\s+\d+\s+cumulative IPC:\s+([\d.]+)'
)


def parse(filepath):
    text = Path(filepath).read_text()

    m = SIM_COMPLETE_RE.search(text)
    instructions = int(m.group(1)) if m else None
    ipc = float(m.group(2)) if m else None

    caches = {}
    for m in ACCESS_RE.finditer(text):
        name, atype = m.group(1), m.group(2)
        caches.setdefault(name, {})
        caches[name][atype] = {
            'access': int(m.group(3)),
            'hit':    int(m.group(4)),
            'miss':   int(m.group(5)),
        }

    for m in PREFETCH_RE.finditer(text):
        name = m.group(1)
        caches.setdefault(name, {})
        caches[name]['_pref_useful']  = int(m.group(2))
        caches[name]['_pref_useless'] = int(m.group(3))

    for m in LATENCY_RE.finditer(text):
        name = m.group(1)
        caches.setdefault(name, {})
        caches[name]['_miss_latency'] = float(m.group(2))

    return {
        'ipc': ipc,
        'instructions': instructions,
        'caches': caches,
    }


def fmt_pct(value):
    return f"{value * 100:.2f}%" if value is not None else "—"

def fmt_f(value, decimals=3):
    return f"{value:.{decimals}f}" if value is not None else "—"


def report(filepath):
    data = parse(filepath)
    instr = data['instructions'] or 0

    print(f"File: {filepath}")
    print(f"  IPC:  {fmt_f(data['ipc'], 4)}")
    print()

    col_w = [6, 16, 12, 16, 16, 14]
    headers = ['Cache', 'Load Hit Rate', 'Load MPKI', 'Pref Accuracy', 'Pref Coverage', 'Miss Latency']
    row_fmt = '  '.join(f"{{:<{w}}}" if i == 0 else f"{{:>{w}}}" for i, w in enumerate(col_w))
    print(row_fmt.format(*headers))
    print('  ' + '-' * (sum(col_w) + 2 * (len(col_w) - 1)))

    for key in CACHE_ORDER:
        if key not in data['caches']:
            continue
        c = data['caches'][key]
        display = DISPLAY_NAMES.get(key, key)

        load = c.get('LOAD', {})
        load_access = load.get('access', 0)
        load_hit    = load.get('hit', 0)
        load_miss   = load.get('miss', 0)

        hit_rate = load_hit / load_access if load_access > 0 else None
        mpki     = load_miss / instr * 1000 if instr > 0 and load_access > 0 else None

        useful  = c.get('_pref_useful', 0)
        useless = c.get('_pref_useless', 0)
        accuracy = useful / (useful + useless) if (useful + useless) > 0 else None
        # Coverage: fraction of potential misses eliminated by useful prefetches.
        # Only meaningful when the prefetcher is active (useful+useless > 0).
        coverage = useful / (useful + load_miss) if (useful + useless) > 0 and (useful + load_miss) > 0 else None

        miss_latency = c.get('_miss_latency')
        latency_str = f"{miss_latency:.1f} cy" if miss_latency is not None else "—"

        print(row_fmt.format(
            display,
            fmt_pct(hit_rate),
            fmt_f(mpki, 3),
            fmt_pct(accuracy),
            fmt_pct(coverage),
            latency_str,
        ))

    print()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <output_file> [output_file ...]")
        sys.exit(1)
    for f in sys.argv[1:]:
        report(f)
