package com.kshouse.gatekeeper_app.gattworker

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/** Exposes signing only. Implementations must never return or serialize private key material. */
interface CredentialSigner {
  fun signCanonical(credentialId: ByteArray, canonical: ByteArray): ByteArray
  fun publicKeySec1(credentialId: ByteArray): ByteArray
}

class AndroidKeystoreCredentialSigner : CredentialSigner {
  /** Enrollment-only native seam. Existing credential signing never recreates a missing key. */
  fun createCredentialKey(credentialId: ByteArray): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    val alias = alias(credentialId)
    cleanupLegacyRawAlias(credentialId)
    ensureKey(alias)
    return publicKeySec1(credentialId)
  }

  override fun signCanonical(credentialId: ByteArray, canonical: ByteArray): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    val alias = alias(credentialId)
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    cleanupLegacyRawAlias(credentialId, keyStore)
    val privateKey = keyStore.getKey(alias, null) as? java.security.PrivateKey
      ?: throw CredentialKeyUnavailableException()
    val der = Signature.getInstance("SHA256withECDSA").run {
      initSign(privateKey)
      update(canonical)
      sign()
    }
    return EcdsaSignatureCodec.derToLowSRaw64(der)
  }

  override fun publicKeySec1(credentialId: ByteArray): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    val alias = alias(credentialId)
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    cleanupLegacyRawAlias(credentialId, keyStore)
    val publicKey = keyStore.getCertificate(alias)?.publicKey
      ?: throw CredentialKeyUnavailableException()
    val point = (publicKey as java.security.interfaces.ECPublicKey).w
    return byteArrayOf(0x04) + fixed32(point.affineX.toByteArray()) + fixed32(point.affineY.toByteArray())
  }

  fun deleteCredentialKey(credentialId: ByteArray): Boolean = try {
    require(credentialId.size == 16) { "credential id length" }
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    for (candidate in listOf(
      alias(credentialId),
      "sgk.device.p256.v1.${credentialId.toHex()}",
    )) {
      if (keyStore.containsAlias(candidate)) keyStore.deleteEntry(candidate)
    }
    true
  } catch (_: Exception) {
    false
  }

  private fun ensureKey(alias: String) {
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    if (keyStore.containsAlias(alias)) return
    KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE).apply {
      initialize(
        KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
          .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
          .setDigests(KeyProperties.DIGEST_SHA256)
          .setUserAuthenticationRequired(false)
          .build(),
      )
    }.generateKeyPair()
  }

  private fun alias(credentialId: ByteArray): String =
    "sgk.device.p256.v2.${GattCanonicalCodec.sha256(credentialId).copyOfRange(0, 16).toHex()}"

  private fun cleanupLegacyRawAlias(
    credentialId: ByteArray,
    keyStore: KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) },
  ) {
    val legacyAlias = "sgk.device.p256.v1.${credentialId.toHex()}"
    if (keyStore.containsAlias(legacyAlias)) {
      // A non-exportable key cannot be renamed safely. Remove the raw-locator alias and require
      // authenticated re-enrollment rather than retaining plaintext metadata or silently changing identity.
      keyStore.deleteEntry(legacyAlias)
    }
  }

  private fun fixed32(value: ByteArray): ByteArray {
    val unsigned = value.dropWhile { it == 0.toByte() }.toByteArray()
    require(unsigned.size <= 32) { "public coordinate too large" }
    return ByteArray(32 - unsigned.size) + unsigned
  }

  private companion object {
    const val ANDROID_KEYSTORE = "AndroidKeyStore"
  }
}

class CredentialKeyUnavailableException : IllegalStateException("credential key unavailable")
