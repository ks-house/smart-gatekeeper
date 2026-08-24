package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.content.pm.PackageManager
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.math.BigInteger
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPublicKeySpec

data class RemoteFeatureFlagEnvelope(
  val enabled: Boolean,
  val issuer: String,
  val authorityKeyId: String,
  val revision: Long,
  val issuedEpochMs: Long,
  val expiresEpochMs: Long,
  val credentialId: ByteArray,
  val credentialPublicKeySha256: ByteArray,
  val signatureDer: ByteArray,
) {
  fun canonicalBytes(): ByteArray {
    require(issuer.toByteArray(Charsets.UTF_8).size in 1..64) { "issuer length" }
    require(authorityKeyId.toByteArray(Charsets.UTF_8).size in 1..64) { "authority key id length" }
    require(credentialId.size == 16) { "credential id length" }
    require(credentialPublicKeySha256.size == 32) { "credential public key hash length" }
    return ByteArrayOutputStream().use { output ->
      DataOutputStream(output).use { data ->
        data.write("SGKFLAG1".toByteArray(Charsets.US_ASCII))
        data.writeShort(1)
        data.writeByte(if (enabled) 1 else 0)
        data.writeLengthPrefixed(issuer)
        data.writeLengthPrefixed(authorityKeyId)
        data.writeLong(revision)
        data.writeLong(issuedEpochMs)
        data.writeLong(expiresEpochMs)
        data.write(credentialId)
        data.write(credentialPublicKeySha256)
      }
      output.toByteArray()
    }
  }

  private fun DataOutputStream.writeLengthPrefixed(value: String) {
    val bytes = value.toByteArray(Charsets.UTF_8)
    writeShort(bytes.size)
    write(bytes)
  }
}

data class FeatureFlagAuthority(
  val issuer: String,
  val keyId: String,
  val publicKeySec1: ByteArray,
)

enum class FeatureFlagVerificationStatus {
  AUTHENTICATED,
  AUTHORITY_UNAVAILABLE,
  AUTHORITY_MISMATCH,
  CREDENTIAL_MISMATCH,
  CREDENTIAL_KEY_MISSING,
  REVISION_REPLAY,
  INVALID_TIME_WINDOW,
  INVALID_SIGNATURE,
  MALFORMED,
}

data class FeatureFlagVerification(
  val status: FeatureFlagVerificationStatus,
  val authenticated: Boolean = status == FeatureFlagVerificationStatus.AUTHENTICATED,
)

object RemoteFeatureFlagAuthenticator {
  const val MAX_CLOCK_SKEW_MS = 5 * 60 * 1000L
  const val MAX_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000L

