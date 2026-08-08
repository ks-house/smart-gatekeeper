package com.kshouse.gatekeeper_app

import android.app.NotificationManager
import android.os.Build
import com.kshouse.gatekeeper_app.gattworker.BleGattHealthBridge
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler
import com.kshouse.gatekeeper_app.blewake.BleWakeRegistrar
import java.io.File
import java.security.MessageDigest

class MainActivity: FlutterActivity() {
    private companion object {
        const val CHANNEL_DIAGNOSTICS = "com.kshouse.gatekeeper_app/notification_channel"
        const val CHANNEL_GATT_WORKER_HEALTH =
            "com.kshouse.gatekeeper_app/ble_gatt_worker_health"
        const val CHANNEL_WAKE_REGISTRATION =
            "com.kshouse.gatekeeper_app/ble_wake_registration"
        const val CHANNEL_UPDATE_SECURITY =
            "com.kshouse.gatekeeper_app/update_security"
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
                    result.success(BleGattWorkScheduler.manualRetry(applicationContext).toMap())
                }
                else -> {
                    result.notImplemented()
                }
            }
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_WAKE_REGISTRATION,
        ).setMethodCallHandler { call, result ->
            val registration = when (call.method) {
                "register" -> BleWakeRegistrar.register(applicationContext)
                "stop" -> BleWakeRegistrar.stop(applicationContext)
                "getStatus" -> BleWakeRegistrar.status(applicationContext)
                else -> {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
            }
            result.success(registration.toMap())
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_UPDATE_SECURITY,
        ).setMethodCallHandler { call, result ->
            if (call.method != "apkCertificateSha256") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val path = call.argument<String>("path")
            if (path.isNullOrBlank() || !File(path).isFile) {
                result.error("APK_MISSING", "APK is not available", null)
                return@setMethodCallHandler
            }
            try {
                val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    packageManager.getPackageArchiveInfo(
                        path,
                        android.content.pm.PackageManager.PackageInfoFlags.of(
                            android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES.toLong(),
                        ),
                    )
                } else {
                    @Suppress("DEPRECATION")
                    packageManager.getPackageArchiveInfo(
                        path,
                        android.content.pm.PackageManager.GET_SIGNING_CERTIFICATES,
                    )
                }
                if (packageInfo == null || packageInfo.packageName != packageName) {
                    result.error("PACKAGE_MISMATCH", "APK package identity does not match", null)
                    return@setMethodCallHandler
                }
                val signers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    packageInfo.signingInfo?.apkContentsSigners
                } else {
                    @Suppress("DEPRECATION")
                    packageInfo.signatures
                }
                if (signers?.size != 1) {
                    result.error("SIGNER_COUNT_INVALID", "APK must have exactly one current signer", null)
                    return@setMethodCallHandler
                }
                val signer = signers.first()
                if (signer.toByteArray().isEmpty()) {
                    result.error("CERTIFICATE_MISSING", "APK certificate is missing", null)
                } else {
                    result.success(MessageDigest.getInstance("SHA-256").digest(signer.toByteArray()).joinToString("") { "%02x".format(it) })
                }
            } catch (error: Exception) {
                result.error("CERTIFICATE_INVALID", "APK certificate could not be read", error.javaClass.simpleName)
            }
        }
    }


}
