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
import com.kshouse.gatekeeper_app.blewake.ContinuousPresencePolicy
import com.kshouse.gatekeeper_app.blewake.ContinuousPresenceTracker
import java.util.concurrent.TimeUnit

object BleGattWorkScheduler {
  const val HAS_NETWORK_CONSTRAINT = false
  const val UNIQUE_WORK_POLICY = "KEEP"
  const val RETRY_WORK_POLICY = "APPEND_OR_REPLACE"
  const val EXPEDITED_MIN_API = Build.VERSION_CODES.S
  private const val INPUT_SESSION_ID = "session_id"
  private var lastContinuousCheckMs = 0L
  private var lastOrphanCheckMs = 0L

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

  @Synchronized
  fun onContinuousPresence(context: Context, deviceAddress: String, epoch: Long): String? {
    val elapsed = android.os.SystemClock.elapsedRealtime()
    if (elapsed - lastContinuousCheckMs < 1_000) return null // normal packet coalescing, not a lost access decision
    lastContinuousCheckMs = elapsed
    val ledger = SharedPreferencesSessionLedger(context.applicationContext)
    val last = ledger.last()
    val blocked = ContinuousPresencePolicy.blockingReason(last, System.currentTimeMillis())
    if (blocked != null) {
      NativeDiagnostics.record(context, NativeDiagnostics.Event.DISPATCH_SKIPPED, blocked,
        sessionId = last?.id, ready = true, epoch = epoch)
      if (last != null && blocked == "SESSION_ALREADY_ACTIVE") reconcilePreProofOrphan(context, last)
      return null
    }
    return onPresence(context, deviceAddress, ContinuousPresencePolicy.eventId(epoch, last),
      requiresFreshPresence = true, failureRecovery = last?.state == DurableSessionState.FAILED)
  }

  private fun reconcilePreProofOrphan(context: Context, observed: DurableGattSession) {
    val now = android.os.SystemClock.elapsedRealtime()
    if (now - lastOrphanCheckMs < 10_000 || !PreProofOrphanPolicy.oldEnough(observed, System.currentTimeMillis())) return
    lastOrphanCheckMs = now
    val app = context.applicationContext
    try {
      val query = WorkManager.getInstance(app).getWorkInfosForUniqueWork(workName(observed.id))
      query.addListener({
        try {
          val unfinished = query.get().any { !it.state.isFinished }
          synchronized(this) {
            val ledger = SharedPreferencesSessionLedger(app)
            val current = ledger.get(observed.id) ?: return@synchronized
            if (!PreProofOrphanPolicy.mayRecover(current, System.currentTimeMillis(), unfinished)) return@synchronized
            // No live scheduled work and durable state is strictly before proof.
            // Never touch PROOF_UNCERTAIN, replay a proof, or assert a Target result.
            ledger.update(current.copy(state = DurableSessionState.FAILED,
              updatedEpochMs = System.currentTimeMillis(), reasonCode = "GATT_CONNECT_FAILED",
              transportReason = "ORPHANED_PREPROOF_WORK", scheduledRetryDelayMs = null,
              failureRecovery = false))
            AndroidEncryptedLocatorVault(app).delete(current.id)
            NativeDiagnostics.record(app, NativeDiagnostics.Event.ORPHAN_RECOVERED,
              "ORPHANED_PREPROOF_WORK", current.id)
          }
        } catch (_: Exception) {
          NativeDiagnostics.record(app, NativeDiagnostics.Event.DISPATCH_SKIPPED, "ORPHAN_QUERY_UNAVAILABLE", observed.id)
        }
      }, java.util.concurrent.Executor { it.run() })
    } catch (_: Exception) {
      NativeDiagnostics.record(app, NativeDiagnostics.Event.DISPATCH_SKIPPED, "ORPHAN_QUERY_UNAVAILABLE", observed.id)
    }
  }

