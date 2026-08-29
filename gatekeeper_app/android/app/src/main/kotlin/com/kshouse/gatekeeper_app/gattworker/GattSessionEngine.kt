package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.withTimeout

enum class MtuNegotiationStatus {
  NOT_REQUESTED,
  REQUESTED,
  ACCEPTED,
  REJECTED,
  TIMED_OUT,
}

data class GattTransportPerformance(
  val negotiatedMtu: Int = 23,
  val mtuStatus: MtuNegotiationStatus = MtuNegotiationStatus.NOT_REQUESTED,
  val highPriorityRequested: Boolean = false,
)

data class GattSessionPerformance(
  val connectSetupMs: Long? = null,
  val negotiationMs: Long? = null,
  val challengeMs: Long? = null,
  val signingMs: Long? = null,
  val proofWriteMs: Long? = null,
  val resultWaitMs: Long? = null,
  val transport: GattTransportPerformance = GattTransportPerformance(),
) {
  fun redactedMap(): Map<String, Any?> = mapOf(
    "connectSetupMs" to connectSetupMs,
    "negotiationMs" to negotiationMs,
    "challengeMs" to challengeMs,
    "signingMs" to signingMs,
    "proofWriteMs" to proofWriteMs,
    "resultWaitMs" to resultWaitMs,
    "negotiatedMtu" to transport.negotiatedMtu,
    "mtuStatus" to transport.mtuStatus.name,
    "highPriorityRequested" to transport.highPriorityRequested,
  )
}

interface BleGattTransport {
  suspend fun connect(deviceAddress: String)
  suspend fun negotiate(clientHello: ByteArray): ByteArray
  suspend fun readChallenge(): ByteArray
  suspend fun writeProof(proof: ByteArray)
  suspend fun awaitResult(): ByteArray
  fun performanceSnapshot(): GattTransportPerformance = GattTransportPerformance()
  fun close()
}

enum class AccessReasonCode(val schemaReason: String, val retryable: Boolean) {
  PERMISSION_DENIED("PERMISSION_DENIED", false),
  BLUETOOTH_DISABLED("BLUETOOTH_DISABLED", true),
  FORCE_STOPPED("FORCE_STOPPED", false),
  BATTERY_RESTRICTED("BATTERY_RESTRICTED", true),
  PRESENCE_EXPIRED("PRESENCE_EXPIRED", false),
  GATT_CONNECT_FAILED("GATT_CONNECT_FAILED", true),
  GATT_TIMEOUT("GATT_TIMEOUT", true),
  GATT_DISCONNECTED("GATT_DISCONNECTED", true),
  SIGNATURE_INVALID("SIGNATURE_INVALID", false),
  PROOF_EXPIRED("PROOF_EXPIRED", false),
  NONCE_REPLAYED("NONCE_REPLAYED", false),
  MALFORMED_PROOF("MALFORMED_PROOF", false),
  PROTOCOL_INCOMPATIBLE("PROTOCOL_INCOMPATIBLE", false),
  ACL_NOT_FOUND("ACL_NOT_FOUND", false),
  CREDENTIAL_INACTIVE("CREDENTIAL_INACTIVE", false),
  TARGET_BUSY("TARGET_BUSY", true),
  INTERNAL_ERROR("INTERNAL_ERROR", false),
}

enum class TargetResultReason(
  val wireCode: Int,
  val wireName: String,
  val observabilityReason: AccessReasonCode,
  val retryable: Boolean,
) {
  UNSUPPORTED_VERSION(1, "UNSUPPORTED_VERSION", AccessReasonCode.PROTOCOL_INCOMPATIBLE, false),
  MALFORMED(2, "MALFORMED", AccessReasonCode.MALFORMED_PROOF, false),
  SESSION_INVALID(3, "SESSION_INVALID", AccessReasonCode.NONCE_REPLAYED, false),
  EXPIRED_OR_REPLAY(4, "EXPIRED_OR_REPLAY", AccessReasonCode.PROOF_EXPIRED, false),
  ACL_UNAVAILABLE(5, "ACL_UNAVAILABLE", AccessReasonCode.ACL_NOT_FOUND, true),
  CREDENTIAL_DENIED(6, "CREDENTIAL_DENIED", AccessReasonCode.CREDENTIAL_INACTIVE, false),
  PROOF_INVALID(7, "PROOF_INVALID", AccessReasonCode.SIGNATURE_INVALID, false),
  BUSY(8, "BUSY", AccessReasonCode.TARGET_BUSY, true),
  RATE_LIMITED(9, "RATE_LIMITED", AccessReasonCode.TARGET_BUSY, true),
  INTERNAL_FAIL_CLOSED(10, "INTERNAL_FAIL_CLOSED", AccessReasonCode.INTERNAL_ERROR, false),
  ;

  companion object {
    fun fromWireCode(code: Int): TargetResultReason = entries.firstOrNull { it.wireCode == code }
      ?: throw IllegalArgumentException("unknown target result reason")
  }
}

