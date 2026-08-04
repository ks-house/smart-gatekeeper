package com.kshouse.gatekeeper_app

import android.app.NotificationManager
import android.os.Build
import com.kshouse.gatekeeper_app.gattworker.BleGattHealthBridge
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler

class MainActivity: FlutterActivity() {
    private companion object {
        const val CHANNEL_DIAGNOSTICS = "com.kshouse.gatekeeper_app/notification_channel"
        const val CHANNEL_GATT_WORKER_HEALTH =
            "com.kshouse.gatekeeper_app/ble_gatt_worker_health"
        const val FOREGROUND_NOTIFICATION_CHANNEL = "smart_key_foreground_channel_v2"
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_DIAGNOSTICS,
        ).setMethodCallHandler { call, result ->
            if (call.method != "getNotificationChannelState") {
                result.notImplemented()
                return@setMethodCallHandler
            }

            val notificationManager = getSystemService(NotificationManager::class.java)
            val appNotificationsEnabled = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                notificationManager.areNotificationsEnabled()
            } else {
                true
            }
            val channel = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                notificationManager.getNotificationChannel(FOREGROUND_NOTIFICATION_CHANNEL)
            } else {
                null
            }

            result.success(
                mapOf(
                    "appNotificationsEnabled" to appNotificationsEnabled,
                    "channelExists" to (channel != null),
                    "importance" to channel?.importance,
                    "channelBlocked" to (channel?.importance == NotificationManager.IMPORTANCE_NONE),
                ),
            )
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_GATT_WORKER_HEALTH,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "getHealth" -> {
                    result.success(BleGattHealthBridge.snapshot(applicationContext))
                }
                "triggerLocalGattRetry" -> {
                    val scheduled = BleGattWorkScheduler.onPresence(
                        applicationContext,
                        "TARGET_LOCAL",
                        "manual_retry_" + System.currentTimeMillis(),
                    )
                    result.success(scheduled != null)
                }
                else -> {
                    result.notImplemented()
                }
            }
        }
    }


}
