import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

class FieldTestMarker {
  const FieldTestMarker({
    required this.ref,
    required this.createdAt,
    required this.expiresAt,
  });

  final String ref;
  final DateTime createdAt;
  final DateTime expiresAt;

  bool isActiveAt(DateTime now) => now.isBefore(expiresAt);

  Map<String, Object?> toJson() => <String, Object?>{
        'ref': ref,
        'created_at': createdAt.toUtc().toIso8601String(),
        'expires_at': expiresAt.toUtc().toIso8601String(),
      };

  static FieldTestMarker? tryParse(Object? value) {
    if (value is! Map) return null;
    final ref = value['ref']?.toString();
    final createdAt = DateTime.tryParse(value['created_at']?.toString() ?? '');
    final expiresAt = DateTime.tryParse(value['expires_at']?.toString() ?? '');
    if (ref == null ||
        !_markerRef.hasMatch(ref) ||
        createdAt == null ||
        expiresAt == null) {
      return null;
    }
    return FieldTestMarker(
        ref: ref, createdAt: createdAt, expiresAt: expiresAt);
  }
}

class FieldDiagnosticsStore {
  static const _uploadEnabledKey = 'field_diagnostics_upload_enabled_v1';
  static const _markerKey = 'field_diagnostics_marker_v1';
  static const _lastUploadedRefKey = 'field_diagnostics_last_uploaded_ref_v1';

  Future<bool> uploadEnabled() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_uploadEnabledKey) ?? false;
  }

  Future<void> setUploadEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_uploadEnabledKey, enabled);
  }

  Future<FieldTestMarker> startMarker({
    DateTime? now,
    Duration duration = const Duration(minutes: 10),
  }) async {
    final timestamp = (now ?? DateTime.now()).toUtc();
    final random = Random.secure();
    final ref = List<int>.generate(8, (_) => random.nextInt(256))
        .map((value) => value.toRadixString(16).padLeft(2, '0'))
        .join();
    final marker = FieldTestMarker(
      ref: ref,
      createdAt: timestamp,
      expiresAt: timestamp.add(duration),
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_markerKey, jsonEncode(marker.toJson()));
    return marker;
  }

  Future<FieldTestMarker?> readMarker() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_markerKey);
    if (raw == null) return null;
    try {
      return FieldTestMarker.tryParse(jsonDecode(raw));
    } catch (_) {
      return null;
    }
  }

  Future<String?> lastUploadedRef() async {
    final prefs = await SharedPreferences.getInstance();
    final value = prefs.getString(_lastUploadedRefKey);
    return value != null && _bundleRef.hasMatch(value) ? value : null;
  }

  Future<void> markUploaded(String bundleRef) async {
    if (!_bundleRef.hasMatch(bundleRef)) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_lastUploadedRefKey, bundleRef);
  }

  Future<void> clearMarker(String markerRef) async {
    final prefs = await SharedPreferences.getInstance();
    FieldTestMarker? current;
    try {
      current = FieldTestMarker.tryParse(
        jsonDecode(prefs.getString(_markerKey) ?? 'null'),
      );
    } catch (_) {
      return;
    }
    if (current?.ref == markerRef) {
      await prefs.remove(_markerKey);
    }
  }
}

final RegExp _markerRef = RegExp(r'^[0-9a-f]{16}$');
final RegExp _bundleRef = RegExp(r'^[0-9a-f]{32}$');
