package com.kshouse.gatekeeper_app

import android.app.NotificationManager
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private companion object {
        const val CHANNEL_DIAGNOSTICS = "com.kshouse.gatekeeper_app/notification_channel"
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
    }
}
