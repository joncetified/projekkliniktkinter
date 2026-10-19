# Klinik Sehat — Python Tkinter

Versi desktop Windows dari sistem Klinik Sehat, ditulis dengan Python 3.13,
Tkinter/ttk dan SQLite. Semua fitur menggunakan database persisten. Tidak ada
akun bawaan atau data dummy pada aplikasi.

## Menjalankan

Dari folder utama proyek di terminal VS Code / PowerShell:

```powershell
.\run-desktop.bat
```

Atau jalankan file Python langsung menggunakan interpreter lokal yang sudah disiapkan:

```powershell
.\.tools\python\python.exe .\desktop_app\main.py
```

Double-click `run-desktop.bat` di Windows Explorer juga membuka aplikasi.
Python lokal pada workspace pengembangan berada di `.tools/python` dan tidak
disertakan dalam repository GitHub. Setelah clone, instal Python 3.11+ dengan
Tcl/Tk, lalu gunakan `python desktop_app/main.py`. Tidak perlu Flutter, Android Studio,
emulator, ataupun paket pip untuk menjalankan desktop ini.

Pada komputer lain, instal Python 3.11 atau lebih baru dengan komponen Tcl/Tk,
lalu jalankan `python desktop_app/main.py`. Database default selalu berada di
`desktop_app/data/clinic.db`, terlepas dari lokasi terminal saat menjalankan aplikasi.

## VS Code

Buka folder utama `projekkilinik`. Konfigurasi `.vscode` sudah memilih Python
lokal. Jalankan dari terminal atau pasang ekstensi Python dan Python Debugger
yang direkomendasikan lalu pilih konfigurasi **Klinik Sehat — Python Tkinter**
dan tekan F5.

## Akun dan alur operasional

1. Aplikasi membuka halaman **Masuk**. Pada database desktop kosong, tersedia
   tombol **Siapkan Admin Pertama** atau **Impor Database Flutter / Backup**.
2. Buat Admin sekali, lalu masuk menggunakan username dan kata sandi tersebut.
   Jika database sudah memiliki akun, setup Admin tidak ditampilkan lagi.
3. Admin membuka **Pengguna → Tambah Dokter**, mengisi nama, username unik,
   kata sandi awal, dan poli. Akun Dokter langsung aktif dan bisa login.
4. Pasien mendaftar melalui **Daftar sebagai Pasien** di halaman Masuk.
5. Pasien membuat pendaftaran dengan dokter aktif, tanggal, jam, dan keluhan.
   Bentrok jadwal pasien/dokter ditolak. Poli menentukan nomor antrean dan tarif.
6. Admin mengonfirmasi atau membatalkan pendaftaran.
7. Dokter membuka antreannya dan mengisi diagnosis, tindakan, serta resep
   opsional. Hanya dokter yang ditugaskan dapat memeriksa, pada tanggal kunjungan
   dan setelah dikonfirmasi. Penyimpanan membuat rekam medis, resep bila diisi,
   dan tagihan dalam satu transaksi. Menu **Resep** pada akun Dokter menampilkan
   kembali resep yang ia tulis, beserta pasien dan status pengambilannya.
8. Pasien membaca rekam medis dan resep. Dokter pembuat resep membuka **Resep →
   Catat Penyerahan Obat** setelah benar-benar menyerahkan seluruh obat.
   Sistem mencatat dokter dan waktu penyerahan. Pasien tidak dapat mengubah statusnya.
9. Pasien memasukkan metode dan referensi pembayaran yang telah dilakukan.
   Admin memverifikasi menjadi lunas atau menolak agar pasien dapat mengirim ulang.
   Aplikasi ini mencatat pembayaran, tidak memproses transfer dana.

Role dibaca dari akun tersimpan, tidak dipilih saat login. Seluruh operasi
memeriksa role dan status aktif kembali di repository. Pasien dan Dokter hanya
membaca data klinis milik mereka; Admin mengelola pengguna, antrean, dan pembayaran.
Admin tidak dapat menonaktifkan dirinya sendiri.
Username baru terdiri dari 3–32 karakter: huruf, angka, titik, garis bawah, atau
tanda hubung, dengan karakter awal huruf/angka. Huruf besar/kecil dianggap sama.
Kata sandi dibuat sendiri, terdiri dari 8–72 karakter dengan huruf dan angka.
Tidak ada username atau kata sandi bawaan. Untuk akun lama yang diimpor, identitas
login lama (termasuk jika berupa email) dan kata sandinya tetap berlaku. Kolom
penyimpanan lama bernama `email` dipertahankan untuk kompatibilitas database;
form dan aturan pendaftaran baru menggunakan username.
Pasien memiliki nomor rekam medis lokal `RM-xxxxxx` yang berasal dari ID akun tetap.
Nomor ini tampil pada rincian kunjungan, rekam medis, resep, dan tagihan.
Status **Pemeriksaan selesai** tidak berarti tagihan lunas atau obat telah diserahkan.

