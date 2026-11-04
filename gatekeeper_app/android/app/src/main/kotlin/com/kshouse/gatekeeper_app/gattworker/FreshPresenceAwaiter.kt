package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive

internal enum class FreshPresenceWaitResult { FRESH, EXPIRED, DISABLED }

/** Waits for live RF only; it holds no BLE lease and never restores cached presence. */
internal object FreshPresenceAwaiter {
  const val MAX_WAIT_MS = 10_000L
  private const val POLL_MS = 100L

  suspend fun await(
    remainingDispatchMs: Long,
    clock: MonotonicClock,
    isFresh: () -> Boolean,
    isEnabled: () -> Boolean,
    onWaiting: () -> Unit = {},
  ): FreshPresenceWaitResult {
    val started = clock.nowMs()
    val budget = remainingDispatchMs.coerceIn(0L, MAX_WAIT_MS)
    var waiting = false
    while (true) {
      currentCoroutineContext().ensureActive()
      if (!isEnabled()) return FreshPresenceWaitResult.DISABLED
      val elapsed = clock.nowMs() - started
      if (elapsed < 0 || elapsed > budget) return FreshPresenceWaitResult.EXPIRED
      if (isFresh()) return FreshPresenceWaitResult.FRESH
      if (elapsed == budget) return FreshPresenceWaitResult.EXPIRED
      if (!waiting) {
        waiting = true
        onWaiting()
      }
      delay(minOf(POLL_MS, budget - elapsed))
    }
  }
}
