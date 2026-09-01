package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.util.Log
import com.kshouse.gatekeeper_app.gattworker.BleGattFeatureFlagStore

object BleWakeBluetoothRestorePolicy {
  fun shouldRestore(
    action: String?,
    newState: Int,
    previousObservedState: Int?,
    registrationRequested: Boolean,
  ): Boolean =
    action == BluetoothAdapter.ACTION_STATE_CHANGED &&
      registrationRequested &&
      newState == BluetoothAdapter.STATE_ON &&
      previousObservedState != BluetoothAdapter.STATE_ON
}

/**
 * Restores the OS-managed PendingIntent scan after Bluetooth returns to ON.
 *
 * ACTION_STATE_CHANGED is not a manifest implicit-broadcast exception on modern
 * Android. Registering for the process lifetime keeps this path native while the
 * app's foreground service keeps the process alive. The broadcast is protected
 * by the platform and never dispatches an access action directly.
 */
object BleWakeBluetoothStateMonitor {
  private const val TAG = "BLE_WAKE_POC"
  private var started = false
  private var previousObservedState: Int? = null

  private val receiver = object : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
      val newState = intent.getIntExtra(
        BluetoothAdapter.EXTRA_STATE,
        BluetoothAdapter.ERROR,
      )
      handleState(context.applicationContext, intent.action, newState)
    }
  }

  @Synchronized
  fun start(context: Context) {
    if (started) return
    val appContext = context.applicationContext
    val currentState = currentAdapterState(appContext)
    previousObservedState = currentState
    try {
      val filter = IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED)
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        // Bluetooth broadcasts can originate from the privileged Bluetooth app,
        // not only the system UID. The action itself is platform-protected.
        appContext.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
      } else {
        @Suppress("DEPRECATION")
        appContext.registerReceiver(receiver, filter)
      }
      started = true
    } catch (error: RuntimeException) {
      Log.w(TAG, "Bluetooth state monitor registration failed: ${error.javaClass.simpleName}")
    }

    val wakeRequested = BleWakeRegistrar.isEnabled(appContext)
    val featureEnabled = wakeRequested &&
      BleGattFeatureFlagStore(appContext).decision().newWorkerEnabled
    if (featureEnabled && currentState != BluetoothAdapter.STATE_ON) {
      BleWakeRegistrar.invalidateReconciliation(
        appContext,
        if (currentState == null) {
          "bluetooth_unavailable"
        } else {
          "bluetooth_off_or_scanner_unavailable"
        },
      )
    }

    if (
      BleWakeBluetoothRestorePolicy.shouldRestore(
        BluetoothAdapter.ACTION_STATE_CHANGED,
        currentState ?: BluetoothAdapter.ERROR,
        null,
        featureEnabled && BleWakeRegistrar.isEnabled(appContext),
      )
    ) {
      restore(appContext, "process_start")
    }
  }

  @Synchronized
  private fun handleState(context: Context, action: String?, newState: Int) {
    if (action != BluetoothAdapter.ACTION_STATE_CHANGED) return
    val oldState = previousObservedState
    previousObservedState = newState
    val wakeRequested = BleWakeRegistrar.isEnabled(context)
    val featureEnabled = wakeRequested &&
      BleGattFeatureFlagStore(context).decision().newWorkerEnabled
    if (newState != BluetoothAdapter.STATE_ON && featureEnabled) {
      BleWakeRegistrar.invalidateReconciliation(
        context,
        "bluetooth_off_or_scanner_unavailable",
      )
    }
    if (
      !BleWakeBluetoothRestorePolicy.shouldRestore(
        action,
        newState,
        oldState,
        featureEnabled && BleWakeRegistrar.isEnabled(context),
      )
    ) return
    restore(context, "bluetooth_state_on")
  }

  private fun restore(context: Context, source: String) {
    val result = BleGattFeatureFlagStore(context).reconcileWakeRegistration()
    val message = "$source registration restore: ${result.status}" +
      (result.errorCode?.let { " ($it)" } ?: "")
    if (result.succeeded) {
      Log.i(TAG, message)
    } else {
      Log.w(TAG, message)
    }
  }

  private fun currentAdapterState(context: Context): Int? = try {
    context.getSystemService(BluetoothManager::class.java)?.adapter?.state
  } catch (_: SecurityException) {
    null
  }
}
