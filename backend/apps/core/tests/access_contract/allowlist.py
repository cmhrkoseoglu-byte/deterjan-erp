"""Anlık görüntüden bilerek ayrılan kararlar (plan §5.5 "İzin listesi").

Her kayıt bir farkı planın bir maddesine bağlar: §8'deki ilk gün değişiklikleri ya da planın adıyla
eklediği uç noktalar ve modeller. Kaydın `step` alanı maddenin açıldığı adımdır (plan §10'daki
madde → adım eşlemesi); kayıt `CURRENT_STEP` o adıma gelince geçerli olur, yani her adım yalnız
kendi maddelerini açar. Kayıt beklenen farkı olabildiğince dar yazar: durum, persona, eski ve yeni
değer. Buraya plan dışı bir kayıt eklemek sahibin onayını ve DECISIONS kaydını ister.

- Desenlerde yalnız `*` (herhangi bir metin) ve `?` (tek karakter) jokerdir; köşeli parantez dahil
  öteki karakterler olduğu gibi eşleşir (durum adları "[kendi önerisi]" gibi parantez taşır).
- `required=True` (varsayılan) kayıt, karşılaştırmada en az bir farkla eşleşmelidir. Onaylı bir
  değişiklik sonradan geri alınırsa (değer dondurulmuş eski değere dönerse) test bunu yakalar.
"""

import re
from dataclasses import dataclass

MISSING = "<yok>"  # durum anlık görüntüde (ya da bugünkü kodda) yok
ANY = "<her>"  # eski ya da yeni değer ne olursa olsun

# Uygulanan adım (plan §10). Her adım bu sayıyı artırır ve kendi kayıtlarını ekler.
CURRENT_STEP = 1


def matches(pattern: str, text: str) -> bool:
    """Desen eşleşmesi: yalnız `*` ve `?` jokerdir (ön yüzdeki `allowlist.ts` ile aynı)."""
    regex = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char) for char in pattern
    )
    return re.fullmatch(regex, text, flags=re.DOTALL) is not None


@dataclass(frozen=True, eq=False)
class Allowed:
    """Bir anlık görüntüde izin verilen fark."""

    item: str
    snapshot: str
    case: str
    persona: str = "*"
    old: object = ANY
    new: object = ANY
    step: int = 1
    required: bool = True

    @property
    def active(self) -> bool:
        return self.step <= CURRENT_STEP

    def permits(self, snapshot: str, case: str, persona: str, old: object, new: object) -> bool:
        return (
            self.active
            and self.snapshot == snapshot
            and matches(self.case, case)
            and matches(self.persona, persona)
            and (self.old == ANY or self.old == old)
            and (self.new == ANY or self.new == new)
        )

    def __str__(self) -> str:
        return f"{self.item}: {self.snapshot} › {self.case} [{self.persona}]"


_SIGNED_IN_PERSONAS = (
    "no_role",
    "yonetim",
    "planlama",
    "depo",
    "uretim",
    "laboratuvar",
    "dolum",
    "sevkiyat",
    "satin_alma",
    "admin",
    "superuser",
    "depo+sevkiyat",
)

ALLOWED: tuple[Allowed, ...] = (
    # 1. adım: planın eklediği uç nokta (plan §5.1, §5.5). Giriş yapan herkese açık (SignedIn).
    *(
        Allowed(
            item="yeni uç nokta: yetki kataloğu (plan §5.1)",
            snapshot="endpoints",
            case="* /api/v1/access/catalog/",
            persona=persona,
            old=MISSING,
            new="401",
        )
        for persona in ("anonymous", "inactive")
    ),
    *(
        Allowed(
            item="yeni uç nokta: yetki kataloğu (plan §5.1)",
            snapshot="endpoints",
            case="* /api/v1/access/catalog/",
            persona=persona,
            old=MISSING,
            new="allow",
        )
        for persona in _SIGNED_IN_PERSONAS
    ),
    # 1. adım: planın eklediği modeller (plan §5.2). Denetim günlüğünde bugünkü gibi yönetime de
    # görünürler; yalnız admine kalmaları denetim günlüğü süzmesiyle gelir (plan §5.6, 6. adım) ve o
    # adım bu kayıtları değiştirir.
    *(
        Allowed(
            item="yeni model: kişiye özel yetki ve paket sürümü (plan §5.2)",
            snapshot="probe_audit",
            case=f"model: core.{model}",
            persona=persona,
            old=MISSING,
            new="full",
        )
        for model in ("accessoverride", "accesscatalogsnapshot")
        for persona in ("yonetim", "admin", "superuser")
    ),
)


def permitted(snapshot: str, case: str, persona: str, old: object, new: object) -> Allowed | None:
    """Farkı izin veren kayıt (yoksa `None`)."""
    for allowed in ALLOWED:
        if allowed.permits(snapshot, case, persona, old, new):
            return allowed
    return None


def required_for(snapshot: str) -> list[Allowed]:
    """Bu anlık görüntünün geçerli ve eşleşmesi gereken kayıtları."""
    return [item for item in ALLOWED if item.snapshot == snapshot and item.active and item.required]
