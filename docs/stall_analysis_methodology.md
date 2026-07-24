# L1D Load-Miss Stall Analysis: Methodology

**Purpose.** Quantify how many processor stall cycles are actually caused by demand
loads that miss the L1 data cache — i.e. the headroom a better L1D prefetcher could
recover — as distinct from memory latency the out-of-order engine already hides.

The mechanism has two parts: fork-local instrumentation compiled into ChampSim that
emits two trace files, and a Python script (`python_scripts/analyze_stalls.py`) that
joins them. All instrumentation is bracketed with `[STALL TRACE]` begin/end rulers so
the boundary against upstream ChampSim code is unambiguous (`grep -rn "\[STALL TRACE\]"
inc src`).

---

## 1. Simulator edits

### 1.1 Trace-prefix plumbing

| File | Change |
|---|---|
| `inc/champsim.h` | Declares `extern std::string STALL_TRACE_PREFIX`. |
| `src/main.cc` | Defines the global and registers a `--stall-trace-prefix <p>` CLI option. The two traces are written as `<p>load_misses.txt` and `<p>load_stalls.txt`. |

Invocation:

```bash
bin/<exe> --stall-trace-prefix results/foo_ <other args> <trace>
python3 python_scripts/analyze_stalls.py results/foo_
```

### 1.2 Miss trace — `<prefix>load_misses.txt`

One `instr_id` per L1D demand-load miss.

- **Location:** `CACHE::handle_miss` in `src/cache.cc`, immediately after
  `sim_stats.misses.increment(...)`.
- **Predicate:** `!warmup && type == access_type::LOAD && NAME contains "L1D"`.
- **Why `handle_miss` and not `try_hit`:** `try_hit` re-runs every cycle on any packet
  whose miss handling failed (MSHR full, or the lower-level queue full), so logging
  there counts a single miss once per retry and inflates the total. `handle_miss` is
  reached exactly once per miss — the same point where `sim_stats.misses` ticks — so the
  file's line count matches the simulator's `L1D LOAD ... MISS` counter exactly.

```cpp
// src/cache.cc, in CACHE::handle_miss, immediately after sim_stats.misses.increment(...)

// Only record real misses we care about:
//   !warmup                      -> ignore the warmup phase; only the measured phase counts
//   type == access_type::LOAD    -> demand loads only (not prefetches, stores, or translations)
//   NAME contains "L1D"          -> this generic CACHE class is reused for every level; keep L1D only
if (!warmup && handle_pkt.type == access_type::LOAD && NAME.find("L1D") != std::string::npos) {
  // Open the output file once, the first time this line runs, and keep it open for the whole run.
  static std::ofstream miss_trace{STALL_TRACE_PREFIX + "load_misses.txt"};
  // Write the ID of the instruction whose load just missed, one per line. That ID is the
  // join key used later to match this miss against the ROB-head stall trace.
  miss_trace << handle_pkt.instr_id << '\n';
}
```

### 1.3 Stall trace — `<prefix>load_stalls.txt`

One record `"<instr_id> <cycles>"` per uninterrupted burst during which that instruction
sat at the ROB head blocked on memory.

- **Location:** `O3_CPU::execute_instruction` in `src/ooo_cpu.cc`, with the running burst
  held in the member fields `O3_CPU::stall_head_id` / `stall_head_cycles`.
- **Predicate:** `ROB.front().executed && !ROB.front().completed &&
  !ROB.front().source_memory.empty()`.

  For a load, `executed` means the address was computed and the request was issued to the
  L1D; `completed` means the data returned. A cache miss therefore holds the ROB head in
  the window *between* the two, which is exactly the condition ChampSim already counts as
  `execute_load_blocked_cycles`. The related counter `execute_head_not_ready`
  (`!executed`) is a **register-dependency** stall, essentially uncorrelated with the
  cache — tracing it yields a near-zero result and was the original error.
- **Outside the execute-bandwidth guard:** the probe deliberately sits *outside* the
  `if (exec_bw.amount_consumed() == 0)` block, so it samples every cycle the head load is
  blocked, including cycles where other instructions still executed out-of-order. As a
  result `total stalled cycles` is **≥** the simulator's `Execute Load Blocked Cycles`
  (which is the bandwidth-guarded subset); the gap is the out-of-order-overlapped blocked
  cycles.
- **Burst encoding:** rather than emitting one line per cycle, consecutive cycles with
  the same head `instr_id` are accumulated into `stall_head_cycles` and flushed as a
  single record when the head changes or unblocks. A single instruction may appear in
  several bursts, because the ROB head can stall, resume, and re-stall.

