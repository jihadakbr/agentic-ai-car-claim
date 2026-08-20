"use client";

// Alat bantu memilih foto untuk video demo, bukan bagian produk. Datanya sudah disiapkan
// lewat scripts/siapkan_galeri_demo.py, jadi halaman ini tidak menjalankan model sama
// sekali dan tetap jalan meski backend mati.

import { useEffect, useMemo, useState } from "react";
import Kerangka from "@/components/Kerangka";
import OverlayVektor, {
  KUNCI_SETELAN,
  SETELAN_AWAL,
  type Bentuk,
  type Setelan,
} from "@/components/OverlayVektor";
import AturOverlay from "@/components/AturOverlay";
import IkonPanah from "@/components/IkonPanah";
import PratinjauFoto from "@/components/PratinjauFoto";
import {
  ambilTargetDemo,
  pasangFotoDemo,
  type TargetDemo,
} from "@/lib/api";
import { butuhIzin, IZIN } from "@/lib/auth";

type FotoDemo = {
  berkas: string;
  asal: string;
  dipakai_di: string | null;
  lebar: number;
  tinggi: number;
  nilai: number;
  iou: number;
  salah_tandai: number;
  tertutup: number;
  part: Bentuk[];
  damage: Bentuk[];
};


function alamatFoto(berkas: string) {
  return `/demo/foto/${berkas}`;
}

