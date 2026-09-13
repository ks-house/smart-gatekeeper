package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.*
import org.junit.Assert.*
import org.junit.Test

/** Finite fake-time RF replay; it deliberately makes no claim about Android/OEM scheduling. */
class BleFieldRecoveryReplayTest {
  @Test fun delayedExitFromPriorVisitDoesNotEraseFreshAllMatchesReentry() {
    ContinuousPresenceTracker.exit(null)
    ContinuousPresenceTracker.observe("fixture", 100)
    ContinuousPresenceTracker.observe("fixture", 1_000_000)
    assertFalse(ContinuousPresenceTracker.exit("fixture", 100))
    assertTrue(ContinuousPresenceTracker.fresh("fixture", 1_000_001))
    assertTrue(ContinuousPresenceTracker.exit("fixture", 1_000_000))
    assertFalse(ContinuousPresenceTracker.fresh("fixture", 1_000_001))
  }

  @Test fun repeatedRegistrationsAfterLongSilenceDoNotBecomePacketEvidence() {
    val lastPacket = 1_000L
    val accepted = 60 * 60_000L
    assertFalse(BleScanRecoveryPolicy.freshPacket(accepted, lastPacket))
    assertEquals("AWAITING_PACKET", BleScanRecoveryPolicy.confirmation(accepted, accepted, lastPacket))
    assertEquals("NO_MATCHING_PACKET", BleScanRecoveryPolicy.confirmation(accepted + 30_000, accepted, lastPacket))
    assertFalse(BleScanRecoveryPolicy.mayStart(accepted + 59_999, accepted))
    assertTrue(BleScanRecoveryPolicy.mayStart(accepted + 60_000, accepted))
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(accepted + 30_000, accepted, lastPacket))
  }

  @Test fun freshReentryConfirmsRfOnlyWithinTheBoundedWindow() {
    val started = 1_000_000L
    assertEquals("MATCHING_PACKET_RECEIVED",
      BleScanRecoveryPolicy.confirmation(started + 20_000, started, started + 19_900))
    assertEquals("NO_MATCHING_PACKET",
      BleScanRecoveryPolicy.confirmation(started + 60_000, started, started + 50_000))
    assertEquals("CLOCK_UNCERTAIN", BleScanRecoveryPolicy.confirmation(started - 1, started, null))
  }

  @Test fun screenOffActivityDeathAndCallbackTypeChangesKeepFreshnessAndProofRules() {
    ContinuousPresenceTracker.exit(null)
    for (interactive in listOf(false, true, false)) {
      val first = event(2, interactive)
      val all = event(1, interactive)
      assertEquals(BleWakeDispatchAction.PRESENCE, BleWakeDispatchPolicy.classify(first))
      assertEquals(BleWakeDispatchAction.PRESENCE, BleWakeDispatchPolicy.classify(all))
      ContinuousPresenceTracker.observe("fixture", first.receivedElapsedMs)
      assertTrue(ContinuousPresenceTracker.fresh("fixture", first.receivedElapsedMs + 5_000))
      assertFalse(ContinuousPresenceTracker.fresh("fixture", first.receivedElapsedMs + 5_001))
      assertEquals(BleWakeDispatchAction.EXIT, BleWakeDispatchPolicy.classify(event(4, interactive)))
      ContinuousPresenceTracker.exit("fixture")
      assertFalse(ContinuousPresenceTracker.fresh("fixture", 100_000))
    }
    // Process recreation clears volatile RF even when a locator/session survives.
    ContinuousPresenceTracker.exit(null)
    assertFalse(ContinuousPresenceTracker.fresh("cached-address", 100_000))
    val uncertain = DurableGattSession("s", "f", 1, 1, 1, DurableSessionState.PROOF_UNCERTAIN)
    assertEquals("PROOF_OUTCOME_UNCERTAIN", ContinuousPresencePolicy.missingHintBlockingReason(uncertain, Long.MAX_VALUE))
    assertEquals("PROOF_OUTCOME_UNCERTAIN", ContinuousPresencePolicy.blockingReason(uncertain, Long.MAX_VALUE))
  }

  private fun event(type: Int, interactive: Boolean) = BleWakeEvent("ble_scan", "field", null, true,
    100_000, 100_000, 100_000_000_000, 0.0, type, 0, 1, -60, "fixture", interactive,
    deviceAddress = "fixture")
}
