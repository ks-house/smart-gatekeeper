package com.kshouse.gatekeeper_app

import android.app.Application
import com.kshouse.gatekeeper_app.blewake.BleWakeBluetoothStateMonitor
import com.kshouse.gatekeeper_app.gattworker.AccessResultNotifier

/**
 * Process-lifetime native initialization that stays independent of Flutter UI state.
 */
class GatekeeperApplication : Application() {
  override fun onCreate() {
    super.onCreate()
    BleWakeBluetoothStateMonitor.start(this)
    AccessResultNotifier.createChannel(this)
  }
}
