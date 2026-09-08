package com.kshouse.gatekeeper_app.gattworker

internal object PreProofOrphanPolicy {
  fun oldEnough(session: DurableGattSession, now: Long): Boolean =
    now >= session.updatedEpochMs && now - session.updatedEpochMs > HandsFreeDispatchPolicy.MAX_PRESENCE_AGE_MS

  fun mayRecover(session: DurableGattSession, now: Long, hasUnfinishedWork: Boolean): Boolean =
    session.requiresFreshPresence && !hasUnfinishedWork && oldEnough(session, now) &&
      DurableAttemptPolicy.canExecute(session.state)
}
