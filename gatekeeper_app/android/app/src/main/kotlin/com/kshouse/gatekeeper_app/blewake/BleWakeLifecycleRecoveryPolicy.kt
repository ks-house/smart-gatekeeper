package com.kshouse.gatekeeper_app.blewake

/** Scheduling evidence only. None of these decisions authorizes a GATT proof. */
internal object BleWakeLifecycleRecoveryPolicy {
  // elapsedRealtime survives process recreation and is unaffected by wall-clock changes.
  fun maySchedule(nowElapsedMs: Long, previousElapsedMs: Long?): Boolean =
    nowElapsedMs >= 0 && (previousElapsedMs == null ||
      (previousElapsedMs >= 0 && BleScanRecoveryPolicy.mayStart(nowElapsedMs, previousElapsedMs)))

  // A running predecessor may receive one successor; an already pending pass
  // observes current registration state, so further lifecycle events need no chain.
  fun needsSuccessor(states: List<String>): Boolean =
    states.none { it == "ENQUEUED" || it == "BLOCKED" } &&
      states.count { it == "RUNNING" } <= 1
}
