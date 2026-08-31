"""Source and behavior contracts for per-session ultrasonic isolation."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVALID_DISTANCE_CM = 999.0


def _insert_and_median(history: list[float], index: int, value: float) -> tuple[int, float]:
    history[index] = value
    return (index + 1) % len(history), sorted(history)[2]


class UltrasonicSessionIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.target_main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")
        cls.sensor = (ROOT / "src/UltrasonicSensor.cpp").read_text(encoding="utf-8")

    def test_local_gatt_action_one_resets_history_only_after_arm_acceptance(self) -> None:
        callback = self.target_main.split(
            "GattServer::setOnAuthGrantCallback", 1
        )[1].split("GattServer::setOnAuthAbortCallback", 1)[0]
        manual_branch, action_one = callback.split("const bool armed", 1)

        self.assertNotIn("UltrasonicSensor::resetHistory()", manual_branch)
        self.assertIn("g_access_fsm.handleAuthSuccess", action_one)
        self.assertIn("if (armed)", action_one)
        self.assertIn("UltrasonicSensor::resetHistory()", action_one)
        self.assertIn('DiagnosticsManager::noteAction("gatt_armed_fresh_sensor_history")', action_one)
        self.assertLess(
            action_one.index("g_access_fsm.handleAuthSuccess"),
            action_one.index("UltrasonicSensor::resetHistory()"),
        )
        self.assertLess(
            action_one.index("UltrasonicSensor::resetHistory()"),
            action_one.index("return armed"),
        )

    def test_reset_contract_uses_five_invalid_sentinels(self) -> None:
        reset = self.sensor.split("void UltrasonicSensor::resetHistory()", 1)[1].split(
            "float UltrasonicSensor::readDistanceCmRaw", 1
        )[0]
        self.assertIn("for (int i = 0; i < 5; i++)", reset)
        self.assertIn("history[i] = 999.0f", reset)
        self.assertIn("historyIdx = 0", reset)

    def test_new_session_requires_three_fresh_valid_samples(self) -> None:
        # This models the production five-slot median after resetHistory().
        history = [INVALID_DISTANCE_CM] * 5
        index = 0
        index, median = _insert_and_median(history, index, 40.0)
        self.assertEqual(INVALID_DISTANCE_CM, median)
        index, median = _insert_and_median(history, index, 42.0)
        self.assertEqual(INVALID_DISTANCE_CM, median)
        _, median = _insert_and_median(history, index, 41.0)
        self.assertEqual(42.0, median)

    def test_reset_prevents_prior_session_median_reuse(self) -> None:
        prior = [40.0, 41.0, 42.0, INVALID_DISTANCE_CM, INVALID_DISTANCE_CM]
        _, stale_median = _insert_and_median(prior, 3, INVALID_DISTANCE_CM)
        self.assertEqual(42.0, stale_median)

        fresh = [INVALID_DISTANCE_CM] * 5
        _, fresh_median = _insert_and_median(fresh, 0, INVALID_DISTANCE_CM)
        self.assertEqual(INVALID_DISTANCE_CM, fresh_median)


if __name__ == "__main__":
    unittest.main()
