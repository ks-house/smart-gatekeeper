package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.withTimeout

interface BleGattTransport {
  suspend fun connect(deviceAddress: String)
  suspend fun negotiate(clientHello: ByteArray): ByteArray
  suspend fun readChallenge(): ByteArray
  suspend fun writeProof(proof: ByteArray)
  suspend fun awaitResult(): ByteArray
  fun close()
}

enum class AccessReasonCode(val schemaReason: String, val retryable: Boolean) {
  PERMISSION_DENIED("PERMISSION_DENIED", false),
  BLUETOOTH_DISABLED("BLUETOOTH_DISABLED", true),
  FORCE_STOPPED("FORCE_STOPPED", false),
  BATTERY_RESTRICTED("BATTERY_RESTRICTED", true),
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

sealed class SessionOutcome {
  data class Success(val latencyMs: Long, val activeAclVersion: Long) : SessionOutcome()
  data class Failure(
    val reason: AccessReasonCode,
    val latencyMs: Long,
    val retryAfterMs: Long = 0,
  ) : SessionOutcome()
}

fun interface MonotonicClock {
  fun nowMs(): Long
}

class GattSessionEngine(
  private val transport: BleGattTransport,
  private val signer: CredentialSigner,
  private val timeoutMs: Long = 15_000,
  private val clock: MonotonicClock = MonotonicClock { android.os.SystemClock.elapsedRealtime() },
  private val mobileBuild: Long = 0,
) {
  suspend fun run(deviceAddress: String, credentialId: ByteArray): SessionOutcome {
    val started = clock.nowMs()
    return try {
      withTimeout(timeoutMs) {
        transport.connect(deviceAddress)
        val clientHello = GattCanonicalCodec.clientHello(mobileBuild)
        val targetHelloBytes = transport.negotiate(clientHello)
        val targetHello = GattCanonicalCodec.parseTargetHello(targetHelloBytes)
        val negotiationHash = GattCanonicalCodec.sha256(clientHello + targetHello.canonical)
        val challenge = GattCanonicalCodec.parseChallenge(
          transport.readChallenge(),
          negotiationHash,
        )
        val canonical = GattCanonicalCodec.proofSigningInput(challenge.canonical, credentialId)
        val signature = signer.signCanonical(credentialId, canonical)
        transport.writeProof(GattCanonicalCodec.proofWire(challenge, credentialId, signature))
        val result = GattCanonicalCodec.parseResult(transport.awaitResult(), challenge.sessionId)
        val elapsed = (clock.nowMs() - started).coerceAtLeast(0)
        if (result.reason == 0) {
          SessionOutcome.Success(elapsed, result.activeAclVersion)
        } else {
          SessionOutcome.Failure(mapTargetReason(result.reason), elapsed, result.retryAfterMs)
        }
      }
    } catch (_: kotlinx.coroutines.TimeoutCancellationException) {
      SessionOutcome.Failure(AccessReasonCode.GATT_TIMEOUT, elapsed(started))
    } catch (_: SecurityException) {
      SessionOutcome.Failure(AccessReasonCode.PERMISSION_DENIED, elapsed(started))
    } catch (_: BluetoothDisabledException) {
      SessionOutcome.Failure(AccessReasonCode.BLUETOOTH_DISABLED, elapsed(started))
    } catch (_: CredentialKeyUnavailableException) {
      SessionOutcome.Failure(AccessReasonCode.CREDENTIAL_INACTIVE, elapsed(started))
    } catch (error: IllegalArgumentException) {
      val reason = if (error.message.orEmpty().contains("protocol")) {
        AccessReasonCode.PROTOCOL_INCOMPATIBLE
      } else {
        AccessReasonCode.MALFORMED_PROOF
      }
      SessionOutcome.Failure(reason, elapsed(started))
    } catch (_: GattDisconnectedException) {
      SessionOutcome.Failure(AccessReasonCode.GATT_DISCONNECTED, elapsed(started))
    } catch (_: Throwable) {
      SessionOutcome.Failure(AccessReasonCode.GATT_CONNECT_FAILED, elapsed(started))
    } finally {
      transport.close()
    }
  }

  private fun elapsed(started: Long): Long = (clock.nowMs() - started).coerceAtLeast(0)

  private fun mapTargetReason(reason: Int): AccessReasonCode = when (reason) {
    1 -> AccessReasonCode.PROTOCOL_INCOMPATIBLE
    2 -> AccessReasonCode.MALFORMED_PROOF
    3 -> AccessReasonCode.PROOF_EXPIRED
    4 -> AccessReasonCode.NONCE_REPLAYED
    5 -> AccessReasonCode.ACL_NOT_FOUND
    6 -> AccessReasonCode.CREDENTIAL_INACTIVE
    7 -> AccessReasonCode.SIGNATURE_INVALID
    8, 9 -> AccessReasonCode.TARGET_BUSY
    else -> AccessReasonCode.INTERNAL_ERROR
  }
}

class GattDisconnectedException : IllegalStateException("GATT disconnected")

object RetryPolicy {
  const val MAX_ATTEMPTS = 3
  const val WORK_BACKOFF_SECONDS = 10L

  fun shouldRetry(attempt: Int, failure: SessionOutcome.Failure): Boolean =
    attempt < MAX_ATTEMPTS && failure.reason.retryable

  fun boundedDelayMs(attempt: Int, targetRetryAfterMs: Long = 0): Long {
    val exponential = (500L shl (attempt - 1).coerceIn(0, 3)).coerceAtMost(4_000L)
    return maxOf(exponential, targetRetryAfterMs.coerceIn(0, 4_000L))
  }
}
