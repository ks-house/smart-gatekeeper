package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

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

  fun logDump(context: Context) {
    Log.i(TAG, JSONObject().put("action", "dump").put("data", dump(context)).toString())
  }

  private fun readArray(value: String?): JSONArray = try {
    if (value == null) JSONArray() else JSONArray(value)
  } catch (_: Exception) {
    JSONArray()
  }
}