export default function HalamanDemo() {
  const [foto, setFoto] = useState<FotoDemo[] | null>(null);
  const [galat, setGalat] = useState("");
  const [dibuka, setDibuka] = useState<FotoDemo | null>(null);
  const [saringDamage, setSaringDamage] = useState("");
  const [saringPart, setSaringPart] = useState("");
  const [cumaTerpasang, setCumaTerpasang] = useState(false);
  const [setelan, setSetelan] = useState<Setelan>(SETELAN_AWAL);
  const [pratinjau, setPratinjau] = useState(false);
  // Penanda instance berbasis urutan, jadi cuma berlaku untuk foto yang sedang dibuka dan
  // tidak boleh ikut disimpan seperti setelan lainnya.
  const [instansiMati, setInstansiMati] = useState<string[]>([]);
  const [sorot, setSorot] = useState<string | null>(null);
  const [target, setTarget] = useState<TargetDemo[]>([]);
  const [tujuan, setTujuan] = useState("");
  const [memasang, setMemasang] = useState(false);
  const [pesan, setPesan] = useState("");

  useEffect(() => {
    const simpanan = localStorage.getItem(KUNCI_SETELAN);
    if (simpanan) {
      try {
        setSetelan({ ...SETELAN_AWAL, ...JSON.parse(simpanan) });
      } catch {
        // Setelan rusak tidak boleh membuat halamannya gagal terbuka.
      }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(KUNCI_SETELAN, JSON.stringify(setelan));
  }, [setelan]);

  useEffect(() => {
    ambilTargetDemo()
      .then(setTarget)
      .catch(() => setTarget([]));
  }, []);

  useEffect(() => {
    fetch("/demo/galeri.json", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error("Data galeri belum dibangkitkan");
        return r.json();
      })
      .then((isi) => setFoto(isi.foto))
      .catch((e: Error) => setGalat(e.message));
  }, []);

  const kelasKerusakan = useMemo(() => {
    const semua = new Set<string>();
    foto?.forEach((f) => f.damage.forEach((b) => semua.add(b.kelas)));
    return [...semua].sort();
  }, [foto]);

  const kelasBagian = useMemo(() => {
    const semua = new Set<string>();
    foto?.forEach((f) => f.part.forEach((b) => semua.add(b.kelas)));
    return [...semua].sort();
  }, [foto]);

  const terlihat = useMemo(() => {
    if (!foto) return [];
    return foto.filter(
      (f) =>
        (!cumaTerpasang || f.dipakai_di) &&
        (!saringDamage || f.damage.some((b) => b.kelas === saringDamage)) &&
        (!saringPart || f.part.some((b) => b.kelas === saringPart)),
    );
  }, [foto, saringDamage, saringPart, cumaTerpasang]);

  // Urutannya mengikuti daftar yang sedang terlihat, jadi saringan yang aktif ikut
  // menentukan gambar berikutnya.
  const indeks = dibuka ? terlihat.findIndex((f) => f.berkas === dibuka.berkas) : -1;
  const adaSebelum = indeks > 0;
  const adaSesudah = indeks >= 0 && indeks < terlihat.length - 1;

  function pindah(arah: number) {
    const i = indeks + arah;
    if (i < 0 || i >= terlihat.length) return;
    setDibuka(terlihat[i]);
    setInstansiMati([]);
    setSorot(null);
  }

  /** Satu baris pilihan per slot, karena folder 5 dan 7 memakai lebih dari satu foto. */
  // Kosong berarti aplikasinya sedang jalan di server yang tidak menyimpan bahan demo.
  const adaTujuan = target.length > 0;

  const pilihanTujuan = target.flatMap((t) =>
    t.slot.map((sl) => ({
      nilai: `${t.folder}|${sl.nomor}`,
      label:
        t.slot.length > 1
          ? `${t.folder}, foto ${sl.nomor}`
          : t.folder + (t.ikut.length ? ` dan ${t.ikut.join(", ")}` : ""),
    })),
  );

  async function pasang() {
    if (!dibuka || !tujuan) return;
    const [folder, slot] = tujuan.split("|");
    setMemasang(true);
    setPesan("");
    try {
      const hasil = await pasangFotoDemo(dibuka.asal, folder, Number(slot));
      setPesan(`Terpasang di ${hasil.ditulis.join(" dan ")}.`);
      // Lencana di galeri disesuaikan tanpa membangkitkan ulang datanya, supaya keadaan
      // di layar tetap cocok dengan isi folder sungguhan.
      setFoto((daftar) =>
        daftar?.map((f) =>
          f.berkas === dibuka.berkas
            ? { ...f, dipakai_di: hasil.ditulis[0] }
            : f.dipakai_di?.startsWith(`${folder}/`)
              ? { ...f, dipakai_di: null }
              : f,
        ) ?? null,
      );
    } catch (e) {
      setPesan((e as Error).message);
    } finally {
      setMemasang(false);
    }
  }

  function ubah(bagian: Partial<Setelan>) {
    setSetelan((s) => ({ ...s, ...bagian }));
  }

  return (
    <Kerangka
      judul="Demo"
      keterangan="Galeri hasil deteksi untuk memilih foto demo"
      butuh={butuhIzin(IZIN.aksesKelola)}
    >
      {galat && (
        <div className="galat">
          {galat}. Jalankan <code>uv run python scripts/siapkan_galeri_demo.py</code> di
          folder backend.
        </div>
      )}
      {!foto && !galat && <p className="redup">Memuat...</p>}

      {foto && !dibuka && (
        <div className="kartu">
          <div className="baris">
            <div>
              <label htmlFor="saring-damage">Kerusakan</label>
              <select
                id="saring-damage"
                value={saringDamage}
                onChange={(e) => setSaringDamage(e.target.value)}
              >
                <option value="">Semua jenis</option>
                {kelasKerusakan.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="saring-part">Bagian mobil</label>
              <select
                id="saring-part"
                value={saringPart}
                onChange={(e) => setSaringPart(e.target.value)}
              >
                <option value="">Semua bagian</option>
                {kelasBagian.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cuma-terpasang">Demo</label>
              <input
                id="cuma-terpasang"
                type="checkbox"
                checked={cumaTerpasang}
                onChange={(e) => setCumaTerpasang(e.target.checked)}
                disabled={!adaTujuan}
                title={
                  adaTujuan
                    ? "Tampilkan hanya foto yang sudah terpasang di folder skenario"
                    : "Folder skenario tidak ada di server, jadi tidak ada yang bisa disaring"
                }
              />
            </div>
          </div>

          <p className="redup">
            {terlihat.length} dari {foto.length} foto. Urutan dari hasil prediksi terbaik.
          </p>

          <div className="galeri-demo">
            {terlihat.map((f) => (
              <button
                key={f.berkas}
                type="button"
                onClick={() => {
                  setDibuka(f);
                  setInstansiMati([]);
                  setSorot(null);
                }}
              >
                <img src={alamatFoto(f.berkas)} alt={f.asal} loading="lazy" />
                <span className="galeri-nilai">{f.nilai.toFixed(2)}</span>
                {f.dipakai_di && (
                  <span className="lencana hijau">{f.dipakai_di.split("/")[0]}</span>
                )}
                <span className="redup">
                  salah label {Math.round(f.salah_tandai * 100)}%, {f.damage.length}{" "}
                  kerusakan
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {dibuka && (
        <>
          <div className="kartu">
            <div className="kepala-demo">
              <button type="button" className="sekunder" onClick={() => setDibuka(null)}>
                Kembali ke galeri
              </button>
              <button
                type="button"
                className="sekunder pindah-gambar"
                onClick={() => pindah(-1)}
                disabled={!adaSebelum}
                aria-label="Gambar sebelumnya"
                title="Gambar sebelumnya"
              >
                <IkonPanah arah="kiri" />
              </button>
              <button
                type="button"
                className="sekunder pindah-gambar"
                onClick={() => pindah(1)}
                disabled={!adaSesudah}
                aria-label="Gambar berikutnya"
                title="Gambar berikutnya"
              >
                <IkonPanah arah="kanan" />
              </button>
              <span className="redup">
                {indeks + 1} dari {terlihat.length}
              </span>
              <span className="redup">
                nilai {dibuka.nilai.toFixed(2)}, berhimpit{" "}
                {Math.round(dibuka.iou * 100)}%, salah label{" "}
                {Math.round(dibuka.salah_tandai * 100)}%
              </span>
            </div>

            <div className="banding-demo">
              <figure onClick={() => setPratinjau(true)}>
                <figcaption>Foto asli</figcaption>
                <img src={alamatFoto(dibuka.berkas)} alt="Foto asli" />
              </figure>
              <figure onClick={() => setPratinjau(true)}>
                <figcaption>Prediksi AI</figcaption>
                <OverlayVektor
                  alamat={alamatFoto(dibuka.berkas)}
                  lebar={dibuka.lebar}
                  tinggi={dibuka.tinggi}
                  part={dibuka.part}
                  damage={dibuka.damage}
                  setelan={setelan}
                  instansiMati={instansiMati}
                  sorot={sorot}
                />
              </figure>
            </div>

            <div className="pasang-demo">
              <label htmlFor="tujuan-demo">Pasang ke folder skenario</label>
              <select
                id="tujuan-demo"
                value={tujuan}
                onChange={(e) => setTujuan(e.target.value)}
                disabled={!adaTujuan}
              >
                <option value="">{adaTujuan ? "Pilih tujuan" : "Tidak tersedia"}</option>
                {pilihanTujuan.map((p) => (
                  <option key={p.nilai} value={p.nilai}>
                    {p.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={pasang}
                disabled={!adaTujuan || !tujuan || memasang}
              >
                {memasang ? "Memasang..." : "Pasang"}
              </button>
              {pesan && <span className="redup">{pesan}</span>}
            </div>

            {!adaTujuan && (
              <p className="redup">
                Pemasangan foto cuma bisa dijalankan saat aplikasinya dijalankan di komputer
                yang menyimpan bahan demo. Di server, folder skenario dan dataset asalnya
                memang tidak ikut diunggah, jadi tidak ada tujuan yang bisa dipilih. Galeri
                di atas tetap berfungsi penuh.
              </p>
            )}

            <p className="redup">
              Berkas aslinya: <code>{dibuka.asal}</code>
            </p>

            {pratinjau && (
              <PratinjauFoto
                saatTutup={() => setPratinjau(false)}
                saatSebelum={adaSebelum ? () => pindah(-1) : undefined}
                saatSesudah={adaSesudah ? () => pindah(1) : undefined}
                panel={[
                  {
                    judul: "Foto asli",
                    keterangan: "Foto asli tanpa hasil deteksi",
                    alamat: alamatFoto(dibuka.berkas),
                  },
                  {
                    judul: "Prediksi AI",
                    keterangan: "Foto dengan hasil deteksi",
                    isi: (
                      <OverlayVektor
                        alamat={alamatFoto(dibuka.berkas)}
                        lebar={dibuka.lebar}
                        tinggi={dibuka.tinggi}
                        part={dibuka.part}
                        damage={dibuka.damage}
                        setelan={setelan}
                        instansiMati={instansiMati}
                        sorot={sorot}
                      />
                    ),
                  },
                ]}
                alat={
                  <AturOverlay
                    setelan={setelan}
                    saatUbah={ubah}
                    part={dibuka.part}
                    damage={dibuka.damage}
                    instansiMati={instansiMati}
                    saatUbahInstansi={setInstansiMati}
                    saatSorot={setSorot}
                  />
                }
              />
            )}
          </div>

        </>
      )}
    </Kerangka>
  );
}
