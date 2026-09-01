// src/ConfigManager.cpp
// =============================================================
// smart-gatekeeper — ConfigManager 구현
// v2.0: BLE RSSI 임계값 관련 함수 제거 (BLE Advertiser 모드로 전환)
// =============================================================
#include "ConfigManager.h"
#include "GattProtocol.h"
#include "config.h"

Preferences ConfigManager::preferences;
static bool configManagerInitialized = false;

namespace {
uint32_t clampAccessTiming(uint32_t value, uint32_t minimum,
                           uint32_t maximum) {
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}
}  // namespace

void ConfigManager::begin() {
    if (configManagerInitialized) {
        return;
    }

    preferences.begin("gatekeeper", false);
    configManagerInitialized = true;

    // 기본값이 NVS에 없는 경우 기본 상수로 초기 세팅
    if (!preferences.isKey("api_url")) {
        preferences.putString("api_url", API_URL);
    }
    if (!preferences.isKey("api_key")) {
        preferences.putString("api_key", API_KEY);
    }
}

String ConfigManager::getWifiSsid() {
    return preferences.getString("ssid", WIFI_SSID);
}

String ConfigManager::getWifiPassword() {
    return preferences.getString("pass", WIFI_PASSWORD);
}

String ConfigManager::getApiUrl() {
    return preferences.getString("api_url", API_URL);
}

String ConfigManager::getApiKey() {
    return preferences.getString("api_key", API_KEY);
}

int ConfigManager::getTxPower(int defaultVal) {
    return preferences.getInt("tx_pwr", defaultVal);
}

int ConfigManager::getDistanceThresholdCm(int defaultVal) {
    if (preferences.isKey("dist_thresh")) {
        return preferences.getInt("dist_thresh", defaultVal);
    }
    return preferences.getInt("tof_dist", defaultVal);
}

int ConfigManager::getTofDistanceCm(int defaultVal) {
    return getDistanceThresholdCm(defaultVal);
}

uint32_t ConfigManager::getPreArmDurationMs(uint32_t defaultVal) {
    return clampAccessTiming(
        preferences.getUInt("prearm_dur", defaultVal),
        PRE_ARM_MIN_DURATION_MS, PRE_ARM_MAX_DURATION_MS);
}

uint32_t ConfigManager::getRelayCooldownMs(uint32_t defaultVal) {
    return clampAccessTiming(
        preferences.getUInt("relay_cool", defaultVal),
        RELAY_COOLDOWN_MIN_MS, RELAY_COOLDOWN_MAX_MS);
}

bool ConfigManager::getHardwarelessRcEnabled(bool defaultVal) {
    return preferences.getBool("hwless_rc", defaultVal);
}

