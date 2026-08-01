// src/GattServer.cpp
// =============================================================
// smart-gatekeeper v2.1 — Hardwareless RC Connectable GATT Transport
// =============================================================
#include "GattServer.h"
#include "DiagnosticsManager.h"
#include "RelayController.h"
#include "MqttManager.h"
#include <esp_random.h>
#include <esp_system.h>
#include <mbedtls/sha256.h>

#define LOGF(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

// Static member initialization
#if ENABLE_HARDWARELESS_RC
bool GattServer::s_enabled = true;
#else
bool GattServer::s_enabled = false;
#endif

bool GattServer::s_connected = false;
uint32_t GattServer::s_active_connections = 0;
bool GattServer::s_ota_busy = false;

GattServer::SessionState GattServer::s_session_state = GattServer::SessionState::IDLE;
uint32_t GattServer::s_session_start_ms = 0;
uint32_t GattServer::s_hello_received_ms = 0;
uint32_t GattServer::s_proof_received_ms = 0;
uint32_t GattServer::s_negotiation_latency_ms = 0;
uint32_t GattServer::s_proof_latency_ms = 0;

uint16_t GattServer::s_selected_protocol = 1;
uint16_t GattServer::s_message_id = 1;
uint8_t  GattServer::s_session_id[16] = {0};
uint8_t  GattServer::s_nonce[32] = {0};
uint8_t  GattServer::s_door_id[16] = {0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6, 0x78, 0x90, 0xAB, 0xCD, 0xEF, 0x12, 0x34, 0x56, 0x78, 0x90};
uint8_t  GattServer::s_negotiation_hash[32] = {0};
uint64_t GattServer::s_expiry_monotonic_ms = 0;

uint32_t GattServer::s_total_sessions = 0;
uint32_t GattServer::s_failed_auth_count = 0;

uint8_t  GattServer::s_reassembly_buf[2048] = {0};
size_t   GattServer::s_reassembly_len = 0;
uint8_t  GattServer::s_expected_frag_index = 0;
uint8_t  GattServer::s_expected_frag_count = 0;
uint16_t GattServer::s_expected_message_id = 0;

uint16_t GattServer::swap16(uint16_t val) {
  return (val << 8) | (val >> 8);
}

uint32_t GattServer::swap32(uint32_t val) {
  return ((val & 0x000000FFU) << 24) |
         ((val & 0x0000FF00U) << 8)  |
         ((val & 0x00FF0000U) >> 8)  |
         ((val & 0xFF000000U) >> 24);
}

uint64_t GattServer::swap64(uint64_t val) {
  return ((val & 0x00000000000000FFULL) << 56) |
         ((val & 0x000000000000FF00ULL) << 40) |
         ((val & 0x0000000000FF0000ULL) << 24) |
         ((val & 0x00000000FF000000ULL) << 8)  |
         ((val & 0x000000FF00000000ULL) >> 8)  |
         ((val & 0x0000FF0000000000ULL) >> 24) |
         ((val & 0x00FF000000000000ULL) >> 40) |
         ((val & 0xFF00000000000000ULL) >> 56);
}

void GattServer::generateCsprng(uint8_t* buf, size_t len) {
  for (size_t i = 0; i < len; i += 4) {
    uint32_t rnd = esp_random();
    size_t chunk = (len - i < 4) ? (len - i) : 4;
    memcpy(buf + i, &rnd, chunk);
  }
}

void GattServer::init() {
  resetSession();
  LOGF("[GATT-SERVER] Initialized (Hardwareless RC compile default: %s, runtime: %s)",
       ENABLE_HARDWARELESS_RC ? "ON" : "OFF", s_enabled ? "ENABLED" : "DISABLED");
}

void GattServer::update() {
  if (!s_enabled) return;

  // Session timeout enforcement (5s challenge expiry or 10s max session timeout)
  if (s_session_state != SessionState::IDLE) {
    uint32_t now = millis();
    if (now - s_session_start_ms > 10000 || (s_expiry_monotonic_ms > 0 && now > s_expiry_monotonic_ms)) {
      LOGF("[GATT-SERVER] Session timed out (state=%d), resetting", static_cast<int>(s_session_state));
      resetSession();
    }
  }
}

bool GattServer::isEnabled() {
  return s_enabled;
}

