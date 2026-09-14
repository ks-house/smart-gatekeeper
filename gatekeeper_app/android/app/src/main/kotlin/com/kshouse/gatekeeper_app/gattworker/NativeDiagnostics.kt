package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.os.Build
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection

/** Diagnostic data only: no path here may dispatch BLE, open a door or change credentials. */
internal object NativeDiagnostics {
  enum class Event { PROCESS_STARTED, HEARTBEAT, CAPTURE_REQUESTED, DISPATCH_SKIPPED,
    WORK_ENQUEUED, ENQUEUE_FAILED, WORKER_STARTED, WORKER_FINISHED, WORKER_STOPPED,
    SCAN_REGISTRATION, SCAN_EXIT, ORPHAN_RECOVERED, MANUAL_OPEN_CONTEXT, INCIDENT_CAPTURE }
  private const val PREFS = "native_diagnostic_outbox_v1"
  private const val CONFIG = "diagnostic-upload-config-v1"
  private val processRef = NativeDiagnosticReport.opaque("diagnostic-process:${UUID.randomUUID()}")
  private var connection: HttpsURLConnection? = null
  private var connectionOwner: String? = null
  private val journal = NativeDiagnosticJournal()
  private val heartbeatExecutor = Executors.newSingleThreadScheduledExecutor { runnable ->
    Thread(runnable, "sgk-diagnostic-heartbeat").apply { isDaemon = true }
  }
  private var heartbeat: ScheduledFuture<*>? = null
  private var lastHeartbeatElapsed = 0L
  private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  internal fun validBase(value: String): String {
    require(value.length <= 1024) { "invalid backend origin" }
    val uri = URI(value.trim().trimEnd('/'))
    require(uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
      uri.rawQuery == null && uri.rawFragment == null && !uri.path.contains("..")) { "invalid backend origin" }
    return uri.toASCIIString()
  }

  @Synchronized fun enabled(context: Context): Boolean = prefs(context).getBoolean("enabled", false)

  @Synchronized fun configure(context: Context, enabled: Boolean, base: String?, apiKey: String?,
                              deviceId: String?, identity: Map<*, *>, since: Long,
                              fieldTest: Map<*, *>? = null): Map<String, Any?> {
    if (!enabled) {
      disable(context)
      return status(context)
    }
    // PendingIntent BLE wake and java.time reports share the Android 8 floor.
    // Keep older Android on the existing Dart diagnostic path without changing OTA.
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return mapOf("supported" to false, "enabled" to false)
    val endpoint = validBase(requireNotNull(base))
    require(!apiKey.isNullOrBlank() && apiKey.length <= 2048 && apiKey.none { it == '\r' || it == '\n' }) { "app auth unavailable" }
    require(!deviceId.isNullOrBlank() && deviceId.length <= 128) { "device identity unavailable" }
    val credential = BleCredentialConfigStore(context).credentialId() ?: error("credential unavailable")
    try {
      val binding = NativeDiagnosticReport.opaque("upload-binding:${credential.toHex()}")
      val old = readConfig(context)
      if (old != null && NativeDiagnosticOutboxPolicy.authorityChanged(old, binding, endpoint, apiKey, deviceId)) {
        // Even with the same key, a changed endpoint/account/app authority must
        // never receive a report captured for the previous configuration.
        clear(context, System.currentTimeMillis())
        check(prefs(context).edit().remove("last_success").remove("last_code").commit())
      }
      val config = JSONObject().put("base", endpoint).put("api_key", apiKey).put("device_id", deviceId)
        .put("binding", binding).put("identity", NativeDiagnosticReport.identity(identity))
        .put("field_test", NativeDiagnosticReport.fieldTest(fieldTest, since, System.currentTimeMillis()) ?: JSONObject.NULL)
      val changed = old?.toString() != config.toString() || !NativeDiagnostics.enabled(context)
      if (changed) {
        val bytes = config.toString().toByteArray(Charsets.UTF_8)
        try { require(bytes.size <= 4000); NoBackupAeadStore(context).write(CONFIG, bytes) } finally { bytes.fill(0) }
        prefs(context).edit().remove("auth_required").apply()
      }
      val p = prefs(context)
      if (since > p.getLong("since", 0)) clear(context, since)
      check(p.edit().putBoolean("enabled", true).commit())
      NativeDiagnosticScheduler.ensurePeriodic(context)
      startHeartbeat(context)
      if (changed) {
        record(context, Event.CAPTURE_REQUESTED)
      }
      return status(context)
    } finally { credential.fill(0) }
  }

