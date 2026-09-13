package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.os.ParcelUuid
import com.kshouse.gatekeeper_app.gattworker.GattProtocol
import java.util.UUID
import com.kshouse.gatekeeper_app.gattworker.BleGattRuntimeEnvironment

class BleWakeScanReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != BleWakeRegistrar.ACTION_SCAN_RESULT) return
    val pendingResult = goAsync()
    try {
      val receivedElapsedNanos = SystemClock.elapsedRealtimeNanos()
      val receivedEpochMs = System.currentTimeMillis()
      val results = scanResults(intent)
      val matchingResults = results.filter { result ->
        BleWakeContract.matchesManufacturerData(
          result.scanRecord?.getManufacturerSpecificData(BleWakeContract.APPLE_COMPANY_ID),
        )
      }
      val errorCode = intent.getIntExtra(BluetoothLeScanner.EXTRA_ERROR_CODE, ScanCallbackError.NONE)
      val callbackType = intent.getIntExtra(BluetoothLeScanner.EXTRA_CALLBACK_TYPE, 0)
      // A strong stale entry in an OS batch must not hide a weaker fresh packet.
      val selected = BleScanObservationPolicy.selectMatching(matchingResults,
        { BleScanObservationPolicy.ageMs(it.timestampNanos, receivedElapsedNanos) },
        { it.rssi }, { it.timestampNanos })
      val newestTimestamp = selected?.timestampNanos
      val hintBytes = selected?.scanRecord?.getServiceData(ParcelUuid(GattProtocol.SERVICE_UUID))
      BleScanDiagnostics.callback(context.applicationContext, errorCode, callbackType,
        results.size, matchingResults.map { result ->
          BleScanObservationPolicy.ageMs(result.timestampNanos, receivedElapsedNanos) to
            BleScanObservationPolicy.hint(result.scanRecord?.getServiceData(ParcelUuid(GattProtocol.SERVICE_UUID)))
        }, receivedEpochMs)
      // Packet callbacks can arrive ten times a second. Keep registration
      // evidence bounded instead of synchronously committing preferences per packet.
      if (errorCode != 0 || callbackType != 1 ||
        SystemClock.elapsedRealtime() - lastContinuousRecordMs >= 2_000) {
        lastContinuousRecordMs = SystemClock.elapsedRealtime()
        BleWakeRegistrar.recordScanCallback(context.applicationContext, errorCode)
      }
      val event = BleWakeEvent(
        source = "ble_scan",
        scenario = "field",
        iteration = null,
        success = errorCode == ScanCallbackError.NONE && matchingResults.isNotEmpty(),
        receivedEpochMs = receivedEpochMs,
        receivedElapsedMs = receivedElapsedNanos / 1_000_000L,
        scanTimestampNanos = newestTimestamp,
        latencyMs = newestTimestamp?.let { BleScanObservationPolicy.ageMs(it, receivedElapsedNanos) },
        callbackType = callbackType,
        errorCode = errorCode,
        resultCount = matchingResults.size,
        strongestRssi = selected?.rssi,
        processId = PROCESS_ID,
        screenInteractive = context.getSystemService(PowerManager::class.java)?.isInteractive ?: true,
        deviceAddress = try {
          selected?.device?.address
        } catch (_: SecurityException) {
          BleGattRuntimeEnvironment.recordBlocked(context, "PERMISSION_DENIED")
          null
        },
        readyHint = PresenceReadyHint.parse(hintBytes),
        readyHintMalformed = BleScanObservationPolicy.hint(hintBytes) == BleScanObservationPolicy.Hint.MALFORMED,
      )
      BleWakeNativeEntrypoint.onWake(context, event)
    } finally {
      pendingResult.finish()
    }
  }

  @Suppress("DEPRECATION")
  private fun scanResults(intent: Intent): List<ScanResult> =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      intent.getParcelableArrayListExtra(
        BluetoothLeScanner.EXTRA_LIST_SCAN_RESULT,
        ScanResult::class.java,
      ).orEmpty()
    } else {
      intent.getParcelableArrayListExtra<ScanResult>(
        BluetoothLeScanner.EXTRA_LIST_SCAN_RESULT,
      ).orEmpty()
    }

  private object ScanCallbackError {
    const val NONE = 0
  }

  companion object {
    private val PROCESS_ID = UUID.randomUUID().toString()
    private var lastContinuousRecordMs = 0L
  }
}
