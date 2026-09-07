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
      val results = scanResults(intent)
      val matchingResults = results.filter { result ->
        BleWakeContract.matchesManufacturerData(
          result.scanRecord?.getManufacturerSpecificData(BleWakeContract.APPLE_COMPANY_ID),
        )
      }
      val selected = matchingResults.maxByOrNull { it.rssi }
      val newestTimestamp = selected?.timestampNanos
      val errorCode = intent.getIntExtra(BluetoothLeScanner.EXTRA_ERROR_CODE, ScanCallbackError.NONE)
      val callbackType = intent.getIntExtra(BluetoothLeScanner.EXTRA_CALLBACK_TYPE, 0)
      // MATCH_LOST and error callbacks are not positive packet reception.
      if (BleScanDiagnostics.isPacketObservation(errorCode, callbackType, matchingResults.size)) {
        BleScanDiagnostics.packet(context.applicationContext)
      }
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
        receivedEpochMs = System.currentTimeMillis(),
        receivedElapsedMs = SystemClock.elapsedRealtime(),
        scanTimestampNanos = newestTimestamp,
        latencyMs = newestTimestamp?.let {
          ((receivedElapsedNanos - it).coerceAtLeast(0L)) / 1_000_000.0
        },
        callbackType = callbackType,
        errorCode = errorCode,
        resultCount = matchingResults.size,
        strongestRssi = matchingResults.maxOfOrNull { it.rssi },
        processId = PROCESS_ID,
        screenInteractive = context.getSystemService(PowerManager::class.java)?.isInteractive ?: true,
        deviceAddress = try {
          selected?.device?.address
        } catch (_: SecurityException) {
          BleGattRuntimeEnvironment.recordBlocked(context, "PERMISSION_DENIED")
          null
        },
        readyHint = PresenceReadyHint.parse(
          selected?.scanRecord?.getServiceData(ParcelUuid(GattProtocol.SERVICE_UUID)),
        ),
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
