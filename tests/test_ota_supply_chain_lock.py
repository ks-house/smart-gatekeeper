import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HASH_RE = re.compile(r"    --hash=sha256:([0-9a-f]{64})(?: \\)?$")
PIN_RE = re.compile(
    r"([a-z0-9][a-z0-9._-]*)==([^ ;\\]+)(?: ; (.+))? \\$"
)


def _normalized_name(name: str) -> str:
  return re.sub(r"[-_.]+", "-", name).lower()


def _direct_pins() -> dict[str, str]:
  pins: dict[str, str] = {}
  for line in (ROOT / "ota/requirements.txt").read_text(
      encoding="utf-8"
  ).splitlines():
    if not line or line.startswith("#"):
      continue
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^ ;]+)", line)
    if match is None:
      raise AssertionError(f"OTA direct dependency is not exactly pinned: {line}")
    pins[_normalized_name(match.group(1))] = match.group(2)
  return pins


def _locked_stanzas() -> list[tuple[str, str, str | None, tuple[str, ...]]]:
  lines = (ROOT / "ota/requirements.lock").read_text(
      encoding="utf-8"
  ).splitlines()
  stanzas: list[tuple[str, str, str | None, tuple[str, ...]]] = []
  index = 0
  while index < len(lines):
    line = lines[index]
    if not line or line.startswith("#") or line.startswith("    #"):
      index += 1
      continue
    match = PIN_RE.fullmatch(line)
    if match is None:
      raise AssertionError(f"unexpected OTA lock syntax: {line}")
    hashes: list[str] = []
    index += 1
    while index < len(lines):
      hash_match = HASH_RE.fullmatch(lines[index])
      if hash_match is None:
        break
      hashes.append(hash_match.group(1))
      index += 1
    if not hashes:
      raise AssertionError(f"locked dependency has no SHA-256: {line}")
    if len(hashes) != len(set(hashes)):
      raise AssertionError(f"locked dependency repeats a SHA-256: {line}")
    stanzas.append(
        (
            _normalized_name(match.group(1)),
            match.group(2),
            match.group(3),
            tuple(hashes),
        )
    )
  return stanzas


class OtaSupplyChainLockTests(unittest.TestCase):
  def test_all_direct_and_transitive_dependencies_are_hash_locked(self):
    direct = _direct_pins()
    self.assertEqual(
        direct,
        {
            "cryptography": "48.0.0",
            "jsonschema": "4.26.0",
            "paramiko": "5.0.0",
            "platformio": "6.1.19",
            "pyyaml": "6.0.3",
        },
    )
    stanzas = _locked_stanzas()
    self.assertGreater(len(stanzas), len(direct))
    for name, version in direct.items():
      self.assertIn((name, version), {(item[0], item[1]) for item in stanzas})

  def test_one_lock_resolves_python_310_and_312_conditions(self):
    lock = (ROOT / "ota/requirements.lock").read_text(encoding="utf-8")
    self.assertIn("uv pip compile --universal --python-version 3.10", lock)
    self.assertIn("--generate-hashes", lock)
    self.assertIn("--exclude-newer 2026-08-23T00:00:00Z", lock)
    stanzas = _locked_stanzas()
    markers = {(name, marker) for name, _, marker, _ in stanzas}
    self.assertIn(("exceptiongroup", "python_full_version < '3.11'"), markers)
    self.assertIn(("rpds-py", "python_full_version < '3.11'"), markers)
    self.assertIn(("rpds-py", "python_full_version >= '3.11'"), markers)

  def test_gradle_wrapper_distributions_have_official_checksums(self):
    # Values are published by https://gradle.org/release-checksums/.
    expected = {
        "gatekeeper_app/android/gradle/wrapper/gradle-wrapper.properties": (
            "https\\://services.gradle.org/distributions/gradle-9.1.0-all.zip",
            "b84e04fa845fecba48551f425957641074fcc00a88a84d2aae5808743b35fc85",
        ),
        (
            "gatekeeper_app/android/app/libs/flutter_beacon_local/android/"
            "gradle/wrapper/gradle-wrapper.properties"
        ): (
            "https\\://services.gradle.org/distributions/gradle-5.4.1-all.zip",
            "14cd15fc8cc8705bd69dcfa3c8fefb27eb7027f5de4b47a8b279218f76895a91",
        ),
    }
    for relative_path, (url, sha256) in expected.items():
      with self.subTest(path=relative_path):
        properties = {}
        for line in (ROOT / relative_path).read_text(encoding="utf-8").splitlines():
          if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            self.assertNotIn(key, properties)
            properties[key] = value
        self.assertEqual(properties["distributionUrl"], url)
        self.assertEqual(properties["distributionSha256Sum"], sha256)


if __name__ == "__main__":
  unittest.main()
