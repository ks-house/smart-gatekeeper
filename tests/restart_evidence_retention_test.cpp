#include <array>
#include <cstdint>
#include <cstring>
#include <cstdio>

#include "RestartEvidenceRetention.h"

namespace {

struct Record {
  uint32_t id = 0;
  uint32_t guard = 0;
};

constexpr uint32_t kGuardMask = 0xa55aa55a;
using Retention =
    sgk::RestartEvidenceRetention<Record, 4, 0x53475453, 1>;

bool validRecord(const Record& record) {
  return record.id != 0 && record.guard == (record.id ^ kGuardMask);
}

Record record(uint32_t id) { return Record{id, id ^ kGuardMask}; }

#define CHECK(condition)                                                   \
  do {                                                                     \
    if (!(condition)) {                                                    \
      std::fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__,       \
                   __LINE__, #condition);                                  \
      return false;                                                        \
    }                                                                      \
  } while (false)

bool repeatedSoftResetRetainsUntilEveryFrontIsAcknowledged() {
  Retention::Image image{};
  std::array<Record, 4> ring{};
  ring[3] = record(30);
  ring[0] = record(40);
  ring[1] = record(50);
  CHECK(Retention::save(ring, 3, 3, &image, validRecord));

  std::array<Record, 4> first_boot{};
  size_t first_head = 99;
  size_t first_count = 99;
  CHECK(Retention::restore(image, &first_boot, &first_head, &first_count,
                           validRecord));
  CHECK(first_head == 0 && first_count == 3);
  CHECK(first_boot[0].id == 30 && first_boot[1].id == 40 &&
        first_boot[2].id == 50);

  Retention first_retention;
  first_retention.retain(first_count);
  CHECK(!first_retention.frontRemoved());
  CHECK(first_retention.retainedCount() == 2);
  CHECK(Retention::isValid(image, validRecord));

  // Simulate a second software reset before the remaining records drain. The
  // intact image restores the complete prefix again: duplicates are possible,
  // but exact terminal evidence cannot disappear.
  std::array<Record, 4> second_boot{};
  size_t second_head = 99;
  size_t second_count = 99;
  CHECK(Retention::restore(image, &second_boot, &second_head, &second_count,
                           validRecord));
  CHECK(second_count == 3 && second_boot[0].id == 30 &&
        second_boot[1].id == 40 && second_boot[2].id == 50);

  Retention second_retention;
  second_retention.retain(second_count);
  CHECK(!second_retention.frontRemoved());
  CHECK(!second_retention.frontRemoved());
  CHECK(second_retention.frontRemoved());
  Retention::clear(&image);
  CHECK(!Retention::isValid(image, validRecord));
  return true;
}

bool partialDrainSnapshotOverwritesWithExactRemainingFifo() {
  Retention::Image image{};
  std::array<Record, 4> ring{};
  ring[2] = record(100);
  ring[3] = record(200);
  ring[0] = record(300);
  CHECK(Retention::save(ring, 2, 3, &image, validRecord));

  // The oldest record migrated to NVS. A newer terminal then joined the RAM
  // tail before NVS failed; the replacement image must contain only the exact
  // remaining FIFO, in order.
  const size_t remaining_head = 3;
  const size_t remaining_count = 3;
  ring[1] = record(400);
  CHECK(Retention::save(ring, remaining_head, remaining_count, &image,
                        validRecord));

  std::array<Record, 4> restored{};
  size_t head = 99;
  size_t count = 99;
  CHECK(Retention::restore(image, &restored, &head, &count, validRecord));
  CHECK(head == 0 && count == 3);
  CHECK(restored[0].id == 200 && restored[1].id == 300 &&
        restored[2].id == 400);

  image.records[sizeof(Record)] ^= 0x01;
  CHECK(!Retention::isValid(image, validRecord));
  return true;
}

bool tornInactiveReplacementKeepsPreviousCommit() {
  Retention::Journal journal{};
  std::array<Record, 4> original{};
  original[0] = record(10);
  original[1] = record(20);
  CHECK(Retention::saveJournal(original, 0, 2, &journal, validRecord));

  size_t active_index = 99;
  CHECK(Retention::newestValidIndex(journal, validRecord, &active_index));
  const size_t inactive_index = active_index ^ 1U;

  // Fault-inject a reset after an inactive-slot replacement has begun but
  // before its magic-last commit. The old slot must remain authoritative.
  Retention::clear(&journal.slots[inactive_index]);
  journal.slots[inactive_index].version = 1;
  journal.slots[inactive_index].count = 2;
  journal.slots[inactive_index].generation =
      journal.slots[active_index].generation + 1U;
  std::memcpy(journal.slots[inactive_index].records, &original[0],
              sizeof(Record));

  std::array<Record, 4> restored{};
  size_t head = 99;
  size_t count = 99;
  uint32_t generation = 0;
  CHECK(Retention::restoreNewest(journal, &restored, &head, &count,
                                 validRecord, &generation));
  CHECK(generation == journal.slots[active_index].generation);
  CHECK(count == 2 && restored[0].id == 10 && restored[1].id == 20);

  std::array<Record, 4> replacement{};
  replacement[0] = record(20);
  replacement[1] = record(30);
  CHECK(Retention::saveJournal(replacement, 0, 2, &journal, validRecord));
  CHECK(Retention::restoreNewest(journal, &restored, &head, &count,
                                 validRecord, &generation));
  CHECK(generation == 2);
  CHECK(count == 2 && restored[0].id == 20 && restored[1].id == 30);
  return true;
}

bool wrappedGenerationSelectsNewestCommit() {
  Retention::Journal journal{};
  std::array<Record, 4> older{};
  older[0] = record(70);
  std::array<Record, 4> newer{};
  newer[0] = record(80);
  CHECK(Retention::save(older, 0, 1, &journal.slots[0], validRecord,
                        UINT32_MAX));
  CHECK(Retention::save(newer, 0, 1, &journal.slots[1], validRecord, 0));

  std::array<Record, 4> restored{};
  size_t head = 99;
  size_t count = 99;
  uint32_t generation = UINT32_MAX;
  CHECK(Retention::restoreNewest(journal, &restored, &head, &count,
                                 validRecord, &generation));
  CHECK(generation == 0);
  CHECK(count == 1 && restored[0].id == 80);
  return true;
}

}  // namespace

int main() {
  if (!repeatedSoftResetRetainsUntilEveryFrontIsAcknowledged()) return 1;
  if (!partialDrainSnapshotOverwritesWithExactRemainingFifo()) return 1;
  if (!tornInactiveReplacementKeepsPreviousCommit()) return 1;
  if (!wrappedGenerationSelectsNewestCommit()) return 1;
  return 0;
}
