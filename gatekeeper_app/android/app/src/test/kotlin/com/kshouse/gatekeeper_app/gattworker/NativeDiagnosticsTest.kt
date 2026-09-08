package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class NativeDiagnosticsTest {
  @Test(timeout = 5000) fun stalledJournalIsBoundedAndNeverExecutesOverflowOnTheCaller() {
    val journal = NativeDiagnosticJournal()
    val started = CountDownLatch(1)
    val release = CountDownLatch(1)
    val overflowRan = AtomicInteger()
    try {
      assertTrue(journal.submit { started.countDown(); release.await() })
      assertTrue(started.await(1, TimeUnit.SECONDS))
      repeat(128) { assertTrue(journal.submit { }) }
      repeat(1000) { assertFalse(journal.submit { overflowRan.incrementAndGet() }) }
      assertEquals(128, journal.pendingCount())
      assertEquals(0, overflowRan.get())
      assertEquals(1007L, journal.totalDropped(7))
      assertEquals(1000L, journal.drainDropped())
      assertEquals(7L, journal.totalDropped(7))
      journal.restoreDropped(1000)
      assertEquals(1007L, journal.totalDropped(7))
      journal.clearPending()
      assertEquals(0, journal.pendingCount())
      assertEquals(7L, journal.totalDropped(7))
      assertTrue(journal.submit { })
    } finally {
      release.countDown()
      journal.close()
    }
  }
  @Test fun endpointAppKeyAndAccountChangesInvalidateTheUploadAuthority() {
    val previous = JSONObject().put("binding", "credential-hash").put("base", "https://example.test/api/v1")
      .put("api_key", "synthetic-app-key").put("device_id", "synthetic-device")
    fun changed(binding: String = "credential-hash", base: String = "https://example.test/api/v1",
                apiKey: String = "synthetic-app-key", deviceId: String = "synthetic-device") =
      NativeDiagnosticOutboxPolicy.authorityChanged(previous, binding, base, apiKey, deviceId)
    assertFalse(changed())
    assertTrue(changed(binding = "new-credential"))
    assertTrue(changed(base = "https://other.test/api/v1"))
    assertTrue(changed(apiKey = "rotated-app-key"))
    assertTrue(changed(deviceId = "another-device"))
  }
  @Test fun ackRequiresBooleanSuccessAndExactReference() {
    val expected = "a".repeat(32)
    assertTrue(NativeDiagnosticOutboxPolicy.accepted(JSONObject().put("accepted", true).put("bundle_ref", expected), expected))
    assertFalse(NativeDiagnosticOutboxPolicy.accepted(JSONObject().put("accepted", "true").put("bundle_ref", expected), expected))
    assertFalse(NativeDiagnosticOutboxPolicy.accepted(JSONObject().put("accepted", true).put("bundle_ref", "b".repeat(32)), expected))
  }

  @Test fun lateAckCannotRetireRevokedClearedOrReplacedReport() {
    assertTrue(NativeDiagnosticOutboxPolicy.current(true, 2, 2, "immutable", "immutable"))
    assertFalse(NativeDiagnosticOutboxPolicy.current(false, 2, 2, "immutable", "immutable"))
    assertFalse(NativeDiagnosticOutboxPolicy.current(true, 3, 2, "immutable", "immutable"))
    assertFalse(NativeDiagnosticOutboxPolicy.current(true, 2, 2, "replacement", "immutable"))
    assertFalse(NativeDiagnosticOutboxPolicy.current(true, 2, 2, null, "immutable"))
  }

  @Test fun captureAckPreservesNewEventsAndOverflowIsCounted() {
    val events = JSONArray()
    for (sequence in 1..260) events.put(JSONObject().put("sequence", sequence))
    assertEquals(4, NativeDiagnosticOutboxPolicy.bound(events))
    assertEquals(256, events.length())
    val after = NativeDiagnosticOutboxPolicy.retainAfterAck(events, 64)
    assertEquals(196, after.length())
    assertEquals(65, after.getJSONObject(0).getInt("sequence"))
    assertEquals(260, after.getJSONObject(after.length() - 1).getInt("sequence"))
  }

  @Test fun endpointCannotDowngradeOrSmuggleCredentialsRedirectQuery() {
    assertEquals("https://example.test:4442/api/v1", NativeDiagnostics.validBase("https://example.test:4442/api/v1/"))
    for (bad in listOf("http://example.test", "https://token@example.test", "https://example.test?token=x",
      "https://example.test/#x", "https://example.test/../other")) {
      assertThrows(IllegalArgumentException::class.java) { NativeDiagnostics.validBase(bad) }
    }
  }

  @Test fun reportUsesClosedProjectionAndClearCutoff() {
    val session = mapOf("sessionId" to "local-private-session", "updatedEpochMs" to 2000L,
      "createdEpochMs" to 1000L, "state" to "SUCCEEDED", "credentialId" to "private-key",
      "targetSessionId" to "fab94c3a-74ef-45d2-8392-e7cffdbb337a")
    val wake = mapOf("processRef" to "a".repeat(16), "source" to "ble_scan", "success" to true,
      "receivedEpochMs" to 2000L, "screenInteractive" to false, "strongestRssi" to 127,
      "deviceAddress" to "AA:BB:CC:DD:EE:FF")
    val report = report(mapOf("sessions" to listOf(session, session + ("updatedEpochMs" to 500L)), "wakeEvents" to listOf(wake)), 1000)
    assertEquals(1, report.getJSONArray("sessions").length())
    assertEquals(16, report.getJSONArray("sessions").getJSONObject(0).getString("event_ref").length)
    assertEquals("fab94c3a-74ef-45d2-8392-e7cffdbb337a", report.getJSONArray("sessions").getJSONObject(0).getString("target_session_id"))
    assertTrue(report.getJSONArray("wake_events").getJSONObject(0).isNull("strongest_rssi"))
    val text = report.toString()
    for (secret in listOf("private", "AA:BB", "resident-name", "unit_number")) assertFalse(text.contains(secret))
    assertEquals(32, report.getString("bundle_ref").length)
    assertEquals("sgk-mobile-support-v2", report.getString("schema"))
    // Synthetic fixture is captured in JUnit XML for cross-language Backend contract validation.
    println("NATIVE_DIAGNOSTIC_FIXTURE=" + report.toString())
  }

  @Test fun reportStaysWithinTransportBudgetAndNeverClaimsFreshPacketFromRegistration() {
    val row = mapOf("sessionId" to "s", "updatedEpochMs" to 2000L, "state" to "FAILED", "reasonCode" to "X".repeat(64))
    val report = report(mapOf("sessions" to List(80) { row }), 0)
    assertTrue(report.toString().toByteArray().size <= NativeDiagnosticReport.MAX_BYTES + 64)
    assertEquals(50, report.getJSONArray("sessions").length())
    assertEquals("NOT_OBSERVED", report.getJSONObject("native").getJSONObject("scan").getString("observation"))
  }

  @Test fun fieldMarkerExpiresWithoutActivityAndClearNeverResurrectsIt() {
    val marker = mapOf("ref" to "c".repeat(16), "created_at" to "2026-09-08T12:00:00Z", "expires_at" to "2026-09-08T12:10:00Z")
    val start = java.time.Instant.parse("2026-09-08T12:00:00Z").toEpochMilli()
    assertTrue(NativeDiagnosticReport.fieldTest(marker, 0, start + 1)!!.getBoolean("active"))
    assertFalse(NativeDiagnosticReport.fieldTest(marker, 0, start + 600_001)!!.getBoolean("active"))
    assertNull(NativeDiagnosticReport.fieldTest(marker, start + 1, start + 2))
    assertNull(NativeDiagnosticReport.fieldTest(marker + ("ref" to "private"), 0, start))
  }

  @Test fun orphanRecoveryNeedsExpiredPreProofStateAndNoUnfinishedPlatformWork() {
    val session = DurableGattSession("id", "fingerprint", 0, 0, 1, DurableSessionState.RUNNING, requiresFreshPresence = true)
    assertTrue(PreProofOrphanPolicy.mayRecover(session, 45_001, false))
    assertFalse(PreProofOrphanPolicy.mayRecover(session, 45_000, false))
    assertFalse(PreProofOrphanPolicy.mayRecover(session, 99_000, true))
    assertFalse(PreProofOrphanPolicy.mayRecover(session, -1, false))
    assertFalse(PreProofOrphanPolicy.mayRecover(session.copy(requiresFreshPresence = false), 99_000, false))
    for (state in listOf(DurableSessionState.PROOF_UNCERTAIN, DurableSessionState.SUCCEEDED, DurableSessionState.FAILED)) {
      assertFalse(PreProofOrphanPolicy.mayRecover(session.copy(state = state), 99_000, false))
    }
  }

  private fun report(recent: Map<String, Any?>, since: Long) = NativeDiagnosticReport.build(
    "test", "1", 36, NativeDiagnosticReport.identity(mapOf("enrollment_state" to "approved", "access_ready" to true,
      "door_count" to 1, "target_synced" to true, "name" to "resident-name", "unit_number" to "401")),
    mapOf("healthy" to true, "handsFreeReady" to true, "wakeRegistered" to true), recent,
    JSONObject().put("captured_epoch_ms", 3000).put("captured_elapsed_ms", 20)
      .put("process_ref", "b".repeat(16)).put("pending_uploads", 0).put("dropped_events", 0).put("lifecycle", JSONArray()),
    since, 3000)
}
