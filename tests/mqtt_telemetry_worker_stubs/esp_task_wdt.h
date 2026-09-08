#pragma once
constexpr int ESP_OK = 0;
int esp_task_wdt_add(void*);
int esp_task_wdt_reset();
int esp_task_wdt_delete(void*);
