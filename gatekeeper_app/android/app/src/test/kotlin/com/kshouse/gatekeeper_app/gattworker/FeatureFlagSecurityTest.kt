package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec

class FeatureFlagSecurityTest {
  private val keyPair = KeyPairGenerator.getInstance("EC").apply {
    initialize(ECGenParameterSpec("secp256r1"))
  }.generateKeyPair()
  private val credentialId = "00112233445566778899aabbccddeeff".hexToBytes()
  private val credentialPublicKeyHash = GattCanonicalCodec.sha256(byteArrayOf(4) + ByteArray(64) { 7 })
  private val authority = FeatureFlagAuthority("rollout.test", "key-1", publicKeySec1(keyPair))

  @Test
  fun signedEnvelopeRejectsTamperReplayExpiryAndCredentialMismatch() {
    val now = 1_000_000L
    val valid = signedEnvelope(enabled = true, revision = 7, issued = now - 100, expires = now + 10_000)
    assertEquals(
      FeatureFlagVerificationStatus.AUTHENTICATED,
      verify(valid, now, minimumRevision = 6).status,
    )
    assertEquals(
      FeatureFlagVerificationStatus.INVALID_SIGNATURE,
      verify(valid.copy(enabled = false), now, minimumRevision = 6).status,
    )
    assertEquals(
      FeatureFlagVerificationStatus.REVISION_REPLAY,
      verify(valid, now, minimumRevision = 7).status,
    )
    assertEquals(
      FeatureFlagVerificationStatus.INVALID_TIME_WINDOW,
      verify(valid, now + 10_000, minimumRevision = 6).status,
    )
    assertEquals(
      FeatureFlagVerificationStatus.CREDENTIAL_MISMATCH,
      RemoteFeatureFlagAuthenticator.verify(
        valid,
        authority,
        ByteArray(16) { 9 },
        credentialPublicKeyHash,
        now,
        6,
      ).status,
    )
    assertEquals(
      FeatureFlagVerificationStatus.CREDENTIAL_KEY_MISSING,
      RemoteFeatureFlagAuthenticator.verify(valid, authority, credentialId, null, now, 6).status,
    )
  }

  @Test
  fun authenticatedOffOnExpiredAndRollbackTransitionsRemainFailClosed() {
    val now = 2_000_000L
    val authenticated = FeatureFlagVerification(FeatureFlagVerificationStatus.AUTHENTICATED)
    val enabledEnvelope = signedEnvelope(true, 1, now - 10, now + 1000)
    val enabledState = state(enabledEnvelope)
    assertTrue(BleGattFeatureFlagPolicy.evaluate(enabledState, authenticated, now).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(enabledState, authenticated, now + 1000).newWorkerEnabled)

    val rollback = signedEnvelope(false, 2, now, now + 1000)
    assertEquals(FeatureFlagVerificationStatus.AUTHENTICATED, verify(rollback, now, 1).status)
    val rollbackDecision = BleGattFeatureFlagPolicy.evaluate(state(rollback), authenticated, now)
    assertFalse(rollbackDecision.newWorkerEnabled)
    assertEquals("legacy", rollbackDecision.owner)
    assertEquals("remote_disabled", rollbackDecision.status)
  }

  private fun verify(
    envelope: RemoteFeatureFlagEnvelope,
    now: Long,
    minimumRevision: Long,
  ) = RemoteFeatureFlagAuthenticator.verify(
    envelope,
    authority,
    credentialId,
    credentialPublicKeyHash,
    now,
    minimumRevision,
  )

  private fun signedEnvelope(
    enabled: Boolean,
    revision: Long,
    issued: Long,
    expires: Long,
  ): RemoteFeatureFlagEnvelope {
    val unsigned = RemoteFeatureFlagEnvelope(
      enabled = enabled,
      issuer = authority.issuer,
      authorityKeyId = authority.keyId,
      revision = revision,
      issuedEpochMs = issued,
      expiresEpochMs = expires,
      credentialId = credentialId,
      credentialPublicKeySha256 = credentialPublicKeyHash,
      signatureDer = byteArrayOf(),
    )
    val signature = Signature.getInstance("SHA256withECDSA").run {
      initSign(keyPair.private)
      update(unsigned.canonicalBytes())
      sign()
    }
    return unsigned.copy(signatureDer = signature)
  }

  private fun state(envelope: RemoteFeatureFlagEnvelope) = AuthenticatedRemoteFlagState(
    enabled = envelope.enabled,
    issuer = envelope.issuer,
    authorityKeyId = envelope.authorityKeyId,
    revision = envelope.revision,
    issuedEpochMs = envelope.issuedEpochMs,
    expiresEpochMs = envelope.expiresEpochMs,
    credentialIdSha256 = GattCanonicalCodec.sha256(envelope.credentialId),
    credentialPublicKeySha256 = envelope.credentialPublicKeySha256,
    signatureDer = envelope.signatureDer,
  )

  private fun publicKeySec1(pair: KeyPair): ByteArray {
    val point = (pair.public as ECPublicKey).w
    return byteArrayOf(4) + fixed32(point.affineX.toByteArray()) + fixed32(point.affineY.toByteArray())
  }

  private fun fixed32(bytes: ByteArray): ByteArray {
    val unsigned = bytes.dropWhile { it == 0.toByte() }.toByteArray()
    return ByteArray(32 - unsigned.size) + unsigned
  }
}
