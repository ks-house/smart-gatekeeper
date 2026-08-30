package com.kshouse.gatekeeper_app

import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import com.kshouse.gatekeeper_app.gattworker.BleGattFeatureFlagStore
import com.kshouse.gatekeeper_app.gattworker.BleGattHealthBridge
import com.kshouse.gatekeeper_app.gattworker.BleGattManualOpenExecutor
import com.kshouse.gatekeeper_app.gattworker.RemoteManualOpenProofSigner
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

import com.kshouse.gatekeeper_app.gattworker.BleGattWorkScheduler
import com.kshouse.gatekeeper_app.blewake.BleWakeRegistrar
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class MainActivity: FlutterActivity() {
    private val nativeActionScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private companion object {
        const val CHANNEL_DIAGNOSTICS = "com.kshouse.gatekeeper_app/notification_channel"
        const val CHANNEL_GATT_WORKER_HEALTH =
            "com.kshouse.gatekeeper_app/ble_gatt_worker_health"
        const val CHANNEL_WAKE_REGISTRATION =
            "com.kshouse.gatekeeper_app/ble_wake_registration"
        const val CHANNEL_UPDATE_SECURITY =
            "com.kshouse.gatekeeper_app/update_security"
        const val CHANNEL_BACKGROUND_REQUIREMENTS =
            "com.kshouse.gatekeeper_app/background_requirements"
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
                "triggerLocalGattOpen" -> {
                    nativeActionScope.launch {
                        result.success(
                            BleGattManualOpenExecutor.execute(applicationContext).toMap(),
                        )
                    }
                }
                "signRemoteManualOpen" -> {
                    val nonce = call.argument<String>("nonce")
                    val expiresAt = call.argument<Number>("expiresAt")?.toLong()
                    val reason = call.argument<String>("reason")
                    val idempotencyKey = call.argument<String>("idempotencyKey")
                    if (nonce == null || expiresAt == null || reason == null || idempotencyKey == null) {
                        result.error("INVALID_ARGUMENT", "remote proof fields are required", null)
                    } else {
                        result.success(
                            RemoteManualOpenProofSigner.sign(
                                applicationContext,
                                nonce,
                                expiresAt,
                                reason,
                                idempotencyKey,
                            ).toMap(),
                        )
                    }
                }
                "prepareLocalGattEnrollment" -> {
                    val material = BleGattFeatureFlagStore(applicationContext)
                        .prepareLocalEnrollmentMaterial()
                    result.success(
                        mapOf(
                            "accepted" to material.accepted,
                            "reason" to material.reason,
                            "credentialId" to material.credentialIdHex,
                            "publicKeySec1" to material.publicKeySec1Hex,
                            "minProtocol" to 1,
                            "maxProtocol" to 1,
                        ),
                    )
                }
                "setLocalGattEnabled" -> {
                    val enabled = call.argument<Boolean>("enabled")
                    if (enabled == null) {
                        result.error("INVALID_ARGUMENT", "enabled must be a boolean", null)
                    } else {
                        val control = BleGattFeatureFlagStore(applicationContext)
                            .setLocalManualEnabled(enabled)
                        val wakeRegistration = when {
                            enabled && control.accepted && control.decision.newWorkerEnabled ->
                                BleWakeRegistrar.register(applicationContext)
                            !enabled && control.accepted ->
                                BleWakeRegistrar.stop(applicationContext)
                            else -> BleWakeRegistrar.status(applicationContext)
                        }
                        result.success(
                            BleGattHealthBridge.snapshot(applicationContext) + mapOf(
                                "accepted" to control.accepted,
                                "reason" to control.reason,
                                "wakeRegistrationStatus" to wakeRegistration.status,
                                "wakeRegistered" to wakeRegistration.enabled,
                            ),
                        )
                    }
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
            try {
                when (call.method) {
                    "apkCertificateSha256" -> {
                        val path = call.argument<String>("path")
                        if (path.isNullOrBlank() || !File(path).isFile) {
                            result.error("APK_MISSING", "APK is not available", null)
                            return@setMethodCallHandler
                        }
                        result.success(archiveCertificateSha256(path))
                    }
                    "installedPackageIdentity" -> {
                        result.success(installedPackageIdentity())
                    }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) {
                result.error(
                    "PACKAGE_IDENTITY_INVALID",
                    "APK package identity could not be verified",
                    error.javaClass.simpleName,
                )
            }
        }

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            CHANNEL_BACKGROUND_REQUIREMENTS,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "isIgnoringBatteryOptimizations" -> {
                    val power = getSystemService(PowerManager::class.java)
                    result.success(power.isIgnoringBatteryOptimizations(packageName))
                }
                "requestIgnoreBatteryOptimizations" -> {
                    val power = getSystemService(PowerManager::class.java)
                    if (!power.isIgnoringBatteryOptimizations(packageName)) {
                        val intent = Intent(
                            BatteryOptimizationRequestPolicy
                                .ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse(
                                BatteryOptimizationRequestPolicy.packageUri(packageName),
                            ),
                        )
                        startActivity(intent)
                    }
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onDestroy() {
        nativeActionScope.cancel()
        super.onDestroy()
    }

    private fun archiveCertificateSha256(path: String): String {
        val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getPackageArchiveInfo(
                path,
                PackageManager.PackageInfoFlags.of(
                    PackageManager.GET_SIGNING_CERTIFICATES.toLong(),
                ),
            )
        } else {
            @Suppress("DEPRECATION")
            packageManager.getPackageArchiveInfo(
                path,
                PackageManager.GET_SIGNING_CERTIFICATES,
            )
        }
        return certificateSha256(requireNotNull(packageInfo))
    }

    private fun installedPackageIdentity(): Map<String, Any> {
        val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getPackageInfo(
                packageName,
                PackageManager.PackageInfoFlags.of(
                    PackageManager.GET_SIGNING_CERTIFICATES.toLong(),
                ),
            )
        } else {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(
                packageName,
                PackageManager.GET_SIGNING_CERTIFICATES,
            )
        }
        val source = File(requireNotNull(packageInfo.applicationInfo?.sourceDir))
        require(source.isFile) { "Installed APK source is unavailable" }
        val buildNumber = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }
        return mapOf(
            "buildNumber" to buildNumber,
            "versionName" to requireNotNull(packageInfo.versionName),
            "sourceSha256" to sha256(source),
            "certificateSha256" to certificateSha256(packageInfo),
        )
    }

    private fun certificateSha256(packageInfo: PackageInfo): String {
        val signers: Array<Signature>? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.signingInfo?.apkContentsSigners
        } else {
            @Suppress("DEPRECATION")
            packageInfo.signatures
        }
        val bytes = UpdatePackageIdentityPolicy.requireSingleSigner(
            actualPackageName = packageInfo.packageName,
            expectedPackageName = packageName,
            signerCertificates = signers?.map { it.toByteArray() }.orEmpty(),
        )
        return MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

}
