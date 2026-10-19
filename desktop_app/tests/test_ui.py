"""Pengujian Tkinter nyata dengan database sementara, tidak memakai data pengguna."""

import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repository import ClinicRepository
from ui import ClinicApp


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = ClinicRepository(Path(self.temp.name) / "test.db")
        self.app = ClinicApp(self.repo)
        self.app.withdraw()
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.update()

    def tearDown(self):
        self.idle()
        self.app.close()
        self.temp.cleanup()

    def idle(self):
        deadline = time.monotonic() + 15
        while self.app.pending and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.app.update()
        self.assertEqual(self.app.pending, 0, "Operasi UI tidak selesai")
        self.assertEqual(self.errors, [], "Callback Tkinter mengeluarkan exception")

    def fill(self, dialog, values):
        for key, value in values.items():
            widget = dialog.inputs[key][0]
            if widget.winfo_class() == "Text":
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
            elif widget.winfo_class() == "TCombobox":
                widget.set(value)
            else:
                widget.delete(0, "end")
                widget.insert(0, value)
        dialog.submit_button.invoke()
        self.idle()

    def setup_admin(self):
        dialog = self.app.setup_admin()
        self.fill(dialog, {"name": "Admin UI", "username": "admin", "password": "Admin1234", "confirmation": "Admin1234"})
        self.assertFalse(dialog.winfo_exists())

    def login(self, username, password):
        self.app.login_vars["username"].set(username)
        self.app.login_vars["password"].set(password)
        self.app.login_button.invoke()
        self.idle()

    def test_admin_add_doctor_error_retry_and_persistence(self):
        self.setup_admin()
        self.login("admin", "Admin1234")
        self.assertEqual(self.app.session["role"], "ADMIN")
        dialog = self.app.add_doctor()
        self.fill(dialog, {"name": "Dokter UI", "username": "admin", "password": "Dokter1234"})
        self.assertTrue(dialog.winfo_exists())
        self.assertIn("Username sudah terdaftar", dialog.error.get())
        self.assertFalse(dialog.busy)
        self.fill(dialog, {"username": "dokter"})
        self.assertFalse(dialog.winfo_exists())
        self.app.show_page("Pengguna")
        self.idle()
        self.assertEqual(len(self.app.tree.get_children()), 2)
        self.repo.authenticate("dokter", "Dokter1234")
        self.assertEqual(self.repo.current_user()["role"], "DOCTOR")

    def test_patient_registration_and_complete_ui_workflow(self):
        self.setup_admin()
        self.login("admin", "Admin1234")
        self.fill(self.app.add_doctor(), {"name": "Dokter UI", "username": "dokter", "password": "Dokter1234"})
        self.app.show_login()
        self.fill(self.app.register_patient(), {"name": "Pasien UI", "username": "pasien", "password": "Pasien1234", "confirmation": "Pasien1234"})
        self.login("pasien", "Pasien1234")
        self.app.add_appointment()
        self.idle()
        self.fill(self.app.dialog, {"date": date.today().isoformat(), "time": "09:00", "complaint": "Keluhan uji antarmuka"})
        self.app.show_login()
        self.login("admin", "Admin1234")
        self.app.show_page("Pendaftaran")
        self.idle()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.app.actions.winfo_children()[0].invoke()
        self.idle()
        self.app.show_login()
        self.login("dokter", "Dokter1234")
        self.app.show_page("Pendaftaran")
        self.idle()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.app.actions.winfo_children()[0].invoke()
        self.fill(self.app.dialog, {"diagnosis": "Diagnosis UI", "treatment": "Tindakan UI", "medicines": "Resep uji"})
        self.app.show_page("Rekam Medis")
        self.idle()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.app.show_page("Resep")
        self.idle()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.assertEqual(next(iter(self.app.rows.values()))["medicines"], "Resep uji")
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        with patch("ui.messagebox.askyesno", return_value=True):
            self.app.actions.winfo_children()[0].invoke()
        self.idle()
        self.assertEqual(next(iter(self.app.rows.values()))["handover_name"], "Dokter UI")
        self.app.show_login()
        self.login("pasien", "Pasien1234")
        self.app.show_page("Resep")
        self.idle()
        self.assertEqual(self.app.actions.winfo_children(), [])
        self.assertEqual(next(iter(self.app.rows.values()))["status"], "COLLECTED")
        self.app.show_page("Pembayaran")
        self.idle()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        self.app.actions.winfo_children()[0].invoke()
        self.fill(self.app.dialog, {"reference": "UI-REF-001"})
        self.app.show_login()
        self.login("admin", "Admin1234")
        self.app.show_page("Pembayaran")
        self.idle()
        self.app.tree.selection_set(self.app.tree.get_children()[0])
        with patch("ui.messagebox.askyesno", return_value=True):
            self.app.actions.winfo_children()[0].invoke()
        self.idle()
        self.assertEqual(self.repo.payments()[0]["status"], "PAID")

    def test_wrong_password_keeps_login_usable_and_setup_hidden_for_existing_db(self):
        self.setup_admin()
        self.login("admin", "wrong")
        self.assertIsNone(self.app.session)
        self.assertIn("Username atau kata sandi", self.app.login_error.get())
        self.login("admin", "Admin1234")
        self.assertEqual(self.app.session["role"], "ADMIN")
        self.app.show_login()
        captions = [w.cget("text") for w in self.app.login_owner.winfo_children() if "text" in w.keys()]
        self.assertNotIn("Siapkan Admin Pertama", captions)
        self.assertIn("Daftar sebagai Pasien", captions)

    def test_callback_error_does_not_stop_background_result_polling(self):
        def broken_callback(_result):
            raise RuntimeError("Simulated render failure")

        self.app.run_task(self.app.login_owner, lambda: None, broken_callback)
        deadline = time.monotonic() + 5
        while not self.errors and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertEqual(len(self.errors), 1)
        self.errors.clear()
        received = []
        self.app.run_task(self.app.login_owner, lambda: "recovered", received.append)
        self.idle()
        self.assertEqual(received, ["recovered"])

    def test_account_dialog_fits_small_screen_and_remains_scrollable(self):
        # Toplevel transient tidak dipetakan jika jendela induknya withdrawn.
        self.app.deiconify()
        self.app.update()
        with patch.object(self.app, "winfo_screenheight", return_value=600):
            dialog = self.app.setup_admin()
        dialog.update()
        self.assertLessEqual(dialog.winfo_height(), 500)
        self.assertGreater(dialog.form_canvas.bbox("all")[3], dialog.form_canvas.winfo_height())
        last_input = dialog.controls[-1][0]
        last_input.focus_force()
        dialog.update()
        self.assertGreaterEqual(last_input.winfo_rooty(), dialog.winfo_rooty())
        self.assertLessEqual(last_input.winfo_rooty() + last_input.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())
        dialog.form_canvas.yview_moveto(1)
        dialog.update()
        self.assertLessEqual(dialog.submit_button.winfo_rooty() + dialog.submit_button.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
