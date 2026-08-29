package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import com.flutterbeacon.CrossProcessBleOwnerCoordinator

data class ManualOpenResult(
  val accepted: Boolean,
  val reason: String,
  val sessionId: String? = null,
  val latencyMs: Long? = null,
  val targetReasonCode: Int? = null,
) {
  fun toMap(): Map<String, Any?> = mapOf(
    "accepted" to accepted,
    "reason" to reason,
    "sessionId" to sessionId,
    "latencyMs" to latencyMs,
    "targetReasonCode" to targetReasonCode,
  )
}

/**
 * Foreground manual-open path. It executes GATT immediately on the caller's
 * coroutine and returns only after the authenticated Target RESULT is known.
 * Presence/background sessions remain WorkManager-owned and action 1 only.
 */
object BleGattManualOpenExecutor {
  suspend fun execute(context: Context): ManualOpenResult {
    val appContext = context.applicationContext
    val decision = BleGattFeatureFlagStore(appContext).decision()
    if (!decision.newWorkerEnabled) {
      return ManualOpenResult(false, "NATIVE_GATT_DISABLED:${decision.status}")
    }
    val target = AuthenticatedTargetLocatorStore(appContext).resolve()
      ?: return ManualOpenResult(false, "TARGET_UNAVAILABLE")
    val credentialId = BleCredentialConfigStore(appContext).credentialId()
      ?: return ManualOpenResult(false, "CREDENTIAL_UNAVAILABLE")
    val ownerLease = CrossProcessBleOwnerCoordinator.forContext(appContext).tryAcquireNative()
      ?: run {
        credentialId.fill(0)
        return ManualOpenResult(false, "BLE_OWNER_CONFLICT")
      }

    val ledger = SharedPreferencesSessionLedger(appContext)
    var session: DurableGattSession? = null
    return try {
      val fingerprint = AndroidKeystorePresenceFingerprinter(appContext).fingerprint(
        target.deviceAddress,
        "manual-open-${System.currentTimeMillis()}",
      )
      val queued = ledger.create(fingerprint, System.currentTimeMillis())
      val running = queued.copy(
        attempt = 1,
        state = DurableSessionState.RUNNING,
        updatedEpochMs = System.currentTimeMillis(),
      )
      session = running
      ledger.update(running)
      val outcome = GattSessionEngine(
        transport = AndroidBleGattTransport(appContext),
        signer = AndroidKeystoreCredentialSigner(),
        proofObserver = object : ProofExecutionObserver {
          override fun beforeProofWrite() {
            val uncertain = running.copy(
              state = DurableSessionState.PROOF_UNCERTAIN,
              updatedEpochMs = System.currentTimeMillis(),
              reasonCode = "PROOF_OUTCOME_UNCERTAIN",
            )
            ledger.update(uncertain)
            session = uncertain
          }
        },
      ).run(
        target.deviceAddress,
        credentialId,
        GattProtocol.ACTION_OPEN_IMMEDIATELY,
      )

      when (outcome) {
        is SessionOutcome.Success -> {
          val succeeded = running.copy(
            state = DurableSessionState.SUCCEEDED,
            updatedEpochMs = System.currentTimeMillis(),
            reasonCode = null,
            latencyMs = outcome.latencyMs,
            activeAclVersion = outcome.activeAclVersion,
            gattPerformance = outcome.performance,
          )
          ledger.update(succeeded)
          ManualOpenResult(true, "OPENED", succeeded.id, outcome.latencyMs)
        }
        is SessionOutcome.Failure -> {
          val uncertain = outcome.proofMayHaveExecuted && outcome.targetReason == null
          val failed = running.copy(
            state = if (uncertain) DurableSessionState.PROOF_UNCERTAIN else DurableSessionState.FAILED,
            updatedEpochMs = System.currentTimeMillis(),
            reasonCode = if (uncertain) "PROOF_OUTCOME_UNCERTAIN" else outcome.reason.schemaReason,
            targetReasonCode = outcome.targetReason?.wireCode,
            targetReasonName = outcome.targetReason?.wireName,
            transportReason = outcome.transportFailure?.name,
            transportStatus = outcome.transportStatus,
            retryAfterMs = outcome.retryAfterMs,
            latencyMs = outcome.latencyMs,
            gattPerformance = outcome.performance,
          )
          ledger.update(failed)
          ManualOpenResult(
            false,
            failed.targetReasonName ?: failed.reasonCode ?: "OPEN_FAILED",
            failed.id,
            outcome.latencyMs,
            failed.targetReasonCode,
          )
        }
      }
    } catch (_: Exception) {
      val failed = session?.copy(
        state = DurableSessionState.FAILED,
        updatedEpochMs = System.currentTimeMillis(),
        reasonCode = AccessReasonCode.GATT_CONNECT_FAILED.schemaReason,
      )
      if (failed != null) ledger.update(failed)
      ManualOpenResult(false, "LOCAL_GATT_OPEN_FAILED", failed?.id)
    } finally {
      credentialId.fill(0)
      ownerLease.close()
    }
  }
}
