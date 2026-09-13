package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeDiagnosticBaselineTest {
  @Test fun optionalOlderServerAckDoesNotInventTargetReadiness() {
    assertNull(NativeDiagnosticBaseline.parse(null, 100_000))
    val good = JSONObject().put("fresh", true).put("observed_epoch_ms", 99_000L)
      .put("state", "IDLE").put("relay_commanded_on", false)
    assertTrue(NativeDiagnosticBaseline.parse(good, 100_000)!!.fresh)
    for ((key, value) in listOf("fresh" to "true", "observed_epoch_ms" to 100_001L,
      "observed_epoch_ms" to 99_000.5, "relay_commanded_on" to "false", "state" to "UNRECOGNIZED")) {
      assertFalse(NativeDiagnosticBaseline.parse(JSONObject(good.toString()).put(key, value), 100_000)!!.fresh)
    }
    assertFalse(NativeDiagnosticBaseline.parse(good, 300_000)!!.fresh)
  }
}