  @Synchronized fun disable(context: Context) {
    val p = prefs(context)
    // Revocation is durable before cancelling any work or dropping configuration.
    check(p.edit().putBoolean("enabled", false).putLong("generation", p.getLong("generation", 0) + 1)
      .remove("pending").remove("events").remove("pending_last_sequence")
      .remove("quarantine").remove("auth_required").remove("next_attempt").remove("upload_attempt")
      .remove("last_ack_captured").remove("last_ack_field_ref").remove("last_target_baseline")
      .remove("incident_ref").remove("incident_at").remove("last_success").remove("last_code").commit())
    journal.clearPending()
    connection?.disconnect()
    connection = null
    connectionOwner = null
    heartbeat?.cancel(false)
    heartbeat = null
    NativeDiagnosticScheduler.cancel(context)
    NoBackupAeadStore(context).delete(CONFIG)
  }

  /** Clear report history, never the authentication ledger, replay state or key. */
  @Synchronized fun clear(context: Context, since: Long = System.currentTimeMillis()) {
    com.kshouse.gatekeeper_app.blewake.BleForegroundDiscoveryStore.clear(context, since.coerceAtLeast(0))
    val p = prefs(context)
    check(p.edit().putLong("since", since.coerceAtLeast(0)).putLong("generation", p.getLong("generation", 0) + 1)
      .remove("pending").remove("events").remove("pending_last_sequence").putLong("dropped", 0).commit())
    check(p.edit().remove("quarantine").remove("auth_required").remove("next_attempt").remove("upload_attempt")
      .remove("last_ack_captured").remove("last_ack_field_ref").remove("last_target_baseline")
      .remove("incident_ref").remove("incident_at").remove("last_code").remove("last_success")
      .remove("journal_dropped").remove("ring_dropped").remove("quarantined_dropped")
      .remove("ring_drop_first").remove("ring_drop_last").commit())
    journal.clearPending()
    connection?.disconnect()
    connection = null
    connectionOwner = null
    NativeDiagnosticScheduler.cancelImmediate(context)
  }

  fun onProcessStart(context: Context) {
    if (!enabled(context)) return
    NativeDiagnosticScheduler.ensurePeriodic(context)
    startHeartbeat(context)
    record(context, Event.PROCESS_STARTED)
  }

  @Synchronized private fun startHeartbeat(context: Context) {
    if (heartbeat != null) return
    val app = context.applicationContext
    // No wake lock and no promise of execution while Android suspends the app.
    // The durable periodic Worker is the independent process-death catch-up path.
    heartbeat = heartbeatExecutor.scheduleWithFixedDelay({
      runCatching {
        if (!enabled(app)) return@runCatching
        val now = SystemClock.elapsedRealtime()
        if (now - lastHeartbeatElapsed >= TimeUnit.MINUTES.toMillis(5)) {
          lastHeartbeatElapsed = now
          record(app, Event.HEARTBEAT)
        } else NativeDiagnosticScheduler.capture(app)
      }
    }, 60, 60, TimeUnit.SECONDS)
  }

  fun record(context: Context, event: Event, reason: String? = null,
                           sessionId: String? = null, ready: Boolean? = null,
                           epoch: Long? = null, status: Int? = null) {
    // Do not wait on disk or on the outbox monitor in a Bluetooth callback.
    // A generation snapshot also prevents queued events reappearing after Clear.
    val app = context.applicationContext
    val p = prefs(app)
    if (!p.getBoolean("enabled", false)) return
    val generation = p.getLong("generation", 0)
    val now = System.currentTimeMillis()
    val elapsed = SystemClock.elapsedRealtime()
    journal.submit { recordNow(app, generation, now, elapsed, event, reason, sessionId, ready, epoch, status) }
  }

