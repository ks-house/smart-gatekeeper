package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import com.kshouse.gatekeeper_app.blewake.BleWakeRegistrar
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

object AccountLogoutCanonical {
  private val domain = "SGKOUT01".toByteArray(Charsets.US_ASCII)

  fun build(
    credentialId: ByteArray,
    nonce: ByteArray,
    expiresAtEpochSeconds: Long,
    idempotencyKey: String,
  ): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    require(nonce.size == 32) { "nonce length" }
    require(expiresAtEpochSeconds > 0) { "expiry" }
    require(idempotencyKey.length in 16..128) { "idempotency" }
    return ByteBuffer.allocate(96)
      .order(ByteOrder.BIG_ENDIAN)
      .put(domain)
      .put(credentialId)
      .put(nonce)
      .putLong(expiresAtEpochSeconds)
      .put(MessageDigest.getInstance("SHA-256").digest(idempotencyKey.toByteArray()))
      .array()
  }
}

object AccountLogoutManager {
  fun sign(
    context: Context,
    nonceHex: String,
    expiresAtEpochSeconds: Long,
    idempotencyKey: String,
  ): RemoteManualOpenProofResult {
    val credential = BleCredentialConfigStore(context.applicationContext).credentialId()
      ?: return RemoteManualOpenProofResult(false, "CREDENTIAL_UNAVAILABLE")
    return try {
      val signature = AndroidKeystoreCredentialSigner().signCanonical(
        credential,
        AccountLogoutCanonical.build(
          credential,
          nonceHex.hexToBytes(),
          expiresAtEpochSeconds,
          idempotencyKey,
        ),
      )
      RemoteManualOpenProofResult(true, "SIGNED", credential.toHex(), signature.toHex())
    } catch (_: Exception) {
      RemoteManualOpenProofResult(false, "LOGOUT_PROOF_UNAVAILABLE")
    } finally {
      credential.fill(0)
    }
  }

  /** Called only after Backend revocation and account unlink succeeded. */
  fun clearLocalIdentity(context: Context): Map<String, Any?> {
    val app = context.applicationContext
    val credentialStore = BleCredentialConfigStore(app)
    val credential = credentialStore.credentialId()
      ?: return mapOf("accepted" to true, "reason" to "ALREADY_LOGGED_OUT")
    return try {
      BleWakeRegistrar.stop(app)
      BleGattWorkScheduler.cancelAll(app)
      val flagCleared = BleGattFeatureFlagStore(app).clearForLogout()
      val sessionsCleared = SharedPreferencesSessionLedger(app).clear()
      val sessionLocatorsCleared = AndroidEncryptedLocatorVault(app).clearAll()
      val currentLocatorCleared = AuthenticatedTargetLocatorStore(app).clear()
      val locatorsCleared = sessionLocatorsCleared && currentLocatorCleared
      val keyCleared = AndroidKeystoreCredentialSigner().deleteCredentialKey(credential)
      val credentialCleared = credentialStore.clear()
      // Server revocation is already complete. The authorization material is
      // gone once both the key and credential locator are deleted; the other
      // stores contain only disabled/redacted recovery diagnostics.
      val accepted = keyCleared && credentialCleared
      mapOf(
        "accepted" to accepted,
        "reason" to when {
          !accepted -> "LOCAL_CLEAR_INCOMPLETE"
          flagCleared && sessionsCleared && locatorsCleared -> "LOCAL_IDENTITY_CLEARED"
          else -> "LOCAL_IDENTITY_CLEARED_WITH_RECOVERY_DATA_REMNANTS"
        },
      )
    } finally {
      credential.fill(0)
    }
  }
}
