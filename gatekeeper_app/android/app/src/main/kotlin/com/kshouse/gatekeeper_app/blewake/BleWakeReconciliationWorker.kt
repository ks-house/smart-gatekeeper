package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.os.SystemClock
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.UUID
import com.kshouse.gatekeeper_app.gattworker.BleGattFeatureFlagStore
import com.kshouse.gatekeeper_app.gattworker.SharedPreferencesSessionLedger
import com.kshouse.gatekeeper_app.gattworker.DurableSessionState

/** Independent of diagnostic-upload consent and Activity/Flutter lifetime. */
class BleScanWatchdogWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
  override fun doWork(): Result {
    if (!BleWakeRegistrar.isEnabled(applicationContext)) return Result.success()
    if (!BleGattFeatureFlagStore(applicationContext).decision().newWorkerEnabled) {
      BleWakeRegistrar.stop(applicationContext)
      return Result.success()
    }
    // Do not perturb scanning while a proof or ambiguous operation is active.
    val last = SharedPreferencesSessionLedger(applicationContext).last()
    if (last?.state in setOf(DurableSessionState.QUEUED, DurableSessionState.RUNNING,
        DurableSessionState.RETRY_PENDING, DurableSessionState.PROOF_UNCERTAIN)) return Result.success()
    BleWakeRegistrar.register(applicationContext)
    return Result.success()
  }
}

/** Native-only bounded registration repair; it never dispatches authentication. */
class BleWakeReconciliationWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
  override fun doWork(): Result {
    if (!BleWakeRegistrar.isEnabled(applicationContext)) return Result.success()
    // A queued request is not authority to re-enable a disabled native owner.
    if (!BleGattFeatureFlagStore(applicationContext).decision().newWorkerEnabled) {
      BleWakeRegistrar.stop(applicationContext)
      return Result.success()
    }
    val reason = inputData.getString(BleWakeReconciliationScheduler.INPUT_LIFECYCLE_REASON)
      ?.let { name -> BleScanRecoveryReason.entries.firstOrNull { it.name == name } }
    BleScanDiagnostics.record(applicationContext, BleScanDiagnostics.Event.RECOVERY_ATTEMPT)
    val registration = BleWakeRegistrar.reconcileRequestedWithoutScheduling(applicationContext, reason)
    if (!registration.requested || registration.reconciled) return Result.success()
    return if (BleWakeReconciliationRetryPolicy.shouldRetry(registration.status, runAttemptCount)) {
      Result.retry()
    } else {
      BleScanDiagnostics.record(applicationContext, BleScanDiagnostics.Event.RECOVERY_EXHAUSTED)
      Result.success()
    }
  }
}

internal object BleWakeReconciliationScheduler {
  private const val TAG = "BLE_WAKE_POC"
  private const val UNIQUE_WORK = "ble-wake-registration-reconciliation"
  private const val MIN_BACKOFF_SECONDS = 10L
  private const val WATCHDOG = "ble-scan-quiet-watchdog-v1"
  internal const val LIFECYCLE_WORK = "ble-wake-lifecycle-reconciliation-v1"
  internal const val INPUT_LIFECYCLE_REASON = "lifecycle_reason"
  private const val LIFECYCLE_PREFS = "ble_wake_lifecycle_recovery_v1"
  private val executor = Executors.newSingleThreadExecutor { task ->
    Thread(task, "sgk-ble-registration-recovery").apply { isDaemon = true }
  }
  private val lifecycleQueued = AtomicBoolean(false)

