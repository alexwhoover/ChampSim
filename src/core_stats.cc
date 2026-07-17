#include "core_stats.h"

cpu_stats operator-(cpu_stats lhs, cpu_stats rhs)
{
  lhs.begin_instrs -= rhs.begin_instrs;
  lhs.begin_cycles -= rhs.begin_cycles;
  lhs.end_instrs -= rhs.end_instrs;
  lhs.end_cycles -= rhs.end_cycles;
  lhs.total_rob_occupancy_at_branch_mispredict -= rhs.total_rob_occupancy_at_branch_mispredict;

  // Idle-cycle counters, ported from PrincetonUniversity/ChampSim
  lhs.fetch_idle_cycles -= rhs.fetch_idle_cycles;
  lhs.fetch_failed_events -= rhs.fetch_failed_events;
  lhs.fetch_buffer_not_empty -= rhs.fetch_buffer_not_empty;
  lhs.fetch_blocked_cycles -= rhs.fetch_blocked_cycles;
  lhs.decode_idle_cycles -= rhs.decode_idle_cycles;
  lhs.execute_idle_cycles -= rhs.execute_idle_cycles;
  lhs.execute_none_cycles -= rhs.execute_none_cycles;
  lhs.execute_head_not_ready -= rhs.execute_head_not_ready;
  lhs.execute_head_not_completed -= rhs.execute_head_not_completed;
  lhs.execute_pending_cycles -= rhs.execute_pending_cycles;
  lhs.execute_load_blocked_cycles -= rhs.execute_load_blocked_cycles;
  lhs.sched_idle_cycles -= rhs.sched_idle_cycles;
  lhs.sched_none_cycles -= rhs.sched_none_cycles;
  lhs.dispatch_idle_cycles -= rhs.dispatch_idle_cycles;
  lhs.rob_idle_cycles -= rhs.rob_idle_cycles;
  lhs.lq_full_events -= rhs.lq_full_events;
  lhs.sq_full_events -= rhs.sq_full_events;

  lhs.total_branch_types -= rhs.total_branch_types;
  lhs.branch_type_misses -= rhs.branch_type_misses;

  return lhs;
}
