package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

class GattTransportCallbackTest {
  @Test
  fun disconnectCallbackPreservesGattStatusAndReason() = runBlocking {
    val mailbox = GattCallbackMailbox()
    mailbox.onDisconnected(19)
    val error = expectTransportFailure { mailbox.awaitMessage(GattProtocol.RESULT) }
    assertEquals(TransportFailureCode.DISCONNECTED, error.failureCode)
    assertEquals(19, error.gattStatus)
  }

  @Test
  fun readFailureCallbackIsNotMisreportedAsProtocolIncompatible() = runBlocking {
    val mailbox = GattCallbackMailbox()
    mailbox.onReadFailure(133)
    val error = expectTransportFailure { mailbox.awaitMessage(GattProtocol.CHALLENGE) }
    assertEquals(TransportFailureCode.READ_FAILED, error.failureCode)
    assertEquals(133, error.gattStatus)
    assertEquals(AccessReasonCode.GATT_CONNECT_FAILED, error.failureCode.observabilityReason)
  }

  @Test
  fun malformedFrameAndUnexpectedMessageRemainDistinct() = runBlocking {
    val malformed = GattCallbackMailbox()
    malformed.onFrame(byteArrayOf(1, 2, 3))
    assertEquals(
      TransportFailureCode.MALFORMED_FRAME,
      expectTransportFailure { malformed.awaitMessage(GattProtocol.RESULT) }.failureCode,
    )

    val unexpected = GattCallbackMailbox()
    GattFraming.fragment(GattProtocol.CHALLENGE, 1, byteArrayOf(7), 23).forEach(unexpected::onFrame)
    val error = expectTransportFailure { unexpected.awaitMessage(GattProtocol.RESULT) }
    assertEquals(TransportFailureCode.UNEXPECTED_MESSAGE_TYPE, error.failureCode)
    assertEquals(GattProtocol.CHALLENGE, error.gattStatus)
  }

  private suspend fun expectTransportFailure(block: suspend () -> Unit): GattTransportException {
    try {
      block()
      fail("expected GattTransportException")
    } catch (error: GattTransportException) {
      return error
    }
    throw AssertionError("unreachable")
  }
}
