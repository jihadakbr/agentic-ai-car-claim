import ReviewStnk from "@/components/ReviewStnk";
import { alamatEstimasiPdf, type DetailKlaim } from "@/lib/api";
import { labelRekomendasi, labelStatus, persen, rupiah, warnaStatus } from "@/lib/format";

function warnaVerdict(verdict: string | null): string {
  if (verdict === "valid") return "hijau";
  if (verdict === "perlu_review") return "kuning";
  if (verdict === "invalid") return "merah";
  return "abu";
}

function KartuCek({ cek }: { cek: DetailKlaim["cek"] }) {
  return (
    <div className="kartu">
      <h2>Pemeriksaan Otomatis Saat Klaim Masuk</h2>
      <p className="petunjuk">
        Dihitung sekali saat klaim diproses, dari hasil baca AI sebelum diperiksa
        adjuster. Koreksi di tabel deteksi maupun STNK tidak mengubah hasil di bawah ini,
        supaya yang tercatat tetap apa yang benar-benar dilihat sistem saat itu.
      </p>
      <ul className="cek">
        {cek.map((c) => (
          <li key={c.kode}>
            <span className="kode">{c.kode}</span>
            <span className="isi">
              <div>{c.nama}</div>
              <div className="alasan">{c.alasan}</div>
            </span>
            <span
              className={`lencana ${c.lolos ? "hijau" : c.tingkat === "soft" ? "kuning" : "merah"}`}
            >
              {c.lolos
                ? "lolos"
                : c.tingkat === "soft"
                  ? "perlu direview"
                  : "gagal"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function KartuBiaya({ klaim }: { klaim: DetailKlaim }) {
  const b = klaim.biaya;
  if (!b) return null;

  const lewatAmbang = b.total_loss_ratio >= b.ambang_total_loss;
  const hitungan = [
    `total biaya      = ${rupiah(b.total_part)} (part) + ${rupiah(b.total_jasa)} (jasa)`,
    `                 = ${rupiah(b.total_biaya)}`,
    `rasio total loss = ${rupiah(b.total_biaya)} / ${rupiah(b.harga_pasar_bekas)}`,
    `                 = ${persen(b.total_loss_ratio)}`,
    `ambang PSAKBI    = ${persen(b.ambang_total_loss, 0)}`,
    `${persen(b.total_loss_ratio)} ${lewatAmbang ? ">=" : "<"} ${persen(b.ambang_total_loss, 0)} -> ${labelRekomendasi(b.rekomendasi)}`,
  ].join("\n");

  return (
    <div className="kartu">
      <div className="kepala-kartu">
        <h2>Rincian Biaya</h2>
        {/* Tautan biasa, bukan fetch lalu blob, supaya nama berkas unduhannya ditentukan
            server dan tidak ada dokumen yang ditahan di memori browser. */}
        <div className="aksi-kartu">
          <a
            className="tombol sekunder"
            href={alamatEstimasiPdf(klaim.id)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Lihat PDF
          </a>
          <a className="tombol sekunder" href={alamatEstimasiPdf(klaim.id, true)}>
            Unduh PDF
          </a>
        </div>
      </div>
      <div className="gulir">
        <table>
          <thead>
            <tr>
              <th>Bagian mobil</th>
              <th>Kerusakan</th>
              <th>Operasi</th>
              <th className="angka">Jam</th>
              <th className="angka">Part</th>
              <th className="angka">Jasa</th>
              <th>Sumber</th>
            </tr>
          </thead>
          <tbody>
            {klaim.baris_biaya.map((r, i) => (
              <tr key={`${r.part_class}-${r.sisi ?? ""}-${i}`}>
                {/* Baris hasil deteksi memakai nama kelas model apa adanya, supaya sama
                    persis dengan tabel Hasil Deteksi pada Foto. Baris dari aturan tidak
                    punya padanan di dataset, jadi tetap nama Indonesianya. */}
                <td>
                  {r.sumber === "deteksi" ? r.part_class : r.nama_part}
                  {r.sisi ? ` (${r.sisi})` : ""}
                </td>
                <td>
                  {r.damage_class ?? "-"}
                  {r.kerusakan_lain ? ` (+ ${r.kerusakan_lain})` : ""}
                </td>
                <td>{r.operasi}</td>
                <td className="angka">{r.jam_standar}</td>
                <td className="angka">{rupiah(r.harga_part)}</td>
                <td className="angka">{rupiah(r.biaya_jasa)}</td>
                <td>{LABEL_SUMBER[r.sumber] ?? r.sumber}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={4}>Total</th>
              <th className="angka">{rupiah(b.total_part)}</th>
              <th className="angka">{rupiah(b.total_jasa)}</th>
              <th />
            </tr>
          </tfoot>
        </table>
      </div>

      <h2 style={{ marginTop: 20 }}>Perhitungan total loss</h2>
      <pre className="hitungan">{hitungan}</pre>

      {/* Own risk hanya berlaku untuk klaim perbaikan. Pada total loss tidak ada biaya
          perbaikan yang dibayarkan, jadi yang perlu dilihat adjuster adalah harga
          penawarannya, sebelum dia menekan tombol setuju. */}
      <dl className="daftar-def" style={{ marginTop: 14 }}>
        {lewatAmbang ? (
          <>
            <dt>Penawaran beli</dt>
            <dd>
              {rupiah(b.harga_tawaran_salvage)}, terbit kalau klaim ini
              disetujui
            </dd>
            <dt>Own risk</dt>
            <dd>Tidak berlaku, tidak ada biaya perbaikan yang dibayarkan</dd>
          </>
        ) : (
          <>
            <dt>Own risk</dt>
            <dd>{rupiah(b.own_risk)} per kejadian, ketentuan OJK</dd>
            <dt>Ditanggung penanggung</dt>
            <dd>{rupiah(b.ditanggung_penanggung)}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

/** Surveyor dan adjuster melihat kartu yang berbeda.
 *
 *  Surveyor perlu tahu apakah kiriman fotonya diterima dan apakah ada yang harus difoto
 *  ulang. Angka biaya, rekomendasi mesin, penilaian agent, dan narasinya adalah bahan
 *  pengambilan keputusan, dan itu wewenang adjuster. */
// Baris "aturan" ditampilkan sebagai Simulasi karena memang tidak berasal dari foto.
// Komponen di balik bodi belum bisa dideteksi model, jadi barisnya dimasukkan aturan
// sebagai gambaran hasil kalau kemampuan itu nanti ada.
const LABEL_SUMBER: Record<string, string> = {
  deteksi: "Deteksi AI",
  aturan: "Simulasi",
  agent: "Agent",
};

export default function HasilKlaim({
  klaim,
  untuk = "adjuster",
  terkunci = false,
  saatBerubah,
}: {
  klaim: DetailKlaim;
  untuk?: "surveyor" | "adjuster";
  /** Klaim yang sudah diputuskan tidak boleh diubah penilaiannya. */
  terkunci?: boolean;
  saatBerubah?: () => void;
}) {
  const penuh = untuk === "adjuster";

  // Adjuster membaca bukti dulu baru ringkasannya, jadi kartu ini turun ke bawah tabel
  // biaya. Surveyor tidak melihat biaya sama sekali dan cuma butuh status kirimannya,
  // jadi untuk dia kartu ini tetap di paling atas.
  const ringkasan = (
    <div className="kartu">
      <h2>Ringkasan Klaim</h2>
      <p className="petunjuk">
        {klaim.nomor_klaim} &middot; {klaim.kendaraan} &middot;{" "}
        {klaim.pemegang_polis} &middot; polis {klaim.nomor_polis}
      </p>
      <div className="baris">
        <div>
          <label>Validitas</label>
          <span
            className={`lencana ${warnaVerdict(klaim.verdict_validitas)}`}
          >
            {klaim.verdict_validitas ?? "-"}
          </span>
        </div>
        {penuh && (
          <>
            <div>
              <label>Rekomendasi mesin</label>
              <span className="lencana abu">
                {labelRekomendasi(klaim.rekomendasi)}
              </span>
            </div>
            <div>
              <label>Total biaya</label>
              <div>{rupiah(klaim.total_biaya)}</div>
            </div>
          </>
        )}
        <div>
          <label>Status</label>
          <span className={`lencana ${warnaStatus(klaim.status)}`}>
            {labelStatus(klaim.status)}
          </span>
        </div>
      </div>
      {penuh && klaim.narasi && <p style={{ margin: 0 }}>{klaim.narasi}</p>}
    </div>
  );

  return (
    <>
      {!penuh && ringkasan}

      {klaim.permintaan_foto.length > 0 && (
        <div className="kartu">
          <h2>Foto tambahan yang diminta</h2>
          <p className="petunjuk">
            Agent menahan penilaian karena buktinya belum cukup. Klaim
            dilanjutkan setelah foto ini masuk.
          </p>
          <ul>
            {klaim.permintaan_foto.map((p, i) => (
              <li key={i}>
                {p.permintaan}
                {p.alasan ? ` — ${p.alasan}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ReviewStnk
        klaim={klaim}
        bolehNilai={penuh}
        terkunci={terkunci}
        saatBerubah={saatBerubah}
      />

      <KartuCek cek={klaim.cek} />

      {penuh && <KartuBiaya klaim={klaim} />}
      {penuh && ringkasan}

      {penuh && klaim.penilaian_agent && (
        <div className="kartu">
          <h2>Rekomendasi Keputusan AI Agent</h2>
          <p style={{ margin: 0 }}>{klaim.penilaian_agent.alasan}</p>
        </div>
      )}
    </>
  );
}
