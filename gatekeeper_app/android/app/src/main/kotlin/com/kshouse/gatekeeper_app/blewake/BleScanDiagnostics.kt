package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

/** Observation only. Never authorizes dispatch, restarts scanning or changes ownership. */
internal object BleScanDiagnostics {
  private const val PREFS = "ble_scan_diagnostics_v1"
  private const val EVENTS = "lifecycle"
  private const val LAST_PACKET = "last_packet_epoch_ms"
  enum class Event { REGISTER_REQUESTED, REGISTER_ACCEPTED, REGISTER_FAILED,
    STOP_REQUESTED, INVALIDATED, CALLBACK_ERROR, RECOVERY_ATTEMPT, RECOVERY_EXHAUSTED }

  internal fun isPacketObservation(error: Int, type: Int, matches: Int): Boolean =
    error == 0 && type in listOf(1, 2) && matches > 0

  @Synchronized
  fun record(context: Context, event: Event, errorCode: Int? = null) {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val now = System.currentTimeMillis()
    val events = parse(prefs.getString(EVENTS, null))
    val last = events.optJSONObject(events.length() - 1)
    // Repeated health reads must not evict the incident with identical errors.
    if (last?.optString("event") == event.name &&
      last.optInt("error_code", -1) == (errorCode ?: -1) &&
      now - last.optLong("at_epoch_ms") in 0 until 10_000) return
    events.put(JSONObject().put("event", event.name).put("at_epoch_ms", now)
      .put("error_code", errorCode?.coerceIn(0, 65535) ?: JSONObject.NULL))
    while (events.length() > 32) events.remove(0)
    prefs.edit().putString(EVENTS, events.toString()).commit()
  }

  private var lastPacketWriteElapsedMs: Long? = null

  @Synchronized
  fun packet(context: Context) {
    val now = SystemClock.elapsedRealtime()
    if (lastPacketWriteElapsedMs?.let { now - it in 0 until 2_000 } == true) return
    lastPacketWriteElapsedMs = now
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
      .putLong(LAST_PACKET, System.currentTimeMillis()).apply()
  }

  @Synchronized
  fun snapshot(context: Context): Map<String, Any?> {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    return mapOf(
      "lastPacketAtEpochMs" to prefs.getLong(LAST_PACKET, 0L).takeIf { it > 0 },
      "lifecycle" to project(prefs.getString(EVENTS, null)),
    )
  }

  internal fun project(value: String?): List<Map<String, Any?>> {
    val events = parse(value)
    return (0 until events.length()).mapNotNull { index ->
      val event = events.optJSONObject(index) ?: return@mapNotNull null
      val code = event.optString("event")
      if (Event.values().none { it.name == code }) return@mapNotNull null
      val at = event.optLong("at_epoch_ms", -1)
      if (at < 0) return@mapNotNull null
      mapOf("event" to code, "atEpochMs" to at,
        "errorCode" to if (event.isNull("error_code")) null
        else event.optInt("error_code").takeIf { it in 0..65535 })
    }.takeLast(32).reversed()
  }

  private fun parse(value: String?): JSONArray = try {
    if (value == null) JSONArray() else JSONArray(value)
  } catch (_: Exception) { JSONArray() }
}
