package com.kshouse.gatekeeper_app.blewake

import android.content.Context
import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler
import com.kshouse.gatekeeper_app.gattworker.AuthenticatedTargetLocatorStore

/**
 * I4 integration seam. This native entrypoint must stay independent of Flutter and OTA UI state.
 */
object BleWakeNativeEntrypoint {
  fun onWake(context: Context, event: BleWakeEvent) {
    val appContext = context.applicationContext
    BleWakeJournal.record(appContext, event)
    if (event.success) {
      event.deviceAddress?.let { AuthenticatedTargetLocatorStore(appContext).record(it) }
      BleGattWorkScheduler.onPresence(appContext, event.deviceAddress, event.presenceEventId())
    }
  }
}
