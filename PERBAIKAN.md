# Ringkasan perbaikan VehiScan

## Cara menjalankan (terminal VS Code, di root proyek)
    .\venv\Scripts\activate
    pip install -r requirements.txt
    python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
    # atau: .\start.bat        (start.bat demo = isi data simulasi)
Buka http://127.0.0.1:8000. Uji asap semua halaman: `pip install httpx` lalu `python tests/smoke_test.py`.
Agar tampilan jalan offline (sekali, butuh internet): `python scripts/download_assets.py`.

## Bug yang diperbaiki
- Kendaraan lambat (< 3 km/jam, saat macet) tidak ikut terhitung -> volume dan LOS terlalu rendah. (Penanganan kecepatan rendah disempurnakan lagi, lihat bagian PKJI 2023.)
- Watchlist tidak cocok bila format spasi plat berbeda ("AB1234XY" vs "AB 1234 XY").
- Corridor: jam puncak dipilih dari jumlah mentah; klip video < 1 jam dianggap volume 1 jam penuh. Sekarang arus diekstrapolasi
  (per video: jumlah/durasi video), PHF hanya dihitung bila ada 4 interval 15 menit, ada filter per video.
- Laporan: jam puncak/V/C/LOS mengabaikan pilihan periode.
- Normalisasi plat memilih tafsiran dengan koreksi karakter paling sedikit ("8 1234 AB" -> "B 1234 AB", bukan "BI 234 AB").
- ANPR: detektor plat dipanggil dua kali per kendaraan.
- Hitung ganda: kendaraan yang sudah tercatat tidak lagi "dilupakan" (kotak yang melompat di garis bisa tercatat dua kali).
- Beberapa job paralel (banyak model YOLO + ffmpeg sekaligus) -> sekarang antre satu per satu.
- Job yang dihapus saat antre membuat thread crash; id job diambil lewat MAX(id) (balapan) -> sekarang lastrowid.
- SQLite: timeout + WAL + koneksi selalu ditutup (hindari "database is locked").
- Pratinjau JPEG tiap frame -> tiap 3 frame. Histogram kecepatan dihitung di SQL.
- anpr_conf default tidak konsisten (0.85 di seed vs 0.7 di default) -> satu nilai.
- start.bat yang disebut di dokumentasi tidak ada di ZIP -> ditambahkan.

## Fitur dibuang
Live Wall + stream RTSP + feed demo, Recordings, System Health (psutil), Users/peran, form SMTP/WhatsApp,
retensi data/purge, WebSocket Overview (diganti polling 5 detik). Data simulasi kini opt-in (`start.bat demo`).

## Belum diselesaikan (butuh keputusan Anda)
- Kapasitas = C0 x FCw x FCsp x FCsf x FCcs TIDAK memakai jumlah lajur/arah. Isi C0 sesuai tabel PKJI 2023 untuk tipe jalan dan arah yang diamati.
- Nilai emp/C0/FC masih placeholder.
- Plat yang baru terbaca setelah kendaraan melewati garis B tidak memperbarui catatan yang sudah tersimpan.
- Akurasi kecepatan/kelas/plat belum divalidasi lapangan; model COCO tidak membedakan KS dari KB.

## Penyesuaian PKJI 2023
- Notasi: FCw/FCsp/FCsf/FCcs -> F_CLJ/F_CPA/F_CHS/F_CUK; V/C -> D_J. D_J > 0,85 ditandai merah di Corridor.
- Kode kelas: BB -> LB (Bus Besar), KB -> LT (Truk Besar). Data lama dan bobot YOLO lama dimigrasi/dipetakan otomatis.
  (Singkatan di dokumen PKJI 2023 yang ditemukan: BB dan TB; LB/LT mengikuti permintaan Anda.)
- Tabel di `configs/pkji_2023.json` dikoreksi terhadap kutipan PKJI 2023:
  - emp 2/2-TT: ambang **1800** kend/jam; emp SM **turun** saat arus naik (<1800: 0,50 / 0,40; >=1800: 0,35 / 0,25 untuk lebar jalur <= 6 m / > 6 m); KS 1,3 -> 1,2.
  - emp jalan terbagi memakai arus PER LAJUR, ambang 1050 (KS 1,3/1,2; SM 0,40/0,25).
  - C0 jalan terbagi **1700**/lajur (bukan 1650); 2/2-TT 2800.
  - F_CLJ: terbagi per lebar lajur (3,0 = 0,92 ... 4,0 = 1,08); 2/2-TT menurut lebar JALUR dua arah (6 m = 0,87, 7 m = 1,00, 8 m = 1,14).
  - F_CHS otomatis dari KHS + lebar bahu untuk 2/2-TT berbahu. Jalan terbagi / berkereb: isi F_CHS manual (tabel tidak lengkap di sumber).
- LB dan LT memakai emp KS (tabel PKJI hanya memuat KS dan SM). BELUM TERVERIFIKASI; ubah di JSON bila dokumen resmi berbeda.
- Kendaraan pelan: SEMUA kendaraan yang melintasi garis A-B dicatat dan dihitung volumenya. Kecepatan < speed_min (default 2) hanya diberi status `macet` dan dikeluarkan dari rata-rata dan histogram kecepatan; tidak membuat notifikasi.
- Jalan terbagi dianalisis PER ARAH. Arah ditentukan otomatis dari urutan lintas garis (kolom `dir`: 1 = A lalu B, 2 = B lalu A). Kapasitas = C0 x lajur satu arah x faktor. Corridor menampilkan arah terburuk dan kedua arah. Data lama tanpa `dir` dianalisis gabungan.
- Halaman Corridor menampilkan rincian langkah; Parameter/Locations punya input KHS, lebar bahu, lebar lajur, pemisahan arah, ukuran kota.

## Batasan
- Hanya Jalan Perkotaan; JLK/JBH dan alinyemen belum ada. Batas LOS/D_J 0,85 dan F_CPA berasal dari catatan Anda, belum dicocokkan ke dokumen resmi.
- Arah 1/2 mengikuti orientasi garis A/B pada kalibrasi, bukan arah mata angin; kendaraan yang berhenti dan tidak mencapai garis kedua tidak tercacah.
