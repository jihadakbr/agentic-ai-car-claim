"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Kerangka from "@/components/Kerangka";
import {
  ambilLogAkses,
  ambilPenggunaAkses,
  ambilPeranAkses,
  aturIzinPeran,
  buatPenggunaAkses,
  buatPeranAkses,
  hapusPenggunaAkses,
  hapusPeranAkses,
  resetSandiPengguna,
  ubahPenggunaAkses,
  ubahPeranAkses,
  type BarisLogAkses,
  type KatalogIzin,
  type PenggunaAkses,
  type PeranAkses,
} from "@/lib/api";
import { butuhIzin, IZIN } from "@/lib/auth";
import { waktu } from "@/lib/format";

const TAB = [
  { kunci: "pengguna", label: "Pengguna" },
  { kunci: "peran", label: "Peran" },
  { kunci: "hak", label: "Hak Akses" },
  { kunci: "log", label: "Log Aktivitas" },
] as const;

type KunciTab = (typeof TAB)[number]["kunci"];

const NAMA_AKSI: Record<string, string> = {
  peran_pengguna_diubah: "Peran pengguna diubah",
  pengguna_diaktifkan: "Pengguna diaktifkan",
  pengguna_dinonaktifkan: "Pengguna dinonaktifkan",
  peran_dibuat: "Peran dibuat",
  peran_diubah: "Peran diubah",
  peran_dihapus: "Peran dihapus",
  hak_akses_diubah: "Hak akses diubah",
};

// Kolom Aksi memakai bentuk pasif ("Peran dihapus") karena itu label, sedangkan kolom
// Rincian menceritakan siapa melakukan apa, jadi butuh kata kerja aktif sendiri.
const KATA_KERJA: Record<string, string> = {
  peran_dibuat: "membuat",
  peran_diubah: "mengubah nama",
  peran_dihapus: "menghapus",
};

/** Ringkasan satu baris log, disusun dari detailnya supaya terbaca sebagai kalimat. */
function ceritaLog(b: BarisLogAkses): string {
  const d = b.detail as Record<string, string | string[]>;
  const oleh = (d.oleh as string) ?? "?";
  if (b.aksi === "peran_pengguna_diubah") {
    return `${oleh} memindahkan ${d.username} dari ${d.dari} ke ${d.ke}`;
  }
  if (b.aksi === "hak_akses_diubah") {
    const tambah = (d.ditambah as string[]) ?? [];
    const cabut = (d.dicabut as string[]) ?? [];
    const bagian = [
      tambah.length ? `menambah ${tambah.join(", ")}` : "",
      cabut.length ? `mencabut ${cabut.join(", ")}` : "",
    ].filter(Boolean);
    return `${oleh} mengubah peran ${d.peran}: ${bagian.join(" dan ") || "tanpa perubahan"}`;
  }
  if (b.aksi.startsWith("pengguna_")) {
    return `${oleh} ${b.aksi === "pengguna_diaktifkan" ? "mengaktifkan" : "menonaktifkan"} ${d.username}`;
  }
  const kerja = KATA_KERJA[b.aksi];
  if (kerja) {
    const nama = d.nama ? ` (${d.nama})` : "";
    return `${oleh} ${kerja} peran ${d.kode}${nama}`;
  }
  return `${oleh}: ${b.aksi} ${d.kode ?? ""}`.trim();
}