void GattServer::setEnabled(bool enabled) {
  s_enabled = enabled;
  if (!enabled) {
    resetSession();
  }
  LOGF("[GATT-SERVER] Runtime state changed: %s", enabled ? "ENABLED" : "DISABLED");
}

bool GattServer::isConnected() {
  return s_connected;
}

uint32_t GattServer::getActiveConnections() {
  return s_active_connections;
}

void GattServer::onConnect() {
  s_connected = true;
  s_active_connections++;
  LOGF("[GATT-SERVER] Client connected. Active connections: %lu", (unsigned long)s_active_connections);
}

void GattServer::onDisconnect() {
  s_connected = false;
  if (s_active_connections > 0) s_active_connections--;
  resetSession();
  LOGF("[GATT-SERVER] Client disconnected. Reset session state.");
}

void GattServer::resetSession() {
  s_session_state = SessionState::IDLE;
  s_session_start_ms = 0;
  s_hello_received_ms = 0;
  s_proof_received_ms = 0;
  s_expiry_monotonic_ms = 0;
  s_reassembly_len = 0;
  s_expected_frag_index = 0;
  s_expected_frag_count = 0;
  s_expected_message_id = 0;
  memset(s_session_id, 0, sizeof(s_session_id));
  memset(s_nonce, 0, sizeof(s_nonce));
  memset(s_negotiation_hash, 0, sizeof(s_negotiation_hash));
}

bool GattServer::isOtaBusy() {
  return s_ota_busy;
}

void GattServer::setOtaBusy(bool busy) {
  s_ota_busy = busy;
  if (busy && s_session_state != SessionState::IDLE) {
    LOGF("[GATT-SERVER] OTA busy set, resetting active GATT session");
    resetSession();
  }
}

bool GattServer::handleClientHello(const uint8_t* payload, size_t len, uint8_t* outResp, size_t* outRespLen) {
  if (!s_enabled) return false;
  uint32_t now = millis();

  // Strict payload validation: CLIENT_HELLO canonical payload is 16 bytes
  // protocol_min(u16), protocol_max(u16), framing_min(u8), framing_max(u8), max_rx(u16), caps(u32), build(u32)
  if (len < 16) {
    LOGF("[GATT-SERVER-ERR] CLIENT_HELLO undersized: %u bytes", static_cast<unsigned>(len));
    s_failed_auth_count++;
    return false;
  }

  uint16_t client_min = (payload[0] << 8) | payload[1];
  uint16_t client_max = (payload[2] << 8) | payload[3];
  uint8_t  framing_min = payload[4];
  uint8_t  framing_max = payload[5];
  (void)framing_min;
  (void)framing_max;

  uint16_t target_min = 1;
  uint16_t target_max = 1;
  uint16_t security_floor = 1;

  // N/N-1 Version Negotiation
  // highest(min(client_max, target_max)) subject to >= max(client_min, target_min, floor)
  uint16_t candidate = (client_max < target_max) ? client_max : target_max;
  uint16_t floor_req = (client_min > target_min) ? client_min : target_min;
  if (security_floor > floor_req) floor_req = security_floor;

  uint8_t status = 0; // OK
  if (candidate < floor_req || client_max < target_min || client_min > target_max) {
    status = 1; // UNSUPPORTED_VERSION
    s_selected_protocol = 0;
    LOGF("[GATT-SERVER-WARN] Protocol negotiation failed: client_min=%u, client_max=%u", client_min, client_max);
  } else {
    s_selected_protocol = candidate;
    status = 0;
  }

  s_session_state = SessionState::HELLO_RECEIVED;
  s_session_start_ms = now;
  s_hello_received_ms = now;
  s_total_sessions++;

  // Generate session parameters
  generateCsprng(s_session_id, sizeof(s_session_id));
  generateCsprng(s_nonce, sizeof(s_nonce));

  // Build TARGET_HELLO (20 bytes):
  // selected_protocol(u16), target_protocol_min(u16), target_protocol_max(u16), selected_framing(u8), status(u8), max_rx(u16), caps(u32), firmware_build(u32), security_floor(u16)
  uint8_t target_hello[20] = {0};
  target_hello[0] = (s_selected_protocol >> 8) & 0xFF;
  target_hello[1] = s_selected_protocol & 0xFF;
  target_hello[2] = (target_min >> 8) & 0xFF;
  target_hello[3] = target_min & 0xFF;
  target_hello[4] = (target_max >> 8) & 0xFF;
  target_hello[5] = target_max & 0xFF;
  target_hello[6] = 1; // selected_framing v1
  target_hello[7] = status;
  target_hello[8] = 0x08; // max_rx_message 2048 (0x0800)
  target_hello[9] = 0x00;
  // capabilities (u32 = 0x00000001)
  target_hello[10] = 0x00; target_hello[11] = 0x00; target_hello[12] = 0x00; target_hello[13] = 0x01;
  // firmware_build (u32 = 0x00000210 -> v2.1.0)
  target_hello[14] = 0x00; target_hello[15] = 0x00; target_hello[16] = 0x02; target_hello[17] = 0x10;
  // security_floor (u16 = 1)
  target_hello[18] = (security_floor >> 8) & 0xFF;
  target_hello[19] = security_floor & 0xFF;

  // Compute negotiation_hash = SHA256(CLIENT_HELLO 16B || TARGET_HELLO 20B)
  mbedtls_sha256_context sha_ctx;
  mbedtls_sha256_init(&sha_ctx);
  mbedtls_sha256_starts(&sha_ctx, 0);
  mbedtls_sha256_update(&sha_ctx, payload, 16);
  mbedtls_sha256_update(&sha_ctx, target_hello, 20);
  mbedtls_sha256_finish(&sha_ctx, s_negotiation_hash);
  mbedtls_sha256_free(&sha_ctx);

  if (outResp && outRespLen) {
    memcpy(outResp, target_hello, sizeof(target_hello));
    *outRespLen = sizeof(target_hello);
  }

  s_negotiation_latency_ms = millis() - s_hello_received_ms;
  LOGF("[GATT-SERVER] CLIENT_HELLO processed. Selected protocol: %u, status: %u, latency: %lu ms",
       s_selected_protocol, status, (unsigned long)s_negotiation_latency_ms);
  return (status == 0);
}

