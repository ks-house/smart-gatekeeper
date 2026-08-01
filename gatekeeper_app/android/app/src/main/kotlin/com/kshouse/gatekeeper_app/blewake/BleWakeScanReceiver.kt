package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import java.util.UUID

class BleWakeScanReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != BleWakeRegistrar.ACTION_SCAN_RESULT) return
    val pendingResult = goAsync()
    try {
      val receivedElapsedNanos = SystemClock.elapsedRealtimeNanos()
      val results = scanResults(intent)
      val matchingResults = results.filter { result ->
        BleWakeContract.matchesManufacturerData(
          result.scanRecord?.getManufacturerSpecificData(BleWakeContract.APPLE_COMPANY_ID),
        )
      }
      val newestTimestamp = matchingResults.maxOfOrNull { it.timestampNanos }
      val errorCode = intent.getIntExtra(BluetoothLeScanner.EXTRA_ERROR_CODE, ScanCallbackError.NONE)
      val event = BleWakeEvent(
        source = "ble_scan",
        scenario = "field",
        iteration = null,
        success = errorCode == ScanCallbackError.NONE && matchingResults.isNotEmpty(),
        receivedEpochMs = System.currentTimeMillis(),
        receivedElapsedMs = SystemClock.elapsedRealtime(),
        scanTimestampNanos = newestTimestamp,
        latencyMs = newestTimestamp?.let {
          ((receivedElapsedNanos - it).coerceAtLeast(0L)) / 1_000_000.0
        },
        callbackType = intent.getIntExtra(BluetoothLeScanner.EXTRA_CALLBACK_TYPE, 0),
        errorCode = errorCode,
        resultCount = matchingResults.size,
        strongestRssi = matchingResults.maxOfOrNull { it.rssi },
        processId = PROCESS_ID,
        screenInteractive = context.getSystemService(PowerManager::class.java)?.isInteractive ?: true,
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
  }
}
