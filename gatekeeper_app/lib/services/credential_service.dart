import 'package:shared_preferences/shared_preferences.dart';
import 'device_id_service.dart';

enum TenantApprovalStatus {
  pending,
  approved,
  revoked,
  unregistered,
}

class CredentialService {
  static final CredentialService _instance = CredentialService._internal();
  factory CredentialService() => _instance;
  CredentialService._internal();

  TenantApprovalStatus approvalStatus = TenantApprovalStatus.unregistered;
  String tenantName = '';
  String roomNumber = '';
  String? deviceId;
  String aclVersion = 'v1.0';
  int aclExpiresAtEpoch = 0;

  Future<void> loadCredentialInfo() async {
    deviceId = await DeviceIdService.getDeviceId();
    final prefs = await SharedPreferences.getInstance();
    final statusStr =
        prefs.getString('tenant_approval_status') ?? 'unregistered';
    switch (statusStr) {
      case 'approved':
        approvalStatus = TenantApprovalStatus.approved;
        break;
      case 'pending':
        approvalStatus = TenantApprovalStatus.pending;
        break;
      case 'revoked':
        approvalStatus = TenantApprovalStatus.revoked;
        break;
      default:
        approvalStatus = TenantApprovalStatus.unregistered;
        break;
    }
    tenantName = prefs.getString('tenant_name') ?? '';
    roomNumber = prefs.getString('room_number') ?? '';
    aclVersion = prefs.getString('acl_version') ?? 'v1.0';
    aclExpiresAtEpoch = prefs.getInt('acl_expires_at') ??
        (DateTime.now().millisecondsSinceEpoch ~/ 1000 + 3600);
  }

  Future<void> saveRegistrationRequest(String name, String room) async {
    tenantName = name;
    roomNumber = room;
    approvalStatus = TenantApprovalStatus.pending;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('tenant_name', name);
    await prefs.setString('room_number', room);
    await prefs.setString('tenant_approval_status', 'pending');
  }

  Future<void> updateStatus(TenantApprovalStatus status) async {
    approvalStatus = status;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('tenant_approval_status', status.name);
  }
}
