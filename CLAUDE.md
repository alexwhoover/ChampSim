# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ChampSim: a trace-driven microarchitecture simulator (C++17). This fork is used for thesis work on data prefetching — it adds prefetcher modules (`prefetcher/BertiGo`, `bertigo_pythia`, `berti`, `pythia`, `ANeLin`), DPC4 competition submissions under `DPC4_code_submissions/`, machine configs in `thesis_configurations/`, Slurm launch scripts in `run_shell_scripts/`, collected simulator output in `results/`, and analysis scripts in `python_scripts/` (`parse_results.py`, `analyze_stalls.py`).

## Build workflow

The build is two-phase: a Python configurator generates makefile fragments and glue code, then `make` compiles.

```bash
# one-time dependency setup (Catch2, fmt, etc. via vcpkg submodule)
git submodule update --init && vcpkg/bootstrap-vcpkg.sh && vcpkg/vcpkg install

./config.sh <config.json>     # generates .csconfig/, absolute.options, generated_environment.cc
make -j$(nproc)               # produces bin/<executable_name>
```

Key points:
- `executable_name` in the JSON determines the binary path, so `bin/champsim` is only the default. `thesis_configurations/1C.fullBW.bertigo.json` builds `bin/1C.fullBW.bertigo`.
- **Always re-run `./config.sh` after changing a JSON config or adding a new module directory.** Editing module `.cc`/`.h` files alone only needs `make`.
- `config.sh` accepts multiple JSON files (`--join product|chain`) and extra module search paths (`--module-dir`, `--prefetcher-dir`, …). Later files win.
- `make clean` removes objects; `make configclean` also drops generated configuration.

## Running

```bash
bin/<exe> --warmup-instructions 200000000 --simulation-instructions 500000000 path/to/trace.champsimtrace.xz
python3 python_scripts/parse_results.py <output.txt>   # summarizes IPC, per-cache hit/miss, prefetch usefulness
```

Long runs go through Slurm; `run_shell_scripts/<workload>_<config>` are sbatch scripts (they build the binary if missing). Note their hardcoded `CHAMPSIM_DIR`/`TRACE` paths refer to the cluster, not this checkout.

## Stall analysis

Fork-local instrumentation that answers "how many stalled cycles were actually caused by an L1D load miss?" — i.e. how much headroom a better prefetcher has, versus latency the out-of-order engine already tolerates. **Grep `[STALL TRACE]` across `inc/` and `src/` to find every site**; the blocks in `.cc` files are bracketed with `begin`/`end` rulers so the boundary against upstream code is unambiguous.

```bash
bin/<exe> --stall-trace-prefix results/foo_ <other args> <trace>   # emits the two traces
python3 python_scripts/analyze_stalls.py results/foo_             # joins them
```

Two files, joined on `instr_id`:

- `<prefix>load_misses.txt` — one ID per L1D demand-load miss, written in `CACHE::handle_miss` (`src/cache.cc`). It must be logged there and **not** in `try_hit`: `try_hit` re-runs every cycle on packets whose miss handling failed (MSHR or lower-level queue full), so logging there double-counts, while `sim_stats.misses` only ticks once.
- `<prefix>load_stalls.txt` — `"<instr_id> <cycles>"` per instruction that blocked the ROB head waiting on memory, written in `O3_CPU::execute_instruction` (`src/ooo_cpu.cc`), with the running count held in `O3_CPU::stall_head_id`/`stall_head_cycles`.

**The predicate is the part that's easy to get wrong.** For a load, `executed` means the address was computed and the request went to the L1D; `completed` means the data came back. A cache miss therefore holds the ROB head in the window *between* the two, so the condition is `executed && !completed && !source_memory.empty()` — the same thing `execute_load_blocked_cycles` counts. `!executed` (`execute_head_not_ready`) is a register-dependency stall and has essentially nothing to do with the cache; tracing it yields a near-zero correlation. The check must also sit **outside** the `exec_bw.amount_consumed() == 0` guard, or stalls are only sampled on cycles when nothing anywhere in the window executed.

Validate every run against the simulator's own output before trusting the percentages:

