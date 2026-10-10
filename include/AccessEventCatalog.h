#pragma once

#include "GattProtocol.h"

namespace sgk {
struct AccessCatalog {
  const char* event_code = nullptr;
  const char* stage = nullptr;
  const char* outcome = nullptr;
  const char* reason_code = nullptr;
};
inline const char* accessTransportReasonName(sgk::ResultReason reason) {
  switch (reason) {
    case sgk::ResultReason::kUnsupportedVersion:
      return "PROTOCOL_INCOMPATIBLE";
    case sgk::ResultReason::kMalformed:
      return "MALFORMED_PROOF";
    case sgk::ResultReason::kSessionInvalid:
      return "GATT_DISCONNECTED";
    case sgk::ResultReason::kExpiredOrReplay:
      return "PROOF_EXPIRED";
    case sgk::ResultReason::kAclUnavailable:
      return "ACL_NOT_FOUND";
    case sgk::ResultReason::kCredentialDenied:
      return "CREDENTIAL_INACTIVE";
    case sgk::ResultReason::kProofInvalid:
      return "SIGNATURE_INVALID";
    case sgk::ResultReason::kBusy:
      return "TARGET_BUSY";
    case sgk::ResultReason::kRateLimited:
      return "SESSION_TIMEOUT";
    default:
      return "INTERNAL_ERROR";
  }
}
inline bool buildAccessCatalog(const Event& event, AccessCatalog* fields) {
  if (fields == nullptr) return false;
  switch (event.code) {
    case sgk::EventCode::kAccessGattConnected:
      fields->event_code = "ACCESS_GATT_CONNECTED";
      fields->stage = "GATT_CONNECT";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "GATT_CONNECTED";
      return true;
    case sgk::EventCode::kAccessGattFailed:
      fields->event_code = "ACCESS_GATT_FAILED";
      fields->stage = "GATT_CONNECT";
      fields->outcome = "FAILED";
      fields->reason_code = "GATT_DISCONNECTED";
      return true;
    case sgk::EventCode::kAccessProofRequested:
      fields->event_code = "ACCESS_PROOF_REQUESTED";
      fields->stage = "PROOF";
      fields->outcome = "STARTED";
      fields->reason_code = "PROOF_CHALLENGE_ISSUED";
      return true;
    case sgk::EventCode::kAccessProofVerified:
      fields->event_code = "ACCESS_PROOF_VERIFIED";
      fields->stage = "PROOF";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "PROOF_VALID";
      return true;
    case sgk::EventCode::kAccessArmed:
      fields->event_code = "ACCESS_ARMED";
      fields->stage = "ARMED";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "ARM_ACCEPTED";
      return true;
    case sgk::EventCode::kAccessSensorDetected:
      fields->event_code = "ACCESS_SENSOR_DETECTED";
      fields->stage = "SENSOR";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "SENSOR_THRESHOLD_MET";
      return true;
    case sgk::EventCode::kAccessRelayOn:
      fields->event_code = "ACCESS_RELAY_ON";
      fields->stage = "RELAY_ON";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "RELAY_ACTIVATED";
      return true;
    case sgk::EventCode::kAccessRelayOff:
      fields->event_code = "ACCESS_RELAY_OFF";
      fields->stage = "RELAY_OFF";
      fields->outcome = "SUCCEEDED";
      fields->reason_code =
          event.reason == sgk::EventReason::kRelayFailsafeCutoff
              ? "RELAY_FAILSAFE_CUTOFF"
              : "RELAY_HOLD_COMPLETE";
      return true;
    case sgk::EventCode::kAccessSessionCompleted:
      fields->event_code = "ACCESS_SESSION_COMPLETED";
      fields->stage = "COMPLETE";
      fields->outcome = "SUCCEEDED";
      fields->reason_code = "ACCESS_GRANTED";
      return true;
    case sgk::EventCode::kAccessProofRejected:
      if (event.transport_reason == sgk::ResultReason::kAclUnavailable ||
          event.transport_reason == sgk::ResultReason::kCredentialDenied) {
        fields->event_code = "ACCESS_ACL_REJECTED";
        fields->stage = "ACL";
      } else {
        if (event.transport_reason != sgk::ResultReason::kUnsupportedVersion &&
            event.transport_reason != sgk::ResultReason::kMalformed &&
            event.transport_reason != sgk::ResultReason::kExpiredOrReplay &&
            event.transport_reason != sgk::ResultReason::kProofInvalid) {
          return false;
        }
        fields->event_code = "ACCESS_PROOF_REJECTED";
        fields->stage = "PROOF";
      }
      fields->outcome = "DENIED";
      fields->reason_code = accessTransportReasonName(event.transport_reason);
      return true;
    case sgk::EventCode::kAccessSessionTerminated:
      fields->event_code = "ACCESS_SESSION_TERMINATED";
      fields->stage = "COMPLETE";
      if (event.reason == sgk::EventReason::kArmTimeout) {
        fields->outcome = "TIMED_OUT";
        fields->reason_code = "ARM_TIMEOUT";
      } else if (event.reason == sgk::EventReason::kSessionSuperseded) {
        fields->outcome = "FAILED";
        fields->reason_code = "SESSION_SUPERSEDED";
      } else if (event.reason == sgk::EventReason::kRelayFailsafeCutoff) {
        fields->outcome = "FAILED";
        fields->reason_code = "RELAY_CONTROL_ERROR";
      } else {
        fields->outcome = "FAILED";
        fields->reason_code = event.reason == sgk::EventReason::kOtaBusy
            ? "OTA_BUSY" : accessTransportReasonName(event.transport_reason);
      }
      return true;
  }
  return false;
}

}  // namespace sgk
