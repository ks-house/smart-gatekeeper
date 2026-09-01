package com.kshouse.gatekeeper_app.blewake

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.kshouse.gatekeeper_app.gattworker.BleGattFeatureFlagStore

class BleWakeBootReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    if (
      intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED) ||
      !BleWakeRegistrar.isEnabled(context)
    ) return
    BleWakeRegistrar.invalidateReconciliation(
      context,
      if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
        "package_replaced_reconciliation_required"
      } else {
        "boot_reconciliation_required"
      },
    )
    val result = BleGattFeatureFlagStore(context).reconcileWakeRegistration()
    Log.i("BLE_WAKE_POC", "${intent.action} registration: ${result.status}")
  }
}
