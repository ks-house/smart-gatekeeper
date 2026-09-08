#pragma once
#include <cstddef>
constexpr unsigned MALLOC_CAP_8BIT = 1;
size_t heap_caps_get_free_size(unsigned);
size_t heap_caps_get_largest_free_block(unsigned);