  fun requestNow(context: Context, reason: String = "USER_REQUEST") {
    if (!enabled(context)) return
    // Do not override a server Retry-After or an active upload. A real pending
    // failure remains scheduled; fresh capture is still durable and visible.
    prefs(context).edit().remove("auth_required").apply()
    record(context, Event.INCIDENT_CAPTURE, reason)
    NativeDiagnosticScheduler.upload(context)
  }

  @Synchronized private fun recordNow(context: Context, generation: Long, now: Long, elapsed: Long,
                         event: Event, reason: String?, sessionId: String?, ready: Boolean?, epoch: Long?, status: Int?) {
    if (!enabled(context) || prefs(context).getLong("generation", 0) != generation) return
    try {
      val p = prefs(context)
      val events = JSONArray(p.getString("events", "[]"))
      val code = NativeDiagnosticReport.code(reason)
      val sessionRef = sessionId?.let { NativeDiagnosticReport.opaque("support:$it") }
      val previous = events.optJSONObject(events.length() - 1)
      if (previous?.optString("event") == event.name && previous.optString("reason") == (code ?: "null") &&
        previous.optString("session_ref") == (sessionRef ?: "null") &&
        previous.opt("ready") == (ready ?: JSONObject.NULL) &&
        previous.opt("ready_epoch") == (epoch ?: JSONObject.NULL) &&
        now - previous.optLong("at_epoch_ms") in 0 until 10_000) return
      val sequence = p.getLong("sequence", 0) + 1
      events.put(JSONObject().put("sequence", sequence).put("event", event.name)
        .put("at_epoch_ms", now).put("elapsed_ms", elapsed)
        .put("reason", code ?: JSONObject.NULL).put("session_ref", sessionRef ?: JSONObject.NULL)
        .put("ready", ready ?: JSONObject.NULL).put("ready_epoch", epoch?.takeIf { it in 0..0xffffffffL } ?: JSONObject.NULL)
        .put("status", status?.takeIf { it in -1..65535 } ?: JSONObject.NULL))
      val rejected = journal.drainDropped()
      try {
        val evictedTimes = mutableListOf<Long>()
        val evicted = NativeDiagnosticOutboxPolicy.bound(events) { evictedTimes.add(it.optLong("at_epoch_ms", now)) }
        val dropped = p.getLong("dropped", 0) + evicted + rejected
        val edit = p.edit().putString("events", events.toString()).putLong("sequence", sequence).putLong("dropped", dropped)
          .putLong("ring_dropped", p.getLong("ring_dropped", 0) + evicted)
          .putLong("journal_dropped", p.getLong("journal_dropped", 0) + rejected)
        if (evicted > 0) edit.putLong("ring_drop_first", minOf(p.getLong("ring_drop_first", Long.MAX_VALUE), evictedTimes.min()))
          .putLong("ring_drop_last", maxOf(p.getLong("ring_drop_last", 0), evictedTimes.max()))
        if (event == Event.MANUAL_OPEN_CONTEXT || event == Event.INCIDENT_CAPTURE ||
            event == Event.WORKER_FINISHED && code !in setOf(null, "SUCCEEDED")) {
          if (!p.contains("incident_ref") || now - p.getLong("incident_at", 0) !in 0..600_000L) {
            edit.putString("incident_ref", NativeDiagnosticReport.opaque("incident:$processRef:$sequence"))
              .putLong("incident_at", now)
          }
        }
        check(edit.commit())
      } catch (failure: Exception) {
        journal.restoreDropped(rejected)
        throw failure
      }
      NativeDiagnosticScheduler.capture(context)
      NativeDiagnosticScheduler.upload(context)
    } catch (_: Exception) {
      // Diagnostics failure must never throw through scan callbacks or authentication.
      prefs(context).edit().putString("last_code", "DIAGNOSTIC_STORAGE_ERROR").apply()
    }
  }

