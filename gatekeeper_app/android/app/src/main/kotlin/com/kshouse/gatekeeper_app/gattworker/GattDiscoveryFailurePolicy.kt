package com.kshouse.gatekeeper_app.gattworker

/** Android GATT_SUCCESS is zero; preserve status and phase without inferring a cache cause. */
internal object GattDiscoveryFailurePolicy {
  fun callback(status: Int, servicePresent: Boolean): TransportFailureCode? = when {
    status != 0 -> TransportFailureCode.SERVICE_DISCOVERY_CALLBACK_FAILED
    !servicePresent -> TransportFailureCode.SERVICE_MISSING
    else -> null
  }
}
