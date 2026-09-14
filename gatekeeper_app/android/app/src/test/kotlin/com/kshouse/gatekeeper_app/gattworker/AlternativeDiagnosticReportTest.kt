package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AlternativeDiagnosticReportTest {
  private fun report(health: Map<String, Any?>) = NativeDiagnosticReport.build(
    "test", "1", 36, NativeDiagnosticReport.identity(emptyMap<String, Any?>()),
    // Production supplies NativeDiagnostics.prepareCapture().runtime. This pure
    // serializer fixture must supply the same six required runtime fields.
    health, emptyMap(), JSONObject()
      .put("captured_epoch_ms", 100_000L)
      .put("captured_elapsed_ms", 12_000L)
      .put("process_ref", "b".repeat(16))
      .put("pending_uploads", 0)
      .put("dropped_events", 0)
      .put("lifecycle", JSONArray()), 0, 100_000)

  @Test fun missingNewFieldsAreOmittedForNMinusOne() {
    val native = report(emptyMap()).getJSONObject("native")
    assertFalse(native.has("location_services_enabled"))
    assertFalse(native.getJSONObject("scan").has("alternative_stage"))
  }

  @Test fun aggregateProjectionBoundsValuesAndDoesNotExportRadioIdentifiers() {
    val report = report(mapOf("locationServicesEnabled" to false, "scanDiagnostics" to mapOf(
      "alternativeStage" to "NO_MATCHING_PACKET",
      "alternativeResultCount" to Long.MAX_VALUE,
      "alternativeCandidateCount" to -1,
      "alternativeMatchCount" to 0,
      "alternativeErrorCount" to 0,
      "alternativeErrorCode" to 65536,
      "alternativeStartedAtEpochMs" to 1,
      "alternativeFinishedAtEpochMs" to 0,
      "alternativeRestoreStatus" to "RESTORED",
      "deviceAddress" to "AA:BB:CC:DD:EE:FF", "name" to "private-name", "rawData" to "secret-bytes")))
    val native = report.getJSONObject("native")
    val runtime = native.getJSONObject("runtime")
    assertEquals(100_000L, runtime.getLong("captured_epoch_ms"))
    assertEquals(12_000L, runtime.getLong("captured_elapsed_ms"))
    assertEquals("b".repeat(16), runtime.getString("process_ref"))
    assertEquals(0, runtime.getInt("pending_uploads"))
    assertEquals(0, runtime.getInt("dropped_events"))
    assertEquals(0, runtime.getJSONArray("lifecycle").length())
    val scan = native.getJSONObject("scan")
    assertFalse(native.getBoolean("location_services_enabled"))
    assertEquals(1_000_000, scan.getInt("alternative_result_count"))
    assertEquals(0, scan.getInt("alternative_candidate_count"))
    assertTrue(scan.isNull("alternative_finished_at_epoch_ms"))
    assertTrue(scan.isNull("alternative_error_code"))
    assertFalse(report.toString().contains("AA:BB"))
    assertFalse(report.toString().contains("private-name"))
    assertFalse(report.toString().contains("secret-bytes"))
    println("ALTERNATIVE_DIAGNOSTIC_FIXTURE=" + report.toString())
  }

  @Test fun unknownLocationIsJsonNullAndFutureOverflowTimesAreNull() {
    val native = report(mapOf("locationServicesEnabled" to null, "scanDiagnostics" to mapOf(
      "alternativeStartedAtEpochMs" to Long.MAX_VALUE,
      "alternativeFinishedAtEpochMs" to -1))).getJSONObject("native")
    assertTrue(native.isNull("location_services_enabled"))
    assertTrue(native.getJSONObject("scan").isNull("alternative_started_at_epoch_ms"))
    assertTrue(native.getJSONObject("scan").isNull("alternative_finished_at_epoch_ms"))
  }
}
