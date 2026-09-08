package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant
import java.util.Locale

/** Closed projection shared by durable native capture and its JVM tests. No locators or keys. */
internal object NativeDiagnosticReport {
  const val MAX_BYTES = 60 * 1024
  fun opaque(value: String): String = MessageDigest.getInstance("SHA-256")
    .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }.take(16)

  fun code(value: Any?): String? = value?.toString()?.uppercase(Locale.ROOT)
    ?.takeIf { it.matches(Regex("^[A-Z0-9_-]{1,64}$")) }

  fun bridge(value: Any?): Any? = when (value) {
    null, JSONObject.NULL -> null
    is JSONObject -> value.keys().asSequence().associateWith { bridge(value.opt(it)) }
    is JSONArray -> (0 until value.length()).map { bridge(value.opt(it)) }
    else -> value
  }

  private fun obj(values: Map<String, Any?>): JSONObject = JSONObject().also { result ->
    values.forEach { (key, value) -> result.put(key, value ?: JSONObject.NULL) }
  }

  fun identity(value: Map<*, *>): JSONObject = obj(mapOf(
    "enrollment_state" to (value["enrollment_state"]?.toString()
      ?.takeIf { it.matches(Regex("^[a-z_]{1,32}$")) } ?: "unknown"),
    "access_ready" to (value["access_ready"] == true),
    "door_count" to ((value["door_count"] as? Number)?.toInt()?.coerceIn(0, 64) ?: 0),
    "target_synced" to (value["target_synced"] == true),
    "acl_version" to (value["acl_version"] as? Number)?.toLong()?.takeIf { it >= 0 },
  ))

  fun fieldTest(value: Map<*, *>?, since: Long, now: Long): JSONObject? {
    return try {
      val ref = value?.get("ref")?.toString() ?: return null
      require(ref.matches(Regex("^[0-9a-f]{16}$")))
      val created = Instant.parse(value["created_at"]?.toString())
      val expires = Instant.parse(value["expires_at"]?.toString())
      require(expires.epochSecond - created.epochSecond in 60..1800 && created.toEpochMilli() > since)
      obj(mapOf("ref" to ref, "created_at" to created.toString(), "expires_at" to expires.toString(),
        "active" to (now < expires.toEpochMilli())))
    } catch (_: Exception) { null }
  }

  private fun projection(source: Map<*, *>, fields: Map<String, String>): JSONObject =
    JSONObject().also { out -> fields.forEach { (wire, native) ->
      val value = source[native]
      out.put(wire, when {
        value is Number -> value
        value is Boolean -> value
        else -> code(value) ?: JSONObject.NULL
      })
    } }

  fun build(version: String, build: String, sdk: Int, identity: JSONObject,
            health: Map<String, Any?>, recent: Map<String, Any?>, runtime: JSONObject,
            since: Long, now: Long, fieldTest: JSONObject? = null): JSONObject {
    val native = projection(health, mapOf(
      "healthy" to "healthy", "hands_free_ready" to "handsFreeReady",
      "wake_registered" to "wakeRegistered", "wake_registration_requested" to "wakeRegistrationRequested",
      "wake_registration_reconciled" to "wakeRegistrationReconciled",
      "wake_registration_status" to "wakeRegistrationStatus",
      "wake_registration_attempted_at_epoch_ms" to "wakeRegistrationAttemptedAtEpochMs",
      "wake_registration_reconciled_at_epoch_ms" to "wakeRegistrationReconciledAtEpochMs",
      "wake_registration_last_callback_at_epoch_ms" to "wakeRegistrationLastCallbackAtEpochMs",
      "initial_work_expedited" to "initialWorkExpedited",
      "presence_to_dispatch_ms" to "lastPresenceToDispatchMs", "presence_to_armed_ms" to "lastPresenceToArmedMs",
    ))
    native.put("stage", code((health["lastSession"] as? Map<*, *>)?.get("state")) ?: "WAITING")
    native.put("reason", code(health["currentBlockingReasonCode"] ?: health["lastReasonCode"]) ?: JSONObject.NULL)
    val scan = health["scanDiagnostics"] as? Map<*, *>
    val packet = (scan?.get("lastPacketAtEpochMs") as? Number)?.toLong()?.takeIf { it > 0 }
    val scanEvents = JSONArray()
    (scan?.get("lifecycle") as? List<*>)?.filterIsInstance<Map<*, *>>()?.take(32)?.forEach { event ->
      val at = (event["atEpochMs"] as? Number)?.toLong() ?: return@forEach
      if (at > since) scanEvents.put(obj(mapOf("event" to code(event["event"]),
        "at_epoch_ms" to at, "error_code" to event["errorCode"])))
    }
    native.put("scan", obj(mapOf("observation" to when {
      packet == null -> "NOT_OBSERVED"
      packet > now -> "CLOCK_UNCERTAIN"
      now - packet <= 30_000 -> "RECENT_PACKET"
      else -> "NO_RECENT_PACKET"
    }, "last_packet_at_epoch_ms" to packet, "lifecycle" to scanEvents)))
    native.put("runtime", runtime)

    val sessions = JSONArray()
    (recent["sessions"] as? List<*>)?.filterIsInstance<Map<*, *>>()
      ?.filter { ((it["updatedEpochMs"] as? Number)?.toLong() ?: 0) > since }
      ?.take(50)?.forEach { row ->
        val entry = projection(row, sessionFields)
        entry.put("event_ref", row["sessionId"]?.toString()?.let { opaque("support:$it") } ?: JSONObject.NULL)
        entry.put("target_session_id", row["targetSessionId"]?.toString()?.takeIf {
          it.matches(Regex("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"))
        } ?: JSONObject.NULL)
        entry.put("gatt_performance", (row["gattPerformance"] as? Map<*, *>)
          ?.let { projection(it, performanceFields) } ?: JSONObject.NULL)
        sessions.put(entry)
      }
    val wakes = JSONArray()
    (recent["wakeEvents"] as? List<*>)?.filterIsInstance<Map<*, *>>()
      ?.filter { ((it["receivedEpochMs"] as? Number)?.toLong() ?: 0) > since }
      ?.sortedByDescending { (it["receivedEpochMs"] as? Number)?.toLong() ?: 0 }
      ?.take(100)?.forEach { row ->
        val entry = projection(row, wakeFields)
        entry.put("process_ref", row["processRef"]?.toString()?.takeIf { it.matches(Regex("^[0-9a-f]{16}$")) } ?: JSONObject.NULL)
        entry.put("strongest_rssi", (row["strongestRssi"] as? Number)?.toInt()?.takeIf { it in -127..20 } ?: JSONObject.NULL)
        wakes.put(entry)
      }
    val result = obj(mapOf("schema" to "sgk-mobile-support-v2",
      "created_at" to Instant.ofEpochMilli(now).toString(),
      "app" to obj(mapOf("version" to version.take(32), "build" to build.take(32), "android_sdk" to sdk)),
      "identity" to identity, "native" to native, "field_test" to fieldTest?.let {
        NativeDiagnosticReport.fieldTest(bridge(it) as? Map<*, *>, since, now)
      },
      "sessions" to sessions, "wake_events" to wakes))
    while (result.toString().toByteArray(Charsets.UTF_8).size > MAX_BYTES && (wakes.length() > 0 || sessions.length() > 0)) {
      if (wakes.length() > 0) wakes.remove(wakes.length() - 1) else sessions.remove(sessions.length() - 1)
    }
    require(result.toString().toByteArray(Charsets.UTF_8).size <= MAX_BYTES) { "diagnostic projection too large" }
    val ref = MessageDigest.getInstance("SHA-256").digest(result.toString().toByteArray(Charsets.UTF_8))
      .joinToString("") { "%02x".format(it) }.take(32)
    return result.put("bundle_ref", ref)
  }

  private val sessionFields = mapOf("created_epoch_ms" to "createdEpochMs", "updated_epoch_ms" to "updatedEpochMs",
    "attempt" to "attempt", "state" to "state", "reason_code" to "reasonCode", "target_reason_code" to "targetReasonCode",
    "target_reason_name" to "targetReasonName", "transport_reason" to "transportReason", "transport_status" to "transportStatus",
    "retry_after_ms" to "retryAfterMs", "scheduled_retry_delay_ms" to "scheduledRetryDelayMs", "latency_ms" to "latencyMs",
    "dispatch_started_epoch_ms" to "dispatchStartedEpochMs", "presence_to_dispatch_ms" to "presenceToDispatchMs",
    "presence_to_armed_ms" to "presenceToArmedMs", "active_acl_version" to "activeAclVersion")
  private val performanceFields = mapOf("connect_setup_ms" to "connectSetupMs", "negotiation_ms" to "negotiationMs",
    "challenge_ms" to "challengeMs", "signing_ms" to "signingMs", "proof_write_ms" to "proofWriteMs",
    "result_wait_ms" to "resultWaitMs", "negotiated_mtu" to "negotiatedMtu", "mtu_status" to "mtuStatus",
    "high_priority_requested" to "highPriorityRequested")
  private val wakeFields = mapOf("source" to "source", "success" to "success", "received_epoch_ms" to "receivedEpochMs",
    "received_elapsed_ms" to "receivedElapsedMs", "callback_latency_ms" to "callbackLatencyMs",
    "screen_interactive" to "screenInteractive", "result_count" to "resultCount", "callback_type" to "callbackType", "error_code" to "errorCode")
}
