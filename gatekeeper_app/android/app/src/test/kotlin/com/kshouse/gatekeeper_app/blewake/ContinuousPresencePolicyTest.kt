package com.kshouse.gatekeeper_app.blewake

import com.kshouse.gatekeeper_app.gattworker.DurableGattSession
import com.kshouse.gatekeeper_app.gattworker.DurableSessionState
import com.kshouse.gatekeeper_app.gattworker.SessionLedgerCodec
import org.junit.Assert.*
import org.junit.Test

class ContinuousPresencePolicyTest {
  @Test fun transientFailureRecoversWithFreshReadyAfterFiveSecondsButHonorsTargetDelay() {
    val failure = session(DurableSessionState.FAILED).copy(reasonCode = "GATT_DISCONNECTED")
    assertFalse(ContinuousPresencePolicy.maySchedule(failure, 6_999))
    assertTrue(ContinuousPresencePolicy.maySchedule(failure, 7_000))
    assertFalse(ContinuousPresencePolicy.maySchedule(failure.copy(
      reasonCode = "TARGET_BUSY", retryAfterMs = 20_000), 21_999))
    assertTrue(ContinuousPresencePolicy.maySchedule(failure.copy(
      reasonCode = "TARGET_BUSY", retryAfterMs = 20_000), 22_000))
    assertFalse(ContinuousPresencePolicy.maySchedule(failure.copy(
      reasonCode = "SIGNATURE_INVALID"), 7_000))
    assertFalse(ContinuousPresencePolicy.maySchedule(failure.copy(
      failureRecovery = true), 61_999))
    assertTrue(ContinuousPresencePolicy.maySchedule(failure.copy(
      failureRecovery = true), 62_000))
    assertTrue(ContinuousPresencePolicy.maySchedule(failure.copy(
      requiresFreshPresence = true), 7_000))
  }

  @Test fun recoveryBackoffSurvivesLedgerRoundTripAndLegacyRowsRemainReadable() {
    val recovering = session(DurableSessionState.FAILED).copy(
      reasonCode = "GATT_DISCONNECTED", failureRecovery = true, requiresFreshPresence = true)
    val encoded = SessionLedgerCodec.encode(listOf(recovering))
    val restored = SessionLedgerCodec.decode(encoded).sessions.single()
    assertTrue(restored.failureRecovery)
    assertFalse(ContinuousPresencePolicy.maySchedule(restored, 7_000))
    val legacy = org.json.JSONArray(encoded).getJSONObject(0).apply { remove("failure_recovery") }
    assertFalse(SessionLedgerCodec.decode(org.json.JSONArray().put(legacy).toString())
      .sessions.single().failureRecovery)
  }

  @Test fun skipJournalBoundsWritesPerClosedReason() {
    val policy = ContinuousSkipJournalPolicy()
    assertTrue(policy.shouldRecord("ble_scan_no_ready_hint", 1))
    assertFalse(policy.shouldRecord("ble_scan_no_ready_hint", 10_000))
    assertTrue(policy.shouldRecord("ble_scan_no_ready_hint", 10_001))
    assertTrue(policy.shouldRecord("ble_scan_stale", 2))
    assertFalse(policy.shouldRecord("raw-secret", 3))
  }
  private fun session(state: DurableSessionState) = DurableGattSession(
    "s", "f", 1_000, 2_000, 1, state,
  )
  @Test fun validatesHintAndUnsignedEpoch() {
    assertNull(PresenceReadyHint.parse(null))
    assertNull(PresenceReadyHint.parse(byteArrayOf(2, 1, 0, 0, 0, 0)))
    assertNull(PresenceReadyHint.parse(byteArrayOf(1, 2, 0, 0, 0, 0)))
    assertEquals(PresenceReadyHint(true, 0xffffffffL),
      PresenceReadyHint.parse(byteArrayOf(1, 1, -1, -1, -1, -1)))
    assertEquals(PresenceReadyHint(false, 42),
      PresenceReadyHint.parse(byteArrayOf(1, 0, 42, 0, 0, 0)))
  }
  @Test fun boundsRepeatsAndNeverResolvesUncertainProofFromAnAdvertisement() {
    assertTrue(ContinuousPresencePolicy.maySchedule(null, 3_000))
    assertFalse(ContinuousPresencePolicy.maySchedule(session(DurableSessionState.SUCCEEDED), 3_999))
    assertTrue(ContinuousPresencePolicy.maySchedule(session(DurableSessionState.SUCCEEDED), 4_000))
    for (state in listOf(DurableSessionState.RUNNING, DurableSessionState.QUEUED,
      DurableSessionState.RETRY_PENDING, DurableSessionState.PROOF_UNCERTAIN)) {
      assertFalse(ContinuousPresencePolicy.maySchedule(session(state), 1_000_000))
    }
    assertFalse(ContinuousPresencePolicy.maySchedule(session(DurableSessionState.FAILED), 61_999))
    assertTrue(ContinuousPresencePolicy.maySchedule(session(DurableSessionState.FAILED), 62_000))
  }
  @Test fun requiresFreshPerTargetEvidenceAndClearsOnExit() {
    ContinuousPresenceTracker.exit(null)
    assertFalse(ContinuousPresenceTracker.fresh("fixture", 100))
    ContinuousPresenceTracker.observe("fixture", 100)
    assertTrue(ContinuousPresenceTracker.fresh("fixture", 5_100))
    assertFalse(ContinuousPresenceTracker.fresh("fixture", 5_101))
    assertFalse(ContinuousPresenceTracker.fresh("other", 100))
    assertFalse(ContinuousPresenceTracker.fresh("fixture", 99))
    ContinuousPresenceTracker.exit("fixture")
    assertFalse(ContinuousPresenceTracker.fresh("fixture", 100))
  }
  @Test fun knownFailureCanRetrySameEpochWithoutReplayingSuccess() {
    assertEquals("ready-v1-42", ContinuousPresencePolicy.eventId(42, null))
    assertEquals("ready-v1-42", ContinuousPresencePolicy.eventId(42,
      session(DurableSessionState.SUCCEEDED)))
    assertEquals("ready-v1-42-after-s", ContinuousPresencePolicy.eventId(42,
      session(DurableSessionState.FAILED)))
    assertFalse(ContinuousPresencePolicy.maySchedule(
      session(DurableSessionState.PROOF_UNCERTAIN), Long.MAX_VALUE))
  }
}
