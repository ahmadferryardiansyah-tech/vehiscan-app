# Contoh perhitungan manual PKJI 2023 dari keluaran deteksi VehiScan

> **Catatan jujur:** paket ZIP tidak berisi hasil deteksi nyata. Log di bawah adalah **contoh ilustrasi** dengan format kolom
> yang sama seperti ekspor aplikasi. Angka diverifikasi dengan `python scripts/contoh_perhitungan_manual.py`
> (dan `--contoh terbagi`). Untuk data asli: Vehicle Logs -> Export CSV, lalu
> `python scripts/contoh_perhitungan_manual.py vehiscan_logs.csv --durasi <detik> --lokasi <id>`.
> Tabel dicocokkan dengan kutipan PKJI 2023 di sumber sekunder; cek ulang dengan dokumen resmi sebelum laporan formal.

## 0. Keluaran aplikasi yang dipakai

Tabel `detections` (Vehicle Logs / CSV). Satu baris = satu kendaraan yang melewati garis A dan B. Kolom `dir`: 1 = A lalu B, 2 = B lalu A.

| id | ts | camera | plate | pkji | speed | status | dir |
|---|---|---|---|---|---|---|---|
| 1 | 2026-11-09 08:00:07 | CAM-03 Simpang Kentungan | AB 4521 BC | MP | 38.4 | normal | 1 |
| 2 | 2026-11-09 08:00:09 | CAM-03 Simpang Kentungan | TIDAK TERBACA | SM | 41.2 | normal | 2 |
| 3 | 2026-11-09 08:00:15 | CAM-03 Simpang Kentungan | TIDAK TERBACA | SM | 0.6 | macet | 1 |
| ... | | | | | | | |

Video **600 detik**. Rekap kolom `pkji`: **SM 103, MP 68, KS 9, LB 2, LT 5 = 187 kendaraan**. Baris `macet` (id 3) tetap dihitung.
Parameter lokasi: 2/2-TT, 2 lajur x 3,5 m, pemisahan arah 50-50, kota 0,85 juta jiwa, KHS rendah (LO), bahu efektif 2,0 m.

## A. Jalan tak terbagi 2/2-TT (dua arah sekaligus)

**Kecepatan (baris 1):** garis A-B 15 m, selisih waktu lintas 1,08 s -> v = 15 / 1,08 x 3,6 = **50,0 km/jam**.
v < 2 km/jam -> status `macet`: tetap dihitung volume, hanya keluar dari statistik kecepatan. v > 250 -> dibuang.

**Arus:** faktor 3600 / 600 = 6.

| Kelas | Jumlah | x 6 = kend/jam |
|---|---|---|
| SM | 103 | 618 |
| MP | 68 | 408 |
| KS | 9 | 54 |
| LB | 2 | 12 |
| LT | 5 | 30 |
| **Q** | 187 | **1.122** |

**emp:** 2/2-TT, Q = 1.122 < 1800 -> baris "Q < 1800": KS 1,3. Lebar jalur 3,5 x 2 = 7 m > 6 m -> SM 0,40. LB dan LT memakai nilai KS (1,3).

| Kelas | emp x Q | smp/jam |
|---|---|---|
| SM | 0,40 x 618 | 247,2 |
| MP | 1,0 x 408 | 408,0 |
| KS | 1,3 x 54 | 70,2 |
| LB | 1,3 x 12 | 15,6 |
| LT | 1,3 x 30 | 39,0 |
| **Q_smp** | | **780,0** |

**Kapasitas:** C = C0 x F_CLJ x F_CPA x F_CHS x F_CUK = 2800 x 1,00 x 1,00 x 1,00 x 0,94 = **2.632 smp/jam**
(F_CLJ lebar jalur 7 m = 1,00; F_CPA 50-50 = 1,00; F_CHS KHS LO + bahu 2,0 m = 1,00; F_CUK 0,5-1,0 juta = 0,94).

**D_J** = 780,0 / 2.632 = **0,296** -> **LOS B**, D_J <= 0,85 sehingga **laik**.

**PHF** (hanya rekaman >= 1 jam): jumlah per 15 menit 255, 280, 310, 280 -> 1.125 / (4 x 310) = **0,91**.

## B. Jalan terbagi 4/2-T (WAJIB per arah)

Rekaman sama 600 detik; tiap arah dipisah dari kolom `dir`. 2 lajur satu arah, lebar lajur 3,5 m.

| | Arah 1 | Arah 2 |
|---|---|---|
| Jumlah (SM, MP, KS, LB, LT) | 60, 40, 5, 1, 3 = 109 | 100, 85, 8, 2, 5 = 200 |
| Q (x 6) | 654 kend/jam | 1.200 kend/jam |
| Q per lajur | 327 | 600 |
| Baris emp (Q/lajur < 1050) | KS 1,3 · SM 0,40 | KS 1,3 · SM 0,40 |
| Q_smp | 144 + 240 + 39 + 7,8 + 23,4 = **454,2** | 240 + 510 + 62,4 + 15,6 + 39 = **867,0** |
| C = 1700 x 2 lajur x 1,00 x 1,00 x F_CHS x 0,94 | **3.196** | **3.196** |
| D_J | 454,2 / 3.196 = **0,142** (LOS A) | 867,0 / 3.196 = **0,271** (LOS B) |

F_CHS jalan terbagi dipakai 1,00 karena tabelnya belum ada; isi manual bila perlu. Aplikasi menampilkan arah terburuk (D_J tertinggi) dan kedua arah di panel rincian.
Bila digabung dua arah, D_J rata-rata bisa menutupi arah yang jenuh, itulah alasan jalan terbagi dihitung per arah.
