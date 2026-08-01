package com.kshouse.gatekeeper_app.blewake

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import java.util.UUID

/** Debug-only ADB seam for hardwareless receiver/journal/metrics verification. */
class BleWakeDebugCommandReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) {
    when (intent.getStringExtra(EXTRA_COMMAND)) {
      "register" -> Log.i(TAG, "debug register: ${BleWakeRegistrar.register(context).status}")
      "stop" -> Log.i(TAG, "debug stop: ${BleWakeRegistrar.stop(context).status}")
      "reset" -> BleWakeJournal.reset(context)
      "dump" -> BleWakeJournal.logDump(context)
      "inject" -> inject(context, intent)
      else -> Log.e(TAG, "unknown debug command")
    }
  }

  private fun inject(context: Context, intent: Intent) {
    val latencyMs = intent.getLongExtra(EXTRA_LATENCY_MS, 0L).toDouble()
    val success = intent.getBooleanExtra(EXTRA_SUCCESS, true)
    val nowElapsedMs = SystemClock.elapsedRealtime()
    BleWakeNativeEntrypoint.onWake(
      context,
      BleWakeEvent(
        source = "synthetic",
        scenario = intent.getStringExtra(EXTRA_SCENARIO) ?: "hardwareless",
        iteration = intent.getIntExtra(EXTRA_ITERATION, -1).takeIf { it >= 0 },
        success = success,
        receivedEpochMs = System.currentTimeMillis(),
        receivedElapsedMs = nowElapsedMs,
        scanTimestampNanos = null,
        latencyMs = latencyMs,
        callbackType = 0,
        errorCode = if (success) 0 else 1,
        resultCount = if (success) 1 else 0,
        strongestRssi = if (success) -55 else null,
        processId = PROCESS_ID,
        screenInteractive = context.getSystemService(PowerManager::class.java)?.isInteractive ?: true,
      ),
    )
  }

  companion object {
    const val ACTION = "com.kshouse.gatekeeper_app.blewake.DEBUG_COMMAND"
    const val EXTRA_COMMAND = "command"
    const val EXTRA_SCENARIO = "scenario"
    const val EXTRA_ITERATION = "iteration"
    const val EXTRA_LATENCY_MS = "latency_ms"
    const val EXTRA_SUCCESS = "success"
    private const val TAG = "BLE_WAKE_POC"
    private val PROCESS_ID = UUID.randomUUID().toString()
  }
}