  @Synchronized
  fun onPresence(context: Context, deviceAddress: String?, presenceEventId: String,
                 requiresFreshPresence: Boolean = false, failureRecovery: Boolean = false): String? {
    if (deviceAddress.isNullOrBlank() || presenceEventId.isBlank()) {
      NativeDiagnostics.record(context, NativeDiagnostics.Event.DISPATCH_SKIPPED, "LOCATOR_UNAVAILABLE")
      return null
    }
    val appContext = context.applicationContext
    if (!BleGattFeatureFlagStore(appContext).decision().newWorkerEnabled) {
      NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED, "NATIVE_GATT_DISABLED")
      return null
    }
    val credentialId = BleCredentialConfigStore(appContext).credentialId() ?: run {
      NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED, "CREDENTIAL_UNAVAILABLE")
      return null
    }
    return try {
      val ledger = SharedPreferencesSessionLedger(appContext)
      val vault = AndroidEncryptedLocatorVault(appContext)
      val (session, duplicate) = PresenceCoalescer(
        ledger,
        AndroidKeystorePresenceFingerprinter(appContext),
      ).enqueue(deviceAddress, presenceEventId, System.currentTimeMillis())
      if (duplicate && !DurableAttemptPolicy.canExecute(session.state)) {
        NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED, "DUPLICATE_TERMINAL_PRESENCE", session.id)
        return session.id
      }
      if (requiresFreshPresence) ledger.update(session.copy(
        requiresFreshPresence = true,
        failureRecovery = session.failureRecovery || failureRecovery,
      ))
      if (!duplicate) vault.store(session.id, LocatorSecret(deviceAddress, credentialId))
      val operation = WorkManager.getInstance(appContext).enqueueUniqueWork(
        workName(session.id),
        ExistingWorkPolicy.KEEP,
        request(session.id, 0),
      )
      operation.result.addListener({
        try {
          operation.result.get() // listener only runs once completion is known; never wait on the BLE callback
          NativeDiagnostics.record(appContext, NativeDiagnostics.Event.WORK_ENQUEUED, sessionId = session.id)
        } catch (_: Exception) {
          NativeDiagnostics.record(appContext, NativeDiagnostics.Event.ENQUEUE_FAILED, "SCHEDULER_UNAVAILABLE", session.id)
        }
      }, java.util.concurrent.Executor { it.run() })
      session.id
    } catch (_: Exception) {
      NativeDiagnostics.record(appContext, NativeDiagnostics.Event.ENQUEUE_FAILED, "STORAGE_OR_SCHEDULER_UNAVAILABLE")
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
    val sessionId = BleGattWorkScheduler.inputSessionId(this)
    NativeDiagnostics.record(applicationContext, NativeDiagnostics.Event.WORKER_STARTED, sessionId = sessionId)
    return try { runSession() } finally {
      NativeDiagnostics.record(applicationContext,
        if (isStopped) NativeDiagnostics.Event.WORKER_STOPPED else NativeDiagnostics.Event.WORKER_FINISHED,
        sessionId = sessionId, status = if (isStopped) stopReason else null)
    }
  }

  private suspend fun runSession(): Result {
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
          override fun onChallengeObserved(targetSessionId: String) {
            val current = ledger.get(sessionId) ?: throw IllegalStateException("session disappeared")
            check(current.state == DurableSessionState.RUNNING)
            ledger.update(current.copy(targetSessionId = targetSessionId))
          }
          override fun beforeProofWrite() {
            if (initial.requiresFreshPresence && !ContinuousPresenceTracker.fresh(
                secret.deviceAddress, android.os.SystemClock.elapsedRealtime())) {
              throw PresenceExpiredBeforeProofException()
            }
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
      val result = commitOutcome(ledger, vault,
        running.copy(targetSessionId = ledger.get(sessionId)?.targetSessionId), secret, outcome)
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
          targetSessionId = outcome.targetSessionId,
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
      // The legacy healthy flag is last-session outcome, NOT scanner liveness.
      "scanDiagnostics" to com.kshouse.gatekeeper_app.blewake.BleScanDiagnostics.snapshot(context),
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
      "wakeRegistrationRequested" to wakeRegistration.requested,
      "wakeRegistrationReconciled" to wakeRegistration.reconciled,
      "wakeRegistered" to wakeRegistration.enabled,
      "wakeRegistrationAttemptedAtEpochMs" to wakeRegistration.attemptedAtEpochMs,
      "wakeRegistrationReconciledAtEpochMs" to wakeRegistration.reconciledAtEpochMs,
      "wakeRegistrationLastCallbackAtEpochMs" to wakeRegistration.lastCallbackAtEpochMs,
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

  fun recentDiagnostics(context: Context): Map<String, Any?> = mapOf(
    "schema" to "sgk-native-diagnostics-v1",
    "androidSdk" to Build.VERSION.SDK_INT,
    "sessions" to SharedPreferencesSessionLedger(context.applicationContext)
      .recent()
      .map { it.redactedMap() },
    "wakeEvents" to BleWakeJournal.recentRedacted(context.applicationContext),
    "runtime" to if (NativeDiagnostics.enabled(context)) NativeDiagnosticReport.bridge(
      NativeDiagnostics.runtime(context, System.currentTimeMillis())) else null,
  )
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
