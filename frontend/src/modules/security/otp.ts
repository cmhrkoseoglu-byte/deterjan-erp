/** SVG metnini `data:` adresine çevirir (UTF-8 güvenli base64). */
export function svgDataUrl(svg: string): string {
  const bytes = new TextEncoder().encode(svg);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `data:image/svg+xml;base64,${btoa(binary)}`;
}

/** Elle girilecek anahtar 4'erli gruplanır: "ABCD EFGH …". */
export function groupSecret(secret: string): string {
  return (secret.replace(/\s+/g, "").match(/.{1,4}/g) ?? []).join(" ");
}
