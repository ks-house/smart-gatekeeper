package com.kshouse.gatekeeper_app.blewake

import com.kshouse.gatekeeper_app.gattworker.DurableGattSession
import com.kshouse.gatekeeper_app.gattworker.DurableSessionState

data class PresenceReadyHint(val ready: Boolean, val epoch: Long) {
  companion object {
    fun parse(bytes: ByteArray?): PresenceReadyHint? {
      if (bytes == null || bytes.size != 6 || bytes[0] != 1.toByte() ||
        bytes[1].toInt() !in 0..1) return null
      val epoch = (0..3).fold(0L) { value, index ->
        value or ((bytes[index + 2].toLong() and 255L) shl (index * 8))
      }
      return PresenceReadyHint(bytes[1] == 1.toByte(), epoch)
    }
  }
}

// Bound diagnostic writes for otherwise invisible ALL_MATCHES early returns.
class ContinuousSkipJournalPolicy {
  private val last = mutableMapOf<String, Long>()
  @Synchronized fun shouldRecord(reason: String, now: Long): Boolean {
    if (reason !in setOf("ble_scan_no_address", "ble_scan_stale", "ble_scan_no_ready_hint")) return false
    val previous = last[reason]
    if (previous != null && now >= previous && now - previous < 10_000) return false
    last[reason] = now
    return true
  }
}

object ContinuousPresencePolicy {
  const val FRESH_MS = 5_000L
  // A terminal failure must not permanently consume an otherwise unchanged
  // ready epoch. Only call after maySchedule's failure backoff has elapsed.
  fun eventId(epoch: Long, last: DurableGattSession?): String =
    "ready-v1-$epoch" + if (last?.state == DurableSessionState.FAILED) "-after-${last.id}" else ""

  fun maySchedule(last: DurableGattSession?, now: Long): Boolean = blockingReason(last, now) == null

  fun blockingReason(last: DurableGattSession?, now: Long): String? {
    if (last == null) return null
    val age = (now - last.updatedEpochMs).coerceAtLeast(0)
    return when (last.state) {
      DurableSessionState.PROOF_UNCERTAIN -> "PROOF_OUTCOME_UNCERTAIN"
      DurableSessionState.RUNNING, DurableSessionState.QUEUED,
      DurableSessionState.RETRY_PENDING -> "SESSION_ALREADY_ACTIVE"
      DurableSessionState.FAILED -> {
        // A new fresh ready advertisement can recover a known pre-proof link
        // failure without a minute-long dead period. Authorization denials keep
        // their existing backoff; unresolved proofs never reach this branch.
        val transient = last.reasonCode in setOf(
          "GATT_CONNECT_FAILED", "GATT_DISCONNECTED", "GATT_TIMEOUT", "TARGET_BUSY",
        )
        // One fast recovery after the ordinary wake. If that fresh-presence
        // recovery also fails, leave the Target its 30-second unverified-lease
        // quiet window rather than reconnecting every five seconds forever.
        val fastRecovery = transient && !last.failureRecovery
        val delay = maxOf(if (fastRecovery) 5_000L else 60_000L, last.retryAfterMs ?: 0L)
        if (age >= delay) null else "FAILURE_BACKOFF"
      }
      else -> if (age >= 2_000) null else "SESSION_COOLDOWN"
    }
  }
}

// Volatile radio evidence only. After process death a fresh callback is required
// before any continuous-presence proof; raw locators are never persisted here.
object ContinuousPresenceTracker {
  private val seen = linkedMapOf<String, Long>()
  @Synchronized fun observe(address: String, now: Long) {
    if (seen.size >= 16 && address !in seen) seen.remove(seen.keys.first())
    seen[address] = now
  }
  @Synchronized fun exit(address: String?) {
    if (address == null) seen.clear() else seen.remove(address)
  }
  @Synchronized fun fresh(address: String, now: Long): Boolean =
    seen[address]?.let { now >= it && now - it <= ContinuousPresencePolicy.FRESH_MS } == true
}