  fun verify(
    envelope: RemoteFeatureFlagEnvelope,
    authority: FeatureFlagAuthority?,
    expectedCredentialId: ByteArray?,
    expectedCredentialPublicKeySha256: ByteArray?,
    nowEpochMs: Long,
    minimumExclusiveRevision: Long? = null,
  ): FeatureFlagVerification = try {
    when {
      authority == null -> FeatureFlagVerification(FeatureFlagVerificationStatus.AUTHORITY_UNAVAILABLE)
      envelope.issuer != authority.issuer || envelope.authorityKeyId != authority.keyId ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.AUTHORITY_MISMATCH)
      expectedCredentialId == null || !envelope.credentialId.contentEquals(expectedCredentialId) ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.CREDENTIAL_MISMATCH)
      expectedCredentialPublicKeySha256 == null ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.CREDENTIAL_KEY_MISSING)
      !envelope.credentialPublicKeySha256.contentEquals(expectedCredentialPublicKeySha256) ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.CREDENTIAL_MISMATCH)
      envelope.revision <= 0 ||
        (minimumExclusiveRevision != null && envelope.revision <= minimumExclusiveRevision) ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.REVISION_REPLAY)
      envelope.issuedEpochMs > nowEpochMs + MAX_CLOCK_SKEW_MS ||
        envelope.expiresEpochMs <= nowEpochMs ||
        envelope.expiresEpochMs <= envelope.issuedEpochMs ||
        envelope.expiresEpochMs - envelope.issuedEpochMs > MAX_LIFETIME_MS ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.INVALID_TIME_WINDOW)
      !verifyP256(authority.publicKeySec1, envelope.canonicalBytes(), envelope.signatureDer) ->
        FeatureFlagVerification(FeatureFlagVerificationStatus.INVALID_SIGNATURE)
      else -> FeatureFlagVerification(FeatureFlagVerificationStatus.AUTHENTICATED)
    }
  } catch (_: RuntimeException) {
    FeatureFlagVerification(FeatureFlagVerificationStatus.MALFORMED)
  } catch (_: java.security.GeneralSecurityException) {
    FeatureFlagVerification(FeatureFlagVerificationStatus.MALFORMED)
  }

  private fun verifyP256(publicKeySec1: ByteArray, canonical: ByteArray, signatureDer: ByteArray): Boolean {
    require(publicKeySec1.size == 65 && publicKeySec1[0] == 0x04.toByte()) { "authority public key" }
    val parameters = AlgorithmParameters.getInstance("EC").apply {
      init(ECGenParameterSpec("secp256r1"))
    }.getParameterSpec(ECParameterSpec::class.java)
    val point = ECPoint(
      BigInteger(1, publicKeySec1.copyOfRange(1, 33)),
      BigInteger(1, publicKeySec1.copyOfRange(33, 65)),
    )
    val publicKey = KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(point, parameters))
    return Signature.getInstance("SHA256withECDSA").run {
      initVerify(publicKey)
      update(canonical)
      verify(signatureDer)
    }
  }
}

object AndroidFeatureFlagAuthorityConfig {
  fun read(context: Context): FeatureFlagAuthority? = try {
    val info = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
      context.packageManager.getApplicationInfo(
        context.packageName,
        PackageManager.ApplicationInfoFlags.of(PackageManager.GET_META_DATA.toLong()),
      )
    } else {
      @Suppress("DEPRECATION")
      context.packageManager.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
    }
    val metadata = info.metaData ?: return null
    val issuer = metadata.getString(META_ISSUER)?.takeIf { it.isNotBlank() } ?: return null
    val keyId = metadata.getString(META_KEY_ID)?.takeIf { it.isNotBlank() } ?: return null
    val publicKey = metadata.getString(META_PUBLIC_KEY)?.takeIf { it.matches(Regex("^04[0-9a-fA-F]{128}$")) }
      ?.hexToBytes() ?: return null
    FeatureFlagAuthority(issuer, keyId, publicKey)
  } catch (_: Exception) {
    null
  }

  const val META_ISSUER = "com.kshouse.gatekeeper_app.GATT_FLAG_AUTHORITY_ISSUER"
  const val META_KEY_ID = "com.kshouse.gatekeeper_app.GATT_FLAG_AUTHORITY_KEY_ID"
  const val META_PUBLIC_KEY = "com.kshouse.gatekeeper_app.GATT_FLAG_AUTHORITY_P256_SEC1_HEX"
}

/**
 * Local-manual bootstrap is an APK policy, not a Flutter preference. Android
 * verifies the APK signature before installing an update, while Target ACL
 * proof remains the final authorization boundary.
 */
object AndroidLocalGattBootstrapConfig {
  fun isAllowed(context: Context): Boolean = try {
    val info = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
      context.packageManager.getApplicationInfo(
        context.packageName,
        PackageManager.ApplicationInfoFlags.of(PackageManager.GET_META_DATA.toLong()),
      )
    } else {
      @Suppress("DEPRECATION")
      context.packageManager.getApplicationInfo(context.packageName, PackageManager.GET_META_DATA)
    }
    info.metaData?.getBoolean(META_LOCAL_MANUAL_BOOTSTRAP, false) == true
  } catch (_: Exception) {
    false
  }

  const val META_LOCAL_MANUAL_BOOTSTRAP =
    "com.kshouse.gatekeeper_app.GATT_LOCAL_MANUAL_BOOTSTRAP"
}
