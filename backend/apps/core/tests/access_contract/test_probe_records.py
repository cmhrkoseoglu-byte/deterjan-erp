"""Sonda: kayıt paneli, ekler, @bahsetme ve kod önerileri (plan §5.5 2. parça, §5.8).

Bu kararlar DRF izin sınıfında değil, işlevlerin içinde verilir; uç nokta anlık görüntüsü
(`test_endpoints.py`) onları görmez:

- `core.records.can_view`: kayıt türünün okuma kuralı (rol, satır kuralı, üst kayıt). Geçmiş,
  yorum, ek ve @bahsetme uç noktaları buna uyar; göremeyene kayıt yokmuş gibi yanıt verilir.
- `core.records.hidden_fields_for`: geçmişte gizlenen alanlar (lot maliyeti, sipariş tutarları).
- `core.attachments.can_add_attachment`: ek ekleme kuralı (GBF, atık, olay, yorum).
- Satır kuralları: yorumu yalnız yazanı düzenler; eki yükleyen ya da admin kaldırır; kaldırılmış
  eki yalnız admin indirir.
- Kod önerisi (`GET /coding/suggest/<tür>/`): türün yazma rolleri, yoksa yalnız admin.
- Kod değişikliği: kaydın kodunu sonradan yalnız admin değiştirir (`coding.ensure_can_change_code`).

Kayıt türleri, ek hedefleri ve kod türleri kayıt defterlerinden alınır; sayıları da denetlenir.
Satır kurallı türlerde (olay, sorun bildirimi) her persona hem kendi bildirdiği hem başkasının
bildirdiği kayıtla denenir. Değer HTTP durumu ve hata kodudur (`400 record_not_found`) ya da
evet/hayır; dosyada her durum tek satırdır (`_codes`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import records
from apps.core import services as core_services
from apps.core.attachments import attachment_targets
from apps.core.coding.registry import MASTER, CodeType, code_types
from apps.core.models import Attachment, User
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import PERSONAS, make_personas, persona_client
from apps.core.tests.factories import UserFactory
from apps.filling.models import FillingOrder, FillingRun, PackagingSpec
from apps.golive.services import report_problem
from apps.hse import services as hse_services
from apps.hse.tests.factories import contractor, report, sds, waste_data
from apps.inventory.models import GoodsReceipt, Lot, StockAdjustment
from apps.inventory.services import create_lot
from apps.inventory.tests.factories import quarantine_location, storage_location
from apps.maintenance.models import MaintenanceKind, MaintenanceWorkOrder
from apps.masterdata.models import Equipment, Material
from apps.masterdata.tests.factories import (
    BulkMaterialFactory,
    CustomerFactory,
    EquipmentFactory,
    LocationFactory,
    MaterialCategoryFactory,
    MaterialFactory,
    PrinterFactory,
    SupplierFactory,
    WarehouseFactory,
    unit,
)
from apps.production.models import ProductionBatch, ProductionOrder
from apps.purchasing.models import PurchaseOrder
from apps.quality.models import Sample, SampleStage
from apps.quality.tests.factories import tdef
from apps.recipes.tests.factories import RecipeFactory
from apps.returns.models import CustomerReturn
from apps.sales.models import SalesOrder, Shipment
from apps.workflow.models import Comment

pytestmark = pytest.mark.django_db

NAME = "probe_records"
API = "/api/v1"
HISTORY = f"{API}/workflow/record-history/"
COMMENTS = f"{API}/workflow/comments/"
MENTIONABLE = f"{API}/workflow/mentionable-users/"
ATTACHMENTS = f"{API}/attachments/"
SUGGEST = f"{API}/coding/suggest/"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
COMMENT = "workflow.comment"
ACTIVE_FILE, REMOVED_FILE = "etkin.png", "kaldirilmis.png"

# Bugünkü kayıt defterleri. Yeni tür eklenince sayı ve sonda kaydı (BUILDERS) birlikte güncellenir.
RECORD_TYPE_COUNT = 19
ATTACHMENT_TARGET_COUNT = 8
CODE_TYPE_COUNT = 32
# `visible` satır kuralı olan türler: bildiren kendi kaydını görür (`created_by`).
ROW_RULE_TYPES = frozenset({"golive.problemreport", "hse.incident"})
# Satır kurallarının (yorumu yazan düzenler, eki yükleyen ya da admin kaldırır, kaldırılmış
# eki admin indirir) yorumlarda denendiği kayıtlar: herkesin okuduğu, rolün okuduğu, kendi
# bildirdiği ve başkasının bildirdiği kayıt.
RULE_SAMPLE = (
    "inventory.lot",
    "purchasing.purchaseorder",
    "hse.incident (own)",
    "golive.problemreport (other's)",
)
# Ana veri kod türlerinin güncelleme uç noktası ve sonda kaydı (kod değişikliği).
CODE_CHANGE: dict[str, tuple[str, Callable[[], Any]]] = {
    "masterdata.customer": ("masterdata/customers", CustomerFactory.create),
    "masterdata.equipment": ("masterdata/equipment", EquipmentFactory.create),
    "masterdata.location": ("masterdata/locations", LocationFactory.create),
    "masterdata.material": ("masterdata/materials", MaterialFactory.create),
    "masterdata.materialcategory": ("masterdata/categories", MaterialCategoryFactory.create),
    "masterdata.printer": ("masterdata/printers", PrinterFactory.create),
    "masterdata.supplier": ("masterdata/suppliers", SupplierFactory.create),
    "masterdata.warehouse": ("masterdata/warehouses", WarehouseFactory.create),
    "quality.testdefinition": ("quality/tests", lambda: tdef("PH")),
    "recipes.recipe": ("recipes/recipes", RecipeFactory.create),
}
# Yalnız testlerde yüklenen uygulamanın kayıtları (core/tests/testapp/apps.py); sondaya girmez.
TEST_APP_RECORD_TYPES = frozenset({"core_testapp.widget"})
TEST_APP_CODE_TYPES = frozenset(
    {
        "core_testapp.widget",
        "core_testapp.typedwidget",
        "document.TD",
        "document.TK",
        "document.TZ",
        "lot.Q",
    }
)

# Dosyada her durum tek satırdır: personaların değerleri PERSONAS sırasıyla birer harf. Sözlükte
# olmayan bir değer çıkarsa o durum persona → değer eşlemesi olarak yazılır.
LEGEND: dict[str, Any] = {
    "-": None,  # persona için kayıt yok (anonimin kendi bildirdiği kayıt)
    "0": False,
    "1": True,
    "a": "200",
    "c": "201",
    "u": "401 not_authenticated",
    "f": "403 permission_denied",
    "4": "404 not_found",
    "n": "400 record_not_found",
    "t": "400 invalid_record_type",
    "x": "400 attachment_forbidden",
}
CODES = {value: code for code, value in LEGEND.items()}


def encode(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {"_personas": list(PERSONAS), "_codes": LEGEND}
    for case, values in cases.items():
        letters = [CODES.get(values[persona], "?") for persona in PERSONAS]
        data[case] = "".join(letters) if "?" not in letters else dict(values)
    return data


def decode(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    personas, legend = data["_personas"], data["_codes"]
    return {
        case: (
            {persona: legend[code] for persona, code in zip(personas, value, strict=True)}
            if isinstance(value, str)
            else dict(value)
        )
        for case, value in data.items()
        if not case.startswith("_")
    }


# --- kayıt defterleri ----------------------------------------------------------------------------


def record_types() -> list[str]:
    labels = set(records.registered_record_types())
    assert labels >= TEST_APP_RECORD_TYPES
    return sorted(labels - TEST_APP_RECORD_TYPES)


def row_rule_types() -> set[str]:
    rules = {label: records.record_access(label) for label in record_types()}
    return {label for label, rule in rules.items() if rule is not None and rule.visible is not None}


def probed_code_types() -> list[CodeType]:
    items = code_types()
    assert {item.key for item in items} >= TEST_APP_CODE_TYPES
    return [item for item in items if item.key not in TEST_APP_CODE_TYPES]


# --- sonda kayıtları -----------------------------------------------------------------------------


class Kit:
    """Kayıtların ortak ana verileri. Kayıtlar en az alanla kurulur: okuma kuralı kaydın durumuna
    bakmaz (satır kuralında yalnız bildirene)."""

    def __init__(self, owner: User) -> None:
        self.owner = owner  # başkasının kaydı, yorumu ve eki (admin)
        self.today = timezone.localdate()
        self.location = storage_location()
        self.tank = EquipmentFactory.create()
        self.bulk = BulkMaterialFactory.create()
        self.product = MaterialFactory.create(
            material_type=Material.Type.FINISHED, base_unit=unit("ADET")
        )
        self._serial = 0

    def next(self) -> int:
        self._serial += 1
        return self._serial

    def number(self, prefix: str) -> str:
        return f"SONDA-{prefix}-{self.next()}"

    def lot(self, material: Material | None = None) -> Lot:
        return create_lot(
            None,
            material=material or MaterialFactory.create(),
            source=Lot.Source.PURCHASE,
            status=Lot.Status.RELEASED,
        )


def _production_order(kit: Kit) -> ProductionOrder:
    return ProductionOrder.objects.create(
        number=kit.number("UE"),
        status="DRAFT",
        product=kit.bulk,
        planned_quantity=Decimal("1000"),
        unit=unit("KG"),
        planned_base_quantity=Decimal("1000"),
        planned_date=kit.today,
        equipment=kit.tank,
        production_location=kit.location,
        rework_lot=kit.lot(kit.bulk),
    )


def _production_batch(kit: Kit) -> ProductionBatch:
    return ProductionBatch.objects.create(
        order=_production_order(kit),
        sequence=1,
        batch_no=kit.number("B"),
        equipment=kit.tank,
        planned_quantity=Decimal("1000"),
        output_lot=kit.lot(kit.bulk),
        started_at=timezone.now(),
    )


def _packaging_spec(kit: Kit) -> PackagingSpec:
    return PackagingSpec.objects.create(
        finished_product=kit.product,
        bulk_product=kit.bulk,
        version_no=kit.next(),
        fill_quantity=Decimal("1"),
        fill_unit=unit("LT"),
        units_per_case=12,
    )


def _filling_order(kit: Kit) -> FillingOrder:
    return FillingOrder.objects.create(
        number=kit.number("DO"),
        status="DRAFT",
        finished_product=kit.product,
        packaging_spec=_packaging_spec(kit),
        planned_units=100,
        filling_line=EquipmentFactory.create(equipment_type=Equipment.Type.FILLING_LINE),
        output_location=kit.location,
        planned_date=kit.today,
    )


def _filling_run(kit: Kit) -> FillingRun:
    return FillingRun.objects.create(
        order=_filling_order(kit),
        sequence=1,
        output_lot=kit.lot(kit.product),
        started_at=timezone.now(),
    )


def _sales_order(kit: Kit) -> SalesOrder:
    return SalesOrder.objects.create(
        number=kit.number("SS"),
        status="DRAFT",
        customer=CustomerFactory.create(),
        order_date=kit.today,
    )


BUILDERS: dict[str, Callable[[Kit], models.Model]] = {
    "filling.fillingorder": _filling_order,
    "filling.fillingrun": _filling_run,
    "filling.packagingspec": _packaging_spec,
    "hse.safetydatasheet": lambda kit: sds(kit.owner, MaterialFactory.create(), with_file=False),
    "hse.wasterecord": lambda kit: hse_services.record_waste(
        kit.owner, waste_data(contractor(kit.owner))
    ),
    "inventory.goodsreceipt": lambda kit: GoodsReceipt.objects.create(
        number=kit.number("MK"),
        status="DRAFT",
        supplier=SupplierFactory.create(),
        receipt_date=kit.today,
    ),
    "inventory.lot": lambda kit: kit.lot(),
    "inventory.stockadjustment": lambda kit: StockAdjustment.objects.create(
        number=kit.number("SD"), status="DRAFT", adjustment_date=kit.today
    ),
    "maintenance.maintenanceworkorder": lambda kit: MaintenanceWorkOrder.objects.create(
        number=kit.number("BK"),
        status="OPEN",
        equipment=kit.tank,
        source=MaintenanceWorkOrder.Source.MANUAL,
        kind=MaintenanceKind.REPAIR,
        title="Sonda",
        responsible_role="uretim",
    ),
    "production.productionbatch": _production_batch,
    "production.productionorder": _production_order,
    "purchasing.purchaseorder": lambda kit: PurchaseOrder.objects.create(
        number=kit.number("SA"),
        status="DRAFT",
        supplier=SupplierFactory.create(),
        order_date=kit.today,
    ),
    "quality.sample": lambda kit: Sample.objects.create(
        number=kit.number("NM"), status="PENDING", lot=kit.lot(), stage=SampleStage.INCOMING
    ),
    "returns.customerreturn": lambda kit: CustomerReturn.objects.create(
        number=kit.number("IA"),
        status="DRAFT",
        customer=CustomerFactory.create(),
        return_date=kit.today,
        reason="Sonda",
        quarantine_location=quarantine_location(),
    ),
    "sales.salesorder": _sales_order,
    "sales.shipment": lambda kit: Shipment.objects.create(
        number=kit.number("SV"),
        status="PLANNED",
        sales_order=_sales_order(kit),
        planned_date=kit.today,
        loading_location=kit.location,
    ),
}


def _reported_by[M: models.Model](record: M, reporter: User) -> M:
    """Kaydın bildirenini personaya çevirir. Rolü olmayan ya da pasif kişi bugün olay
    bildiremez; kayıt, rolünü ya da etkinliğini sonradan kaybeden kişinin kaydı gibi kurulur."""
    model = type(record)
    model._base_manager.filter(pk=record.pk).update(created_by=reporter)
    return model._base_manager.get(pk=record.pk)


ROW_BUILDERS: dict[str, Callable[[Kit, User], models.Model]] = {
    "golive.problemreport": lambda kit, reporter: _reported_by(
        report_problem(kit.owner, description="Sonda: sorun"), reporter
    ),
    "hse.incident": lambda kit, reporter: _reported_by(report(kit.owner), reporter),
}


@dataclass(frozen=True)
class Subject:
    """Sondadaki bir kayıt: her persona için denenen kayıt (anonimin kendi kaydı yok: `None`)."""

    name: str
    label: str
    objects: Mapping[str, models.Model | None]


def _shared(name: str, label: str, obj: models.Model) -> Subject:
    return Subject(name, label, dict.fromkeys(PERSONAS, obj))


def record_subjects(kit: Kit, users: Mapping[str, User | None]) -> list[Subject]:
    """Yorum paneli açılan her tür; satır kurallı türde kendi ve başkasının kaydı."""
    subjects: list[Subject] = []
    for label in record_types():
        if label == COMMENT:
            continue
        if label in ROW_BUILDERS:
            build_row = ROW_BUILDERS[label]
            own = {p: None if u is None else build_row(kit, u) for p, u in users.items()}
            subjects.append(Subject(f"{label} (own)", label, own))
            subjects.append(_shared(f"{label} (other's)", label, build_row(kit, kit.owner)))
            continue
        build = BUILDERS.get(label)
        assert build is not None, f"Sonda kaydı yok: {label}; BUILDERS'a ekleyin."
        subjects.append(_shared(label, label, build(kit)))
    return subjects


def _comment(author: User, target: models.Model) -> Comment:
    return Comment.objects.create(
        content_type=ContentType.objects.get_for_model(target),
        object_id=target.pk,
        author=author,
        body="Sonda yorumu",
    )


def comment_subjects(
    subjects: list[Subject], authors: Mapping[str, User | None], tag: str
) -> list[Subject]:
    """Her kaydın yorumu: `authors[persona]` yazmış (`None`: yorum yok)."""
    out: list[Subject] = []
    for subject in subjects:
        made: dict[tuple[int, int], Comment] = {}
        objects: dict[str, models.Model | None] = {}
        for persona in PERSONAS:
            target, author = subject.objects[persona], authors[persona]
            if target is None or author is None:
                objects[persona] = None
                continue
            key = (author.pk, target.pk)
            if key not in made:
                made[key] = _comment(author, target)
            objects[persona] = made[key]
        out.append(Subject(f"{COMMENT}{tag} on {subject.name}", COMMENT, objects))
    return out


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def _upload(actor: User, target: models.Model, name: str) -> Attachment:
    return core_services.add_attachment(
        actor, target_type=target._meta.label_lower, object_id=target.pk, file=_png(name)
    )


def _bare_attachment(uploader: User, target: models.Model) -> Attachment:
    """Dosyası yazılmamış ek (kaldırma dosyayı açmaz)."""
    return Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(target),
        object_id=target.pk,
        file="sonda/kaldir.png",
        original_name="kaldir.png",
        size=1,
        mime_type="image/png",
        created_by=uploader,
    )


# --- sonda ---------------------------------------------------------------------------------------


def outcome(response: Any) -> str:
    """`200`, `201` ya da `<durum> <hata kodu>` (ör. `400 record_not_found`)."""
    if response.status_code < 400:
        return str(response.status_code)
    return f"{response.status_code} {response.json().get('code', '')}".strip()


def params(target: models.Model, **extra: str) -> dict[str, str]:
    return {"content_type": target._meta.label_lower, "object_id": str(target.pk), **extra}


Call = Callable[[APIClient, models.Model, str], Any]


class Probe:
    def __init__(self, users: Mapping[str, User | None]) -> None:
        self.users = users
        self.clients: dict[str, APIClient] = {}
        for persona, user in users.items():
            self.clients[persona] = persona_client(user)
        self.admin = self.clients["admin"]
        self.cases: dict[str, dict[str, Any]] = {}

    def record(self, surface: str, subject: str, values: dict[str, Any]) -> None:
        case = f"{surface} | {subject}"
        assert case not in self.cases, case
        self.cases[case] = values

    def each(self, surface: str, subjects: list[Subject], call: Call) -> None:
        """Her persona kendi istemcisiyle, kendisi için kurulan kayıtta (değer: `outcome`)."""
        for subject in subjects:
            values: dict[str, Any] = dict.fromkeys(PERSONAS)
            for persona in PERSONAS:
                target = subject.objects[persona]
                if target is not None:
                    result = call(self.clients[persona], target, persona)
                    values[persona] = result if isinstance(result, str) else outcome(result)
            self.record(surface, subject.name, values)


def probe_read_rules(probe: Probe, subjects: list[Subject]) -> None:
    """Kayıt defterinin kararı doğrudan (`core.records`): okuma ve geçmişte gizlenen alanlar."""
    for subject in subjects:
        values: dict[str, Any] = dict.fromkeys(PERSONAS)
        for persona in PERSONAS:
            target = subject.objects[persona]
            if target is not None:
                user = probe.users[persona] or AnonymousUser()
                values[persona] = records.can_view(user, target)
        probe.record("can_view", subject.name, values)
    for label in record_types():
        hidden = {
            persona: records.hidden_fields_for(user or AnonymousUser(), label)
            for persona, user in probe.users.items()
        }
        fields: set[str] = set()
        for names in hidden.values():
            fields |= names
        for field in sorted(fields):
            values = {persona: field in hidden[persona] for persona in PERSONAS}
            probe.record("history hides", f"{label}.{field}", values)


def probe_panel(probe: Probe, subjects: list[Subject]) -> None:
    """Kayıt paneli: geçmiş, yorum listesi, yorum yazma ve @bahsetme isteği (isteyenin okuması)."""

    def create(client: APIClient, target: models.Model, persona: str) -> Any:
        return client.post(COMMENTS, {**params(target), "body": "Sonda yorumu"}, format="json")

    probe.each("history", subjects, lambda c, t, p: c.get(HISTORY, params(t)))
    probe.each("comments.list", subjects, lambda c, t, p: c.get(COMMENTS, params(t)))
    probe.each("comments.create", subjects, create)
    probe.each("mentions.request", subjects, lambda c, t, p: c.get(MENTIONABLE, params(t)))


def _offered(admin: APIClient, user: User, query: dict[str, str]) -> bool:
    """Kullanıcı adıyla arayınca kişi öneride mi (liste en çok 10 kişi; ad tek kişiyi seçer)."""
    response = admin.get(MENTIONABLE, query)
    assert response.status_code == 200, response.content
    return user.username in {row["username"] for row in response.json()}


def probe_mentions(probe: Probe, subjects: list[Subject]) -> None:
    """Kimden bahsedilebilir: öneride (`mentions.offered`) ve yorumda bahsedilince
    (`mentions.notified`, bildirim gider). İsteyen ve yazan admin; değer bahsedilen persona için."""
    for subject in subjects:
        offered: dict[str, Any] = dict.fromkeys(PERSONAS)
        notified: dict[str, Any] = dict.fromkeys(PERSONAS)
        # Aynı kayıtta bahsedilecek personalar tek yorumda: kayıt no → (kayıt, {persona: ad}).
        groups: dict[int, tuple[models.Model, dict[str, str]]] = {}
        for persona in PERSONAS:
            target, user = subject.objects[persona], probe.users[persona]
            if target is None or user is None:
                continue
            offered[persona] = _offered(probe.admin, user, params(target, search=user.username))
            groups.setdefault(target.pk, (target, {}))[1][persona] = user.username
        for target, names in groups.values():
            body = " ".join(f"@{name}" for name in names.values())
            response = probe.admin.post(COMMENTS, {**params(target), "body": body}, format="json")
            assert response.status_code == 201, (subject.name, response.content)
            mentioned = {row["username"] for row in response.json()["mentions"]}
            for persona, name in names.items():
                notified[persona] = name in mentioned
        probe.record("mentions.offered", subject.name, offered)
        probe.record("mentions.notified", subject.name, notified)

    # Kayıt verilmezse etkin kullanıcıların hepsi önerilir.
    probe.record(
        "mentions.offered",
        "(no record)",
        {
            persona: None
            if user is None
            else _offered(probe.admin, user, {"search": user.username})
            for persona, user in probe.users.items()
        },
    )


def probe_comments(probe: Probe, comments: list[Subject], editable: list[Subject]) -> None:
    """Tek yorum: okuma, bağlı olduğu kaydın kuralıyla (her türde); düzenleme, yalnız yazan
    (örnek kayıtlarda başkasının ve kendi yorumu)."""

    def edit(client: APIClient, comment: models.Model, persona: str) -> Any:
        body = {"body": f"Sonda düzeltmesi: {persona}"}
        return client.patch(f"{COMMENTS}{comment.pk}/", body, format="json")

    probe.each("comments.retrieve", comments, lambda c, t, p: c.get(f"{COMMENTS}{t.pk}/"))
    probe.each("comments.edit", editable, edit)


def _key(target: models.Model) -> tuple[str, int]:
    return target._meta.label_lower, target.pk


def _download(client: APIClient, attachment: Attachment) -> str:
    response: Any = client.get(f"{ATTACHMENTS}{attachment.pk}/download/")
    if response.streaming:
        # Dosyayı sonuna kadar okumak tutamağı kapatır (test istemcisi bağlantıyı korur).
        b"".join(response.streaming_content)
    return outcome(response)


def probe_attachments(
    probe: Probe, kit: Kit, subjects: list[Subject], rows: list[Subject], own: list[Subject]
) -> None:
    """Ekler. `subjects`: ek alan her kayıt (liste, ekleme); `rows`: satır kurallarının denendiği
    kayıtlar (indirme, kaldırılmış eki indirme, kaldırma); `own`: personanın kendi yorumu (yoruma
    eki yalnız yazan ekler). Her kayıtta admin'in yüklediği bir etkin ve bir kaldırılmış ek var."""
    active: dict[tuple[str, int], Attachment] = {}
    removed: dict[tuple[str, int], Attachment] = {}
    for subject in subjects:
        for target in subject.objects.values():
            if target is not None and _key(target) not in active:
                active[_key(target)] = _upload(kit.owner, target, ACTIVE_FILE)
                upload = _upload(kit.owner, target, REMOVED_FILE)
                removed[_key(target)] = core_services.remove_attachment(kit.owner, upload, "Sonda")

    for subject in subjects:
        listed: dict[str, Any] = dict.fromkeys(PERSONAS)
        shows_removed: dict[str, Any] = dict.fromkeys(PERSONAS)
        can_remove: dict[str, Any] = dict.fromkeys(PERSONAS)
        for persona in PERSONAS:
            target = subject.objects[persona]
            if target is None:
                continue
            client = probe.clients[persona]
            response = client.get(ATTACHMENTS, params(target, include_removed="true"))
            listed[persona] = outcome(response)
            if response.status_code == 200:
                files = {row["original_name"]: row for row in response.json()}
                shows_removed[persona] = REMOVED_FILE in files
                can_remove[persona] = files[ACTIVE_FILE]["can_remove"]
        probe.record("attachments.list", subject.name, listed)
        probe.record("attachments.list shows removed", subject.name, shows_removed)
        probe.record("attachments.list can_remove", subject.name, can_remove)

    def add(client: APIClient, target: models.Model, persona: str) -> Any:
        body = {**params(target), "file": _png("ek.png")}
        return client.post(ATTACHMENTS, body, format="multipart")

    probe.each("attachments.add", subjects + own, add)
    probe.each("attachments.download", rows, lambda c, t, p: _download(c, active[_key(t)]))
    probe.each("attachments.download removed", rows, lambda c, t, p: _download(c, removed[_key(t)]))

    def remove(own_upload: bool) -> Call:
        """Her deneme yeni bir eki kaldırır: yükleyen admin ya da personanın kendisi."""

        def call(client: APIClient, target: models.Model, persona: str) -> Any:
            uploader = probe.users[persona] if own_upload else kit.owner
            assert uploader is not None
            attachment = _bare_attachment(uploader, target)
            return client.post(f"{ATTACHMENTS}{attachment.pk}/remove/", {"reason": "Sonda"})

        return call

    probe.each("attachments.remove (other's upload)", rows, remove(own_upload=False))
    uploads = [
        Subject(s.name, s.label, {p: s.objects[p] if probe.users[p] else None for p in PERSONAS})
        for s in rows
    ]
    probe.each("attachments.remove (own upload)", uploads, remove(own_upload=True))


