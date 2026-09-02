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
    assertFalse(notice.detail.contains("문 열림"))
    assertFalse(notice.title.contains("확인"))
    assertEquals(
      AccessResultNotificationPolicy.ACCESS_READY_TIMEOUT_MS,
      notice.timeoutAfterMs,
    )
    assertEquals(
      AccessResultNotificationPolicy.ACCESS_READY_NOTIFICATION_ID,
      AccessResultNotificationPolicy.notificationIdFor(notice),
    )
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
  fun `failure reports authentication failure without a physical door claim`() {
    val notice = AccessResultNotificationPolicy.forState(DurableSessionState.FAILED)!!
    assertTrue(notice.isFailure)
    assertEquals("스마트키 인증 실패", notice.title)
    assertFalse(notice.title.contains("문 열림"))
    assertFalse(notice.detail.contains("문이 열"))
    assertNull(notice.timeoutAfterMs)
    assertEquals(
      AccessResultNotificationPolicy.ATTENTION_NOTIFICATION_ID,
      AccessResultNotificationPolicy.notificationIdFor(notice),
    )
  }

  @Test
  fun `non terminal state has no user notification`() {
    assertNull(AccessResultNotificationPolicy.forState(DurableSessionState.RUNNING))
    assertNull(AccessResultNotificationPolicy.forState(DurableSessionState.RETRY_PENDING))
  }
}
