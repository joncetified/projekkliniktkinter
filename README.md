# Klinik Sehat — Python Tkinter

Aplikasi desktop klinik rawat jalan sederhana dengan Python, Tkinter/ttk,
dan SQLite. Role: Admin, Dokter, dan Pasien.

## Menjalankan

Instal Python 3.11 atau lebih baru dengan komponen Tcl/Tk, lalu jalankan:

```powershell
git clone https://github.com/joncetified/projekkliniktkinter.git
cd projekkliniktkinter
python desktop_app/main.py
```

Di Windows, `run-desktop.bat` juga dapat diklik dua kali. Launcher menggunakan
Python lokal `.tools/python` jika tersedia, atau perintah `python` dari PATH.
Tidak ada dependensi pip. Installer dan interpreter Python tidak disertakan.

Untuk VS Code, pasang ekstensi Python, pilih interpreter Python yang terpasang
melalui **Python: Select Interpreter**, lalu jalankan dari terminal. Konfigurasi
debug lokal `.vscode` memakai `.tools/python/python.exe`; sesuaikan path tersebut
jika menggunakan Python dari instalasi lain.

## Akun dan fitur

- Tidak ada akun, password, atau data pasien bawaan. Gunakan **Siapkan Admin Pertama**.
- Login memakai username dan password. Admin membuat akun Dokter; Pasien mendaftar sendiri.
- Pendaftaran kunjungan, konfirmasi Admin, pemeriksaan Dokter, dan rekam medis.
- Resep dan pencatatan penyerahan oleh Dokter, beserta petugas dan waktunya.
- Tagihan pemeriksaan dan verifikasi pembayaran manual oleh Admin.
- Backup SQLite serta impor database Flutter yang kompatibel.

Database dibuat otomatis di `desktop_app/data/clinic.db` dan tidak masuk Git.
Seluruh data disimpan lokal; aplikasi belum memiliki sinkronisasi antarperangkat.
Batas fitur operasional dijelaskan dalam [audit sistem](desktop_app/AUDIT_SISTEM.md).

## Pengujian

```powershell
python -W error::ResourceWarning -m unittest discover -s desktop_app/tests -v
python desktop_app/main.py --smoke-test
```

Pengujian menggunakan database sementara. Tes UI memerlukan desktop dengan Tkinter.
Lihat [panduan lengkap](desktop_app/README.md) untuk alur penggunaan dan impor data.
