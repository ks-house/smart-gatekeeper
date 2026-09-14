package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.ForegroundDiscoverySession
import com.kshouse.gatekeeper_app.blewake.BleWakeContract
import org.junit.Assert.*
import org.junit.Test

class ForegroundDiscoverySessionTest {
  private class Radio : ForegroundDiscoverySession.Port {
    val calls = mutableListOf<String>()
    var ownerAvailable = true
    var failStart = false
    var failStop = false
    var failPrimary = false
    var failRelease = false
    var failRestore = false
    override fun acquire(): Boolean { calls += "acquire"; return ownerAvailable }
    override fun stopPrimary() { calls += "stopPrimary"; if (failPrimary) throw IllegalStateException() }
    override fun startAlternative() {
      calls += "startAlternative"
      if (failStart) throw IllegalStateException("synthetic")
    }
    override fun stopAlternative() { calls += "stopAlternative"; if (failStop) throw IllegalStateException() }
    override fun release() { calls += "release"; if (failRelease) throw IllegalStateException() }
    override fun restore(): String { calls += "restore"; if (failRestore) throw IllegalStateException(); return "RESTORED" }
  }

  @Test fun matchingPacketReleasesRadioBeforeOrdinaryDispatchAndLateCallbacksAreIgnored() {
    val radio = Radio()
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertTrue(session.sample(true, true))
    session.finish("MATCH_OBSERVED")
    radio.calls += "ordinaryDispatch"
    assertEquals(listOf("acquire", "stopPrimary", "startAlternative", "stopAlternative",
      "release", "restore", "ordinaryDispatch"), radio.calls)
    assertFalse(session.sample(true, true))
    session.error(6)
    session.start(true)
    assertEquals(1, session.matchCount)
    assertEquals(0, session.errorCount)
    assertEquals("MATCH_OBSERVED", session.stage)
  }

  @Test fun everyCancellationRestoresExactlyOnceAndDoesNotRetry() {
    for (reason in listOf("NO_MATCHING_PACKET", "CANCELLED_SCREEN_OFF", "CANCELLED_ACTIVITY_STOP",
        "CANCELLED_GATT", "CANCELLED_UPDATE", "ENVIRONMENT_BLOCKED")) {
      val radio = Radio()
      val session = ForegroundDiscoverySession(radio)
      session.start(true)
      session.finish(reason)
      session.finish(reason)
      session.start(true)
      assertFalse(session.active)
      assertEquals(reason, session.stage)
      assertEquals(1, radio.calls.count { it == "restore" })
      assertEquals(1, radio.calls.count { it == "startAlternative" })
    }
  }

  @Test fun bluetoothOffAndDisableReleaseWithoutStartingAnotherScanner() {
    for (reason in listOf("CANCELLED_DISABLED", "CANCELLED_BLUETOOTH_OFF")) {
      val radio = Radio()
      val session = ForegroundDiscoverySession(radio)
      session.start(true)
      session.finish(reason, restore = false)
      assertEquals("release", radio.calls.last())
      assertEquals("NOT_REQUESTED", session.restoreStatus)
      assertFalse(radio.calls.contains("restore"))
    }
  }

  @Test fun deniedOwnerOrEnvironmentNeverTouchesScanner() {
    val radio = Radio().apply { ownerAvailable = false }
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertEquals("OWNER_BUSY", session.stage)
    assertEquals(listOf("acquire"), radio.calls)
    val blocked = ForegroundDiscoverySession(Radio())
    blocked.start(false)
    assertEquals("ENVIRONMENT_BLOCKED", blocked.stage)
  }

  @Test fun platformStartFailureAndAsyncErrorReleaseAndRestore() {
    val radio = Radio().apply { failStart = true }
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertFalse(session.active)
    assertEquals("SCAN_ERROR", session.stage)
    assertEquals(1, session.errorCount)
    assertEquals(listOf("stopAlternative", "release", "restore"), radio.calls.takeLast(3))
    val async = ForegroundDiscoverySession(Radio())
    async.start(true)
    async.error(6)
    async.error(6)
    assertEquals(6, async.errorCode)
    assertEquals(1, async.errorCount)
  }

