package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject

/** Observation only. Never authorizes dispatch, restarts scanning or changes ownership. */
internal object BleScanDiagnostics {
  private const val PREFS = "ble_scan_diagnostics_v1"
  private const val EVENTS = "lifecycle"
  // N-1 stored callback-arrival time, including stale batches. Retain that key
  // as history, but require one qualifying packet before claiming new RF evidence.
  private const val LAST_PACKET = "last_fresh_packet_epoch_ms_v2"
  enum class Event { REGISTER_REQUESTED, REGISTER_ACCEPTED, REGISTER_FAILED,
    STOP_REQUESTED, INVALIDATED, CALLBACK_ERROR, RECOVERY_ATTEMPT, RECOVERY_EXHAUSTED }

  internal fun isPacketObservation(error: Int, type: Int, matches: Int): Boolean =
    BleScanObservationPolicy.positiveCallback(error, type) && matches > 0

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
    prefs.edit().putString(EVENTS, events.toString()).apply()
  }

  private var counters: BleScanCounters? = null
  private var lastFlushElapsedMs: Long? = null
  private val latest = mutableMapOf<String, Any?>()

  private fun initialize(context: Context) {
    if (counters != null) return
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    counters = BleScanCounters(BleScanCounters.KEYS.associateWith { prefs.getLong(it, 0) })
    for (key in TIME_FIELDS) latest[key] = prefs.getLong(key, 0).takeIf { it > 0 }
    latest["lastPacketAtEpochMs"] = prefs.getLong(LAST_PACKET, 0).takeIf { it > 0 }
    latest["lastErrorCode"] = prefs.getInt("lastErrorCode", -1).takeIf { it >= 0 }
    latest["lastDispatchReason"] = prefs.getString("lastDispatchReason", null)
  }

  /** Coalesced asynchronous persistence: never commit per advertisement. */
  @Synchronized
  fun callback(context: Context, error: Int, type: Int, resultCount: Int,
               matches: List<Pair<Double?, BleScanObservationPolicy.Hint>>, receivedEpochMs: Long) {
    try {
      initialize(context)
      val counts = counters!!
      val now = receivedEpochMs
      val age = counts.callback(error, type, resultCount, matches)
      latest["lastCallbackAtEpochMs"] = now
      if (error != 0) {
        latest["lastErrorAtEpochMs"] = now
        latest["lastErrorCode"] = error.coerceIn(0, 65535)
      }
      BleScanObservationPolicy.packetEpochMs(now, age)?.let { at ->
        val previous = (latest["lastPacketAtEpochMs"] as? Long)?.takeIf { it <= now } ?: 0
        latest["lastPacketAtEpochMs"] = maxOf(at, previous)
        BleScanRecoveryObserver.observe(context, at)
      }
      flush(context)
    } catch (_: RuntimeException) { /* Observation failure must not block local access. */ }
  }

  @Synchronized
  fun dispatch(context: Context, event: BleDispatchDiagnostic, reason: String) {
    try {
      initialize(context)
      counters!!.add(when (event) {
        BleDispatchDiagnostic.ATTEMPT -> "dispatchAttemptCount"
        BleDispatchDiagnostic.ENQUEUED -> "dispatchEnqueuedCount"
        BleDispatchDiagnostic.SKIPPED -> "dispatchSkippedCount"
        BleDispatchDiagnostic.OWNER_WAIT -> "ownerWaitCount"
        BleDispatchDiagnostic.ENQUEUE_FAILED -> "enqueueFailureCount"
      })
      latest["lastDispatchAtEpochMs"] = System.currentTimeMillis()
      // Call sites pass closed codes. Never persist arbitrary exception text.
      latest["lastDispatchReason"] = reason.takeIf { it.matches(Regex("^[A-Z0-9_]{1,64}$")) }
      flush(context)
    } catch (_: RuntimeException) { /* Counters are independent of dispatch. */ }
  }

  private fun flush(context: Context) {
    val elapsed = SystemClock.elapsedRealtime()
    if (lastFlushElapsedMs?.let { elapsed - it in 0 until 2_000 } == true) return
    lastFlushElapsedMs = elapsed
    val editor = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
    counters!!.snapshot().forEach { (key, value) -> editor.putLong(key, value) }
    latest.forEach { (key, value) ->
      val storedKey = if (key == "lastPacketAtEpochMs") LAST_PACKET else key
      when (value) {
        is Long -> editor.putLong(storedKey, value)
        is Int -> editor.putInt(storedKey, value)
        is String -> editor.putString(storedKey, value)
      }
    }
    editor.apply()
  }

  @Synchronized
  fun snapshot(context: Context): Map<String, Any?> {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    initialize(context)
    return latest.toMap() + counters!!.snapshot() + BleScanRecoveryObserver.snapshot(context) + mapOf(
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

  private val TIME_FIELDS = listOf("lastCallbackAtEpochMs", "lastErrorAtEpochMs", "lastDispatchAtEpochMs")
}
