package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.BleWakeReconciliationEvidence
import com.kshouse.gatekeeper_app.blewake.BleWakeReconciliationPolicy
import com.kshouse.gatekeeper_app.blewake.BleWakeReconciliationRetryPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Hosted native GATT selector regression for the native-wake ownership gate. */
class BleWakeRegistrationLivenessTest {
  @Test
  fun requestedIntentDoesNotBecomeAuthoritativeUntilCurrentProcessReconciles() {
    val requestedOnly = evidence(
      requested = true,
      reconciled = false,
      processId = "old-process",
    )
    assertFalse(
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(
        requestedOnly,
        "new-process",
      ),
    )

    val attempt = BleWakeReconciliationPolicy.begin(
      requestedOnly,
      processId = "new-process",
      nowEpochMs = 100L,
    )
    val accepted = BleWakeReconciliationPolicy.accept(
      attempt,
      processId = "new-process",
      nowEpochMs = 101L,
    )
    assertTrue(
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(
        accepted,
        "new-process",
      ),
    )
  }

  @Test
  fun transientRecoveryIsNativeBoundedAndPermissionFailuresDoNotRetry() {
    assertTrue(BleWakeReconciliationRetryPolicy.shouldSchedule("scan_callback_error"))
    assertTrue(BleWakeReconciliationRetryPolicy.shouldSchedule("native_owner_unavailable"))
    assertTrue(BleWakeReconciliationRetryPolicy.shouldRetry("scan_error", completedAttempt = 0))
    assertTrue(BleWakeReconciliationRetryPolicy.shouldRetry("scan_error", completedAttempt = 1))
    assertFalse(BleWakeReconciliationRetryPolicy.shouldRetry("scan_error", completedAttempt = 2))
    assertFalse(
      BleWakeReconciliationRetryPolicy.shouldSchedule(
        "missing_permission:android.permission.BLUETOOTH_SCAN",
      ),
    )
    assertFalse(BleWakeReconciliationRetryPolicy.shouldSchedule("security_exception"))
    assertEquals(3, BleWakeReconciliationRetryPolicy.MAX_ATTEMPTS)
  }

  @Test
  fun repeatedHealthInvalidationDoesNotCreateUnboundedWorkerChains() {
    val accepted = evidence(
      requested = true,
      reconciled = true,
      processId = "process-a",
    )
    assertTrue(
      BleWakeReconciliationRetryPolicy.shouldScheduleInvalidation(
        accepted,
        "process-a",
        "bluetooth_off_or_scanner_unavailable",
      ),
    )

    val alreadyInvalidated = BleWakeReconciliationPolicy.fail(
      accepted,
      "process-a",
      "bluetooth_off_or_scanner_unavailable",
    )
    assertFalse(
      BleWakeReconciliationRetryPolicy.shouldScheduleInvalidation(
        alreadyInvalidated,
        "process-a",
        "bluetooth_off_or_scanner_unavailable",
      ),
    )
    assertTrue(
      BleWakeReconciliationRetryPolicy.shouldScheduleInvalidation(
        alreadyInvalidated,
        "process-a",
        "bluetooth_unavailable",
      ),
    )
  }

  private fun evidence(
    requested: Boolean,
    reconciled: Boolean,
    processId: String?,
  ): BleWakeReconciliationEvidence = BleWakeReconciliationEvidence(
    requested = requested,
    reconciled = reconciled,
    reconciledProcessId = processId,
    status = if (reconciled) "registered" else "reconciliation_required",
    attemptedAtEpochMs = null,
    reconciledAtEpochMs = null,
    lastCallbackAtEpochMs = null,
    errorCode = null,
  )
}
