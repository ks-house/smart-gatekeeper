package com.kshouse.gatekeeper_app.blewake

/** Silence can mean out of range. Refresh conservatively; never claim a radio failure. */
internal object BleScanRecoveryPolicy {
  const val QUIET_REFRESH_MS = 15 * 60 * 1000L
  const val CONFIRMATION_WINDOW_MS = 30_000L
  const val REENTRY_COOLDOWN_MS = 60_000L

  fun mayStart(now: Long, startedAt: Long?): Boolean = startedAt == null ||
    now < startedAt || now - startedAt >= REENTRY_COOLDOWN_MS

  fun freshPacket(now: Long, packetAt: Long?): Boolean = packetAt != null &&
    now >= packetAt && now - packetAt <= CONFIRMATION_WINDOW_MS

  fun confirmation(now: Long, started: Long, packetAt: Long?): String = when {
    now < started -> "CLOCK_UNCERTAIN"
    packetAt != null && packetAt in started..minOf(now, started + CONFIRMATION_WINDOW_MS) -> "MATCHING_PACKET_RECEIVED"
    now - started >= CONFIRMATION_WINDOW_MS -> "NO_MATCHING_PACKET"
    else -> "AWAITING_PACKET"
  }

  fun shouldRefresh(now: Long, acceptedAt: Long?, lastPacketAt: Long?): Boolean {
    if (acceptedAt == null) return true
    // A fresh registration needs time to produce packets. Old callbacks from
    // before registration must not cause repeated stop/start or scan throttling.
    if (now < acceptedAt) return true
    val packet = lastPacketAt?.takeIf { it <= now } ?: acceptedAt
    val baseline = maxOf(acceptedAt, packet)
    return now - baseline >= QUIET_REFRESH_MS
  }
}
