"use client";

// Panel pengatur tampilan overlay. Dipisah jadi komponen sendiri karena hidup di dalam mode
// pratinjau, dan layar lain yang menampilkan hasil deteksi bisa memakainya juga tanpa
// menyalin ulang.

import { useEffect, useMemo, useRef, useState } from "react";
import IkonPanah from "@/components/IkonPanah";
import {
  idBentuk,
  nomorSekelas,
  SETELAN_AWAL,
  type Bentuk,
  type Setelan,
} from "@/components/OverlayVektor";

type Baris = { id: string; bentuk: Bentuk; nomor: number | null };
type Kelompok = { kelas: string; isi: Baris[] };

/** Luas poligon dalam persen luas foto, dipakai membedakan instance yang sekelas. */
function luas(titik: [number, number][]): number {
  let a = 0;
  for (let i = 0; i < titik.length; i++) {
    const [x1, y1] = titik[i];
    const [x2, y2] = titik[(i + 1) % titik.length];
    a += x1 * y2 - x2 * y1;
  }
  return (Math.abs(a) / 2) * 100;
}

function kelompokkan(daftar: Bentuk[], lapisan: "part" | "damage"): Kelompok[] {
  const nomor = nomorSekelas(daftar);
  const peta = new Map<string, Baris[]>();
  daftar.forEach((bentuk, i) => {
    const baris = peta.get(bentuk.kelas) ?? [];
    baris.push({ id: idBentuk(lapisan, i), bentuk, nomor: nomor[i] });
    peta.set(bentuk.kelas, baris);
  });
  // Nomornya ikut jadi urutan tampilan, supaya yang dibaca di daftar sama dengan yang
  // tertulis di gambarnya.
  return [...peta.entries()]
    .map(([kelas, isi]) => ({ kelas, isi }))
    .sort((a, b) => a.kelas.localeCompare(b.kelas));
}

