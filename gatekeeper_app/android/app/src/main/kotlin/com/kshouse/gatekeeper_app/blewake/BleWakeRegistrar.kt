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
import com.flutterbeacon.CrossProcessBleOwnerCoordinator
import java.util.UUID

data class BleWakeRegistrationResult(
  val status: String,
  val errorCode: Int? = null,
  val requested: Boolean = false,
  val reconciled: Boolean = false,
  val attemptedAtEpochMs: Long? = null,
  val reconciledAtEpochMs: Long? = null,
  val lastCallbackAtEpochMs: Long? = null,
) {
  val enabled: Boolean
    get() = reconciled

  val succeeded: Boolean
    get() = status == "registered" || status == "stopped"

  fun toMap(): Map<String, Any?> = mapOf(
    "status" to status,
    "errorCode" to errorCode,
    "requested" to requested,
    "reconciled" to reconciled,
    "registered" to reconciled,
    "attemptedAtEpochMs" to attemptedAtEpochMs,
    "reconciledAtEpochMs" to reconciledAtEpochMs,
    "lastCallbackAtEpochMs" to lastCallbackAtEpochMs,
    "nextAction" to when {
      reconciled -> "none"
      status.startsWith("missing_permission") -> "grant_permission"
      status == "bluetooth_off_or_scanner_unavailable" -> "enable_bluetooth"
      requested -> "reconcile_registration"
      else -> "retry"
    },
  )
}

object BleWakeRegistrar {
  const val ACTION_SCAN_RESULT = "com.kshouse.gatekeeper_app.blewake.SCAN_RESULT"
  private const val PREFS = "ble_wake_poc"
  private const val KEY_ENABLED = "registration_enabled"
  private const val KEY_RECONCILED = "registration_reconciled"
  private const val KEY_RECONCILED_PROCESS_ID = "registration_reconciled_process_id"
  private const val KEY_LAST_STATUS = "registration_last_status"
  private const val KEY_LAST_ERROR_CODE = "registration_last_error_code"
  private const val KEY_ATTEMPTED_AT = "registration_attempted_at_epoch_ms"
  private const val KEY_RECONCILED_AT = "registration_reconciled_at_epoch_ms"
  private const val KEY_LAST_CALLBACK_AT = "registration_callback_at_epoch_ms"
  private const val REQUEST_CODE = 1414
  private val processId = UUID.randomUUID().toString()

  @Synchronized
  fun register(context: Context): BleWakeRegistrationResult {
    val result = registerOnce(context)
    if (result.reconciled) {
      BleWakeReconciliationScheduler.cancel(context)
    } else {
      BleWakeReconciliationScheduler.scheduleIfRetryable(context, result)
    }
    return result
  }

  @Synchronized
  internal fun reconcileRequestedWithoutScheduling(context: Context): BleWakeRegistrationResult {
    val evidence = readEvidence(context)
    if (!evidence.requested) {
      return result(evidence.copy(status = "not_registered"))
    }
    return registerOnce(context)
  }

  private fun registerOnce(context: Context): BleWakeRegistrationResult {
    // Persist user intent before touching the adapter. A Bluetooth-OFF attempt
    // must remain eligible for restoration when the adapter later reaches ON.
    val attempt = BleWakeReconciliationPolicy.begin(
      readEvidence(context).copy(requested = true),
      processId,
      System.currentTimeMillis(),
    )
    writeEvidence(context, attempt)
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return fail(context, attempt, "unsupported_api")
    }
    val missingPermission = missingPermission(context)
    if (missingPermission != null) {
      return fail(context, attempt, "missing_permission:$missingPermission")
    }