  fun ensureWatchdog(context: Context) {
    try {
      WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
        WATCHDOG, ExistingPeriodicWorkPolicy.KEEP,
        PeriodicWorkRequestBuilder<BleScanWatchdogWorker>(15, TimeUnit.MINUTES)
          .setInitialDelay(15, TimeUnit.MINUTES).build())
    } catch (_: IllegalStateException) { /* Later registration retries scheduling. */ }
  }

  fun cancelWatchdog(context: Context) {
    try { WorkManager.getInstance(context.applicationContext).cancelUniqueWork(WATCHDOG) }
    catch (_: IllegalStateException) { /* Durable disabled intent prevents recovery. */ }
  }

  /** One immediate filtered-registration check, at most one pending successor. */
  fun scheduleLifecycle(context: Context, reason: BleScanRecoveryReason) {
    if (reason !in setOf(BleScanRecoveryReason.PROCESS_START,
        BleScanRecoveryReason.APP_BACKGROUND, BleScanRecoveryReason.SCREEN_OFF)) return
    val app = context.applicationContext
    if (!BleWakeRegistrar.isEnabled(app)) return
    val p = app.getSharedPreferences(LIFECYCLE_PREFS, Context.MODE_PRIVATE)
    val generation = p.getString("generation", "") ?: ""
    if (!lifecycleQueued.compareAndSet(false, true)) return
    executor.execute {
      lifecycleQueued.set(false)
      try {
        val manager = WorkManager.getInstance(app)
        val states = manager.getWorkInfosForUniqueWork(LIFECYCLE_WORK)
          .get(5, TimeUnit.SECONDS).map { it.state.name }
        if (!BleWakeLifecycleRecoveryPolicy.needsSuccessor(states)) return@execute
        val operation = synchronized(BleWakeRegistrar) {
          // stop/logout invalidates callbacks already waiting on the scheduler.
          if (!BleWakeRegistrar.isEnabled(app) || generation != p.getString("generation", "")) return@synchronized null
          val now = SystemClock.elapsedRealtime()
          val previous = if (p.contains("last_elapsed_ms")) p.getLong("last_elapsed_ms", 0) else null
          if (!BleWakeLifecycleRecoveryPolicy.maySchedule(now, previous)) return@synchronized null
          val packet = BleScanDiagnostics.snapshot(app)["lastPacketAtEpochMs"] as? Long
          if (BleScanRecoveryPolicy.freshPacket(System.currentTimeMillis(), packet)) return@synchronized null
          // BluetoothStateMonitor already restores immediately at process start.
          // Do not stop/start an accepted registration a second time on that path.
          if (reason == BleScanRecoveryReason.PROCESS_START && BleWakeRegistrar.status(app).reconciled) return@synchronized null
          if (!p.edit().putLong("last_elapsed_ms", now).commit()) return@synchronized null
          val request = OneTimeWorkRequestBuilder<BleWakeReconciliationWorker>()
            .setInputData(workDataOf(INPUT_LIFECYCLE_REASON to reason.name))
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, MIN_BACKOFF_SECONDS, TimeUnit.SECONDS)
            .build()
          // KEEP could lose the event immediately before a running pass returns.
          // A pending pass already sees current state, so the query bounds this to two.
          manager.enqueueUniqueWork(LIFECYCLE_WORK,
            if ("RUNNING" in states) ExistingWorkPolicy.APPEND_OR_REPLACE else ExistingWorkPolicy.REPLACE, request)
        }
        operation?.result?.get(5, TimeUnit.SECONDS)
      } catch (error: Exception) {
        Log.w(TAG, "lifecycle registration scheduling unavailable: ${error.javaClass.simpleName}")
      }
    }
  }

  fun scheduleIfRetryable(context: Context, result: BleWakeRegistrationResult) {
    if (!result.requested || !BleWakeReconciliationRetryPolicy.shouldSchedule(result.status)) return
    val request = OneTimeWorkRequestBuilder<BleWakeReconciliationWorker>()
      .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, MIN_BACKOFF_SECONDS, TimeUnit.SECONDS).build()
    try {
      WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
        UNIQUE_WORK, ExistingWorkPolicy.KEEP, request)
    } catch (error: IllegalStateException) {
      Log.w(TAG, "native reconciliation scheduler unavailable: ${error.javaClass.simpleName}")
    }
  }

  fun cancelTransient(context: Context) {
    try { WorkManager.getInstance(context.applicationContext).cancelUniqueWork(UNIQUE_WORK) }
    catch (error: IllegalStateException) {
      Log.w(TAG, "native reconciliation cancel unavailable: ${error.javaClass.simpleName}")
    }
  }

  fun cancel(context: Context) {
    cancelTransient(context)
    val app = context.applicationContext
    app.getSharedPreferences(LIFECYCLE_PREFS, Context.MODE_PRIVATE).edit()
      .putString("generation", UUID.randomUUID().toString()).commit()
    try { WorkManager.getInstance(app).cancelUniqueWork(LIFECYCLE_WORK) }
    catch (error: IllegalStateException) {
      Log.w(TAG, "lifecycle reconciliation cancel unavailable: ${error.javaClass.simpleName}")
    }
  }
}
