import base64
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repository import ClinicError, ClinicRepository, check_password


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = self.open_repo("clinic.db")
        self.admin = self.repo.create_initial_admin("Admin Klinik", "admin", "Admin1234")
        self.login("admin")
        self.doctor = self.repo.create_doctor("Dokter Utama", "doctor", "Doctor1234", "Poli Umum")
        self.other_doctor = self.repo.create_doctor("Dokter Lain", "otherdoctor", "Doctor1234", "Poli Gigi")
        self.patient = self.repo.register_patient("Pasien Pertama", "patient", "Patient1234")
        self.other_patient = self.repo.register_patient("Pasien Kedua", "otherpatient", "Patient1234")
        self.today = date.today().isoformat()

    def open_repo(self, name):
        repo = ClinicRepository(Path(self.temp.name) / name)
        self.addCleanup(repo.close)
        return repo

    def login(self, who):
        password = "Admin1234" if who == "admin" else "Doctor1234" if "doctor" in who else "Patient1234"
        return self.repo.authenticate(who, password)

    def visit(self):
        self.login("patient")
        return self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "Keluhan untuk pengujian")

    def complete(self, medicines="Obat uji dan aturan pakai"):
        visit = self.visit()
        self.login("admin")
        self.repo.confirm_registration(visit["id"])
        self.login("doctor")
        self.repo.complete_examination(visit["id"], "Diagnosis uji", "Tindakan uji", medicines)
        return visit

    def test_complete_workflow_and_persistence(self):
        visit = self.complete()
        self.login("patient")
        self.assertEqual(self.repo.registrations()[0]["status"], "COMPLETED")
        self.assertEqual(len(self.repo.medical_records()), 1)
        prescription = self.repo.prescriptions()[0]
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        self.login("doctor")
        self.repo.dispense_prescription(prescription["id"])
        self.login("patient")
        self.assertEqual(self.repo.prescriptions()[0]["status"], "COLLECTED")
        self.assertEqual(self.repo.prescriptions()[0]["handed_over_by"], self.doctor["id"])
        payment = self.repo.payments()[0]
        self.assertEqual(payment["amount"], 85000)
        self.repo.submit_payment(payment["id"], "Transfer Bank", "REF-TEST-001")
        self.login("admin")
        self.repo.review_payment(payment["id"], True)
        reopened = ClinicRepository(self.repo.path)
        self.addCleanup(reopened.close)
        reopened.authenticate("patient", "Patient1234")
        self.assertEqual(reopened.payments()[0]["status"], "PAID")
        self.assertEqual(reopened.registrations()[0]["id"], visit["id"])

    def test_only_prescribing_doctor_can_record_handover_once(self):
        self.complete()
        prescription = self.repo.prescriptions()[0]
        self.assertEqual(prescription["patient_name"], self.patient["full_name"])
        self.assertEqual(prescription["doctor_name"], self.doctor["full_name"])
        self.login("otherdoctor")
        self.assertEqual(self.repo.prescriptions(), [])
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        self.login("admin")
        with self.assertRaises(ClinicError):
            self.repo.prescriptions()
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        self.login("doctor")
        self.repo.dispense_prescription(prescription["id"])
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM prescription_handoffs").fetchone()[0], 1)

    def test_completed_import_requires_record_and_payment(self):
        self.complete()
        self.login("admin")
        for table in ("medical_records", "payments"):
            with self.subTest(missing=table):
                source = Path(self.temp.name) / (table + ".db")
                self.repo.backup(source)
                with closing(sqlite3.connect(source)) as damaged:
                    damaged.execute(f"DELETE FROM {table}")
                    damaged.commit()
                empty = self.open_repo("import-" + table + ".db")
                with self.assertRaises(ClinicError):
                    empty.import_flutter(source)
                self.assertFalse(empty.has_users())

    def test_handover_failure_rolls_back_status_and_staff_record(self):
        self.complete()
        prescription = self.repo.prescriptions()[0]
        self.repo.db.execute("CREATE TRIGGER fail_handover BEFORE UPDATE ON prescriptions BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        self.assertEqual(self.repo.prescriptions()[0]["status"], "READY")
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM prescription_handoffs").fetchone()[0], 0)

    def test_legacy_collected_prescription_is_not_falsely_attributed_to_doctor(self):
        self.complete()
        self.login("admin")
        path = Path(self.temp.name) / "legacy.db"
        self.repo.backup(path)
        with closing(sqlite3.connect(path)) as db:
            db.execute("DROP TABLE prescription_handoffs")
            db.execute("PRAGMA user_version=1")
            db.execute("UPDATE prescriptions SET status='COLLECTED'")
            db.commit()
        empty = self.open_repo("import-legacy.db")
        empty.import_flutter(path)
        empty.authenticate("patient", "Patient1234")
        item = empty.prescriptions()[0]
        self.assertEqual(item["status"], "COLLECTED")
        self.assertIsNone(item["handed_over_by"])
        self.assertIn("data lama", item["delivery_status"])
        with closing(ClinicRepository(path)) as migrated:
            migrated.authenticate("patient", "Patient1234")
            self.assertEqual(migrated.prescriptions()[0]["delivery_status"], item["delivery_status"])
            self.assertEqual(migrated.db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_patient_identifier_distinguishes_names_and_follows_visit(self):
        same_name = self.repo.register_patient(self.patient["full_name"], "same-name", "Patient1234")
        self.assertNotEqual(same_name["medical_number"], self.patient["medical_number"])
        self.complete()
        self.assertEqual(self.repo.medical_records()[0]["medical_number"], self.patient["medical_number"])
        self.assertEqual(self.repo.prescriptions()[0]["medical_number"], self.patient["medical_number"])
        self.login("patient")
        self.assertEqual(self.repo.registrations()[0]["medical_number"], self.patient["medical_number"])
        self.assertEqual(self.repo.payments()[0]["medical_number"], self.patient["medical_number"])

    def test_disabled_existing_session_cannot_continue_reading_or_writing(self):
        self.login("patient")
        with closing(ClinicRepository(self.repo.path)) as other_session:
            other_session.authenticate("admin", "Admin1234")
            other_session.set_user_active(self.patient["id"], False)
        for operation in (self.repo.current_user, self.repo.registrations, self.repo.medical_records, self.repo.prescriptions, self.repo.payments):
            with self.subTest(operation=operation.__name__), self.assertRaises(ClinicError):
                operation()
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "10:00", "Keluhan uji")

    def test_role_enforcement_and_read_isolation(self):
        visit = self.visit()
        with self.assertRaises(ClinicError):
            self.repo.create_doctor("Dokter Ilegal", "illegal", "Doctor1234", "Poli Umum")
        with self.assertRaises(ClinicError):
            self.repo.users()
        with self.assertRaises(ClinicError):
            self.repo.confirm_registration(visit["id"])
        self.login("otherpatient")
        self.assertEqual(self.repo.registrations(), [])
        self.login("otherdoctor")
        self.assertEqual(self.repo.registrations(), [])
        with self.assertRaises(ClinicError):
            self.repo.payments()
        with self.assertRaises(ClinicError):
            self.repo.complete_examination(visit["id"], "Diagnosis", "Tindakan", "")

    def test_duplicate_username_case_insensitive_and_password_not_plaintext(self):
        with self.assertRaisesRegex(ClinicError, "Username sudah terdaftar"):
            self.repo.create_doctor("Dokter Duplikat", " DOCTOR ", "Doctor1234", "Poli Umum")
        row = self.repo.db.execute("SELECT * FROM users WHERE id=?", (self.doctor["id"],)).fetchone()
        self.assertNotEqual(row["password_hash"], "Doctor1234")
        self.assertEqual(len(base64.b64decode(row["password_salt"])), 16)
        self.assertTrue(check_password("Doctor1234", row["password_salt"], row["password_hash"]))
        self.assertFalse(check_password("wrong", row["password_salt"], row["password_hash"]))
        self.assertFalse(check_password("Doctor1234", "invalid", "invalid"))
        self.assertNotIn("password_hash", self.repo.users()[0])

    def test_password_and_user_validation(self):
        for password in ("short1", "12345678", "abcdefgh", "a1" * 40):
            with self.subTest(password_length=len(password)), self.assertRaises(ClinicError):
                self.repo.register_patient("Valid Name", "new", password)
        with self.assertRaises(ClinicError):
            self.repo.register_patient("X", "new", "Patient1234")
        with self.assertRaises(ClinicError):
            self.repo.register_patient("Valid Name", "invalid username", "Patient1234")

    def test_username_rules_and_case_insensitive_login(self):
        account = self.repo.register_patient("Pasien Username", " Pasien_01 ", "Patient1234")
        self.assertEqual(account["username"], "pasien_01")
        self.assertNotIn("email", account)
        self.assertEqual(self.repo.authenticate(" PASIEN_01 ", "Patient1234")["id"], account["id"])
        for invalid in ("ab", "a" * 33, "pasien@example.test", "pasien satu", "_pasien", "pasien!"):
            with self.subTest(username=invalid), self.assertRaises(ClinicError):
                self.repo.register_patient("Pasien Baru", invalid, "Patient1234")

    def test_legacy_email_login_and_import_keep_old_password(self):
        # Simulasi identitas dari database lama, bukan pendaftaran akun baru.
        self.repo.db.execute("UPDATE users SET email='admin@legacy.test' WHERE id=?", (self.admin["id"],))
        self.repo.db.commit()
        self.repo.authenticate("ADMIN@LEGACY.TEST", "Admin1234")
        backup = Path(self.temp.name) / "legacy-login.db"
        self.repo.backup(backup)
        imported = self.open_repo("import-login.db")
        imported.import_flutter(backup)
        account = imported.authenticate("admin@legacy.test", "Admin1234")
        self.assertEqual(account["role"], "ADMIN")
        self.assertEqual(account["username"], "admin@legacy.test")

    def test_no_seed_and_admin_setup_once(self):
        empty = self.open_repo("empty.db")
        self.assertFalse(empty.has_users())
        with self.assertRaises(ClinicError):
            empty.register_patient("Patient Name", "user_p", "Patient1234")
        empty.create_initial_admin("First Admin", "user_a", "Admin1234")
        with self.assertRaises(ClinicError):
            empty.create_initial_admin("Second Admin", "user_b", "Admin1234")
        self.assertEqual(empty.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_disable_account_and_prevent_admin_self_disable(self):
        with self.assertRaises(ClinicError):
            self.repo.set_user_active(self.admin["id"], False)
        self.repo.set_user_active(self.doctor["id"], False)
        with self.assertRaises(ClinicError):
            self.login("doctor")
        with self.assertRaises(ClinicError):
            self.repo.users()
        self.login("patient")
        self.assertNotIn(self.doctor["id"], [r["id"] for r in self.repo.active_doctors()])
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "Keluhan uji")

    def test_doctor_and_patient_schedule_conflicts(self):
        self.visit()
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.other_doctor["id"], self.today, "09:00", "Keluhan lainnya")
        self.login("otherpatient")
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "Keluhan lainnya")

    def test_cancellation_frees_slot_but_does_not_reuse_queue(self):
        visit = self.visit()
        self.login("admin")
        self.repo.cancel_registration(visit["id"])
        self.login("patient")
        next_visit = self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "Keluhan lainnya")
        self.assertNotEqual(visit["queue_number"], next_visit["queue_number"])

    def test_completed_visit_still_occupies_doctor_and_patient_slot(self):
        self.complete()
        self.login("patient")
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.other_doctor["id"], self.today, "09:00", "Keluhan lain")
        self.login("otherpatient")
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "Keluhan lain")

    def test_import_rejects_mismatched_clinical_identity(self):
        self.complete()
        self.login("admin")
        backup = Path(self.temp.name) / "mismatched.db"
        self.repo.backup(backup)
        with closing(sqlite3.connect(backup)) as damaged:
            damaged.execute("UPDATE medical_records SET patient_id=?", (self.other_patient["id"],))
            damaged.commit()
        empty = self.open_repo("import.db")
        with self.assertRaises(ClinicError):
            empty.import_flutter(backup)
        self.assertFalse(empty.has_users())

    def test_import_rejects_invalid_doctor_clinic(self):
        backup = Path(self.temp.name) / "invalid-clinic.db"
        self.repo.backup(backup)
        with closing(sqlite3.connect(backup)) as damaged:
            damaged.execute("UPDATE users SET clinic='Poli Tidak Ada' WHERE role='DOCTOR'")
            damaged.commit()
        empty = self.open_repo("import.db")
        with self.assertRaises(ClinicError):
            empty.import_flutter(backup)
        self.assertFalse(empty.has_users())

    def test_import_copies_data_without_untrusted_source_triggers(self):
        backup = Path(self.temp.name) / "with-trigger.db"
        self.repo.backup(backup)
        with closing(sqlite3.connect(backup)) as source:
            source.execute("CREATE TRIGGER unexpected_change AFTER INSERT ON users BEGIN UPDATE users SET is_active=0; END")
            source.commit()
        empty = self.open_repo("import.db")
        empty.import_flutter(backup)
        self.assertIsNone(empty.db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone())
        empty.register_patient("Pasien Impor", "import", "Patient1234")
        empty.authenticate("admin", "Admin1234")
        self.assertEqual(empty.current_user()["role"], "ADMIN")

    def test_import_write_failure_rolls_back_previously_copied_users(self):
        empty = self.open_repo("import.db")
        # Simulasi kegagalan penyimpanan setelah tabel users berhasil disalin.
        empty.db.execute("CREATE TRIGGER fail_registration BEFORE INSERT ON registrations BEGIN SELECT RAISE(ABORT, 'test import rollback'); END")
        self.visit()
        self.login("admin")
        full_backup = Path(self.temp.name) / "with-registration.db"
        self.repo.backup(full_backup)
        with self.assertRaises(ClinicError):
            empty.import_flutter(full_backup)
        self.assertFalse(empty.has_users())

    def test_date_time_and_complaint_validation(self):
        self.login("patient")
        for day in ("2026-02-30", "bad", (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=366)).isoformat()):
            with self.subTest(day=day), self.assertRaises(ClinicError):
                self.repo.register_appointment(self.doctor["id"], day, "09:00", "Keluhan uji")
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "03:00", "Keluhan uji")
        with self.assertRaises(ClinicError):
            self.repo.register_appointment(self.doctor["id"], self.today, "09:00", "x")

    def test_examination_requires_confirmation_and_today(self):
        visit = self.visit()
        self.login("doctor")
        with self.assertRaises(ClinicError):
            self.repo.complete_examination(visit["id"], "Diagnosis uji", "Tindakan uji", "")
        self.login("patient")
        tomorrow = self.repo.register_appointment(self.doctor["id"], (date.today() + timedelta(days=1)).isoformat(), "09:00", "Keluhan uji")
        self.login("admin")
        self.repo.confirm_registration(tomorrow["id"])
        self.login("doctor")
        with self.assertRaises(ClinicError):
            self.repo.complete_examination(tomorrow["id"], "Diagnosis uji", "Tindakan uji", "")

    def test_atomic_examination_rolls_back_all_changes(self):
        visit = self.visit()
        self.login("admin")
        self.repo.confirm_registration(visit["id"])
        self.login("doctor")
        self.repo.db.execute("CREATE TRIGGER fail_payment BEFORE INSERT ON payments BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(ClinicError):
            self.repo.complete_examination(visit["id"], "Diagnosis uji", "Tindakan uji", "Resep uji")
        for table in ("medical_records", "prescriptions", "payments"):
            self.assertEqual(self.repo.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(self.repo.registrations()[0]["status"], "CONFIRMED")

    def test_examination_without_prescription_and_no_duplicate_completion(self):
        visit = self.complete("")
        with self.assertRaises(ClinicError):
            self.repo.complete_examination(visit["id"], "Diagnosis uji", "Tindakan uji", "")
        self.login("patient")
        self.assertEqual(self.repo.prescriptions(), [])
        self.assertEqual(len(self.repo.payments()), 1)

    def test_payment_reject_resubmit_and_verify(self):
        self.complete()
        self.login("patient")
        payment = self.repo.payments()[0]
        self.repo.submit_payment(payment["id"], "QRIS", "REF-001")
        self.login("admin")
        self.repo.review_payment(payment["id"], False)
        self.login("patient")
        self.repo.submit_payment(payment["id"], "Transfer Bank", "REF-002")
        with self.assertRaises(ClinicError):
            self.repo.submit_payment(payment["id"], "QRIS", "REF-003")
        self.login("admin")
        self.repo.review_payment(payment["id"], True)
        with self.assertRaises(ClinicError):
            self.repo.review_payment(payment["id"], False)

    def test_patient_cannot_operate_other_patients_payment_or_prescription(self):
        self.complete()
        self.login("patient")
        prescription = self.repo.prescriptions()[0]
        payment = self.repo.payments()[0]
        self.login("otherpatient")
        self.assertEqual(self.repo.payments(), [])
        self.assertEqual(self.repo.medical_records(), [])
        self.assertEqual(self.repo.prescriptions(), [])
        with self.assertRaises(ClinicError):
            self.repo.dispense_prescription(prescription["id"])
        with self.assertRaises(ClinicError):
            self.repo.submit_payment(payment["id"], "QRIS", "REF-001")

    def test_backup_import_preserves_credentials_and_clinical_rows(self):
        self.complete()
        self.repo.dispense_prescription(self.repo.prescriptions()[0]["id"])
        self.login("admin")
        backup = Path(self.temp.name) / "backup.db"
        self.repo.backup(backup)
        empty = self.open_repo("import.db")
        empty.import_flutter(backup)
        empty.authenticate("patient", "Patient1234")
        self.assertEqual(len(empty.medical_records()), 1)
        self.assertEqual(len(empty.payments()), 1)
        self.assertEqual(empty.prescriptions()[0]["handed_over_by"], self.doctor["id"])
        self.assertGreater(empty.prescriptions()[0]["handed_over_at"], 0)
        with self.assertRaises(ClinicError):
            empty.import_flutter(backup)
        with self.assertRaises(ClinicError):
            self.repo.backup(backup)

    def test_invalid_import_does_not_change_destination(self):
        bad_path = Path(self.temp.name) / "unrelated.db"
        with closing(sqlite3.connect(bad_path)) as bad:
            bad.execute("CREATE TABLE unrelated(id INTEGER)")
            bad.commit()
        empty = self.open_repo("import.db")
        with self.assertRaises(ClinicError):
            empty.import_flutter(bad_path)
        self.assertFalse(empty.has_users())
        with self.assertRaises(ClinicError):
            ClinicRepository(bad_path)


if __name__ == "__main__":
    unittest.main()
