package com.kshouse.gatekeeper_app.gattworker

import android.Manifest
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import java.util.concurrent.atomic.AtomicInteger
import java.util.UUID

private sealed class GattCallbackEvent {
  data class Message(val type: Int, val payload: ByteArray) : GattCallbackEvent()
  data class Failure(val exception: GattTransportException) : GattCallbackEvent()
}

internal class GattCallbackMailbox(
  private val reassembler: GattReassembler = GattReassembler(),
) {
  private val events = Channel<GattCallbackEvent>(Channel.BUFFERED)
  private var terminal = false

  suspend fun awaitMessage(expectedType: Int): ByteArray {
    while (true) {
      when (val event = events.receive()) {
        is GattCallbackEvent.Message -> {
          if (event.type == expectedType) return event.payload
          throw GattTransportException(TransportFailureCode.UNEXPECTED_MESSAGE_TYPE, event.type)
        }
        is GattCallbackEvent.Failure -> throw event.exception
      }
    }
  }

  @Synchronized
  fun onFrame(value: ByteArray) {
    if (terminal) return
    try {
      reassembler.accept(value)?.let { (type, payload) ->
        events.trySend(GattCallbackEvent.Message(type, payload))
      }
    } catch (error: IllegalArgumentException) {
      failOnce(
        GattTransportException(TransportFailureCode.MALFORMED_FRAME, cause = error),
      )
    }
  }

  @Synchronized
  fun onDisconnected(status: Int) {
    failOnce(GattTransportException(TransportFailureCode.DISCONNECTED, status))
  }

  @Synchronized
  fun onReadFailure(status: Int) {
    failOnce(GattTransportException(TransportFailureCode.READ_FAILED, status))
  }

  private fun failOnce(error: GattTransportException) {
    if (terminal) return
    terminal = true
    events.trySend(GattCallbackEvent.Failure(error))
  }
}

internal enum class GattPendingOperation {
  CHARACTERISTIC_WRITE,
  DESCRIPTOR_WRITE,
}

internal sealed class GattOperationResult {
  data class Callback(val status: Int) : GattOperationResult()
  data class Failure(val exception: GattTransportException) : GattOperationResult()
}

internal class GattOperationToken internal constructor(
  internal val connection: GattConnectionCoordinator.Connection,
  internal val operation: GattPendingOperation,
  internal val targetUuid: UUID,
  internal val sequence: Long,
  internal val result: CompletableDeferred<GattOperationResult>,
) {
  internal val isCompleted: Boolean
    get() = result.isCompleted
}

/**
 * Owns every callback and in-flight operation for exactly one BluetoothGatt generation.
 *
 * Android callbacks carry a BluetoothGatt instance but no application operation ID. A callback
 * therefore has effect only when both its captured generation and GATT object own the active
 * connection. Operation results are unbuffered single-consumer latches: a duplicate or late
 * callback cannot become the result of the next write, while disconnect completes both possible
 * in-flight write classes with the exact Android status.
 */
internal class GattConnectionCoordinator {
  internal class Connection internal constructor(
    val generation: Long,
  ) {
    internal val connected = CompletableDeferred<Unit>()
    internal val servicesReady = CompletableDeferred<Unit>()
    internal val mailbox = GattCallbackMailbox()
    internal var owner: Any? = null
    internal var terminalFailure: GattTransportException? = null
    internal var characteristicWrite: GattOperationToken? = null
    internal var descriptorWrite: GattOperationToken? = null
    internal var nextSequence = 1L
  }

  private var nextGeneration = 1L
  private var active: Connection? = null

  @Synchronized
  fun openConnection(): Connection {
    active?.let {
      terminateLocked(it, GattTransportException(TransportFailureCode.DISCONNECTED))
    }
    return Connection(nextGeneration++).also { active = it }
  }

  @Synchronized
  fun bind(connection: Connection, owner: Any): Boolean {
    if (active !== connection) return false
    if (connection.owner == null) connection.owner = owner
    return connection.owner === owner
  }

  @Synchronized
  fun onConnected(connection: Connection, owner: Any): Boolean {
    if (!acceptCallbackLocked(connection, owner)) return false
    return connection.connected.complete(Unit)
  }

  @Synchronized
  fun onServicesReady(connection: Connection, owner: Any): Boolean {
    if (!acceptCallbackLocked(connection, owner)) return false
    return connection.servicesReady.complete(Unit)
  }

  @Synchronized
  fun onServicesFailed(connection: Connection, owner: Any, status: Int?): Boolean {
    if (!acceptCallbackLocked(connection, owner)) return false
    return connection.servicesReady.completeExceptionally(
      GattTransportException(TransportFailureCode.SERVICE_DISCOVERY_FAILED, status),
    )
  }

