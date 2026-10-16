// Ek dosyası hazırlığı: boyut sınırı ve tablet fotoğraflarının tarayıcıda küçültülmesi.

export const MAX_ATTACHMENT_MB = 20;
export const ACCEPT =
  ".pdf,.jpg,.jpeg,.png,.webp,.heic,.gif,.xlsx,.xls,.docx,.doc,.csv,.txt,image/*,application/pdf";
const MAX_SIDE = 2000;
const SHRINK_ABOVE = 1024 * 1024;

/** 1 MB'tan büyük JPEG/PNG/WebP fotoğrafı uzun kenarı 2000 px olacak şekilde JPEG'e küçültür.
 * Küçültülemezse (tarayıcı desteği yok) dosya olduğu gibi döner. */
export async function prepareImage(file: File): Promise<File> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size <= SHRINK_ABOVE) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85),
    );
    if (!blob || blob.size >= file.size) return file;
    const name = file.name.replace(/\.[^.]+$/, "") + ".jpg";
    return new File([blob], name, { type: "image/jpeg" });
  } catch {
    return file;
  }
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}
