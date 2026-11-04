package com.kshouse.gatekeeper_app.blewake

import android.app.Activity
import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.util.Log
import java.util.Collections
import java.util.IdentityHashMap

/** Process-lifetime registration repair, independent of Flutter's Activity channel. */
internal object BleWakeLifecycleMonitor {
  private var started = false
  private val activities = Collections.newSetFromMap(IdentityHashMap<Activity, Boolean>())

  @Synchronized fun start(application: Application) {
    if (started) return
    started = true
    application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
      override fun onActivityStarted(activity: Activity) { activities.add(activity) }
      override fun onActivityStopped(activity: Activity) {
        if (activities.remove(activity) && activities.isEmpty()) {
          // Activity-stop also occurs for Home and screen locking. It is not
          // evidence that the user swiped a recent task or force-stopped the app.
          BleWakeReconciliationScheduler.scheduleLifecycle(application, BleScanRecoveryReason.APP_BACKGROUND)
        }
      }
      override fun onActivityCreated(activity: Activity, state: Bundle?) {}
      override fun onActivityResumed(activity: Activity) {}
      override fun onActivityPaused(activity: Activity) {}
      override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) {}
      override fun onActivityDestroyed(activity: Activity) { activities.remove(activity) }
    })
    val screenReceiver = object : BroadcastReceiver() {
      override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_SCREEN_OFF) {
          BleWakeReconciliationScheduler.scheduleLifecycle(application, BleScanRecoveryReason.SCREEN_OFF)
        }
      }
    }
    try {
      val filter = IntentFilter(Intent.ACTION_SCREEN_OFF)
      if (Build.VERSION.SDK_INT >= 33) application.registerReceiver(screenReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
      else {
        @Suppress("DEPRECATION")
        application.registerReceiver(screenReceiver, filter)
      }
    } catch (error: RuntimeException) {
      Log.w("BLE_WAKE_POC", "screen lifecycle monitor unavailable: ${error.javaClass.simpleName}")
    }
    BleWakeReconciliationScheduler.scheduleLifecycle(application, BleScanRecoveryReason.PROCESS_START)
  }
}
