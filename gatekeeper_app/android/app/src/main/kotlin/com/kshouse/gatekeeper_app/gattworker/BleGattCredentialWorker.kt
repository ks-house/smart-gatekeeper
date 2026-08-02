package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.Manifest
import android.bluetooth.BluetoothManager
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit

object BleGattWorkScheduler {
  const val HAS_NETWORK_CONSTRAINT = false
  const val UNIQUE_WORK_POLICY = "KEEP"
  private const val INPUT_SESSION_ID = "session_id"

  fun onPresence(context: Context, deviceAddress: String?): String? {
    if (deviceAddress.isNullOrBlank()) return null
    val appContext = context.applicationContext
    if (!BleGattFeatureFlagStore(appContext).decision().newWorkerEnabled) return null
    val credentialId = BleCredentialConfigStore(appContext).credentialId() ?: return null
    val ledger = SharedPreferencesSessionLedger(appContext)
    val (session, _) = PresenceCoalescer(
      ledger,
      BleGattWorkerSecrets.fingerprintKey(appContext),
    ).enqueue(deviceAddress, credentialId.toHex(), System.currentTimeMillis())
    val request = OneTimeWorkRequestBuilder<BleGattCredentialWorker>()
      .setInputData(workDataOf(INPUT_SESSION_ID to session.id))
      .setBackoffCriteria(
        BackoffPolicy.EXPONENTIAL,
        RetryPolicy.WORK_BACKOFF_SECONDS,
        TimeUnit.SECONDS,
      )
      .build()
    WorkManager.getInstance(appContext).enqueueUniqueWork(
      "ble-gatt-session-${session.id}",
      ExistingWorkPolicy.KEEP,
      request,
    )
    return session.id
  }

  internal fun inputSessionId(worker: CoroutineWorker): String? =
    worker.inputData.getString(INPUT_SESSION_ID)
}

class BleGattCredentialWorker(
  appContext: Context,
  params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
  override suspend fun doWork(): Result {
    val sessionId = BleGattWorkScheduler.inputSessionId(this) ?: return Result.failure()
    val ledger = SharedPreferencesSessionLedger(applicationContext)
    val session = ledger.get(sessionId) ?: return Result.failure()
    if (!BleGattFeatureFlagStore(applicationContext).decision().newWorkerEnabled) {
      ledger.update(
        session.copy(
          state = DurableSessionState.DISABLED,
          updatedEpochMs = System.currentTimeMillis(),
        ),
      )
      return Result.success()
    }
    val attempt = runAttemptCount + 1
    ledger.update(
      session.copy(
        attempt = attempt,
        state = DurableSessionState.RUNNING,
        updatedEpochMs = System.currentTimeMillis(),
        reasonCode = null,
      ),
    )
    val outcome = GattSessionEngine(
      transport = AndroidBleGattTransport(applicationContext),
      signer = AndroidKeystoreCredentialSigner(),
    ).run(session.deviceAddress, session.credentialIdHex.hexToBytes())
    return when (outcome) {
      is SessionOutcome.Success -> {
        ledger.update(
          session.copy(
            attempt = attempt,
            state = DurableSessionState.SUCCEEDED,
            updatedEpochMs = System.currentTimeMillis(),
            reasonCode = null,
            latencyMs = outcome.latencyMs,
            activeAclVersion = outcome.activeAclVersion,
          ),
        )
        Result.success()
      }
      is SessionOutcome.Failure -> {
        val retry = RetryPolicy.shouldRetry(attempt, outcome)
        ledger.update(
          session.copy(
            attempt = attempt,
            state = if (retry) DurableSessionState.RETRY_PENDING else DurableSessionState.FAILED,
            updatedEpochMs = System.currentTimeMillis(),
            reasonCode = outcome.reason.schemaReason,
            latencyMs = outcome.latencyMs,
          ),
        )
        if (retry) Result.retry() else Result.failure()
      }
    }
  }
}

object BleGattHealthBridge {
  fun snapshot(context: Context): Map<String, Any?> {
    val decision = BleGattFeatureFlagStore(context.applicationContext).decision()
    val last = SharedPreferencesSessionLedger(context.applicationContext).last()
    return mapOf(
      "featureEnabled" to decision.newWorkerEnabled,
      "featureStatus" to decision.status,
      "bleOwner" to decision.owner,
      "healthy" to (last?.state !in setOf(DurableSessionState.FAILED)),
      "lastSession" to last?.redactedMap(),
      "lastReasonCode" to last?.reasonCode,
      "lastLatencyMs" to last?.latencyMs,
      "currentBlockingReasonCode" to BleGattRuntimeEnvironment.currentBlockingReason(context),
      "forceStopReasonCode" to AccessReasonCode.FORCE_STOPPED.schemaReason,
      "reasonCodeMap" to mapOf(
        "permission" to AccessReasonCode.PERMISSION_DENIED.schemaReason,
        "bluetooth_off" to AccessReasonCode.BLUETOOTH_DISABLED.schemaReason,
        "force_stop" to AccessReasonCode.FORCE_STOPPED.schemaReason,
        "battery_restricted" to AccessReasonCode.BATTERY_RESTRICTED.schemaReason,
      ),
      "updateManagerIndependent" to true,
      "updateManagerOwnedByWorker" to false,
      "networkRequired" to BleGattWorkScheduler.HAS_NETWORK_CONSTRAINT,
    )
  }
}

object BleGattRuntimeEnvironment {
  fun currentBlockingReason(context: Context): String? {
    val appContext = context.applicationContext
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
      appContext.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
    ) return AccessReasonCode.PERMISSION_DENIED.schemaReason
    val adapter = appContext.getSystemService(BluetoothManager::class.java)?.adapter
    if (adapter == null || !adapter.isEnabled) return AccessReasonCode.BLUETOOTH_DISABLED.schemaReason
    val power = appContext.getSystemService(PowerManager::class.java)
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
      power != null && !power.isIgnoringBatteryOptimizations(appContext.packageName)
    ) return AccessReasonCode.BATTERY_RESTRICTED.schemaReason
    return appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .getString(KEY_LAST_BLOCKED, null)
  }

  fun recordBlocked(context: Context, schemaReason: String) {
    require(schemaReason in AccessReasonCode.entries.map { it.schemaReason }) { "unknown reason code" }
    context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .edit()
      .putString(KEY_LAST_BLOCKED, schemaReason)
      .commit()
  }

  private const val PREFS = "ble_gatt_worker_environment"
  private const val KEY_LAST_BLOCKED = "last_blocked_reason"
}
