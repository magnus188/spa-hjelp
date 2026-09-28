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
                             {"volume_liters": 1700}, measurement(chlorine_mg_l=1.2), [], NOW)
        self.assertEqual(rec["product"], "active_oxygen")
        self.assertEqual(rec["amount_ml"], 75)

    def test_strip_changes_follow_alkalinity_then_ph_and_stop_at_high_chlorine(self):
        strip = measurement(ph=None, alkalinity_mg_l=None, chlorine_mg_l=None,
                            active_oxygen_mg_l=None,
                            adjustments={"alkalinity_mg_l": -10, "ph": -0.2,
                                         "chlorine_mg_l": 0, "active_oxygen_mg_l": 0})
        settings = {"volume_liters": 1500}
        first = recommendation(flow("before_bath"), settings, strip, [], NOW)
        self.assertEqual(first["product"], "alka_down")
        self.assertEqual(first["amount_ml"], 22.5)
        strip["adjustments"]["alkalinity_mg_l"] = 0
        second = recommendation(flow("before_bath"), settings, strip, [], NOW)
        self.assertEqual(second["product"], "ph_down")
        strip["adjustments"]["ph"] = 0
        strip["adjustments"]["chlorine_mg_l"] = -0.2
        blocked = recommendation(flow("before_bath"), settings, strip, [], NOW)
        self.assertEqual(blocked["type"], "measure")
        self.assertEqual(blocked["title"], "For mye klor")

    def test_small_strip_chlorine_rise_is_theoretical_and_requires_recheck(self):
        strip = measurement(ph=None, alkalinity_mg_l=None, chlorine_mg_l=None,
                            active_oxygen_mg_l=None,
                            adjustments={"alkalinity_mg_l": 0, "ph": 0,
                                         "chlorine_mg_l": 0.2, "active_oxygen_mg_l": 2})
        settings = {"volume_liters": 1500}
        first = recommendation(flow("before_bath"), settings, strip, [], NOW)
        self.assertEqual(first["product"], "mini_chlor")
        self.assertEqual(first["amount_ml"], 0.545)
        self.assertTrue(first["estimated"])
        addition = {"product": "mini_chlor", "flow_id": 1,
                    "added_at": (NOW - timedelta(minutes=1)).isoformat()}
        self.assertEqual(recommendation(flow("before_bath"), settings, strip, [addition], NOW)["type"], "wait")
        addition["added_at"] = (NOW - timedelta(minutes=21)).isoformat()
        strip["measured_at"] = (NOW - timedelta(minutes=2)).isoformat()
        self.assertEqual(recommendation(flow("before_bath"), settings, strip, [addition], NOW)["type"], "measure")
        strip["measured_at"] = (NOW - timedelta(seconds=20)).isoformat()
        strip["adjustments"]["chlorine_mg_l"] = 0
        next_step = recommendation(flow("before_bath"), settings, strip, [addition], NOW)
        self.assertEqual(next_step["product"], "active_oxygen")
        self.assertIn("Ønsket O₂-økning", next_step["description"])

    def test_after_bath_waits_for_oxygen_cycle_without_measurement(self):
        addition = {"product": "active_oxygen", "flow_id": 4,
                    "added_at": (NOW - timedelta(minutes=3)).isoformat()}
        waiting = recommendation(flow("after_bath"), {"volume_liters": 1500}, None, [addition], NOW)
        self.assertEqual(waiting["type"], "wait")
        addition["added_at"] = (NOW - timedelta(minutes=21)).isoformat()
        ready = recommendation(flow("after_bath"), {"volume_liters": 1500}, None, [addition], NOW)
        self.assertEqual(ready["product"], "mini_chlor")

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