  @Synchronized
  fun acceptsCallback(connection: Connection, owner: Any): Boolean =
    acceptCallbackLocked(connection, owner)

  @Synchronized
  fun onDisconnected(connection: Connection, owner: Any, status: Int): Boolean {
    if (active !== connection) return false
    if (connection.owner == null) connection.owner = owner
    if (connection.owner !== owner || connection.terminalFailure != null) return false
    terminateLocked(
      connection,
      GattTransportException(TransportFailureCode.DISCONNECTED, status),
    )
    return true
  }

  @Synchronized
  fun begin(
    connection: Connection,
    operation: GattPendingOperation,
    targetUuid: UUID,
  ): GattOperationToken {
    requireActiveLocked(connection)
    check(pendingLocked(connection, operation) == null) { "$operation already in flight" }
    val token = GattOperationToken(
      connection = connection,
      operation = operation,
      targetUuid = targetUuid,
      sequence = connection.nextSequence++,
      result = CompletableDeferred(),
    )
    setPendingLocked(connection, operation, token)
    return token
  }

  @Synchronized
  fun complete(
    connection: Connection,
    owner: Any,
    operation: GattPendingOperation,
    targetUuid: UUID,
    status: Int,
  ): Boolean {
    if (!acceptCallbackLocked(connection, owner)) return false
    val pending = pendingLocked(connection, operation) ?: return false
    if (pending.targetUuid != targetUuid || pending.isCompleted) return false
    return pending.result.complete(GattOperationResult.Callback(status))
  }

  suspend fun await(token: GattOperationToken): Int {
    return try {
      when (val outcome = token.result.await()) {
        is GattOperationResult.Callback -> outcome.status
        is GattOperationResult.Failure -> throw outcome.exception
      }
    } finally {
      clear(token)
    }
  }

  @Synchronized
  fun cancel(token: GattOperationToken) {
    if (pendingLocked(token.connection, token.operation) === token) {
      setPendingLocked(token.connection, token.operation, null)
      token.result.cancel()
    }
  }

  @Synchronized
  fun currentFailure(connection: Connection): GattTransportException? = when {
    active !== connection -> GattTransportException(TransportFailureCode.DISCONNECTED)
    else -> connection.terminalFailure
  }

  @Synchronized
  fun close(connection: Connection) {
    if (active !== connection) return
    terminateLocked(connection, GattTransportException(TransportFailureCode.DISCONNECTED))
    active = null
  }

  @Synchronized
  private fun clear(token: GattOperationToken) {
    if (pendingLocked(token.connection, token.operation) === token) {
      setPendingLocked(token.connection, token.operation, null)
    }
  }

  private fun acceptCallbackLocked(connection: Connection, owner: Any): Boolean {
    if (active !== connection || connection.terminalFailure != null) return false
    if (connection.owner == null) connection.owner = owner
    return connection.owner === owner
  }

  private fun requireActiveLocked(connection: Connection) {
    if (active !== connection) {
      throw GattTransportException(TransportFailureCode.DISCONNECTED)
    }
    connection.terminalFailure?.let { throw it }
  }

  private fun terminateLocked(connection: Connection, error: GattTransportException) {
    if (connection.terminalFailure != null) return
    connection.terminalFailure = error
    connection.connected.completeExceptionally(error)
    connection.servicesReady.completeExceptionally(error)
    connection.mailbox.onDisconnected(error.gattStatus ?: 0)
    connection.characteristicWrite?.result?.complete(GattOperationResult.Failure(error))
    connection.descriptorWrite?.result?.complete(GattOperationResult.Failure(error))
  }

  private fun pendingLocked(
    connection: Connection,
    operation: GattPendingOperation,
  ): GattOperationToken? = when (operation) {
    GattPendingOperation.CHARACTERISTIC_WRITE -> connection.characteristicWrite
    GattPendingOperation.DESCRIPTOR_WRITE -> connection.descriptorWrite
  }

  private fun setPendingLocked(
    connection: Connection,
    operation: GattPendingOperation,
    token: GattOperationToken?,
  ) {
    when (operation) {
      GattPendingOperation.CHARACTERISTIC_WRITE -> connection.characteristicWrite = token
      GattPendingOperation.DESCRIPTOR_WRITE -> connection.descriptorWrite = token
    }
  }
}

class AndroidBleGattTransport(private val context: Context) : BleGattTransport {
  private val messageId = AtomicInteger(1)
  private val callbackCoordinator = GattConnectionCoordinator()
  private var connection: GattConnectionCoordinator.Connection? = null
  private var gatt: BluetoothGatt? = null
  private var mtu = 23

