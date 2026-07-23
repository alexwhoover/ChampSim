#!/usr/bin/env python3
"""Correlate load cache misses with the cycles the pipeline spent stalled.

Reads the two traces emitted by the instrumented simulator:

    <prefix>load_misses.txt  one instr_id per L1D demand-load miss
    <prefix>load_stalls.txt  one instr_id per cycle the ROB head was not ready

where <prefix> is whatever was passed to the simulator's --stall-trace-prefix,
and reports which misses actually stalled the machine, and for how long.
"""

import sys
from collections import Counter
from itertools import groupby
from pathlib import Path


def read_ids(path):
    """Return the instruction IDs in a trace file, in order."""
    ids = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(int(line))
    return ids


def stall_runs(path):
    """Return (instr_id, consecutive_cycles) for each uninterrupted stall burst.

    An instruction can appear in more than one burst: the ROB head stays put
    while other instructions execute, and those cycles are not logged.
    """
    runs = []
    for instr_id, group in groupby(read_ids(path)):
        length = 0
        for _ in group:
            length += 1
        runs.append((instr_id, length))
    return runs


def analyze(miss_path, stall_path):
    # One instruction can issue several loads, so count rather than just collect
    miss_counts = Counter(read_ids(miss_path))

    total_cycles = Counter()  # instr_id -> cycles stalled at the ROB head
    bursts = Counter()        # instr_id -> number of separate stall bursts
    longest_burst = Counter() # instr_id -> longest single burst

    for instr_id, length in stall_runs(stall_path):
        total_cycles[instr_id] += length
        bursts[instr_id] += 1
        longest_burst[instr_id] = max(longest_burst[instr_id], length)

    return miss_counts, total_cycles, bursts, longest_burst


def report(miss_counts, total_cycles, bursts, longest_burst):
    stalled_ids = set(total_cycles)
    missed_ids = set(miss_counts)

    stalling_misses = missed_ids & stalled_ids
    silent_misses = missed_ids - stalled_ids
    stalls_without_miss = stalled_ids - missed_ids

    all_cycles = sum(total_cycles.values())
    miss_cycles = sum(total_cycles[i] for i in stalling_misses)

    def pct(part, whole):
        return f'{100.0 * part / whole:6.2f}%' if whole else '   n/a'

    print('=== Misses ===')
    print(f'  load misses (accesses)   {sum(miss_counts.values()):>12,}')
    print(f'  distinct instructions    {len(missed_ids):>12,}')
    print(f'  ...that stalled the ROB  {len(stalling_misses):>12,}  {pct(len(stalling_misses), len(missed_ids))}')
    print(f'  ...fully hidden          {len(silent_misses):>12,}  {pct(len(silent_misses), len(missed_ids))}')

    print('\n=== Stall cycles ===')
    print(f'  total stalled cycles     {all_cycles:>12,}')
    print(f'  ...on a missing load     {miss_cycles:>12,}  {pct(miss_cycles, all_cycles)}')
    print(f'  ...on something else     {all_cycles - miss_cycles:>12,}  {pct(all_cycles - miss_cycles, all_cycles)}')
    print(f'  distinct stalled instrs  {len(stalled_ids):>12,}')
    print(f'  ...with no load miss     {len(stalls_without_miss):>12,}  {pct(len(stalls_without_miss), len(stalled_ids))}')

    if stalling_misses:
        cycles = sorted(total_cycles[i] for i in stalling_misses)
        mean = sum(cycles) / len(cycles)
        print('\n=== Stall length, missing loads only ===')
        print(f'  mean {mean:.1f}  median {cycles[len(cycles) // 2]}  '
              f'p90 {cycles[int(len(cycles) * 0.90)]}  p99 {cycles[int(len(cycles) * 0.99)]}  max {cycles[-1]}')


def main():
    args = sys.argv[1:]
    prefix = args[0] if len(args) > 0 else ''

    miss_path = Path(prefix + 'load_misses.txt')
    stall_path = Path(prefix + 'load_stalls.txt')

    for path in (miss_path, stall_path):
        if not path.exists():
            print(f'{sys.argv[0]}: {path} not found', file=sys.stderr)
            print(f'Usage: {sys.argv[0]} [prefix]', file=sys.stderr)
            return 1

    results = analyze(miss_path, stall_path)
    report(*results)
    return 0


if __name__ == '__main__':
    sys.exit(main())
