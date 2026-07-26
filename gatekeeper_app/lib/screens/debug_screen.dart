import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../services/ble_scanner.dart';

class DebugScreen extends StatefulWidget {
  const DebugScreen({super.key});

  @override
  State<DebugScreen> createState() => _DebugScreenState();
}

class _DebugScreenState extends State<DebugScreen> {
  final BleScanner _scanner = BleScanner();

  // Target 원격 튜닝 입력 변수
  int _selectedTxPower = 9; // dBm (-6, 0, 3, 9)
  double _tofDistanceCm = 50; // cm (5 ~ 200)
  double _durationMs = 60000; // ms (1000 ~ 60000)

  // Target 현재 적용 상태 변수 (서버/Target 실제 반영 상태)
  int _appliedTxPower = 9;
  double _appliedTofDistanceCm = 50;
  double _appliedDurationMs = 60000;
  String _lastSyncTimeStr = '미동기화';

  bool _isSending = false;
  bool _isFetching = false;
  String _targetResponseMsg = '';

  @override
  void initState() {
    super.initState();
    // 디버그 화면 진입 시 고속 저지연 실시간 비콘 스캔 모드로 전환
    _scanner.startScanning(forceRestart: true);
    // 현재 서버/Target에 적용된 실시간 튜닝 설정값 로드
    _fetchAdminConfig();
  }