| `analyze_stalls.py` | must equal ChampSim stat |
|---|---|
| `load misses (accesses)` | `L1D LOAD ... MISS` |
| `total stalled cycles` | `Execute Load Blocked Cycles` |

Limitations: single-core only (the `static std::ofstream`s are shared across instances and `instr_id`s collide between cores); the burst in flight when simulation ends is never flushed, so stalled cycles can be short by one record; and an L2 hit is counted the same as a DRAM trip, so the "prefetchable" figure is an upper bound.

## Tests

```bash
make test                      # builds test/bin/000-test-main (Catch2) and runs it
make test TEST_NUM=040         # run only tests whose source file starts with that number
make pytest                    # unittest suite for the config/ Python package
```

C++ unit tests live in `test/cpp/src/NNN-name.cc` and are selected by the numeric prefix, which becomes a Catch2 tag. `test/config/compile-only/*.json` are configurations exercised by CI only for successful configure+compile.

## Architecture

**Core loop.** `src/main.cc` builds the environment and drives everything through `champsim::operable` — every component (`O3_CPU`, `CACHE`, `PageTableWalker`, `MEMORY_CONTROLLER`) implements `operate()` and is ticked each cycle at its own clock frequency (see `inc/operable.h`, `inc/chrono.h`). `src/ooo_cpu.cc` is the out-of-order pipeline; `src/cache.cc` is the generic cache used for L1I/L1D/L2C/LLC/TLBs alike — the level's behavior comes entirely from its configured sizes, latencies, and attached modules.

**Component wiring is generated, not hand-written.** `config/parse.py` reads the JSON, applies `config/defaults.py`, and `config/instantiation_file.py` + `config/makefile.py` emit `src/generated_environment.cc` and `.csconfig/*.mk`. That generated environment is what constructs and connects the caches, so there is no static topology file to read — to understand a build's structure, read the JSON and, if needed, the generated `src/generated_environment.cc`. Components communicate over `champsim::channel` queues (RQ/WQ/PQ + MSHRs), defined in `inc/channel.h`.

**Modules (prefetchers, branch predictors, BTBs, replacement policies)** are compiled directly into the binary, selected by name in the JSON. Each lives in `<kind>/<name>/` and is found by directory name. Modern modules are classes deriving from `champsim::modules::prefetcher` / `branch_predictor` / `btb` / `replacement` (`inc/modules.h`); the base uses SFINAE detection, so you implement only the hooks you need (`prefetcher_cache_operate`, `prefetcher_cache_fill`, `prefetcher_cycle_operate`, `prefetcher_final_stats`, …) and omitted ones compile away. `prefetcher/next_line` is the cleanest template. Legacy free-function modules are still supported via a generated `legacy_bridge`.

When a directory holds a namespaced or non-default class, name it explicitly in the config:

```json
"L2C": { "prefetcher": { "path": "bertigo_pythia", "class": "bertigo_pythia::pythia" } }
```

`"compile_all_modules"` (default on) means every module in the search path is compiled even if unused — a compile error in any prefetcher directory breaks all builds. Newly added modules under `DPC4_code_submissions/` are only picked up if that path is passed to `config.sh` as a module dir.

**Addresses are typed.** `champsim::address` (`inc/address.h`) with `champsim::extent`/`address_slice` replaces raw `uint64_t`. Prefer the typed API; `uint64_t` overloads exist but are `[[deprecated]]`.

**Stats** are collected per-phase (`inc/phase_info.h`) and rendered by `src/plain_printer.cc` (the text output `parse_results.py` scrapes) or `src/json_printer.cc` (`--json`). Only the simulation phase, not warmup, appears in final stats.

## Conventions

- C++17, built with `-Wall -Wextra -Wshadow -Wpedantic -Wconversion` (see `global.options`); module TUs also get `-DCHAMPSIM_MODULE`.
- Formatting is enforced by `.clang-format` (LLVM base, 160 columns, regrouped includes) over `src inc prefetcher branch replacement btb test tracer`. Run `clang-format -i` on files you touch.
- Upstream default branch is `develop`; this fork works on `master`.