/** Daftar kelas yang bisa dibentangkan sampai ke tiap instance-nya. */
function DaftarKelas({
  judul,
  kelompok,
  kelasMati,
  instansiMati,
  saatBalikKelas,
  saatBalikInstansi,
  saatSemua,
  saatSorot,
}: {
  judul: string;
  kelompok: Kelompok[];
  kelasMati: string[];
  instansiMati: string[];
  saatBalikKelas: (kelas: string, isi: string[], nyala: boolean) => void;
  saatBalikInstansi: (id: string, kelas: string, saudara: string[]) => void;
  saatSemua: (kelas: string[], nyala: boolean) => void;
  saatSorot: (id: string | null) => void;
}) {
  const [buka, setBuka] = useState(false);
  const [terbentang, setTerbentang] = useState<string[]>([]);
  const bungkus = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!buka) return;
    function luarPanel(e: MouseEvent) {
      if (!bungkus.current?.contains(e.target as Node)) setBuka(false);
    }
    document.addEventListener("mousedown", luarPanel);
    return () => document.removeEventListener("mousedown", luarPanel);
  }, [buka]);

  // Sorot dilepas begitu panelnya ditutup, kalau tidak gambarnya tertinggal redup.
  useEffect(() => {
    if (!buka) saatSorot(null);
  }, [buka, saatSorot]);

  const kelas = kelompok.map((k) => k.kelas);
  const total = kelompok.reduce((n, k) => n + k.isi.length, 0);
  const tampil = kelompok.reduce(
    (n, k) =>
      n +
      (kelasMati.includes(k.kelas)
        ? 0
        : k.isi.filter((b) => !instansiMati.includes(b.id)).length),
    0,
  );
  const semuaNyala = total > 0 && tampil === total;

  function bentang(nama: string) {
    setTerbentang((t) => (t.includes(nama) ? t.filter((x) => x !== nama) : [...t, nama]));
  }

  // Kelas berinstance tunggal pun tetap bisa dibentangkan. Barisnya memang mengulang
  // kotak centang kelasnya, tapi di situlah keyakinan, luas, dan sorot ke gambarnya berada.
  const bisaDibentang = kelompok.map((k) => k.kelas);
  const semuaTerbentang =
    bisaDibentang.length > 0 && bisaDibentang.every((k) => terbentang.includes(k));

  return (
    <div className="turun-kelas" ref={bungkus}>
      <button type="button" className="sekunder" onClick={() => setBuka(!buka)}>
        {judul} {tampil}/{total}
        <span aria-hidden="true"> ▾</span>
      </button>

      {buka && (
        <div className="panel-turun" role="group" aria-label={judul}>
          <div className="panel-turun-alat">
            <label>
              <input
                type="checkbox"
                checked={semuaNyala}
                // Setengah tercentang saat sebagian mati, supaya keadaannya tidak terbaca
                // seolah semuanya sudah mati.
                ref={(el) => {
                  if (el) el.indeterminate = tampil > 0 && !semuaNyala;
                }}
                onChange={(e) => saatSemua(kelas, e.target.checked)}
              />
              <span>Select all</span>
            </label>

            {bisaDibentang.length > 0 && (
              <button
                type="button"
                className={`bentang${semuaTerbentang ? " terbuka" : ""}`}
                onClick={() => setTerbentang(semuaTerbentang ? [] : bisaDibentang)}
                aria-expanded={semuaTerbentang}
                title={semuaTerbentang ? "Tutup semua rincian" : "Bentangkan semua rincian"}
                aria-label={
                  semuaTerbentang ? "Tutup semua rincian" : "Bentangkan semua rincian"
                }
              >
                <IkonPanah arah="kanan" />
              </button>
            )}
          </div>

          {kelompok.map((k) => {
            const matiKelas = kelasMati.includes(k.kelas);
            const nyala = matiKelas
              ? 0
              : k.isi.filter((b) => !instansiMati.includes(b.id)).length;
            const dibentang = terbentang.includes(k.kelas);

            return (
              <div key={k.kelas} className="turun-kelompok">
                <div className="turun-kelas-baris">
                  <label>
                    <input
                      type="checkbox"
                      checked={nyala === k.isi.length}
                      ref={(el) => {
                        if (el) el.indeterminate = nyala > 0 && nyala < k.isi.length;
                      }}
                      onChange={() =>
                        saatBalikKelas(
                          k.kelas,
                          k.isi.map((x) => x.id),
                          nyala < k.isi.length,
                        )
                      }
                    />
                    <span>{k.kelas}</span>
                  </label>

                  <button
                    type="button"
                    className={`bentang${dibentang ? " terbuka" : ""}`}
                    onClick={() => bentang(k.kelas)}
                    aria-expanded={dibentang}
                    aria-label={`Rincian ${k.kelas}`}
                  >
                    <span className="jumlah">
                      {nyala}/{k.isi.length}
                    </span>
                    <IkonPanah arah="kanan" />
                  </button>
                </div>

                {dibentang && (
                  <div className="turun-instansi">
                    {k.isi.map((b) => (
                      <label
                        key={b.id}
                        onMouseEnter={() => saatSorot(b.id)}
                        onMouseLeave={() => saatSorot(null)}
                      >
                        <input
                          type="checkbox"
                          checked={!matiKelas && !instansiMati.includes(b.id)}
                          onChange={() =>
                            saatBalikInstansi(b.id, k.kelas, k.isi.map((x) => x.id))
                          }
                        />
                        <span className="nomor">({b.nomor ?? 1})</span>
                        <span>{Math.round(b.bentuk.keyakinan * 100)}%</span>
                        <span className="redup">{luas(b.bentuk.titik).toFixed(1)}% luas</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function AturOverlay({
  setelan,
  saatUbah,
  part,
  damage,
  instansiMati,
  saatUbahInstansi,
  saatSorot,
}: {
  setelan: Setelan;
  saatUbah: (bagian: Partial<Setelan>) => void;
  part: Bentuk[];
  damage: Bentuk[];
  /** Bentuk yang disembunyikan sendiri-sendiri. Berbasis urutan, jadi hanya untuk foto ini. */
  instansiMati: string[];
  saatUbahInstansi: (daftar: string[]) => void;
  saatSorot: (id: string | null) => void;
}) {
  const kelompokPart = useMemo(() => kelompokkan(part, "part"), [part]);
  const kelompokDamage = useMemo(() => kelompokkan(damage, "damage"), [damage]);

  /** Menyalakan kelas memunculkan seluruh instance-nya, termasuk yang tadinya dimatikan
   *  sendiri-sendiri. Tanpa itu, mencentang kelasnya cuma mengembalikan satu bentuk yang
   *  terakhir dicentang, dan centangnya terasa tidak berfungsi. */
  function balikKelas(kelas: string, isi: string[], nyala: boolean) {
    saatUbah({
      kelasMati: nyala
        ? setelan.kelasMati.filter((x) => x !== kelas)
        : [...new Set([...setelan.kelasMati, kelas])],
    });
    if (nyala) saatUbahInstansi(instansiMati.filter((x) => !isi.includes(x)));
  }

  /** Instance yang dinyalakan sendiri tidak boleh tertahan oleh kelasnya yang masih mati. */
  function balikInstansi(id: string, kelas: string, saudara: string[]) {
    if (setelan.kelasMati.includes(kelas)) {
      // Kelasnya ikut dinyalakan, tapi saudaranya dimatikan satu per satu. Tanpa itu,
      // mencentang satu instance saat kelasnya mati akan memunculkan seluruh kelasnya.
      saatUbah({ kelasMati: setelan.kelasMati.filter((x) => x !== kelas) });
      saatUbahInstansi([
        ...instansiMati.filter((x) => !saudara.includes(x)),
        ...saudara.filter((x) => x !== id),
      ]);
      return;
    }
    saatUbahInstansi(
      instansiMati.includes(id)
        ? instansiMati.filter((x) => x !== id)
        : [...instansiMati, id],
    );
  }

  function semuaKelas(daftar: string[], nyala: boolean, kelompok: Kelompok[]) {
    const sisa = setelan.kelasMati.filter((k) => !daftar.includes(k));
    saatUbah({ kelasMati: nyala ? sisa : [...sisa, ...daftar] });
    // Menyalakan semua ikut membersihkan instance yang dimatikan sendiri, kalau tidak
    // "Select all" terasa tidak berfungsi.
    if (nyala) {
      const punya = new Set(kelompok.flatMap((k) => k.isi.map((b) => b.id)));
      saatUbahInstansi(instansiMati.filter((x) => !punya.has(x)));
    }
  }

  return (
    <div className="atur-overlay">
      <div className="atur-kelompok">
        <label className="sakelar-baris">
          <input
            type="checkbox"
            checked={setelan.tampilPart}
            onChange={(e) => saatUbah({ tampilPart: e.target.checked })}
          />
          <span>Bagian mobil</span>
        </label>
        <input
          type="color"
          value={setelan.warnaPart}
          onChange={(e) => saatUbah({ warnaPart: e.target.value })}
          aria-label="Warna bagian mobil"
        />
        <DaftarKelas
          judul="Class"
          kelompok={kelompokPart}
          kelasMati={setelan.kelasMati}
          instansiMati={instansiMati}
          saatBalikKelas={balikKelas}
          saatBalikInstansi={balikInstansi}
          saatSemua={(d, n) => semuaKelas(d, n, kelompokPart)}
          saatSorot={saatSorot}
        />
      </div>

      <div className="atur-kelompok">
        <label className="sakelar-baris">
          <input
            type="checkbox"
            checked={setelan.tampilDamage}
            onChange={(e) => saatUbah({ tampilDamage: e.target.checked })}
          />
          <span>Kerusakan</span>
        </label>
        <input
          type="color"
          value={setelan.warnaDamage}
          onChange={(e) => saatUbah({ warnaDamage: e.target.value })}
          aria-label="Warna kerusakan"
        />
        <DaftarKelas
          judul="Class"
          kelompok={kelompokDamage}
          kelasMati={setelan.kelasMati}
          instansiMati={instansiMati}
          saatBalikKelas={balikKelas}
          saatBalikInstansi={balikInstansi}
          saatSemua={(d, n) => semuaKelas(d, n, kelompokDamage)}
          saatSorot={saatSorot}
        />
      </div>

      <div className="atur-kelompok">
        <label className="sakelar-baris">
          <input
            type="checkbox"
            checked={setelan.tampilLabel}
            onChange={(e) => saatUbah({ tampilLabel: e.target.checked })}
          />
          <span>Label</span>
        </label>

        <label className="sakelar-baris">
          <span>Thickness {setelan.tebal}</span>
          <input
            type="range"
            min={0.5}
            max={6}
            step={0.5}
            value={setelan.tebal}
            onChange={(e) => saatUbah({ tebal: Number(e.target.value) })}
            aria-label="Tebal garis"
          />
        </label>

        <label className="sakelar-baris">
          <span>Fill {Math.round(setelan.kepekatan * 100)}%</span>
          <input
            type="range"
            min={0}
            max={0.6}
            step={0.05}
            value={setelan.kepekatan}
            onChange={(e) => saatUbah({ kepekatan: Number(e.target.value) })}
            aria-label="Kepekatan isian"
          />
        </label>

        <button
          type="button"
          className="sekunder"
          onClick={() => {
            saatUbah(SETELAN_AWAL);
            saatUbahInstansi([]);
          }}
        >
          Reset
        </button>
      </div>
    </div>
  );
}
