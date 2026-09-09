package com.kshouse.gatekeeper_app.blewake

/** Silence can mean out of range. Refresh conservatively; never claim a radio failure. */
internal object BleScanRecoveryPolicy {
  const val QUIET_REFRESH_MS = 15 * 60 * 1000L

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
