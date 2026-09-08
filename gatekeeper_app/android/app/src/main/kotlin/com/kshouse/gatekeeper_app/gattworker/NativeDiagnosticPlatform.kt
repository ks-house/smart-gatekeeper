package com.kshouse.gatekeeper_app.gattworker

import android.app.ActivityManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.Build
import android.os.PowerManager

/** Closed OS metadata only. Never read exit trace streams, descriptions or process names. */
internal object NativeDiagnosticPlatform {
  fun snapshot(context: Context): Map<String, Any?> {
    val activity = context.getSystemService(ActivityManager::class.java)
    val power = context.getSystemService(PowerManager::class.java)
    val exit = if (Build.VERSION.SDK_INT >= 30) runCatching {
      activity?.getHistoricalProcessExitReasons(context.packageName, 0, 1)?.firstOrNull()
    }.getOrNull() else null
    return mapOf(
      "background_restricted" to if (Build.VERSION.SDK_INT >= 28) runCatching { activity?.isBackgroundRestricted }.getOrNull() else null,
      "battery_optimization_exempt" to runCatching { power?.isIgnoringBatteryOptimizations(context.packageName) }.getOrNull(),
      "device_idle" to runCatching { power?.isDeviceIdleMode }.getOrNull(),
      "app_standby_bucket" to if (Build.VERSION.SDK_INT >= 28) runCatching {
        context.getSystemService(UsageStatsManager::class.java)?.appStandbyBucket
      }.getOrNull() else null,
      "previous_exit_reason" to if (Build.VERSION.SDK_INT >= 30) exit?.reason else null,
      "previous_exit_epoch_ms" to if (Build.VERSION.SDK_INT >= 30) exit?.timestamp else null,
      "last_start_was_force_stopped" to if (Build.VERSION.SDK_INT >= 35) runCatching {
        activity?.getHistoricalProcessStartReasons(1)?.firstOrNull()?.wasForceStopped()
      }.getOrNull() else null,
    )
  }
}
