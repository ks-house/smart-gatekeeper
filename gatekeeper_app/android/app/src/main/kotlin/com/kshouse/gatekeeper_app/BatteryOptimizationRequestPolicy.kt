package com.kshouse.gatekeeper_app

object BatteryOptimizationRequestPolicy {
    const val ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS =
        "android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS"

    fun packageUri(packageName: String): String {
        require(packageName.matches(Regex("^[A-Za-z][A-Za-z0-9_.]{2,254}$"))) {
            "invalid Android package name"
        }
        return "package:$packageName"
    }
}
