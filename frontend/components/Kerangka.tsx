"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import IkonPanah from "@/components/IkonPanah";
import { ubahSandiSendiri } from "@/lib/api";
import { ambilSesi, halamanAwal, hapusSesi, IZIN, type Sesi } from "@/lib/auth";

type Menu = { alamat: string; label: string; izin: string };

// Menu ditentukan hak, bukan nama peran, supaya peran buatan sendiri dari layar
// Manajemen Akses langsung mendapat menu yang sesuai tanpa mengubah kode.
const MENU: Menu[] = [
  { alamat: "/overview", label: "Overview", izin: IZIN.overviewLihat },
  { alamat: "/adjuster", label: "Daftar Klaim", izin: IZIN.klaimLihat },
  { alamat: "/surveyor", label: "Ajukan Klaim", izin: IZIN.klaimKirim },
  { alamat: "/klaim-saya", label: "Klaim Saya", izin: IZIN.klaimLacak },
  { alamat: "/akses", label: "Manajemen Akses", izin: IZIN.aksesKelola },
  { alamat: "/demo", label: "Demo", izin: IZIN.aksesKelola },
];

// Halaman Demo alat bantu memilih foto, bukan bagian produk. Menunya disembunyikan supaya
// penonton demo tidak melihat sesuatu yang perlu dijelaskan.
const KUNCI_DEMO = "menu_demo";

// Sidebar yang ditutup bertahan antar halaman, supaya tabel lebar tetap lega setelah pindah
// menu tanpa perlu menutupnya lagi tiap kali.
const KUNCI_SISI = "sisi_tutup";

