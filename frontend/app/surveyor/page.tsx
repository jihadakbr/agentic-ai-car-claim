"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useFormulirKlaim } from "@/components/FormulirKlaim";
import Kerangka from "@/components/Kerangka";
import { ambilPolis, kirimKlaim } from "@/lib/api";
import { butuhIzin, IZIN } from "@/lib/auth";
import { perkecil } from "@/lib/gambar";
import { berkasKembar, bisaMenyidik, sidikSemua } from "@/lib/sidik";

// Batas sebenarnya ada di tabel config dan ditegakkan server. Angka di sini cuma supaya
// tombol Kirim mati lebih awal, jadi kalau config diubah, angka ini ikut disesuaikan.
const MIN_FOTO = 1;
const MAX_FOTO = 6;
const MAX_PELENGKAP = 12;

/** Kembalikan daftar berkas ke kotak pilih berkas setelah komponennya dibuat ulang. */
function pulihkanBerkas(kotak: HTMLInputElement | null, berkas: File[]) {
  if (!kotak || berkas.length === 0 || typeof DataTransfer === "undefined") return;
  const wadah = new DataTransfer();
  berkas.forEach((b) => wadah.items.add(b));
  kotak.files = wadah.files;
}

function Wajib() {
  return (
    <span className="wajib" aria-hidden="true">
      *
    </span>
  );
}