    return try {
      val manager = context.getSystemService(BluetoothManager::class.java)
      val adapter = manager?.adapter ?: return fail(context, attempt, "bluetooth_unavailable")
      val scanner = adapter.bluetoothLeScanner
        ?: return fail(context, attempt, "bluetooth_off_or_scanner_unavailable")
      val nativeLease = CrossProcessBleOwnerCoordinator.forContext(context).tryAcquireNative()
        ?: return fail(context, attempt, "native_owner_unavailable")
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
      nativeLease.use {
        val callbackIntent = callbackIntent(context)
        // Reconcile to one exact PendingIntent registration only while legacy
        // has fully released the cross-process lease. The durable native owner
        // marker prevents a new legacy lease after this temporary lock closes.
        scanner.stopScan(callbackIntent)
        val errorCode = scanner.startScan(listOf(filter), settings, callbackIntent)
        if (errorCode == 0) {
          val accepted = BleWakeReconciliationPolicy.accept(
            attempt,
            processId,
            System.currentTimeMillis(),
          )
          writeEvidence(context, accepted)
          result(accepted)
        } else {
          fail(context, attempt, "scan_error", errorCode)
        }
      }
    } catch (_: SecurityException) {
      fail(context, attempt, "security_exception")
    } catch (_: IllegalStateException) {
      fail(context, attempt, "illegal_state")
    }
  }

  @Synchronized
  fun stop(context: Context): BleWakeRegistrationResult {
    // Disable semantics are durable even when the adapter/permission prevents
    // the best-effort platform stop call.
    val stopped = BleWakeReconciliationPolicy.stop(readEvidence(context), processId)
    writeEvidence(context, stopped)
    BleWakeReconciliationScheduler.cancel(context)
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return result(stopped)
    }
    return try {
      val scanner = context.getSystemService(BluetoothManager::class.java)
        ?.adapter
        ?.bluetoothLeScanner
      if (scanner != null) scanner.stopScan(callbackIntent(context))
      result(stopped)
    } catch (_: SecurityException) {
      // The durable request is already disabled. Report the platform stop
      // failure without ever restoring reconciliation evidence.
      val failedStop = stopped.copy(status = "stop_security_exception")
      writeEvidence(context, failedStop)
      result(failedStop)
    }
  }

  fun isEnabled(context: Context): Boolean = context
    .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    .getBoolean(KEY_ENABLED, false)

  @Synchronized
  fun status(context: Context): BleWakeRegistrationResult {
    var evidence = readEvidence(context)
    if (!evidence.requested) return result(evidence.copy(status = "not_registered"))
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
      return invalidate(context, "unsupported_api")
    }
    val missingPermission = missingPermission(context)
    if (missingPermission != null) {
      return invalidate(context, "missing_permission:$missingPermission")
    }
    try {
      val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
        ?: return invalidate(context, "bluetooth_unavailable")
      if (!adapter.isEnabled || adapter.bluetoothLeScanner == null) {
        return invalidate(context, "bluetooth_off_or_scanner_unavailable")
      }
    } catch (_: SecurityException) {
      return invalidate(context, "security_exception")
    }
    evidence = readEvidence(context)
    if (!BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(evidence, processId)) {
      val unresolvedStatus = evidence.status.takeUnless {
        it == "registered" || it == "stopped" || it == "not_registered"
      } ?: "reconciliation_required"
      return result(evidence.copy(status = unresolvedStatus, reconciled = false))
    }
    return result(evidence.copy(status = "registered"))
  }

  @Synchronized
  fun invalidateReconciliation(context: Context, status: String): BleWakeRegistrationResult =
    invalidate(context, status)

  @Synchronized
  fun recordScanCallback(
    context: Context,
    errorCode: Int,
  ): BleWakeRegistrationResult {
    val evidence = readEvidence(context)
    if (!evidence.requested) return result(evidence.copy(status = "not_registered"))
    val updated = BleWakeReconciliationPolicy.recordCallback(
      evidence,
      processId,
      errorCode,
      System.currentTimeMillis(),
    )
    writeEvidence(context, updated)
    val registration = result(updated)
    if (errorCode != 0) {
      BleWakeReconciliationScheduler.scheduleIfRetryable(context, registration)
    }
    return registration
  }

  internal fun callbackIntent(context: Context): PendingIntent {
    val intent = Intent(context, BleWakeScanReceiver::class.java).setAction(ACTION_SCAN_RESULT)
    // BluetoothLeScanner must add ScanResult extras at delivery time. Android 12+
    // therefore needs a mutable PendingIntent; the explicit non-exported receiver
    // and fixed action constrain the mutable surface.
    val flags = PendingIntent.FLAG_UPDATE_CURRENT or
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
    return PendingIntent.getBroadcast(context, REQUEST_CODE, intent, flags)
  }

  private fun fail(
    context: Context,
    previous: BleWakeReconciliationEvidence,
    status: String,
    errorCode: Int? = null,
  ): BleWakeRegistrationResult {
    val failed = BleWakeReconciliationPolicy.fail(previous, processId, status, errorCode)
    writeEvidence(context, failed)
    return result(failed)
  }

  private fun invalidate(context: Context, status: String): BleWakeRegistrationResult {
    val previous = readEvidence(context)
    val shouldSchedule = BleWakeReconciliationRetryPolicy.shouldScheduleInvalidation(
      previous,
      processId,
      status,
    )
    val invalidated = fail(context, previous, status)
    // Health reads can be the first observer of a transient adapter/scanner
    // loss. Schedule only its first state transition: one-second health polling
    // must not create an unbounded sequence of otherwise bounded work chains.
    if (shouldSchedule) {
      BleWakeReconciliationScheduler.scheduleIfRetryable(context, invalidated)
    }
    return invalidated
  }

  private fun result(evidence: BleWakeReconciliationEvidence): BleWakeRegistrationResult =
    BleWakeRegistrationResult(
      status = evidence.status,
      errorCode = evidence.errorCode,
      requested = evidence.requested,
      reconciled = BleWakeReconciliationPolicy.isAcceptedForCurrentProcess(evidence, processId),
      attemptedAtEpochMs = evidence.attemptedAtEpochMs,
      reconciledAtEpochMs = evidence.reconciledAtEpochMs,
      lastCallbackAtEpochMs = evidence.lastCallbackAtEpochMs,
    )

  private fun readEvidence(context: Context): BleWakeReconciliationEvidence {
    val preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    return BleWakeReconciliationEvidence(
      requested = preferences.getBoolean(KEY_ENABLED, false),
      reconciled = preferences.getBoolean(KEY_RECONCILED, false),
      reconciledProcessId = preferences.getString(KEY_RECONCILED_PROCESS_ID, null),
      status = preferences.getString(KEY_LAST_STATUS, null) ?: "not_registered",
      attemptedAtEpochMs = preferences.optionalLong(KEY_ATTEMPTED_AT),
      reconciledAtEpochMs = preferences.optionalLong(KEY_RECONCILED_AT),
      lastCallbackAtEpochMs = preferences.optionalLong(KEY_LAST_CALLBACK_AT),
      errorCode = preferences.optionalInt(KEY_LAST_ERROR_CODE),
    )
  }

  private fun writeEvidence(context: Context, evidence: BleWakeReconciliationEvidence) {
    val editor = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .edit()
      .putBoolean(KEY_ENABLED, evidence.requested)
      .putBoolean(KEY_RECONCILED, evidence.reconciled)
      .putString(KEY_RECONCILED_PROCESS_ID, evidence.reconciledProcessId)
      .putString(KEY_LAST_STATUS, evidence.status)
    editor.putOptionalLong(KEY_ATTEMPTED_AT, evidence.attemptedAtEpochMs)
    editor.putOptionalLong(KEY_RECONCILED_AT, evidence.reconciledAtEpochMs)
    editor.putOptionalLong(KEY_LAST_CALLBACK_AT, evidence.lastCallbackAtEpochMs)
    editor.putOptionalInt(KEY_LAST_ERROR_CODE, evidence.errorCode)
    editor.commit()
  }

  private fun android.content.SharedPreferences.optionalLong(key: String): Long? =
    if (contains(key)) getLong(key, 0L) else null

  private fun android.content.SharedPreferences.optionalInt(key: String): Int? =
    if (contains(key)) getInt(key, 0) else null

  private fun android.content.SharedPreferences.Editor.putOptionalLong(
    key: String,
    value: Long?,
  ) {
    if (value == null) remove(key) else putLong(key, value)
  }

  private fun android.content.SharedPreferences.Editor.putOptionalInt(
    key: String,
    value: Int?,
  ) {
    if (value == null) remove(key) else putInt(key, value)
  }

  private fun missingPermission(context: Context): String? {
    fun missing(permission: String): Boolean =
      context.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED

    return when {
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && missing(Manifest.permission.BLUETOOTH_SCAN) ->
        Manifest.permission.BLUETOOTH_SCAN
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && missing(Manifest.permission.BLUETOOTH_CONNECT) ->
        Manifest.permission.BLUETOOTH_CONNECT
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
