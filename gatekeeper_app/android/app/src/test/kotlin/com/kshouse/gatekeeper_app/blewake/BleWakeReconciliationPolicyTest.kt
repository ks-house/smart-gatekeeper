package com.kshouse.gatekeeper_app.blewake

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BleWakeReconciliationPolicyTest {
  @Test
  fun durableRequestIsNotCurrentProcessRegistrationEvidence() {
    val persisted = baseline(requested = true).copy(
      reconciled = true,
      reconciledProcessId = "old-process",
      status = "registered",
      reconciledAtEpochMs = 90L,
    )

    assertFalse(
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(
        persisted,
        "new-process",
      ),
    )
  }

  @Test
  fun beginClearsStaleEvidenceUntilStartScanIsAccepted() {
    val attempt = BleWakeReconciliationPolicy.begin(
      baseline(requested = true).copy(
        reconciled = true,
        reconciledProcessId = "old-process",
        status = "registered",
      ),
      processId = "new-process",
      nowEpochMs = 100L,
    )

    assertTrue(attempt.requested)
    assertFalse(attempt.reconciled)
    assertEquals("reconciling", attempt.status)
    assertEquals(100L, attempt.attemptedAtEpochMs)
    assertNull(attempt.reconciledAtEpochMs)

    val accepted = BleWakeReconciliationPolicy.accept(
      attempt,
      processId = "new-process",
      nowEpochMs = 110L,
    )
    assertTrue(
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(
        accepted,
        "new-process",
      ),
    )
    assertEquals("registered", accepted.status)
    assertEquals(110L, accepted.reconciledAtEpochMs)
  }

  @Test
  fun registrationFailureAndCallbackErrorInvalidateAcceptedEvidence() {
    val accepted = acceptedEvidence()
    val failed = BleWakeReconciliationPolicy.fail(
      accepted,
      processId = "process-a",
      status = "scan_error",
      errorCode = 2,
    )
    assertFalse(failed.reconciled)
    assertNull(failed.reconciledAtEpochMs)
    assertEquals(2, failed.errorCode)

    val callbackFailure = BleWakeReconciliationPolicy.recordCallback(
      accepted,
      processId = "process-a",
      errorCode = 3,
      nowEpochMs = 150L,
    )
    assertFalse(callbackFailure.reconciled)
    assertEquals("scan_callback_error", callbackFailure.status)
    assertEquals(150L, callbackFailure.lastCallbackAtEpochMs)
  }

  @Test
  fun successfulCallbackUpdatesEvidenceWithoutInventingRegistration() {
    val requestedOnly = baseline(requested = true)
    val callback = BleWakeReconciliationPolicy.recordCallback(
      requestedOnly,
      processId = "process-a",
      errorCode = 0,
      nowEpochMs = 200L,
    )

    assertFalse(callback.reconciled)
    assertEquals(200L, callback.lastCallbackAtEpochMs)
    assertFalse(
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(
        callback,
        "process-a",
      ),
    )
  }

  @Test
  fun stopClearsIntentAndReconciliationBeforePlatformStop() {
    val stopped = BleWakeReconciliationPolicy.stop(acceptedEvidence(), "process-a")

    assertFalse(stopped.requested)
    assertFalse(stopped.reconciled)
    assertEquals("stopped", stopped.status)
    assertNull(stopped.reconciledAtEpochMs)
  }

  private fun acceptedEvidence(): BleWakeReconciliationEvidence = baseline(requested = true).copy(
    reconciled = true,
    reconciledProcessId = "process-a",
    status = "registered",
    attemptedAtEpochMs = 100L,
    reconciledAtEpochMs = 110L,
    errorCode = 0,
  )

  private fun baseline(requested: Boolean): BleWakeReconciliationEvidence =
    BleWakeReconciliationEvidence(
      requested = requested,
      reconciled = false,
      reconciledProcessId = null,
      status = if (requested) "reconciliation_required" else "not_registered",
      attemptedAtEpochMs = null,
      reconciledAtEpochMs = null,
      lastCallbackAtEpochMs = null,
      errorCode = null,
    )
}