export default function HalamanSurveyor() {
  // Isian formulir tinggal di layout, bukan di halaman ini, supaya tidak hilang saat
  // pindah menu lalu kembali.
  const {
    nomorPolis, setNomorPolis,
    polis, setPolis,
    foto, setFoto,
    fotoStnk, setFotoStnk,
    fotoPelengkap, setFotoPelengkap,
  } = useFormulirKlaim();

  const [galat, setGalat] = useState("");
  const [duplikat, setDuplikat] = useState("");
  const [terkirim, setTerkirim] = useState("");
  const [sibuk, setSibuk] = useState(false);

  // Kotak pilih berkas selalu kosong saat dibuat ulang, meski fotonya masih tersimpan.
  // Isinya dikembalikan lewat DataTransfer, satu-satunya cara yang diizinkan browser
  // untuk mengisi kotak berkas dari kode.
  const kotakFoto = useRef<HTMLInputElement>(null);
  const kotakStnk = useRef<HTMLInputElement>(null);
  const kotakPelengkap = useRef<HTMLInputElement>(null);

  // Penanda supaya pengecekan otomatis cuma sekali, dan tidak pernah untuk nomor yang
  // sedang diketik. Tanpa penanda kedua, tiap huruf yang diketik memicu satu permintaan.
  const otomatisJalan = useRef(false);
  const diketik = useRef(false);

  useEffect(() => {
    pulihkanBerkas(kotakFoto.current, foto);
    pulihkanBerkas(kotakStnk.current, fotoStnk ? [fotoStnk] : []);
    pulihkanBerkas(kotakPelengkap.current, fotoPelengkap);
    // Sengaja cuma sekali saat halaman dibuka. Menjalankannya tiap kali daftar fotonya
    // berubah akan menimpa pilihan yang baru saja dibuat surveyor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Nomor polis bertahan di sessionStorage, data polisnya tidak. Tanpa pengecekan ulang
  // di sini, halaman yang dimuat ulang menampilkan nomor polis yang sudah terisi sementara
  // tombol Kirim tetap mati tanpa sebab yang terlihat.
  useEffect(() => {
    if (otomatisJalan.current || diketik.current) return;
    if (!nomorPolis.trim() || polis !== null) return;
    otomatisJalan.current = true;
    periksaPolis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nomorPolis, polis]);

  async function periksaPolis() {
    setGalat("");
    setPolis(null);
    try {
      setPolis(await ambilPolis(nomorPolis.trim()));
    } catch (e) {
      setGalat((e as Error).message);
    }
  }

  async function kirim() {
    if (!fotoStnk) return;
    setGalat("");
    setDuplikat("");
    setTerkirim("");
    setSibuk(true);
    try {
      // Yang diperiksa di sini cuma foto kembar di dalam satu kiriman, karena itu salah
      // pilih berkas. Foto yang dipakai ulang dari klaim lain diperiksa server lewat
      // sidik jari gambar, supaya hasilnya sama dari browser mana pun.
      if (bisaMenyidik()) {
        const sidik = await sidikSemua(foto);
        const kembar = berkasKembar(foto, sidik);
        if (kembar.length > 0) {
          setDuplikat(
            `Foto yang sama dipilih lebih dari sekali (${kembar.join(", ")}). ` +
              "Ganti dengan sudut yang berbeda.",
          );
          return;
        }
      }

      const kecil = await Promise.all(foto.map(perkecil));
      // Foto pelengkap ikut diperkecil. Isinya cuma dilihat mata adjuster, tidak dibaca OCR
      // maupun model deteksi, jadi ukuran layar sudah cukup.
      const pelengkapKecil = await Promise.all(fotoPelengkap.map(perkecil));
      // Foto STNK tidak diperkecil, karena tulisan kecil di dalamnya harus tetap terbaca OCR.
      const hasil = await kirimKlaim(
        nomorPolis.trim(), kecil, fotoStnk, pelengkapKecil,
      );

      setTerkirim(hasil.nomor_klaim);

      // Foto dikosongkan, nomor polis dipertahankan karena satu polis kadang dikirimi
      // lebih dari satu klaim berturut-turut.
      setFoto([]);
      setFotoStnk(null);
      setFotoPelengkap([]);
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setSibuk(false);
    }
  }

  const jumlahPas = foto.length >= MIN_FOTO && foto.length <= MAX_FOTO;

  // Tugas surveyor selesai begitu foto terkirim. Klaim yang ditahan menunggu foto tambahan
  // tidak menghalangi pengiriman berikutnya, dan diselesaikan dari menu Klaim Saya.
  const bisaKirim =
    !sibuk &&
    polis !== null &&
    jumlahPas &&
    fotoStnk !== null &&
    fotoPelengkap.length <= MAX_PELENGKAP;

  return (
    <Kerangka
      judul="Ajukan Klaim"
      keterangan="Upload foto kerusakan mobil dan STNK"
      butuh={butuhIzin(IZIN.klaimKirim)}
    >
      <div className="kartu">
        <h2>Data klaim</h2>
        {/* Tanpa <br /> di antara kalimatnya. Baris yang dipaksa putus terlihat kacau
            begitu kalimat sebelumnya sudah terbungkus sendiri oleh batas lebar. */}
        <p className="petunjuk">
          Data kendaraan dibaca dari STNK. <br />
          Tanda <span className="wajib">*</span> wajib diisi.
        </p>

        {galat && <div className="galat">{galat}</div>}
        {duplikat && <div className="peringatan">{duplikat}</div>}

        <div className="baris">
          <div>
            <label htmlFor="polis">
              Nomor polis <Wajib />
            </label>
            <input
              id="polis"
              type="text"
              value={nomorPolis}
              placeholder="POL-2024-0037"
              onChange={(e) => {
                diketik.current = true;
                setNomorPolis(e.target.value);
              }}
              onBlur={() => nomorPolis.trim() && periksaPolis()}
            />
          </div>
        </div>

        {polis && (
          <p className="redup">
            {polis.kendaraan} {polis.tahun}, {polis.nomor_polisi}, atas nama{" "}
            {polis.pemegang}
          </p>
        )}

        {/* Tombol Kirim mati selama polisnya belum terbaca, dan tanpa baris ini tidak ada
            yang menunjukkan kenapa. */}
        {!polis && !galat && nomorPolis.trim() !== "" && (
          <p className="redup">
            Klik di luar kotak untuk memeriksa nomor polisnya.
          </p>
        )}

        <div style={{ marginBottom: 14 }}>
          <label htmlFor="foto">
            Foto kerusakan <Wajib />
          </label>
          <p className="redup" style={{ margin: "0 0 6px" }}>
            AI mendeteksi kerusakan dari foto ini. <br /> 
            Maksimum: {MAX_FOTO} foto. 
          </p>
          <input
            id="foto"
            type="file"
            accept="image/jpeg,image/png"
            multiple
            ref={kotakFoto}
            onChange={(e) => setFoto(Array.from(e.target.files ?? []))}
          />
          {foto.length > MAX_FOTO && (
            <p className="redup">
              Terpilih {foto.length} foto.
            </p>
          )}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label htmlFor="pelengkap">Foto pelengkap</label>
          <p className="redup" style={{ margin: "0 0 6px" }}>
            Tidak diproses oleh AI, hanya sebagai pelengkap. <br />
            Maksimum: {MAX_PELENGKAP} foto.
          </p>
          <input
            id="pelengkap"
            type="file"
            accept="image/jpeg,image/png"
            multiple
            ref={kotakPelengkap}
            onChange={(e) => setFotoPelengkap(Array.from(e.target.files ?? []))}
          />
          {fotoPelengkap.length > MAX_PELENGKAP && (
            <p className="redup">
              Terpilih {fotoPelengkap.length} foto pelengkap.
            </p>
          )}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label htmlFor="stnk">
            Foto STNK <Wajib />
          </label>
          <input
            id="stnk"
            type="file"
            accept="image/jpeg,image/png"
            ref={kotakStnk}
            onChange={(e) => setFotoStnk(e.target.files?.[0] ?? null)}
          />
        </div>

        <button onClick={kirim} disabled={!bisaKirim}>
          {sibuk ? "Mengirim..." : "Kirim klaim"}
        </button>

        {/* Konfirmasi ditaruh di bawah tombolnya, di tempat mata berhenti setelah menekan
            Kirim, bukan di atas formulir yang sudah terlewat. */}
        {terkirim && (
          <div className="berhasil-kotak" style={{ margin: "var(--jarak) 0 0" }}>
            Klaim {terkirim} terkirim dan sedang diproses. <br />
            Pantau statusnya di menu <Link href="/klaim-saya">Klaim Saya</Link>.
          </div>
        )}
      </div>
    </Kerangka>
  );
}
