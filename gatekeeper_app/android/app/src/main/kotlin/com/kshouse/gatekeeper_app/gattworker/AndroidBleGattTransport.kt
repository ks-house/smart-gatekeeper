package com.kshouse.gatekeeper_app.gattworker

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import java.util.concurrent.atomic.AtomicInteger

class AndroidBleGattTransport(private val context: Context) : BleGattTransport {
  private val messageId = AtomicInteger(1)
  private val inbox = Channel<Pair<Int, ByteArray>>(Channel.BUFFERED)
  private val writeResult = Channel<Int>(Channel.BUFFERED)
  private val descriptorResult = Channel<Int>(Channel.BUFFERED)
  private val connected = CompletableDeferred<Unit>()
  private val servicesReady = CompletableDeferred<Unit>()
  private val reassembler = GattReassembler()
  private var gatt: BluetoothGatt? = null
  private var mtu = 23

  override suspend fun connect(deviceAddress: String) {
    requireConnectPermission()
    val manager = context.getSystemService(BluetoothManager::class.java)
      ?: throw IllegalStateException("Bluetooth unavailable")
    val adapter = manager.adapter ?: throw IllegalStateException("Bluetooth unavailable")
    if (!adapter.isEnabled) throw BluetoothDisabledException()
    val device = adapter.getRemoteDevice(deviceAddress)
    gatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
      device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
    } else {
      @Suppress("DEPRECATION")
      device.connectGatt(context, false, callback)
    }
    connected.await()
    servicesReady.await()
    enableIndication(GattProtocol.HELLO_UUID)
    enableIndication(GattProtocol.CHALLENGE_UUID)
    enableIndication(GattProtocol.RESULT_UUID)
  }

  override suspend fun negotiate(clientHello: ByteArray): ByteArray {
    writeMessage(GattProtocol.HELLO_UUID, GattProtocol.CLIENT_HELLO, clientHello)
    return awaitMessage(GattProtocol.TARGET_HELLO)
  }

  override suspend fun readChallenge(): ByteArray {
    val characteristic = characteristic(GattProtocol.CHALLENGE_UUID)
    val started = gatt?.readCharacteristic(characteristic) == true
    if (!started) throw IllegalStateException("challenge read rejected")
    return awaitMessage(GattProtocol.CHALLENGE)
  }

  override suspend fun writeProof(proof: ByteArray) {
    writeMessage(GattProtocol.PROOF_UUID, GattProtocol.PROOF, proof)
  }

  override suspend fun awaitResult(): ByteArray = awaitMessage(GattProtocol.RESULT)

  override fun close() {
    try {
      gatt?.disconnect()
    } catch (_: SecurityException) {
      // Permission revocation is already represented by the session reason.
    }
    gatt?.close()
    gatt = null
  }

  private suspend fun writeMessage(uuid: java.util.UUID, type: Int, payload: ByteArray) {
    val id = messageId.getAndUpdate { if (it == 0xffff) 1 else it + 1 }
    for (frame in GattFraming.fragment(type, id, payload, mtu)) {
      writeCharacteristic(characteristic(uuid), frame)
      if (writeResult.receive() != BluetoothGatt.GATT_SUCCESS) {
        throw IllegalStateException("GATT write failed")
      }
    }
  }

  private suspend fun awaitMessage(expectedType: Int): ByteArray {
    while (true) {
      val (type, payload) = inbox.receive()
      if (type == expectedType) return payload
      if (type == 0x7f) throw IllegalArgumentException("Target protocol error")
    }
  }

  private fun acceptFrame(value: ByteArray) {
    try {
      reassembler.accept(value)?.let(inbox::trySend)
    } catch (_: IllegalArgumentException) {
      inbox.trySend(0x7f to byteArrayOf())
    }
  }

  private suspend fun enableIndication(uuid: java.util.UUID) {
    val characteristic = characteristic(uuid)
    if (gatt?.setCharacteristicNotification(characteristic, true) != true) {
      throw IllegalStateException("indication enable rejected")
    }
    val descriptor = characteristic.getDescriptor(GattProtocol.CCCD_UUID)
      ?: throw IllegalStateException("CCCD missing")
    writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_INDICATION_VALUE)
    if (descriptorResult.receive() != BluetoothGatt.GATT_SUCCESS) {
      throw IllegalStateException("CCCD write failed")
    }
  }

  private fun characteristic(uuid: java.util.UUID): BluetoothGattCharacteristic =
    gatt?.getService(GattProtocol.SERVICE_UUID)?.getCharacteristic(uuid)
      ?: throw IllegalStateException("auth characteristic unavailable")

  @Suppress("DEPRECATION")
  private fun writeCharacteristic(characteristic: BluetoothGattCharacteristic, value: ByteArray) {
    val activeGatt = gatt ?: throw GattDisconnectedException()
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
    if (!started) throw IllegalStateException("GATT write rejected")
  }

  @Suppress("DEPRECATION")
  private fun writeDescriptor(descriptor: BluetoothGattDescriptor, value: ByteArray) {
    val activeGatt = gatt ?: throw GattDisconnectedException()
    val started = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
      activeGatt.writeDescriptor(descriptor, value) == BluetoothGatt.GATT_SUCCESS
    } else {
      descriptor.value = value
      activeGatt.writeDescriptor(descriptor)
    }
    if (!started) throw IllegalStateException("descriptor write rejected")
  }

  private fun requireConnectPermission() {
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
      context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED
    ) {
      throw SecurityException("Bluetooth connect permission denied")
    }
  }

  private val callback = object : BluetoothGattCallback() {
    override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
      if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
        connected.complete(Unit)
        if (!gatt.discoverServices()) servicesReady.completeExceptionally(IllegalStateException("service discovery rejected"))
      } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
        val error = GattDisconnectedException()
        if (!connected.isCompleted) connected.completeExceptionally(error)
        if (!servicesReady.isCompleted) servicesReady.completeExceptionally(error)
        inbox.trySend(0x7f to byteArrayOf())
      }
    }

    override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
      if (status == BluetoothGatt.GATT_SUCCESS && gatt.getService(GattProtocol.SERVICE_UUID) != null) {
        servicesReady.complete(Unit)
      } else {
        servicesReady.completeExceptionally(IllegalStateException("auth service discovery failed"))
      }
    }

    override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
      if (status == BluetoothGatt.GATT_SUCCESS) this@AndroidBleGattTransport.mtu = mtu.coerceAtLeast(23)
    }

    @Deprecated("API 33 callback")
    override fun onCharacteristicRead(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      status: Int,
    ) {
      if (status == BluetoothGatt.GATT_SUCCESS) acceptFrame(characteristic.value ?: byteArrayOf())
      else inbox.trySend(0x7f to byteArrayOf())
    }

    override fun onCharacteristicRead(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      value: ByteArray,
      status: Int,
    ) {
      if (status == BluetoothGatt.GATT_SUCCESS) acceptFrame(value)
      else inbox.trySend(0x7f to byteArrayOf())
    }

    @Deprecated("API 33 callback")
    override fun onCharacteristicChanged(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
      acceptFrame(characteristic.value ?: byteArrayOf())
    }

    override fun onCharacteristicChanged(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      value: ByteArray,
    ) {
      acceptFrame(value)
    }

    override fun onCharacteristicWrite(
      gatt: BluetoothGatt,
      characteristic: BluetoothGattCharacteristic,
      status: Int,
    ) {
      writeResult.trySend(status)
    }

    override fun onDescriptorWrite(gatt: BluetoothGatt, descriptor: BluetoothGattDescriptor, status: Int) {
      descriptorResult.trySend(status)
    }
  }
}

class BluetoothDisabledException : IllegalStateException("Bluetooth disabled")
