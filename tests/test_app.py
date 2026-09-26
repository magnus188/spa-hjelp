import tempfile
import unittest
import shutil
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
        blocked = self.client.post("/api/confirm", json={})
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("ikke tilsettes samtidig", blocked.json["error"])

    def test_invalid_reading_rejected(self):
        bad = self.client.post("/api/measurements", json={"ph": 17})
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
