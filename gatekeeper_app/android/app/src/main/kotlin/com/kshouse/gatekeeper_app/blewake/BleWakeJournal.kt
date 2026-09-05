package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

object BleWakeJournal {
  private const val TAG = "BLE_WAKE_POC"
  private const val PREFS = "ble_wake_poc"
  private const val KEY_EVENTS = "events"
  private const val MAX_EVENTS = 400

  @Synchronized
  fun record(context: Context, event: BleWakeEvent) {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val events = readArray(prefs.getString(KEY_EVENTS, null))
    events.put(event.toJson())
    while (events.length() > MAX_EVENTS) {
      events.remove(0)
    }
    if (!prefs.edit().putString(KEY_EVENTS, events.toString()).commit()) {
      Log.e(TAG, "failed to persist native wake event")
    }
    Log.i(TAG, event.toJson().toString())
  }

  @Synchronized
  fun reset(context: Context) {
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .edit()
      .remove(KEY_EVENTS)
      .commit()
    Log.i(TAG, JSONObject().put("action", "reset").toString())
  }

  @Synchronized
  fun dump(context: Context): JSONObject {
    val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val events = readArray(prefs.getString(KEY_EVENTS, null))
    val observations = buildList {
      for (index in 0 until events.length()) {
        val event = events.getJSONObject(index)
        add(
          BleWakeObservation(
            success = event.optBoolean("success", false),
            latencyMs = if (event.isNull("latency_ms")) null else event.optDouble("latency_ms"),
          ),
        )
      }
    }
    val summary = BleWakeMetrics.summarize(observations)
    return JSONObject()
      .put("events", events)
      .put(
        "summary",
        JSONObject()
          .put("attempts", summary.attempts)
          .put("successes", summary.successes)
          .put("success_rate", summary.successRate)
          .put("p50_latency_ms", summary.p50LatencyMs)
          .put("p95_latency_ms", summary.p95LatencyMs)
          .put("max_latency_ms", summary.maxLatencyMs),
      )
  }

  /**
   * Returns only the latest privacy-safe presence fields needed by the
   * foreground dashboard. Raw BLE addresses and credential identifiers are
   * never written to the journal and therefore cannot cross this bridge.
   */
  @Synchronized
  fun latestRedacted(context: Context): Map<String, Any?>? = latestRedactedFromJson(
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .getString(KEY_EVENTS, null),
  )

  @Synchronized
  fun recentRedacted(context: Context, limit: Int = 100): List<Map<String, Any?>> =
    recentRedactedFromJson(
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString(KEY_EVENTS, null),
      limit,
    )

  internal fun latestRedactedFromJson(value: String?): Map<String, Any?>? {
    val events = readArray(value)
    if (events.length() == 0) return null
    val event = events.optJSONObject(events.length() - 1) ?: return null
    return mapOf(
      "source" to event.optString("source", "unknown"),
      "success" to event.optBoolean("success", false),
      "receivedEpochMs" to event.optLong("received_epoch_ms", 0L),
      "callbackLatencyMs" to event.optDoubleOrNull("latency_ms"),
      "strongestRssi" to event.optIntOrNull("strongest_rssi"),
      "screenInteractive" to event.optBoolean("screen_interactive", true),
      "resultCount" to event.optInt("result_count", 0),
      "errorCode" to event.optInt("error_code", 0),
    )
  }

  internal fun recentRedactedFromJson(
    value: String?,
    limit: Int,
  ): List<Map<String, Any?>> {
    if (limit <= 0) return emptyList()
    val events = readArray(value)
    val start = (events.length() - limit.coerceAtMost(100)).coerceAtLeast(0)
    return buildList {
      for (index in start until events.length()) {
        val event = events.optJSONObject(index) ?: continue
        add(
          mapOf(
            "source" to event.optString("source", "unknown"),
            "processRef" to opaqueProcessRef(event.optString("process_id", "")),
            "success" to event.optBoolean("success", false),
            "receivedEpochMs" to event.optLong("received_epoch_ms", 0L),
            "receivedElapsedMs" to event.optLong("received_elapsed_ms", 0L),
            "callbackLatencyMs" to event.optDoubleOrNull("latency_ms"),
            "strongestRssi" to event.optIntOrNull("strongest_rssi"),
            "screenInteractive" to event.optBoolean("screen_interactive", true),
            "resultCount" to event.optInt("result_count", 0),
            "callbackType" to event.optInt("callback_type", 0),
            "errorCode" to event.optInt("error_code", 0),
          ),
        )
      }
    }
  }

  fun logDump(context: Context) {
    Log.i(TAG, JSONObject().put("action", "dump").put("data", dump(context)).toString())
  }

  private fun readArray(value: String?): JSONArray = try {
    if (value == null) JSONArray() else JSONArray(value)
  } catch (_: Exception) {
    JSONArray()
  }

  private fun JSONObject.optIntOrNull(key: String): Int? =
    if (!has(key) || isNull(key)) null else optInt(key)

  private fun JSONObject.optDoubleOrNull(key: String): Double? =
    if (!has(key) || isNull(key)) null else optDouble(key)

  private fun opaqueProcessRef(value: String): String? {
    if (value.isBlank()) return null
    return MessageDigest.getInstance("SHA-256")
      .digest("support-process:$value".toByteArray(Charsets.UTF_8))
      .take(8)
      .joinToString("") { "%02x".format(it.toInt() and 0xff) }
  }
}
