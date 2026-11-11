"""Anlık görüntüden bilerek ayrılan kararlar (plan §5.5 "İzin listesi").

Her kayıt bir farkı planın bir maddesine bağlar: §8'deki ilk gün değişiklikleri ya da planın
eklediği yeni uç noktalar. Her adım yalnız kendi maddelerini ekler (plan §10'daki madde → adım
eşlemesi). Buraya plan dışı bir kayıt eklemek sahibin onayını ve DECISIONS kaydını ister.
"""

from dataclasses import dataclass
from fnmatch import fnmatchcase

MISSING = "<yok>"  # durum anlık görüntüde (ya da bugünkü kodda) yok
ANY = "<her>"  # eski ya da yeni değer ne olursa olsun


@dataclass(frozen=True)
class Allowed:
    """Bir anlık görüntüde izin verilen fark.

    `case` ve `persona` `fnmatch` desenidir (ör. `"GET /api/v1/access/*"`, `"*"`).
    """

    item: str
    snapshot: str
    case: str
    persona: str = "*"
    old: object = ANY
    new: object = ANY

    def permits(self, snapshot: str, case: str, persona: str, old: object, new: object) -> bool:
        return (
            self.snapshot == snapshot
            and fnmatchcase(case, self.case)
            and fnmatchcase(persona, self.persona)
            and (self.old == ANY or self.old == old)
            and (self.new == ANY or self.new == new)
        )


ALLOWED: tuple[Allowed, ...] = (
    # 1. adım: planın eklediği yeni uç noktalar (plan §5.5).
    Allowed(
        item="yeni uç nokta: yetki kataloğu (plan §5.1)",
        snapshot="endpoints",
        case="* /api/v1/access/catalog/",
        old=MISSING,
    ),
)


def permitted(snapshot: str, case: str, persona: str, old: object, new: object) -> Allowed | None:
    """Farkı izin veren kayıt (yoksa `None`)."""
    for allowed in ALLOWED:
        if allowed.permits(snapshot, case, persona, old, new):
            return allowed
    return None
