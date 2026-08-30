package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RemoteManualOpenCanonicalTest {
  @Test
  fun `canonical proof is fixed width and binds expiry`() {
    val credential = ByteArray(16) { 0x33 }
    val nonce = ByteArray(32) { 0x44 }
    val first = RemoteManualOpenCanonical.build(
      credential,
      nonce,
      1_900_000_000L,
      "mobile_manual_button",
      "555555555555555555555555555555555555555555555555",
    )
    val second = RemoteManualOpenCanonical.build(
      credential,
      nonce,
      1_900_000_001L,
      "mobile_manual_button",
      "555555555555555555555555555555555555555555555555",
    )

    assertEquals(128, first.size)
    assertEquals("SGKRMO01", first.copyOfRange(0, 8).toString(Charsets.US_ASCII))
    assertFalse(first.contentEquals(second))
  }
}
