"""Anlık görüntüden bilerek ayrılan kararlar (plan §5.5 "İzin listesi").

Her kayıt bir farkı planın bir maddesine bağlar: §8'deki ilk gün değişiklikleri ya da planın adıyla
eklediği uç noktalar ve modeller. Liste 1. adımda bütün maddeleriyle yazıldı (plan §5.5). Kaydın
`step` alanı maddenin açıldığı adımdır (plan §10'daki madde → adım eşlemesi); kayıt `CURRENT_STEP` o
adıma gelince geçerli olur, yani her adım yalnız kendi maddelerini açar. `until` verilirse kayıt o
adımdan sonra geçersizdir (yerini sonraki bir adımın kaydı alır). Kayıt beklenen farkı hücre
hücre yazar: durum, persona, eski ve yeni değer; yeni değeri plan sabitlemiyorsa `ANY`. Buraya plan
dışı bir kayıt eklemek ya da bir kaydı genişletmek sahibin onayını ve DECISIONS kaydını ister.
`test_allowlist.py` her kaydın planın bir maddesine ve dondurulmuş bir hücreye bağlı olduğunu,
sonraki adımların kayıtları dahil, bugünden denetler.

- Desenlerde yalnız `*` (herhangi bir metin) ve `?` (tek karakter) jokerdir; köşeli parantez dahil
  öteki karakterler olduğu gibi eşleşir (durum adları "[kendi önerisi]" gibi parantez taşır).
- `required=True` (varsayılan) kayıt, karşılaştırmada en az bir farkla eşleşmelidir. Onaylı bir
  değişiklik sonradan geri alınırsa (değer dondurulmuş eski değere dönerse) test bunu yakalar.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

MISSING = "<yok>"  # durum anlık görüntüde (ya da bugünkü kodda) yok
ANY = "<her>"  # eski ya da yeni değer ne olursa olsun

# Uygulanan adım (plan §10). Her adım bu sayıyı artırır ve kendi kayıtlarını ekler.
CURRENT_STEP = 2


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
    until: int | None = None
    required: bool = True

    @property
    def active(self) -> bool:
        return self.step <= CURRENT_STEP and (self.until is None or self.until >= CURRENT_STEP)

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


def _cells(
    item: str,
    snapshot: str,
    cells: Mapping[str, Iterable[str]],
    *,
    step: int,
    old: object = ANY,
    new: object = ANY,
    until: int | None = None,
    required: bool = True,
) -> tuple[Allowed, ...]:
    """Her (durum, persona) hücresi için ayrı bir kayıt: her hücre ayrı ayrı gereklidir, kısmi bir
    uygulama testi geçemez. Eski değer verilmezse hücrenin dondurulmuş değeridir."""
    return tuple(
        Allowed(
            item=item,
            snapshot=snapshot,
            case=case,
            persona=persona,
            old=old,
            new=new,
            step=step,
            until=until,
            required=required,
        )
        for case, personas in cells.items()
        for persona in personas
    )


# Fiyatları görür'ü olan ve olmayan giriş yapmış personalar (rol paketleri, plan §3.18).
_PRICE_HOLDERS = ("yonetim", "satin_alma", "admin", "superuser")
_NO_PRICES = (
    "no_role",
    "planlama",
    "depo",
    "uretim",
    "laboratuvar",
    "dolum",
    "sevkiyat",
    "depo+sevkiyat",
)
_SIGNED_OUT = ("anonymous", "inactive")
# Mal kabulün geçmişte gizlenen alanları: satır fiyatı, para birimi, kur, ek masraf tutarı ve
# silinen ek masraf kaydının kendisi.
_RECEIPT_PRICE_FIELDS = ("amount", "currency", "exchange_rate", "extra_cost", "unit_price")
# 2. adımda gözlenen mal kabul geçmişi, fiyatları görmeyen kişide: fiyat düzeltmesi ve silinen ek
# masraf kaydı yok, silinen satırın içi fiyatsız, notlar aynen.
_RECEIPT_HISTORY_WITHOUT_PRICES = {
    "entries": [
        {"action": "status_change", "money": {}, "note": ""},
        {"action": "update", "money": {"line": [{}, None]}, "note": "Satır # kaldırıldı (taslak)"},
        {"action": "create", "money": {}, "note": ""},
    ],
    "status": 200,
}

# İade kayıtları: Değiştirir'i olmayan, giriş yapmış personalar (iadelerin sevkiyat seçimi).
_RETURNS_DENIED = (
    "no_role",
    "yonetim",
    "planlama",
    "depo",
    "uretim",
    "laboratuvar",
    "dolum",
    "satin_alma",
)

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
    # görünürler; yalnız admine kalmaları denetim günlüğü süzmesiyle gelir (plan §5.6, 6. adım), bu
    # yüzden yönetimin kaydı 5. adımda biter.
    *(
        Allowed(
            item="yeni model: kişiye özel yetki ve paket sürümü (plan §5.2)",
            snapshot="probe_audit",
            case=f"model: core.{model}",
            persona=persona,
            old=MISSING,
            new="full",
            until=5 if persona == "yonetim" else None,
        )
        for model in ("accessoverride", "accesscatalogsnapshot")
        for persona in ("yonetim", "admin", "superuser")
    ),
    # 2. adım — Mal kabul geçmişinde tutar içeren notlar ve silinen satır ve ek masraf kayıtlarının
    # içindeki fiyatlar Fiyatları görür'ü olmayana gösterilmez (§8 madde 7, plan §5.6): fiyat
    # düzeltmesi ve silinen ek masraf kaydı listelenmez, silinen satırın fiyatı gizlenir.
    *_cells(
        "§8 madde 7 (mal kabul)",
        "probe_prices",
        {"goods_receipt.history": _NO_PRICES},
        step=2,
        new=_RECEIPT_HISTORY_WITHOUT_PRICES,
    ),
    # Mal kabulün gizli alan listesi (yeni durum) ve geçmişte gizlenen alanlar.
    *_cells(
        "§8 madde 7 (mal kabul)",
        "probe_prices",
        {"record_type.hidden_fields.inventory.goodsreceipt": _PRICE_HOLDERS},
        step=2,
        old=MISSING,
        new=[],
    ),
    *_cells(
        "§8 madde 7 (mal kabul)",
        "probe_prices",
        {"record_type.hidden_fields.inventory.goodsreceipt": _SIGNED_OUT + _NO_PRICES},
        step=2,
        old=MISSING,
        new=list(_RECEIPT_PRICE_FIELDS),
    ),
    *_cells(
        "§8 madde 7 (mal kabul)",
        "probe_records",
        {
            f"history hides | inventory.goodsreceipt.{name}": _PRICE_HOLDERS
            for name in _RECEIPT_PRICE_FIELDS
        },
        step=2,
        old=MISSING,
        new=False,
    ),
    *_cells(
        "§8 madde 7 (mal kabul)",
        "probe_records",
        {
            f"history hides | inventory.goodsreceipt.{name}": _SIGNED_OUT + _NO_PRICES
            for name in _RECEIPT_PRICE_FIELDS
        },
        step=2,
        old=MISSING,
        new=True,
    ),
    # 4. adım — İade formunun sevk edilmiş sevkiyat seçimi iadelerin kendi uç noktasıdır; "İade
    # kayıtları: Değiştirir" ister (plan §5.4).
    *_cells(
        "yeni uç nokta: iadelerin sevkiyat seçimi (plan §5.4)",
        "endpoints",
        {
            "* /api/v1/returns/*shipment*": (
                "anonymous",
                "inactive",
            )
        },
        step=4,
        old=MISSING,
        new="401",
    ),
    *_cells(
        "yeni uç nokta: iadelerin sevkiyat seçimi (plan §5.4)",
        "endpoints",
        {
            "GET /api/v1/returns/*shipment*": _RETURNS_DENIED,
            "HEAD /api/v1/returns/*shipment*": _RETURNS_DENIED,
        },
        step=4,
        old=MISSING,
        new="403",
    ),
    # OPTIONS görünümün okuma iznini izleyebilir (AccessMixin'de `metadata`); plan bunu sabitlemez.
    *_cells(
        "yeni uç nokta: iadelerin sevkiyat seçimi (plan §5.4)",
        "endpoints",
        {"OPTIONS /api/v1/returns/*shipment*": _RETURNS_DENIED},
        step=4,
        old=MISSING,
        required=False,
    ),
    *_cells(
        "yeni uç nokta: iadelerin sevkiyat seçimi (plan §5.4)",
        "endpoints",
        {
            "* /api/v1/returns/*shipment*": (
                "sevkiyat",
                "admin",
                "superuser",
                "depo+sevkiyat",
            )
        },
        step=4,
        old=MISSING,
        new="allow",
    ),
    # 4. adım — Şartlı kabulü öneren kişi onaylayamaz, admin dahil (karar 10; plan §5.11
    # `conditional_same_person`). Reddetme değişmez.
    *_cells(
        "§8 madde 5",
        "probe_rules",
        {
            "quality.conditional_release.approve [kendi önerisi]": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=4,
        old="ok",
        new="400 conditional_same_person",
    ),
    # 5. adım — Onaya gönderme ve onay kayıtlarında tutar, kur ve limit notta değil ayrı alan
    # satırlarında görünür; nottaki tutar aramada bulunmaz.
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_audit",
        {
            "trail: purchasing.purchaseorder status_change [status] note$": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old=2,
        new=MISSING,
    ),
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_audit",
        {
            "trail: purchasing.purchaseorder status_change [*$*]*": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old=MISSING,
    ),
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_audit",
        {
            "read: detail purchasing.purchaseorder status_change": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old="purchasing.purchaseorder status_change [status] note$",
    ),
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_audit",
        {
            "amounts: notes": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        new=[
            "costing.lotcost create",
            "inventory.goodsreceipt update",
            "inventory.goodsreceiptline update",
            "inventory.lot update",
            "personnel.employee custom",
        ],
    ),
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_audit",
        {
            "search: 12.345,60": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old=["purchasing.purchaseorder status_change ×2"],
        new=[],
    ),
    # 5. adım — Tutar taşıyan alanların listesi 7. ve 8. maddeyle değişir (uygulamaya bağlı, gerekli
    # değil).
    *_cells(
        "§8 madde 7 ve madde 8",
        "probe_audit",
        {
            "amounts: fields": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        required=False,
    ),
    # 5. adım — İşçilik oranı notunda tutar yerine bordro numarası (denetim günlüğü; gerekli değil).
    *_cells(
        "§8 madde 8",
        "probe_audit",
        {
            "read: detail costing.costrate create (işçilik notu)": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        new="costing.costrate create [kind, note, rate_per_kg$, stage, valid_from]",
        required=False,
    ),
    *_cells(
        "§8 madde 8",
        "probe_audit",
        {
            "trail: costing.costrate create [kind, note$, rate_per_kg$, stage, valid_from]": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old=1,
        new=MISSING,
        required=False,
    ),
    *_cells(
        "§8 madde 8",
        "probe_audit",
        {
            "trail: costing.costrate create [kind, note, rate_per_kg$, stage, valid_from]": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
        old=MISSING,
        new=1,
        required=False,
    ),
    # 5. adım — Satın alma siparişi geçmişinde tutar içeren notlar ve silinen satırların fiyatları
    # Fiyatları görür'ü olmayana gösterilmez; onaya gönderme ve onay kayıtlarında tutar, kur ve
    # limit ayrı alan satırlarındadır (fiyatları görenlerde de).
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_prices",
        {
            "purchase_order.history": (
                "depo",
                "depo+sevkiyat",
            )
        },
        step=5,
    ),
    *_cells(
        "§8 madde 7 (satın alma)",
        "probe_prices",
        {
            "purchase_order.history": (
                "yonetim",
                "satin_alma",
                "admin",
                "superuser",
            )
        },
        step=5,
    ),
    # 5. adım — Personel maliyetinden açılan yeni gider oranının notunda tutar yerine bordro
    # numarası yazar.
    *_cells(
        "§8 madde 8",
        "probe_prices",
        {
            "costing.labor_rate.detail": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
    ),
    *_cells(
        "§8 madde 8",
        "probe_prices",
        {
            "costing.labor_rate.list": (
                "yonetim",
                "admin",
                "superuser",
            )
        },
        step=5,
    ),
    # 6. adım — Kişiye özel ayarlar ve paket sürümleri denetim günlüğünde yalnız admine görünür
    # (plan §5.6); yönetimin 1. adımdaki kaydı 5. adımda biter.
    *_cells(
        "yeni model: kişiye özel yetki ve paket sürümü (plan §5.2, §5.6)",
        "probe_audit",
        {
            "model: core.accessoverride": ("yonetim",),
            "model: core.accesscatalogsnapshot": ("yonetim",),
        },
        step=6,
        old=MISSING,
        new="absent",
    ),
    # 6. adım — Rapor dosyası indirilirken raporun yetkisi yeniden denetlenir: dosyayı istedikten
    # sonra yetkisini kaybeden kişi indiremez. İş ayrıntısı ve listeler değişmez.
    *_cells(
        "§8 madde 12",
        "probe_reports",
        {
            "job.filling.stale.download": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "job.production.stale.download": (
                "no_role",
                "depo",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "job.quality.stale.download": (
                "no_role",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "job.shipments.stale.download": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "job.stock-movements.stale.download": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
            ),
            "job.stock-status.stale.download": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "job.task-durations.stale.download": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
        },
        step=6,
        old="200",
    ),
    # 7. adım — Yükten gelen bildirim alıcıları da yetkiyle süzülür (ör. siparişi açan kişi).
    *_cells(
        "§8 madde 10",
        "probe_workflow",
        {
            "notify shipment_dispatched: payload user notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            )
        },
        step=7,
        old=True,
        new=False,
    ),
    # 7. adım — Görevi üstlenen kişi gereken yetkisini ya da rolünü kaybederse görevi görmez ve
    # tamamlayamaz; yetkili başka bir üye tamamlar (karar 5). İptal bildirimi de aynı süzgeçten
    # geçer (plan §5.7).
    *_cells(
        "§8 madde 6",
        "probe_workflow",
        {
            "task batch_sample_analysis: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task conditional_release_approval: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task dispatch_shipment: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "task finished_qc: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task incident_review: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task incoming_qc: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_dolum: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_laboratuvar: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_planlama: claimer listed": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_uretim: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_yonetim: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task material_prep: claimer listed": (
                "no_role",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task packaging_prep: claimer listed": (
                "no_role",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task pick_shipment: claimer listed": (
                "no_role",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task plan_shipment: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "task problem_reported: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task purchase_order_approval: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task purchase_request: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "depo+sevkiyat",
            ),
            "task return_qc: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task return_rework: claimer listed": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task return_scrap: claimer listed": (
                "no_role",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task rework_order: claimer listed": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task sales_shortage: claimer listed": (
                "no_role",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task start_batch: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task start_filling: claimer listed": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "cancel filling_order_cancelled after packaging_prep: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
            ),
            "cancel filling_order_cancelled after start_filling: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
            ),
            "cancel production_order_cancelled after material_prep: claimer notified": (
                "no_role",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "cancel production_order_cancelled after start_batch: claimer notified": (
                "no_role",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "cancel purchase_order_cancelled after purchase_order_approval: claimer notified": (
                "no_role",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
            ),
            "cancel sales_order_cancelled after plan_shipment: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "cancel sales_order_cancelled after sales_shortage: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "cancel shipment_cancelled after dispatch_shipment: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "cancel shipment_cancelled after pick_shipment: claimer notified": (
                "no_role",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
        },
        step=7,
        old=True,
        new=False,
    ),
    *_cells(
        "§8 madde 6",
        "probe_workflow",
        {
            "task batch_sample_analysis: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task conditional_release_approval: claimer complete": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task dispatch_shipment: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "task finished_qc: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task incident_review: claimer complete": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task incoming_qc: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_dolum: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_laboratuvar: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_planlama: claimer complete": (
                "no_role",
                "yonetim",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_uretim: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task maintenance_work_order_yonetim: claimer complete": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task material_prep: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task packaging_prep: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task pick_shipment: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task plan_shipment: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "satin_alma",
            ),
            "task problem_reported: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task purchase_order_approval: claimer complete": (
                "no_role",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task purchase_request: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "depo+sevkiyat",
            ),
            "task return_qc: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task return_rework: claimer complete": (
                "no_role",
                "yonetim",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task return_scrap: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
            ),
            "task rework_order: claimer complete": (
                "no_role",
                "yonetim",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task sales_shortage: claimer complete": (
                "no_role",
                "yonetim",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task start_batch: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
            "task start_filling: claimer complete": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            ),
        },
        step=7,
        old=200,
    ),
    # 9. adım — "Kim neyi görür" raporu ve Excel'i: yalnız admin (plan §5.10).
    *_cells(
        "yeni uç nokta: Kim neyi görür raporu (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/access/report*": (
                "anonymous",
                "inactive",
            )
        },
        step=9,
        old=MISSING,
        new="401",
    ),
    *_cells(
        "yeni uç nokta: Kim neyi görür raporu (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/access/report*": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            )
        },
        step=9,
        old=MISSING,
        new="403",
    ),
    *_cells(
        "yeni uç nokta: Kim neyi görür raporu (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/access/report*": (
                "admin",
                "superuser",
            )
        },
        step=9,
        old=MISSING,
        new="allow",
    ),
    # 9. adım — Yetkilerim: giriş yapan herkes (plan §5.10).
    *_cells(
        "yeni uç nokta: Yetkilerim (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/auth/me/access/": (
                "anonymous",
                "inactive",
            )
        },
        step=9,
        old=MISSING,
        new="401",
    ),
    *_cells(
        "yeni uç nokta: Yetkilerim (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/auth/me/access/": (
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
        },
        step=9,
        old=MISSING,
        new="allow",
    ),
    # 9. adım — Kişinin yetki matrisi: yalnız admin (plan §5.10).
    *_cells(
        "yeni uç nokta: kişinin yetki matrisi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/": (
                "anonymous",
                "inactive",
            )
        },
        step=9,
        old=MISSING,
        new="401",
    ),
    *_cells(
        "yeni uç nokta: kişinin yetki matrisi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            )
        },
        step=9,
        old=MISSING,
        new="403",
    ),
    *_cells(
        "yeni uç nokta: kişinin yetki matrisi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/": (
                "admin",
                "superuser",
            )
        },
        step=9,
        old=MISSING,
        new="allow",
    ),
    # 9. adım — Yetki geçmişi: yalnız admin (plan §5.10).
    *_cells(
        "yeni uç nokta: yetki geçmişi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/history/": (
                "anonymous",
                "inactive",
            )
        },
        step=9,
        old=MISSING,
        new="401",
    ),
    *_cells(
        "yeni uç nokta: yetki geçmişi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/history/": (
                "no_role",
                "yonetim",
                "planlama",
                "depo",
                "uretim",
                "laboratuvar",
                "dolum",
                "sevkiyat",
                "satin_alma",
                "depo+sevkiyat",
            )
        },
        step=9,
        old=MISSING,
        new="403",
    ),
    *_cells(
        "yeni uç nokta: yetki geçmişi (plan §5.10)",
        "endpoints",
        {
            "* /api/v1/users/{*}/access/history/": (
                "admin",
                "superuser",
            )
        },
        step=9,
        old=MISSING,
        new="allow",
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
