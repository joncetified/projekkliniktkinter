"""Aturan bisnis klinik desktop. SQLite dan PBKDF2 kompatibel dengan Flutter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from datetime import date, timedelta
from pathlib import Path

CLINICS = {"Poli Umum": ("A", 85000), "Poli Gigi": ("G", 150000), "Poli Anak": ("K", 100000)}
TIMES = ("08:00", "09:00", "10:00", "11:00", "13:00", "14:00", "15:00")
METHODS = ("Transfer Bank", "QRIS")
LABELS = {
    "ADMIN": "Admin", "DOCTOR": "Dokter", "PATIENT": "Pasien",
    "WAITING": "Menunggu", "CONFIRMED": "Dikonfirmasi", "COMPLETED": "Pemeriksaan selesai",
    "CANCELLED": "Dibatalkan", "READY": "Menunggu penyerahan", "COLLECTED": "Sudah diserahkan",
    "UNPAID": "Belum dibayar", "AWAITING_VERIFICATION": "Menunggu verifikasi",
    "REJECTED": "Ditolak", "PAID": "Lunas",
}
REQUIRED_COLUMNS = {
    "users": {"id", "full_name", "email", "password_hash", "password_salt", "role", "clinic", "is_active", "created_at"},
    "registrations": {"id", "patient_id", "doctor_id", "clinic", "visit_date", "visit_time", "complaint", "status", "queue_number", "created_at"},
    "medical_records": {"id", "registration_id", "patient_id", "doctor_id", "visit_date", "complaint", "diagnosis", "treatment", "created_at"},
    "prescriptions": {"id", "registration_id", "patient_id", "doctor_id", "visit_date", "medicines", "status", "created_at"},
    "payments": {"id", "registration_id", "patient_id", "description", "amount", "payment_method", "payment_reference", "status", "created_at"},
}
SCHEMA = """
CREATE TABLE users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
 email TEXT NOT NULL COLLATE NOCASE UNIQUE, password_hash TEXT NOT NULL,
 password_salt TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('PATIENT','DOCTOR','ADMIN')),
 clinic TEXT, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), created_at INTEGER NOT NULL
);
CREATE TABLE registrations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 clinic TEXT NOT NULL, visit_date TEXT NOT NULL, visit_time TEXT NOT NULL,
 complaint TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('WAITING','CONFIRMED','COMPLETED','CANCELLED')),
 queue_number TEXT NOT NULL, created_at INTEGER NOT NULL, UNIQUE(visit_date, queue_number)
);
CREATE INDEX registrations_patient_idx ON registrations(patient_id);
CREATE INDEX registrations_doctor_idx ON registrations(doctor_id);
CREATE TABLE medical_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(id) ON DELETE RESTRICT,
 patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 visit_date TEXT NOT NULL, complaint TEXT NOT NULL, diagnosis TEXT NOT NULL,
 treatment TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE prescriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 registration_id INTEGER NOT NULL REFERENCES registrations(id) ON DELETE RESTRICT,
 patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 doctor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 visit_date TEXT NOT NULL, medicines TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('READY','COLLECTED')), created_at INTEGER NOT NULL
);
CREATE TABLE payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 registration_id INTEGER NOT NULL REFERENCES registrations(id) ON DELETE RESTRICT,
 patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 description TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
 payment_method TEXT, payment_reference TEXT,
 status TEXT NOT NULL CHECK(status IN ('UNPAID','AWAITING_VERIFICATION','REJECTED','PAID')),
 created_at INTEGER NOT NULL
);
PRAGMA user_version = 1;
"""
HANDOFF_COLUMNS = {"prescription_id", "actor_id", "created_at"}
HANDOFF_SCHEMA = """CREATE TABLE IF NOT EXISTS prescription_handoffs (
 prescription_id INTEGER PRIMARY KEY REFERENCES prescriptions(id) ON DELETE RESTRICT,
 actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 created_at INTEGER NOT NULL CHECK(created_at > 0)
)"""


class ClinicError(ValueError):
    """Kesalahan yang aman ditampilkan kepada pengguna."""


def password_hash(password: str, salt: bytes) -> str:
    return base64.b64encode(hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000, 32)).decode("ascii")


def check_password(password: str, salt: str, expected: str) -> bool:
    try:
        salt_bytes = base64.b64decode(salt, validate=True)
        actual = base64.b64decode(password_hash(password, salt_bytes), validate=True)
        return hmac.compare_digest(actual, base64.b64decode(expected, validate=True))
    except (ValueError, TypeError):
        return False


def validate_database(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0] > 2:
        raise ClinicError("Versi database lebih baru dari aplikasi ini.")
    for table, columns in REQUIRED_COLUMNS.items():
        kind = db.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if not kind or kind[0] != "table":
            raise ClinicError("File bukan database Klinik Sehat Flutter yang didukung.")
        found = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if not columns <= found:
            raise ClinicError("File bukan database Klinik Sehat Flutter yang didukung.")
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
        raise ClinicError("Database rusak atau memiliki relasi yang tidak valid.")
    invalid_queries = [
        ("SELECT 1 FROM users WHERE role IS NULL OR role NOT IN ('ADMIN','DOCTOR','PATIENT') OR is_active IS NULL OR is_active NOT IN (0,1) OR (role='DOCTOR' AND (clinic IS NULL OR clinic NOT IN (?,?,?))) LIMIT 1", tuple(CLINICS)),
        ("SELECT 1 FROM users GROUP BY email COLLATE NOCASE HAVING COUNT(*)>1 LIMIT 1", ()),
        ("SELECT 1 FROM registrations r LEFT JOIN users p ON p.id=r.patient_id LEFT JOIN users d ON d.id=r.doctor_id WHERE p.role IS NOT 'PATIENT' OR d.role IS NOT 'DOCTOR' OR r.clinic IS NOT d.clinic OR r.status IS NULL OR r.status NOT IN ('WAITING','CONFIRMED','COMPLETED','CANCELLED') LIMIT 1", ()),
        ("SELECT 1 FROM prescriptions WHERE status IS NULL OR status NOT IN ('READY','COLLECTED') LIMIT 1", ()),
        ("SELECT 1 FROM payments WHERE amount IS NULL OR amount<=0 OR status IS NULL OR status NOT IN ('UNPAID','AWAITING_VERIFICATION','REJECTED','PAID') LIMIT 1", ()),
        ("SELECT 1 FROM registrations r WHERE r.status='COMPLETED' AND (NOT EXISTS (SELECT 1 FROM medical_records m WHERE m.registration_id=r.id) OR NOT EXISTS (SELECT 1 FROM payments p WHERE p.registration_id=r.id)) LIMIT 1", ()),
    ]
    for table in ("medical_records", "prescriptions", "payments"):
        identity = "c.patient_id IS NOT r.patient_id"
        if table != "payments":
            identity += " OR c.doctor_id IS NOT r.doctor_id OR c.visit_date IS NOT r.visit_date"
        invalid_queries.append((f"SELECT 1 FROM {table} c LEFT JOIN registrations r ON r.id=c.registration_id WHERE r.id IS NULL OR r.status IS NOT 'COMPLETED' OR {identity} LIMIT 1", ()))
        invalid_queries.append((f"SELECT 1 FROM {table} GROUP BY registration_id HAVING COUNT(*)>1 LIMIT 1", ()))
    if any(db.execute(query, args).fetchone() for query, args in invalid_queries):
        raise ClinicError("Database memiliki role, poli, status, atau hubungan data klinis yang tidak valid.")
    handoffs = db.execute("SELECT type FROM sqlite_master WHERE name='prescription_handoffs'").fetchone()
    if not handoffs and db.execute("PRAGMA user_version").fetchone()[0] == 2:
        raise ClinicError("Catatan penyerahan obat tidak ditemukan pada database versi 2.")
    if handoffs:
        columns = {row[1] for row in db.execute("PRAGMA table_info(prescription_handoffs)")}
        if handoffs[0] != "table" or not HANDOFF_COLUMNS <= columns:
            raise ClinicError("Struktur catatan penyerahan obat tidak valid.")
        if db.execute("SELECT 1 FROM prescription_handoffs h LEFT JOIN prescriptions p ON p.id=h.prescription_id LEFT JOIN users u ON u.id=h.actor_id WHERE p.id IS NULL OR p.status IS NOT 'COLLECTED' OR u.role IS NOT 'DOCTOR' OR h.actor_id IS NOT p.doctor_id OR h.created_at IS NULL OR h.created_at<=0 LIMIT 1").fetchone():
            raise ClinicError("Petugas atau status penyerahan obat tidak valid.")


class ClinicRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.session_id: int | None = None
        self.db = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys = ON")
            # Kunci sebelum memeriksa tabel: dua aplikasi boleh mulai bersamaan.
            # DDL ikut transaksi sehingga kegagalan tidak meninggalkan skema separuh.
            with self.transaction():
                tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                if not tables:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                validate_database(self.db)
                self.db.execute(HANDOFF_SCHEMA)
                self.db.execute("PRAGMA user_version = 2")
        except Exception:
            self.db.close()
            raise

    def close(self):
        with self.lock:
            self.session_id = None
            self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except sqlite3.IntegrityError as error:
                self.db.rollback()
                raise ClinicError("Data berbenturan dengan data tersimpan. Muat ulang dan periksa isian.") from error
            except Exception:
                self.db.rollback()
                raise

    def _rows(self, sql, args=()):
        rows = [dict(row) for row in self.db.execute(sql, args).fetchall()]
        for row in rows:
            if "patient_id" in row:
                row["medical_number"] = f"RM-{row['patient_id']:06d}"
        return rows

    def _get(self, table, record_id):
        row = self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise ClinicError("Data tidak ditemukan. Muat ulang halaman.")
        return dict(row)

    def _actor(self, *roles):
        if self.session_id is None:
            raise ClinicError("Silakan masuk terlebih dahulu.")
        actor = self._get("users", self.session_id)
        if not actor["is_active"]:
            raise ClinicError("Akun dinonaktifkan. Hubungi admin.")
        if roles and actor["role"] not in roles:
            raise ClinicError("Akses ditolak untuk role akun Anda.")
        return actor

    @staticmethod
    def public_user(user):
        result = {key: value for key, value in user.items() if key not in ("password_hash", "password_salt", "email")}
        # Kolom lama dipertahankan agar backup Flutter tetap bisa diimpor.
        result["username"] = user["email"]
        if user["role"] == "PATIENT":
            result["medical_number"] = f"RM-{user['id']:06d}"
        return result

    def has_users(self):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    def current_user(self):
        with self.lock:
            return self.public_user(self._actor())

    def authenticate(self, username, password):
        with self.lock:
            self.session_id = None
            row = self.db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (username.strip().lower(),)).fetchone()
            if row is None or not row["is_active"] or not check_password(password, row["password_salt"], row["password_hash"]):
                raise ClinicError("Username atau kata sandi tidak benar, atau akun tidak aktif.")
            self.session_id = row["id"]
            return self.public_user(dict(row))

    def logout(self):
        with self.lock:
            self.session_id = None

    def _create_user(self, name, username, password, role, clinic=None):
        name, username = name.strip(), username.strip().lower()
        if not 3 <= len(name) <= 80:
            raise ClinicError("Nama harus terdiri dari 3–80 karakter.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", username):
            raise ClinicError("Username harus 3–32 karakter, diawali huruf/angka; gunakan huruf, angka, titik, garis bawah, atau tanda hubung.")
        if not 8 <= len(password) <= 72 or not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
            raise ClinicError("Kata sandi harus 8–72 karakter, mengandung huruf dan angka.")
        if self.db.execute("SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (username,)).fetchone():
            raise ClinicError("Username sudah terdaftar. Gunakan username lain atau masuk dengan akun lama.")
        salt = secrets.token_bytes(16)
        cursor = self.db.execute(
            "INSERT INTO users(full_name,email,password_hash,password_salt,role,clinic,is_active,created_at) VALUES(?,?,?,?,?,?,1,?)",
            (name, username, password_hash(password, salt), base64.b64encode(salt).decode("ascii"), role, clinic, int(time.time() * 1000)),
        )
        return self.public_user(self._get("users", cursor.lastrowid))

    def create_initial_admin(self, name, username, password):
        with self.transaction():
            if self.has_users():
                raise ClinicError("Admin pertama sudah tersedia. Silakan masuk dengan akun lama.")
            return self._create_user(name, username, password, "ADMIN")

    def register_patient(self, name, username, password):
        with self.transaction():
            if not self.has_users():
                raise ClinicError("Siapkan admin klinik terlebih dahulu.")
            return self._create_user(name, username, password, "PATIENT")

    def create_doctor(self, name, username, password, clinic):
        with self.transaction():
            self._actor("ADMIN")
            if clinic not in CLINICS:
                raise ClinicError("Poli dokter tidak valid.")
            return self._create_user(name, username, password, "DOCTOR", clinic)

    def users(self):
        with self.lock:
            self._actor("ADMIN")
            return [self.public_user(row) for row in self._rows("SELECT * FROM users ORDER BY created_at, id")]

    def set_user_active(self, user_id, active):
        with self.transaction():
            actor = self._actor("ADMIN")
            if actor["id"] == user_id:
                raise ClinicError("Admin tidak dapat menonaktifkan akunnya sendiri.")
            self._get("users", user_id)
            self.db.execute("UPDATE users SET is_active=? WHERE id=?", (int(bool(active)), user_id))

    def active_doctors(self):
        with self.lock:
            self._actor("PATIENT", "ADMIN")
            return self._rows("SELECT id,full_name,clinic,email AS username FROM users WHERE role='DOCTOR' AND is_active=1 ORDER BY full_name")

    def register_appointment(self, doctor_id, visit_date, visit_time, complaint):
        with self.transaction():
            actor = self._actor("PATIENT")
            doctor = self._get("users", doctor_id)
            if doctor["role"] != "DOCTOR" or not doctor["is_active"] or doctor["clinic"] not in CLINICS:
                raise ClinicError("Dokter tidak aktif atau poli tidak valid.")
            try:
                parsed = date.fromisoformat(visit_date)
            except ValueError as error:
                raise ClinicError("Tanggal harus YYYY-MM-DD, misalnya 2026-10-11.") from error
            if parsed.isoformat() != visit_date or not date.today() <= parsed <= date.today() + timedelta(days=365):
                raise ClinicError("Pilih tanggal mulai hari ini sampai 365 hari ke depan.")
            if visit_time not in TIMES:
                raise ClinicError("Jam kunjungan tidak tersedia.")
            complaint = complaint.strip()
            if not 3 <= len(complaint) <= 250:
                raise ClinicError("Keluhan harus terdiri dari 3–250 karakter.")
            conflicts = self.db.execute(
                "SELECT patient_id,doctor_id FROM registrations WHERE visit_date=? AND visit_time=? AND status IN ('WAITING','CONFIRMED','COMPLETED') AND (patient_id=? OR doctor_id=?)",
                (visit_date, visit_time, actor["id"], doctor_id),
            ).fetchall()
            if conflicts:
                raise ClinicError("Jadwal pasien atau dokter pada tanggal dan jam tersebut sudah terisi.")
            prefix = CLINICS[doctor["clinic"]][0]
            queues = self._rows("SELECT queue_number FROM registrations WHERE visit_date=? AND queue_number LIKE ?", (visit_date, prefix + "-%"))
            numbers = [int(row["queue_number"].split("-")[-1]) for row in queues if row["queue_number"].split("-")[-1].isdigit()]
            queue = f"{prefix}-{max(numbers, default=0) + 1:03d}"
            cursor = self.db.execute(
                "INSERT INTO registrations(patient_id,doctor_id,clinic,visit_date,visit_time,complaint,status,queue_number,created_at) VALUES(?,?,?,?,?,?,'WAITING',?,?)",
                (actor["id"], doctor_id, doctor["clinic"], visit_date, visit_time, complaint, queue, int(time.time() * 1000)),
            )
            return self._get("registrations", cursor.lastrowid)

    def registrations(self):
        with self.lock:
            actor = self._actor()
            where, args = self._scope(actor, "r")
            return self._rows("SELECT r.*,p.full_name AS patient_name,d.full_name AS doctor_name FROM registrations r JOIN users p ON p.id=r.patient_id JOIN users d ON d.id=r.doctor_id" + where + " ORDER BY r.visit_date DESC,r.visit_time,r.id DESC", args)

    @staticmethod
    def _scope(actor, alias):
        if actor["role"] == "ADMIN":
            return "", ()
        column = "doctor_id" if actor["role"] == "DOCTOR" else "patient_id"
        return f" WHERE {alias}.{column}=?", (actor["id"],)

    def confirm_registration(self, registration_id):
        with self.transaction():
            self._actor("ADMIN")
            record = self._get("registrations", registration_id)
            if record["status"] != "WAITING" or record["visit_date"] < date.today().isoformat():
                raise ClinicError("Hanya pendaftaran menunggu yang belum lewat dapat dikonfirmasi.")
            doctor = self._get("users", record["doctor_id"])
            patient = self._get("users", record["patient_id"])
            if not doctor["is_active"] or not patient["is_active"]:
                raise ClinicError("Akun dokter atau pasien tidak aktif.")
            self.db.execute("UPDATE registrations SET status='CONFIRMED' WHERE id=?", (registration_id,))

    def cancel_registration(self, registration_id):
        with self.transaction():
            self._actor("ADMIN")
            if self._get("registrations", registration_id)["status"] not in ("WAITING", "CONFIRMED"):
                raise ClinicError("Pendaftaran selesai atau batal tidak dapat dibatalkan.")
            self.db.execute("UPDATE registrations SET status='CANCELLED' WHERE id=?", (registration_id,))

    def complete_examination(self, registration_id, diagnosis, treatment, medicines):
        with self.transaction():
            actor = self._actor("DOCTOR")
            record = self._get("registrations", registration_id)
            if record["doctor_id"] != actor["id"]:
                raise ClinicError("Dokter tidak ditugaskan untuk pasien ini.")
            if record["status"] != "CONFIRMED" or record["visit_date"] != date.today().isoformat():
                raise ClinicError("Pemeriksaan harus dikonfirmasi dan dilakukan pada tanggal kunjungan.")
            diagnosis, treatment, medicines = diagnosis.strip(), treatment.strip(), medicines.strip()
            if not 3 <= len(diagnosis) <= 200 or not 3 <= len(treatment) <= 300:
                raise ClinicError("Diagnosis harus 3–200 karakter dan tindakan 3–300 karakter.")
            if len(medicines) > 500:
                raise ClinicError("Resep maksimal 500 karakter.")
            now = int(time.time() * 1000)
            self.db.execute("INSERT INTO medical_records(registration_id,patient_id,doctor_id,visit_date,complaint,diagnosis,treatment,created_at) VALUES(?,?,?,?,?,?,?,?)", (registration_id, record["patient_id"], actor["id"], record["visit_date"], record["complaint"], diagnosis, treatment, now))
            if medicines:
                self.db.execute("INSERT INTO prescriptions(registration_id,patient_id,doctor_id,visit_date,medicines,status,created_at) VALUES(?,?,?,?,?,'READY',?)", (registration_id, record["patient_id"], actor["id"], record["visit_date"], medicines, now))
            self.db.execute("INSERT INTO payments(registration_id,patient_id,description,amount,status,created_at) VALUES(?,?,?,?,'UNPAID',?)", (registration_id, record["patient_id"], "Pemeriksaan " + record["clinic"], CLINICS[record["clinic"]][1], now))
            self.db.execute("UPDATE registrations SET status='COMPLETED' WHERE id=?", (registration_id,))

    def medical_records(self):
        with self.lock:
            actor = self._actor("PATIENT", "DOCTOR")
            where, args = self._scope(actor, "m")
            return self._rows("SELECT m.*,p.full_name AS patient_name,d.full_name AS doctor_name FROM medical_records m JOIN users p ON p.id=m.patient_id JOIN users d ON d.id=m.doctor_id" + where + " ORDER BY m.visit_date DESC,m.id DESC", args)

    def prescriptions(self):
        with self.lock:
            actor = self._actor("PATIENT", "DOCTOR")
            where, args = self._scope(actor, "s")
            rows = self._rows("SELECT s.*,p.full_name AS patient_name,d.full_name AS doctor_name,h.actor_id AS handed_over_by,h.created_at AS handed_over_at,u.full_name AS handover_name FROM prescriptions s JOIN users p ON p.id=s.patient_id JOIN users d ON d.id=s.doctor_id LEFT JOIN prescription_handoffs h ON h.prescription_id=s.id LEFT JOIN users u ON u.id=h.actor_id" + where + " ORDER BY s.visit_date DESC,s.id DESC", args)
            for row in rows:
                row["delivery_status"] = "Tercatat diambil (data lama)" if row["status"] == "COLLECTED" and row["handed_over_by"] is None else LABELS[row["status"]]
            return rows

    def dispense_prescription(self, prescription_id):
        with self.transaction():
            actor = self._actor("DOCTOR")
            item = self._get("prescriptions", prescription_id)
            if item["doctor_id"] != actor["id"] or item["status"] != "READY":
                raise ClinicError("Resep bukan tanggung jawab dokter ini atau sudah tercatat diserahkan.")
            self.db.execute("INSERT INTO prescription_handoffs(prescription_id,actor_id,created_at) VALUES(?,?,?)", (prescription_id, actor["id"], int(time.time() * 1000)))
            self.db.execute("UPDATE prescriptions SET status='COLLECTED' WHERE id=?", (prescription_id,))

    def payments(self):
        with self.lock:
            actor = self._actor("ADMIN", "PATIENT")
            where = " WHERE t.patient_id=?" if actor["role"] == "PATIENT" else ""
            return self._rows("SELECT t.*,p.full_name AS patient_name FROM payments t JOIN users p ON p.id=t.patient_id" + where + " ORDER BY t.id DESC", (actor["id"],) if where else ())

    def submit_payment(self, payment_id, method, reference):
        with self.transaction():
            actor = self._actor("PATIENT")
            payment = self._get("payments", payment_id)
            if payment["patient_id"] != actor["id"] or payment["status"] not in ("UNPAID", "REJECTED"):
                raise ClinicError("Tagihan bukan milik akun ini atau sudah diproses.")
            if method not in METHODS or not 4 <= len(reference.strip()) <= 40:
                raise ClinicError("Pilih metode yang valid dan isi referensi transaksi 4–40 karakter.")
            self.db.execute("UPDATE payments SET payment_method=?,payment_reference=?,status='AWAITING_VERIFICATION' WHERE id=?", (method, reference.strip(), payment_id))

    def review_payment(self, payment_id, accepted):
        with self.transaction():
            self._actor("ADMIN")
            if self._get("payments", payment_id)["status"] != "AWAITING_VERIFICATION":
                raise ClinicError("Pembayaran tidak sedang menunggu verifikasi.")
            self.db.execute("UPDATE payments SET status=? WHERE id=?", ("PAID" if accepted else "REJECTED", payment_id))

    def backup(self, destination):
        with self.lock:
            self._actor("ADMIN")
            target = Path(destination).resolve()
            if target.exists():
                raise ClinicError("Nama file backup sudah ada. Pilih nama baru.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(target)) as copy:
                self.db.backup(copy)
                validate_database(copy)

    def import_flutter(self, source):
        with self.lock:
            if self.has_users() or self.session_id is not None:
                raise ClinicError("Impor hanya tersedia sebelum database desktop memiliki akun.")
            path = Path(source).resolve()
            if path == self.path or not path.is_file():
                raise ClinicError("Pilih file database Flutter yang berbeda dan tersedia.")
            try:
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as original:
                    # Validasi dan impor harus membaca snapshot sumber yang sama.
                    original.execute("BEGIN")
                    validate_database(original)
                    if not original.execute("SELECT 1 FROM users WHERE role='ADMIN' AND is_active=1 LIMIT 1").fetchone():
                        raise ClinicError("Database sumber tidak memiliki Admin aktif.")
                    # Impor data saja: jangan membawa trigger/skema asing ke aplikasi.
                    # Transaksi juga mencegah impor menimpa akun yang baru dibuat
                    # oleh instance desktop lain setelah pemeriksaan awal.
                    with self.transaction():
                        if self.has_users():
                            raise ClinicError("Database desktop sudah memiliki akun. Impor dibatalkan.")
                        for table, required in REQUIRED_COLUMNS.items():
                            columns = ",".join(sorted(required))
                            placeholders = ",".join("?" for _ in required)
                            rows = original.execute(f"SELECT {columns} FROM {table}")
                            while batch := rows.fetchmany(500):
                                self.db.executemany(f"INSERT INTO {table}({columns}) VALUES({placeholders})", batch)
                        if original.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prescription_handoffs'").fetchone():
                            rows = original.execute("SELECT prescription_id,actor_id,created_at FROM prescription_handoffs")
                            while batch := rows.fetchmany(500):
                                self.db.executemany("INSERT INTO prescription_handoffs(prescription_id,actor_id,created_at) VALUES(?,?,?)", batch)
                        validate_database(self.db)
            except sqlite3.DatabaseError as error:
                raise ClinicError("Database tidak dapat diimpor. Gunakan file SQLite Flutter yang valid.") from error
