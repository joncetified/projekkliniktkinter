"""Keutuhan database pada kegagalan startup dan penggunaan beberapa instance."""

import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repository
from repository import ClinicError, ClinicRepository


class StorageTests(unittest.TestCase):
    def test_failed_initialization_is_atomic_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clinic.db"
            with patch.object(repository, "SCHEMA", repository.SCHEMA + "INVALID SQL;"):
                with self.assertRaises(sqlite3.DatabaseError):
                    ClinicRepository(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
            with closing(ClinicRepository(path)) as repo:
                self.assertFalse(repo.has_users())

    def test_parallel_startup_and_first_admin_create_exactly_one_admin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clinic.db"
            barrier = threading.Barrier(6)

            def initialize(_index):
                barrier.wait(timeout=10)
                with closing(ClinicRepository(path)) as repo:
                    return repo.has_users()

            with ThreadPoolExecutor(max_workers=6) as executor:
                self.assertEqual(list(executor.map(initialize, range(6))), [False] * 6)

            barrier = threading.Barrier(2)

            def create_admin(index):
                with closing(ClinicRepository(path)) as repo:
                    barrier.wait(timeout=10)
                    try:
                        repo.create_initial_admin("Admin Klinik", f"admin{index}", "Admin1234")
                        return True
                    except ClinicError:
                        return False

            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sorted(executor.map(create_admin, range(2))), [False, True])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
