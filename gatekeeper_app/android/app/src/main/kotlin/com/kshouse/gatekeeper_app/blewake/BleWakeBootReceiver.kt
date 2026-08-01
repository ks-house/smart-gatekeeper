package com.kshouse.gatekeeper_app.blewake

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class BleWakeBootReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (
      intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED) ||
      !BleWakeRegistrar.isEnabled(context)
    ) return
    val result = BleWakeRegistrar.register(context)
    Log.i("BLE_WAKE_POC", "${intent.action} registration: ${result.status}")
  }
}
