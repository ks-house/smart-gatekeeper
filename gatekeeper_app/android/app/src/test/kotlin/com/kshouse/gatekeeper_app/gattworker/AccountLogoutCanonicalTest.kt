package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class AccountLogoutCanonicalTest {
  @Test
  fun `canonical logout proof is fixed width and domain separated`() {
    val credential = ByteArray(16) { 0x31 }
    val nonce = ByteArray(32) { 0x42 }
    val first = AccountLogoutCanonical.build(
      credential,
      nonce,
      1_900_000_000L,
      "555555555555555555555555555555555555555555555555",
    )
    val second = AccountLogoutCanonical.build(
      credential,
      nonce,
      1_900_000_000L,
      "666666666666666666666666666666666666666666666666",
    )

    assertEquals(96, first.size)
    assertEquals("SGKOUT01", first.copyOfRange(0, 8).toString(Charsets.US_ASCII))
    assertFalse(first.contentEquals(second))
  }
}
