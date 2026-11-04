/** Ters bölü ya da kontrol karakteri (sekme, satır sonu…): tarayıcı "\" işaretini "/" sayar ve
 * sekmeyi adresten siler; "/\x" ya da "/<sekme>/x" başka sunucuya giden "//x" olabilir. */
function hasUnsafeChars(value: string): boolean {
  for (const char of value) {
    const code = char.charCodeAt(0);
    if (char === "\\" || code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

/**
 * Adresten ya da kullanıcıdan gelen değer uygulama içi bir yol mu (açık yönlendirmeyi önler)?
 * Yalnızca "/" ile başlayan, "//" ile başlamayan, ters bölü ve kontrol karakteri içermeyen ve bu
 * sitenin içine çözülen yollar geçer. Çözülmüş yol da "//" ile başlamamalı: "/..//x" gibi nokta
 * bölümleri çözülünce "//x" kalır ve tarayıcı bunu başka sunucu sayar. Geçerse yol + sorgu + çapa
 * döner, geçmezse null.
 */
export function safeAppPath(value: string | null | undefined): string | null {
  if (!value || !value.startsWith("/") || value.startsWith("//") || hasUnsafeChars(value)) {
    return null;
  }
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || url.pathname.startsWith("//")) return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}