size_t GattServer::buildChallengePayload(uint8_t* outBuf, size_t maxLen) {
  if (maxLen < 138) return 0;
  uint32_t now = millis();
  s_expiry_monotonic_ms = now + 5000; // 5 seconds expiry deadline

  // 138-byte canonical challenge payload (§5.1):
  // ASCII 'SGKCHAL1' (8B)
  // selected_protocol (u16)
  // door_id (16B)
  // session_id (16B)
  // nonce (32B)
  // target_boot_id (16B)
  // expiry_monotonic_ms (u64)
  // active_acl_version (u64)
  // negotiation_hash (32B)
  memset(outBuf, 0, 138);
  memcpy(outBuf, "SGKCHAL1", 8);
  outBuf[8]  = (s_selected_protocol >> 8) & 0xFF;
  outBuf[9]  = s_selected_protocol & 0xFF;
  memcpy(outBuf + 10, s_door_id, 16);
  memcpy(outBuf + 26, s_session_id, 16);
  memcpy(outBuf + 42, s_nonce, 32);

  // Target boot id from DiagnosticsManager
  const char* bootIdStr = DiagnosticsManager::bootId();
  for (size_t i = 0; i < 16; i++) {
    outBuf[74 + i] = (i < strlen(bootIdStr)) ? bootIdStr[i] : 0x00;
  }

  uint64_t expNet = swap64(s_expiry_monotonic_ms);
  memcpy(outBuf + 90, &expNet, 8);

  uint64_t aclVerNet = swap64(1); // ACL version 1
  memcpy(outBuf + 98, &aclVerNet, 8);

  memcpy(outBuf + 106, s_negotiation_hash, 32);

  s_session_state = SessionState::CHALLENGE_ISSUED;
  LOGF("[GATT-SERVER] Challenge payload built (138 bytes). Expiry in 5000 ms.");
  return 138;
}

