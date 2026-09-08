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
    SCAN_REGISTRATION, SCAN_EXIT, ORPHAN_RECOVERED }
  private const val PREFS = "native_diagnostic_outbox_v1"
  private const val CONFIG = "diagnostic-upload-config-v1"
  private val processRef = NativeDiagnosticReport.opaque("diagnostic-process:${UUID.randomUUID()}")
  private var connection: HttpsURLConnection? = null
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
      }
      val p = prefs(context)
      if (since > p.getLong("since", 0)) clear(context, since)
      check(p.edit().putBoolean("enabled", true).commit())
      if (changed) {
        NativeDiagnosticScheduler.ensurePeriodic(context)
        startHeartbeat(context)
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
      .remove("last_success").remove("last_code").commit())
    journal.clearPending()
    connection?.disconnect()
    connection = null
    heartbeat?.cancel(false)
    heartbeat = null
    NativeDiagnosticScheduler.cancel(context)
    NoBackupAeadStore(context).delete(CONFIG)
  }

  /** Clear report history, never the authentication ledger, replay state or key. */
  @Synchronized fun clear(context: Context, since: Long = System.currentTimeMillis()) {
    val p = prefs(context)
    check(p.edit().putLong("since", since.coerceAtLeast(0)).putLong("generation", p.getLong("generation", 0) + 1)
      .remove("pending").remove("events").remove("pending_last_sequence").putLong("dropped", 0).commit())
    journal.clearPending()
    connection?.disconnect()
    connection = null
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
        val dropped = p.getLong("dropped", 0) + NativeDiagnosticOutboxPolicy.bound(events) + rejected
        check(p.edit().putString("events", events.toString()).putLong("sequence", sequence).putLong("dropped", dropped).commit())
      } catch (failure: Exception) {
        journal.restoreDropped(rejected)
        throw failure
      }
      NativeDiagnosticScheduler.capture(context)
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
      "lastCode" to p.getString("last_code", null), "droppedEvents" to journal.totalDropped(p.getLong("dropped", 0)))
  }

  @Synchronized internal fun runtime(context: Context, now: Long): JSONObject {
    val p = prefs(context)
    val pending = p.getString("pending", null)?.let(::JSONObject)
    val events = JSONArray(p.getString("events", "[]"))
    val projected = JSONArray()
    for (index in 0 until minOf(64, events.length())) {
      projected.put(JSONObject(events.getJSONObject(index).toString()).apply { remove("sequence") })
    }
    return JSONObject().put("captured_epoch_ms", now).put("captured_elapsed_ms", SystemClock.elapsedRealtime())
      .put("process_ref", processRef).put("pending_uploads", if (pending == null) 0 else 1)
      .put("oldest_pending_epoch_ms", if (pending == null) JSONObject.NULL else java.time.Instant.parse(pending.getString("created_at")).toEpochMilli())
      .put("last_upload_success_epoch_ms", p.getLong("last_success", 0).takeIf { it > 0 } ?: JSONObject.NULL)
      .put("last_upload_code", p.getString("last_code", null) ?: JSONObject.NULL)
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
  @Synchronized internal fun beginHttp(context: Context, upload: Upload, http: HttpsURLConnection): Boolean {
    if (!enabled(context) || prefs(context).getLong("generation", 0) != upload.generation) return false
    connection = http
    return true
  }
  @Synchronized internal fun finishHttp(http: HttpsURLConnection) { if (connection === http) connection = null }

  @Synchronized internal fun complete(context: Context, upload: Upload, code: String, accepted: Boolean) {
    val p = prefs(context)
    if (!NativeDiagnosticOutboxPolicy.current(enabled(context), p.getLong("generation", 0),
        upload.generation, p.getString("pending", null), upload.report)) return
    val edit = p.edit().putString("last_code", code)
    if (accepted) {
      val acknowledged = p.getLong("pending_last_sequence", 0)
      val events = JSONArray(p.getString("events", "[]"))
      val remaining = NativeDiagnosticOutboxPolicy.retainAfterAck(events, acknowledged)
      edit.remove("pending").remove("pending_last_sequence").putString("events", remaining.toString())
        .putLong("last_success", System.currentTimeMillis())
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
