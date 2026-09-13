package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.os.Build
import android.os.SystemClock
import androidx.work.*
import org.json.JSONObject
import java.net.URL
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.HttpsURLConnection

internal object NativeDiagnosticScheduler {
  private const val CAPTURE = "native-diagnostic-capture-v1"
  private const val LEGACY_UPLOAD = "native-diagnostic-upload-v1"
  private const val UPLOAD = "native-diagnostic-upload-v2"
  private const val HEARTBEAT = "native-diagnostic-heartbeat-v1"
  private val executor = Executors.newSingleThreadExecutor { task ->
    Thread(task, "sgk-diagnostic-scheduler").apply { isDaemon = true }
  }
  private val uploadQueued = AtomicBoolean(false)
  fun capture(context: Context) = safely(context) {
    WorkManager.getInstance(context).enqueueUniqueWork(CAPTURE, ExistingWorkPolicy.KEEP,
      OneTimeWorkRequestBuilder<NativeDiagnosticCaptureWorker>().setInitialDelay(2, TimeUnit.SECONDS).build())
  }
  fun upload(context: Context) {
    if (!uploadQueued.compareAndSet(false, true)) return
    val app = context.applicationContext
    executor.execute {
      // A concurrent producer may enqueue one more pass; all passes are serialized.
      uploadQueued.set(false)
      safely(app) {
        if (!NativeDiagnostics.enabled(app) || NativeDiagnostics.authRequired(app)) return@safely
        val manager = WorkManager.getInstance(app)
        val states = manager.getWorkInfosForUniqueWork(UPLOAD).get(5, TimeUnit.SECONDS).map { it.state.name }
        if (NativeDiagnosticDrain.needsSuccessor(states)) {
          val delay = NativeDiagnostics.nextAttemptDelay(app)
          val work = OneTimeWorkRequestBuilder<NativeDiagnosticUploadWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInitialDelay(delay, TimeUnit.MILLISECONDS).build()
          // At most one running job plus one pending successor. Unlike KEEP this
          // also covers an event produced just before the running job returns.
          val policy = if ("RUNNING" in states) ExistingWorkPolicy.APPEND_OR_REPLACE else ExistingWorkPolicy.REPLACE
          manager.enqueueUniqueWork(UPLOAD, policy, work)
            .result.get(5, TimeUnit.SECONDS)
          NativeDiagnostics.schedulerEnqueued(app)
        }
      }
    }
  }
  fun ensurePeriodic(context: Context) = safely(context) {
    WorkManager.getInstance(context).enqueueUniquePeriodicWork(HEARTBEAT, ExistingPeriodicWorkPolicy.KEEP,
      PeriodicWorkRequestBuilder<NativeDiagnosticHeartbeatWorker>(15, TimeUnit.MINUTES).build())
    val app = context.applicationContext
    executor.execute { safely(app) {
      val p = app.getSharedPreferences("native_diagnostic_scheduler", Context.MODE_PRIVATE)
      if (p.getInt("version", 0) < 2) {
        // Keep immutable pending bytes and consent generation; retire only old
        // WorkManager backoff. APK update needs no Clear or opt-out/opt-in cycle.
        WorkManager.getInstance(app).cancelUniqueWork(LEGACY_UPLOAD).result.get(5, TimeUnit.SECONDS)
        check(p.edit().putInt("version", 2).commit())
      }
      upload(app)
    } }
  }
  fun cancelImmediate(context: Context) = safely(context) {
    WorkManager.getInstance(context).cancelUniqueWork(CAPTURE)
    WorkManager.getInstance(context).cancelUniqueWork(LEGACY_UPLOAD)
    WorkManager.getInstance(context).cancelUniqueWork(UPLOAD)
  }
  fun cancel(context: Context) { cancelImmediate(context); safely(context) { WorkManager.getInstance(context).cancelUniqueWork(HEARTBEAT) } }
  private inline fun safely(context: Context, block: () -> Unit) {
    try { block() } catch (_: Exception) { NativeDiagnostics.schedulerFailed(context) }
  }
}

class NativeDiagnosticHeartbeatWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result {
    NativeDiagnostics.record(applicationContext, NativeDiagnostics.Event.HEARTBEAT)
    return Result.success()
  }
}

class NativeDiagnosticCaptureWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result = try {
    capture(applicationContext)
    Result.success()
  } catch (_: Exception) { Result.retry() }

  companion object {
    internal fun capture(context: Context) {
      val state = NativeDiagnostics.prepareCapture(context)
      if (state != null) {
        @Suppress("DEPRECATION")
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        val build = if (Build.VERSION.SDK_INT >= 28) packageInfo.longVersionCode.toString() else {
          @Suppress("DEPRECATION") packageInfo.versionCode.toString()
        }
        val report = NativeDiagnosticReport.build(packageInfo.versionName ?: "unknown", build, Build.VERSION.SDK_INT,
          state.config.getJSONObject("identity"), BleGattHealthBridge.snapshot(context),
          BleGattHealthBridge.recentDiagnostics(context), state.runtime, state.since,
          state.runtime.getLong("captured_epoch_ms"), state.config.optJSONObject("field_test"))
        NativeDiagnostics.storeCapture(context, state, report)
      }
    }
  }
}

