package com.kshouse.gatekeeper_app.blewake

/**
 * Durable intent and best-known platform reconciliation evidence are separate.
 *
 * Android does not expose a query for PendingIntent scan registration. A
 * successful startScan return is therefore acceptance evidence, not a claim
 * that the OS registration will remain live indefinitely.
 */
internal data class BleWakeReconciliationEvidence(
  val requested: Boolean,
  val reconciled: Boolean,
  val reconciledProcessId: String?,
  val status: String,
  val attemptedAtEpochMs: Long?,
  val reconciledAtEpochMs: Long?,
  val lastCallbackAtEpochMs: Long?,
  val errorCode: Int?,
)

internal object BleWakeReconciliationPolicy {
  fun begin(
    previous: BleWakeReconciliationEvidence,
    processId: String,
    nowEpochMs: Long,
  ): BleWakeReconciliationEvidence = previous.copy(
    requested = true,
    reconciled = false,
    reconciledProcessId = processId,
    status = "reconciling",
    attemptedAtEpochMs = nowEpochMs,
    reconciledAtEpochMs = null,
    errorCode = null,
  )

  fun accept(
    attempt: BleWakeReconciliationEvidence,
    processId: String,
    nowEpochMs: Long,
  ): BleWakeReconciliationEvidence = attempt.copy(
    requested = true,
    reconciled = true,
    reconciledProcessId = processId,
    status = "registered",
    reconciledAtEpochMs = nowEpochMs,
    errorCode = 0,
  )

  fun fail(
    previous: BleWakeReconciliationEvidence,
    processId: String,
    status: String,
    errorCode: Int? = null,
  ): BleWakeReconciliationEvidence = previous.copy(
    reconciled = false,
    reconciledProcessId = processId,
    status = status,
    reconciledAtEpochMs = null,
    errorCode = errorCode,
  )

  fun stop(
    previous: BleWakeReconciliationEvidence,
    processId: String,
  ): BleWakeReconciliationEvidence = previous.copy(
    requested = false,
    reconciled = false,
    reconciledProcessId = processId,
    status = "stopped",
    reconciledAtEpochMs = null,
    errorCode = null,
  )

  fun recordCallback(
    previous: BleWakeReconciliationEvidence,
    processId: String,
    errorCode: Int,
    nowEpochMs: Long,
  ): BleWakeReconciliationEvidence = if (errorCode == 0) {
    previous.copy(lastCallbackAtEpochMs = nowEpochMs)
  } else {
    fail(previous, processId, "scan_callback_error", errorCode)
      .copy(lastCallbackAtEpochMs = nowEpochMs)
  }

  fun isAcceptedForCurrentProcess(
    evidence: BleWakeReconciliationEvidence,
    processId: String,
  ): Boolean = evidence.requested &&
    evidence.reconciled &&
    evidence.reconciledProcessId == processId
}

internal object BleWakeReconciliationRetryPolicy {
  const val MAX_ATTEMPTS = 3

  private val retryableStatuses = setOf(
    "bluetooth_unavailable",
    "bluetooth_off_or_scanner_unavailable",
    "illegal_state",
    "native_owner_unavailable",
    "scan_callback_error",
    "scan_error",
  )

  fun shouldSchedule(status: String): Boolean = status in retryableStatuses

  fun shouldScheduleInvalidation(
    previous: BleWakeReconciliationEvidence,
    processId: String,
    status: String,
  ): Boolean = shouldSchedule(status) && (
    previous.status != status ||
      BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(previous, processId)
    )

  fun shouldRetry(status: String, completedAttempt: Int): Boolean =
    shouldSchedule(status) && completedAttempt + 1 < MAX_ATTEMPTS
}