  Future<void> _fetchAdminConfig() async {
    setState(() {
      _isFetching = true;
    });

    try {
      final url = Uri.parse('${_scanner.backendBaseUrl}/admin/config');
      final response = await http
          .get(url)
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['result'] == 'success') {
          setState(() {
            if (data['tx_power'] != null) {
              _selectedTxPower = data['tx_power'];
              _appliedTxPower = data['tx_power'];
            }
            if (data['tof_distance'] != null) {
              _tofDistanceCm = (data['tof_distance'] as num).toDouble();
              _appliedTofDistanceCm = _tofDistanceCm;
            }
            if (data['duration'] != null) {
              _durationMs = (data['duration'] as num).toDouble();
              _appliedDurationMs = _durationMs;
            }
            final now = DateTime.now();
            _lastSyncTimeStr = '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
            _targetResponseMsg = '🔄 최신 실시간 설정 동기화 완료 ($_lastSyncTimeStr)\n[적용 상태] Tx: ${_appliedTxPower}dBm | ToF: ${_appliedTofDistanceCm.round()}cm | Duration: ${(_appliedDurationMs / 1000).round()}s';
          });
        }
      }
    } catch (e) {
      debugPrint('[DebugScreen] _fetchAdminConfig 에러: $e');
    } finally {
      if (mounted) {
        setState(() {
          _isFetching = false;
        });
      }
    }
  }

  Future<void> _sendAdminConfig() async {
    setState(() {
      _isSending = true;
      _targetResponseMsg = '전송 중...';
    });

    try {
      final url = Uri.parse('${_scanner.backendBaseUrl}/admin/config');
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'tx_power': _selectedTxPower,
              'tof_distance': _tofDistanceCm.toInt(),
              'duration': _durationMs.toInt(),
            }),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final now = DateTime.now();
        final timeStr = '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
        setState(() {
          _appliedTxPower = _selectedTxPower;
          _appliedTofDistanceCm = _tofDistanceCm;
          _appliedDurationMs = _durationMs;
          _lastSyncTimeStr = timeStr;
          _targetResponseMsg = '✅ Target 파라미터 전송 & 실시간 적용 완료! ($timeStr)\n[적용 중] Tx: ${_appliedTxPower}dBm | ToF: ${_appliedTofDistanceCm.round()}cm | Duration: ${(_appliedDurationMs / 1000).round()}s';
        });
      } else {
        setState(() {
          _targetResponseMsg = '❌ 실패 (HTTP ${response.statusCode}): ${response.body}';
        });
      }
    } catch (e) {
      setState(() {
        _targetResponseMsg = '🚨 통신 오류: $e';
      });
    } finally {
      setState(() {
        _isSending = false;
      });
    }
  }


  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: AppBar(
        title: const Text('🔧 엔지니어 디버그 & 튜닝'),
        backgroundColor: const Color(0xFF1E1E1E),
        elevation: 0,
        actions: [
          IconButton(
            icon: _isFetching
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.cyanAccent))
                : const Icon(Icons.refresh, color: Colors.cyanAccent),
            tooltip: '최신 튜닝 설정 새로고침',
            onPressed: _isFetching ? null : _fetchAdminConfig,
          ),
        ],
      ),

      body: SafeArea(
        bottom: true,
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [

            // ─── SECTION 1: 실시간 RSSI 모니터 ───────────────────
            _buildRssiMonitorCard(),

            const SizedBox(height: 16),

            // ─── SECTION 2: 로컬 파라미터 조절 UI ─────────────────
            _buildLocalConfigCard(),

            const SizedBox(height: 16),

            // ─── SECTION 3: Target 원격 제어 UI ─────────────────
            _buildTargetRemoteControlCard(),
          ],
        ),
      ),
    );
  }

  Widget _buildRssiMonitorCard() {
    return ValueListenableBuilder<bool>(
      valueListenable: _scanner.isBeaconConnected,
      builder: (context, isConnected, _) {
        return ValueListenableBuilder<int>(
          valueListenable: _scanner.packetCount,
          builder: (context, count, _) {
            final rssi = isConnected ? _scanner.liveRssi.value : null;
            final lastTime = _scanner.lastRssiUpdateTime.value;
            final String timeStr = (isConnected && lastTime != null)
                ? '${lastTime.hour.toString().padLeft(2, '0')}:${lastTime.minute.toString().padLeft(2, '0')}:${lastTime.second.toString().padLeft(2, '0')}.${(lastTime.millisecond ~/ 100)}'
                : '미수신 (연결 안됨)';

            Color badgeColor = Colors.grey;
            String badgeText = '🔴 신호 없음 (연결 안됨)';

            if (isConnected && rssi != null) {
              if (rssi >= -60) {
                badgeColor = Colors.green;
                badgeText = '🟢 매우 강함 (근접)';
              } else if (rssi >= -75) {
                badgeColor = Colors.blue;
                badgeText = '🔵 보통 (감지 범위)';
              } else {
                badgeColor = Colors.orange;
                badgeText = '🟠 약함 (경계)';
              }
            }

            return Card(
              color: const Color(0xFF1E1E1E),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          '📡 실시간 비콘 RSSI 모니터',
                          style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: badgeColor.withOpacity(0.2),
                            border: Border.all(color: badgeColor),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            badgeText,
                            style: TextStyle(color: badgeColor, fontSize: 12, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    Text(
                      (isConnected && rssi != null) ? '$rssi dBm' : '연결 안됨',
                      style: TextStyle(
                        fontSize: (isConnected && rssi != null) ? 48 : 36,
                        fontWeight: FontWeight.bold,
                        color: (isConnected && rssi != null) ? Colors.cyanAccent : Colors.redAccent,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      isConnected
                          ? 'UUID: ${_scanner.targetBeaconUuid}\n수신 시각: $timeStr | 누적 패킷: $count개'
                          : 'Target 비콘 UUID (${_scanner.targetBeaconUuid}) 미수신 중...\n수신을 멈추고 연결 대기 중입니다.',
                      style: const TextStyle(fontSize: 12, color: Colors.grey),
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }



  Widget _buildLocalConfigCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '📱 앱 로컬 동작 파라미터 조절',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('동적 RSSI Threshold:', style: TextStyle(color: Colors.white70)),
                Text(
                  '${_scanner.rssiThreshold} dBm',
                  style: const TextStyle(color: Colors.cyanAccent, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            Slider(
              value: _scanner.rssiThreshold.toDouble(),
              min: -90.0,
              max: -30.0,
              divisions: 60,
              activeColor: Colors.cyan,
              label: '${_scanner.rssiThreshold} dBm',
              onChanged: (val) {
                setState(() {
                  _scanner.setRssiThreshold(val.round());
                });
              },
            ),
            const Divider(color: Colors.white10),
            CheckboxListTile(
              title: const Text('스마트 쿨다운 무시 (Ignore Cooldown)', style: TextStyle(color: Colors.white, fontSize: 14)),
              subtitle: const Text('체크 시 문 열기 직후에도 쿨다운 없이 비콘 API 연타 가능', style: TextStyle(color: Colors.grey, fontSize: 12)),
              value: _scanner.ignoreCooldown,
              activeColor: Colors.amber.shade800,
              onChanged: (val) {
                setState(() {
                  _scanner.setIgnoreCooldown(val ?? false);
                });
              },
            ),

          ],
        ),
      ),
    );
  }

  Widget _buildTargetRemoteControlCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '🎯 Target (ESP32-C6) 원격 튜닝',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: Colors.white),
            ),
            const SizedBox(height: 12),
            _buildActiveTargetStatusBox(),
            const SizedBox(height: 16),

            const SizedBox(height: 16),
            const Text('1. BLE Tx Power 출력:', style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [-6, 0, 3, 9].map((pwr) {
                final isSelected = _selectedTxPower == pwr;
                return ChoiceChip(
                  label: Text('$pwr dBm'),
                  selected: isSelected,
                  selectedColor: Colors.cyan,
                  backgroundColor: Colors.grey.shade800,
                  labelStyle: TextStyle(color: isSelected ? Colors.black : Colors.white),
                  onSelected: (selected) {
                    if (selected) {
                      setState(() {
                        _selectedTxPower = pwr;
                      });
                    }
                  },
                );
              }).toList(),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('2. ToF 감지 기준 거리:', style: TextStyle(color: Colors.white70, fontSize: 13)),
                Text('${_tofDistanceCm.round()} cm', style: const TextStyle(color: Colors.cyanAccent, fontWeight: FontWeight.bold)),
              ],
            ),
            Slider(
              value: _tofDistanceCm,
              min: 10,
              max: 150,
              divisions: 28,
              activeColor: Colors.cyan,
              label: '${_tofDistanceCm.round()} cm',
              onChanged: (val) {
                setState(() {
                  _tofDistanceCm = val;
                });
              },
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('3. Pre-arm 무장 유지 시간:', style: TextStyle(color: Colors.white70, fontSize: 13)),
                Text('${(_durationMs / 1000).toStringAsFixed(1)} 초 (${_durationMs.round()} ms)', style: const TextStyle(color: Colors.cyanAccent, fontWeight: FontWeight.bold)),
              ],
            ),
            Slider(
              value: _durationMs,
              min: 3000,
              max: 60000,
              divisions: 57,
              activeColor: Colors.cyan,
              label: '${(_durationMs / 1000).round()}초',
              onChanged: (val) {
                setState(() {
                  _durationMs = val;
                });
              },
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _isFetching ? null : _fetchAdminConfig,
                    icon: _isFetching
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.cyan))
                        : const Icon(Icons.sync, color: Colors.cyan),
                    label: const Text('현재 설정 불러오기', style: TextStyle(color: Colors.cyan, fontSize: 13, fontWeight: FontWeight.bold)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.cyan),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _isSending ? null : _sendAdminConfig,
                    icon: _isSending
                        ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                        : const Icon(Icons.send),
                    label: const Text('Target 파라미터 전송', style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.cyan,
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ),
              ],
            ),

            if (_targetResponseMsg.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.black38,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.white24),
                ),
                child: Text(
                  _targetResponseMsg,
                  style: const TextStyle(fontSize: 13, color: Colors.white),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildActiveTargetStatusBox() {

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.black45,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.cyan.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  const Icon(Icons.check_circle_outline, color: Colors.greenAccent, size: 16),
                  const SizedBox(width: 6),
                  const Text(
                    'Target 현재 적용 상태 (Live Applied)',
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: Colors.cyanAccent),
                  ),
                ],
              ),


              Text(
                _lastSyncTimeStr,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildActiveParamItem('Tx Power', '$_appliedTxPower dBm', Colors.amberAccent),
              Container(width: 1, height: 28, color: Colors.white12),
              _buildActiveParamItem('ToF 거리', '${_appliedTofDistanceCm.round()} cm', Colors.greenAccent),
              Container(width: 1, height: 28, color: Colors.white12),
              _buildActiveParamItem('Pre-arm 시간', '${(_appliedDurationMs / 1000).round()} 초', Colors.cyanAccent),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildActiveParamItem(String label, String value, Color color) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 3),
        Text(value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: color)),
      ],
    );
  }
}

