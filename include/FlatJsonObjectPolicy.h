#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace sgk {
namespace flat_json_detail {

inline bool isSpace(uint8_t value) {
  return value == ' ' || value == '\t' || value == '\r' || value == '\n';
}

inline bool isHex(uint8_t value) {
  return (value >= '0' && value <= '9') ||
         (value >= 'a' && value <= 'f') ||
         (value >= 'A' && value <= 'F');
}

inline void skipSpace(const uint8_t* input, size_t length, size_t* cursor) {
  while (*cursor < length && isSpace(input[*cursor])) ++(*cursor);
}

inline bool consumeString(const uint8_t* input, size_t length, size_t* cursor,
                          char* key, size_t key_capacity) {
  if (*cursor >= length || input[(*cursor)++] != '"') return false;
  size_t key_length = 0;
  while (*cursor < length) {
    const uint8_t value = input[(*cursor)++];
    if (value == '"') {
      if (key != nullptr) key[key_length] = '\0';
      return true;
    }
    if (value < 0x20) return false;
    if (value == '\\') {
      // Canonical schema names are unescaped ASCII. Rejecting escapes in keys
      // prevents aliases such as "acti\u006fn" from bypassing duplicate checks.
      if (key != nullptr || *cursor >= length) return false;
      const uint8_t escaped = input[(*cursor)++];
      if (escaped == 'u') {
        for (size_t index = 0; index < 4; ++index) {
          if (*cursor >= length || !isHex(input[(*cursor)++])) return false;
        }
      } else if (escaped != '"' && escaped != '\\' && escaped != '/' &&
                 escaped != 'b' && escaped != 'f' && escaped != 'n' &&
                 escaped != 'r' && escaped != 't') {
        return false;
      }
      continue;
    }
    if (key != nullptr) {
      if (key_length + 1 >= key_capacity || value > 0x7e) return false;
      key[key_length++] = static_cast<char>(value);
    }
  }
  return false;
}

inline int fieldIndex(const char* key, const char* const* fields,
                      size_t field_count) {
  for (size_t index = 0; index < field_count; ++index) {
    if (std::strcmp(key, fields[index]) == 0) return static_cast<int>(index);
  }
  return -1;
}

}  // namespace flat_json_detail

// Validates the raw member sequence before a DOM parser can collapse duplicate
// names. The signed command schema is a flat object whose values are strings or
// numbers; nested values and escaped member names are deliberately rejected.
inline bool hasExactUniqueFlatJsonFields(const uint8_t* input, size_t length,
                                         const char* const* fields,
                                         size_t field_count) {
  if (input == nullptr || fields == nullptr || field_count == 0 ||
      field_count > 31) {
    return false;
  }
  size_t cursor = 0;
  uint32_t seen = 0;
  size_t members = 0;
  flat_json_detail::skipSpace(input, length, &cursor);
  if (cursor >= length || input[cursor++] != '{') return false;
  while (true) {
    flat_json_detail::skipSpace(input, length, &cursor);
    char key[32]{};
    if (!flat_json_detail::consumeString(input, length, &cursor, key,
                                         sizeof(key))) {
      return false;
    }
    const int field = flat_json_detail::fieldIndex(key, fields, field_count);
    if (field < 0 || (seen & (1UL << field)) != 0) return false;
    seen |= 1UL << field;
    ++members;

    flat_json_detail::skipSpace(input, length, &cursor);
    if (cursor >= length || input[cursor++] != ':') return false;
    flat_json_detail::skipSpace(input, length, &cursor);
    if (cursor >= length || input[cursor] == '{' || input[cursor] == '[') {
      return false;
    }
    if (input[cursor] == '"') {
      if (!flat_json_detail::consumeString(input, length, &cursor, nullptr, 0)) {
        return false;
      }
    } else {
      bool non_space = false;
      while (cursor < length && input[cursor] != ',' && input[cursor] != '}') {
        const uint8_t value = input[cursor++];
        if (value == '"' || value == ':' || value == '{' || value == '[' ||
            (value < 0x20 && !flat_json_detail::isSpace(value))) {
          return false;
        }
        non_space = non_space || !flat_json_detail::isSpace(value);
      }
      if (!non_space) return false;
    }

    flat_json_detail::skipSpace(input, length, &cursor);
    if (cursor >= length) return false;
    if (input[cursor] == ',') {
      ++cursor;
      continue;
    }
    if (input[cursor++] != '}') return false;
    flat_json_detail::skipSpace(input, length, &cursor);
    const uint32_t expected = (1UL << field_count) - 1UL;
    return cursor == length && members == field_count && seen == expected;
  }
}

}  // namespace sgk
