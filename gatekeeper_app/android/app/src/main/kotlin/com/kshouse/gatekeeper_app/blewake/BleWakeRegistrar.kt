package com.kshouse.gatekeeper_app.blewake

import android.Manifest
import android.app.PendingIntent
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

data class BleWakeRegistrationResult(
  val status: String,
  val errorCode: Int? = null,
) {
  val succeeded: Boolean
    get() = status == "registered" || status == "stopped"

  fun toMap(): Map<String, Any?> = mapOf(
    "status" to status,
    "errorCode" to errorCode,
    "registered" to (status == "registered"),
  )
}

object BleWakeRegistrar {
  const val ACTION_SCAN_RESULT = "com.kshouse.gatekeeper_app.blewake.SCAN_RESULT"
  private const val PREFS = "ble_wake_poc"
  private const val KEY_ENABLED = "registration_enabled"
  private const val REQUEST_CODE = 1414

  fun register(context: Context): BleWakeRegistrationResult {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return BleWakeRegistrationResult("unsupported_api")
    }
    val missingPermission = missingPermission(context)
    if (missingPermission != null) {
      return BleWakeRegistrationResult("missing_permission:$missingPermission")
    }

    return try {
      val manager = context.getSystemService(BluetoothManager::class.java)
      val adapter = manager?.adapter ?: return BleWakeRegistrationResult("bluetooth_unavailable")
      val scanner = adapter.bluetoothLeScanner
        ?: return BleWakeRegistrationResult("bluetooth_off_or_scanner_unavailable")
      val filter = ScanFilter.Builder()
        .setManufacturerData(
          BleWakeContract.APPLE_COMPANY_ID,
          BleWakeContract.manufacturerDataPrefix,
          BleWakeContract.manufacturerDataMask,
        )
        .build()
      val settings = ScanSettings.Builder()
        .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER)
        .setCallbackType(ScanSettings.CALLBACK_TYPE_FIRST_MATCH)
        .setMatchMode(ScanSettings.MATCH_MODE_AGGRESSIVE)
        .setNumOfMatches(ScanSettings.MATCH_NUM_ONE_ADVERTISEMENT)
        .build()
      val errorCode = scanner.startScan(listOf(filter), settings, callbackIntent(context))
      if (errorCode == 0) {
        setEnabled(context, true)
        BleWakeRegistrationResult("registered", errorCode)
      } else {
        BleWakeRegistrationResult("scan_error", errorCode)
      }
    } catch (_: SecurityException) {
      BleWakeRegistrationResult("security_exception")
    } catch (_: IllegalStateException) {
      BleWakeRegistrationResult("illegal_state")
    }
  }

  fun stop(context: Context): BleWakeRegistrationResult {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      setEnabled(context, false)
      return BleWakeRegistrationResult("unsupported_api")
    }
    return try {
      val scanner = context.getSystemService(BluetoothManager::class.java)
        ?.adapter
        ?.bluetoothLeScanner
      if (scanner != null) scanner.stopScan(callbackIntent(context))
      setEnabled(context, false)
      BleWakeRegistrationResult("stopped")
    } catch (_: SecurityException) {
      BleWakeRegistrationResult("security_exception")
    }
  }

  fun isEnabled(context: Context): Boolean = context
    .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    .getBoolean(KEY_ENABLED, false)

  internal fun callbackIntent(context: Context): PendingIntent {
    val intent = Intent(context, BleWakeScanReceiver::class.java).setAction(ACTION_SCAN_RESULT)
    // BluetoothLeScanner must add ScanResult extras at delivery time. Android 12+
    // therefore needs a mutable PendingIntent; the explicit non-exported receiver
    // and fixed action constrain the mutable surface.
    val flags = PendingIntent.FLAG_UPDATE_CURRENT or
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
    return PendingIntent.getBroadcast(context, REQUEST_CODE, intent, flags)
  }

  private fun setEnabled(context: Context, value: Boolean) {
    context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .edit()
      .putBoolean(KEY_ENABLED, value)
      .commit()
  }

  private fun missingPermission(context: Context): String? {
    fun missing(permission: String): Boolean =
      context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED

    return when {
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && missing(Manifest.permission.BLUETOOTH_SCAN) ->
        Manifest.permission.BLUETOOTH_SCAN
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && missing(Manifest.permission.ACCESS_FINE_LOCATION) ->
        Manifest.permission.ACCESS_FINE_LOCATION
      Build.VERSION.SDK_INT in Build.VERSION_CODES.Q..Build.VERSION_CODES.R &&
        missing(Manifest.permission.ACCESS_BACKGROUND_LOCATION) ->
        Manifest.permission.ACCESS_BACKGROUND_LOCATION
      Build.VERSION.SDK_INT < Build.VERSION_CODES.Q && missing(Manifest.permission.ACCESS_COARSE_LOCATION) ->
        Manifest.permission.ACCESS_COARSE_LOCATION
      else -> null
    }
  }
}
