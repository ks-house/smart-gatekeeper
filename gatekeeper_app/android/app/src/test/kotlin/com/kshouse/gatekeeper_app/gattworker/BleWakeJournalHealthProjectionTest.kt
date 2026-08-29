package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.BleWakeJournal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BleWakeJournalHealthProjectionTest {
  @Test
  fun latestRedactedReturnsOnlyDashboardSafeFields() {
    val result = BleWakeJournal.latestRedactedFromJson(
      """[
        {"source":"ble_scan","success":true,"received_epoch_ms":1000,
         "latency_ms":12.5,"strongest_rssi":-54,"screen_interactive":false,
         "result_count":2,"error_code":0,"process_id":"private-process",
         "credential_id":"private-credential","device_address":"AA:BB:CC:DD:EE:FF"}
      ]""",
    )

    requireNotNull(result)
    assertEquals("ble_scan", result["source"])
    assertTrue(result["success"] as Boolean)
    assertEquals(1000L, result["receivedEpochMs"])
    assertEquals(-54, result["strongestRssi"])
    assertFalse(result["screenInteractive"] as Boolean)
    assertEquals(
      setOf(
        "source",
        "success",
        "receivedEpochMs",
        "callbackLatencyMs",
        "strongestRssi",
        "screenInteractive",
        "resultCount",
        "errorCode",
      ),
      result.keys,
    )
  }

  @Test
  fun latestRedactedHandlesEmptyOrNullableMetrics() {
    assertNull(BleWakeJournal.latestRedactedFromJson(null))
    val result = BleWakeJournal.latestRedactedFromJson(
      """[{"source":"ble_scan","success":false,"received_epoch_ms":2000,
        "latency_ms":null,"strongest_rssi":null,"screen_interactive":true,
        "result_count":0,"error_code":3}]""",
    )
    requireNotNull(result)
    assertNull(result["callbackLatencyMs"])
    assertNull(result["strongestRssi"])
    assertEquals(3, result["errorCode"])
  }
}
