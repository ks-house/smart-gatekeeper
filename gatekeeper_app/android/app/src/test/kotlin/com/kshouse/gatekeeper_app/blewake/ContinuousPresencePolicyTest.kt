package com.kshouse.gatekeeper_app.blewake

import com.kshouse.gatekeeper_app.gattworker.DurableGattSession
import com.kshouse.gatekeeper_app.gattworker.DurableSessionState
import org.junit.Assert.*
import org.junit.Test

class ContinuousPresencePolicyTest {
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
}
