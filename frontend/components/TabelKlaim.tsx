"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { hapusKlaim, type RingkasanKlaim } from "@/lib/api";
import { IZIN, punyaIzin } from "@/lib/auth";
import {
  labelRekomendasi,
  labelStatus,
  persen,
  rupiah,
  waktu,
  warnaStatus,
} from "@/lib/format";

/** Kolom bernilai sedikit dan berulang disaring lewat daftar centang. Kolom bernilai unik
 *  hampir tiap baris, seperti nomor klaim, disaring lewat kotak ketik, karena daftar
 *  centang sepanjang jumlah barisnya tidak menolong siapa pun. */
const FACET = [
  { kunci: "surveyor", judul: "Pengirim" },
  { kunci: "pemegang_polis", judul: "Pemegang polis" },
  { kunci: "kendaraan", judul: "Kendaraan" },
  { kunci: "tahun_kendaraan", judul: "Tahun" },
  { kunci: "verdict_validitas", judul: "Validitas" },
  { kunci: "rekomendasi", judul: "Rekomendasi" },
  { kunci: "status", judul: "Status" },
] as const;

type KunciFacet = (typeof FACET)[number]["kunci"];
type KunciUrut = "total_biaya" | "dibuat";
type Arah = "naik" | "turun";
type Pilihan = Partial<Record<KunciFacet, string[]>>;

const JUDUL: Record<KunciFacet, string> = Object.fromEntries(
  FACET.map((f) => [f.kunci, f.judul]),
) as Record<KunciFacet, string>;

function tampilan(k: RingkasanKlaim, kunci: KunciFacet): string {
  const nilai = k[kunci];
  if (nilai === null || nilai === undefined || nilai === "") return "(kosong)";
  if (kunci === "rekomendasi") return labelRekomendasi(nilai as string);
  if (kunci === "status") return labelStatus(nilai as string);
  // Pengirim disaring memakai nama tampilannya, sama seperti yang terbaca di barisnya.
  if (kunci === "surveyor") return k.nama_surveyor || String(nilai);
  return String(nilai);
}

/** Tanggal WIB dalam bentuk yyyy-mm-dd, sama seperti isian tanggal di penyaring.
 *  Waktunya disimpan UTC, jadi memotong sepuluh huruf pertama akan salah sehari untuk
 *  klaim yang masuk sore ke atas. */
function tanggalWib(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta" });
}

function cocokTanggal(k: RingkasanKlaim, dari: string, sampai: string): boolean {
  if (!dari && !sampai) return true;
  if (!k.dibuat) return false;
  const tanggal = tanggalWib(k.dibuat);
  if (dari && tanggal < dari) return false;
  // Batas atas ikut disertakan, karena "sampai 17 Agustus" secara umum dibaca termasuk
  // hari itu, bukan sampai tengah malam sebelumnya.
  if (sampai && tanggal > sampai) return false;
  return true;
}

/** Menu penyaring yang menempel di judul kolomnya.
 *
 *  Panelnya dipasang dengan posisi fixed dan koordinat diukur dari tombolnya, bukan
 *  posisi absolut biasa. Tabel dibungkus wadah yang bisa digeser mendatar, dan wadah
 *  semacam itu memotong apa pun yang keluar dari batasnya. */
function MenuKolom({
  judul,
  aktif,
  children,
}: {
  judul: string;
  aktif: boolean;
  children: () => React.ReactNode;
}) {
  const [buka, setBuka] = useState(false);
  const [posisi, setPosisi] = useState({ atas: 0, kiri: 0 });
  const tombol = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!buka) return;
    function luar(e: MouseEvent) {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !tombol.current?.contains(t)) setBuka(false);
    }
    function esc(e: KeyboardEvent) {
      if (e.key === "Escape") setBuka(false);
    }
    document.addEventListener("mousedown", luar);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", luar);
      document.removeEventListener("keydown", esc);
    };
  }, [buka]);

  function balik() {
    const kotak = tombol.current?.getBoundingClientRect();
    if (kotak) {
      // Panel digeser ke kiri kalau kolomnya dekat tepi kanan layar, supaya tidak
      // sebagian keluar layar dan isinya terpotong.
      const kiri = Math.min(kotak.left, window.innerWidth - 280);
      setPosisi({ atas: kotak.bottom + 4, kiri: Math.max(8, kiri) });
    }
    setBuka(!buka);
  }

  return (
    <>
      <button
        ref={tombol}
        type="button"
        className={`saring-kolom${aktif ? " aktif" : ""}`}
        onClick={balik}
        aria-expanded={buka}
        aria-label={`Saring ${judul}`}
        title={`Saring ${judul}`}
      >
        <span aria-hidden="true">{aktif ? "▼" : "▽"}</span>
      </button>

      {buka && (
        <div
          ref={panel}
          className="panel-kolom"
          style={{ top: posisi.atas, left: posisi.kiri }}
          role="group"
          aria-label={`Saring ${judul}`}
        >
          {children()}
        </div>
      )}
    </>
  );
}

