package com.kshouse.gatekeeper_app.gattworker

import android.Manifest
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import androidx.work.BackoffPolicy
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequest
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.flutterbeacon.CrossProcessBleOwnerCoordinator
import com.kshouse.gatekeeper_app.blewake.BleWakeJournal
import java.util.concurrent.TimeUnit

object BleGattWorkScheduler {
  const val HAS_NETWORK_CONSTRAINT = false
  const val UNIQUE_WORK_POLICY = "KEEP"
  const val RETRY_WORK_POLICY = "APPEND_OR_REPLACE"
  const val EXPEDITED_MIN_API = Build.VERSION_CODES.S
  private const val INPUT_SESSION_ID = "session_id"

  data class ManualRetryResult(
    val accepted: Boolean,
    val reason: String,
    val sessionId: String? = null,
    val targetSeenEpochMs: Long? = null,
  ) {
    fun toMap(): Map<String, Any?> = mapOf(
      "accepted" to accepted,
      "reason" to reason,
      "sessionId" to sessionId,
      "targetSeenEpochMs" to targetSeenEpochMs,
    )
  }

  fun onPresence(context: Context, deviceAddress: String?, presenceEventId: String): String? {
    if (deviceAddress.isNullOrBlank() || presenceEventId.isBlank()) return null
    val appContext = context.applicationContext
    if (!BleGattFeatureFlagStore(appContext).decision().newWorkerEnabled) return null
    val credentialId = BleCredentialConfigStore(appContext).credentialId() ?: return null
    return try {
      val ledger = SharedPreferencesSessionLedger(appContext)
      val vault = AndroidEncryptedLocatorVault(appContext)
      val (session, duplicate) = PresenceCoalescer(
        ledger,
        AndroidKeystorePresenceFingerprinter(appContext),
      ).enqueue(deviceAddress, presenceEventId, System.currentTimeMillis())
      if (!duplicate) vault.store(session.id, LocatorSecret(deviceAddress, credentialId))
      WorkManager.getInstance(appContext).enqueueUniqueWork(
        workName(session.id),
        ExistingWorkPolicy.KEEP,
        request(session.id, 0),
      )
      session.id
    } catch (_: Exception) {
      null
    } finally {
      credentialId.fill(0)
    }
  }

  fun manualRetry(context: Context): ManualRetryResult {
    val appContext = context.applicationContext
    val flagStore = BleGattFeatureFlagStore(appContext)
    val flagDecision = flagStore.decision()
    if (!flagDecision.newWorkerEnabled) {
      return ManualRetryResult(false, "NATIVE_GATT_DISABLED:${flagDecision.status}")
    }
    val target = AuthenticatedTargetLocatorStore(appContext).resolve()
      ?: return ManualRetryResult(false, "TARGET_UNAVAILABLE")
    val sessionId = onPresence(appContext, target.deviceAddress, "manual-retry-${System.currentTimeMillis()}")
      ?: return ManualRetryResult(false, "CREDENTIAL_OR_SCHEDULER_UNAVAILABLE")
    return ManualRetryResult(true, "QUEUED", sessionId, target.lastSeenEpochMs)
  }

  fun enqueueRetry(context: Context, sessionId: String, delayMs: Long) {
    WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
      workName(sessionId),
      ExistingWorkPolicy.APPEND_OR_REPLACE,
      request(sessionId, delayMs),
    )
  }

  fun cancelAll(context: Context) {
    WorkManager.getInstance(context.applicationContext).cancelAllWorkByTag(WORK_TAG)
  }

  private fun request(sessionId: String, initialDelayMs: Long): OneTimeWorkRequest {
    val builder = OneTimeWorkRequestBuilder<BleGattCredentialWorker>()
      .addTag(WORK_TAG)
      .setInputData(workDataOf(INPUT_SESSION_ID to sessionId))
      .setInitialDelay(initialDelayMs.coerceAtLeast(0), TimeUnit.MILLISECONDS)
      .setBackoffCriteria(
        BackoffPolicy.EXPONENTIAL,
        RetryPolicy.WORK_BACKOFF_SECONDS,
        TimeUnit.SECONDS,
      )
    if (
      Build.VERSION.SDK_INT >= EXPEDITED_MIN_API &&
      HandsFreeDispatchPolicy.shouldExpedite(initialDelayMs)
    ) {
      builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
    }
    return builder.build()
  }

  private fun workName(sessionId: String) = "ble-gatt-session-$sessionId"

  private const val WORK_TAG = "ble-gatt-session"

  internal fun inputSessionId(worker: CoroutineWorker): String? = worker.inputData.getString(INPUT_SESSION_ID)
}

