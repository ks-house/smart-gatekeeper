package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

data class RemoteManualOpenProofResult(
  val accepted: Boolean,
  val reason: String,
  val credentialIdHex: String? = null,
  val signatureRaw64Hex: String? = null,
) {
  fun toMap(): Map<String, Any?> = mapOf(
    "accepted" to accepted,
    "reason" to reason,
    "credentialId" to credentialIdHex,
    "signatureRaw64" to signatureRaw64Hex,
  )
}

/** Canonical proof for one explicit Backend/MQTTS manual-open request. */
object RemoteManualOpenCanonical {
  private val domain = "SGKRMO01".toByteArray(Charsets.US_ASCII)

  fun build(
    credentialId: ByteArray,
    nonce: ByteArray,
    expiresAtEpochSeconds: Long,
    reason: String,
    idempotencyKey: String,
  ): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    require(nonce.size == 32) { "nonce length" }
    require(expiresAtEpochSeconds > 0) { "expiry" }
    require(reason == "mobile_manual_button") { "reason" }
    require(idempotencyKey.length in 16..128) { "idempotency" }
    return ByteBuffer.allocate(128)
      .order(ByteOrder.BIG_ENDIAN)
      .put(domain)
      .put(credentialId)
      .put(nonce)
      .putLong(expiresAtEpochSeconds)
      .put(sha256(reason.toByteArray(Charsets.UTF_8)))
      .put(sha256(idempotencyKey.toByteArray(Charsets.UTF_8)))
      .array()
  }

  private fun sha256(value: ByteArray): ByteArray =
    MessageDigest.getInstance("SHA-256").digest(value)
}

object RemoteManualOpenProofSigner {
  fun sign(
    context: Context,
    nonceHex: String,
    expiresAtEpochSeconds: Long,
    reason: String,
    idempotencyKey: String,
  ): RemoteManualOpenProofResult {
    val credentialId = BleCredentialConfigStore(context.applicationContext).credentialId()
      ?: return RemoteManualOpenProofResult(false, "CREDENTIAL_UNAVAILABLE")
    return try {
      val nonce = nonceHex.hexToBytes()
      val canonical = RemoteManualOpenCanonical.build(
        credentialId,
        nonce,
        expiresAtEpochSeconds,
        reason,
        idempotencyKey,
      )
      val signature = AndroidKeystoreCredentialSigner()
        .signCanonical(credentialId, canonical)
      RemoteManualOpenProofResult(
        true,
        "SIGNED",
        credentialId.toHex(),
        signature.toHex(),
      )
    } catch (_: Exception) {
      RemoteManualOpenProofResult(false, "REMOTE_PROOF_UNAVAILABLE")
    } finally {
      credentialId.fill(0)
    }
  }
}
