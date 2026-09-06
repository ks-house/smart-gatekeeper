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

object ContinuousPresencePolicy {
  const val FRESH_MS = 5_000L
  fun maySchedule(last: DurableGattSession?, now: Long): Boolean {
    if (last == null) return true
    val age = (now - last.updatedEpochMs).coerceAtLeast(0)
    return when (last.state) {
      DurableSessionState.PROOF_UNCERTAIN -> false
      DurableSessionState.RUNNING, DurableSessionState.QUEUED,
      DurableSessionState.RETRY_PENDING -> false
      DurableSessionState.FAILED -> age >= 60_000
      else -> age >= 2_000
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
