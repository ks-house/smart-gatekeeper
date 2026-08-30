import '../l10n/generated/app_localizations.dart';

enum HomeMessageKind {
  statusRefreshing,
  backendUnavailable,
  statusUpdated,
  credentialEnrolling,
  credentialEnrollmentComplete,
  manualOpenRequesting,
  manualOpenCommandExecuted,
  manualOpenOutcomeUnknown,
  failure,
}

class HomeMessage {
  const HomeMessage(
    this.kind, {
    this.reason,
    this.latencyMs,
  });

  final HomeMessageKind kind;
  final String? reason;
  final int? latencyMs;

  String resolve(AppLocalizations strings) {
    return switch (kind) {
      HomeMessageKind.statusRefreshing => strings.statusRefreshing,
      HomeMessageKind.backendUnavailable => strings.backendUnavailableRetry,
      HomeMessageKind.statusUpdated => strings.statusUpdated,
      HomeMessageKind.credentialEnrolling => strings.credentialEnrolling,
      HomeMessageKind.credentialEnrollmentComplete =>
        strings.credentialEnrollmentComplete,
      HomeMessageKind.manualOpenRequesting => strings.manualOpenRequesting,
      HomeMessageKind.manualOpenCommandExecuted =>
        '${strings.manualOpenCommandExecuted}${_latencySuffix()}',
      HomeMessageKind.manualOpenOutcomeUnknown =>
        strings.manualOpenOutcomeUnknown,
      HomeMessageKind.failure => friendlyFailure(reason ?? '', strings),
    };
  }

  String _latencySuffix() => latencyMs == null ? '' : ' (${latencyMs}ms)';
}

String friendlyFailure(String reason, AppLocalizations strings) {
  if (reason.contains('BLUETOOTH')) return strings.bluetoothRequired;
  if (reason.contains('PERMISSION')) return strings.permissionsRequired;
  if (reason.contains('BATTERY')) return strings.batteryRestrictionRequired;
  if (reason.contains('TARGET_UNAVAILABLE')) return strings.targetUnavailable;
  if (reason.contains('REVOKED') || reason.contains('INACTIVE')) {
    return strings.smartKeyPermissionCheck;
  }
  if (reason.contains('PROOF') || reason.contains('UNCERTAIN')) {
    return strings.manualOpenOutcomeUnknown;
  }
  if (reason.contains('TIMEOUT')) return strings.targetResponseTimeout;
  return strings.requestFailedGeneric;
}