enum class TransportFailureCode(val observabilityReason: AccessReasonCode) {
  DISCONNECTED(AccessReasonCode.GATT_DISCONNECTED),
  READ_FAILED(AccessReasonCode.GATT_CONNECT_FAILED),
  WRITE_FAILED(AccessReasonCode.GATT_CONNECT_FAILED),
  DESCRIPTOR_WRITE_FAILED(AccessReasonCode.GATT_CONNECT_FAILED),
  SERVICE_DISCOVERY_FAILED(AccessReasonCode.GATT_CONNECT_FAILED),
  MALFORMED_FRAME(AccessReasonCode.MALFORMED_PROOF),
  UNEXPECTED_MESSAGE_TYPE(AccessReasonCode.PROTOCOL_INCOMPATIBLE),
}

open class GattTransportException(
  val failureCode: TransportFailureCode,
  val gattStatus: Int? = null,
  cause: Throwable? = null,
) : IllegalStateException(failureCode.name, cause)

sealed class SessionOutcome {
  data class Success(
    val latencyMs: Long,
    val activeAclVersion: Long,
    val performance: GattSessionPerformance? = null,
  ) : SessionOutcome()
  data class Failure(
    val reason: AccessReasonCode,
    val latencyMs: Long,
    val retryAfterMs: Long = 0,
    val targetReason: TargetResultReason? = null,
    val transportFailure: TransportFailureCode? = null,
    val transportStatus: Int? = null,
    val proofMayHaveExecuted: Boolean = false,
    val performance: GattSessionPerformance? = null,
  ) : SessionOutcome() {
    val retryable: Boolean
      get() = targetReason?.retryable ?: reason.retryable
  }
}

fun interface MonotonicClock {
  fun nowMs(): Long
}

interface ProofExecutionObserver {
  /** Must durably commit PROOF_UNCERTAIN before returning. */
  fun beforeProofWrite()
  fun afterProofWrite() {}
  fun afterResultReceived(result: TargetResult) {}

  companion object {
    val NONE = object : ProofExecutionObserver {
      override fun beforeProofWrite() = Unit
    }
  }
}

