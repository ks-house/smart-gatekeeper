#!/usr/bin/env python3
"""Migrate legacy Home Assistant discovery to the secure Target namespace.

The default mode is a network-free dry run. ``--apply`` publishes 15 retained,
read-only discovery documents and removes seven retained legacy controls.
Credentials are accepted only through fixed environment variables or files.
"""

import argparse
import json
import os
import re
import ssl
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


DEVICE_ID = "smart_gatekeeper_01"
USERNAME_ENV = "SGK_MQTT_USERNAME"
PASSWORD_ENV = "SGK_MQTT_PASSWORD"
CA_FILE_ENV = "SGK_MQTT_CA_FILE"
TARGET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Publication:
  topic: str
  payload: str
  qos: int = 1
  retain: bool = True


def _device():
  return {
      "identifiers": [DEVICE_ID],
      "manufacturer": "KS-House",
      "model": "ESP32-C6 Door Controller",
      "name": "Smart Gatekeeper",
  }


def _base_config(name, object_id, availability_topic):
  return {
      "availability_template": "{{ value_json.status }}",
      "availability_topic": availability_topic,
      "device": _device(),
      "name": name,
      "payload_available": "online",
      "payload_not_available": "offline",
      "unique_id": f"{DEVICE_ID}_{object_id}",
  }