```cpp
// src/ooo_cpu.cc, in O3_CPU::execute_instruction, after the exec-bandwidth guarded block.
// This runs once per cycle. stall_head_id / stall_head_cycles are O3_CPU members, so their
// values carry over from one cycle to the next -- that is how we accumulate a burst.
if (!warmup) {  // only measure the real phase, not warmup
  // Open the output file once and keep it open for the whole run.
  static std::ofstream stall_trace{STALL_TRACE_PREFIX + "load_stalls.txt"};

  // Is the oldest instruction (ROB head) stuck this cycle waiting on a memory load?
  //   !ROB.empty()          -> there is an instruction to look at
  //   executed              -> its address is computed and the load was sent to the L1D
  //   !completed            -> the data has not come back yet
  //   !source_memory.empty  -> it actually is a load (has a memory source), not some other op
  const bool blocked = !ROB.empty() && ROB.front().executed && !ROB.front().completed && !std::empty(ROB.front().source_memory);
  // The ID of that stuck instruction (or a placeholder 0 if nothing is blocked this cycle).
  const auto head_id = blocked ? ROB.front().instr_id : ooo_model_instr::id_type{};

  // A "burst" is a run of consecutive cycles the same instruction is stuck at the head.
  // If we are no longer blocked, or a *different* instruction is now stuck, the previous
  // burst has ended -- so flush it and start counting a new one.
  if (!blocked || head_id != stall_head_id) {
    if (stall_head_cycles > 0) {
      // Write "<instr_id> <how many cycles it was stuck>" for the burst that just finished.
      stall_trace << stall_head_id << ' ' << stall_head_cycles << '\n';
    }
    stall_head_id = head_id;   // remember who is stuck now
    stall_head_cycles = 0;     // reset the per-burst cycle counter
  }
  // If we are still blocked this cycle, add one more cycle to the current burst.
  if (blocked) {
    ++stall_head_cycles;
  }
}
```

---

## 2. `analyze_stalls.py` methodology

The script joins the two files on `instr_id`; no cycle timestamps are used.

**Definitions.**

- **M** = set of instruction IDs that had an L1D load miss (`load_misses.txt`). One
  instruction can miss more than once, but for the partition only membership matters.
- For each instruction *i*, **c(i)** = the cycles it spent blocked at the ROB head, i.e.
  the sum of its burst lengths from `load_stalls.txt`. **S** = { i : c(i) > 0 } is the set
  of instructions that ever stalled.

**Total stalled cycles.**

$$T \;=\; \sum_{i \in S} c(i)$$

**Partition**, by whether the blocking instruction is in M — reported by the script as
`...load missed L1D` and `...load hit L1D`:

$$\underbrace{T_{\text{miss}} = \sum_{i \in S \cap M} c(i)}_{\texttt{...load missed L1D}}
\qquad\qquad
\underbrace{T - T_{\text{miss}} = \sum_{i \in S \setminus M} c(i)}_{\texttt{...load hit L1D}}$$

The reported percentages are $T_{\text{miss}}/T$ and $1 - T_{\text{miss}}/T$.

**Why the remainder is `...load hit L1D`, not "other stalls".** The stall predicate only
fires when the ROB head is a load waiting for its data (`source_memory` non-empty), so
every cycle in *T* is already a load waiting on memory. The split is therefore purely by
cache outcome:

- $i \in M$ → that load **missed** L1D → counts toward `...load missed L1D`.
- $i \notin M$ → that load **hit** L1D → counts toward `...load hit L1D`.

So `...load hit L1D` is **cycles the head stalled on a load that hit the L1D** — the
instruction reached the ROB head before its short hit latency elapsed and briefly blocked
retirement anyway. A better L1D prefetcher cannot remove those; it can only attack
$T_{\text{miss}}$. That makes $T_{\text{miss}}/T$ the **prefetch-headroom fraction** and the
remainder the irreducible hit-latency floor.

**Also reported** (secondary): miss coverage — the fraction of distinct misses in M that
ever appear in S (how often a miss stalls the head at all) — and the stall-length
distribution (mean / median / p90 / p99 / max) of c(i) over $i \in S \cap M$.

---

## 3. Validation

Every run is cross-checked against the simulator's own final statistics:

| `analyze_stalls.py` field | must match ChampSim stat | relation |
|---|---|---|
| `load misses (accesses)` | `L1D LOAD ... MISS` | equal |
| `total stalled cycles` | `Execute Load Blocked Cycles` | ≥ (probe is outside the exec-bandwidth guard) |

The miss count matching exactly confirms the retry-inflation bug is absent; the stall
total exceeding the guarded counter by the expected margin confirms the probe predicate
and placement.

---

## 4. Interpretation and limitations

- **Attribution, not recoverable cycles.** Under memory-level parallelism several misses
  are outstanding at once, but only the ROB-head miss is credited each cycle. The
  miss-attributed cycle count is therefore an **upper bound** on what a perfect L1D could
  recover — removing one miss often exposes the next — and per-miss stall cycles do not
  sum to a speedup estimate.
- **No per-cycle overlap check.** The join is by `instr_id` only. When an instruction has
  both a hitting and a missing load, the whole stall is credited to the miss.
- **Merges counted as fills.** An MSHR-merged load (waiting on a fill already requested by
  another access) is counted the same as a fresh miss, and an L2 hit the same as a DRAM
  trip, so the "prefetchable" figure is a further upper bound.
- **Single-core only.** The `static std::ofstream`s are shared across cores and
  `instr_id`s collide between them; the `NAME.find("L1D")` filter also does not
  distinguish per-core L1Ds.
- **Final burst not flushed.** The stall burst in flight when simulation ends is never
  written, so stalled cycles can be short by one record.
