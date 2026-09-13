package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import com.kshouse.gatekeeper_app.gattworker.NativeDiagnostics
import java.util.concurrent.TimeUnit

internal enum class BleScanRecoveryReason { PROCESS_START, APP_FOREGROUND, BLUETOOTH_ON, CALLBACK_ERROR, QUIET_REFRESH }

/** Observes one finite window on the existing owner/registrations. Never opens a second scanner. */
internal object BleScanRecoveryObserver {
  private const val PREFS = "ble_scan_recovery_v1"
  private const val WORK = "ble-scan-receive-confirmation-v1"

  @Synchronized
  fun begin(context: Context, reason: BleScanRecoveryReason): Boolean {
    observe(context)
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val now = System.currentTimeMillis()
    val previous = p.getLong("started", 0).takeIf { it > 0 }
    if (!BleScanRecoveryPolicy.mayStart(now, previous)) return false
    p.edit().putLong("started", now).putString("reason", reason.name)
      .putString("outcome", "AWAITING_PACKET").remove("finished").apply()
    NativeDiagnostics.record(context, NativeDiagnostics.Event.SCAN_REGISTRATION, "RECOVERY_AWAITING_PACKET")
    try {
      val operation = WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE,
        OneTimeWorkRequestBuilder<BleScanReceiveConfirmationWorker>()
          .setInitialDelay(BleScanRecoveryPolicy.CONFIRMATION_WINDOW_MS, TimeUnit.MILLISECONDS).build())
      operation.result.addListener({
        try {
          operation.result.get()
        } catch (_: Exception) {
          synchronized(this) {
            // Late completion from a replaced schedule cannot corrupt the new window.
            if (p.getLong("started", 0) == now && p.getString("outcome", null) == "AWAITING_PACKET") {
              finish(context, "CONFIRMATION_SCHEDULER_UNAVAILABLE", System.currentTimeMillis())
            }
          }
        }
      }, java.util.concurrent.Executor { it.run() })
    } catch (_: RuntimeException) {
      finish(context, "CONFIRMATION_SCHEDULER_UNAVAILABLE", now)
    }
    return true
  }

  @Synchronized
  fun observe(context: Context, packetAt: Long? = null) {
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    if (p.getString("outcome", null) != "AWAITING_PACKET") return
    val now = System.currentTimeMillis()
    val outcome = BleScanRecoveryPolicy.confirmation(now, p.getLong("started", now), packetAt)
    if (outcome != "AWAITING_PACKET") finish(context, outcome, now)
  }

  @Synchronized
  fun cancel(context: Context) {
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    if (p.getString("outcome", null) == "AWAITING_PACKET") finish(context, "CANCELLED", System.currentTimeMillis())
  }

  private fun finish(context: Context, outcome: String, now: Long) {
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
      .putString("outcome", outcome).putLong("finished", now).apply()
    NativeDiagnostics.record(context, NativeDiagnostics.Event.SCAN_REGISTRATION, "RECOVERY_$outcome")
  }

  @Synchronized
  fun snapshot(context: Context): Map<String, Any?> {
    // Android may run the delayed observer late; a snapshot can close the same
    // elapsed window without implying Android promised an execution deadline.
    observe(context)
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val started = p.getLong("started", 0).takeIf { it > 0 }
    return mapOf("recoveryStartedAtEpochMs" to started,
      "recoveryDeadlineAtEpochMs" to started?.plus(BleScanRecoveryPolicy.CONFIRMATION_WINDOW_MS),
      "recoveryFinishedAtEpochMs" to p.getLong("finished", 0).takeIf { it > 0 },
      "recoveryReason" to p.getString("reason", null),
      "recoveryOutcome" to p.getString("outcome", null))
  }
}

class BleScanReceiveConfirmationWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
  override fun doWork(): Result {
    BleScanRecoveryObserver.observe(applicationContext)
    return Result.success()
  }
}
