#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>

namespace sgk {

// Owns the byte-exact image format and the volatile acknowledgement boundary
// for evidence retained across a controlled software reset. Image deliberately
// contains only scalar fields and raw bytes so RTC_NOINIT placement cannot run
// a Record constructor during startup.
template <typename Record, size_t Capacity, uint32_t Magic, uint16_t Version>
class RestartEvidenceRetention {
 public:
  static_assert(std::is_trivially_copyable<Record>::value,
                "RTC evidence records must be trivially copyable");

  struct Image {
    uint32_t magic;
    uint16_t version;
    uint16_t count;
    uint32_t checksum;
    // Version 1 images originally required this field to be zero. Treating it
    // as a checksum-bound generation preserves those images as generation 0
    // while allowing crash-atomic A/B replacement.
    uint32_t generation;
    alignas(alignof(Record)) uint8_t records[Capacity * sizeof(Record)];
  };

  struct Journal {
    Image slots[2];
  };

  static_assert(std::is_trivial<Image>::value,
                "RTC evidence image must not have startup initialization");
  static_assert(std::is_trivial<Journal>::value,
                "RTC evidence journal must not have startup initialization");

  using Validator = bool (*)(const Record&);

  static void clear(Image* image) {
    if (image != nullptr) std::memset(image, 0, sizeof(*image));
  }

  static uint32_t checksum(const Image& image) {
    const auto* bytes = reinterpret_cast<const uint8_t*>(&image);
    const uint32_t expected_magic = Magic;
    const auto* magic_bytes =
        reinterpret_cast<const uint8_t*>(&expected_magic);
    constexpr size_t magic_offset = offsetof(Image, magic);
    constexpr size_t checksum_offset = offsetof(Image, checksum);
    uint32_t hash = 2166136261UL;
    for (size_t index = 0; index < sizeof(image); ++index) {
      const bool magic_byte =
          index >= magic_offset &&
          index < magic_offset + sizeof(image.magic);
      const bool checksum_byte =
          index >= checksum_offset &&
          index < checksum_offset + sizeof(image.checksum);
      const uint8_t value = magic_byte
          ? magic_bytes[index - magic_offset]
          : (checksum_byte ? 0 : bytes[index]);
      hash ^= value;
      hash *= 16777619UL;
    }
    return hash;
  }

  static bool isValid(const Image& image, Validator validator) {
    if (validator == nullptr || image.magic != Magic ||
        image.version != Version || image.count == 0 ||
        image.count > Capacity ||
        image.checksum != checksum(image)) {
      return false;
    }
    for (size_t index = 0; index < image.count; ++index) {
      Record record{};
      std::memcpy(&record, image.records + index * sizeof(Record),
                  sizeof(record));
      if (!validator(record)) return false;
    }
    return true;
  }

  static bool save(const std::array<Record, Capacity>& ring, size_t head,
                   size_t count, Image* image, Validator validator,
                   uint32_t generation = 0) {
    if (image == nullptr || validator == nullptr || count == 0 ||
        count > Capacity || head >= Capacity) {
      return false;
    }

    // Invalidate and replace the complete image. The checksum is committed
    // only after all current FIFO records have been copied.
    clear(image);
    image->version = Version;
    image->count = static_cast<uint16_t>(count);
    image->generation = generation;
    for (size_t index = 0; index < count; ++index) {
      const Record& record = ring[(head + index) % Capacity];
      if (!validator(record)) {
        clear(image);
        return false;
      }
      std::memcpy(image->records + index * sizeof(Record), &record,
                  sizeof(record));
    }
    image->checksum = checksum(*image);
    // Commit magic last. A reset at any earlier instruction leaves an invalid
    // image instead of exposing a partially replaced FIFO as current.
    std::atomic_signal_fence(std::memory_order_release);
    image->magic = Magic;
    if (isValid(*image, validator)) return true;
    clear(image);
    return false;
  }

  static void clearJournal(Journal* journal) {
    if (journal != nullptr) std::memset(journal, 0, sizeof(*journal));
  }

  static bool hasRecognizedMagic(const Journal& journal) {
    return journal.slots[0].magic == Magic || journal.slots[1].magic == Magic;
  }

  // Serial-number arithmetic makes generation 0 correctly follow UINT32_MAX.
  // saveJournal() only leaves adjacent committed generations, so the ambiguous
  // half-range comparison cannot occur in a journal produced by this class.
  static bool generationIsNewer(uint32_t candidate, uint32_t reference) {
    const uint32_t distance = candidate - reference;
    return distance != 0 && distance < 0x80000000UL;
  }

  static bool newestValidIndex(const Journal& journal, Validator validator,
                               size_t* index) {
    if (index == nullptr) return false;
    const bool first_valid = isValid(journal.slots[0], validator);
    const bool second_valid = isValid(journal.slots[1], validator);
    if (!first_valid && !second_valid) return false;
    if (!second_valid) {
      *index = 0;
    } else if (!first_valid) {
      *index = 1;
    } else {
      *index = generationIsNewer(journal.slots[1].generation,
                                 journal.slots[0].generation)
          ? 1
          : 0;
    }
    return true;
  }

  // Writes only the inactive slot. Until its checksum and magic-last commit
  // validate, the previously committed slot remains byte-for-byte restorable.
  static bool saveJournal(const std::array<Record, Capacity>& ring,
                          size_t head, size_t count, Journal* journal,
                          Validator validator) {
    if (journal == nullptr) return false;
    size_t active_index = 0;
    const bool has_active =
        newestValidIndex(*journal, validator, &active_index);
    const size_t destination_index = has_active ? active_index ^ 1U : 0;
    const uint32_t generation = has_active
        ? journal->slots[active_index].generation + 1U
        : 1U;
    if (!save(ring, head, count, &journal->slots[destination_index],
              validator, generation)) {
      return false;
    }
    size_t committed_index = 0;
    return newestValidIndex(*journal, validator, &committed_index) &&
           committed_index == destination_index;
  }

  static bool restoreNewest(const Journal& journal,
                            std::array<Record, Capacity>* ring,
                            size_t* head, size_t* count,
                            Validator validator,
                            uint32_t* generation = nullptr) {
    size_t index = 0;
    if (!newestValidIndex(journal, validator, &index) ||
        !restore(journal.slots[index], ring, head, count, validator)) {
      return false;
    }
    if (generation != nullptr) {
      *generation = journal.slots[index].generation;
    }
    return true;
  }

  static bool restore(const Image& image,
                      std::array<Record, Capacity>* ring,
                      size_t* head, size_t* count, Validator validator) {
    if (ring == nullptr || head == nullptr || count == nullptr ||
        !isValid(image, validator)) {
      return false;
    }
    for (size_t index = 0; index < image.count; ++index) {
      std::memcpy(&(*ring)[index],
                  image.records + index * sizeof(Record), sizeof(Record));
    }
    *head = 0;
    *count = image.count;
    return true;
  }

  void retain(size_t count) {
    retained_front_count_ = count <= Capacity ? count : 0;
  }

  void reset() { retained_front_count_ = 0; }

  // Returns true only when the removal durably acknowledges the final record
  // represented by the RTC image. Records appended behind this prefix cannot
  // cause an early clear.
  bool frontRemoved() {
    if (retained_front_count_ == 0) return false;
    --retained_front_count_;
    return retained_front_count_ == 0;
  }

  size_t retainedCount() const { return retained_front_count_; }

 private:
  size_t retained_front_count_ = 0;
};

}  // namespace sgk
