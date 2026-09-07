package com.kshouse.gatekeeper_app.blewake

import org.junit.Assert.*
import org.junit.Test

class BleScanDiagnosticsTest {
  @Test fun lossErrorsAndEmptyResultsAreNotPacketEvidence() {
    assertTrue(BleScanDiagnostics.isPacketObservation(0, 1, 1))
    assertTrue(BleScanDiagnostics.isPacketObservation(0, 2, 1))
    assertFalse(BleScanDiagnostics.isPacketObservation(0, 4, 1))
    assertFalse(BleScanDiagnostics.isPacketObservation(3, 1, 1))
    assertFalse(BleScanDiagnostics.isPacketObservation(0, 1, 0))
  }
  @Test fun projectionIsBoundedNewestFirstAndClosed() {
    val rows = (1..40).joinToString(",") {
      """{"event":"REGISTER_ACCEPTED","at_epoch_ms":$it,"error_code":null,"mac":"private"}"""
    }
    val result = BleScanDiagnostics.project("[$rows]")
    assertEquals(32, result.size)
    assertEquals(40L, result.first()["atEpochMs"])
    assertEquals(9L, result.last()["atEpochMs"])
    assertEquals(setOf("event", "atEpochMs", "errorCode"), result.first().keys)
    assertNull(result.first()["errorCode"])
  }

  @Test fun malformedOrUnknownEventsAreNotExported() {
    assertTrue(BleScanDiagnostics.project("bad json").isEmpty())
    assertTrue(BleScanDiagnostics.project(null).isEmpty())
    assertTrue(BleScanDiagnostics.project("""[{"event":"private text","at_epoch_ms":1}]""").isEmpty())
    assertTrue(BleScanDiagnostics.project("""[{"event":"REGISTER_ACCEPTED","at_epoch_ms":-1}]""").isEmpty())
  }
}
