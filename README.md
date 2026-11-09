# VehiScan ITS Enterprise (Smart Road Capacity)

Membaca video lalu lintas: kelas kendaraan (PKJI), plat nomor, kecepatan, lalu menghitung volume, kapasitas, derajat kejenuhan (D_J), LOS, dan PHF menurut PKJI 2023.
Seluruh pemrosesan berjalan lokal di komputer ini.

## Menjalankan (Windows, terminal VS Code di folder ini)
```
py -3.12 -m venv venv          # sekali saja
.\venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```
Buka http://127.0.0.1:8000. Atau klik dua kali `start.bat` (`start.bat demo` mengisi data simulasi untuk presentasi).

## Alur pemakaian
1. **Calibration**: ambil satu frame jalan, klik 4 titik, isi ukuran asli (meter), atur garis A/B, simpan.
2. **Video Analysis**: unggah MP4 dengan kamera yang sama; pantau pratinjau; tonton replay beranotasi setelah selesai.
3. **Corridor / Vehicle Logs / Reports**: hasilnya dibaca dari database yang sama.
4. **Parameter / Locations / Cameras**: semua angka dan keterangan bisa diubah lewat web.

## Memperbarui tanpa kehilangan data
Paket ini **tidak** membawa `data/` (database, video, replay) maupun `configs/calibration.json` (kalibrasi Anda).
Ekstrak ke atas folder lama dan pilih *Replace*; data dan kalibrasi tetap aman. Pada folder baru, kalibrasi dibuat otomatis dari
`configs/calibration.example.json` (belum ada kamera terkalibrasi). Jangan ikutkan folder `venv` saat membuat zip/cadangan.

## Bila video tidak terproses
```
python scripts/cek_sistem.py
```
Memeriksa paket, model, OCR, ffmpeg, kalibrasi, dan menguji seluruh rantai; hasil di `data/cek_sistem.txt`.
Alasan kegagalan job juga tampil di kolom **Catatan** (menu Video Analysis), di terminal, dan di `data/errors.log`.
Uji halaman web: `python -m pip install httpx` lalu `python tests/smoke_test.py`.
Agar tampilan jalan offline (sekali, butuh internet): `python scripts/download_assets.py`.

## Catatan
- Model: `yolo11_pkji.pt` (hasil training sendiri) diprioritaskan; bila belum ada dipakai `yolo11s.pt` (COCO, KS tidak terbedakan dari KB).
- Parameter PKJI 2023 (emp dinamis, C0, F_CLJ, F_CPA, F_CHS, F_CUK) mengikuti `configs/pkji_2023.json`; hanya Jalan Perkotaan. Jalan terbagi dianalisis per arah. Verifikasi tabel dengan dokumen resmi sebelum laporan formal.
- Kode kelas: SM, MP, KS, LB (Bus Besar), LT (Truk Besar). Bobot lama dengan nama KB/BB tetap dikenali.
- Contoh hitungan tangan: `PERHITUNGAN_MANUAL.md`; jalankan pada data sendiri dengan `python scripts/contoh_perhitungan_manual.py data.csv --durasi 600`.
- Belum ada login. Jangan dibuka ke internet publik.
- Perubahan dari sesi perbaikan terdapat di `PERBAIKAN.md`.
