package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
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

  @Test
  fun targetHelloAndChallengeIndicationsShareOneOrderedMailbox() = runBlocking {
    val mailbox = GattCallbackMailbox()
    val targetHello = ByteArray(20) { (it + 1).toByte() }
    val challenge = ByteArray(138) { (it + 31).toByte() }

    GattFraming.fragment(GattProtocol.TARGET_HELLO, 7, targetHello, 23)
      .forEach(mailbox::onFrame)
    GattFraming.fragment(GattProtocol.CHALLENGE, 8, challenge, 23)
      .forEach(mailbox::onFrame)

    assertTrue(
      targetHello.contentEquals(mailbox.awaitMessage(GattProtocol.TARGET_HELLO)),
    )
    assertTrue(
      challenge.contentEquals(mailbox.awaitMessage(GattProtocol.CHALLENGE)),
    )
  }

  @Test
  fun disconnectDuringClientHelloWriteWakesWaiterWithExactStatusBeforeTimeout() = runBlocking {
    val fixture = connectedFixture()
    val write = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.HELLO_UUID,
    )

    assertTrue(fixture.coordinator.onDisconnected(fixture.connection, fixture.owner, 19))
    val error = expectTransportFailure {
      withTimeout(100) { fixture.coordinator.await(write) }
    }

    assertEquals(TransportFailureCode.DISCONNECTED, error.failureCode)
    assertEquals(AccessReasonCode.GATT_DISCONNECTED, error.failureCode.observabilityReason)
    assertEquals(19, error.gattStatus)
  }

  @Test
  fun disconnectDuringProofWriteUsesSameLosslessCharacteristicPath() = runBlocking {
    val fixture = connectedFixture()
    val write = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.PROOF_UUID,
    )

    fixture.coordinator.onDisconnected(fixture.connection, fixture.owner, 133)
    val error = expectTransportFailure { fixture.coordinator.await(write) }

    assertEquals(TransportFailureCode.DISCONNECTED, error.failureCode)
    assertEquals(133, error.gattStatus)
  }

  @Test
  fun disconnectDuringCccdWriteWakesDescriptorWaiterWithExactStatus() = runBlocking {
    val fixture = connectedFixture()
    val descriptor = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.DESCRIPTOR_WRITE,
      GattProtocol.RESULT_UUID,
    )

    fixture.coordinator.onDisconnected(fixture.connection, fixture.owner, 8)
    val error = expectTransportFailure {
      withTimeout(100) { fixture.coordinator.await(descriptor) }
    }

    assertEquals(TransportFailureCode.DISCONNECTED, error.failureCode)
    assertEquals(8, error.gattStatus)
  }

  @Test
  fun disconnectWakesCharacteristicAndDescriptorWaitersExactlyOnce() = runBlocking {
    val fixture = connectedFixture()
    val write = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.HELLO_UUID,
    )
    val descriptor = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.DESCRIPTOR_WRITE,
      GattProtocol.CHALLENGE_UUID,
    )

    assertTrue(fixture.coordinator.onDisconnected(fixture.connection, fixture.owner, 22))
    assertFalse(fixture.coordinator.onDisconnected(fixture.connection, fixture.owner, 23))
    assertEquals(22, expectTransportFailure { fixture.coordinator.await(write) }.gattStatus)
    assertEquals(22, expectTransportFailure { fixture.coordinator.await(descriptor) }.gattStatus)
  }

  @Test
  fun lateAndDuplicateCallbacksAreNeverBufferedForTheNextOperation() = runBlocking {
    val fixture = connectedFixture()
    val first = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.HELLO_UUID,
    )
    assertTrue(
      fixture.coordinator.complete(
        fixture.connection,
        fixture.owner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.HELLO_UUID,
        0,
      ),
    )
    assertFalse(
      fixture.coordinator.complete(
        fixture.connection,
        fixture.owner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.HELLO_UUID,
        0,
      ),
    )
    assertEquals(0, fixture.coordinator.await(first))

    val next = fixture.coordinator.begin(
      fixture.connection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.PROOF_UUID,
    )
    assertFalse(next.isCompleted)
    assertFalse(
      fixture.coordinator.complete(
        fixture.connection,
        fixture.owner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.HELLO_UUID,
        0,
      ),
    )
    assertFalse(next.isCompleted)
    assertTrue(
      fixture.coordinator.complete(
        fixture.connection,
        fixture.owner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.PROOF_UUID,
        5,
      ),
    )
    assertEquals(5, fixture.coordinator.await(next))
  }

  @Test
  fun reconnectGenerationRejectsEveryCallbackFromTheOldGatt() = runBlocking {
    val coordinator = GattConnectionCoordinator()
    val oldConnection = coordinator.openConnection()
    val oldOwner = Any()
    assertTrue(coordinator.bind(oldConnection, oldOwner))
    val oldWrite = coordinator.begin(
      oldConnection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.HELLO_UUID,
    )
    coordinator.onDisconnected(oldConnection, oldOwner, 19)

    val newConnection = coordinator.openConnection()
    val newOwner = Any()
    assertTrue(coordinator.bind(newConnection, newOwner))
    val newWrite = coordinator.begin(
      newConnection,
      GattPendingOperation.CHARACTERISTIC_WRITE,
      GattProtocol.HELLO_UUID,
    )

    assertFalse(
      coordinator.complete(
        oldConnection,
        oldOwner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.HELLO_UUID,
        0,
      ),
    )
    assertFalse(newWrite.isCompleted)
    assertTrue(
      coordinator.complete(
        newConnection,
        newOwner,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        GattProtocol.HELLO_UUID,
        0,
      ),
    )

    assertEquals(19, expectTransportFailure { coordinator.await(oldWrite) }.gattStatus)
    assertEquals(0, coordinator.await(newWrite))
  }

  private fun connectedFixture(): CoordinatorFixture {
    val coordinator = GattConnectionCoordinator()
    val connection = coordinator.openConnection()
    val owner = Any()
    assertTrue(coordinator.bind(connection, owner))
    return CoordinatorFixture(coordinator, connection, owner)
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

private data class CoordinatorFixture(
  val coordinator: GattConnectionCoordinator,
  val connection: GattConnectionCoordinator.Connection,
  val owner: Any,
)