  @Synchronized fun status(context: Context): Map<String, Any?> {
    val p = prefs(context)
    return mapOf("supported" to true, "enabled" to p.getBoolean("enabled", false),
      "pendingUploads" to if (p.contains("pending")) 1 else 0,
      "pendingEvents" to runCatching { JSONArray(p.getString("events", "[]")).length() }.getOrDefault(0),
      "lastSuccessEpochMs" to p.getLong("last_success", 0).takeIf { it > 0 },
      "lastCode" to p.getString("last_code", null), "droppedEvents" to journal.totalDropped(p.getLong("dropped", 0)),
      "oldestPendingEpochMs" to oldestPending(context), "nextAttemptEpochMs" to p.getLong("next_attempt", 0).takeIf { it > 0 },
      "uploadAttempt" to p.getInt("upload_attempt", 0), "uploadState" to uploadState(context),
      "lastAckCapturedEpochMs" to p.getLong("last_ack_captured", 0).takeIf { it > 0 },
      "lastAckFieldTestRef" to p.getString("last_ack_field_ref", null),
      "lastTargetBaseline" to p.getString("last_target_baseline", null)?.let { raw ->
        val item = JSONObject(raw)
        mapOf("fresh" to item.optBoolean("fresh"), "observedEpochMs" to item.optLong("observed_epoch_ms"),
          "state" to item.optString("state"), "relayCommandedOn" to (item.opt("relay_commanded_on") as? Boolean))
      },
      "quarantinedCount" to JSONArray(p.getString("quarantine", "[]")).length())
  }

  private fun oldestPending(context: Context): Long? {
    val p = prefs(context)
    val events = JSONArray(p.getString("events", "[]"))
    val event = events.optJSONObject(0)?.optLong("at_epoch_ms")?.takeIf { it > 0 }
    val pending = p.getString("pending", null)?.let { java.time.Instant.parse(JSONObject(it).getString("created_at")).toEpochMilli() }
    return listOfNotNull(event, pending).minOrNull()
  }

  private fun uploadState(context: Context): String {
    val p = prefs(context)
    return when {
      !p.getBoolean("enabled", false) -> "DISABLED"
      p.getBoolean("auth_required", false) -> "AUTH_REQUIRED"
      connection != null -> "UPLOADING"
      p.getLong("next_attempt", 0) > System.currentTimeMillis() -> "RETRY_WAIT"
      p.contains("pending") || JSONArray(p.getString("events", "[]")).length() > 0 -> "QUEUED"
      p.getLong("last_success", 0) == 0L -> "NOT_UPLOADED"
      System.currentTimeMillis() - p.getLong("last_success", 0) > 300_000 -> "STALE"
      else -> "ACKNOWLEDGED"
    }
  }

