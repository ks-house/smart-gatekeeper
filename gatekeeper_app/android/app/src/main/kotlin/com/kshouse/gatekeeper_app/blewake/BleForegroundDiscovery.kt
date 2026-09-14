package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import com.flutterbeacon.CrossProcessBleOwnerCoordinator
import com.kshouse.gatekeeper_app.gattworker.BleGattFeatureFlagStore
import com.kshouse.gatekeeper_app.gattworker.BleGattRuntimeEnvironment
import com.kshouse.gatekeeper_app.gattworker.NativeDiagnostics

/** One foreground attempt per resume, with a durable cooldown and a kernel BLE lease.
 * All state changes serialize on the existing registrar; snapshots only read aggregates.
 */
internal object BleForegroundDiscovery {
  private const val PREFS = "ble_foreground_discovery_v1"
  private val handler = Handler(Looper.getMainLooper())
  private var foreground = false
  private var generation = 0L
  private var pending: Runnable? = null
  private var deadline: Runnable? = null
  @Volatile private var session: ForegroundDiscoverySession? = null
  private var screenReceiver: BroadcastReceiver? = null
  private var lastFlush = 0L
  private var windowStartedAt = 0L

  fun onForeground(context: Context) = synchronized(BleWakeRegistrar) {
    if (foreground) return@synchronized
    foreground = true
    val app = context.applicationContext
    val receiver = object : BroadcastReceiver() {
      override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_SCREEN_OFF) cancel(context, "CANCELLED_SCREEN_OFF")
      }
    }
    try {
      if (Build.VERSION.SDK_INT >= 33) app.registerReceiver(receiver,
        IntentFilter(Intent.ACTION_SCREEN_OFF), Context.RECEIVER_NOT_EXPORTED)
      else {
        @Suppress("DEPRECATION")
        app.registerReceiver(receiver, IntentFilter(Intent.ACTION_SCREEN_OFF))
      }
      screenReceiver = receiver
    } catch (_: RuntimeException) { foreground = false; return@synchronized }
    if (!BleWakeRegistrar.isEnabled(app) || !BleGattFeatureFlagStore(app).decision().newWorkerEnabled) return@synchronized
    awaitPrimary(app)
  }

  internal fun awaitPrimary(app: Context) = synchronized(BleWakeRegistrar) {
    if (pending != null) return@synchronized
    val p = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val now = System.currentTimeMillis()
    if (busy()) return@synchronized // A failed cleanup still owns the radio.
    if (!BleScanRecoveryPolicy.mayStart(now, p.getLong("last_attempt", p.getLong("alternativeStartedAtEpochMs", 0)).takeIf { it > 0 })) return@synchronized
    // Process death releases ScanCallback and kernel lock; do not claim old SCANNING is alive.
    if (p.getString("alternativeStage", null) == "SCANNING")
      p.edit().putString("alternativeStage", "PROCESS_INTERRUPTED").apply()
    windowStartedAt = now
    BleForegroundDiscoveryStore.waiting(app)
    val token = ++generation
    pending = Runnable { synchronized(BleWakeRegistrar) {
      if (token != generation || !foreground) return@synchronized
      pending = null
      val packet = BleScanDiagnostics.snapshot(app)["lastPacketAtEpochMs"] as? Long
      if (BleScanRecoveryPolicy.freshPacket(System.currentTimeMillis(), packet)) {
        BleForegroundDiscoveryStore.finishWaiting(app, windowStartedAt, "MATCH_OBSERVED")
        return@synchronized
      }
      start(app, token)
    } }
    handler.postDelayed(pending!!, ForegroundDiscoverySession.PRIMARY_GRACE_MS)
  }

  fun onBackground(context: Context) = synchronized(BleWakeRegistrar) {
    cancel(context, "CANCELLED_ACTIVITY_STOP")
    foreground = false
    screenReceiver?.let { runCatching { context.applicationContext.unregisterReceiver(it) } }
    screenReceiver = null
  }

  private fun eligible(context: Context): Boolean = runCatching { foreground &&
    context.getSystemService(PowerManager::class.java)?.isInteractive == true &&
    BleWakeRegistrar.isEnabled(context) && BleGattFeatureFlagStore(context).decision().newWorkerEnabled &&
    BleGattRuntimeEnvironment.currentBlockingReason(context) == null }.getOrDefault(false)

  private fun start(context: Context, token: Long) {
    var scanner: BluetoothLeScanner? = null
    var lease: CrossProcessBleOwnerCoordinator.Lease? = null
    val stopAt = SystemClock.elapsedRealtime() + ForegroundDiscoverySession.WINDOW_MS
    lateinit var current: ForegroundDiscoverySession
    val callback = object : ScanCallback() {
      override fun onScanResult(callbackType: Int, result: ScanResult) = receive(listOf(result))
      override fun onBatchScanResults(results: MutableList<ScanResult>) = receive(results)
      private fun receive(results: List<ScanResult>) = synchronized(BleWakeRegistrar) {
        if (generation != token || !current.acceptingResults) return@synchronized
        if (!eligible(context)) { cancel(context, "ENVIRONMENT_BLOCKED"); return@synchronized }
        if (!ForegroundDiscoverySession.inWindow(SystemClock.elapsedRealtime(), stopAt)) {
          finish(context, "NO_MATCHING_PACKET"); return@synchronized
        }
        for (result in results.take(ForegroundDiscoverySession.MAX_BATCH)) {
          val data = result.scanRecord?.getManufacturerSpecificData(BleWakeContract.APPLE_COMPANY_ID)
          val fresh = result.timestampNanos / 1_000_000L >= stopAt - ForegroundDiscoverySession.WINDOW_MS && BleScanObservationPolicy.fresh(
            BleScanObservationPolicy.ageMs(result.timestampNanos, SystemClock.elapsedRealtimeNanos()))
          if (current.sample(ForegroundDiscoverySession.candidate(data),
              BleWakeContract.matchesManufacturerData(data) && fresh)) {
            // Stop callback and restore PendingIntents BEFORE feeding an exact, fresh
            // match into the existing policy/auth pipeline. No alternative auth path.
            finish(context, "MATCH_OBSERVED")
            if (current.active) return@synchronized // Stop/release failed: no authentication.
            BleWakeScanReceiver.processResults(context, listOf(result), 0,
              ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
            return@synchronized
          }
        }
        persist(context, terminal = false)
      }
      override fun onScanFailed(errorCode: Int) = synchronized(BleWakeRegistrar) {
        if (generation != token || !current.acceptingResults) return@synchronized
        current.error(errorCode)
        clearDeadline()
        persist(context, terminal = true)
      }
    }
    current = ForegroundDiscoverySession(object : ForegroundDiscoverySession.Port {
      override fun acquire(): Boolean {
        if (BleWakeRegistrar.inFlightSession(context)) return false
        lease = CrossProcessBleOwnerCoordinator.forContext(context).tryAcquireNative()
        return lease != null
      }
      override fun stopPrimary() {
        scanner = context.getSystemService(BluetoothManager::class.java)?.adapter?.bluetoothLeScanner
          ?: throw IllegalStateException()
        scanner!!.stopScan(BleWakeRegistrar.callbackIntent(context))
        scanner!!.stopScan(BleWakeRegistrar.callbackIntent(context, continuous = true))
        BleWakeRegistrar.pauseForAlternative(context)
      }
      override fun startAlternative() {
        scanner!!.startScan(emptyList(), ScanSettings.Builder()
          .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
          .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES).setReportDelay(0).build(), callback)
      }
      override fun stopAlternative() { scanner?.stopScan(callback) }
      override fun release() { lease?.close(); lease = null }
      override fun restore(): String = if (!BleWakeRegistrar.isEnabled(context)) "NOT_REQUESTED" else {
        val result = runCatching { BleWakeRegistrar.restoreAfterAlternative(context) }.getOrNull()
        if (result?.reconciled == true) "RESTORED" else "RESTORE_PENDING"
      }
    })
    session = current
    synchronized(BleForegroundDiscoveryStore) {
      val edit = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
        .putLong("last_attempt", System.currentTimeMillis())
      if (BleForegroundDiscoveryStore.visible(context, windowStartedAt))
        edit.putLong("alternativeStartedAtEpochMs", System.currentTimeMillis()).remove("alternativeFinishedAtEpochMs")
      edit.apply()
    }
    lastFlush = 0L
    current.start(eligible(context))
    persist(context, terminal = !current.active)
    if (current.active) {
      deadline = Runnable { synchronized(BleWakeRegistrar) {
        if (generation == token) finish(context, "NO_MATCHING_PACKET")
      } }
      handler.postDelayed(deadline!!, ForegroundDiscoverySession.WINDOW_MS)
    }
  }

  fun busy(): Boolean = session?.active == true

  fun cancel(context: Context, reason: String, restore: Boolean = true,
             radioDisabled: Boolean = false) = synchronized(BleWakeRegistrar) {
    ++generation
    pending?.let(handler::removeCallbacks)
    if (pending != null) BleForegroundDiscoveryStore.finishWaiting(context, windowStartedAt, reason)
    pending = null
    finish(context.applicationContext, reason, restore, radioDisabled)
  }

  private fun finish(context: Context, outcome: String, restore: Boolean = true, radioDisabled: Boolean = false) {
    if (session?.active != true) return
    session!!.finish(outcome, restore, radioDisabled)
    clearDeadline()
    persist(context, terminal = true)
  }

  private fun clearDeadline() { deadline?.let(handler::removeCallbacks); deadline = null }

  private fun persist(context: Context, terminal: Boolean) {
    val current = session ?: return
    val elapsed = SystemClock.elapsedRealtime()
    if (!terminal && lastFlush != 0L && elapsed - lastFlush < 2_000) return
    lastFlush = elapsed
    synchronized(BleForegroundDiscoveryStore) {
    if (!BleForegroundDiscoveryStore.visible(context, windowStartedAt)) return
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
      .putString("alternativeStage", current.stage)
      .putInt("alternativeResultCount", current.resultCount)
      .putInt("alternativeCandidateCount", current.candidateCount)
      .putInt("alternativeMatchCount", current.matchCount)
      .putInt("alternativeErrorCount", current.errorCount)
      .putInt("alternativeErrorCode", current.errorCode ?: -1)
      .putString("alternativeRestoreStatus", current.restoreStatus)
    if (terminal) p.putLong("alternativeFinishedAtEpochMs", System.currentTimeMillis())
    p.apply()
    }
    val journalWindow = windowStartedAt
    val journalStage = current.stage
    if (terminal || current.resultCount == 0) handler.post {
      if (BleForegroundDiscoveryStore.visible(context, journalWindow))
        NativeDiagnostics.record(context, NativeDiagnostics.Event.SCAN_REGISTRATION, "ALTERNATIVE_$journalStage")
    }
  }

  fun snapshot(context: Context): Map<String, Any?> {
    val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val stored = p.getString("alternativeStage", null)
    val stage = if (stored in setOf("SCANNING", "STOP_FAILED", "RELEASE_FAILED") && !busy()) "PROCESS_INTERRUPTED" else stored
    return mapOf("alternativeStage" to stage,
      "alternativeResultCount" to p.getInt("alternativeResultCount", 0),
      "alternativeCandidateCount" to p.getInt("alternativeCandidateCount", 0),
      "alternativeMatchCount" to p.getInt("alternativeMatchCount", 0),
      "alternativeErrorCount" to p.getInt("alternativeErrorCount", 0),
      "alternativeErrorCode" to p.getInt("alternativeErrorCode", -1).takeIf { it >= 0 },
      "alternativeStartedAtEpochMs" to p.getLong("alternativeStartedAtEpochMs", 0).takeIf { it > 0 },
      "alternativeFinishedAtEpochMs" to p.getLong("alternativeFinishedAtEpochMs", 0).takeIf { it > 0 },
      "alternativeRestoreStatus" to p.getString("alternativeRestoreStatus", null))
  }
}