export default function HalamanAkses() {
  const [tab, setTab] = useState<KunciTab>("pengguna");
  const [pengguna, setPengguna] = useState<PenggunaAkses[]>([]);
  const [peran, setPeran] = useState<PeranAkses[]>([]);
  const [katalog, setKatalog] = useState<KatalogIzin[]>([]);
  const [log, setLog] = useState<BarisLogAkses[]>([]);
  const [galat, setGalat] = useState("");
  const [pesan, setPesan] = useState("");

  const muat = useCallback(async () => {
    setGalat("");
    try {
      const [orang, hak, riwayat] = await Promise.all([
        ambilPenggunaAkses(),
        ambilPeranAkses(),
        ambilLogAkses(),
      ]);
      setPengguna(orang);
      setPeran(hak.peran);
      setKatalog(hak.katalog_izin);
      setLog(riwayat);
    } catch (e) {
      setGalat((e as Error).message);
    }
  }, []);

  useEffect(() => {
    muat();
  }, [muat]);

  /** Jalankan satu perubahan lalu muat ulang semuanya, supaya angka di tab lain ikut betul. */
  async function jalankan(kerja: () => Promise<unknown>, sukses: string) {
    setGalat("");
    setPesan("");
    try {
      await kerja();
      setPesan(sukses);
      await muat();
    } catch (e) {
      setGalat((e as Error).message);
    }
  }

  return (
    <Kerangka
      judul="Manajemen Akses"
      keterangan="Siapa boleh melakukan apa di sistem ini"
      butuh={butuhIzin(IZIN.aksesKelola)}
    >
      <div className="tab">
        {TAB.map((t) => (
          <button
            key={t.kunci}
            type="button"
            className={t.kunci === tab ? "aktif" : ""}
            onClick={() => setTab(t.kunci)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {galat && <div className="galat">{galat}</div>}
      {pesan && <div className="berhasil-kotak">{pesan}</div>}

      {tab === "pengguna" && (
        <TabPengguna pengguna={pengguna} peran={peran} jalankan={jalankan} />
      )}
      {tab === "peran" && <TabPeran peran={peran} jalankan={jalankan} />}
      {tab === "hak" && (
        <TabHak peran={peran} katalog={katalog} jalankan={jalankan} />
      )}
      {tab === "log" && <TabLog log={log} />}
    </Kerangka>
  );
}

type Jalankan = (kerja: () => Promise<unknown>, sukses: string) => Promise<void>;

function TabPengguna({
  pengguna,
  peran,
  jalankan,
}: {
  pengguna: PenggunaAkses[];
  peran: PeranAkses[];
  jalankan: Jalankan;
}) {
  const [username, setUsername] = useState("");
  const [nama, setNama] = useState("");
  const [peranBaru, setPeranBaru] = useState("");
  const [sandi, setSandi] = useState("");
  const [akanDihapus, setAkanDihapus] = useState<PenggunaAkses | null>(null);

  // Bawaannya peran pertama, yang baru ada setelah daftar peran selesai dimuat.
  const peranTerpilih = peranBaru || peran[0]?.kode || "";

  return (
    <>
    <div className="kartu">
      <h2>Pengguna</h2>
      <p className="petunjuk">
        Ubah peran seseorang lewat pilihan di kolom Peran.
      </p>

      <div className="gulir">
        <table>
          <thead>
            <tr>
              <th>Username</th>
              <th>Nama</th>
              <th>Peran</th>
              <th>Keadaan</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {pengguna.map((u) => (
              <tr key={u.username}>
                <td>
                  <strong>{u.username}</strong>
                </td>
                <td>{u.nama}</td>
                <td>
                  <select
                    value={u.peran}
                    onChange={(e) =>
                      jalankan(
                        () => ubahPenggunaAkses(u.username, { peran: e.target.value }),
                        `Peran ${u.username} diubah jadi ${e.target.value}.`,
                      )
                    }
                  >
                    {peran.map((p) => (
                      <option key={p.kode} value={p.kode}>
                        {p.nama}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <span className={`lencana ${u.aktif ? "hijau" : "abu"}`}>
                    {u.aktif ? "Aktif" : "Nonaktif"}
                  </span>
                </td>
                <td className="aksi">
                  <button
                    type="button"
                    className="sekunder"
                    onClick={() =>
                      jalankan(
                        () => ubahPenggunaAkses(u.username, { aktif: !u.aktif }),
                        `${u.username} ${u.aktif ? "dinonaktifkan" : "diaktifkan"}.`,
                      )
                    }
                  >
                    {u.aktif ? "Nonaktifkan" : "Aktifkan"}
                  </button>
                  <button
                    type="button"
                    className="sekunder"
                    onClick={() => setAkanDihapus(u)}
                    title={`Hapus pengguna ${u.username}`}
                  >
                    Hapus
                  </button>
                  <button
                    type="button"
                    className="sekunder"
                    onClick={() =>
                      jalankan(
                        () => resetSandiPengguna(u.username),
                        `Kata sandi ${u.username} dikembalikan ke sandi demo.`,
                      )
                    }
                  >
                    Reset sandi
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="redup">
        Akun yang dinonaktifkan tidak bisa masuk lagi, tapi klaim yang pernah dia
        kirim tetap utuh beserta namanya di jejak audit.
      </p>
    </div>

    <div className="kartu">
      <h2>Tambah pengguna</h2>
      <div className="baris">
        <div>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            value={username}
            placeholder="toni"
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="nama-pengguna">Nama tampil</label>
          <input
            id="nama-pengguna"
            type="text"
            value={nama}
            placeholder="Toni Saputra"
            onChange={(e) => setNama(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="peran-pengguna">Peran</label>
          <select
            id="peran-pengguna"
            value={peranTerpilih}
            onChange={(e) => setPeranBaru(e.target.value)}
          >
            {peran.map((p) => (
              <option key={p.kode} value={p.kode}>
                {p.nama}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="sandi-pengguna">Kata sandi</label>
          <input
            id="sandi-pengguna"
            type="password"
            value={sandi}
            placeholder="Kosongkan untuk sandi demo"
            onChange={(e) => setSandi(e.target.value)}
          />
        </div>
      </div>

      <button
        type="button"
        disabled={!username.trim() || !nama.trim() || !peranTerpilih}
        onClick={() =>
          jalankan(async () => {
            await buatPenggunaAkses(username.trim(), nama.trim(), peranTerpilih, sandi);
            setUsername("");
            setNama("");
            setSandi("");
          }, `Pengguna ${username.trim()} dibuat.`)
        }
      >
        Tambah pengguna
      </button>
    </div>

    {akanDihapus && (
      <div className="tirai" role="dialog" aria-modal="true" aria-label="Konfirmasi hapus">
        <div className="dialog">
          <h2>Hapus pengguna {akanDihapus.username}?</h2>
          <p>
            Akunnya hilang dan tidak bisa masuk lagi. Klaim yang pernah dia kirim dan
            jejak auditnya tetap utuh beserta namanya. Ini tidak bisa dibatalkan.
          </p>
          <div className="tombol-dialog">
            <button
              type="button"
              className="sekunder"
              onClick={() => setAkanDihapus(null)}
            >
              Batal
            </button>
            <button
              type="button"
              className="bahaya"
              onClick={() =>
                jalankan(async () => {
                  await hapusPenggunaAkses(akanDihapus.username);
                  setAkanDihapus(null);
                }, `Pengguna ${akanDihapus.username} dihapus.`)
              }
            >
              Ya, hapus
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

function TabPeran({ peran, jalankan }: { peran: PeranAkses[]; jalankan: Jalankan }) {
  const [kode, setKode] = useState("");
  const [nama, setNama] = useState("");
  const [keterangan, setKeterangan] = useState("");
  const [sunting, setSunting] = useState<string | null>(null);
  const [suntingNama, setSuntingNama] = useState("");
  const [suntingKet, setSuntingKet] = useState("");

  function mulaiSunting(p: PeranAkses) {
    setSunting(p.kode);
    setSuntingNama(p.nama);
    setSuntingKet(p.keterangan);
  }

  return (
    <>
      <div className="kartu">
        <h2>Peran</h2>
        <p className="petunjuk">
          Peran default tidak bisa dihapus tapi haknya tetap boleh diubah di tab Hak Akses.
        </p>

        <div className="gulir">
          <table>
            <thead>
              <tr>
                <th>Kode</th>
                <th>Nama</th>
                <th>Keterangan</th>
                <th className="angka">Pengguna</th>
                <th className="angka">Hak</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {peran.map((p) => (
                <tr key={p.kode}>
                  <td>
                    <code>{p.kode}</code>
                    {p.bawaan && <span className="lencana abu">default</span>}
                  </td>
                  <td>
                    {sunting === p.kode ? (
                      <input
                        type="text"
                        value={suntingNama}
                        onChange={(e) => setSuntingNama(e.target.value)}
                      />
                    ) : (
                      p.nama
                    )}
                  </td>
                  <td>
                    {sunting === p.kode ? (
                      <input
                        type="text"
                        value={suntingKet}
                        onChange={(e) => setSuntingKet(e.target.value)}
                      />
                    ) : (
                      <span className="redup">{p.keterangan || "-"}</span>
                    )}
                  </td>
                  <td className="angka">{p.jumlah_pengguna}</td>
                  <td className="angka">{p.izin.length}</td>
                  <td className="aksi">
                    {sunting === p.kode ? (
                      <>
                        <button
                          type="button"
                          onClick={() =>
                            jalankan(async () => {
                              await ubahPeranAkses(p.kode, suntingNama, suntingKet);
                              setSunting(null);
                            }, `Peran ${p.kode} disimpan.`)
                          }
                        >
                          Simpan
                        </button>{" "}
                        <button
                          type="button"
                          className="sekunder"
                          onClick={() => setSunting(null)}
                        >
                          Batal
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="sekunder"
                          onClick={() => mulaiSunting(p)}
                        >
                          Ubah
                        </button>{" "}
                        {!p.bawaan && (
                          <button
                            type="button"
                            className="hapus"
                            title={`Hapus peran ${p.kode}`}
                            onClick={() =>
                              jalankan(
                                () => hapusPeranAkses(p.kode),
                                `Peran ${p.kode} dihapus.`,
                              )
                            }
                          >
                            <span aria-hidden="true">×</span>
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="kartu">
        <h2>Buat peran baru</h2>
        <p className="petunjuk">
          Peran baru dibuat tanpa hak sama sekali. Setelah dibuat, beri haknya di tab
          Hak Akses.
        </p>

        <div className="baris">
          <div>
            <label htmlFor="kode">Kode</label>
            <input
              id="kode"
              type="text"
              value={kode}
              placeholder="peninjau"
              onChange={(e) => setKode(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="nama">Nama tampil</label>
            <input
              id="nama"
              type="text"
              value={nama}
              placeholder="Peninjau"
              onChange={(e) => setNama(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="ket">Keterangan</label>
            <input
              id="ket"
              type="text"
              value={keterangan}
              placeholder="Boleh melihat klaim, tidak boleh memutuskan"
              onChange={(e) => setKeterangan(e.target.value)}
            />
          </div>
        </div>

        <button
          type="button"
          disabled={!kode.trim() || !nama.trim()}
          onClick={() =>
            jalankan(async () => {
              await buatPeranAkses(kode.trim(), nama.trim(), keterangan.trim());
              setKode("");
              setNama("");
              setKeterangan("");
            }, `Peran ${kode.trim()} dibuat.`)
          }
        >
          Buat peran
        </button>
      </div>
    </>
  );
}

function TabHak({
  peran,
  katalog,
  jalankan,
}: {
  peran: PeranAkses[];
  katalog: KatalogIzin[];
  jalankan: Jalankan;
}) {
  const [draf, setDraf] = useState<Record<string, string[]>>({});

  // Draf disalin dari data yang baru dimuat, jadi centang yang belum disimpan tidak
  // hilang saat komponennya digambar ulang, dan ikut betul setelah disimpan.
  useEffect(() => {
    setDraf(Object.fromEntries(peran.map((p) => [p.kode, [...p.izin]])));
  }, [peran]);

  const kelompok = [...new Set(katalog.map((k) => k.kelompok))];

  function balik(kode: string, hak: string) {
    setDraf((d) => {
      const punya = d[kode] ?? [];
      return {
        ...d,
        [kode]: punya.includes(hak)
          ? punya.filter((x) => x !== hak)
          : [...punya, hak],
      };
    });
  }

  function berubah(p: PeranAkses): boolean {
    const a = [...(draf[p.kode] ?? [])].sort().join(",");
    return a !== [...p.izin].sort().join(",");
  }

  return (
    <div className="kartu">
      <h2>Hak Akses</h2>

      <div className="gulir">
        <table className="matriks-hak">
          <thead>
            <tr>
              <th>Hak akses</th>
              {peran.map((p) => (
                <th key={p.kode} className="angka">
                  {p.nama}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kelompok.map((g) => (
              <Fragment key={g}>
                <tr className="kelompok">
                  <th colSpan={peran.length + 1}>{g}</th>
                </tr>
                {katalog
                  .filter((k) => k.kelompok === g)
                  .map((k) => (
                    <tr key={k.kode}>
                      <td>
                        <div>{k.nama}</div>
                        <div className="redup">{k.keterangan}</div>
                      </td>
                      {peran.map((p) => (
                        <td key={p.kode} className="angka">
                          <input
                            type="checkbox"
                            aria-label={`${k.nama} untuk ${p.nama}`}
                            checked={(draf[p.kode] ?? []).includes(k.kode)}
                            onChange={() => balik(p.kode, k.kode)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="simpan-hak">
        {peran.filter(berubah).map((p) => (
          <button
            key={p.kode}
            type="button"
            onClick={() =>
              jalankan(
                () => aturIzinPeran(p.kode, draf[p.kode] ?? []),
                `Hak akses peran ${p.nama} disimpan dan langsung berlaku.`,
              )
            }
          >
            Simpan perubahan {p.nama}
          </button>
        ))}
        {peran.every((p) => !berubah(p)) && (
          <p className="redup" style={{ margin: 0 }}>
            Belum ada perubahan yang perlu disimpan.
          </p>
        )}
      </div>
    </div>
  );
}

function TabLog({ log }: { log: BarisLogAkses[] }) {
  return (
    <div className="kartu">
      <h2>Log Aktivitas</h2>
      <p className="petunjuk">
        Log Aktivitas pada menu "Mnajemen Akses". Ditampilkan 100 perubahan akses terakhir.
      </p>

      {log.length === 0 ? (
        <p className="redup">Belum ada perubahan akses yang tercatat.</p>
      ) : (
        <div className="gulir">
          <table>
            <thead>
              <tr>
                <th>Waktu</th>
                <th>Aksi</th>
                <th>Rincian</th>
              </tr>
            </thead>
            <tbody>
              {log.map((b, i) => (
                <tr key={i}>
                  <td>{waktu(b.waktu)}</td>
                  <td>{NAMA_AKSI[b.aksi] ?? b.aksi}</td>
                  <td>{ceritaLog(b)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
