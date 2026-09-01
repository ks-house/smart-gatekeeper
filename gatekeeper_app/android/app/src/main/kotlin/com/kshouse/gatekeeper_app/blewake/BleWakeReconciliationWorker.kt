package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Native-only bounded reconciliation for transient scanner failures.
 *
 * Permission and unsupported-platform failures require user/app action and are
 * never retried here. Bluetooth STATE_ON and package/boot lifecycle paths still
 * reconcile immediately; this worker only closes transient silent gaps without
 * requiring a Flutter engine or MainActivity MethodChannel.
 */
class BleWakeReconciliationWorker(
  context: Context,
  parameters: WorkerParameters,
) : Worker(context, parameters) {
  override fun doWork(): Result {
    val registration =
      BleWakeRegistrar.reconcileRequestedWithoutScheduling(applicationContext)
    if (!registration.requested) return Result.success()
    if (registration.reconciled) return Result.success()
    return if (
      BleWakeReconciliationRetryPolicy.shouldRetry(
        registration.status,
        runAttemptCount,
      )
    ) {
      Result.retry()
    } else {
      Result.success()
    }
  }
}

internal object BleWakeReconciliationScheduler {
  private const val TAG = "BLE_WAKE_POC"
  private const val UNIQUE_WORK = "ble-wake-registration-reconciliation"
  private const val MIN_BACKOFF_SECONDS = 10L

  fun scheduleIfRetryable(context: Context, result: BleWakeRegistrationResult) {
    if (!result.requested || !BleWakeReconciliationRetryPolicy.shouldSchedule(result.status)) return
    val request = OneTimeWorkRequestBuilder<BleWakeReconciliationWorker>()
      .setBackoffCriteria(
        BackoffPolicy.EXPONENTIAL,
        MIN_BACKOFF_SECONDS,
        TimeUnit.SECONDS,
      )
      .build()
    try {
      WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
        UNIQUE_WORK,
        ExistingWorkPolicy.KEEP,
        request,
      )
    } catch (error: IllegalStateException) {
      Log.w(TAG, "native reconciliation scheduler unavailable: ${error.javaClass.simpleName}")
    }
  }

  fun cancel(context: Context) {
    try {
      WorkManager.getInstance(context.applicationContext).cancelUniqueWork(UNIQUE_WORK)
    } catch (error: IllegalStateException) {
      Log.w(TAG, "native reconciliation cancel unavailable: ${error.javaClass.simpleName}")
    }
  }
}
