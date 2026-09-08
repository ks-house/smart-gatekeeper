package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.os.Build
import androidx.work.*
import org.json.JSONObject
import java.net.URL
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection

internal object NativeDiagnosticScheduler {
  private const val CAPTURE = "native-diagnostic-capture-v1"
  private const val UPLOAD = "native-diagnostic-upload-v1"
  private const val HEARTBEAT = "native-diagnostic-heartbeat-v1"
  fun capture(context: Context) = safely {
    WorkManager.getInstance(context).enqueueUniqueWork(CAPTURE, ExistingWorkPolicy.KEEP,
      OneTimeWorkRequestBuilder<NativeDiagnosticCaptureWorker>().setInitialDelay(2, TimeUnit.SECONDS).build())
  }
  fun upload(context: Context) = safely {
    WorkManager.getInstance(context).enqueueUniqueWork(UPLOAD, ExistingWorkPolicy.KEEP,
      OneTimeWorkRequestBuilder<NativeDiagnosticUploadWorker>()
        .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build())
  }
  fun ensurePeriodic(context: Context) = safely {
    WorkManager.getInstance(context).enqueueUniquePeriodicWork(HEARTBEAT, ExistingPeriodicWorkPolicy.KEEP,
      PeriodicWorkRequestBuilder<NativeDiagnosticHeartbeatWorker>(15, TimeUnit.MINUTES).build())
  }
  fun cancelImmediate(context: Context) = safely {
    WorkManager.getInstance(context).cancelUniqueWork(CAPTURE)
    WorkManager.getInstance(context).cancelUniqueWork(UPLOAD)
  }
  fun cancel(context: Context) { cancelImmediate(context); safely { WorkManager.getInstance(context).cancelUniqueWork(HEARTBEAT) } }
  private inline fun safely(block: () -> Unit) { try { block() } catch (_: RuntimeException) { /* journal remains durable */ } }
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
    val upload = try { NativeDiagnostics.pending(applicationContext) } catch (_: Exception) { return Result.retry() }
      ?: return Result.success()
    val credential = BleCredentialConfigStore(applicationContext).credentialId() ?: run {
      NativeDiagnostics.complete(applicationContext, upload, "CREDENTIAL_UNAVAILABLE", false)
      return Result.retry()
    }
    var http: HttpsURLConnection? = null
    var code = "NETWORK_OR_IDENTITY_ERROR"
    var accepted = false
    try {
      if (upload.config.getString("binding") != NativeDiagnosticReport.opaque("upload-binding:${credential.toHex()}")) {
        NativeDiagnostics.disable(applicationContext)
        return Result.success()
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
      if (!NativeDiagnostics.beginHttp(applicationContext, upload, http)) return Result.success()
      try { http.outputStream.use { it.write(body) } } finally { body.fill(0) }
      val status = http.responseCode
      code = "HTTP_$status"
      if (status in 200..299) {
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
        code = if (accepted) "ACCEPTED" else "INVALID_ACK"
      }
    } catch (_: Exception) { /* no server body, credential, URL or exception text retained */ }
    finally {
      credential.fill(0)
      http?.let { NativeDiagnostics.finishHttp(it); it.disconnect() }
    }
    try {
      NativeDiagnostics.complete(applicationContext, upload, code, accepted)
      if (accepted) {
        // A capture queued while this unique upload is RUNNING must not get
        // stranded by KEEP. Persist the next batch before yielding this worker.
        NativeDiagnosticCaptureWorker.capture(applicationContext)
        if (NativeDiagnostics.pending(applicationContext) != null) return Result.retry()
      }
    } catch (_: Exception) { return Result.retry() }
    // Permanent-looking schema/auth failures are also retained for a later deployment/config fix.
    return if (accepted) Result.success() else Result.retry()
  }
}
