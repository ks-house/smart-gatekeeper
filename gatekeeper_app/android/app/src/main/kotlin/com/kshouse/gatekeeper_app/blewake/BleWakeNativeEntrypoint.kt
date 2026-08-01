package com.kshouse.gatekeeper_app.blewake

import android.content.Context

/**
 * I4 integration seam. This native entrypoint must stay independent of Flutter and OTA UI state.
 */
object BleWakeNativeEntrypoint {
  fun onWake(context: Context, event: BleWakeEvent) {
    BleWakeJournal.record(context.applicationContext, event)
  }
}
