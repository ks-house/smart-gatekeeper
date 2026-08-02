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
  fun featureFlagIsDefaultOffAndRejectsUnvalidatedStaleOrRemoteFalse() {
    val now = 1000L
    assertEquals("default_off", BleGattFeatureFlagPolicy.evaluate(null, now).status)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(null, now).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(ValidatedRemoteFlag(true, false, "r1", 2000), now).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(ValidatedRemoteFlag(true, true, "r1", 1000), now).newWorkerEnabled)
    assertFalse(BleGattFeatureFlagPolicy.evaluate(ValidatedRemoteFlag(false, true, "r1", 2000), now).newWorkerEnabled)
    val enabled = BleGattFeatureFlagPolicy.evaluate(ValidatedRemoteFlag(true, true, "r1", 2000), now)
    assertTrue(enabled.newWorkerEnabled)
    assertEquals("native_gatt", enabled.owner)
  }

  @Test
  fun duplicatesAndWorkerRestartReuseOneDurableSession() {
    val ledger = InMemoryLedger()
    val firstCoordinator = PresenceCoalescer(ledger, ByteArray(32) { 7 })
    val first = firstCoordinator.enqueue("00:11:22:33:44:55", "aa".repeat(16), 1000)
    val duplicate = firstCoordinator.enqueue("00:11:22:33:44:55", "aa".repeat(16), 1200)
    val restartedCoordinator = PresenceCoalescer(ledger, ByteArray(32) { 7 })
    val afterRestart = restartedCoordinator.enqueue("00:11:22:33:44:55", "aa".repeat(16), 1500)

    assertFalse(first.second)
    assertTrue(duplicate.second)
    assertTrue(afterRestart.second)
    assertEquals(first.first.id, duplicate.first.id)
    assertEquals(first.first.id, afterRestart.first.id)
    assertEquals(1, ledger.sessions.size)
  }

  @Test
  fun terminalSessionAllowsASeparateLaterPresence() {
    val ledger = InMemoryLedger()
    val coalescer = PresenceCoalescer(ledger, ByteArray(32) { 8 })
    val first = coalescer.enqueue("00:11:22:33:44:55", "aa".repeat(16), 1000).first
    ledger.update(first.copy(state = DurableSessionState.SUCCEEDED, updatedEpochMs = 1100))
    val next = coalescer.enqueue("00:11:22:33:44:55", "aa".repeat(16), 1200)
    assertFalse(next.second)
    assertTrue(first.id != next.first.id)
  }

  @Test
  fun diagnosticsRedactTransportAndSecretMaterialAndKeepOtaIndependent() {
    val session = sampleSession()
    val map = session.redactedMap()
    val serialized = map.toString()
    assertFalse(serialized.contains(session.deviceAddress))
    assertFalse(serialized.contains(session.presenceFingerprint))
    assertFalse(serialized.contains(session.credentialIdHex))
    assertFalse(serialized.contains("nonce", ignoreCase = true))
    assertFalse(serialized.contains("signature", ignoreCase = true))
    assertFalse(BleGattWorkScheduler.HAS_NETWORK_CONSTRAINT)
    assertEquals("KEEP", BleGattWorkScheduler.UNIQUE_WORK_POLICY)
  }

  private fun sampleSession() = DurableGattSession(
    id = UUID.randomUUID().toString(),
    presenceFingerprint = "secret-fingerprint",
    deviceAddress = "00:11:22:33:44:55",
    credentialIdHex = "aa".repeat(16),
    createdEpochMs = 1,
    updatedEpochMs = 2,
    attempt = 1,
    state = DurableSessionState.FAILED,
    reasonCode = "GATT_TIMEOUT",
    latencyMs = 15000,
  )
}

private class InMemoryLedger : DurableSessionLedger {
  val sessions = mutableListOf<DurableGattSession>()

  override fun findCoalescible(fingerprint: String, nowEpochMs: Long, windowMs: Long): DurableGattSession? =
    sessions.lastOrNull {
      it.presenceFingerprint == fingerprint &&
        it.state in setOf(DurableSessionState.QUEUED, DurableSessionState.RUNNING, DurableSessionState.RETRY_PENDING) &&
        nowEpochMs - it.createdEpochMs in 0..windowMs
    }

  override fun create(
    fingerprint: String,
    deviceAddress: String,
    credentialIdHex: String,
    nowEpochMs: Long,
  ): DurableGattSession = DurableGattSession(
    id = UUID.randomUUID().toString(),
    presenceFingerprint = fingerprint,
    deviceAddress = deviceAddress,
    credentialIdHex = credentialIdHex,
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