/** Persistent report and reference remain byte-for-byte identical across retries/process deaths. */
class NativeDiagnosticUploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result {
    var current: NativeDiagnostics.Upload? = null
    return try {
      NativeDiagnostics.workerStarted(applicationContext)
      NativeDiagnosticDrain.run(object : NativeDiagnosticDrain.Port {
        override fun stopped() = isStopped || !NativeDiagnostics.enabled(applicationContext)
        override fun elapsedMs() = SystemClock.elapsedRealtime()
        override fun next(): Boolean {
          if (NativeDiagnostics.authRequired(applicationContext)) return false
          if (NativeDiagnostics.nextAttemptDelay(applicationContext) > 0) { continueLater(); return false }
          NativeDiagnosticCaptureWorker.capture(applicationContext)
          current = NativeDiagnostics.pending(applicationContext)
          return current != null
        }
        override fun send() = transmit(requireNotNull(current))
        override fun finish(attempt: NativeDiagnosticDrain.Attempt) =
          NativeDiagnostics.completeAttempt(applicationContext, requireNotNull(current), attempt)
        override fun continueLater() = NativeDiagnosticScheduler.upload(applicationContext)
      })
      Result.success()
    } catch (_: Exception) {
      NativeDiagnostics.schedulerFailed(applicationContext)
      Result.retry() // Storage/scheduler failure only, never a successful batch.
    } finally { NativeDiagnostics.workerStopped(applicationContext) }
  }

  override fun onStopped() { NativeDiagnostics.stopHttp(id.toString()) }

  private fun transmit(upload: NativeDiagnostics.Upload): NativeDiagnosticDrain.Attempt {
    val credential = BleCredentialConfigStore(applicationContext).credentialId() ?: run {
      return NativeDiagnosticDrain.Attempt("CREDENTIAL_UNAVAILABLE", NativeDiagnosticDrain.Disposition.AUTH_REQUIRED)
    }
    var http: HttpsURLConnection? = null
    var code = "NETWORK_OR_IDENTITY_ERROR"
    var accepted = false
    var status: Int? = null
    var retryAfter: String? = null
    var baseline: NativeDiagnosticBaseline? = null
    try {
      if (upload.config.getString("binding") != NativeDiagnosticReport.opaque("upload-binding:${credential.toHex()}")) {
        NativeDiagnostics.disable(applicationContext)
        return NativeDiagnosticDrain.Attempt("AUTHORITY_CHANGED", NativeDiagnosticDrain.Disposition.CANCELLED)
      }
      val report = JSONObject(upload.report)
      val body = JSONObject().put("device_id", upload.config.getString("device_id"))
        .put("credential_id", credential.toHex())
        .put("public_key_sec1", AndroidKeystoreCredentialSigner().publicKeySec1(credential).toHex())
        .put("bundle", report).toString().toByteArray(Charsets.UTF_8)
      require(body.size <= 64 * 1024)
      val base = NativeDiagnostics.validBase(upload.config.getString("base"))
      http = URL("$base/acl/personal/diagnostics").openConnection() as HttpsURLConnection
      http.instanceFollowRedirects = false
      http.connectTimeout = 10_000
      http.readTimeout = 10_000
      http.requestMethod = "POST"
      http.doOutput = true
      http.setRequestProperty("Content-Type", "application/json")
      http.setRequestProperty("X-API-KEY", upload.config.getString("api_key"))
      http.setFixedLengthStreamingMode(body.size)
      if (!NativeDiagnostics.beginHttp(applicationContext, upload, http, id.toString())) {
        body.fill(0)
        return NativeDiagnosticDrain.Attempt("CANCELLED", NativeDiagnosticDrain.Disposition.CANCELLED)
      }
      try { http.outputStream.use { it.write(body) } } finally { body.fill(0) }
      val responseStatus = http.responseCode
      status = responseStatus
      retryAfter = http.getHeaderField("Retry-After")
      code = "HTTP_$responseStatus"
      if (responseStatus in 200..299) {
        val response = http.inputStream.use { stream ->
          val buffer = ByteArray(4097)
          var count = 0
          while (count < buffer.size) {
            val read = stream.read(buffer, count, buffer.size - count)
            if (read < 0) break
            count += read
          }
          require(count <= 4096)
          JSONObject(String(buffer, 0, count, Charsets.UTF_8))
        }
        accepted = NativeDiagnosticOutboxPolicy.accepted(response, report.getString("bundle_ref"))
        if (accepted) baseline = NativeDiagnosticBaseline.parse(response.optJSONObject("target_baseline"), System.currentTimeMillis())
        code = if (accepted) "ACCEPTED" else "INVALID_ACK"
      }
    } catch (_: Exception) { /* no server body, credential, URL or exception text retained */ }
    finally {
      credential.fill(0)
      http?.let { NativeDiagnostics.finishHttp(it); it.disconnect() }
    }
    return status?.let { NativeDiagnosticDrain.http(it, accepted, retryAfter, System.currentTimeMillis()).copy(targetBaseline = baseline) }
      ?: NativeDiagnosticDrain.Attempt(code, NativeDiagnosticDrain.Disposition.RETRY)
  }
}