function DialogSandi({ tutup }: { tutup: () => void }) {
  const [lama, setLama] = useState("");
  const [baru, setBaru] = useState("");
  const [ulang, setUlang] = useState("");
  const [galat, setGalat] = useState("");
  const [mengirim, setMengirim] = useState(false);
  const [berhasil, setBerhasil] = useState(false);

  const cocok = baru.length > 0 && baru === ulang;

  async function simpan() {
    setMengirim(true);
    setGalat("");
    try {
      await ubahSandiSendiri(lama, baru);
      setBerhasil(true);
    } catch (e) {
      setGalat((e as Error).message);
    } finally {
      setMengirim(false);
    }
  }

  return (
    <div className="tirai" role="dialog" aria-modal="true" aria-label="Ubah kata sandi">
      <div className="dialog">
        <h2>Ubah kata sandi</h2>

        {berhasil ? (
          <>
            <p>Kata sandi sudah diganti. Pakai yang baru saat masuk berikutnya.</p>
            <div className="tombol-dialog">
              <button type="button" onClick={tutup}>
                Tutup
              </button>
            </div>
          </>
        ) : (
          <>
            {galat && <div className="galat">{galat}</div>}

            <label htmlFor="sandi-lama">Kata sandi lama</label>
            <input
              id="sandi-lama"
              type="password"
              value={lama}
              onChange={(e) => setLama(e.target.value)}
            />

            <label htmlFor="sandi-baru">Kata sandi baru</label>
            <input
              id="sandi-baru"
              type="password"
              value={baru}
              onChange={(e) => setBaru(e.target.value)}
            />

            <label htmlFor="sandi-ulang">Ulangi kata sandi baru</label>
            <input
              id="sandi-ulang"
              type="password"
              value={ulang}
              onChange={(e) => setUlang(e.target.value)}
            />
            {ulang.length > 0 && !cocok && (
              <p className="redup">Ulangan sandinya belum sama.</p>
            )}

            <div className="tombol-dialog">
              <button type="button" className="sekunder" onClick={tutup} disabled={mengirim}>
                Batal
              </button>
              <button type="button" onClick={simpan} disabled={!lama || !cocok || mengirim}>
                {mengirim ? "Menyimpan..." : "Simpan"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Kerangka({
  judul,
  keterangan,
  butuh,
  children,
}: {
  judul: string;
  keterangan?: string;
  butuh?: (s: Sesi | null) => boolean;
  children: React.ReactNode;
}) {
  const [sesi, setSesi] = useState<Sesi | null>(null);
  const [siap, setSiap] = useState(false);
  const [ubahSandi, setUbahSandi] = useState(false);
  const [menuDemo, setMenuDemo] = useState(false);
  const [sisiTutup, setSisiTutup] = useState(false);

  // Dibaca setelah komponen terpasang, bukan saat render pertama, supaya hasil server dan
  // hasil browser tidak berbeda.
  useEffect(() => {
    setMenuDemo(localStorage.getItem(KUNCI_DEMO) === "1");
    setSisiTutup(localStorage.getItem(KUNCI_SISI) === "1");
  }, []);

  function balikMenuDemo(nyala: boolean) {
    setMenuDemo(nyala);
    localStorage.setItem(KUNCI_DEMO, nyala ? "1" : "0");
  }

  function balikSisi() {
    const tutup = !sisiTutup;
    setSisiTutup(tutup);
    localStorage.setItem(KUNCI_SISI, tutup ? "1" : "0");
  }
  const router = useRouter();
  const jalur = usePathname();

  useEffect(() => {
    const s = ambilSesi();
    if (!s) {
      router.replace("/login");
      return;
    }
    // Peran yang tidak berhak dipulangkan ke halaman awalnya sendiri. Penolakan yang
    // sebenarnya tetap dikerjakan backend, ini cuma supaya layarnya tidak membingungkan.
    if (butuh && !butuh(s)) {
      router.replace(halamanAwal(s));
      return;
    }
    setSesi(s);
    setSiap(true);
  }, [butuh, router]);

  if (!siap || !sesi) return null;

  function keluar() {
    hapusSesi();
    router.replace("/login");
  }

  return (
    <div className={sisiTutup ? "kerangka sisi-tutup" : "kerangka"}>
      <aside className="sisi">
        <div className="merek">
          <strong>Agentic AI Car Claim</strong>
        </div>

        <ul className="menu">
          {MENU.filter(
            (m) =>
              sesi.izin?.includes(m.izin) && (m.alamat !== "/demo" || menuDemo),
          ).map((m) => (
            <li key={m.alamat}>
              <Link
                href={m.alamat}
                className={jalur.startsWith(m.alamat) ? "aktif" : ""}
              >
                {m.label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="kaki-sisi">
          <div className="nama">{sesi.nama || sesi.username}</div>
          <div className="baris-peran">
            <span className="peran">{sesi.peran}</span>
            {sesi.izin?.includes(IZIN.aksesKelola) && (
              <label className="sakelar-diam">
                <input
                  type="checkbox"
                  checked={menuDemo}
                  onChange={(e) => balikMenuDemo(e.target.checked)}
                  aria-label="Tampilkan menu Demo"
                />
                <span aria-hidden="true" />
              </label>
            )}
          </div>
          <button onClick={() => setUbahSandi(true)}>
            Ubah sandi
          </button>
          <button onClick={keluar}>
            Keluar
          </button>
        </div>
      </aside>

      {/* Di luar aside, karena tombol yang ikut hilang bersama sidebarnya tidak bisa dipakai
          membukanya lagi. */}
      <button
        type="button"
        className="tombol-sisi"
        onClick={balikSisi}
        aria-expanded={!sisiTutup}
        aria-label={sisiTutup ? "Tampilkan menu samping" : "Sembunyikan menu samping"}
        title={sisiTutup ? "Tampilkan menu samping" : "Sembunyikan menu samping"}
      >
        <IkonPanah arah={sisiTutup ? "kanan" : "kiri"} />
      </button>

      <div className="isi">
        <header className="bilah-atas">
          <div>
            <h1>{judul}</h1>
            {keterangan && <div className="keterangan">{keterangan}</div>}
          </div>
        </header>
        <div className="wadah">{children}</div>
      </div>

      {ubahSandi && <DialogSandi tutup={() => setUbahSandi(false)} />}
    </div>
  );
}