namespace {
int hexNibble(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

bool parseDoorId(const String& value, std::array<uint8_t, 16>* doorId) {
    if (doorId == nullptr) return false;
    doorId->fill(0);
    if (value.length() != 32) return false;
    bool anyNonzero = false;
    bool anyNotFf = false;
    for (size_t index = 0; index < doorId->size(); ++index) {
        const int high = hexNibble(value[index * 2]);
        const int low = hexNibble(value[index * 2 + 1]);
        if (high < 0 || low < 0) {
            doorId->fill(0);
            return false;
        }
        const uint8_t byte = static_cast<uint8_t>((high << 4) | low);
        (*doorId)[index] = byte;
        anyNonzero = anyNonzero || byte != 0;
        anyNotFf = anyNotFf || byte != 0xff;
    }
    if (!anyNonzero || !anyNotFf) {
        doorId->fill(0);
        return false;
    }
    return true;
}

#if ENABLE_HARDWARELESS_RC
bool isValidAclSignerPublicKeyHex(const String& value) {
    if (value.length() != 130 || value[0] != '0' || value[1] != '4') {
        return false;
    }
    for (size_t index = 2; index < value.length(); ++index) {
        if (hexNibble(value[index]) < 0) return false;
    }
    return true;
}
#endif
}  // namespace

bool ConfigManager::getHardwarelessDoorId(
        std::array<uint8_t, 16>* doorId) {
    const String configured = preferences.getString(
        "hwless_door", HARDWARELESS_DOOR_ID_HEX);
    return parseDoorId(configured, doorId);
}

String ConfigManager::getAclSignerPublicKeyHex() {
#ifdef SECRET_ACL_SIGNER_PUBLIC_KEY_HEX
    const char* defaultKey = SECRET_ACL_SIGNER_PUBLIC_KEY_HEX;
#else
    const char* defaultKey = "";
#endif
    return preferences.getString("acl_signer_pub", defaultKey);
}

uint32_t ConfigManager::getAclSigningKeyId(uint32_t defaultVal) {
#ifdef SECRET_ACL_SIGNING_KEY_ID
    uint32_t defaultId = SECRET_ACL_SIGNING_KEY_ID;
#else
    uint32_t defaultId = defaultVal;
#endif
    return preferences.getUInt("acl_key_id", defaultId);
}

uint32_t ConfigManager::incrementBootCount() {
    uint32_t count = preferences.getUInt("boot_count", 0) + 1;
    preferences.putUInt("boot_count", count);
    return count;
}

String ConfigManager::consumePlannedRestartReason() {
    String reason = preferences.getString("next_restart", "");
    if (preferences.isKey("next_restart")) {
        preferences.remove("next_restart");
    }
    return reason;
}


void ConfigManager::setWifiCredentials(const String& ssid, const String& password) {
    preferences.putString("ssid", ssid);
    preferences.putString("pass", password);
}

void ConfigManager::setApiCredentials(const String& url, const String& key) {
    preferences.putString("api_url", url);
    preferences.putString("api_key", key);
}

void ConfigManager::setTxPower(int powerDbm) {
    preferences.putInt("tx_pwr", powerDbm);
}

void ConfigManager::setDistanceThresholdCm(int distanceCm) {
    preferences.putInt("dist_thresh", distanceCm);
    preferences.putInt("tof_dist", distanceCm);
}

void ConfigManager::setTofDistanceCm(int distanceCm) {
    setDistanceThresholdCm(distanceCm);
}


void ConfigManager::setPreArmDurationMs(uint32_t durationMs) {
    preferences.putUInt(
        "prearm_dur",
        clampAccessTiming(durationMs, PRE_ARM_MIN_DURATION_MS,
                          PRE_ARM_MAX_DURATION_MS));
}

void ConfigManager::setRelayCooldownMs(uint32_t cooldownMs) {
    preferences.putUInt(
        "relay_cool",
        clampAccessTiming(cooldownMs, RELAY_COOLDOWN_MIN_MS,
                          RELAY_COOLDOWN_MAX_MS));
}

void ConfigManager::setHardwarelessRcEnabled(bool enabled) {
    preferences.putBool("hwless_rc", enabled);
}

bool ConfigManager::setHardwarelessDoorIdHex(const String& doorIdHex) {
    std::array<uint8_t, 16> parsed{};
    if (!parseDoorId(doorIdHex, &parsed)) return false;
    return preferences.putString("hwless_door", doorIdHex) == doorIdHex.length();
}

void ConfigManager::setPlannedRestartReason(const char* reason) {
    preferences.putString("next_restart", reason ? reason : "unspecified");
}

bool ConfigManager::enforceCompileTimeSecurityPolicy() {
#if ENABLE_HARDWARELESS_RC
    const bool migrationComplete = preferences.getBool("hwless_p1", false);
    std::array<uint8_t, 16> doorId{};
    const bool provisioningValid = getHardwarelessDoorId(&doorId) &&
        isValidAclSignerPublicKeyHex(getAclSignerPublicKeyHex()) &&
        getAclSigningKeyId() != 0;
    if (!sgk::shouldInitializePersonalHardwarelessState(
            sgk::hardwarelessRuntimeDefaultEnabled(), migrationComplete,
            provisioningValid)) {
        return true;
    }

    // Write enable first and the migration marker last. A reset between writes
    // safely retries; after the marker exists, a later false is authoritative.
    if (preferences.putBool("hwless_rc", true) != 1) return false;
    return preferences.putBool("hwless_p1", true) == 1;
#else
    // Compile-OFF is authoritative and starts a new migration epoch. This
    // distinguishes its forced false from a later personal-profile kill switch.
    bool ok = true;
    if (preferences.isKey("hwless_p1")) {
        ok = preferences.remove("hwless_p1") && ok;
    }
    if (preferences.isKey("hwless_rc")) {
        ok = preferences.putBool("hwless_rc", false) == 1 && ok;
    }
    if (preferences.isKey("hwless_owner")) {
        ok = preferences.remove("hwless_owner") && ok;
    }
    return ok;
#endif
}

void ConfigManager::clearConfig() {

    preferences.clear();
}
