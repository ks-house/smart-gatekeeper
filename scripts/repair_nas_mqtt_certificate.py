#!/usr/bin/env python3
"""Replace the NAS Mosquitto TLS files over pinned-host-key SFTP.

This is an intentionally narrow incident-recovery utility. Certificate and key
material are accepted only through environment variables, never through command
line arguments, and the generated report contains metadata only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import paramiko
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


EXPECTED_HOSTNAME = "tworimpa.synology.me"
EXPECTED_CURRENT_CERT_SHA256 = (
    "75c0bc223008e44f0867e274d9862a8921433afe91965fde14f03ac7c52ef13b"
)
EXPECTED_REPLACEMENT_CERT_SHA256 = (
    "f2c90a2b4a8b3181bb0ae6863618a0101139593ff55105518726a10c78a94e23"
)
REMOTE_DIRECTORY = "/docker/mosquitto/config"
REMOTE_FILES = {
    "certificate": f"{REMOTE_DIRECTORY}/cert.pem",
    "chain": f"{REMOTE_DIRECTORY}/chain.pem",
    "private_key": f"{REMOTE_DIRECTORY}/privkey.pem",
}
MAX_FILE_SIZE = 64 * 1024


def require_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def pem_bytes(name: str) -> bytes:
    value = require_environment(name).encode("utf-8")
    if len(value) > MAX_FILE_SIZE:
        raise RuntimeError(f"{name} exceeds the permitted size")
    if not value.endswith(b"\n"):
        value += b"\n"
    return value


def certificate_fingerprint(certificate: x509.Certificate) -> str:
    return certificate.fingerprint(hashes.SHA256()).hex()


def load_certificate(data: bytes, label: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError as exc:
        raise RuntimeError(f"{label} is not a valid PEM certificate") from exc


def load_private_key(data: bytes, label: str):
    try:
        return serialization.load_pem_private_key(data, password=None)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not a valid unencrypted PEM private key") from exc


def load_chain(data: bytes) -> list[x509.Certificate]:
    blocks = re.findall(
        br"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        data,
        flags=re.DOTALL,
    )
    if not blocks:
        raise RuntimeError("replacement chain does not contain a certificate")
    return [load_certificate(block, "replacement chain entry") for block in blocks]


def public_keys_match(certificate: x509.Certificate, private_key: Any) -> bool:
    cert_public = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return cert_public == key_public


def verify_leaf_signature(
    certificate: x509.Certificate, issuer: x509.Certificate
) -> None:
    issuer_key = issuer.public_key()
    try:
        if isinstance(issuer_key, rsa.RSAPublicKey):
            issuer_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                certificate.signature_hash_algorithm,
            )
        elif isinstance(issuer_key, ec.EllipticCurvePublicKey):
            issuer_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        else:
            raise RuntimeError("replacement issuer uses an unsupported public-key type")
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("replacement leaf signature does not verify against chain") from exc


def validate_replacement(
    certificate_data: bytes, chain_data: bytes, key_data: bytes
) -> dict[str, Any]:
    certificate = load_certificate(certificate_data, "replacement certificate")
    private_key = load_private_key(key_data, "replacement private key")
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise RuntimeError("replacement private key must be RSA for the current listener")
    if not public_keys_match(certificate, private_key):
        raise RuntimeError("replacement certificate and private key do not match")

    fingerprint = certificate_fingerprint(certificate)
    if fingerprint != EXPECTED_REPLACEMENT_CERT_SHA256:
        raise RuntimeError("replacement certificate fingerprint is not the approved export")

    try:
        names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound as exc:
        raise RuntimeError("replacement certificate has no DNS subjectAltName") from exc
    if EXPECTED_HOSTNAME not in names:
        raise RuntimeError("replacement certificate does not cover the broker hostname")

    now = datetime.now(timezone.utc)
    if certificate.not_valid_before_utc > now:
        raise RuntimeError("replacement certificate is not valid yet")
    if certificate.not_valid_after_utc <= now + timedelta(days=30):
        raise RuntimeError("replacement certificate has less than 30 days validity")

    chain = load_chain(chain_data)
    issuer = next(
        (candidate for candidate in chain if candidate.subject == certificate.issuer),
        None,
    )
    if issuer is None:
        raise RuntimeError("replacement chain does not contain the leaf issuer")
    verify_leaf_signature(certificate, issuer)

    return {
        "certificate_sha256": fingerprint,
        "not_before": certificate.not_valid_before_utc.isoformat(),
        "not_after": certificate.not_valid_after_utc.isoformat(),
        "dns_names": sorted(names),
        "key_type": "RSA",
        "chain_certificates": len(chain),
    }


def read_remote(sftp: paramiko.SFTPClient, path: str) -> bytes:
    attributes = sftp.stat(path)
    if not stat.S_ISREG(attributes.st_mode):
        raise RuntimeError(f"remote path is not a regular file: {path}")
    if attributes.st_size <= 0 or attributes.st_size > MAX_FILE_SIZE:
        raise RuntimeError(f"remote path has an invalid size: {path}")
    with sftp.open(path, "rb") as stream:
        data = stream.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise RuntimeError(f"remote path exceeded the permitted size: {path}")
    return data


def write_remote(
    sftp: paramiko.SFTPClient, path: str, data: bytes, mode: int
) -> None:
    try:
        sftp.stat(path)
    except OSError:
        pass
    else:
        raise RuntimeError(f"refusing to overwrite staging or backup path: {path}")
    with sftp.open(path, "wb") as stream:
        stream.write(data)
        stream.flush()
    sftp.chmod(path, mode)
    if hashlib.sha256(read_remote(sftp, path)).digest() != hashlib.sha256(data).digest():
        raise RuntimeError(f"remote readback mismatch: {path}")


def remove_if_present(sftp: paramiko.SFTPClient, path: str) -> None:
    try:
        sftp.remove(path)
    except OSError:
        pass


def parse_mosquitto_tls_paths(configuration: bytes) -> dict[str, str]:
    try:
        text = configuration.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("mosquitto.conf is not UTF-8") from exc
    directives: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise RuntimeError("mosquitto.conf contains an invalid directive") from exc
        if len(parts) >= 2 and parts[0] in {"certfile", "keyfile", "cafile"}:
            directives[parts[0]] = parts[1]
    expected_basenames = {
        "certfile": "cert.pem",
        "keyfile": "privkey.pem",
        "cafile": "chain.pem",
    }
    for directive, basename in expected_basenames.items():
        configured = directives.get(directive, "")
        if not configured or configured.rstrip("/").split("/")[-1] != basename:
            raise RuntimeError(f"mosquitto.conf does not reference {basename}")
    return directives


def restore_originals(
    sftp: paramiko.SFTPClient,
    originals: dict[str, bytes],
    modes: dict[str, int],
    suffix: str,
) -> None:
    for label, destination in REMOTE_FILES.items():
        recovery_path = f"{destination}.recovery-{suffix}"
        remove_if_present(sftp, recovery_path)
        with sftp.open(recovery_path, "wb") as stream:
            stream.write(originals[label])
            stream.flush()
        sftp.chmod(recovery_path, modes[label])
        sftp.posix_rename(recovery_path, destination)


def main() -> int:
    report_path = Path("evidence/nas-mqtt-certificate-repair.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "remote_directory": REMOTE_DIRECTORY,
        "replacement_completed": False,
        "restart_required": False,
    }
    client: paramiko.SSHClient | None = None
    sftp: paramiko.SFTPClient | None = None
    originals: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    replacements_started = False
    suffix = ""
    try:
        host = require_environment("NAS_HOST")
        user = require_environment("NAS_USER")
        password = require_environment("NAS_PASSWORD")
        port_text = require_environment("NAS_PORT")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            raise RuntimeError("NAS_HOST format is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}", user):
            raise RuntimeError("NAS_USER format is invalid")
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise RuntimeError("NAS_PORT format is invalid")

        certificate_data = pem_bytes("MQTT_TLS_CERT_PEM")
        chain_data = pem_bytes("MQTT_TLS_CHAIN_PEM")
        key_data = pem_bytes("MQTT_TLS_PRIVATE_KEY_PEM")
        replacement_metadata = validate_replacement(
            certificate_data, chain_data, key_data
        )
        replacement_data = {
            "certificate": certificate_data,
            "chain": chain_data,
            "private_key": key_data,
        }

        run_id = require_environment("GITHUB_RUN_ID")
        run_attempt = require_environment("GITHUB_RUN_ATTEMPT")
        if not run_id.isdigit() or not run_attempt.isdigit():
            raise RuntimeError("GitHub run identity is invalid")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"{timestamp}-{run_id}-{run_attempt}"

        known_hosts = Path(os.environ["RUNNER_TEMP"]) / "nas_known_hosts"
        known_hosts.write_text(
            require_environment("NAS_KNOWN_HOSTS").rstrip("\r\n") + "\n",
            encoding="utf-8",
        )
        known_hosts.chmod(0o600)

        client = paramiko.SSHClient()
        client.load_host_keys(str(known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=host,
            port=int(port_text),
            username=user,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
        )
        sftp = client.open_sftp()

        tls_paths = parse_mosquitto_tls_paths(
            read_remote(sftp, f"{REMOTE_DIRECTORY}/mosquitto.conf")
        )
        for label, path in REMOTE_FILES.items():
            attributes = sftp.stat(path)
            modes[label] = stat.S_IMODE(attributes.st_mode)
            originals[label] = read_remote(sftp, path)

        current_certificate = load_certificate(
            originals["certificate"], "current remote certificate"
        )
        current_fingerprint = certificate_fingerprint(current_certificate)
        if current_fingerprint != EXPECTED_CURRENT_CERT_SHA256:
            raise RuntimeError(
                "current remote certificate changed since the read-only audit"
            )
        current_key = load_private_key(
            originals["private_key"], "current remote private key"
        )
        if not public_keys_match(current_certificate, current_key):
            raise RuntimeError("current remote certificate and key do not match")

        backup_paths: dict[str, str] = {}
        staging_paths: dict[str, str] = {}
        for label, path in REMOTE_FILES.items():
            backup_path = f"{path}.backup-{suffix}-{current_fingerprint[:12]}"
            staging_path = f"{path}.next-{suffix}"
            write_remote(sftp, backup_path, originals[label], modes[label])
            write_remote(sftp, staging_path, replacement_data[label], modes[label])
            backup_paths[label] = backup_path
            staging_paths[label] = staging_path

        staged_metadata = validate_replacement(
            read_remote(sftp, staging_paths["certificate"]),
            read_remote(sftp, staging_paths["chain"]),
            read_remote(sftp, staging_paths["private_key"]),
        )
        if staged_metadata != replacement_metadata:
            raise RuntimeError("staged replacement metadata changed during transfer")

        replacements_started = True
        for label in ("chain", "private_key", "certificate"):
            sftp.posix_rename(staging_paths[label], REMOTE_FILES[label])

        installed_metadata = validate_replacement(
            read_remote(sftp, REMOTE_FILES["certificate"]),
            read_remote(sftp, REMOTE_FILES["chain"]),
            read_remote(sftp, REMOTE_FILES["private_key"]),
        )
        if installed_metadata != replacement_metadata:
            raise RuntimeError("installed replacement did not pass final validation")

        report.update(
            {
                "replacement_completed": True,
                "restart_required": True,
                "previous_certificate_sha256": current_fingerprint,
                "replacement": replacement_metadata,
                "backup_paths": backup_paths,
                "configured_tls_basenames": {
                    name: value.rstrip("/").split("/")[-1]
                    for name, value in tls_paths.items()
                },
            }
        )
        return 0
    except Exception as exc:
        if replacements_started and sftp is not None and originals:
            try:
                restore_originals(sftp, originals, modes, suffix)
                report["automatic_restore_completed"] = True
            except Exception:
                report["automatic_restore_completed"] = False
        report["error_type"] = exc.__class__.__name__
        raise RuntimeError("NAS Mosquitto certificate replacement failed safely") from exc
    finally:
        if sftp is not None:
            sftp.close()
        if client is not None:
            client.close()
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
