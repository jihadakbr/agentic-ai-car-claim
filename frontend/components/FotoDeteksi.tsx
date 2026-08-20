"use client";

import { useEffect, useState } from "react";
import AturOverlay from "@/components/AturOverlay";
import IkonPanah from "@/components/IkonPanah";
import OverlayVektor, {
  idBentuk,
  KUNCI_SETELAN,
  namaSekelas,
  nomorSekelas,
  SETELAN_AWAL,
  type Setelan,
} from "@/components/OverlayVektor";
import PratinjauFoto from "@/components/PratinjauFoto";
import {
  alamatFoto,
  batalkanReviewDeteksi,
  kirimReviewDeteksi,
  type AlasanSalah,
  type DetailKlaim,
  type FotoKlaim,
} from "@/lib/api";
import { persen } from "@/lib/format";

/** Alasan dibatasi pilihan tetap, bukan teks bebas, supaya hasilnya bisa dihitung dan
 *  dipakai sebagai label saat model dilatih ulang.
 *
 *  Awalannya membedakan dua hal yang beda jenis. "Salah" berarti modelnya keliru dan
 *  jawabannya layak jadi label pelatihan. "Tidak dijamin" berarti modelnya benar, cuma
 *  kerusakannya memang tidak bisa diklaim, dan itu bukan urusan akurasi model.
 */
const ALASAN: Record<AlasanSalah, { awalan: string; teks: string }> = {
  bagian_salah: { awalan: "Salah", teks: '"Bagian mobil"' },
  jenis_kerusakan_salah: { awalan: "Salah", teks: 'Jenis "Kerusakan"' },
  kerusakan_tidak_ada: { awalan: "Salah", teks: '"Kerusakan" tidak ada' },
  luas_terlalu_besar: { awalan: "Salah", teks: 'Luas "Kerusakan" terlalu besar' },
  luas_terlalu_kecil: { awalan: "Salah", teks: 'Luas "Kerusakan" terlalu kecil' },
  kerusakan_lama: {
    awalan: "Tidak dijamin",
    teks: "Kerusakan lama, bukan dari kejadian ini",
  },
};

type Nilai = "benar" | AlasanSalah;

/** Sisi dan nomor instance disatukan dalam satu kurung, supaya barisnya tidak berakhir
 *  dengan dua kurung berturut-turut seperti "Front-bumper (kiri) (2)". */
function labelBagian(kelas: string, sisi: string | null, nomor: number | null): string {
  const isi = [sisi, nomor === null ? null : String(nomor)].filter(Boolean);
  return isi.length ? `${kelas} (${isi.join(", ")})` : kelas;
}

/** Penilaian adjuster menang atas usulan sistem. Usulan cuma mengisi baris yang belum
 *  pernah dinilai, jadi adjuster yang sudah menjawab "benar" tidak ditimpa tiap muat ulang. */
function nilaiAwal(foto: FotoKlaim[]): Record<string, Nilai> {
  const awal: Record<string, Nilai> = {};
  for (const f of foto) {
    for (const t of f.temuan) {
      if (t.review) {
        awal[t.id] = t.review.benar ? "benar" : t.review.alasan!;
      } else {
        awal[t.id] = t.usulan?.alasan ?? "benar";
      }
    }
  }
  return awal;
}

/** Kalimat pengantarnya berbeda menurut siapa yang membaca, karena tanggung jawabnya
 *  memang berbeda. Surveyor memeriksa apakah fotonya layak dipakai selagi masih di lokasi.
 *  Adjuster butuh tahu dari mana angka biayanya datang, karena dialah yang menyetujui. */
const PENGANTAR = {
  surveyor:
    "Periksa apakah sistem menandai bagian yang benar. Kalau ada yang meleset karena " +
    "fotonya terlalu jauh atau kurang terang, foto ulang selagi masih di lokasi.",
  adjuster:
    "Angka biaya dihitung dari irisan antara luas bagian yang rusak terhadap luas bagian " +
    "mobilnya.",
};