def _discovery_publication(component, object_id, config):
  topic = f"homeassistant/{component}/{DEVICE_ID}/{object_id}/config"
  payload = json.dumps(
      config, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
  return Publication(topic=topic, payload=payload)


def build_plan(target_id):
  """Return seven fail-closed control tombstones, then 15 read-only updates."""
  if TARGET_ID_PATTERN.fullmatch(target_id) is None:
    raise ValueError("target ID must match [A-Za-z0-9_-]{1,64}")

  prefix = f"gatekeeper/v1/targets/{target_id}"
  status_topic = f"{prefix}/status"
  config_topic = f"{prefix}/config-state"
  availability_topic = f"{prefix}/availability"
  publications = []

  status_sensors = (
      ("distance", "[Gatekeeper] 초음파 감지 거리 (mm)",
       "{{ value_json.distance_mm }}", "mm", "mdi:ruler", None, None),
      ("distance_cm", "[Gatekeeper] 초음파 감지 거리 (cm)",
       "{{ value_json.distance_cm }}", "cm", "mdi:ruler-square", None,
       None),
      ("state", "[Gatekeeper] 게이트키퍼 동작 상태",
       "{{ value_json.state }}", None, "mdi:state-machine", None, None),
      ("ip", "[Gatekeeper] IP 주소", "{{ value_json.ip }}", None,
       "mdi:ip-network", None, None),
      ("arm_remaining_s", "[Gatekeeper] Pre-arm 잔여 시간",
       "{{ value_json.arm_remaining_s }}", "s", "mdi:timer-outline", None,
       None),
      ("wifi_rssi", "[Gatekeeper] Wi-Fi 신호 강도 (RSSI)",
       "{{ value_json.wifi_rssi }}", "dBm", "mdi:wifi",
       "signal_strength", "diagnostic"),
      ("free_heap", "[Gatekeeper] Free Heap 메모리",
       "{{ value_json.free_heap }}", "B", "mdi:memory", None,
       "diagnostic"),
      ("uptime_s", "[Gatekeeper] 시스템 가동 시간",
       "{{ value_json.uptime_s }}", "s", "mdi:clock-outline", "duration",
       "diagnostic"),
      ("firmware", "[Gatekeeper] 펌웨어 버전",
       "{{ value_json.firmware }}", None, "mdi:information-outline", None,
       "diagnostic"),
  )
  for (object_id, name, value_template, unit, icon, device_class,
       entity_category) in status_sensors:
    config = _base_config(name, object_id, availability_topic)
    config.update({
        "icon": icon,
        "state_topic": status_topic,
        "value_template": value_template,
    })
    if unit is not None:
      config["unit_of_measurement"] = unit
    if device_class is not None:
      config["device_class"] = device_class
    if entity_category is not None:
      config["entity_category"] = entity_category
    publications.append(_discovery_publication("sensor", object_id, config))

  binary_sensors = (
      ("door_binary", "[Gatekeeper] 도어 개방 여부",
       "{% if value_json.state == 'RELAY_HOLD' %}ON{% else %}OFF{% endif %}",
       "door", None),
      ("pre_armed", "[Gatekeeper] Pre-arm 활성화 상태",
       "{% if value_json.is_armed %}ON{% else %}OFF{% endif %}", "lock",
       "mdi:shield-check"),
  )
  for object_id, name, value_template, device_class, icon in binary_sensors:
    config = _base_config(name, object_id, availability_topic)
    config.update({
        "device_class": device_class,
        "payload_off": "OFF",
        "payload_on": "ON",
        "state_topic": status_topic,
        "value_template": value_template,
    })
    if icon is not None:
      config["icon"] = icon
    publications.append(
        _discovery_publication("binary_sensor", object_id, config))

  config_sensors = (
      ("cfg_tx_power", "[Gatekeeper] [설정] BLE Tx Power",
       "{{ value_json.tx_power }}", "dBm", "mdi:bluetooth-settings"),
      ("cfg_distance_thresh", "[Gatekeeper] [설정] 초음파 감지 기준 거리",
       "{{ value_json.distance_threshold_cm }}", "cm",
       "mdi:tune-vertical"),
      ("cfg_prearm_duration", "[Gatekeeper] [설정] Pre-arm 유효 시간",
       "{{ (value_json.duration_ms / 1000) | int }}", "s",
       "mdi:clock-edit-outline"),
      ("cfg_relay_cooldown", "[Gatekeeper] [설정] 릴레이 쿨다운 시간",
       "{{ (value_json.relay_cooldown_ms / 1000) | int }}", "s",
       "mdi:timer-cog-outline"),
  )
  for object_id, name, value_template, unit, icon in config_sensors:
    config = _base_config(name, object_id, availability_topic)
    config.update({
        "entity_category": "diagnostic",
        "icon": icon,
        "state_topic": config_topic,
        "unit_of_measurement": unit,
        "value_template": value_template,
    })
    publications.append(_discovery_publication("sensor", object_id, config))

  legacy_controls = {
      "button": ("open_gate", "trigger_ota", "reboot"),
      "number": (
          "config_tx_power_num",
          "config_dist_thresh_num",
          "config_duration_num",
          "config_relay_cooldown_num",
      ),
  }
  control_removals = []
  for component, object_ids in legacy_controls.items():
    for object_id in object_ids:
      control_removals.append(Publication(
          topic=(f"homeassistant/{component}/{DEVICE_ID}/"
                 f"{object_id}/config"),
          payload="",
      ))
  return control_removals + publications


def _read_secret(file_path, env_name, label):
  env_present = env_name in os.environ
  if file_path is not None and env_present:
    raise ValueError(
        f"choose either {label} file or {env_name}, not both")
  if file_path is not None:
    value = Path(file_path).read_text(encoding="utf-8").rstrip("\r\n")
  else:
    value = os.environ.get(env_name)
  if value == "":
    raise ValueError(f"{label} source is empty")
  return value


def _resolve_ca_file(argument):
  env_value = os.environ.get(CA_FILE_ENV)
  if argument is not None and env_value:
    raise ValueError(
        f"choose either TLS CA file argument or {CA_FILE_ENV}, not both")
  value = argument if argument is not None else env_value
  if value is None:
    return None
  path = Path(value)
  if not path.is_file():
    raise ValueError("TLS CA file is not a readable file")
  return path


def _mqtt_client(mqtt_module, client_id):
  if hasattr(mqtt_module, "CallbackAPIVersion"):
    return mqtt_module.Client(
        mqtt_module.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt_module.MQTTv311,
    )
  return mqtt_module.Client(
      client_id=client_id, protocol=mqtt_module.MQTTv311)


def publish_plan(host, port, plan, username=None, password=None,
                 use_tls=False, ca_file=None, timeout_seconds=15):
  try:
    import paho.mqtt.client as mqtt
  except ImportError as exc:
    raise RuntimeError(
        "paho-mqtt is required for --apply; install backend requirements") \
        from exc

  client = _mqtt_client(mqtt, f"sgk-ha-migrate-{uuid.uuid4().hex[:10]}")
  if username is not None:
    client.username_pw_set(username, password)
  if use_tls or ca_file is not None:
    client.tls_set(
        ca_certs=str(ca_file) if ca_file is not None else None,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)

  loop_started = False
  try:
    connect_result = client.connect(host, port, keepalive=30)
    if connect_result != mqtt.MQTT_ERR_SUCCESS:
      raise RuntimeError("MQTT connection was not accepted")
    client.loop_start()
    loop_started = True
    for publication in plan:
      info = client.publish(
          publication.topic,
          payload=publication.payload,
          qos=publication.qos,
          retain=publication.retain,
      )
      if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError("MQTT publish could not be queued")
      info.wait_for_publish(timeout=timeout_seconds)
      if hasattr(info, "is_published") and not info.is_published():
        raise TimeoutError("MQTT retained publish acknowledgement timed out")
  finally:
    try:
      client.disconnect()
    finally:
      if loop_started:
        client.loop_stop()


def build_parser():
  parser = argparse.ArgumentParser(
      description=(
          "Migrate 15 read-only HA entities to secure per-Target topics; "
          "default is network-free dry-run."),
      epilog=(
          f"Credential environment variables: {USERNAME_ENV}, "
          f"{PASSWORD_ENV}. Optional CA-file environment variable: "
          f"{CA_FILE_ENV}."))
  parser.add_argument("--broker-host", required=True)
  parser.add_argument("--broker-port", required=True, type=int)
  parser.add_argument("--target-id", required=True)
  parser.add_argument("--apply", action="store_true")
  parser.add_argument(
      "--tls", action="store_true",
      help="enable TLS with system trust; a CA file also enables TLS")
  parser.add_argument("--tls-ca-file", type=Path)
  parser.add_argument("--username-file", type=Path)
  parser.add_argument("--password-file", type=Path)
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  if not 1 <= args.broker_port <= 65535:
    raise ValueError("broker port must be between 1 and 65535")
  plan = build_plan(args.target_id)
  updates = sum(1 for item in plan if item.payload)
  removals = len(plan) - updates

  if not args.apply:
    print(
        f"DRY_RUN discovery_updates={updates} "
        f"legacy_control_removals={removals} total={len(plan)}")
    print("No network connection or MQTT publish was attempted.")
    print("Use --apply only after reviewing the target and broker inputs.")
    return 0

  username = _read_secret(args.username_file, USERNAME_ENV, "username")
  password = _read_secret(args.password_file, PASSWORD_ENV, "password")
  if (username is None) != (password is None):
    raise ValueError("username and password must be supplied together")
  ca_file = _resolve_ca_file(args.tls_ca_file)
  use_tls = args.tls or ca_file is not None
  if username is not None and not use_tls:
    raise ValueError("credentialed MQTT apply requires TLS")
  try:
    publish_plan(
        args.broker_host,
        args.broker_port,
        plan,
        username=username,
        password=password,
        use_tls=use_tls,
        ca_file=ca_file,
    )
  except Exception as exc:
    message = str(exc)
    for secret in (username, password):
      if secret:
        message = message.replace(secret, "[REDACTED]")
    print(f"ERROR: {exc.__class__.__name__}: {message}", file=sys.stderr)
    return 1
  print(
      f"APPLIED discovery_updates={updates} "
      f"legacy_control_removals={removals} total={len(plan)}")
  print("All MQTT publishes used QoS 1 and retained=true.")
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except (OSError, ValueError) as exc:
    print(f"ERROR: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    raise SystemExit(2)
