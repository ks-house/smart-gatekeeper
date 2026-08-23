#!/usr/bin/env python3
"""Fail a Target build when its flash layout cannot safely support OTA."""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Partition:
  name: str
  kind: str
  subtype: str
  offset: int
  size: int

  @property
  def end(self):
    return self.offset + self.size


def parse_partitions(path):
  partitions = []
  with Path(path).open(encoding="utf-8") as source:
    lines = (line for line in source if not line.lstrip().startswith("#"))
    for row in csv.reader(lines):
      if not row or not any(field.strip() for field in row):
        continue
      if len(row) < 5:
        raise ValueError(f"invalid partition row: {row}")
      partitions.append(Partition(
          name=row[0].strip(),
          kind=row[1].strip(),
          subtype=row[2].strip(),
          offset=int(row[3].strip(), 0),
          size=int(row[4].strip(), 0),
      ))
  return partitions


def verify_layout(partition_path, flash_size, firmware_size,
                  max_slot_usage_percent):
  partitions = parse_partitions(partition_path)
  if not partitions:
    raise ValueError("partition table is empty")

  by_name = {partition.name: partition for partition in partitions}
  required = {"nvs", "otadata", "app0", "app1"}
  missing = sorted(required - set(by_name))
  if missing:
    raise ValueError(f"missing required partitions: {', '.join(missing)}")

  ordered = sorted(partitions, key=lambda partition: partition.offset)
  for partition in ordered:
    if partition.size <= 0 or partition.end > flash_size:
      raise ValueError(
          f"partition {partition.name} ends outside flash: 0x{partition.end:x}")
  for previous, current in zip(ordered, ordered[1:]):
    if current.offset < previous.end:
      raise ValueError(
          f"partitions overlap: {previous.name} and {current.name}")

  app0 = by_name["app0"]
  app1 = by_name["app1"]
  if app0.kind != "app" or app0.subtype != "ota_0":
    raise ValueError("app0 is not an ota_0 application partition")
  if app1.kind != "app" or app1.subtype != "ota_1":
    raise ValueError("app1 is not an ota_1 application partition")
  if app0.size != app1.size:
    raise ValueError("OTA application partitions must have equal capacity")

  slot_size = app0.size
  if firmware_size <= 0 or firmware_size > slot_size:
    raise ValueError(
        f"firmware size {firmware_size} does not fit OTA slot {slot_size}")
  usage_percent = firmware_size * 100.0 / slot_size
  if usage_percent > max_slot_usage_percent:
    raise ValueError(
        f"firmware uses {usage_percent:.2f}% of OTA slot; "
        f"limit is {max_slot_usage_percent:.2f}%")
  return slot_size, usage_percent


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--partitions", required=True, type=Path)
  parser.add_argument("--firmware", required=True, type=Path)
  parser.add_argument("--flash-size", default="0x1000000")
  parser.add_argument("--max-slot-usage-percent", default=80.0, type=float)
  args = parser.parse_args()

  firmware_size = args.firmware.stat().st_size
  slot_size, usage_percent = verify_layout(
      args.partitions,
      int(args.flash_size, 0),
      firmware_size,
      args.max_slot_usage_percent,
  )
  print(
      f"OTA_SIZE_OK firmware={firmware_size} slot={slot_size} "
      f"usage={usage_percent:.2f}% "
      f"headroom={slot_size - firmware_size}")


if __name__ == "__main__":
  main()