def probe_code_suggestions(probe: Probe) -> None:
    """Sıradaki kod önerisi: karar görünümün içinde (türün yazma rolleri, yoksa yalnız admin)."""
    for item in probed_code_types():
        values = {
            persona: outcome(client.get(f"{SUGGEST}{item.key}/"))
            for persona, client in probe.clients.items()
        }
        probe.record("coding.suggest", item.key, values)


def probe_code_changes(probe: Probe) -> None:
    """Kaydın kodunu sonradan yalnız admin değiştirir (`masterdata.update_record` içinde
    `coding.ensure_can_change_code`). Her persona kendi yeni koduyla dener."""
    for key, (path, build) in sorted(CODE_CHANGE.items()):
        record = build()
        values = {
            persona: outcome(
                client.patch(
                    f"{API}/{path}/{record.pk}/", {"code": f"{record.code}Z{index}"}, format="json"
                )
            )
            for index, (persona, client) in enumerate(probe.clients.items())
        }
        probe.record("coding.change_code", key, values)


def current_cases() -> dict[str, dict[str, Any]]:
    users = make_personas()
    owner = UserFactory.create(username="probe_owner", roles=["admin"])
    kit = Kit(owner)
    probe = Probe(users)

    subjects = record_subjects(kit, users)
    comments = comment_subjects(subjects, dict.fromkeys(PERSONAS, owner), "")
    # Yorumun kendi paneli açılmaz (yorum yalnız ek alır): panel bu türü reddeder.
    lot_comment = next(s for s in comments if s.name == f"{COMMENT} on inventory.lot")
    probe_read_rules(probe, subjects + comments)
    probe_panel(probe, [*subjects, Subject(COMMENT, COMMENT, lot_comment.objects)])
    probe_mentions(probe, subjects)

    # Yorum ve ekin satır kuralları kaydın türüne bakmaz: okuma kuralının her biçiminden bir
    # kayıtta denenir. Yorumun okuması her türde ayrıca denenir (`comments.retrieve`, ekler).
    sample = [s for s in subjects if s.name in RULE_SAMPLE]
    assert len(sample) == len(RULE_SAMPLE)
    on_sample = [c for c in comments if c.name.removeprefix(f"{COMMENT} on ") in RULE_SAMPLE]
    own_comments = comment_subjects(sample, users, " (own)")
    probe_comments(probe, comments, on_sample + own_comments)

    targets = set(attachment_targets())
    record_targets = [s for s in subjects if s.label in targets]
    commented = COMMENT in targets
    probe_attachments(
        probe,
        kit,
        record_targets + (comments if commented else []),
        rows=record_targets + (on_sample if commented else []),
        own=own_comments if commented else [],
    )
    probe_code_suggestions(probe)
    probe_code_changes(probe)
    return probe.cases


def test_registries_are_fully_probed() -> None:
    """Yeni kayıt türü, ek hedefi ya da kod türü eklenince sonda da genişletilmelidir."""
    labels = record_types()
    assert len(labels) == RECORD_TYPE_COUNT, labels
    assert set(labels) == set(BUILDERS) | set(ROW_BUILDERS) | {COMMENT}
    assert row_rule_types() == set(ROW_BUILDERS) == ROW_RULE_TYPES
    targets = attachment_targets()
    assert len(targets) == ATTACHMENT_TARGET_COUNT, targets
    assert set(targets) <= set(labels)
    keys = [item.key for item in probed_code_types()]
    assert len(keys) == CODE_TYPE_COUNT, keys
    masters = {item.key for item in probed_code_types() if item.kind == MASTER}
    assert set(CODE_CHANGE) == masters, masters


def test_record_panel_matches_snapshot() -> None:
    snapshot.check(NAME, current_cases(), encode=encode, decode=decode)
