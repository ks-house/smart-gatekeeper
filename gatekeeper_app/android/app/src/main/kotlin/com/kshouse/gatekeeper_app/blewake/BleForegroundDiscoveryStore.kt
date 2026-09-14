package com.kshouse.gatekeeper_app.blewake

import android.content.Context

/** Observations only. Cooldown and the in-memory/kernel owner survive Clear. */
internal object BleForegroundDiscoveryStore {
  private fun prefs(context: Context) = context.getSharedPreferences("ble_foreground_discovery_v1", Context.MODE_PRIVATE)
  private val fields = listOf("alternativeStage", "alternativeResultCount", "alternativeCandidateCount",
    "alternativeMatchCount", "alternativeErrorCount", "alternativeErrorCode", "alternativeStartedAtEpochMs",
    "alternativeFinishedAtEpochMs", "alternativeRestoreStatus")

  @Synchronized fun visible(context: Context, startedAt: Long): Boolean =
    startedAt > prefs(context).getLong("cleared_at", 0)

  @Synchronized fun clear(context: Context, since: Long) {
    val p = prefs(context)
    val edit = p.edit().putLong("cleared_at", since)
      .putLong("last_attempt", p.getLong("last_attempt", p.getLong("alternativeStartedAtEpochMs", 0)))
    fields.forEach(edit::remove)
    edit.apply()
  }

  @Synchronized fun waiting(context: Context) {
    val edit = prefs(context).edit()
    fields.forEach(edit::remove)
    edit.putString("alternativeStage", "WAITING_PRIMARY").apply()
  }

  @Synchronized fun finishWaiting(context: Context, startedAt: Long, stage: String) {
    if (!visible(context, startedAt)) return
    prefs(context).edit().putString("alternativeStage", stage)
      .putLong("alternativeFinishedAtEpochMs", System.currentTimeMillis()).apply()
  }
}