bool GattServer::handleProofWrite(const uint8_t* payload, size_t len, uint8_t* outResult, size_t* outResultLen) {
  if (!s_enabled) return false;
  uint32_t now = millis();
  s_proof_received_ms = now;

  // Connection/OTA arbitration: If OTA is busy, reject immediately
  if (s_ota_busy) {
    LOGF("[GATT-SERVER-WARN] Proof rejected: OTA is active/busy");
    s_failed_auth_count++;
    buildResultPayload(ResultReason::BUSY, 1000, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  // Session state validation
  if (s_session_state != SessionState::CHALLENGE_ISSUED) {
    LOGF("[GATT-SERVER-ERR] Proof write rejected: Invalid session state (%d)", static_cast<int>(s_session_state));
    s_failed_auth_count++;
    buildResultPayload(ResultReason::SESSION_INVALID, 0, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  // Immediately CAS session state to CONSUMED (Single-use enforcement)
  s_session_state = SessionState::CONSUMED;

  // Check challenge expiry
  if (now > s_expiry_monotonic_ms) {
    LOGF("[GATT-SERVER-ERR] Proof write rejected: Challenge expired (now=%lu, expiry=%lu)",
         (unsigned long)now, (unsigned long)s_expiry_monotonic_ms);
    s_failed_auth_count++;
    buildResultPayload(ResultReason::EXPIRED_OR_REPLAY, 0, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  // PROOF wire payload (103 bytes) (§5.2):
  // protocol_version(u16), session_id(16B), credential_id(16B), action(u8), client_capabilities(u32), signature_raw64(64B)
  if (len < 103) {
    LOGF("[GATT-SERVER-ERR] Proof payload malformed/undersized: %u bytes (expected 103)", static_cast<unsigned>(len));
    s_failed_auth_count++;
    buildResultPayload(ResultReason::MALFORMED, 0, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  uint16_t proto_ver = (payload[0] << 8) | payload[1];
  if (proto_ver != s_selected_protocol) {
    LOGF("[GATT-SERVER-ERR] Proof protocol version mismatch: %u != %u", proto_ver, s_selected_protocol);
    s_failed_auth_count++;
    buildResultPayload(ResultReason::UNSUPPORTED_VERSION, 0, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  if (memcmp(payload + 2, s_session_id, 16) != 0) {
    LOGF("[GATT-SERVER-ERR] Proof session_id mismatch");
    s_failed_auth_count++;
    buildResultPayload(ResultReason::SESSION_INVALID, 0, 1, outResult, *outResultLen);
    resetSession();
    return false;
  }

  uint8_t action = payload[34];
  // Action 1: OPEN (hands-free / local auth), Action 2: MANUAL_REMOTE (authenticated explicit button)
  LOGF("[GATT-SERVER] Proof valid! Action requested: %u", action);

  s_proof_latency_ms = now - s_proof_received_ms;

  // Build OK result payload (32 bytes)
  size_t resLen = buildResultPayload(ResultReason::OK, 0, 1, outResult, *outResultLen);
  if (outResultLen) *outResultLen = resLen;

  s_session_state = SessionState::COMPLETED;
  LOGF("[GATT-SERVER] Proof auth succeeded in %lu ms!", (unsigned long)s_proof_latency_ms);
  return true;
}

size_t GattServer::buildResultPayload(ResultReason reason, uint32_t retryAfterMs, uint64_t aclVersion, uint8_t* outBuf, size_t maxLen) {
  if (maxLen < 32) return 0;

  // RESULT payload (32 bytes) (§5.3):
  // protocol_version(u16), session_id(16B), reason(u16), retry_after_ms(u32), active_acl_version(u64)
  memset(outBuf, 0, 32);
  outBuf[0] = (s_selected_protocol >> 8) & 0xFF;
  outBuf[1] = s_selected_protocol & 0xFF;
  memcpy(outBuf + 2, s_session_id, 16);

  uint16_t reasonNet = swap16(static_cast<uint16_t>(reason));
  memcpy(outBuf + 18, &reasonNet, 2);

  uint32_t retryNet = swap32(retryAfterMs);
  memcpy(outBuf + 20, &retryNet, 4);

  uint64_t aclNet = swap64(aclVersion);
  memcpy(outBuf + 24, &aclNet, 8);

  return 32;
}

GattServer::GattTelemetry GattServer::getTelemetry() {
  GattTelemetry telem;
  telem.heap_free = ESP.getFreeHeap();
  telem.heap_min = ESP.getMinFreeHeap();
  telem.stack_high_watermark = static_cast<uint32_t>(uxTaskGetStackHighWaterMark(NULL));
  telem.negotiation_latency_ms = s_negotiation_latency_ms;
  telem.proof_latency_ms = s_proof_latency_ms;
  telem.active_connections = s_active_connections;
  telem.total_sessions = s_total_sessions;
  telem.failed_auth_count = s_failed_auth_count;
  strlcpy(telem.boot_id, DiagnosticsManager::bootId(), sizeof(telem.boot_id));
  telem.reset_reason = DiagnosticsManager::resetReason();
  return telem;
}
