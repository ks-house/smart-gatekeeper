package com.kshouse.gatekeeper_app.blewake

import java.util.UUID

/** Stable bytes shared by the Target iBeacon advertisement and Android wake filter. */
object BleWakeContract {
  const val APPLE_COMPANY_ID = 0x004C
  const val IBEACON_TYPE = 0x02
  const val IBEACON_UUID_LENGTH = 0x15
  const val TARGET_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

  val manufacturerDataPrefix: ByteArray
    get() = byteArrayOf(IBEACON_TYPE.toByte(), IBEACON_UUID_LENGTH.toByte()) + uuidBytes(TARGET_UUID)

  val manufacturerDataMask: ByteArray
    get() = ByteArray(manufacturerDataPrefix.size) { 0xFF.toByte() }

  fun uuidBytes(value: String): ByteArray {
    val uuid = UUID.fromString(value)
    return ByteArray(16) { index ->
      val shift = if (index < 8) 56 - index * 8 else 56 - (index - 8) * 8
      val source = if (index < 8) uuid.mostSignificantBits else uuid.leastSignificantBits
      (source ushr shift).toByte()
    }
  }

  fun matchesManufacturerData(data: ByteArray?): Boolean {
    if (data == null || data.size < manufacturerDataPrefix.size) return false
    return manufacturerDataPrefix.indices.all { index ->
      (data[index].toInt() and manufacturerDataMask[index].toInt()) ==
        (manufacturerDataPrefix[index].toInt() and manufacturerDataMask[index].toInt())
    }
  }
}