  @Synchronized internal fun runtime(context: Context, now: Long): JSONObject {
    val p = prefs(context)
    val pending = p.getString("pending", null)?.let(::JSONObject)
    val events = JSONArray(p.getString("events", "[]"))
    val projected = JSONArray()
    for (index in 0 until minOf(64, events.length())) {
      projected.put(JSONObject(events.getJSONObject(index).toString()))
    }
    return JSONObject().put("captured_epoch_ms", now).put("captured_elapsed_ms", SystemClock.elapsedRealtime())
      .put("process_ref", processRef).put("pending_uploads", if (pending == null) 0 else 1)
      .put("oldest_pending_epoch_ms", oldestPending(context) ?: JSONObject.NULL)
      .put("last_upload_success_epoch_ms", p.getLong("last_success", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("last_upload_code", p.getString("last_code", null) ?: JSONObject.NULL)
      .put("generation", p.getLong("generation", 0)).put("pending_events", events.length())
      .put("event_first_epoch_ms", projected.optJSONObject(0)?.optLong("at_epoch_ms") ?: JSONObject.NULL)
      .put("event_last_epoch_ms", projected.optJSONObject(projected.length() - 1)?.optLong("at_epoch_ms") ?: JSONObject.NULL)
      .put("last_enqueue_epoch_ms", p.getLong("last_enqueue", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("last_worker_start_epoch_ms", p.getLong("last_worker_start", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("last_worker_stop_epoch_ms", p.getLong("last_worker_stop", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("last_upload_attempt_epoch_ms", p.getLong("last_attempt", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("next_attempt_epoch_ms", p.getLong("next_attempt", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("upload_attempt", p.getInt("upload_attempt", 0)).put("upload_state", uploadState(context))
      .put("journal_dropped", journal.totalDropped(p.getLong("journal_dropped", 0)))
      .put("ring_dropped", p.getLong("ring_dropped", 0))
      .put("ring_drop_first_epoch_ms", p.getLong("ring_drop_first", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("ring_drop_last_epoch_ms", p.getLong("ring_drop_last", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("quarantined_count", JSONArray(p.getString("quarantine", "[]")).length())
      .put("quarantined_dropped", p.getLong("quarantined_dropped", 0))
      .put("latest_snapshot", true).put("incident_ref", p.getString("incident_ref", null)
        ?.takeIf { now - p.getLong("incident_at", 0) in 0..600_000L } ?: JSONObject.NULL)
      .put("dropped_events", journal.totalDropped(p.getLong("dropped", 0))).put("lifecycle", projected).also { result ->
        NativeDiagnosticPlatform.snapshot(context).forEach { (key, value) -> result.put(key, value ?: JSONObject.NULL) }
      }
  }

  internal data class CaptureState(val generation: Long, val since: Long, val config: JSONObject, val runtime: JSONObject, val lastSequence: Long)
  @Synchronized internal fun prepareCapture(context: Context): CaptureState? {
    if (!enabled(context)) return null
    val p = prefs(context)
    if (p.contains("pending")) { NativeDiagnosticScheduler.upload(context); return null }
    val config = readConfig(context) ?: return null
    val events = JSONArray(p.getString("events", "[]"))
    if (events.length() == 0) return null
    return CaptureState(p.getLong("generation", 0), p.getLong("since", 0), config,
      runtime(context, System.currentTimeMillis()), events.getJSONObject(minOf(64, events.length()) - 1).getLong("sequence"))
  }

  @Synchronized internal fun storeCapture(context: Context, state: CaptureState, report: JSONObject) {
    val p = prefs(context)
    if (!enabled(context) || p.getLong("generation", 0) != state.generation || p.contains("pending")) return
    check(p.edit().putString("pending", report.toString()).putLong("pending_last_sequence", state.lastSequence).commit())
    NativeDiagnosticScheduler.upload(context)
  }

  internal data class Upload(val generation: Long, val report: String, val config: JSONObject)
  @Synchronized internal fun pending(context: Context): Upload? {
    if (!enabled(context)) return null
    val p = prefs(context)
    val raw = p.getString("pending", null) ?: return null
    return Upload(p.getLong("generation", 0), raw, readConfig(context) ?: return null)
  }
  @Synchronized internal fun beginHttp(context: Context, upload: Upload, http: HttpsURLConnection, owner: String = "legacy"): Boolean {
    if (connection != null || !NativeDiagnosticOutboxPolicy.current(enabled(context),
        prefs(context).getLong("generation", 0), upload.generation, prefs(context).getString("pending", null), upload.report)) return false
    connection = http
    connectionOwner = owner
    prefs(context).edit().putLong("last_attempt", System.currentTimeMillis()).apply()
    return true
  }
  @Synchronized internal fun finishHttp(http: HttpsURLConnection) { if (connection === http) { connection = null; connectionOwner = null } }
  @Synchronized internal fun stopHttp(owner: String) {
    if (connectionOwner == owner) { connection?.disconnect(); connection = null; connectionOwner = null }
  }
  @Synchronized internal fun authRequired(context: Context) = prefs(context).getBoolean("auth_required", false)
  @Synchronized internal fun nextAttemptDelay(context: Context) =
    (prefs(context).getLong("next_attempt", 0) - System.currentTimeMillis()).coerceAtLeast(0)
  internal fun schedulerEnqueued(context: Context) { prefs(context).edit().putLong("last_enqueue", System.currentTimeMillis()).apply() }
  internal fun schedulerFailed(context: Context) { prefs(context).edit().putString("last_code", "SCHEDULER_OR_STORAGE_ERROR").apply() }
  internal fun workerStarted(context: Context) { prefs(context).edit().putLong("last_worker_start", System.currentTimeMillis()).apply() }
  internal fun workerStopped(context: Context) { prefs(context).edit().putLong("last_worker_stop", System.currentTimeMillis()).apply() }

  @Synchronized internal fun completeAttempt(context: Context, upload: Upload, attempt: NativeDiagnosticDrain.Attempt) {
    val p = prefs(context)
    if (!NativeDiagnosticOutboxPolicy.current(enabled(context), p.getLong("generation", 0),
        upload.generation, p.getString("pending", null), upload.report)) return
    when (attempt.disposition) {
      NativeDiagnosticDrain.Disposition.ACCEPTED -> complete(context, upload, attempt.code, true, attempt.targetBaseline)
      NativeDiagnosticDrain.Disposition.RETRY -> {
        val tries = (p.getInt("upload_attempt", 0) + 1).coerceAtMost(1000)
        check(p.edit().putString("last_code", attempt.code).putInt("upload_attempt", tries)
          .putLong("next_attempt", System.currentTimeMillis() + NativeDiagnosticDrain.delayMs(tries, attempt.retryAfterMs)).commit())
      }
      NativeDiagnosticDrain.Disposition.AUTH_REQUIRED -> check(p.edit().putString("last_code", attempt.code)
        .putBoolean("auth_required", true).remove("next_attempt").commit())
      NativeDiagnosticDrain.Disposition.QUARANTINE -> {
        val rejected = JSONArray(p.getString("quarantine", "[]"))
        rejected.put(JSONObject().put("report", JSONObject(upload.report)).put("code", attempt.code)
          .put("at_epoch_ms", System.currentTimeMillis()))
        var evicted = 0
        while (rejected.length() > 4) { rejected.remove(0); evicted++ }
        val remaining = NativeDiagnosticOutboxPolicy.retainAfterAck(JSONArray(p.getString("events", "[]")),
          p.getLong("pending_last_sequence", 0))
        // Rejected evidence is quarantined, NOT acknowledged. Never update last_success.
        check(p.edit().putString("quarantine", rejected.toString()).putString("last_code", attempt.code)
          .putLong("quarantined_dropped", p.getLong("quarantined_dropped", 0) + evicted)
          .remove("pending").remove("pending_last_sequence").putString("events", remaining.toString())
          .remove("next_attempt").putInt("upload_attempt", 0).commit())
      }
      NativeDiagnosticDrain.Disposition.CANCELLED -> Unit
    }
  }

  @Synchronized internal fun complete(context: Context, upload: Upload, code: String, accepted: Boolean,
                                      baseline: NativeDiagnosticBaseline? = null) {
    val p = prefs(context)
    if (!NativeDiagnosticOutboxPolicy.current(enabled(context), p.getLong("generation", 0),
        upload.generation, p.getString("pending", null), upload.report)) return
    val edit = p.edit().putString("last_code", code)
    if (accepted) {
      val report = JSONObject(upload.report)
      val captured = report.optJSONObject("native")?.optJSONObject("runtime")?.optLong("captured_epoch_ms")
        ?: java.time.Instant.parse(report.getString("created_at")).toEpochMilli()
      edit.putLong("last_ack_captured", captured)
      val fieldRef = report.optJSONObject("field_test")?.optString("ref")?.takeIf { it.matches(Regex("[0-9a-f]{16}")) }
      if (fieldRef == null) edit.remove("last_ack_field_ref") else edit.putString("last_ack_field_ref", fieldRef)
      if (baseline == null) edit.remove("last_target_baseline") else edit.putString("last_target_baseline", baseline.json().toString())
      val acknowledged = p.getLong("pending_last_sequence", 0)
      val events = JSONArray(p.getString("events", "[]"))
      val remaining = NativeDiagnosticOutboxPolicy.retainAfterAck(events, acknowledged)
      edit.remove("pending").remove("pending_last_sequence").putString("events", remaining.toString())
        .putLong("last_success", System.currentTimeMillis()).putInt("upload_attempt", 0)
        .remove("next_attempt").remove("auth_required")
    }
    check(edit.commit())
    // ACK does not itself create a new diagnostic event or an endless upload loop.
    if (accepted) NativeDiagnosticScheduler.capture(context)
  }

  private fun readConfig(context: Context): JSONObject? {
    val bytes = NoBackupAeadStore(context).read(CONFIG) ?: return null
    return try { JSONObject(String(bytes, Charsets.UTF_8)) } finally { bytes.fill(0) }
  }
}