export default function FotoDeteksi({
  klaim,
  untuk,
  terkunci = false,
  saatBerubah,
}: {
  klaim: DetailKlaim;
  untuk: keyof typeof PENGANTAR;
  /** Klaim yang sudah diputuskan tidak boleh diubah penilaiannya. */
  terkunci?: boolean;
  saatBerubah?: () => void;
}) {
  const [pilih, setPilih] = useState(0);
  const [nilai, setNilai] = useState<Record<string, Nilai>>(() =>
    nilaiAwal(klaim.foto ?? []),
  );
  const [kirim, setKirim] = useState(false);
  const [pesan, setPesan] = useState("");
  const [galat, setGalat] = useState("");
  const [pratinjau, setPratinjau] = useState(false);
  const [setelan, setSetelan] = useState<Setelan>(SETELAN_AWAL);
  const [instansiMati, setInstansiMati] = useState<string[]>([]);
  const [sorot, setSorot] = useState<string | null>(null);
  const [tanyaBatal, setTanyaBatal] = useState(false);
  // Ukuran asli foto dibaca dari gambarnya sendiri, karena poligonnya dinormalkan dan
  // butuh ukuran untuk digambar ulang dengan perbandingan yang benar.
  const [ukuran, setUkuran] = useState<{ lebar: number; tinggi: number } | null>(null);

  const urutan = klaim.foto?.length
    ? klaim.foto[Math.min(pilih, klaim.foto.length - 1)].urutan
    : null;

  useEffect(() => {
    const simpanan = localStorage.getItem(KUNCI_SETELAN);
    if (!simpanan) return;
    try {
      setSetelan({ ...SETELAN_AWAL, ...JSON.parse(simpanan) });
    } catch {
      // Setelan rusak tidak boleh membuat halamannya gagal terbuka.
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(KUNCI_SETELAN, JSON.stringify(setelan));
  }, [setelan]);

  useEffect(() => {
    if (urutan === null) return;
    setUkuran(null);
    // Penanda instance berbasis urutan, jadi tidak berlaku lagi begitu fotonya berganti.
    setInstansiMati([]);
    setSorot(null);
    const gambar = new Image();
    gambar.onload = () => setUkuran({ lebar: gambar.naturalWidth, tinggi: gambar.naturalHeight });
    gambar.src = alamatFoto(klaim.id, urutan, "kerusakan");
  }, [klaim.id, urutan]);

  if (!klaim.foto?.length) return null;

  const foto = klaim.foto[Math.min(pilih, klaim.foto.length - 1)];
  const nomor = Math.min(pilih, klaim.foto.length - 1);

  function pindahFoto(arah: number) {
    const i = nomor + arah;
    if (i >= 0 && i < klaim.foto.length) setPilih(i);
  }
  // Backend versi lama mengirim temuan tanpa penanda. Tanpa penanda, tiap pilihan akan
  // menimpa pilihan baris lain dan penyimpanannya pasti gagal, jadi lebih baik tidak
  // ditampilkan sama sekali daripada terlihat jalan padahal tidak.
  const punyaPenanda = klaim.foto.every((f) => f.temuan.every((t) => t.id));
  const bolehNilai = untuk === "adjuster" && punyaPenanda;
  const sudahDinilai = klaim.foto.some((f) => f.temuan.some((t) => t.review));
  // Yang sudah disimpan dikunci supaya tidak berubah tanpa sengaja. Untuk mengubahnya,
  // penilaiannya dibatalkan lebih dulu, dan pembatalan itu tercatat di audit.
  const matikan = sudahDinilai || terkunci;

  async function batalkan() {
    setGalat("");
    setPesan("");
    setKirim(true);
    try {
      await batalkanReviewDeteksi(klaim.id);
      setTanyaBatal(false);
      saatBerubah?.();
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setKirim(false);
    }
  }

  // Bentuk mask baru tersimpan sejak versi ini, jadi klaim lama tidak punya. Kalau kosong,
  // pratinjaunya memakai gambar overlay yang dibakar di server seperti sebelumnya.
  const bentukPart = foto.bentuk?.part ?? [];
  const bentukDamage = foto.bentuk?.damage ?? [];
  const adaBentuk = bentukPart.length > 0 || bentukDamage.length > 0;

  // Nomor instance diambil dari daftar bentuk yang sama dengan yang digambar, jadi baris
  // tabel dan label di gambarnya selalu menunjuk mask yang sama.
  const nomorPart = nomorSekelas(bentukPart);
  const nomorDamage = nomorSekelas(bentukDamage);
  const nomorDari = (daftar: (number | null)[], urutan?: number | null) =>
    urutan === null || urutan === undefined ? null : (daftar[urutan] ?? null);

  const lapisanNyala = { part: setelan.tampilPart, damage: setelan.tampilDamage };

  function terlihat(lapisan: "part" | "damage", urutan: number, kelas: string) {
    return (
      lapisanNyala[lapisan] &&
      !setelan.kelasMati.includes(kelas) &&
      !instansiMati.includes(idBentuk(lapisan, urutan))
    );
  }

  /** Bentuk yang dinyalakan dari tabel tidak boleh tertahan lapisan atau kelasnya yang
   *  masih mati, kalau tidak centangnya terlihat tidak berfungsi.
   *
   *  Menyalakan lapisan atau kelasnya akan ikut membuka bentuk lain yang tadinya
   *  tersembunyi karena itu, jadi bentuk-bentuk itu disembunyikan sendiri-sendiri supaya
   *  yang muncul cuma yang barusan dicentang.
   */
  function balikBentuk(lapisan: "part" | "damage", urutan: number, kelas: string) {
    const id = idBentuk(lapisan, urutan);
    if (terlihat(lapisan, urutan, kelas)) {
      setInstansiMati((d) => [...d, id]);
      return;
    }

    const daftar = lapisan === "part" ? bentukPart : bentukDamage;
    const tetapMati = daftar
      .map((b, i) => ({ b, i }))
      .filter(
        ({ b, i }) =>
          i !== urutan &&
          !terlihat(lapisan, i, b.kelas) &&
          // Yang tersembunyi karena kelasnya dibiarkan, kelasnya memang tidak disentuh.
          !setelan.kelasMati.includes(b.kelas),
      )
      .map(({ i }) => idBentuk(lapisan, i));

    setSetelan((x) => ({
      ...x,
      tampilPart: lapisan === "part" ? true : x.tampilPart,
      tampilDamage: lapisan === "damage" ? true : x.tampilDamage,
      kelasMati: x.kelasMati.filter((k) => k !== kelas),
    }));
    setInstansiMati((d) => [
      ...new Set([...d.filter((x) => x !== id), ...tetapMati]),
    ]);
  }

  /** Centang di kepala kolom menyalakan atau mematikan seluruh lapisannya, termasuk
   *  bentuk yang tidak punya baris di tabel karena tidak ada kerusakannya. */
  function semuaLapisan(lapisan: "part" | "damage", nyala: boolean) {
    const daftar = lapisan === "part" ? bentukPart : bentukDamage;
    const kelas = new Set(daftar.map((b) => b.kelas));
    const id = new Set(daftar.map((_, i) => idBentuk(lapisan, i)));
    setSetelan((x) => ({
      ...x,
      tampilPart: lapisan === "part" ? nyala : x.tampilPart,
      tampilDamage: lapisan === "damage" ? nyala : x.tampilDamage,
      kelasMati: nyala ? x.kelasMati.filter((k) => !kelas.has(k)) : x.kelasMati,
    }));
    if (nyala) setInstansiMati((d) => d.filter((x) => !id.has(x)));
  }

  /** Kepala kolom dengan centang penyalur untuk seluruh lapisannya. */
  function kepalaLapisan(lapisan: "part" | "damage", teks: string) {
    const daftar = lapisan === "part" ? bentukPart : bentukDamage;
    if (!adaBentuk || daftar.length === 0) return teks;
    const nyala = daftar.filter((b, i) => terlihat(lapisan, i, b.kelas)).length;
    return (
      <label className="pilih-bentuk">
        <input
          type="checkbox"
          checked={nyala === daftar.length}
          // Setengah tercentang saat sebagian saja yang mati, supaya keadaannya tidak
          // terbaca seolah semuanya sudah mati.
          ref={(el) => {
            if (el) el.indeterminate = nyala > 0 && nyala < daftar.length;
          }}
          onChange={(e) => semuaLapisan(lapisan, e.target.checked)}
        />
        <span>{teks}</span>
      </label>
    );
  }

  /** Nama bentuk beserta centang untuk menyembunyikannya dari gambar. Klaim lama tidak
   *  punya nomor mask, jadi namanya ditampilkan apa adanya tanpa centang. */
  function selBentuk(
    lapisan: "part" | "damage",
    urutan: number | null | undefined,
    kelas: string,
    teks: string,
  ) {
    if (urutan === null || urutan === undefined || !adaBentuk) return teks;
    return (
      <label className="pilih-bentuk">
        <input
          type="checkbox"
          checked={terlihat(lapisan, urutan, kelas)}
          onChange={() => balikBentuk(lapisan, urutan, kelas)}
        />
        <span>{teks}</span>
      </label>
    );
  }

  const urutanOverlay = foto.urutan_overlay;

  const panelPratinjau = [
    {
      judul: "Foto asli",
      alamat: alamatFoto(klaim.id, foto.urutan, "kerusakan"),
      keterangan: `Foto kerusakan nomor ${foto.urutan + 1}`,
    },
    ...(foto.ada_overlay
      ? [
          adaBentuk && ukuran
            ? {
                judul: "Prediksi AI",
                keterangan: `Hasil deteksi pada foto nomor ${foto.urutan + 1}`,
                isi: (
                  <OverlayVektor
                    alamat={alamatFoto(klaim.id, foto.urutan, "kerusakan")}
                    lebar={ukuran.lebar}
                    tinggi={ukuran.tinggi}
                    part={bentukPart}
                    damage={bentukDamage}
                    setelan={setelan}
                    instansiMati={instansiMati}
                    sorot={sorot}
                  />
                ),
              }
            : {
                judul: "Prediksi AI",
                alamat: alamatFoto(klaim.id, urutanOverlay ?? foto.urutan, "overlay"),
                keterangan: `Hasil deteksi pada foto nomor ${foto.urutan + 1}`,
              },
        ]
      : []),
  ];

  async function simpan() {
    setKirim(true);
    setPesan("");
    setGalat("");
    try {
      const hasil = await kirimReviewDeteksi(
        klaim.id,
        Object.entries(nilai).map(([temuan_id, n]) => ({
          temuan_id,
          benar: n === "benar",
          alasan: n === "benar" ? null : n,
        })),
      );
      const salah = Object.values(nilai).filter((n) => n !== "benar").length;
      setPesan(
        `${hasil.dinilai} temuan tersimpan, ${salah} ditandai salah. ` +
          "Angkanya masuk ke halaman Overview.",
      );
      // Induknya perlu memuat ulang klaim, kalau tidak penanda sudah dinilai tidak ikut
      // berubah dan panelnya tidak pernah terkunci.
      saatBerubah?.();
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setKirim(false);
    }
  }

  return (
    <div className="kartu">
      <h2>Hasil Deteksi pada Foto</h2>

      <div
        className="kepala-kartu"
        style={{ marginBottom: 6, justifyContent: "flex-end" }}
      >
        <div className="alat-foto">
          {klaim.foto.length > 1 && (
            <>
              <button
                className="sekunder pindah-gambar"
                onClick={() => pindahFoto(-1)}
                disabled={nomor === 0}
                aria-label="Foto sebelumnya"
                title="Foto sebelumnya"
              >
                <IkonPanah arah="kiri" />
              </button>
              <span className="redup">
                {nomor + 1} dari {klaim.foto.length}
              </span>
              <button
                className="sekunder pindah-gambar"
                onClick={() => pindahFoto(1)}
                disabled={nomor === klaim.foto.length - 1}
                aria-label="Foto berikutnya"
                title="Foto berikutnya"
              >
                <IkonPanah arah="kanan" />
              </button>
            </>
          )}
          <button className="sekunder" onClick={() => setPratinjau(true)}>
            Perbesar dan bandingkan
          </button>
        </div>
      </div>

      <div className="pasangan-foto">
        <figure>
          <figcaption>Foto asli</figcaption>
          <img
            src={alamatFoto(klaim.id, foto.urutan, "kerusakan")}
            alt={`Foto kerusakan nomor ${foto.urutan + 1}`}
            onClick={() => setPratinjau(true)}
          />
        </figure>
        {foto.ada_overlay && (
          <figure onClick={() => setPratinjau(true)}>
            <figcaption>Prediksi AI</figcaption>
            {adaBentuk && ukuran ? (
              <OverlayVektor
                alamat={alamatFoto(klaim.id, foto.urutan, "kerusakan")}
                lebar={ukuran.lebar}
                tinggi={ukuran.tinggi}
                part={bentukPart}
                damage={bentukDamage}
                setelan={setelan}
                instansiMati={instansiMati}
              />
            ) : (
              <img
                src={alamatFoto(klaim.id, urutanOverlay ?? foto.urutan, "overlay")}
                alt={`Hasil deteksi pada foto nomor ${foto.urutan + 1}`}
              />
            )}
          </figure>
        )}
      </div>

      <p className="petunjuk" style={{ margin: "10px 0 16px" }}>
        {PENGANTAR[untuk]}
      </p>

      {klaim.foto.length > 1 && (
        <div className="pemilih-foto">
          {klaim.foto.map((f, i) => (
            <button
              key={f.urutan}
              className={i === pilih ? "aktif" : ""}
              onClick={() => setPilih(i)}
            >
              Foto {i + 1}
            </button>
          ))}
        </div>
      )}

      {foto.temuan.length > 0 ? (
        <div className="gulir">
          <table>
            <thead>
              <tr>
                <th>{kepalaLapisan("part", "Bagian mobil")}</th>
                <th>{kepalaLapisan("damage", "Kerusakan")}</th>
                <th>Luas kerusakan</th>
                <th className="angka">Confidence bagian mobil</th>
                <th className="angka">Confidence kerusakan</th>
                {bolehNilai && <th>Deteksinya benar?</th>}
              </tr>
            </thead>
            <tbody>
              {foto.temuan.map((t, i) => (
                <tr key={i}>
                  <td>
                    {selBentuk(
                      "part",
                      t.part_urutan,
                      t.part_class,
                      labelBagian(
                        t.part_class,
                        t.sisi,
                        nomorDari(nomorPart, t.part_urutan),
                      ),
                    )}
                  </td>
                  <td>
                    {t.damage_class
                      ? selBentuk(
                          "damage",
                          t.damage_urutan,
                          t.damage_class,
                          namaSekelas(
                            t.damage_class,
                            nomorDari(nomorDamage, t.damage_urutan),
                          ),
                        )
                      : "-"}
                  </td>
                  <td>
                    {t.sebaran ? `${t.sebaran} (${persen(t.rasio_luas)})` : "-"}
                  </td>
                  <td className="angka">{persen(t.confidence_part, 0)}</td>
                  <td className="angka">{persen(t.confidence_damage, 0)}</td>
                  {bolehNilai && (
                    <td>
                      <select
                        value={nilai[t.id] ?? "benar"}
                        disabled={matikan}
                        onChange={(e) =>
                          setNilai({ ...nilai, [t.id]: e.target.value as Nilai })
                        }
                      >
                        <option value="benar">Benar</option>
                        {Object.entries(ALASAN).map(([kode, { awalan, teks }]) => (
                          <option key={kode} value={kode}>
                            {awalan}: {teks}
                          </option>
                        ))}
                      </select>
                      {!t.review && t.usulan && (
                        <div className="redup" style={{ fontSize: 12, marginTop: 4 }}>
                          Diusulkan sistem, cocok dengan {t.usulan.klaim_lama} (
                          {persen(t.usulan.rasio_dulu)})
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="redup">Tidak ada kerusakan yang terdeteksi di foto ini.</p>
      )}

      {bolehNilai && (
        <div className="nilai-deteksi">
          {sudahDinilai && (
            <p className="redup">
              Penilaian klaim ini sudah tersimpan dan dikunci. Batalkan dulu kalau mau
              mengubahnya.
            </p>
          )}
          {sudahDinilai ? (
            <button
              className="sekunder"
              onClick={() => setTanyaBatal(true)}
              disabled={kirim || terkunci}
              title={
                terkunci
                  ? "Klaim ini sudah diputuskan. Batalkan keputusannya lebih dulu."
                  : undefined
              }
            >
              {kirim ? "Membatalkan..." : "Batalkan penilaian deteksi"}
            </button>
          ) : (
            <button onClick={simpan} disabled={kirim}>
              {kirim ? "Menyimpan..." : "Simpan penilaian deteksi"}
            </button>
          )}
          {pesan && <p className="berhasil">{pesan}</p>}
          {galat && <div className="galat">{galat}</div>}
        </div>
      )}

      {untuk === "adjuster" && !punyaPenanda && (
        <p className="redup" style={{ marginTop: 12 }}>
          Penilaian ketepatan deteksi belum bisa dipakai untuk klaim ini karena
          temuannya dibuat sebelum penanda temuan ada. Kirim ulang klaimnya
          setelah backend dijalankan ulang.
        </p>
      )}

      {pratinjau && (
        <PratinjauFoto
          panel={panelPratinjau}
          saatTutup={() => setPratinjau(false)}
          saatSebelum={nomor > 0 ? () => pindahFoto(-1) : undefined}
          saatSesudah={
            nomor < klaim.foto.length - 1 ? () => pindahFoto(1) : undefined
          }
          alat={
            adaBentuk ? (
              <AturOverlay
                setelan={setelan}
                saatUbah={(bagian) => setSetelan((x) => ({ ...x, ...bagian }))}
                part={bentukPart}
                damage={bentukDamage}
                instansiMati={instansiMati}
                saatUbahInstansi={setInstansiMati}
                saatSorot={setSorot}
              />
            ) : undefined
          }
        />
      )}

      {/* Menghapus penilaian membuang jejak yang sudah masuk hitungan ketepatan model,
          jadi wajib lewat satu langkah tegas. */}
      {tanyaBatal && (
        <div
          className="tirai"
          role="dialog"
          aria-modal="true"
          aria-label="Konfirmasi pembatalan penilaian"
        >
          <div className="dialog">
            <h2>Batalkan penilaian deteksi klaim {klaim.nomor_klaim}?</h2>
            <p>
              Seluruh penilaian yang sudah tersimpan untuk klaim ini dihapus, dan angkanya ikut keluar dari ketepatan deteksi di halaman Overview. Klaim ini tidak bisa diputuskan lagi sampai penilaiannya diisi ulang. Pembatalan ini tercatat di jejak audit atas nama akun Anda.
            </p>
            {galat && <div className="galat">{galat}</div>}
            <div className="tombol-dialog">
              <button
                type="button"
                className="sekunder"
                onClick={() => setTanyaBatal(false)}
                disabled={kirim}
              >
                Tidak jadi
              </button>
              <button
                type="button"
                className="bahaya"
                onClick={batalkan}
                disabled={kirim}
              >
                {kirim ? "Membatalkan..." : "Ya, batalkan"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