class BleGattCredentialWorker(
  appContext: Context,
  params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
  override suspend fun doWork(): Result {
    val sessionId = BleGattWorkScheduler.inputSessionId(this) ?: return Result.failure()
    val ledger = SharedPreferencesSessionLedger(applicationContext)
    val vault = AndroidEncryptedLocatorVault(applicationContext)
    val initial = ledger.get(sessionId) ?: return Result.failure()
    if (!DurableAttemptPolicy.canExecute(initial.state)) {
      vault.delete(sessionId)
      return Result.success()
    }
    val dispatchEpochMs = System.currentTimeMillis()
    if (!HandsFreeDispatchPolicy.isFresh(initial.createdEpochMs, dispatchEpochMs)) {
      terminateFailure(
        ledger,
        vault,
        initial,
        AccessReasonCode.PRESENCE_EXPIRED,
        "PRESENCE_AGE_EXCEEDED",
      )
      return Result.success()
    }
    if (!BleGattFeatureFlagStore(applicationContext).decision().newWorkerEnabled) {
      terminateDisabled(ledger, vault, initial)
      return Result.success()
    }
    val remainingDelayMs = RetryPolicy.remainingDelayMs(initial, System.currentTimeMillis())
    if (remainingDelayMs > 0) {
      BleGattWorkScheduler.enqueueRetry(applicationContext, initial.id, remainingDelayMs)
      return Result.success()
    }
    val ownerLease = CrossProcessBleOwnerCoordinator.forContext(applicationContext).tryAcquireNative()
      ?: return scheduleOwnershipRetry(ledger, initial)
    try {
      val secret = vault.load(sessionId) ?: run {
        terminateFailure(
          ledger,
          vault,
          initial,
          AccessReasonCode.CREDENTIAL_INACTIVE,
          "ENCRYPTED_LOCATOR_UNAVAILABLE",
        )
        return Result.failure()
      }
      val configuredCredential = BleCredentialConfigStore(applicationContext).credentialId()
      if (configuredCredential == null || !configuredCredential.contentEquals(secret.credentialId)) {
        configuredCredential?.fill(0)
        secret.credentialId.fill(0)
        terminateFailure(
          ledger,
          vault,
          initial,
          AccessReasonCode.CREDENTIAL_INACTIVE,
          "CREDENTIAL_BINDING_MISMATCH",
        )
        return Result.failure()
      }
      configuredCredential.fill(0)
      val attempt = initial.attempt + 1
      val runningEpochMs = System.currentTimeMillis()
      val running = initial.copy(
        attempt = attempt,
        state = DurableSessionState.RUNNING,
        updatedEpochMs = runningEpochMs,
        dispatchStartedEpochMs = runningEpochMs,
        presenceToDispatchMs = HandsFreeDispatchPolicy.presenceAgeMs(
          initial.createdEpochMs,
          runningEpochMs,
        ),
        presenceToArmedMs = null,
        reasonCode = null,
        targetReasonCode = null,
        targetReasonName = null,
        transportReason = null,
        transportStatus = null,
        retryAfterMs = null,
        scheduledRetryDelayMs = null,
        gattPerformance = null,
      )
      ledger.update(running)
      var flagDisabledBeforeProof = false
      val outcome = GattSessionEngine(
        transport = AndroidBleGattTransport(applicationContext),
        signer = AndroidKeystoreCredentialSigner(),
        proofObserver = object : ProofExecutionObserver {
          override fun beforeProofWrite() {
            if (!BleGattFeatureFlagStore(applicationContext).decision().newWorkerEnabled) {
              flagDisabledBeforeProof = true
              throw FeatureFlagDisabledBeforeProofException()
            }
            val current = ledger.get(sessionId) ?: throw IllegalStateException("session disappeared")
            check(
              current.state == DurableSessionState.RUNNING &&
                ledgerUpdateUncertain(ledger, current),
            ) { "failed durable pre-proof commit" }
            // A crash after this boundary must not retain or reuse raw connection locators.
            vault.delete(sessionId)
          }
        },
      ).run(
        secret.deviceAddress,
        secret.credentialId,
        GattProtocol.ACTION_ARM_FOR_SENSOR,
      )
      if (flagDisabledBeforeProof) {
        secret.credentialId.fill(0)
        terminateDisabled(ledger, vault, ledger.get(sessionId) ?: running)
        return Result.success()
      }
      val result = commitOutcome(ledger, vault, running, secret, outcome)
      secret.credentialId.fill(0)
      return result
    } finally {
      ownerLease.close()
    }
  }

  private fun ledgerUpdateUncertain(ledger: DurableSessionLedger, current: DurableGattSession): Boolean = try {
    ledger.update(
      current.copy(
        state = DurableSessionState.PROOF_UNCERTAIN,
        updatedEpochMs = System.currentTimeMillis(),
        reasonCode = "PROOF_OUTCOME_UNCERTAIN",
      ),
    )
    true
  } catch (_: Exception) {
    false
  }

  private fun commitOutcome(
    ledger: DurableSessionLedger,
    vault: LocatorVault,
    running: DurableGattSession,
    secret: LocatorSecret,
    outcome: SessionOutcome,
  ): Result = when (outcome) {
    is SessionOutcome.Success -> {
      val armedEpochMs = System.currentTimeMillis()
      ledger.update(
        running.copy(
          state = DurableSessionState.SUCCEEDED,
          updatedEpochMs = armedEpochMs,
          reasonCode = null,
          latencyMs = outcome.latencyMs,
          presenceToArmedMs = HandsFreeDispatchPolicy.presenceAgeMs(
            running.createdEpochMs,
            armedEpochMs,
          ),
          activeAclVersion = outcome.activeAclVersion,
          gattPerformance = outcome.performance,
        ),
      )
      vault.delete(running.id)
      AccessResultNotifier.post(applicationContext, DurableSessionState.SUCCEEDED)
      Result.success()
    }
    is SessionOutcome.Failure -> {
      val retry = RetryPolicy.shouldRetry(running.attempt, outcome)
      if (outcome.proofMayHaveExecuted && outcome.targetReason == null) {
        // No authenticated Target result resolved whether proof/ARM executed. Never replay this wake.
        ledger.update(failureCopy(running, outcome, DurableSessionState.PROOF_UNCERTAIN, null))
        vault.delete(running.id)
        AccessResultNotifier.post(
          applicationContext,
          DurableSessionState.PROOF_UNCERTAIN,
          "PROOF_OUTCOME_UNCERTAIN",
        )
        Result.success()
      } else if (retry) {
        val delayMs = RetryPolicy.boundedDelayMs(running.attempt, outcome.retryAfterMs)
        val retrySession = failureCopy(running, outcome, DurableSessionState.RETRY_PENDING, delayMs)
        ledger.update(retrySession)
        vault.store(running.id, secret)
        BleGattWorkScheduler.enqueueRetry(applicationContext, running.id, delayMs)
        Result.success()
      } else {
        ledger.update(failureCopy(running, outcome, DurableSessionState.FAILED, null))
        vault.delete(running.id)
        AccessResultNotifier.post(
          applicationContext,
          DurableSessionState.FAILED,
          outcome.reason.schemaReason,
        )
        Result.failure()
      }
    }
  }

  private fun failureCopy(
    session: DurableGattSession,
    failure: SessionOutcome.Failure,
    state: DurableSessionState,
    scheduledDelayMs: Long?,
  ): DurableGattSession = session.copy(
    state = state,
    updatedEpochMs = System.currentTimeMillis(),
    reasonCode = if (state == DurableSessionState.PROOF_UNCERTAIN) {
      "PROOF_OUTCOME_UNCERTAIN"
    } else {
      failure.reason.schemaReason
    },
    targetReasonCode = failure.targetReason?.wireCode,
    targetReasonName = failure.targetReason?.wireName,
    transportReason = failure.transportFailure?.name,
    transportStatus = failure.transportStatus,
    retryAfterMs = failure.retryAfterMs,
    scheduledRetryDelayMs = scheduledDelayMs,
    latencyMs = failure.latencyMs,
    gattPerformance = failure.performance,
  )

  private fun scheduleOwnershipRetry(
    ledger: DurableSessionLedger,
    session: DurableGattSession,
  ): Result {
    val attempt = session.attempt + 1
    if (attempt >= RetryPolicy.MAX_ATTEMPTS) {
      ledger.update(
        session.copy(
          attempt = attempt,
          state = DurableSessionState.FAILED,
          updatedEpochMs = System.currentTimeMillis(),
          reasonCode = AccessReasonCode.GATT_CONNECT_FAILED.schemaReason,
          transportReason = "BLE_OWNER_CONFLICT",
        ),
      )
      AndroidEncryptedLocatorVault(applicationContext).delete(session.id)
      AccessResultNotifier.post(
        applicationContext,
        DurableSessionState.FAILED,
        AccessReasonCode.GATT_CONNECT_FAILED.schemaReason,
      )
      return Result.failure()
    }
    val delayMs = RetryPolicy.boundedDelayMs(attempt)
    ledger.update(
      session.copy(
        attempt = attempt,
        state = DurableSessionState.RETRY_PENDING,
        updatedEpochMs = System.currentTimeMillis(),
        reasonCode = AccessReasonCode.GATT_CONNECT_FAILED.schemaReason,
        transportReason = "BLE_OWNER_CONFLICT",
        scheduledRetryDelayMs = delayMs,
      ),
    )
    BleGattWorkScheduler.enqueueRetry(applicationContext, session.id, delayMs)
    return Result.success()
  }

  private fun terminateDisabled(
    ledger: DurableSessionLedger,
    vault: LocatorVault,
    session: DurableGattSession,
  ) {
    ledger.update(
      session.copy(
        state = DurableSessionState.DISABLED,
        updatedEpochMs = System.currentTimeMillis(),
      ),
    )
    vault.delete(session.id)
    AccessResultNotifier.post(applicationContext, DurableSessionState.DISABLED)
  }

  private fun terminateFailure(
    ledger: DurableSessionLedger,
    vault: LocatorVault,
    session: DurableGattSession,
    reason: AccessReasonCode,
    transportReason: String,
  ) {
    ledger.update(
      session.copy(
        state = DurableSessionState.FAILED,
        updatedEpochMs = System.currentTimeMillis(),
        reasonCode = reason.schemaReason,
        transportReason = transportReason,
      ),
    )
    vault.delete(session.id)
    AccessResultNotifier.post(
      applicationContext,
      DurableSessionState.FAILED,
      reason.schemaReason,
    )
  }
}

