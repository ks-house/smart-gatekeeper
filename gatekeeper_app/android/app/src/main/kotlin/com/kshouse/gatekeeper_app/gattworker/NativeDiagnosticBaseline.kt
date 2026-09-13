package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONObject

/** Optional server observation, never an access authorization or physical result. */
internal data class NativeDiagnosticBaseline(val fresh: Boolean, val observedEpochMs: Long?,
                                             val state: String?, val relayCommandedOn: Boolean?) {
  fun json(): JSONObject = JSONObject().put("fresh", fresh)
    .put("observed_epoch_ms", observedEpochMs ?: JSONObject.NULL)
    .put("state", state ?: JSONObject.NULL).put("relay_commanded_on", relayCommandedOn ?: JSONObject.NULL)
  companion object {
    fun parse(value: JSONObject?, now: Long): NativeDiagnosticBaseline? {
      if (value == null) return null
      val rawTime = value.opt("observed_epoch_ms")
      val observed = (rawTime as? Long ?: (rawTime as? Int)?.toLong())?.takeIf { it > 0 }
      val state = (value.opt("state") as? String)?.takeIf {
        it in setOf("IDLE", "AUTH_PENDING", "ARMED", "RELAY_HOLD", "COOLDOWN", "FAULT", "BOOTING")
      }
      val relay = value.opt("relay_commanded_on") as? Boolean
      val fresh = value.opt("fresh") == true && observed != null && now - observed in 0..120_000 && state != null && relay != null
      return NativeDiagnosticBaseline(fresh, observed, state, relay)
    }
  }
}