class GattSessionEngine(
  private val transport: BleGattTransport,
  private val signer: CredentialSigner,
  private val timeoutMs: Long = 15_000,
  private val clock: MonotonicClock = MonotonicClock { android.os.SystemClock.elapsedRealtime() },
  private val mobileBuild: Long = 0,
  private val proofObserver: ProofExecutionObserver = ProofExecutionObserver.NONE,
) {
  suspend fun run(
    deviceAddress: String,
    credentialId: ByteArray,
    action: Int = GattProtocol.ACTION_ARM_FOR_SENSOR,
  ): SessionOutcome {
    require(
      action == GattProtocol.ACTION_ARM_FOR_SENSOR ||
        action == GattProtocol.ACTION_OPEN_IMMEDIATELY,
    ) { "unsupported local access action" }
    val started = clock.nowMs()
    var phaseStarted = started
    var connectSetupMs: Long? = null
    var negotiationMs: Long? = null
    var challengeMs: Long? = null
    var signingMs: Long? = null
    var proofWriteMs: Long? = null
    var resultWaitMs: Long? = null
    var proofMayHaveExecuted = false

    fun markPhase(): Long {
      val now = clock.nowMs()
      return (now - phaseStarted).coerceAtLeast(0).also { phaseStarted = now }
    }

    fun performance() = GattSessionPerformance(
      connectSetupMs = connectSetupMs,
      negotiationMs = negotiationMs,
      challengeMs = challengeMs,
      signingMs = signingMs,
      proofWriteMs = proofWriteMs,
      resultWaitMs = resultWaitMs,
      transport = transport.performanceSnapshot(),
    )

    return try {
      withTimeout(timeoutMs) {
        transport.connect(deviceAddress)
        connectSetupMs = markPhase()
        val clientHello = GattCanonicalCodec.clientHello(mobileBuild)
        val targetHelloBytes = transport.negotiate(clientHello)
        val targetHello = GattCanonicalCodec.parseTargetHello(targetHelloBytes)
        negotiationMs = markPhase()
        val negotiationHash = GattCanonicalCodec.sha256(clientHello + targetHello.canonical)
        val challenge = GattCanonicalCodec.parseChallenge(
          transport.readChallenge(),
          negotiationHash,
        )
        challengeMs = markPhase()
        val canonical = GattCanonicalCodec.proofSigningInput(
          challenge.canonical,
          credentialId,
          action,
        )
        val signature = signer.signCanonical(credentialId, canonical)
        signingMs = markPhase()
        proofObserver.beforeProofWrite()
        proofMayHaveExecuted = true
        transport.writeProof(
          GattCanonicalCodec.proofWire(challenge, credentialId, signature, action),
        )
        proofWriteMs = markPhase()
        proofObserver.afterProofWrite()
        val result = GattCanonicalCodec.parseResult(transport.awaitResult(), challenge.sessionId)
        resultWaitMs = markPhase()
        proofObserver.afterResultReceived(result)
        val elapsed = elapsed(started)
        if (result.reason == 0) {
          SessionOutcome.Success(elapsed, result.activeAclVersion, performance())
        } else {
          val targetReason = TargetResultReason.fromWireCode(result.reason)
          SessionOutcome.Failure(
            reason = targetReason.observabilityReason,
            latencyMs = elapsed,
            retryAfterMs = result.retryAfterMs,
            targetReason = targetReason,
            proofMayHaveExecuted = true,
            performance = performance(),
          )
        }
      }
    } catch (_: kotlinx.coroutines.TimeoutCancellationException) {
      SessionOutcome.Failure(
        AccessReasonCode.GATT_TIMEOUT,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (_: SecurityException) {
      SessionOutcome.Failure(
        AccessReasonCode.PERMISSION_DENIED,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (_: BluetoothDisabledException) {
      SessionOutcome.Failure(
        AccessReasonCode.BLUETOOTH_DISABLED,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (_: CredentialKeyUnavailableException) {
      SessionOutcome.Failure(
        AccessReasonCode.CREDENTIAL_INACTIVE,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (error: GattTransportException) {
      SessionOutcome.Failure(
        reason = error.failureCode.observabilityReason,
        latencyMs = elapsed(started),
        transportFailure = error.failureCode,
        transportStatus = error.gattStatus,
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (error: TargetHelloRejectedException) {
      SessionOutcome.Failure(
        reason = if (error.status == 2) {
          AccessReasonCode.TARGET_BUSY
        } else {
          AccessReasonCode.PROTOCOL_INCOMPATIBLE
        },
        latencyMs = elapsed(started),
        proofMayHaveExecuted = false,
        performance = performance(),
      )
    } catch (error: IllegalArgumentException) {
      val reason = if (error.message.orEmpty().contains("protocol")) {
        AccessReasonCode.PROTOCOL_INCOMPATIBLE
      } else {
        AccessReasonCode.MALFORMED_PROOF
      }
      SessionOutcome.Failure(
        reason,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } catch (_: FeatureFlagDisabledBeforeProofException) {
      SessionOutcome.Failure(
        AccessReasonCode.CREDENTIAL_INACTIVE,
        elapsed(started),
        proofMayHaveExecuted = false,
        performance = performance(),
      )
    } catch (_: Exception) {
      SessionOutcome.Failure(
        AccessReasonCode.GATT_CONNECT_FAILED,
        elapsed(started),
        proofMayHaveExecuted = proofMayHaveExecuted,
        performance = performance(),
      )
    } finally {
      transport.close()
    }
  }

  private fun elapsed(started: Long): Long = (clock.nowMs() - started).coerceAtLeast(0)
}

class FeatureFlagDisabledBeforeProofException : IllegalStateException("feature flag disabled before proof")

object DurableAttemptPolicy {
  fun canExecute(state: DurableSessionState): Boolean = state in setOf(
    DurableSessionState.QUEUED,
    DurableSessionState.RUNNING,
    DurableSessionState.RETRY_PENDING,
  )
}

object RetryPolicy {
  const val MAX_ATTEMPTS = 3
  const val WORK_BACKOFF_SECONDS = 10L
  const val MAX_TARGET_RETRY_AFTER_MS = 30_000L

  fun shouldRetry(attempt: Int, failure: SessionOutcome.Failure): Boolean =
    attempt < MAX_ATTEMPTS && failure.retryable

  fun boundedDelayMs(attempt: Int, targetRetryAfterMs: Long = 0): Long {
    val exponential = (500L shl (attempt - 1).coerceIn(0, 5)).coerceAtMost(16_000L)
    return maxOf(exponential, targetRetryAfterMs.coerceIn(0, MAX_TARGET_RETRY_AFTER_MS))
  }

  fun remainingDelayMs(session: DurableGattSession, nowEpochMs: Long): Long {
    if (session.state != DurableSessionState.RETRY_PENDING) return 0
    val scheduled = session.scheduledRetryDelayMs ?: return 0
    val elapsed = (nowEpochMs - session.updatedEpochMs).coerceAtLeast(0)
    return (scheduled - elapsed).coerceAtLeast(0)
  }
}

object HandsFreeDispatchPolicy {
  const val MAX_PRESENCE_AGE_MS = 45_000L

  fun shouldExpedite(initialDelayMs: Long): Boolean = initialDelayMs <= 0

  fun presenceAgeMs(createdEpochMs: Long, nowEpochMs: Long): Long =
    (nowEpochMs - createdEpochMs).coerceAtLeast(0)

  fun isFresh(createdEpochMs: Long, nowEpochMs: Long): Boolean =
    presenceAgeMs(createdEpochMs, nowEpochMs) <= MAX_PRESENCE_AGE_MS
}