object BleGattHealthBridge {
  fun snapshot(context: Context): Map<String, Any?> {
    val flagStore = BleGattFeatureFlagStore(context.applicationContext)
    val decision = flagStore.decision()
    val localConsent = flagStore.localConsentStatus()
    val last = SharedPreferencesSessionLedger(context.applicationContext).last()
    val wakeRegistration = com.kshouse.gatekeeper_app.blewake.BleWakeRegistrar.status(context)
    val blockingReason = BleGattRuntimeEnvironment.currentBlockingReason(context)
    return mapOf(
      "featureEnabled" to decision.newWorkerEnabled,
      "featureStatus" to decision.status,
      "featureRevision" to decision.revision,
      "bleOwner" to decision.owner,
      "localBootstrapAllowed" to flagStore.localBootstrapAllowed(),
      "credentialProvisioned" to localConsent.credentialProvisioned,
      "localConsentValid" to localConsent.valid,
      "healthy" to (last?.state !in setOf(DurableSessionState.FAILED, DurableSessionState.PROOF_UNCERTAIN)),
      "latestDetection" to BleWakeJournal.latestRedacted(context.applicationContext),
      "lastSession" to last?.redactedMap(),
      "lastReasonCode" to last?.reasonCode,
      "lastTargetReasonCode" to last?.targetReasonCode,
      "lastTargetReasonName" to last?.targetReasonName,
      "lastTransportReason" to last?.transportReason,
      "lastRetryAfterMs" to last?.retryAfterMs,
      "lastScheduledRetryDelayMs" to last?.scheduledRetryDelayMs,
      "lastLatencyMs" to last?.latencyMs,
      "lastPresenceToDispatchMs" to last?.presenceToDispatchMs,
      "lastPresenceToArmedMs" to last?.presenceToArmedMs,
      "lastActiveAclVersion" to last?.activeAclVersion,
      "lastGattPerformance" to last?.gattPerformance?.redactedMap(),
      "wakeRegistrationStatus" to wakeRegistration.status,
      "wakeRegistered" to wakeRegistration.enabled,
      "handsFreeReady" to (
        decision.newWorkerEnabled && wakeRegistration.enabled && blockingReason == null
      ),
      "initialWorkExpedited" to (
        Build.VERSION.SDK_INT >= BleGattWorkScheduler.EXPEDITED_MIN_API
      ),
      "maxPresenceAgeMs" to HandsFreeDispatchPolicy.MAX_PRESENCE_AGE_MS,
      "currentBlockingReasonCode" to blockingReason,
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
      (
        appContext.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED ||
          appContext.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
      )
    ) return AccessReasonCode.PERMISSION_DENIED.schemaReason
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
      appContext.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED
    ) return AccessReasonCode.PERMISSION_DENIED.schemaReason
    if (
      Build.VERSION.SDK_INT in Build.VERSION_CODES.Q..Build.VERSION_CODES.R &&
      appContext.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) != PackageManager.PERMISSION_GRANTED
    ) return AccessReasonCode.PERMISSION_DENIED.schemaReason
    val adapter = appContext.getSystemService(BluetoothManager::class.java)?.adapter
    if (adapter == null || !adapter.isEnabled) return AccessReasonCode.BLUETOOTH_DISABLED.schemaReason
    val power = appContext.getSystemService(PowerManager::class.java)
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
      power != null && !power.isIgnoringBatteryOptimizations(appContext.packageName)
    ) return AccessReasonCode.BATTERY_RESTRICTED.schemaReason
    return appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_LAST_BLOCKED, null)
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
