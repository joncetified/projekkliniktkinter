# Audit alur sistem klinik — 17 Oktober 2026

Aplikasi ini termasuk sistem klinik rawat jalan sederhana dengan tiga role:
Pasien, Dokter, dan Admin. Alur inti pendaftaran, pemeriksaan, rekam medis,
resep, dan pembayaran tersedia. Referensi produk di bawah digunakan untuk
menilai alur; hasil audit ini bukan pernyataan bahwa aplikasi sudah memiliki
seluruh kemampuan sistem rumah sakit atau telah memenuhi seluruh persyaratan
operasional sebuah klinik tertentu.

## Perbandingan dan perubahan

| Bagian | Temuan pada aplikasi | Hasil pemeriksaan/perbaikan |
| --- | --- | --- |
| Kunjungan | Pemeriksaan, resep, dan tagihan terkait satu pendaftaran | Hubungan ID dipertahankan dan penyimpanan pemeriksaan dilakukan dalam satu transaksi. Ini sesuai pola kunjungan yang mengelompokkan layanan dalam [OpenMRS](https://guide.openmrs.org/getting-started/openmrs-information-model/). |
| Identitas pasien | Nama bisa sama; ID pasien belum jelas pada tampilan | Nomor rekam medis lokal `RM-xxxxxx` ditampilkan pada akun dan rincian layanan, berdasarkan ID pasien yang tetap. OpenMRS menggunakan identitas pasien tersendiri saat [registrasi](https://guide.openmrs.org/collecting-data/registering-patients/). Nomor ini unik dalam database klinik, bukan identitas nasional. |
| Penyerahan obat | Pasien bisa mengubah sendiri status menjadi diambil; resep baru langsung disebut siap diambil | Dikoreksi: resep baru berstatus menunggu penyerahan. Dokter pembuat resep mencatat penyerahan, disertai ID petugas dan waktu. Pasien hanya membaca status. [Bahmni](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/48889901/Dispensing+Drugs) menempatkan pencatatan ini pada petugas yang menyerahkan, termasuk dokter pada alur tertentu. |
| Riwayat obat lama | Status diambil belum memiliki bukti siapa yang mencatat/menyerahkan | Tidak diubah menjadi bukti penyerahan dokter. Ditampilkan sebagai data lama tanpa petugas yang dikarang. |
| Status selesai | Label selesai dapat disalahartikan sebagai seluruh layanan sudah selesai | Label menjadi pemeriksaan selesai. Status penyerahan obat dan pelunasan tetap terpisah. |
| Pembayaran | Tagihan pemeriksaan dibuat otomatis; pasien mengirim referensi dan Admin memverifikasi | Alur ini adalah pencatatan pembayaran manual. Bahmni membedakan [tagihan dan penerimaan pembayaran](https://www.bahmni.org/billing-and-accounting). Status tidak menjadi lunas hanya karena pasien mengirim referensi. |

## Keputusan untuk tiga role

Role tambahan apoteker belum tersedia. Alur yang diterapkan adalah dokter
menyerahkan dan mencatat obat dari resepnya sendiri. Admin tidak diberi kewenangan
klinis baru. Ini pilihan alur aplikasi berdasarkan contoh Bahmni, bukan aturan
universal bahwa semua klinik harus menyerahkan obat melalui dokter.

Tombol penyerahan berarti seluruh obat pada resep telah diserahkan. Penyerahan
sebagian, persediaan obat, dan alur apotek terpisah belum didukung. Jika klinik
memakai apoteker untuk penyerahan, diperlukan role dan alur farmasi tersendiri.

## Batas yang masih nyata

- Registrasi masih berbasis akun. Biodata pasien seperti tanggal lahir, alamat,
  kontak, wali anak, dan mekanisme penggabungan pasien ganda belum tersedia;
  [registrasi Bahmni](https://www.bahmni.org/registration) mencakup informasi yang lebih lengkap.
- Rekam medis saat ini berisi keluhan, diagnosis, tindakan, dokter, dan tanggal.
  Tanda vital, alergi, hasil pemeriksaan terstruktur, lampiran, dan koreksi
  rekam medis dengan riwayat revisi belum tersedia.
- Resep masih berupa teks. Belum ada katalog obat, dosis terstruktur, stok,
  kedaluwarsa, atau biaya obat. [Prescribing Medications Bahmni](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/40501375/Prescribing+Medications)
  menunjukkan pemisahan dosis, frekuensi, rute, dan instruksi.
- Tagihan hanya biaya pemeriksaan per poli. Tarif dan slot jadwal masih memakai
  nilai tetap proyek; harus disesuaikan dengan layanan klinik yang sebenarnya.
  Belum ada rincian biaya obat, pembayaran tunai, cicilan, atau pengembalian dana.
- Database SQLite berada di satu komputer dan belum menyinkronkan perangkat.
  Tidak ada integrasi bank, BPJS, atau SATUSEHAT.

Kesimpulan audit: alur inti sistem klinik sederhana ada dan diuji, tetapi aplikasi
belum dapat disebut sistem operasional klinik lengkap. Bagian yang memerlukan
aturan fasilitas, tarif sebenarnya, dan alur petugas perlu ditentukan sebelum
menambah modul operasional tersebut.

## Verifikasi

Pengujian menggunakan database sementara dan widget Tkinter sebenarnya, meliputi
pembatasan role, alur kunjungan hingga pembayaran, penyerahan oleh dokter yang
sesuai, penolakan pengubahan status oleh pasien, transaksi gagal, migrasi database
versi 1, backup/impor versi 2, identitas pasien bernama sama, dan startup bersamaan.

```powershell
.\.tools\python\python.exe -W error::ResourceWarning -m unittest discover -s desktop_app\tests -v
.\run-desktop.bat --smoke-test
```
