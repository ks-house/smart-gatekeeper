// include/GattServer.h
// =============================================================
// smart-gatekeeper v2.1 — Hardwareless RC Connectable GATT Transport
// (ESP32-C6 Connectable GATT Advertising, Auth Service & Coexistence)
// =============================================================
#pragma once

#include <cstdint>
#include <cstddef>
#include <Arduino.h>
#include "config.h"

// Hardwareless RC Connectable GATT Transport Manager
class GattServer {
public:
  enum class MsgType : uint8_t {
    CLIENT_HELLO = 0x01,
    TARGET_HELLO = 0x02,
    CHALLENGE    = 0x10,
    PROOF        = 0x11,
    RESULT       = 0x12,
    ERROR        = 0x7F
  };

  enum class ResultReason : uint16_t {
    OK                   = 0,
    UNSUPPORTED_VERSION  = 1,
    MALFORMED            = 2,
    SESSION_INVALID      = 3,
    EXPIRED_OR_REPLAY    = 4,
    ACL_UNAVAILABLE      = 5,
    CREDENTIAL_DENIED    = 6,
    PROOF_INVALID        = 7,
    BUSY                 = 8,
    RATE_LIMITED         = 9,
    INTERNAL_FAIL_CLOSED = 10
  };

  enum class SessionState {
    IDLE,
    HELLO_RECEIVED,
    CHALLENGE_ISSUED,
    PROOF_VERIFYING,
    CONSUMED,
    COMPLETED
  };

  #pragma pack(push, 1)
  struct FramingHeader {
    uint8_t  magic[2];           // 'S', 'G' (0x53, 0x47)
    uint8_t  framing_version;    // 1
    uint8_t  message_type;       // MsgType
    uint16_t message_id;         // Network byte order
    uint8_t  fragment_index;     // 0-based
    uint8_t  fragment_count;     // 1..255
    uint16_t total_message_len;  // Network byte order, max 2048
  };
  #pragma pack(pop)

  struct GattTelemetry {
    uint32_t heap_free;
    uint32_t heap_min;
    uint32_t stack_high_watermark;
    uint32_t negotiation_latency_ms;
    uint32_t proof_latency_ms;
    uint32_t active_connections;
    uint32_t total_sessions;
    uint32_t failed_auth_count;
    char     boot_id[20];
    const char* reset_reason;
  };

  static void init();
  static void update();

  static bool isEnabled();
  static void setEnabled(bool enabled);

  static bool isConnected();
  static uint32_t getActiveConnections();
  static void onConnect();
  static void onDisconnect();

  static bool handleClientHello(const uint8_t* payload, size_t len, uint8_t* outResp, size_t* outRespLen);
  static bool handleProofWrite(const uint8_t* payload, size_t len, uint8_t* outResult, size_t* outResultLen);

  static size_t buildChallengePayload(uint8_t* outBuf, size_t maxLen);
  static size_t buildResultPayload(ResultReason reason, uint32_t retryAfterMs, uint64_t aclVersion, uint8_t* outBuf, size_t maxLen);

  static void resetSession();

  static bool isOtaBusy();
  static void setOtaBusy(bool busy);

  static GattTelemetry getTelemetry();

private:
  static bool s_enabled;
  static bool s_connected;
  static uint32_t s_active_connections;
  static bool s_ota_busy;

  static SessionState s_session_state;
  static uint32_t s_session_start_ms;
  static uint32_t s_hello_received_ms;
  static uint32_t s_proof_received_ms;
  static uint32_t s_negotiation_latency_ms;
  static uint32_t s_proof_latency_ms;

  static uint16_t s_selected_protocol;
  static uint16_t s_message_id;
  static uint8_t  s_session_id[16];
  static uint8_t  s_nonce[32];
  static uint8_t  s_door_id[16];
  static uint8_t  s_negotiation_hash[32];
  static uint64_t s_expiry_monotonic_ms;

  static uint32_t s_total_sessions;
  static uint32_t s_failed_auth_count;

  static uint8_t  s_reassembly_buf[2048];
  static size_t   s_reassembly_len;
  static uint8_t  s_expected_frag_index;
  static uint8_t  s_expected_frag_count;
  static uint16_t s_expected_message_id;

  static void generateCsprng(uint8_t* buf, size_t len);
  static uint16_t swap16(uint16_t val);
  static uint32_t swap32(uint32_t val);
  static uint64_t swap64(uint64_t val);
};
