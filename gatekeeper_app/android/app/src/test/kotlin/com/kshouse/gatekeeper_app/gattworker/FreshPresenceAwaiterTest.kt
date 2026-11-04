package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.ContinuousPresenceTracker
import com.kshouse.gatekeeper_app.blewake.ContinuousPresencePolicy
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class FreshPresenceAwaiterTest {
  @Test fun explicitPreProofFreshnessFailureHasOneFastRecoveryOnly() {
    val expired = DurableGattSession("s", "f", 1_000, 2_000, 1, DurableSessionState.FAILED).copy(
      reasonCode = "PRESENCE_EXPIRED", transportReason = "FRESH_PACKET_REQUIRED",
      requiresFreshPresence = true)
    assertEquals("FAILURE_BACKOFF", ContinuousPresencePolicy.blockingReason(expired, 6_999))
    assertNull(ContinuousPresencePolicy.blockingReason(expired, 7_000))
    assertEquals("FAILURE_BACKOFF", ContinuousPresencePolicy.blockingReason(
      expired.copy(failureRecovery = true), 7_000))
    assertEquals("FAILURE_BACKOFF", ContinuousPresencePolicy.blockingReason(
      expired.copy(transportReason = "PRESENCE_AGE_EXCEEDED"), 7_000))
    assertEquals("FAILURE_BACKOFF", ContinuousPresencePolicy.blockingReason(
      expired.copy(targetReasonCode = 7), 7_000))
    assertEquals("MISSING_HINT_PROBE_COOLDOWN", ContinuousPresencePolicy.missingHintBlockingReason(expired, 7_000))
    assertEquals("PROOF_OUTCOME_UNCERTAIN", ContinuousPresencePolicy.blockingReason(
      expired.copy(state = DurableSessionState.PROOF_UNCERTAIN), Long.MAX_VALUE))
  }

  @Test fun restoredWorkerWaitsForNewSameTargetPacket() = runTest {
    ContinuousPresenceTracker.exit(null) // Simulated process recreation, durable session survives.
    var result: FreshPresenceWaitResult? = null
    var waits = 0
    val job = launch {
      result = FreshPresenceAwaiter.await(10_000, MonotonicClock { testScheduler.currentTime },
        { ContinuousPresenceTracker.fresh("target", testScheduler.currentTime) }, { true }) { waits++ }
    }
    runCurrent()
    assertNull(result)
    advanceTimeBy(500)
    ContinuousPresenceTracker.observe("other", testScheduler.currentTime)
    runCurrent()
    assertNull(result)
    ContinuousPresenceTracker.observe("target", testScheduler.currentTime)
    advanceTimeBy(100)
    runCurrent()
    assertEquals(FreshPresenceWaitResult.FRESH, result)
    assertEquals(1, waits)
    job.join()
  }

  @Test fun noPacketStopsAtRemainingDispatchBudgetWithoutExtendingIt() = runTest {
    val start = testScheduler.currentTime
    val result = FreshPresenceAwaiter.await(250, MonotonicClock { testScheduler.currentTime },
      { false }, { true })
    assertEquals(FreshPresenceWaitResult.EXPIRED, result)
    assertEquals(250L, testScheduler.currentTime - start)
  }

  @Test fun alreadyFreshDoesNotDelayAndOversizedBudgetIsBounded() = runTest {
    assertEquals(FreshPresenceWaitResult.FRESH,
      FreshPresenceAwaiter.await(10_000, MonotonicClock { testScheduler.currentTime }, { true }, { true }))
    assertEquals(0L, testScheduler.currentTime)
    assertEquals(FreshPresenceWaitResult.EXPIRED,
      FreshPresenceAwaiter.await(Long.MAX_VALUE, MonotonicClock { testScheduler.currentTime }, { false }, { true }))
    assertEquals(10_000L, testScheduler.currentTime)
  }

  @Test fun disableAndCancellationStopWithoutWaitingForTimeout() = runTest {
    var enabled = true
    var result: FreshPresenceWaitResult? = null
    val clock = MonotonicClock { testScheduler.currentTime }
    val waiting = launch { result = FreshPresenceAwaiter.await(10_000, clock, { false }, { enabled }) }
    runCurrent()
    enabled = false
    advanceTimeBy(100)
    runCurrent()
    assertEquals(FreshPresenceWaitResult.DISABLED, result)
    waiting.join()
    var cancelled = false
    val stopped = launch {
      try { FreshPresenceAwaiter.await(10_000, clock, { false }, { true }) }
      catch (failure: CancellationException) { cancelled = true; throw failure }
    }
    runCurrent()
    stopped.cancelAndJoin()
    assertTrue(cancelled)
    assertTrue(testScheduler.currentTime < 10_000)
  }

  @Test fun disabledWinsOverFreshAndLatePacketCannotExtendDeadline() = runTest {
    assertEquals(FreshPresenceWaitResult.DISABLED,
      FreshPresenceAwaiter.await(1_000, MonotonicClock { testScheduler.currentTime }, { true }, { false }))
    var now = 0L
    assertEquals(FreshPresenceWaitResult.EXPIRED,
      FreshPresenceAwaiter.await(100, MonotonicClock { now.also { now += 101 } }, { true }, { true }))
  }
}
