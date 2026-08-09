package com.kshouse.gatekeeper_app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class BatteryOptimizationRequestPolicyTest {
    @Test
    fun `uses dedicated battery optimization exemption action`() {
        assertEquals(
            "android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
            BatteryOptimizationRequestPolicy.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
        )
        assertEquals(
            "package:com.kshouse.gatekeeper_app",
            BatteryOptimizationRequestPolicy.packageUri("com.kshouse.gatekeeper_app"),
        )
    }

    @Test
    fun `rejects malformed package names`() {
        assertThrows(IllegalArgumentException::class.java) {
            BatteryOptimizationRequestPolicy.packageUri("package:attacker")
        }
    }
}