export default function TabelKlaim({
  klaim,
  ringkas = false,
  saatHapus,
}: {
  klaim: RingkasanKlaim[];
  /** Dipanggil setelah satu klaim terhapus, supaya halamannya memuat ulang datanya. */
  saatHapus?: () => void;
  /** Bentuk ringkas dipakai di halaman Overview: kolom yang sudah terwakili grafik di
   *  atasnya disembunyikan, penyaring kolom yang tersisa tetap ada. */
  ringkas?: boolean;
}) {
  const [nomor, setNomor] = useState("");
  const [pilihan, setPilihan] = useState<Pilihan>({});
  const [dari, setDari] = useState("");
  const [sampai, setSampai] = useState("");
  const [urut, setUrut] = useState<{ kunci: KunciUrut; arah: Arah }>({
    kunci: "dibuat",
    arah: "turun",
  });
  const [akanDihapus, setAkanDihapus] = useState<RingkasanKlaim | null>(null);
  const [menghapus, setMenghapus] = useState(false);
  const [galatHapus, setGalatHapus] = useState("");

  // Hak dibaca sekali setelah komponen terpasang. Membacanya saat render pertama membuat
  // hasil server dan hasil browser berbeda, dan React menolak itu.
  const [bolehHapus, setBolehHapus] = useState(false);
  useEffect(() => setBolehHapus(punyaIzin(IZIN.klaimHapus)), []);

  async function jalankanHapus() {
    if (!akanDihapus) return;
    setMenghapus(true);
    setGalatHapus("");
    try {
      await hapusKlaim(akanDihapus.id);
      setAkanDihapus(null);
      saatHapus?.();
    } catch (e) {
      setGalatHapus((e as Error).message);
    } finally {
      setMenghapus(false);
    }
  }

  const facetDipakai = ringkas
    ? FACET.filter((f) => f.kunci !== "pemegang_polis")
    : FACET;

  /** Baris yang lolos semua penyaring kecuali satu kolom. Dipakai menghitung angka di
   *  daftar centang, supaya angkanya mencerminkan pilihan lain yang sedang aktif. */
  function lolosKecuali(kecuali: KunciFacet | null): RingkasanKlaim[] {
    const cari = nomor.trim().toLowerCase();
    return klaim.filter(
      (k) =>
        (!cari || k.nomor_klaim.toLowerCase().includes(cari)) &&
        cocokTanggal(k, dari, sampai) &&
        facetDipakai.every(({ kunci }) => {
          if (kunci === kecuali) return true;
          const dipilih = pilihan[kunci];
          return !dipilih?.length || dipilih.includes(tampilan(k, kunci));
        }),
    );
  }

  const baris = useMemo(() => {
    const arah = urut.arah === "naik" ? 1 : -1;
    return [...lolosKecuali(null)].sort((a, b) => {
      // Total biaya datang sebagai teks karena angkanya desimal presisi tetap, jadi harus
      // diubah ke angka dulu supaya 7,200,000 tidak terurut di atas 74,250,000.
      const kiri =
        urut.kunci === "total_biaya" ? Number(a.total_biaya ?? 0) : (a.dibuat ?? "");
      const kanan =
        urut.kunci === "total_biaya" ? Number(b.total_biaya ?? 0) : (b.dibuat ?? "");
      if (kiri === kanan) return 0;
      return kiri > kanan ? arah : -arah;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [klaim, nomor, pilihan, dari, sampai, urut]);

  const cip = useMemo(() => {
    const hasil: { teks: string; hapus: () => void }[] = [];
    if (nomor.trim())
      hasil.push({ teks: `Nomor klaim: ${nomor.trim()}`, hapus: () => setNomor("") });
    for (const { kunci, judul } of facetDipakai) {
      for (const v of pilihan[kunci] ?? []) {
        hasil.push({
          teks: `${judul}: ${v}`,
          hapus: () =>
            setPilihan((p) => ({
              ...p,
              [kunci]: (p[kunci] ?? []).filter((x) => x !== v),
            })),
        });
      }
    }
    if (dari) hasil.push({ teks: `Klaim dari ${dari}`, hapus: () => setDari("") });
    if (sampai) hasil.push({ teks: `Klaim sampai ${sampai}`, hapus: () => setSampai("") });
    return hasil;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nomor, pilihan, dari, sampai]);

  function hapusSemua() {
    setNomor("");
    setPilihan({});
    setDari("");
    setSampai("");
  }

  function balikUrut(kunci: KunciUrut) {
    setUrut((s) =>
      s.kunci === kunci
        ? { kunci, arah: s.arah === "naik" ? "turun" : "naik" }
        : { kunci, arah: "turun" },
    );
  }

  function JudulUrut({ kunci, judul }: { kunci: KunciUrut; judul: string }) {
    const aktif = urut.kunci === kunci;
    return (
      <button
        type="button"
        className={`urut${aktif ? " aktif" : ""}`}
        onClick={() => balikUrut(kunci)}
        title={`Urutkan menurut ${judul.toLowerCase()}`}
      >
        {judul}
        <span aria-hidden="true">{aktif ? (urut.arah === "naik" ? "↑" : "↓") : "⇅"}</span>
      </button>
    );
  }

  /** Judul kolom yang penyaringnya berupa daftar centang. */
  function KolomFacet({ kunci }: { kunci: KunciFacet }) {
    const terpilih = pilihan[kunci] ?? [];
    const hitungan = new Map<string, number>();
    for (const k of lolosKecuali(kunci)) {
      const label = tampilan(k, kunci);
      hitungan.set(label, (hitungan.get(label) ?? 0) + 1);
    }
    const nilai = [...hitungan].sort((a, b) => a[0].localeCompare(b[0]));

    function balik(label: string) {
      setPilihan({
        ...pilihan,
        [kunci]: terpilih.includes(label)
          ? terpilih.filter((v) => v !== label)
          : [...terpilih, label],
      });
    }

    return (
      <th className={terpilih.length ? "tersaring" : ""}>
        <span className="judul-kolom">
          {JUDUL[kunci]}
          <MenuKolom judul={JUDUL[kunci]} aktif={terpilih.length > 0}>
            {() => (
              <>
                {nilai.map(([label, jumlah]) => (
                  <label key={label}>
                    <input
                      type="checkbox"
                      checked={terpilih.includes(label)}
                      onChange={() => balik(label)}
                    />
                    <span className="teks">{label}</span>
                    <span className="redup">{jumlah}</span>
                  </label>
                ))}
                {terpilih.length > 0 && (
                  <button
                    type="button"
                    className="bersih"
                    onClick={() => setPilihan({ ...pilihan, [kunci]: [] })}
                  >
                    Bersihkan
                  </button>
                )}
              </>
            )}
          </MenuKolom>
        </span>
      </th>
    );
  }

  return (
    <>
      {/* Penyaring yang sedang aktif selalu terlihat sebagai label yang bisa dilepas satu
          per satu. Tabel tersaring yang terlihat seperti tabel utuh membuat orang salah
          membaca datanya. */}
      {cip.length > 0 && (
        <div className="cip-saring">
          <span className="redup">
            {baris.length} dari {klaim.length} klaim
          </span>
          {cip.map((c) => (
            <button key={c.teks} type="button" className="cip" onClick={c.hapus}>
              {c.teks}
              <span aria-hidden="true">×</span>
            </button>
          ))}
          <button type="button" className="tautan" onClick={hapusSemua}>
            Hapus semua
          </button>
        </div>
      )}

      <div className="gulir">
        <table className="tabel-saring">
          <thead>
            <tr>
              <th className={nomor.trim() ? "tersaring" : ""}>
                <span className="judul-kolom">
                  Nomor klaim
                  <MenuKolom judul="Nomor klaim" aktif={Boolean(nomor.trim())}>
                    {() => (
                      <div className="isian-panel">
                        <input
                          type="search"
                          autoFocus
                          placeholder="Ketik sebagian nomor"
                          value={nomor}
                          onChange={(e) => setNomor(e.target.value)}
                        />
                      </div>
                    )}
                  </MenuKolom>
                </span>
              </th>

              <KolomFacet kunci="surveyor" />
              {!ringkas && <KolomFacet kunci="pemegang_polis" />}
              <KolomFacet kunci="kendaraan" />
              <KolomFacet kunci="tahun_kendaraan" />
              <KolomFacet kunci="verdict_validitas" />
              <KolomFacet kunci="rekomendasi" />

              <th className="angka">
                <JudulUrut kunci="total_biaya" judul="Total biaya" />
              </th>
              <th className="angka">Bekas</th>
              {!ringkas && <th className="angka">Rasio</th>}

              <KolomFacet kunci="status" />

              <th className={dari || sampai ? "tersaring" : ""}>
                <span className="judul-kolom">
                  <JudulUrut kunci="dibuat" judul="Tanggal klaim" />
                  <MenuKolom judul="Tanggal klaim" aktif={Boolean(dari || sampai)}>
                    {() => (
                      <div className="isian-panel">
                        <label>
                          Dari
                          <input
                            type="date"
                            value={dari}
                            onChange={(e) => setDari(e.target.value)}
                          />
                        </label>
                        <label>
                          Sampai
                          <input
                            type="date"
                            value={sampai}
                            min={dari || undefined}
                            onChange={(e) => setSampai(e.target.value)}
                          />
                        </label>
                        {(dari || sampai) && (
                          <button
                            type="button"
                            className="bersih"
                            onClick={() => {
                              setDari("");
                              setSampai("");
                            }}
                          >
                            Bersihkan
                          </button>
                        )}
                      </div>
                    )}
                  </MenuKolom>
                </span>
              </th>
              {bolehHapus && <th className="aksi" aria-label="Hapus" />}
            </tr>
          </thead>
          <tbody>
            {baris.map((k) => (
              <tr key={k.id}>
                <td>
                  {k.status === "diproses" ? (
                    <span className="redup" title="Klaim masih diproses, rinciannya belum ada">
                      {k.nomor_klaim}
                    </span>
                  ) : k.status === "menunggu_foto_tambahan" ? (
                    <span
                      className="redup"
                      title="Klaim menunggu foto tambahan dari surveyor, belum bisa direview"
                    >
                      {k.nomor_klaim}
                    </span>
                  ) : (
                    <Link href={`/adjuster/${k.id}`}>{k.nomor_klaim}</Link>
                  )}
                  {k.contoh_demo && <span className="lencana abu">contoh</span>}
                </td>
                <td>
                  {k.nama_surveyor || k.surveyor || "-"}
                  {k.nama_surveyor && <div className="redup">{k.surveyor}</div>}
                </td>
                {!ringkas && <td>{k.pemegang_polis}</td>}
                <td>{k.kendaraan}</td>
                <td>{k.tahun_kendaraan ?? "-"}</td>
                <td>{k.verdict_validitas ?? "-"}</td>
                <td>{labelRekomendasi(k.rekomendasi)}</td>
                <td className="angka">{rupiah(k.total_biaya)}</td>
                <td className="angka">{rupiah(k.harga_pasar_bekas)}</td>
                {!ringkas && <td className="angka">{persen(k.total_loss_ratio)}</td>}
                <td>
                  <span className={`lencana ${warnaStatus(k.status)}`}>
                    {labelStatus(k.status)}
                  </span>
                </td>
                <td>{waktu(k.dibuat)}</td>
                {bolehHapus && (
                  <td className="aksi">
                    <button
                      type="button"
                      className="hapus"
                      onClick={() => {
                        setGalatHapus("");
                        setAkanDihapus(k);
                      }}
                      aria-label={`Hapus klaim ${k.nomor_klaim}`}
                      title={`Hapus klaim ${k.nomor_klaim}`}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Penghapusan tidak bisa dibatalkan, jadi wajib lewat satu langkah tegas. Nomor
          klaimnya ditulis di dalam pertanyaan supaya jelas yang mana yang akan hilang. */}
      {akanDihapus && (
        <div className="tirai" role="dialog" aria-modal="true" aria-label="Konfirmasi hapus">
          <div className="dialog">
            <h2>Hapus klaim {akanDihapus.nomor_klaim}?</h2>
            <p>
              Foto, hasil deteksi, hitungan biaya, keputusan, dan jejak auditnya ikut
              terhapus. Ini tidak bisa dibatalkan.
            </p>
            {galatHapus && <div className="galat">{galatHapus}</div>}
            <div className="tombol-dialog">
              <button
                type="button"
                className="sekunder"
                onClick={() => setAkanDihapus(null)}
                disabled={menghapus}
              >
                Batal
              </button>
              <button
                type="button"
                className="bahaya"
                onClick={jalankanHapus}
                disabled={menghapus}
              >
                {menghapus ? "Menghapus..." : "Ya, hapus"}
              </button>
            </div>
          </div>
        </div>
      )}

      {baris.length === 0 && (
        <p className="redup" style={{ marginTop: 12 }}>
          Tidak ada klaim yang cocok dengan penyaring ini.{" "}
          <button type="button" className="tautan" onClick={hapusSemua}>
            Hapus semua penyaring
          </button>
        </p>
      )}
    </>
  );
}
