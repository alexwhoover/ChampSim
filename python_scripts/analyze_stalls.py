#!/usr/bin/env python3
"""Correlate load cache misses with the cycles the pipeline spent stalled.

Reads the two traces emitted by the instrumented simulator:

    <prefix>load_misses.txt  one instr_id per L1D demand-load miss
    <prefix>load_stalls.txt  "<instr_id> <cycles>" per instruction that blocked the
                             ROB head waiting on memory, and for how many cycles

where <prefix> is whatever was passed to the simulator's --stall-trace-prefix,
and reports which misses actually stalled the machine, and for how long.

The simulator side of this is fork-local instrumentation: grep the C++ sources for
"[STALL TRACE]" to find every site that writes or configures these two files.

Two sanity checks against the simulator's own output: the reported miss count
should equal the L1D LOAD MISS statistic, and the total stalled cycles should
equal Execute Load Blocked Cycles (short by at most one record, since the burst
in flight when the simulation ends is never written out).
"""

import sys
from collections import Counter
from pathlib import Path


def count_ids(path):
    """Count occurrences of each instruction ID in a trace file.

    Streams the file line by line so nothing larger than the resulting Counter is
    ever held in memory (these traces have one line per L1D demand-load miss).
    """
    counts = Counter()  # instr_id -> number of misses
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                counts[int(line)] += 1
    return counts


def sum_stalls(path):
    """Sum stall cycles per instruction ID.

    An instruction contributes exactly one record: a load is executed before it is
    completed and neither flag is ever reset, so once the head blocks on memory it
    stays blocked until its data returns, at which point it retires. Streamed line
    by line so only the per-instruction totals live in memory.
    """
    total_cycles = Counter()  # instr_id -> cycles spent blocking the ROB head
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                total_cycles[int(parts[0])] += int(parts[1])
    return total_cycles


def analyze(miss_path, stall_path):
    # One instruction can issue several loads, so count rather than just collect
    miss_counts = count_ids(miss_path)
    total_cycles = sum_stalls(stall_path)
    return miss_counts, total_cycles


def report(miss_counts, total_cycles):
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

    hit_cycles = all_cycles - miss_cycles
    print('\n=== Stall cycles (ROB head blocked on a load) ===')
    print(f'  {"total stalled cycles":<30}{all_cycles:>12,}')
    print(f'  {"...load missed L1D":<30}{miss_cycles:>12,}  {pct(miss_cycles, all_cycles)}')
    print(f'  {"...load hit L1D":<30}{hit_cycles:>12,}  {pct(hit_cycles, all_cycles)}')
    print(f'  {"distinct stalled instrs":<30}{len(stalled_ids):>12,}')
    print(f'  {"...load hit L1D (no miss)":<30}{len(stalls_without_miss):>12,}  {pct(len(stalls_without_miss), len(stalled_ids))}')

    if stalling_misses:
        cycles = sorted(total_cycles[i] for i in stalling_misses)
        mean = sum(cycles) / len(cycles)

        def pctl(q):
            return cycles[min(int(len(cycles) * q), len(cycles) - 1)]

        print('\n=== Stall length, missing loads only ===')
        print(f'  mean {mean:.1f}  median {pctl(0.50)}  '
              f'p90 {pctl(0.90)}  p99 {pctl(0.99)}  max {cycles[-1]}')


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print(f'Usage: {sys.argv[0]} <load_misses.txt> <load_stalls.txt>', file=sys.stderr)
        return 1

    miss_path = Path(args[0])
    stall_path = Path(args[1])

    for path in (miss_path, stall_path):
        if not path.exists():
            print(f'{sys.argv[0]}: {path} not found', file=sys.stderr)
            print(f'Usage: {sys.argv[0]} <load_misses.txt> <load_stalls.txt>', file=sys.stderr)
            return 1

    results = analyze(miss_path, stall_path)
    report(*results)
    return 0


if __name__ == '__main__':
    sys.exit(main())
