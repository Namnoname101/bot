import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from webapp.store import WebAppStore, get_week_info


class RosterAndSwapsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_week_info_and_default_roster(self):
        w_info = get_week_info(0)
        self.assertIn("week_key", w_info)
        self.assertEqual(len(w_info["days"]), 7)

        roster = self.store.get_roster(w_info["week_key"])
        self.assertEqual(roster["status"], "draft")
        self.assertIn("T2_Sáng", roster["shifts"])
        self.assertEqual(roster["targets"]["T2_Sáng"], 2)

    def test_roster_save_draft_and_publish(self):
        w_key = "2026-10-05"
        self.store.save_roster_draft(
            week_key=w_key,
            shifts={"T2_Sáng": ["An", "Bình"], "T2_Tối": ["Chi"]},
            targets={"T2_Sáng": 2, "T2_Tối": 1},
            week_label="Tuần 05/10 - 11/10/2026",
        )
        roster = self.store.get_roster(w_key)
        self.assertEqual(roster["shifts"]["T2_Sáng"], ["An", "Bình"])
        self.assertEqual(roster["status"], "draft")

        # Publish roster
        pub = self.store.publish_roster(w_key)
        self.assertEqual(pub["status"], "published")
        self.assertTrue(bool(pub["published_at"]))

        # Check notifications generated for assigned staff An, Bình, Chi
        notifs_an = self.store.get_notifications("An")
        self.assertTrue(any("công bố" in n["title"] or "công bố" in n["message"] for n in notifs_an))

    def test_suggestion_engine_draft(self):
        w_key = "2026-10-05"
        # Setup registrations
        self.store.save_shift_schedule(
            nickname="An",
            role="Barista",
            slots={"T2": ["Sáng"], "T3": ["Chiều"]},
            target_shifts=3,
        )
        self.store.save_shift_schedule(
            nickname="Bình",
            role="Barista",
            slots={"T2": ["Sáng"], "T4": ["Tối"]},
            target_shifts=4,
        )
        employees = [
            {"nickname": "An", "role": "Barista"},
            {"nickname": "Bình", "role": "Barista"},
        ]

        suggested = self.store.suggest_roster(w_key, employees)
        self.assertEqual(suggested["status"], "draft")
        # T2_Sáng should have both An and Bình assigned
        self.assertIn("An", suggested["shifts"]["T2_Sáng"])
        self.assertIn("Bình", suggested["shifts"]["T2_Sáng"])

    def test_shift_swap_workflow_atomic(self):
        w_key = "2026-10-05"
        # Setup roster with An on T4 Tối and Bình on T4 Sáng
        self.store.save_roster_draft(
            week_key=w_key,
            shifts={"T4_Tối": ["An"], "T4_Sáng": ["Bình"]},
            week_label="Tuần 05/10 - 11/10/2026",
        )

        # Create swap request: An wants to swap T4 Tối with Bình's T4 Sáng
        swap = self.store.create_swap_request(
            week_key=w_key,
            requester="An",
            requester_role="Barista",
            requester_shift={"day": "T4", "ca": "Tối", "date": "07/10/2026", "time": "18:00 – 22:30"},
            target="Bình",
            target_role="Barista",
            target_shift={"day": "T4", "ca": "Sáng", "date": "07/10/2026", "time": "07:00 – 12:00"},
            reason="Bận việc gia đình buổi tối",
        )
        self.assertEqual(swap["status"], "pending")
        swap_id = swap["id"]

        # Bình gets a notification
        binh_notifs = self.store.get_notifications("Bình")
        self.assertTrue(any(n["type"] == "swap_received" for n in binh_notifs))

        # Admin approves the swap
        decided = self.store.decide_swap_request(swap_id, approve=True)
        self.assertIsNotNone(decided)
        self.assertEqual(decided["status"], "approved")

        # ATOMIC SWAP CHECK:
        # In T4_Tối, An should be replaced by Bình!
        # In T4_Sáng, Bình should be replaced by An!
        roster_after = self.store.get_roster(w_key)
        self.assertIn("Bình", roster_after["shifts"]["T4_Tối"])
        self.assertNotIn("An", roster_after["shifts"]["T4_Tối"])
        self.assertIn("An", roster_after["shifts"]["T4_Sáng"])
        self.assertNotIn("Bình", roster_after["shifts"]["T4_Sáng"])

        # Both get notifications that swap was approved
        an_notifs = self.store.get_notifications("An")
        self.assertTrue(any(n["type"] == "swap_approved" for n in an_notifs))

        # Test mark read
        first_notif = an_notifs[0]
        ok = self.store.mark_notification_read(first_notif["id"], "An")
        self.assertTrue(ok)
        unread = self.store.get_notifications("An", unread_only=True)
        self.assertFalse(any(n["id"] == first_notif["id"] for n in unread))


if __name__ == "__main__":
    unittest.main()
