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
    event.success -> BleWakeDispatchAction.PRESENCE
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
        NativeDiagnostics.record(appContext, NativeDiagnostics.Event.SCAN_EXIT)
        ContinuousPresenceTracker.exit(event.deviceAddress)
        BleWakeJournal.record(
          appContext,
          event.copy(source = "ble_scan_exit", success = false),
        )
        AccessResultNotifier.dismiss(appContext)
      }
      BleWakeDispatchAction.PRESENCE -> {
        val continuous = event.callbackType == ScanSettings.CALLBACK_TYPE_ALL_MATCHES
        if (continuous || event.readyHint != null) {
          val address = event.deviceAddress ?: run {
            recordSkipped(appContext, event, "ble_scan_no_address")
            return
          }
          // Reject stale OS batches before treating them as current proximity.
          if (event.latencyMs == null || !event.latencyMs.isFinite() ||
            event.latencyMs < 0 || event.latencyMs > ContinuousPresencePolicy.FRESH_MS) {
            recordSkipped(appContext, event, "ble_scan_stale")
            return
          }
          ContinuousPresenceTracker.observe(address, event.receivedElapsedMs - event.latencyMs.toLong())
          val hint = event.readyHint ?: run {
            recordSkipped(appContext, event, "ble_scan_no_ready_hint")
            return // N-1 Target retains FIRST_MATCH only.
          }
          if (event.receivedElapsedMs - lastContinuousJournalMs >= 2_000) {
            lastContinuousJournalMs = event.receivedElapsedMs
            BleWakeJournal.record(appContext, event)
            AuthenticatedTargetLocatorStore(appContext).record(address)
          }
          if (hint.ready) BleGattWorkScheduler.onContinuousPresence(appContext, address, hint.epoch)
          else NativeDiagnostics.record(appContext, NativeDiagnostics.Event.DISPATCH_SKIPPED,
            "TARGET_NOT_READY", ready = false, epoch = hint.epoch)
          return
        }
        BleWakeJournal.record(appContext, event)
        event.deviceAddress?.let { AuthenticatedTargetLocatorStore(appContext).record(it) }
        BleGattWorkScheduler.onPresence(appContext, event.deviceAddress, event.presenceEventId())
      }
      BleWakeDispatchAction.IGNORE -> BleWakeJournal.record(appContext, event)
    }
  }
}
