"""Jalankan: python desktop_app/main.py. Hanya memerlukan library bawaan Python."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import Tk, messagebox

from repository import ClinicRepository
from ui import ClinicApp


def main():
    parser = argparse.ArgumentParser(description="Klinik Sehat — Python Tkinter")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parent / "data" / "clinic.db")
    parser.add_argument("--import-db", type=Path, help="Impor database Flutter/backup ke desktop kosong")
    parser.add_argument("--smoke-test", action="store_true", help="Periksa startup Tkinter lalu tutup")
    args = parser.parse_args()
    args.database = args.database.resolve()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.database.parent / "desktop.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    repository = None
    try:
        repository = ClinicRepository(args.database)
        if args.import_db:
            repository.import_flutter(args.import_db)
        app = ClinicApp(repository)
    except Exception:
        if repository is not None:
            repository.close()
        logging.exception("Startup aplikasi gagal")
        root = Tk()
        root.withdraw()
        messagebox.showerror("Klinik Sehat", "Aplikasi tidak dapat membuka database. Periksa file dan data/desktop.log.", parent=root)
        root.destroy()
        raise
    if args.smoke_test:
        app.withdraw()
        app.update()
        app.close()
        print("Tkinter startup OK")
    else:
        app.mainloop()


if __name__ == "__main__":
    main()
