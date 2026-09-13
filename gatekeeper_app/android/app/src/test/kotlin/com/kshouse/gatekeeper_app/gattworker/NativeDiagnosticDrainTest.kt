package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.*
import org.junit.Test

class NativeDiagnosticDrainTest {
  private class Queue(var pending: Int, val responses: MutableList<NativeDiagnosticDrain.Attempt> = mutableListOf()) : NativeDiagnosticDrain.Port {
    var clock = 0L
    var cancelled = false
    var continued = 0
    var accepted = 0
    var sends = 0
    var delay = 0L
    var failures = 0
    var perSendMs = 1L
    override fun stopped() = cancelled
    override fun elapsedMs() = clock
    override fun next() = pending > 0
    override fun send(): NativeDiagnosticDrain.Attempt {
      sends++; clock += perSendMs
      return if (responses.isEmpty()) NativeDiagnosticDrain.Attempt("ACCEPTED", NativeDiagnosticDrain.Disposition.ACCEPTED) else responses.removeAt(0)
    }
    override fun finish(attempt: NativeDiagnosticDrain.Attempt) {
      when (attempt.disposition) {
        NativeDiagnosticDrain.Disposition.ACCEPTED -> { pending--; accepted++; failures = 0; delay = 0 }
        NativeDiagnosticDrain.Disposition.QUARANTINE -> pending--
        NativeDiagnosticDrain.Disposition.RETRY -> { failures++; delay = NativeDiagnosticDrain.delayMs(failures, attempt.retryAfterMs) }
        else -> Unit
      }
    }
    override fun continueLater() { continued++ }
  }

  @Test fun successfulBacklogNeverBecomesExponentialFailureBackoff() {
    val queue = Queue(16)
    repeat(4) {
      assertEquals(4, NativeDiagnosticDrain.run(queue))
      assertEquals(0, queue.failures)
      assertEquals(0L, queue.delay)
    }
    assertEquals(16, queue.accepted)
    assertEquals(0, queue.pending)
  }

  @Test fun offlineKeepsSamePendingThenRecoveryDrainsWithoutInheritedDelay() {
    val queue = Queue(3, mutableListOf(NativeDiagnosticDrain.Attempt("NETWORK_ERROR", NativeDiagnosticDrain.Disposition.RETRY)))
    assertEquals(0, NativeDiagnosticDrain.run(queue))
    assertEquals(3, queue.pending)
    assertEquals(30_000L, queue.delay)
    queue.clock += queue.delay
    assertEquals(3, NativeDiagnosticDrain.run(queue))
    assertEquals(0, queue.failures)
    assertEquals(0L, queue.delay)
  }

  @Test fun permanentReportRejectionDoesNotAcknowledgeOrBlockTheFollowingReport() {
    val queue = Queue(2, mutableListOf(NativeDiagnosticDrain.http(422, false, null, 0)))
    assertEquals(2, NativeDiagnosticDrain.run(queue))
    assertEquals(1, queue.accepted)
    assertEquals(0, queue.pending)
  }

  @Test fun authErrorDoesNotRetryForeverAndStopDoesNotSend() {
    val queue = Queue(2, mutableListOf(NativeDiagnosticDrain.http(401, false, null, 0)))
    NativeDiagnosticDrain.run(queue)
    assertEquals(0, queue.continued)
    assertEquals(2, queue.pending)
    queue.cancelled = true
    NativeDiagnosticDrain.run(queue)
    assertEquals(1, queue.sends)
  }

  @Test fun runningWorkGetsOneSuccessorButQueuedOrBlockedWorkIsCoalesced() {
    assertTrue(NativeDiagnosticDrain.needsSuccessor(listOf("SUCCEEDED", "RUNNING")))
    assertFalse(NativeDiagnosticDrain.needsSuccessor(listOf("RUNNING", "BLOCKED")))
    assertFalse(NativeDiagnosticDrain.needsSuccessor(listOf("ENQUEUED")))
    assertTrue(NativeDiagnosticDrain.needsSuccessor(listOf("FAILED")))
    assertTrue(NativeDiagnosticDrain.needsSuccessor(emptyList()))
  }

  @Test fun budgetYieldsFreshContinuationWithoutFailure() {
    val queue = Queue(10).apply { perSendMs = 20_000 }
    assertEquals(2, NativeDiagnosticDrain.run(queue))
    assertEquals(1, queue.continued)
    assertEquals(0, queue.failures)
  }

  @Test fun retryAfterAndAckAreStrictAndBounded() {
    assertEquals(120_000L, NativeDiagnosticDrain.http(429, false, "120", 0).retryAfterMs)
    assertEquals(0L, NativeDiagnosticDrain.retryAfterMs("-1", 0))
    assertEquals(0L, NativeDiagnosticDrain.retryAfterMs("secret-untrusted", 0))
    assertEquals(60_000L, NativeDiagnosticDrain.retryAfterMs("Thu, 01 Jan 1970 00:01:00 GMT", 0))
    assertEquals(120_000L, NativeDiagnosticDrain.delayMs(1, 120_000))
    assertEquals(900_000L, NativeDiagnosticDrain.delayMs(1000))
    assertEquals(NativeDiagnosticDrain.Disposition.RETRY, NativeDiagnosticDrain.http(200, false, null, 0).disposition)
  }
}
