package com.kshouse.gatekeeper_app.blewake

import org.json.JSONObject

data class BleWakeEvent(
  val source: String,
  val scenario: String,
  val iteration: Int?,
  val success: Boolean,
  val receivedEpochMs: Long,
  val receivedElapsedMs: Long,
  val scanTimestampNanos: Long?,
  val latencyMs: Double?,
  val callbackType: Int,
  val errorCode: Int,
  val resultCount: Int,
  val strongestRssi: Int?,
  val processId: String,
  val screenInteractive: Boolean,
  /** Internal transport locator. Intentionally omitted from journal/log JSON. */
  val deviceAddress: String? = null,
) {
  fun toJson(): JSONObject = JSONObject()
    .put("source", source)
    .put("scenario", scenario)
    .put("iteration", iteration)
    .put("success", success)
    .put("received_epoch_ms", receivedEpochMs)
    .put("received_elapsed_ms", receivedElapsedMs)
    .put("scan_timestamp_nanos", scanTimestampNanos)
    .put("latency_ms", latencyMs)
    .put("callback_type", callbackType)
    .put("error_code", errorCode)
    .put("result_count", resultCount)
    .put("strongest_rssi", strongestRssi)
    .put("process_id", processId)
    .put("screen_interactive", screenInteractive)
}
