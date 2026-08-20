const SISI_TERPANJANG = 1280;
const MUTU = 0.85;

/** Perkecil foto di browser sebelum diunggah, supaya waktu unggah dan pra-proses turun. */
export async function perkecil(berkas: File): Promise<File> {
  const bitmap = await createImageBitmap(berkas);
  const skala = Math.min(1, SISI_TERPANJANG / Math.max(bitmap.width, bitmap.height));
  if (skala === 1) {
    bitmap.close();
    return berkas;
  }

  const kanvas = document.createElement("canvas");
  kanvas.width = Math.round(bitmap.width * skala);
  kanvas.height = Math.round(bitmap.height * skala);
  const ctx = kanvas.getContext("2d");
  if (!ctx) {
    bitmap.close();
    return berkas;
  }
  ctx.drawImage(bitmap, 0, 0, kanvas.width, kanvas.height);
  bitmap.close();

  const blob = await new Promise<Blob | null>((selesai) =>
    kanvas.toBlob(selesai, "image/jpeg", MUTU),
  );
  if (!blob) return berkas;

  const nama = berkas.name.replace(/\.[^.]+$/, "") + ".jpg";
  return new File([blob], nama, { type: "image/jpeg" });
}
