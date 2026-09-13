#pragma once
#include <cstdint>
#include <cstdio>
constexpr int INPUT = 0;
constexpr int OUTPUT = 1;
constexpr int LOW = 0;
constexpr int HIGH = 1;
void pinMode(int pin, int mode);
void digitalWrite(int pin, int value);
void delayMicroseconds(unsigned int us);
unsigned long pulseIn(int pin, int value, unsigned long timeout);
