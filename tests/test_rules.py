import unittest
from datetime import datetime, timedelta, timezone

from rules import chlorine_estimate, recommendation


NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)


def measurement(**changes):
    value = {
        "measured_at": (NOW - timedelta(minutes=1)).isoformat(),
        "ph": 7.2, "alkalinity_mg_l": 100, "chlorine_mg_l": 0.2,
    }
    value.update(changes)
    return value


def flow(kind, step=0, meta=None):
    return {"id": 1, "kind": kind, "step": step, "meta": meta or {},
            "created_at": (NOW - timedelta(minutes=2)).isoformat(),
            "updated_at": (NOW - timedelta(minutes=1)).isoformat()}


class RecipeTests(unittest.TestCase):
    def test_small_chlorine_increase_is_a_warning_not_a_whole_scoop(self):
        result = chlorine_estimate(0.2, 1000, 15, 0.2)
        self.assertAlmostEqual(result["amount_ml"], 0.364, places=3)
        self.assertAlmostEqual(result["scoops"], 0.0242, places=4)
        self.assertTrue(result["hard_to_measure"])
        self.assertEqual(result["projected_mg_l"], 0.4)

    def test_new_water_scales_no_scale_but_not_sundances_two_spoons(self):
        settings = {"volume_liters": 1700}
        first = recommendation(flow("new_water"), settings, measurement(), [], NOW)
        self.assertEqual(first["product"], "no_scale")
        self.assertEqual(first["amount_ml"], 85)
        additions = [{"product": "no_scale", "flow_id": 1,
                      "added_at": (NOW - timedelta(minutes=11)).isoformat()}]
        second = recommendation(flow("new_water", 1), settings, measurement(), additions, NOW)
        self.assertEqual(second["product"], "mini_chlor")
        self.assertEqual(second["amount_ml"], 30)

    def test_weekly_prioritizes_ta_then_ph_and_uses_small_steps(self):
        settings = {"volume_liters": 1000}
        low_ta = recommendation(flow("weekly"), settings,
                                measurement(alkalinity_mg_l=70, ph=7.8), [], NOW)
        self.assertEqual(low_ta["product"], "alka_up")
        self.assertEqual(low_ta["amount_ml"], 20)
        high_ph = recommendation(flow("weekly"), settings,
                                 measurement(alkalinity_mg_l=100, ph=7.8), [], NOW)
        self.assertEqual(high_ph["product"], "ph_down")
        self.assertAlmostEqual(high_ph["amount_ml"], 6)
        balanced = recommendation(flow("weekly"), settings, measurement(), [], NOW)
        self.assertEqual(balanced["product"], "mini_chlor")

    def test_weekly_waits_for_a_reading_after_two_hours(self):
        additions = [{"product": "alka_up", "flow_id": 1,
                      "added_at": (NOW - timedelta(hours=1)).isoformat()}]
        early = recommendation(flow("weekly"), {"volume_liters": 1000},
                               measurement(), additions, NOW)
        self.assertEqual(early["type"], "wait")
        additions[0]["added_at"] = (NOW - timedelta(hours=3)).isoformat()
        stale = recommendation(flow("weekly"), {"volume_liters": 1000},
                               measurement(measured_at=(NOW - timedelta(hours=2)).isoformat()),
                               additions, NOW)
        self.assertEqual(stale["type"], "measure")

    def test_adjustment_rejects_readings_taken_before_wait_ends(self):
        adjustment = flow("adjust", meta={"targets": {"alkalinity_mg_l": 100}})
        added = [{"product": "alka_up", "flow_id": 1,
                  "added_at": (NOW - timedelta(hours=1)).isoformat()}]
        early_reading = measurement(alkalinity_mg_l=100,
                                    measured_at=(NOW - timedelta(minutes=5)).isoformat())
        self.assertEqual(recommendation(adjustment, {"volume_liters": 1500},
                                        early_reading, added, NOW)["type"], "wait")
        added[0]["added_at"] = (NOW - timedelta(hours=3)).isoformat()
        early_reading["measured_at"] = (NOW - timedelta(hours=2, minutes=30)).isoformat()
        self.assertEqual(recommendation(adjustment, {"volume_liters": 1500},
                                        early_reading, added, NOW)["type"], "measure")

    def test_before_bath_uses_sundances_extra_spoon_after_three_people(self):
        rec = recommendation(flow("before_bath", meta={"bathers": 5}),
                             {"volume_liters": 1700}, measurement(), [], NOW)
        self.assertEqual(rec["product"], "active_oxygen")
        self.assertEqual(rec["amount_ml"], 75)

    def test_holiday_enforces_five_minute_gap_then_volume_dose(self):
        meta = {"departure_date": "2026-09-26", "return_date": "2026-10-03"}
        addition = {"product": "mini_chlor", "flow_id": 1,
                    "added_at": (NOW - timedelta(minutes=2)).isoformat()}
        waiting = recommendation(flow("holiday", 2, meta), {"volume_liters": 1700},
                                 measurement(), [addition], NOW)
        self.assertEqual(waiting["type"], "wait")
        addition["added_at"] = (NOW - timedelta(minutes=6)).isoformat()
        ready = recommendation(flow("holiday", 2, meta), {"volume_liters": 1700},
                               measurement(), [addition], NOW)
        self.assertEqual(ready["product"], "oxyplus")
        self.assertEqual(ready["amount_ml"], 34)


if __name__ == "__main__":
    unittest.main()
