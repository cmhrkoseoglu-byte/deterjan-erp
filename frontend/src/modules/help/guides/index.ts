import type { Role } from "../../../api/types";
import admin from "./admin.md?raw";
import depo from "./depo.md?raw";
import dolum from "./dolum.md?raw";
import gecis from "./gecis.md?raw";
import genel from "./genel.md?raw";
import laboratuvar from "./laboratuvar.md?raw";
import planlama from "./planlama.md?raw";
import satinAlma from "./satin-alma.md?raw";
import sevkiyat from "./sevkiyat.md?raw";
import uretim from "./uretim.md?raw";
import yonetim from "./yonetim.md?raw";

export interface Guide {
  slug: string;
  title: string;
  /** Bu rollerdeki kullanıcıya "Rolünüzün kılavuzları" altında gösterilir. */
  roles: readonly Role[];
  content: string;
}

// Kılavuzlar Markdown'dur; ekran görüntüleri `public/kilavuz/` altında,
// `scripts/kilavuz-ekran-goruntuleri.mjs` demo verisiyle yeniden üretir.
export const GUIDES: Guide[] = [
  {
    slug: "genel",
    title: "Başlarken",
    roles: [
      "admin",
      "yonetim",
      "planlama",
      "depo",
      "uretim",
      "laboratuvar",
      "dolum",
      "sevkiyat",
      "satin_alma",
    ],
    content: genel,
  },
  { slug: "depo", title: "Depo", roles: ["depo"], content: depo },
  { slug: "planlama", title: "Planlama", roles: ["planlama"], content: planlama },
  { slug: "uretim", title: "Üretim (tablet)", roles: ["uretim"], content: uretim },
  { slug: "laboratuvar", title: "Laboratuvar", roles: ["laboratuvar"], content: laboratuvar },
  { slug: "dolum", title: "Dolum (tablet)", roles: ["dolum"], content: dolum },
  { slug: "sevkiyat", title: "Sevkiyat", roles: ["sevkiyat"], content: sevkiyat },
  { slug: "satin-alma", title: "Satın alma", roles: ["satin_alma"], content: satinAlma },
  { slug: "yonetim", title: "Yönetim", roles: ["yonetim"], content: yonetim },
  { slug: "admin", title: "Sistem yöneticisi", roles: ["admin"], content: admin },
  {
    slug: "gecis",
    title: "Canlıya geçiş ve sayım günü",
    roles: ["admin", "yonetim", "planlama", "depo"],
    content: gecis,
  },
];