  @Test fun unrelatedAndMalformedPacketsOnlyIncrementBoundedAggregates() {
    assertFalse(ForegroundDiscoverySession.candidate(null))
    assertFalse(ForegroundDiscoverySession.candidate(byteArrayOf(2)))
    val partial = byteArrayOf(2, 0x15)
    assertTrue(ForegroundDiscoverySession.candidate(partial))
    assertFalse(BleWakeContract.matchesManufacturerData(partial))
    val oldPayload = BleWakeContract.manufacturerDataPrefix + byteArrayOf(0, 1, 0, 2, -59)
    assertTrue(BleWakeContract.matchesManufacturerData(oldPayload))
    val session = ForegroundDiscoverySession(Radio())
    session.start(true)
    repeat(1_000_010) { session.sample(true, false) }
    assertEquals(1_000_000, session.resultCount)
    assertEquals(1_000_000, session.candidateCount)
    assertEquals(0, session.matchCount)
  }

  @Test fun failedStopRetainsOwnerAndSuppressesResultsUntilExplicitCleanup() {
    val radio = Radio().apply { failStop = true }
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertFalse(session.finish("MATCH_OBSERVED"))
    assertTrue(session.active)
    assertEquals("STOP_FAILED", session.stage)
    assertEquals("RESTORE_PENDING", session.restoreStatus)
    assertFalse(session.sample(true, true))
    assertFalse(radio.calls.contains("release"))
    assertFalse(radio.calls.contains("restore"))
    radio.failStop = false
    assertTrue(session.finish("CANCELLED_GATT"))
    assertFalse(session.active)
  }

  @Test fun actualBluetoothOffCanReleaseAfterStopFailure() {
    val radio = Radio().apply { failStop = true }
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertTrue(session.finish("CANCELLED_BLUETOOTH_OFF", restore = false, radioDisabled = true))
    assertFalse(session.active)
    assertFalse(radio.calls.contains("restore"))
  }

  @Test fun releaseAndRestoreExceptionsNeverEscapeOrAllowCompetingScanners() {
    val release = Radio().apply { failRelease = true }
    val held = ForegroundDiscoverySession(release)
    held.start(true)
    assertFalse(held.finish("NO_MATCHING_PACKET"))
    assertTrue(held.active)
    assertEquals("RELEASE_FAILED", held.stage)
    assertFalse(release.calls.contains("restore"))
    val restore = Radio().apply { failRestore = true }
    val stopped = ForegroundDiscoverySession(restore)
    stopped.start(true)
    assertTrue(stopped.finish("NO_MATCHING_PACKET"))
    assertFalse(stopped.active)
    assertEquals("RESTORE_PENDING", stopped.restoreStatus)
  }

  @Test fun partialPrimaryStopFailureNeverStartsAlternativeAndRestores() {
    val radio = Radio().apply { failPrimary = true }
    val session = ForegroundDiscoverySession(radio)
    session.start(true)
    assertEquals("SCAN_ERROR", session.stage)
    assertFalse(radio.calls.contains("startAlternative"))
    assertEquals("restore", radio.calls.last())
  }

  @Test fun deadlineRejectsLateOrClockReversedCallbacksAndGraceIsShort() {
    assertEquals(3000L, ForegroundDiscoverySession.PRIMARY_GRACE_MS)
    assertEquals(64, ForegroundDiscoverySession.MAX_BATCH)
    assertTrue(ForegroundDiscoverySession.inWindow(13000, 13001))
    assertFalse(ForegroundDiscoverySession.inWindow(13001, 13001))
    assertFalse(ForegroundDiscoverySession.inWindow(13002, 13001))
    assertFalse(ForegroundDiscoverySession.inWindow(1000, 13001))
    val session = ForegroundDiscoverySession(Radio())
    session.start(true)
    session.finish("NO_MATCHING_PACKET")
    assertFalse(session.sample(true, true))
    assertEquals(0, session.matchCount)
  }
}
