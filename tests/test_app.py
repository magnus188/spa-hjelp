import tempfile
import unittest
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import create_app
from storage import connect


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.directory.name) / "spa.sqlite3")
        self.app = create_app({"TESTING": True, "DB_PATH": self.db_path})
        self.client = self.app.test_client()
        self.client.post("/api/settings", json={"volume_liters": 1700, "scoops": {"mini_chlor": 10}})
        self.client.post("/api/measurements", json={"ph": 7.2, "alkalinity_mg_l": 100,
                                                     "chlorine_mg_l": 0.2})

    def tearDown(self):
        self.directory.cleanup()

    def test_summary_and_tiny_chlorine_dose_survive_restart(self):
        estimate = self.client.post("/api/chlorine-estimate", json={"delta_mg_l": 0.2}).json
        self.assertAlmostEqual(estimate["amount_ml"], 0.618, places=3)
        self.assertAlmostEqual(estimate["scoops"], 0.0618, places=4)
        self.assertTrue(estimate["hard_to_measure"])
        response = self.client.post("/api/chlorine-add", json={"delta_mg_l": 0.2})
        self.assertEqual(response.status_code, 201)
        fresh_app = create_app({"TESTING": True, "DB_PATH": self.db_path})
        summary = fresh_app.test_client().get("/api/summary").json
        self.assertTrue(summary["cover_open"])
        self.assertEqual(summary["last_added"]["product"], "mini_chlor")
        self.assertEqual(summary["last_added"]["amount_ml"], 0.618)
        self.assertEqual(summary["volume_liters"], 1700)

    def test_sqlite_backup_can_be_restored(self):
        self.client.post("/api/chlorine-add", json={"delta_mg_l": 0.2})
        restored = str(Path(self.directory.name) / "restored.sqlite3")
        shutil.copy2(self.db_path, restored)
        recovered = create_app({"TESTING": True, "DB_PATH": restored}).test_client().get("/api/summary").json
        self.assertEqual(recovered["measurements"]["chlorine_mg_l"], 0.2)
        self.assertEqual(recovered["last_added"]["amount_ml"], 0.618)
        self.assertTrue(recovered["cover_open"])

    def test_weekly_uses_custom_scoop_size(self):
        self.client.post("/api/flows", json={"kind": "weekly"})
        summary = self.client.get("/api/summary").json
        self.assertEqual(summary["next_step"]["amount_ml"], 30)
        self.assertEqual(summary["next_step"]["scoops"], 3)
        self.client.post("/api/confirm", json={})
        after = self.client.get("/api/summary").json
        self.assertEqual(after["next_step"]["type"], "done")
        self.assertEqual(after["last_added"]["scoop_ml"], 10)

    def test_holiday_requires_five_minutes_before_oxyplus(self):
        self.client.post("/api/flows", json={
            "kind": "holiday", "departure_date": date.today().isoformat(),
            "return_date": (date.today() + timedelta(days=7)).isoformat(),
        })
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "check")
        self.client.post("/api/confirm", json={})  # filter
        self.client.post("/api/confirm", json={})  # MiniChlor
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "wait")
        self.assertEqual(self.client.post("/api/confirm", json={}).status_code, 400)
        with connect(self.db_path) as db:
            older = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
            db.execute("UPDATE additions SET added_at = ? WHERE product = 'mini_chlor'", (older,))
        ready = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(ready["product"], "oxyplus")
        self.assertEqual(ready["amount_ml"], 34)
        self.client.post("/api/confirm", json={})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "check")
        self.client.post("/api/confirm", json={})  # temperature
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "away")

    def test_active_oxygen_and_chlorine_cannot_be_logged_together(self):
        self.client.post("/api/chlorine-add", json={"delta_mg_l": 0.2})
        self.client.post("/api/flows", json={"kind": "before_bath", "bathers": 2})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "wait")
        blocked = self.client.post("/api/confirm", json={})
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("ikke bekreftes", blocked.json["error"])

    def test_default_volume_and_existing_volume_are_preserved(self):
        fresh_path = str(Path(self.directory.name) / "fresh.sqlite3")
        fresh = create_app({"TESTING": True, "DB_PATH": fresh_path}).test_client()
        self.assertEqual(fresh.get("/api/summary").json["volume_liters"], 1500)
        self.assertEqual(create_app({"TESTING": True, "DB_PATH": self.db_path})
                         .test_client().get("/api/summary").json["volume_liters"], 1700)

    def test_adjustment_sequence_waits_and_remeasures(self):
        self.client.post("/api/settings", json={"volume_liters": 1500})
        self.client.post("/api/measurements", json={
            "alkalinity_mg_l": 70, "ph": 6.8, "chlorine_mg_l": 0.2,
            "active_oxygen_mg_l": 2,
        })
        started = self.client.post("/api/flows", json={"kind": "adjust", "increments": {
            "alkalinity_mg_l": 30, "ph": 0.4, "chlorine_mg_l": 0.2,
            "active_oxygen_mg_l": 4,
        }})
        self.assertEqual(started.status_code, 201)
        first = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(first["product"], "alka_up")
        self.assertEqual(first["amount_ml"], 90)
        self.client.post("/api/confirm", json={})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "wait")
        with connect(self.db_path) as db:
            db.execute("UPDATE additions SET added_at = ? WHERE product = 'alka_up'",
                       ((datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),))
            db.execute("UPDATE measurements SET measured_at = ?",
                       ((datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),))
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "measure")
        self.client.post("/api/measurements", json={"alkalinity_mg_l": 100, "ph": 6.8})
        second = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(second["product"], "ph_up")
        self.assertEqual(second["amount_ml"], 15)
        self.client.post("/api/confirm", json={})
        with connect(self.db_path) as db:
            db.execute("UPDATE additions SET added_at = ? WHERE product = 'ph_up'",
                       ((datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),))
        self.client.post("/api/measurements", json={"ph": 7.2, "chlorine_mg_l": 0.2})
        third = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(third["product"], "mini_chlor")
        self.assertAlmostEqual(third["amount_ml"], 0.545, places=3)
        self.client.post("/api/confirm", json={})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "wait")
        with connect(self.db_path) as db:
            db.execute("UPDATE additions SET added_at = ? WHERE product = 'mini_chlor'",
                       ((datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat(),))
        self.client.post("/api/measurements", json={"chlorine_mg_l": 0.4,
                                                     "active_oxygen_mg_l": 3})
        fourth = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(fourth["product"], "active_oxygen")
        self.assertEqual(fourth["amount_ml"], 45)
        self.client.post("/api/confirm", json={})
        with connect(self.db_path) as db:
            db.execute("UPDATE additions SET added_at = ? WHERE product = 'active_oxygen'",
                       ((datetime.now(timezone.utc) - timedelta(minutes=21)).isoformat(),))
        self.client.post("/api/measurements", json={"active_oxygen_mg_l": 5,
                                                     "chlorine_mg_l": 0.1})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "done")

    def test_negative_readings_are_rejected_and_decimals_are_rounded(self):
        bad = self.client.post("/api/measurements", json={"ph": -0.01})
        self.assertEqual(bad.status_code, 400)
        bad_oxygen = self.client.post("/api/measurements", json={"active_oxygen_mg_l": -0.01})
        self.assertEqual(bad_oxygen.status_code, 400)
        accepted = self.client.post("/api/measurements", json={
            "method": "machine", "ph": 7.256, "alkalinity_mg_l": 100.25,
            "chlorine_mg_l": 0.256,
        })
        self.assertEqual(accepted.status_code, 201)
        readings = self.client.get("/api/summary").json["measurements"]
        self.assertEqual(readings["ph"], 7.26)
        self.assertEqual(readings["alkalinity_mg_l"], 100.25)
        self.assertEqual(readings["chlorine_mg_l"], 0.26)

    def test_oxygen_only_reading_keeps_other_values_and_chlorine_estimate(self):
        response = self.client.post("/api/measurements", json={"active_oxygen_mg_l": 5})
        self.assertEqual(response.status_code, 201)
        summary = self.client.get("/api/summary").json
        self.assertEqual(summary["measurements"]["active_oxygen_mg_l"], 5)
        self.assertEqual(summary["measurements"]["ph"], 7.2)
        self.assertEqual(summary["measurements"]["alkalinity_mg_l"], 100)
        self.assertEqual(summary["measurements"]["chlorine_mg_l"], 0.2)
        self.assertNotEqual(summary["measurements"]["field_measured_at"]["chlorine_mg_l"],
                            summary["measurements"]["measured_at"])
        estimate = self.client.post("/api/chlorine-estimate", json={"delta_mg_l": 0.2})
        self.assertEqual(estimate.status_code, 200)
        self.assertEqual(estimate.json["projected_mg_l"], 0.4)

    def test_oxygen_only_does_not_make_old_chlorine_fresh(self):
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with connect(self.db_path) as db:
            db.execute("UPDATE measurements SET measured_at = ?", (old,))
        self.client.post("/api/measurements", json={"active_oxygen_mg_l": 7})
        summary = self.client.get("/api/summary").json
        self.assertEqual(summary["measurements"]["chlorine_mg_l"], 0.2)
        estimate = self.client.post("/api/chlorine-estimate", json={"delta_mg_l": 0.2})
        self.assertEqual(estimate.status_code, 400)
        self.assertIn("ny klormåling", estimate.json["error"])

    def test_existing_database_is_migrated_for_oxygen_readings(self):
        legacy_path = str(Path(self.directory.name) / "legacy.sqlite3")
        with sqlite3.connect(legacy_path) as db:
            db.execute("""CREATE TABLE measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                measured_at TEXT NOT NULL, ph REAL, alkalinity_mg_l REAL,
                chlorine_mg_l REAL, source TEXT NOT NULL)""")
            db.execute("""INSERT INTO measurements
                (measured_at, ph, alkalinity_mg_l, chlorine_mg_l, source)
                VALUES (?, 7.1, 90, 0.3, 'manual')""", (datetime.now(timezone.utc).isoformat(),))
        migrated = create_app({"TESTING": True, "DB_PATH": legacy_path}).test_client()
        self.assertEqual(migrated.post("/api/measurements", json={"active_oxygen_mg_l": 6}).status_code, 201)
        summary = migrated.get("/api/summary").json
        self.assertEqual(summary["measurements"]["active_oxygen_mg_l"], 6)
        self.assertEqual(summary["measurements"]["ph"], 7.1)

    def test_strips_store_desired_changes_without_pretending_they_are_values(self):
        response = self.client.post("/api/measurements", json={
            "method": "strip", "adjustments": {
                "ph": -0.2, "alkalinity_mg_l": 10,
                "chlorine_mg_l": 0.2, "active_oxygen_mg_l": 2,
            },
        })
        self.assertEqual(response.status_code, 201)
        summary = create_app({"TESTING": True, "DB_PATH": self.db_path}).test_client().get("/api/summary").json
        self.assertEqual(summary["measurements"]["method"], "strip")
        for field in ("ph", "alkalinity_mg_l", "chlorine_mg_l", "active_oxygen_mg_l"):
            self.assertIsNone(summary["measurements"][field])
        self.assertEqual(summary["measurements"]["adjustments"]["chlorine_mg_l"], 0.2)
        self.client.post("/api/flows", json={"kind": "before_bath"})
        step = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(step["product"], "alka_up")
        self.assertEqual(step["amount_ml"], 34)

    def test_large_strip_request_is_accepted_but_chlorine_is_dosed_in_one_step(self):
        self.client.post("/api/measurements", json={
            "method": "strip", "adjustments": {
                "ph": 0, "alkalinity_mg_l": 0,
                "chlorine_mg_l": 4.126, "active_oxygen_mg_l": 0,
            },
        })
        self.client.post("/api/flows", json={"kind": "before_bath"})
        summary = self.client.get("/api/summary").json
        self.assertEqual(summary["measurements"]["adjustments"]["chlorine_mg_l"], 4.13)
        self.assertEqual(summary["next_step"]["product"], "mini_chlor")
        self.assertIn("Første trinn", summary["next_step"]["description"])
        self.assertAlmostEqual(summary["next_step"]["amount_ml"], 9.273, places=3)

    def test_machine_has_only_three_values_and_high_chlorine_stops_dosing(self):
        invalid = self.client.post("/api/measurements", json={
            "method": "machine", "ph": 7.2, "alkalinity_mg_l": 100,
            "chlorine_mg_l": 4, "active_oxygen_mg_l": 6,
        })
        self.assertEqual(invalid.status_code, 400)
        self.client.post("/api/measurements", json={
            "method": "machine", "ph": 7.2, "alkalinity_mg_l": 100, "chlorine_mg_l": 4,
        })
        self.client.post("/api/flows", json={"kind": "before_bath"})
        step = self.client.get("/api/summary").json["next_step"]
        self.assertEqual(step["type"], "measure")
        self.assertIn("For mye klor", step["title"])
        self.assertEqual(self.client.post("/api/confirm", json={}).status_code, 400)
        self.client.post("/api/flows", json={"kind": "after_bath"})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "done")

    def test_after_bath_and_new_water_work_without_measurement(self):
        fresh_path = str(Path(self.directory.name) / "empty.sqlite3")
        fresh = create_app({"TESTING": True, "DB_PATH": fresh_path}).test_client()
        fresh.post("/api/flows", json={"kind": "after_bath"})
        self.assertEqual(fresh.get("/api/summary").json["next_step"]["product"], "mini_chlor")
        fresh.post("/api/flows", json={"kind": "new_water"})
        self.assertEqual(fresh.get("/api/summary").json["next_step"]["product"], "no_scale")

    def test_new_water_invalidates_readings_from_previous_fill(self):
        self.client.post("/api/flows", json={"kind": "new_water"})
        self.assertIsNone(self.client.get("/api/summary").json["measurements"]["chlorine_mg_l"])
        self.client.post("/api/flows", json={"kind": "before_bath"})
        self.assertEqual(self.client.get("/api/summary").json["next_step"]["type"], "measure")


if __name__ == "__main__":
    unittest.main()
