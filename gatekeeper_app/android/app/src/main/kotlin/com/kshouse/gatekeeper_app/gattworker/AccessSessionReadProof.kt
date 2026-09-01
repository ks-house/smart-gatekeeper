package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.SecureRandom
import java.util.UUID

data class AccessSessionReadProofResult(
  val accepted: Boolean,
  val reason: String,
  val nonceHex: String? = null,
  val expiresAtEpochSeconds: Long? = null,
  val signatureRaw64Hex: String? = null,
) {
  fun toMap(): Map<String, Any?> = mapOf(
    "accepted" to accepted,
    "reason" to reason,
    "nonce" to nonceHex,
    "expiresAt" to expiresAtEpochSeconds,
    "signatureRaw64" to signatureRaw64Hex,
  )
}

object AccessSessionReadCanonical {
  private val domain = "SGKASR01".toByteArray(Charsets.US_ASCII)

  fun build(
    credentialId: ByteArray,
    targetSessionId: ByteArray,
    nonce: ByteArray,
    expiresAtEpochSeconds: Long,
  ): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    require(targetSessionId.size == 16) { "target session id length" }
    require((targetSessionId[6].toInt() and 0xf0) == 0x40) { "target session version" }
    require((targetSessionId[8].toInt() and 0xc0) == 0x80) { "target session variant" }
    require(nonce.size == 32) { "nonce length" }
    require(expiresAtEpochSeconds > 0) { "expiry" }
    return ByteBuffer.allocate(80)
      .order(ByteOrder.BIG_ENDIAN)
      .put(domain)
      .put(credentialId)
      .put(targetSessionId)
      .put(nonce)
      .putLong(expiresAtEpochSeconds)
      .array()
  }

  fun targetSessionBytes(targetSessionUuid: String): ByteArray {
    val uuid = UUID.fromString(targetSessionUuid)
    require(uuid.version() == 4 && uuid.variant() == 2) { "canonical target session" }
    return ByteBuffer.allocate(16)
      .order(ByteOrder.BIG_ENDIAN)
      .putLong(uuid.mostSignificantBits)
      .putLong(uuid.leastSignificantBits)
      .array()
  }
}

object AccessSessionReadProofSigner {
  // The Backend accepts proofs no more than 30 seconds ahead of its own clock.
  // Keep ten seconds of skew headroom for a phone whose clock is fast.
  internal const val PROOF_TTL_SECONDS = 20L

  fun sign(
    context: Context,
    targetSessionUuid: String,
    nowEpochSeconds: Long = System.currentTimeMillis() / 1000,
  ): AccessSessionReadProofResult {
    val credentialId = BleCredentialConfigStore(context.applicationContext).credentialId()
      ?: return AccessSessionReadProofResult(false, "CREDENTIAL_UNAVAILABLE")
    val nonce = ByteArray(32)
    var targetSessionId: ByteArray? = null
    var signature: ByteArray? = null
    return try {
      SecureRandom().nextBytes(nonce)
      val targetSession =
        AccessSessionReadCanonical.targetSessionBytes(targetSessionUuid)
      targetSessionId = targetSession
      val expiresAt = Math.addExact(nowEpochSeconds, PROOF_TTL_SECONDS)
      val canonical = AccessSessionReadCanonical.build(
        credentialId,
        targetSession,
        nonce,
        expiresAt,
      )
      val proofSignature = AndroidKeystoreCredentialSigner().signCanonical(
        credentialId,
        canonical,
      )
      signature = proofSignature
      AccessSessionReadProofResult(
        accepted = true,
        reason = "SIGNED",
        nonceHex = nonce.toHex(),
        expiresAtEpochSeconds = expiresAt,
        signatureRaw64Hex = proofSignature.toHex(),
      )
    } catch (_: Exception) {
      AccessSessionReadProofResult(false, "ACCESS_SESSION_PROOF_UNAVAILABLE")
    } finally {
      credentialId.fill(0)
      nonce.fill(0)
      targetSessionId?.fill(0)
      signature?.fill(0)
    }
  }
}
