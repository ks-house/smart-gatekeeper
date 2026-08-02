package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkerPolicyTest {
  @Test
  fun featureFlagIsDefaultOffAndRequiresAuthenticatedUnexpiredRemoteState() {
    val now = 1000L
    val authenticated = FeatureFlagVerification(FeatureFlagVerificationStatus.AUTHENTICATED)
    val enabledState = flagState(enabled = true, expiresEpochMs = 2000)
    assertEquals("default_off", BleGattFeatureFlagPolicy.evaluate(null, null, now).status)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(enabledState, null, now).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(enabledState, authenticated, 2000).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(flagState(false, 2000), authenticated, now).newWorkerEnabled)
    val enabled = BleGattFeatureFlagPolicy.evaluate(enabledState, authenticated, now)
    assertTrue(enabled.newWorkerEnabled)
    assertEquals("native_gatt", enabled.owner)
  }

  @Test
  fun duplicatesAndWorkerRestartReuseOneDurableSession() {
    val ledger = InMemoryLedger()
    val firstCoordinator = PresenceCoalescer(ledger, DeterministicPresenceFingerprinter(ByteArray(32) { 7 }))
    val first = firstCoordinator.enqueue("00:11:22:33:44:55", "wake-1", 1000)
    val duplicate = firstCoordinator.enqueue("00:11:22:33:44:55", "wake-1", 1200)
    val restartedCoordinator = PresenceCoalescer(
      ledger,
      DeterministicPresenceFingerprinter(ByteArray(32) { 7 }),
    )
    val afterRestart = restartedCoordinator.enqueue("00:11:22:33:44:55", "wake-1", 1500)

    assertFalse(first.second)
    assertTrue(duplicate.second)
    assertTrue(afterRestart.second)
    assertEquals(first.first.id, duplicate.first.id)
    assertEquals(first.first.id, afterRestart.first.id)
    assertEquals(1, ledger.sessions.size)
  }

  @Test
  fun terminalDuplicateWakeCoalescesButDistinctWakeCreatesNewSession() {
    val ledger = InMemoryLedger()
    val coalescer = PresenceCoalescer(ledger, DeterministicPresenceFingerprinter(ByteArray(32) { 8 }))
    val first = coalescer.enqueue("00:11:22:33:44:55", "wake-1", 1000).first
    ledger.update(first.copy(state = DurableSessionState.SUCCEEDED, updatedEpochMs = 1100))
    val terminalDuplicate = coalescer.enqueue("00:11:22:33:44:55", "wake-1", 1200)
    val next = coalescer.enqueue("00:11:22:33:44:55", "wake-2", 1200)
    assertTrue(terminalDuplicate.second)
    assertEquals(first.id, terminalDuplicate.first.id)
    assertFalse(next.second)
    assertTrue(first.id != next.first.id)
  }

  @Test
  fun diagnosticsRedactTransportAndSecretMaterialAndKeepOtaIndependent() {
    val session = sampleSession()
    val map = session.redactedMap()
    val serialized = map.toString()
    assertFalse(serialized.contains(session.presenceFingerprint))
    assertFalse(serialized.contains("nonce", ignoreCase = true))
    assertFalse(serialized.contains("signature", ignoreCase = true))
    assertFalse(BleGattWorkScheduler.HAS_NETWORK_CONSTRAINT)
    assertEquals("KEEP", BleGattWorkScheduler.UNIQUE_WORK_POLICY)
    assertEquals("APPEND_OR_REPLACE", BleGattWorkScheduler.RETRY_WORK_POLICY)
  }

  @Test
  fun legacyLedgerMigrationDropsRawDeviceAndCredentialLocators() {
    val raw = """[{"id":"00000000-0000-0000-0000-000000000001","presence_fingerprint":"fingerprint","device_address":"00:11:22:33:44:55","credential_id_hex":"${"aa".repeat(16)}","created_epoch_ms":1,"updated_epoch_ms":2,"attempt":1,"state":"RUNNING"}]"""
    val decoded = SessionLedgerCodec.decode(raw)
    val migrated = SessionLedgerCodec.encode(decoded.sessions)
    assertTrue(decoded.containedLegacySensitiveFields)
    assertFalse(migrated.contains("00:11:22:33:44:55"))
    assertFalse(migrated.contains("credential_id_hex"))
    assertFalse(migrated.contains("device_address"))
    assertTrue(migrated.contains("fingerprint"))
  }

  @Test
  fun retryDelaySurvivesWorkerProcessRestartAndClockRollback() {
    val retry = sampleSession().copy(
      state = DurableSessionState.RETRY_PENDING,
      updatedEpochMs = 1_000,
      scheduledRetryDelayMs = 9_000,
    )
    assertEquals(7_000, RetryPolicy.remainingDelayMs(retry, 3_000))
    assertEquals(1, RetryPolicy.remainingDelayMs(retry, 9_999))
    assertEquals(0, RetryPolicy.remainingDelayMs(retry, 10_000))
    assertEquals(9_000, RetryPolicy.remainingDelayMs(retry, 500))
    assertEquals(0, RetryPolicy.remainingDelayMs(retry.copy(state = DurableSessionState.QUEUED), 3_000))
  }

  private fun sampleSession() = DurableGattSession(
    id = UUID.randomUUID().toString(),
    presenceFingerprint = "secret-fingerprint",
    createdEpochMs = 1,
    updatedEpochMs = 2,
    attempt = 1,
    state = DurableSessionState.FAILED,
    reasonCode = "GATT_TIMEOUT",
    latencyMs = 15000,
  )

  private fun flagState(enabled: Boolean, expiresEpochMs: Long) = AuthenticatedRemoteFlagState(
    enabled = enabled,
    issuer = "test",
    authorityKeyId = "key-1",
    revision = 1,
    issuedEpochMs = 1,
    expiresEpochMs = expiresEpochMs,
    credentialIdSha256 = ByteArray(32),
    credentialPublicKeySha256 = ByteArray(32),
    signatureDer = byteArrayOf(1),
  )
}

private class InMemoryLedger : DurableSessionLedger {
  val sessions = mutableListOf<DurableGattSession>()

  override fun findByPresenceFingerprint(fingerprint: String): DurableGattSession? =
    sessions.lastOrNull { it.presenceFingerprint == fingerprint }

  override fun create(
    fingerprint: String,
    nowEpochMs: Long,
  ): DurableGattSession = DurableGattSession(
    id = UUID.randomUUID().toString(),
    presenceFingerprint = fingerprint,
    createdEpochMs = nowEpochMs,
    updatedEpochMs = nowEpochMs,
    attempt = 0,
    state = DurableSessionState.QUEUED,
  ).also(sessions::add)

  override fun get(id: String): DurableGattSession? = sessions.firstOrNull { it.id == id }
  override fun update(session: DurableGattSession) {
    sessions.removeAll { it.id == session.id }
    sessions.add(session)
  }
  override fun last(): DurableGattSession? = sessions.maxByOrNull { it.updatedEpochMs }
}