  override suspend fun connect(deviceAddress: String) {
    requireConnectPermission()
    val manager = context.getSystemService(BluetoothManager::class.java)
      ?: throw IllegalStateException("Bluetooth unavailable")
    val adapter = manager.adapter ?: throw IllegalStateException("Bluetooth unavailable")
    if (!adapter.isEnabled) throw BluetoothDisabledException()
    val device = adapter.getRemoteDevice(deviceAddress)
    val newConnection = callbackCoordinator.openConnection()
    connection = newConnection
    val callback = callback(newConnection)
    val newGatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
      device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
    } else {
      @Suppress("DEPRECATION")
      device.connectGatt(context, false, callback)
    }
    gatt = newGatt
    if (!callbackCoordinator.bind(newConnection, newGatt)) {
      newGatt.close()
      throw callbackCoordinator.currentFailure(newConnection)
        ?: GattTransportException(TransportFailureCode.DISCONNECTED)
    }
    newConnection.connected.await()
    newConnection.servicesReady.await()
    enableIndication(GattProtocol.HELLO_UUID)
    enableIndication(GattProtocol.CHALLENGE_UUID)
    enableIndication(GattProtocol.RESULT_UUID)
  }

  override suspend fun negotiate(clientHello: ByteArray): ByteArray {
    writeMessage(GattProtocol.HELLO_UUID, GattProtocol.CLIENT_HELLO, clientHello)
    return activeConnection().mailbox.awaitMessage(GattProtocol.TARGET_HELLO)
  }

  override suspend fun readChallenge(): ByteArray {
    // The Target emits the challenge as an ACK-gated indication stream after
    // TARGET_HELLO.  Issuing a characteristic read at the same time creates a
    // second, single-frame representation with the same message ID; Android can
    // deliver it between indicated fragments and the strict reassembler must
    // reject that mixed stream.  The CCCD is enabled before CLIENT_HELLO, so a
    // single mailbox path is both lossless and deterministic here.
    return activeConnection().mailbox.awaitMessage(GattProtocol.CHALLENGE)
  }

  override suspend fun writeProof(proof: ByteArray) {
    writeMessage(GattProtocol.PROOF_UUID, GattProtocol.PROOF, proof)
  }

  override suspend fun awaitResult(): ByteArray =
    activeConnection().mailbox.awaitMessage(GattProtocol.RESULT)

  override fun close() {
    connection?.let(callbackCoordinator::close)
    try {
      gatt?.disconnect()
    } catch (_: SecurityException) {
      // Permission revocation is already represented by the session reason.
    }
    gatt?.close()
    gatt = null
    connection = null
  }

  private suspend fun writeMessage(uuid: java.util.UUID, type: Int, payload: ByteArray) {
    val id = messageId.getAndUpdate { if (it == 0xffff) 1 else it + 1 }
    for (frame in GattFraming.fragment(type, id, payload, mtu)) {
      val activeConnection = activeConnection()
      val token = callbackCoordinator.begin(
        activeConnection,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        uuid,
      )
      try {
        writeCharacteristic(characteristic(uuid), frame, activeConnection)
      } catch (error: Throwable) {
        callbackCoordinator.cancel(token)
        throw error
      }
      val status = callbackCoordinator.await(token)
      if (status != BluetoothGatt.GATT_SUCCESS) {
        throw GattTransportException(TransportFailureCode.WRITE_FAILED, status)
      }
    }
  }

  private suspend fun enableIndication(uuid: java.util.UUID) {
    val activeConnection = activeConnection()
    val characteristic = characteristic(uuid)
    if (gatt?.setCharacteristicNotification(characteristic, true) != true) {
      callbackCoordinator.currentFailure(activeConnection)?.let { throw it }
      throw GattTransportException(TransportFailureCode.DESCRIPTOR_WRITE_FAILED)
    }
    val descriptor = characteristic.getDescriptor(GattProtocol.CCCD_UUID)
      ?: throw GattTransportException(TransportFailureCode.DESCRIPTOR_WRITE_FAILED)
    val token = callbackCoordinator.begin(
      activeConnection,
      GattPendingOperation.DESCRIPTOR_WRITE,
      uuid,
    )
    try {
      writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_INDICATION_VALUE, activeConnection)
    } catch (error: Throwable) {
      callbackCoordinator.cancel(token)
      throw error
    }
    val status = callbackCoordinator.await(token)
    if (status != BluetoothGatt.GATT_SUCCESS) {
      throw GattTransportException(TransportFailureCode.DESCRIPTOR_WRITE_FAILED, status)
    }
  }

  private fun characteristic(uuid: java.util.UUID): BluetoothGattCharacteristic =
    gatt?.getService(GattProtocol.SERVICE_UUID)?.getCharacteristic(uuid)
      ?: throw GattTransportException(TransportFailureCode.SERVICE_DISCOVERY_FAILED)

  @Suppress("DEPRECATION")
  private fun writeCharacteristic(
    characteristic: BluetoothGattCharacteristic,
    value: ByteArray,
    connection: GattConnectionCoordinator.Connection,
  ) {
    val activeGatt = gatt ?: throw GattTransportException(TransportFailureCode.DISCONNECTED)
    val started = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      activeGatt.writeCharacteristic(
        characteristic,
        value,
        BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT,
      ) == BluetoothGatt.GATT_SUCCESS
    } else {
      characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
      characteristic.value = value
      activeGatt.writeCharacteristic(characteristic)
    }
    if (!started) {
      callbackCoordinator.currentFailure(connection)?.let { throw it }
      throw GattTransportException(TransportFailureCode.WRITE_FAILED)
    }
  }

  @Suppress("DEPRECATION")
  private fun writeDescriptor(
    descriptor: BluetoothGattDescriptor,
    value: ByteArray,
    connection: GattConnectionCoordinator.Connection,
  ) {
    val activeGatt = gatt ?: throw GattTransportException(TransportFailureCode.DISCONNECTED)
    val started = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      activeGatt.writeDescriptor(descriptor, value) == BluetoothGatt.GATT_SUCCESS
    } else {
      descriptor.value = value
      activeGatt.writeDescriptor(descriptor)
    }
    if (!started) {
      callbackCoordinator.currentFailure(connection)?.let { throw it }
      throw GattTransportException(TransportFailureCode.DESCRIPTOR_WRITE_FAILED)
    }
  }

  private fun activeConnection(): GattConnectionCoordinator.Connection =
    connection ?: throw GattTransportException(TransportFailureCode.DISCONNECTED)

  private fun requireConnectPermission() {
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
      context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
    ) {
      throw SecurityException("Bluetooth connect permission denied")
    }
  }

  private fun callback(connection: GattConnectionCoordinator.Connection) = object : BluetoothGattCallback() {
    override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
      if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
        if (callbackCoordinator.onConnected(connection, gatt) && !gatt.discoverServices()) {
          callbackCoordinator.onServicesFailed(connection, gatt, null)
        }
      } else {
        callbackCoordinator.onDisconnected(connection, gatt, status)
      }
    }

    override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
      if (status == BluetoothGatt.GATT_SUCCESS && gatt.getService(GattProtocol.SERVICE_UUID) != null) {
        callbackCoordinator.onServicesReady(connection, gatt)
      } else {
        callbackCoordinator.onServicesFailed(connection, gatt, status)
      }
    }

    override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
      if (
        status == BluetoothGatt.GATT_SUCCESS &&
        callbackCoordinator.acceptsCallback(connection, gatt)
      ) {
        this@AndroidBleGattTransport.mtu = mtu.coerceAtLeast(23)
      }
    }

    @Deprecated("API 33 callback")
    override fun onCharacteristicRead(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      status: Int,
    ) {
      if (!callbackCoordinator.acceptsCallback(connection, gatt)) return
      if (status == BluetoothGatt.GATT_SUCCESS) {
        connection.mailbox.onFrame(characteristic.value ?: byteArrayOf())
      } else {
        connection.mailbox.onReadFailure(status)
      }
    }

    override fun onCharacteristicRead(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      value: ByteArray,
      status: Int,
    ) {
      if (!callbackCoordinator.acceptsCallback(connection, gatt)) return
      if (status == BluetoothGatt.GATT_SUCCESS) {
        connection.mailbox.onFrame(value)
      } else {
        connection.mailbox.onReadFailure(status)
      }
    }

    @Deprecated("API 33 callback")
    override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
      if (callbackCoordinator.acceptsCallback(connection, gatt)) {
        connection.mailbox.onFrame(characteristic.value ?: byteArrayOf())
      }
    }

    override fun onCharacteristicChanged(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      value: ByteArray,
    ) {
      if (callbackCoordinator.acceptsCallback(connection, gatt)) {
        connection.mailbox.onFrame(value)
      }
    }

    override fun onCharacteristicWrite(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      status: Int,
    ) {
      callbackCoordinator.complete(
        connection,
        gatt,
        GattPendingOperation.CHARACTERISTIC_WRITE,
        characteristic.uuid,
        status,
      )
    }

    override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
      callbackCoordinator.complete(
        connection,
        gatt,
        GattPendingOperation.DESCRIPTOR_WRITE,
        descriptor.characteristic.uuid,
        status,
      )
    }
  }
}

class BluetoothDisabledException : IllegalStateException("Bluetooth disabled")
