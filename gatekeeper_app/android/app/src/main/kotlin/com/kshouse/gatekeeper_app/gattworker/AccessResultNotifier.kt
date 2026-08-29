package com.kshouse.gatekeeper_app.gattworker

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.kshouse.gatekeeper_app.MainActivity
import com.kshouse.gatekeeper_app.R

data class UserAccessNotice(
  val title: String,
  val detail: String,
  val isFailure: Boolean,
)

object AccessResultNotificationPolicy {
  fun forState(state: DurableSessionState, reason: String? = null): UserAccessNotice? = when (state) {
    DurableSessionState.SUCCEEDED -> UserAccessNotice(
      "출입 준비 완료",
      "Target 인증이 완료되었습니다. 문 앞 센서에 접근하세요.",
      false,
    )
    DurableSessionState.PROOF_UNCERTAIN -> UserAccessNotice(
      "결과 확인 필요",
      "Target 결과를 확인할 수 없습니다. 자동으로 다시 시도하지 마세요.",
      true,
    )
    DurableSessionState.FAILED -> UserAccessNotice(
      "스마트키 인증 실패",
      friendlyFailure(reason),
      true,
    )
    DurableSessionState.DISABLED -> UserAccessNotice(
      "자동 출입 비활성",
      "앱에서 Smart Key 설정을 확인해주세요.",
      true,
    )
    else -> null
  }

  private fun friendlyFailure(reason: String?): String = when {
    reason?.contains("BLUETOOTH") == true -> "Bluetooth를 켠 뒤 다시 시도해주세요."
    reason?.contains("PERMISSION") == true -> "필수 권한을 확인해주세요."
    reason?.contains("BATTERY") == true -> "배터리 사용 제한을 해제해주세요."
    reason?.contains("EXPIRED") == true -> "Target 감지 시간이 만료되었습니다."
    reason?.contains("CREDENTIAL") == true -> "스마트키 등록 상태를 확인해주세요."
    else -> "앱의 활동 화면에서 상세 상태를 확인해주세요."
  }
}

object AccessResultNotifier {
  private const val CHANNEL_ID = "smart_key_access_result_v1"
  private const val NOTIFICATION_ID = 7712

  fun createChannel(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val manager = context.getSystemService(NotificationManager::class.java)
    manager.createNotificationChannel(
      NotificationChannel(
        CHANNEL_ID,
        "Smart Key 출입 상태",
        NotificationManager.IMPORTANCE_DEFAULT,
      ).apply {
        description = "Target 감지와 스마트키 인증 결과"
        setShowBadge(false)
      },
    )
  }

  fun post(context: Context, state: DurableSessionState, reason: String? = null) {
    val appContext = context.applicationContext
    val notice = AccessResultNotificationPolicy.forState(state, reason) ?: return
    if (
      Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
      appContext.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
      PackageManager.PERMISSION_GRANTED
    ) return
    createChannel(appContext)
    val intent = Intent(appContext, MainActivity::class.java).apply {
      flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
    }
    val pendingIntent = PendingIntent.getActivity(
      appContext,
      0,
      intent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val notification = NotificationCompat.Builder(appContext, CHANNEL_ID)
      .setSmallIcon(R.mipmap.ic_launcher)
      .setContentTitle(notice.title)
      .setContentText(notice.detail)
      .setStyle(NotificationCompat.BigTextStyle().bigText(notice.detail))
      .setPriority(NotificationCompat.PRIORITY_DEFAULT)
      .setAutoCancel(true)
      .setOnlyAlertOnce(true)
      .setContentIntent(pendingIntent)
      .build()
    NotificationManagerCompat.from(appContext).notify(NOTIFICATION_ID, notification)
  }
}
