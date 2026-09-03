package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.le.ScanSettings
import android.content.Context
import com.kshouse.gatekeeper_app.gattworker.AccessResultNotifier
import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler
import com.kshouse.gatekeeper_app.gattworker.AuthenticatedTargetLocatorStore

enum class BleWakeDispatchAction {
  PRESENCE,
  EXIT,
  IGNORE,
}

object BleWakeDispatchPolicy {
  fun classify(event: BleWakeEvent): BleWakeDispatchAction = when {
    event.errorCode != 0 -> BleWakeDispatchAction.IGNORE
    event.callbackType and ScanSettings.CALLBACK_TYPE_MATCH_LOST != 0 ->
      BleWakeDispatchAction.EXIT
    event.success -> BleWakeDispatchAction.PRESENCE
    else -> BleWakeDispatchAction.IGNORE
  }
}

/**
 * I4 integration seam. This native entrypoint must stay independent of Flutter and OTA UI state.
 */
object BleWakeNativeEntrypoint {
  fun onWake(context: Context, event: BleWakeEvent) {
    val appContext = context.applicationContext
    when (BleWakeDispatchPolicy.classify(event)) {
      BleWakeDispatchAction.EXIT -> {
        BleWakeJournal.record(
          appContext,
          event.copy(source = "ble_scan_exit", success = false),
        )
        AccessResultNotifier.dismiss(appContext)
      }
      BleWakeDispatchAction.PRESENCE -> {
        BleWakeJournal.record(appContext, event)
        event.deviceAddress?.let { AuthenticatedTargetLocatorStore(appContext).record(it) }
        BleGattWorkScheduler.onPresence(appContext, event.deviceAddress, event.presenceEventId())
      }
      BleWakeDispatchAction.IGNORE -> BleWakeJournal.record(appContext, event)
    }
  }
}
