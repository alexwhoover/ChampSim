#ifndef CORE_STATS_H
#define CORE_STATS_H

#include <cstdint>
#include <string>

#include "event_counter.h"
#include "instruction.h"

struct cpu_stats {
  std::string name;
  long long begin_instrs = 0;
  long long begin_cycles = 0;
  long long end_instrs = 0;
  long long end_cycles = 0;
  uint64_t total_rob_occupancy_at_branch_mispredict = 0;

  // Per-stage idle-cycle counters, ported from PrincetonUniversity/ChampSim
  // (https://github.com/PrincetonUniversity/ChampSim/blob/master/inc/ooo_cpu.h)
  uint64_t fetch_idle_cycles = 0;
  uint64_t fetch_failed_events = 0;
  uint64_t fetch_buffer_not_empty = 0;
  uint64_t fetch_blocked_cycles = 0;
  uint64_t decode_idle_cycles = 0;
  uint64_t execute_idle_cycles = 0;
  uint64_t execute_none_cycles = 0;
  uint64_t execute_head_not_ready = 0;
  uint64_t execute_head_not_completed = 0;
  uint64_t execute_pending_cycles = 0;
  uint64_t execute_load_blocked_cycles = 0;
  uint64_t sched_idle_cycles = 0;
  uint64_t sched_none_cycles = 0;
  uint64_t dispatch_idle_cycles = 0;
  uint64_t rob_idle_cycles = 0;
  uint64_t lq_full_events = 0;
  uint64_t sq_full_events = 0;

  champsim::stats::event_counter<branch_type> total_branch_types = {};
  champsim::stats::event_counter<branch_type> branch_type_misses = {};

  [[nodiscard]] auto instrs() const { return end_instrs - begin_instrs; }
  [[nodiscard]] auto cycles() const { return end_cycles - begin_cycles; }
};

cpu_stats operator-(cpu_stats lhs, cpu_stats rhs);

#endif
