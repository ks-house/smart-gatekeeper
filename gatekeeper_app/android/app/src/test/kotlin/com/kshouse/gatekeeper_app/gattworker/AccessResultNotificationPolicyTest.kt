package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessResultNotificationPolicyTest {
  @Test
  fun `success means sensor armed and never claims door opened`() {
    val notice = AccessResultNotificationPolicy.forState(DurableSessionState.SUCCEEDED)
    assertNotNull(notice)
    assertEquals("출입 준비 완료", notice!!.title)
    assertTrue(notice.detail.contains("센서"))
    assertFalse(notice.detail.contains("문이 열"))
  }

  @Test
  fun `proof uncertainty warns against automatic retry`() {
    val notice = AccessResultNotificationPolicy.forState(
      DurableSessionState.PROOF_UNCERTAIN,
    )!!
    assertTrue(notice.isFailure)
    assertTrue(notice.detail.contains("다시 시도하지"))
  }

  @Test
  fun `non terminal state has no user notification`() {
    assertNull(AccessResultNotificationPolicy.forState(DurableSessionState.RUNNING))
    assertNull(AccessResultNotificationPolicy.forState(DurableSessionState.RETRY_PENDING))
  }
}
