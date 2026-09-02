#!/usr/bin/env python3
"""Migrate HA discovery to read-only state and backend-signed controls.

The default mode is a network-free dry run. ``--apply`` first removes seven
legacy direct-Target controls, then publishes backend-ingress controls and 18
read-only discovery documents.
Credentials are accepted only through fixed environment variables or files.
"""

import argparse
import os
import ssl
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

from backend.app.home_assistant_bridge import (  # noqa: E402
    Publication,
    build_discovery_plan,
)


USERNAME_ENV = "SGK_MQTT_USERNAME"
PASSWORD_ENV = "SGK_MQTT_PASSWORD"
CA_FILE_ENV = "SGK_MQTT_CA_FILE"


def build_plan(target_id, *, allow_manual_remote=False):
  return build_discovery_plan(
      target_id, allow_manual_remote=allow_manual_remote)


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
          "Migrate HA state and controls to a backend-signed bridge; "
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
      "--allow-manual-remote", action="store_true",
      help=(
          "publish the direct-open UI only after a dedicated HA broker ACL "
          "has been reviewed; other controls do not require this flag"))
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
  plan = build_plan(
      args.target_id, allow_manual_remote=args.allow_manual_remote)
  updates = sum(1 for item in plan if item.payload)
  removals = len(plan) - updates
  controls = sum(
      1 for item in plan if item.payload and
      ("/button/" in item.topic or "/number/" in item.topic))
  read_only = updates - controls

  if not args.apply:
    print(
      f"DRY_RUN discovery_updates={updates} "
        f"secure_controls={controls} read_only={read_only} "
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
      f"secure_controls={controls} read_only={read_only} "
      f"legacy_control_removals={removals} total={len(plan)}")
  print("All MQTT publishes used QoS 1 and retained=true.")
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except (OSError, ValueError) as exc:
    print(f"ERROR: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    raise SystemExit(2)
