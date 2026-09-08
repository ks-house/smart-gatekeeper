#pragma once
#include <mutex>
using portMUX_TYPE = std::mutex;
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(value) (value)->lock()
#define portEXIT_CRITICAL(value) (value)->unlock()
constexpr int pdPASS = 1;
constexpr unsigned tskIDLE_PRIORITY = 0;
