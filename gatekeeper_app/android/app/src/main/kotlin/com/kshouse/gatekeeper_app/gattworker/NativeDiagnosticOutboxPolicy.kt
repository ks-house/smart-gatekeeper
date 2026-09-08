package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONArray
import org.json.JSONObject

/** Pure ACK/generation rules used by the persistent queue, not by access authorization. */
internal object NativeDiagnosticOutboxPolicy {
  const val MAX_EVENTS = 256
  fun authorityChanged(previous: JSONObject, binding: String, base: String, apiKey: String, deviceId: String): Boolean =
    previous.optString("binding") != binding || previous.optString("base") != base ||
      previous.optString("api_key") != apiKey || previous.optString("device_id") != deviceId
  fun current(enabled: Boolean, currentGeneration: Long, capturedGeneration: Long,
              pending: String?, uploaded: String): Boolean =
    enabled && currentGeneration == capturedGeneration && pending == uploaded

  fun accepted(response: JSONObject, expectedRef: String): Boolean =
    response.opt("accepted") == true && response.opt("bundle_ref") == expectedRef

  fun retainAfterAck(events: JSONArray, sequence: Long): JSONArray = JSONArray().also { remaining ->
    for (index in 0 until events.length()) {
      val event = events.getJSONObject(index)
      if (event.getLong("sequence") > sequence) remaining.put(event)
    }
  }

  fun bound(events: JSONArray): Int {
    var dropped = 0
    while (events.length() > MAX_EVENTS) { events.remove(0); dropped++ }
    return dropped
  }
}