Hasil perbandingan dengan referensi OpenMRS dan Bahmni, beserta batas fitur aplikasi,
tersedia di [AUDIT_SISTEM.md](AUDIT_SISTEM.md).

## Data Flutter dan backup

Database desktop terpisah dari penyimpanan Android. Akun lama **tidak otomatis
muncul** sebelum database Flutter diimpor. Impor menerima `clinic_flutter.db`
atau backup SQLite desktop, memeriksa struktur dan relasi, serta mempertahankan
ID, email, hash kata sandi, role, pendaftaran, rekam medis, resep, dan tagihan.
Impor menyalin data ke skema desktop yang terkontrol, bukan membawa trigger dari
file sumber. Identitas pasien/dokter dan hubungan data klinis diperiksa sebelum
disimpan; kegagalan impor membatalkan seluruh perubahan.
Database desktop diperbarui secara transaksional ke versi 2 untuk mencatat penyerahan
obat. Status pengambilan dari versi lama dipertahankan sebagai **Tercatat diambil
(data lama)** jika belum memiliki catatan petugas; identitas petugas tidak dikarang.
Backup desktop versi 2 menyertakan catatan penyerahan. Impor Flutter versi 1 tetap
didukung; backup desktop versi 2 bukan untuk dibuka oleh aplikasi Flutter lama.
Algoritma PBKDF2-HMAC-SHA256, 210.000 iterasi, salt Base64 dan hash 32 byte
kompatibel dengan versi Flutter sehingga kata sandi tidak perlu direset.

Impor hanya tersedia ketika desktop belum memiliki akun. Pilih file database
melalui tombol impor pada halaman Masuk, atau jalankan:

```powershell
.\.tools\python\python.exe .\desktop_app\main.py --import-db "D:\backup\clinic_flutter.db"
```

Tutup aplikasi sumber sebelum menyalin file SQLite agar semua transaksi tersimpan.
Database Kotlin/Room `clinic.db` tidak memiliki format yang sama dan tidak didukung
oleh jalur impor Flutter ini. File database Android berada di penyimpanan aplikasi
perangkat/emulator; file tersebut tidak disertakan dalam source code.

Admin dapat membuat backup melalui tombol **Backup Database** di Beranda.
File backup yang sudah ada tidak ditimpa. Simpan file backup di lokasi yang aksesnya
terbatas karena berisi data klinik. SQLite lokal ini tidak dienkripsi dan tidak
menyinkronkan data antarperangkat. Sesi login hanya berada di memori.

Gunakan database alternatif jika diperlukan:

```powershell
.\.tools\python\python.exe .\desktop_app\main.py --database "D:\klinik\clinic.db"
```

## Pengujian

```powershell
.\.tools\python\python.exe -m unittest discover -s desktop_app\tests -v
.\.tools\python\python.exe -m compileall -q desktop_app
```

Pengujian repository memakai SQLite sementara dan mencakup otorisasi, validasi,
bentrok jadwal, transaksi rollback, resep, pembayaran, persistensi, backup, serta
impor. Test UI membuka Tkinter dengan database sementara dan mengoperasikan form
serta tombol asli, termasuk kegagalan tambah dokter dan alur sampai pembayaran lunas.
Kasus regresi meliputi slot kunjungan selesai yang tidak boleh dipesan ulang,
impor dengan identitas klinis tidak cocok, pemulihan setelah error callback,
serta form layar kecil yang bisa digulir dan diakses melalui keyboard.
Pengujian penyimpanan juga memeriksa pembukaan beberapa instance bersamaan,
pembuatan tepat satu Admin pertama, serta pemulihan dari kegagalan pembuatan skema.
Kunjungan selesai wajib memiliki rekam medis dan tagihan. Akun yang dinonaktifkan
kehilangan akses pada operasi berikutnya, termasuk bila sebelumnya sudah masuk.
Test tidak menulis data dummy ke database aplikasi.

Jika operasi gagal, pesan ditampilkan pada form. Error tak terduga dicatat di
`desktop_app/data/desktop.log` tanpa mencatat kata sandi. Pemrosesan database/hash
berjalan pada worker; widget hanya diperbarui di thread Tkinter.

## Struktur

- `main.py`: entrypoint, opsi database, logging.
- `repository.py`: skema SQLite, autentikasi dan seluruh aturan bisnis.
- `ui.py`: halaman Masuk, Beranda, pengguna, kunjungan, rekam medis, resep, pembayaran.
- `tests/`: pengujian repository dan antarmuka.
- `data/`: dibuat otomatis saat aplikasi dijalankan; dikecualikan dari Git.
