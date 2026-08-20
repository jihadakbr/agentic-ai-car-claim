"use client";

import { useEffect, useState } from "react";
import {
  Donat,
  KartuAngka,
  WARNA_CEK,
  WARNA_KATEGORI,
  WARNA_REKOMENDASI,
  WARNA_VERDICT,
} from "@/components/Grafik";
import Kerangka from "@/components/Kerangka";
import TabelKlaim from "@/components/TabelKlaim";
import { ambilRingkasan, type Ringkasan } from "@/lib/api";
import { butuhIzin, IZIN } from "@/lib/auth";
import { labelRekomendasi, persen, rupiah } from "@/lib/format";

const NAMA_VERDICT: Record<string, string> = {
  valid: "Valid",
  perlu_review: "Perlu review",
  invalid: "Invalid",
};

const NAMA_CEK: Record<string, string> = {
  C1: "Ada kerusakan riil",
  C2: "Foto tidak dipakai ulang",
  C3: "Konsisten antar sudut",
  C4: "Plat cocok dengan STNK",
  C5: "STNK terbaca dan konsisten",
  C6: "STNK cocok dengan polis",
  C7: "Bukan kerusakan lama",
};

const NAMA_ALASAN: Record<string, string> = {
  bagian_salah: "Bagian mobil salah",
  jenis_kerusakan_salah: "Jenis kerusakan salah",
  kerusakan_tidak_ada: "Kerusakan tidak ada",
  luas_terlalu_besar: "Luas kerusakan terlalu besar",
  luas_terlalu_kecil: "Luas kerusakan terlalu kecil",
  kerusakan_lama: "Kerusakan lama",
};

const BELUM_DIPUTUSKAN = ["siap_review", "menunggu_foto_tambahan", "diproses"];

export default function HalamanRingkasan() {
  const [data, setData] = useState<Ringkasan | null>(null);
  const [galat, setGalat] = useState("");

  function muat() {
    ambilRingkasan()
      .then(setData)
      .catch((e: Error) => setGalat(e.message));
  }

  useEffect(muat, []);

  // Backend versi lama belum mengirim angka deteksi. Halaman tetap harus tampil, bukan
  // mati total, kalau backend-nya belum dijalankan ulang setelah pembaruan.
  const deteksi = data?.deteksi ?? {
    total_temuan: 0,
    dinilai: 0,
    benar: 0,
    akurasi: null,
    alasan_salah: {},
  };
  const stnk = data?.stnk ?? {
    dinilai: 0,
    benar: 0,
    akurasi: null,
    salah_per_field: {},
  };

  const menunggu = data
    ? BELUM_DIPUTUSKAN.reduce((a, s) => a + (data.per_status[s] ?? 0), 0)
    : 0;

  return (
    <Kerangka
      judul="Overview"
      keterangan="Angka gabungan seluruh klaim yang pernah masuk"
      butuh={butuhIzin(IZIN.overviewLihat)}
    >
      {galat && <div className="galat">{galat}</div>}
      {!data && !galat && <p className="redup">Memuat...</p>}

      {data && (
        <>
          <div className="kisi-angka">
            <KartuAngka label="Total klaim" nilai={String(data.total_klaim)} />
            <KartuAngka
              label="Menunggu diputuskan"
              nilai={String(menunggu)}
              keterangan="Belum disetujui, ditolak, maupun diminta revisi"
            />
            <KartuAngka
              label="Total nilai klaim"
              nilai={rupiah(data.total_nilai_klaim)}
              keterangan={`Dari ${data.klaim_dinilai} klaim yang sudah dihitung`}
            />
            <KartuAngka
              label="Rata-rata rasio total loss"
              nilai={persen(data.rata_rasio)}
              keterangan="Ambang PSAKBI 75%"
            />
            <KartuAngka
              label="Ketepatan deteksi kerusakan"
              nilai={
                deteksi.akurasi === null
                  ? "Belum dinilai"
                  : persen(deteksi.akurasi)
              }
              keterangan={`${deteksi.dinilai} dari ${deteksi.total_temuan} temuan sudah dinilai adjuster`}
            />
            <KartuAngka
              label="Ketepatan baca STNK"
              nilai={stnk.akurasi === null ? "Belum dinilai" : persen(stnk.akurasi)}
              keterangan={`${stnk.benar} dari ${stnk.dinilai} field terbaca benar`}
            />
          </div>

          <div className="kisi-grafik">
            <div className="kartu">
              <Donat
                judul="Rekomendasi mesin"
                potongan={Object.entries(data.per_rekomendasi).map(
                  ([k, v]) => ({
                    label: labelRekomendasi(k),
                    nilai: v,
                    warna: WARNA_REKOMENDASI[k] ?? "#94a3b8",
                  }),
                )}
              />
            </div>

            <div className="kartu">
              <Donat
                judul="Hasil pemeriksaan validitas"
                potongan={Object.entries(data.per_verdict).map(([k, v]) => ({
                  label: NAMA_VERDICT[k] ?? k,
                  nilai: v,
                  warna: WARNA_VERDICT[k] ?? "#94a3b8",
                }))}
              />
            </div>

            <div className="kartu">
              <Donat
                judul="Pemeriksaan yang paling sering gagal"
                potongan={Object.entries(data.gagal_cek)
                  .sort((a, b) => b[1] - a[1])
                  .map(([kode, jumlah], i) => ({
                    label: `${kode}: ${NAMA_CEK[kode] ?? kode}`,
                    nilai: jumlah,
                    warna: WARNA_CEK[i % WARNA_CEK.length],
                  }))}
                satuan="kali"
              />
            </div>

            {/* Baru muncul setelah ada temuan yang ditandai salah, supaya tidak ada kartu
                kosong saat belum ada penilaian sama sekali. */}
            {Object.keys(deteksi.alasan_salah).length > 0 && (
              <div className="kartu">
                <Donat
                  judul="Jenis kesalahan deteksi"
                  potongan={Object.entries(deteksi.alasan_salah)
                    .sort((a, b) => b[1] - a[1])
                    .map(([kode, jumlah], i) => ({
                      label: NAMA_ALASAN[kode] ?? kode,
                      nilai: jumlah,
                      warna: WARNA_KATEGORI[i % WARNA_KATEGORI.length],
                    }))}
                  satuan="temuan"
                />
              </div>
            )}
          </div>

          <div className="kartu">
            <h2>Klaim terbaru</h2>
            <TabelKlaim klaim={data.terbaru} ringkas saatHapus={muat} />
          </div>

          <p className="redup">
            Pemakaian token LLM seluruh klaim: {data.token.masuk} input,{" "} {data.token.keluar} output.
          </p>
        </>
      )}
    </Kerangka>
  );
}
