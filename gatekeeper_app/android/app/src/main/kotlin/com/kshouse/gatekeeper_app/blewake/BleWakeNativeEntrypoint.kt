package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.le.ScanSettings
import android.content.Context
import com.kshouse.gatekeeper_app.gattworker.AccessResultNotifier
import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler
import com.kshouse.gatekeeper_app.gattworker.AuthenticatedTargetLocatorStore
import com.kshouse.gatekeeper_app.gattworker.NativeDiagnostics

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
    event.success && event.resultCount > 0 &&
      BleScanObservationPolicy.positiveCallback(event.errorCode, event.callbackType) -> BleWakeDispatchAction.PRESENCE
    else -> BleWakeDispatchAction.IGNORE
  }
}

/**
 * I4 integration seam. This native entrypoint must stay independent of Flutter and OTA UI state.
 */
object BleWakeNativeEntrypoint {
  private var lastContinuousJournalMs = 0L
  private val skippedJournal = ContinuousSkipJournalPolicy()

  private fun recordSkipped(context: Context, event: BleWakeEvent, reason: String) {
    BleScanDiagnostics.dispatch(context, BleDispatchDiagnostic.SKIPPED, reason.uppercase(java.util.Locale.ROOT))
    NativeDiagnostics.record(context, NativeDiagnostics.Event.DISPATCH_SKIPPED, reason,
      ready = event.readyHint?.ready, epoch = event.readyHint?.epoch)
    if (skippedJournal.shouldRecord(reason, event.receivedElapsedMs)) {
      // Closed reason codes only; preserve radio success without pretending an
      // authentication was dispatched. No address/advertisement payload logged.
      BleWakeJournal.record(context, event.copy(
        source = reason,
        success = event.success && reason == "ble_scan_no_ready_hint",
      ))
    }
  }
  fun onWake(context: Context, event: BleWakeEvent) {
    val appContext = context.applicationContext
    when (BleWakeDispatchPolicy.classify(event)) {
      BleWakeDispatchAction.EXIT -> {
        val lostAt = event.scanTimestampNanos?.takeIf { it > 0 }?.div(1_000_000L)
        if (!ContinuousPresenceTracker.exit(event.deviceAddress, lostAt)) {
          BleScanDiagnostics.dispatch(appContext, BleDispatchDiagnostic.SKIPPED, "STALE_EXIT_CALLBACK")
          NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED, "STALE_EXIT_CALLBACK")
          return
        }
        NativeDiagnostics.record(appContext, NativeDiagnostics.Event.SCAN_EXIT)
        BleWakeJournal.record(
          appContext,
          event.copy(source = "ble_scan_exit", success = false),
        )
        AccessResultNotifier.dismiss(appContext)
      }
      BleWakeDispatchAction.PRESENCE -> {
        val address = event.deviceAddress ?: run {
          recordSkipped(appContext, event, "ble_scan_no_address")
          return
        }
        // FIRST_MATCH has the same freshness requirement as ALL_MATCHES.
        if (!BleScanObservationPolicy.fresh(event.latencyMs)) {
          recordSkipped(appContext, event, "ble_scan_stale")
          return
        }
        ContinuousPresenceTracker.observe(address, event.scanTimestampNanos?.takeIf { it > 0 }?.div(1_000_000L)
          ?: (event.receivedElapsedMs - event.latencyMs!!.toLong()))
        if (event.readyHintMalformed) {
          recordSkipped(appContext, event, "ble_scan_malformed_ready_hint")
          return
        }
        if (event.receivedElapsedMs - lastContinuousJournalMs >= 2_000) {
          lastContinuousJournalMs = event.receivedElapsedMs
          BleWakeJournal.record(appContext, event)
          AuthenticatedTargetLocatorStore(appContext).record(address)
        }
        val hint = event.readyHint
        if (hint == null) {
          // Missing scan response is an optimization loss, never an ACL/proof.
          BleGattWorkScheduler.onMissingReadyHint(appContext, address)
        } else if (hint.ready) {
          BleGattWorkScheduler.onContinuousPresence(appContext, address, hint.epoch)
        } else {
          BleScanDiagnostics.dispatch(appContext, BleDispatchDiagnostic.SKIPPED, "TARGET_NOT_READY")
          NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED,
            "TARGET_NOT_READY", ready = false, epoch = hint.epoch)
        }
      }
      BleWakeDispatchAction.IGNORE -> BleWakeJournal.record(appContext, event)
    }
  }
}
