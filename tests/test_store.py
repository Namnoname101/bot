import tempfile
import unittest
from pathlib import Path

from webapp.store import (
    DEFAULT_CHECKLISTS,
    DEFAULT_RECIPES,
    WebAppStore,
    hash_password,
    verify_password,
)


class StoreLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "store.json"
        self.store = WebAppStore(path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_hashing_and_verification(self):
        h, salt = hash_password("secret123")
        self.assertTrue(verify_password("secret123", h, salt))
        self.assertFalse(verify_password("wrongpass", h, salt))
        self.assertFalse(verify_password("", h, salt))

    def test_default_checklists_and_recipes(self):
        checklists = self.store.get_checklists()
        self.assertIn("Pha Chế", checklists)
        self.assertIn("Phục Vụ", checklists)

        recipes = self.store.get_recipes()
        self.assertGreaterEqual(len(recipes), 4)

    def test_recipe_save_and_delete(self):
        item = self.store.save_recipe({
            "name": "Cà Phê Trứng",
            "group": "Cà Phê",
            "size": "M",
            "ingredients": "Trứng gà, cafe",
            "steps": "Đánh bông trứng",
        })
        self.assertIn("id", item)
        recipes = self.store.get_recipes()
        self.assertTrue(any(r["name"] == "Cà Phê Trứng" for r in recipes))

        ok = self.store.delete_recipe(item["id"])
        self.assertTrue(ok)
        recipes_after = self.store.get_recipes()
        self.assertFalse(any(r["name"] == "Cà Phê Trứng" for r in recipes_after))

    def test_petty_expenses(self):
        exp = self.store.add_petty_expense(
            nickname="an",
            role="Pha Chế",
            ca="Sáng",
            amount=50000,
            reason="Mua túi rác và đá",
        )
        self.assertEqual(exp["amount"], 50000)
        items = self.store.get_petty_expenses(10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["nickname"], "an")

    def test_shift_schedule(self):
        entry = self.store.save_shift_schedule(
            nickname="an",
            role="Pha Chế",
            slots={"T2": ["Sáng"], "T3": ["Chiều"]},
            note="Đi học buổi tối",
        )
        self.assertEqual(entry["nickname"], "an")
        all_sched = self.store.get_shift_schedules()
        self.assertIn("an", all_sched)
        self.assertEqual(all_sched["an"]["slots"]["T2"], ["Sáng"])

    def test_leave_request_flow(self):
        req = self.store.add_leave_request(
            nickname="an",
            role="Pha Chế",
            req_type="leave",
            date_str="10/10/2026",
            ca="Sáng",
            reason="Bận việc gia đình",
        )
        self.assertEqual(req["status"], "pending")
        req_id = req["id"]

        requests = self.store.get_leave_requests()
        self.assertTrue(any(r["id"] == req_id for r in requests))

        # Decide request
        decided = self.store.decide_leave_request(req_id, approve=True)
        self.assertIsNotNone(decided)
        self.assertEqual(decided["status"], "approved")

    def test_verify_login_modes(self):
        employees = [{"nickname": "an", "full_name": "Nguyễn An"}]

        # Default password login for employee
        ok, user, msg = self.store.verify_login("an", "123456789", employees)
        self.assertTrue(ok)
        self.assertTrue(user.get("must_change_password"))

        # Set custom password
        self.store.set_account_password("an", "my_new_pass")

        # Old password fails
        ok_old, _, _ = self.store.verify_login("an", "123456789", employees)
        self.assertFalse(ok_old)

        # New password succeeds and must_change_password is False
        ok_new, user_new, _ = self.store.verify_login("an", "my_new_pass", employees)
        self.assertTrue(ok_new)
        self.assertFalse(user_new.get("must_change_password"))


if __name__ == '__main__':
    unittest.main()
