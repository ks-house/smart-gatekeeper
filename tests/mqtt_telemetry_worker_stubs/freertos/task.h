#pragma once
#include <cstdint>
int xTaskCreate(void (*entry)(void*), const char*, uint32_t, void*, unsigned, void*);
void vTaskDelete(void*);
