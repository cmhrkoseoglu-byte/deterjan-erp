"""Sonda: panolar ve raporlar (plan §5.5 2. parça, §3.15; §8 madde 12).

Raporlama uç noktaları giriş yapan herkese açıktır (`endpoints.json`); kimin neyi gördüğüne
görünümün ve servisin içinde karar verilir (`reporting/api/views.py`, `reporting/reports.py`,
`reporting/services.py`). Bu sonda o kararları 14 personayla, API üzerinden dondurur:

- panolar: listede görünen ve açılan panolar; yönetim panosundaki stok değeri ve onay bekleyen
  satın alma siparişlerinin TL toplamı; her panonun admin'in gördüğünden farkı;
- raporlar: listede görünen ve açılan raporlar; ekranda, Excel'de ve PDF'te görünen sütunlar ve
  özet satırları (maliyet sütunları, TL toplamı); satırlardaki alanlar ve satır sayısı;
- rapor dosyaları (arka plan işi): kişi yalnız kendi dosyasını görür ve indirir. "stale" dosya,
  admin'in tam yetkiyle hazırlayıp kişiye geçirilmiş dosyasıdır (yetkisi sonradan değişen kişinin
  eski dosyası gibi); bugün yeniden denetlenmeden iner, §8 madde 12 bunu değiştirir.

Değerler metindir:
- "-": persona buna erişemez ya da durum ona uygulanmaz; "none": boş liste;
- sütunlar rapor tanımına göre: "all" tanımdaki bütün sütunlar, "-x" gizli, "+x" tanımda yok;
- pano farkı admin'e göre: "same" ya da "yol:admin>persona" (tür ya da boş değer), "-yol" (eksik),
  "+yol" (fazla), "yol[]:fewer" / "yol[]:more" (liste boyu). Değerlerin kendisi karşılaştırılmaz.
"""

import io
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.models import User
from apps.core.roles import SATIN_ALMA
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import PERSONAS, make_personas
from apps.inventory.services import set_lot_cost
from apps.inventory.tests.factories import stocked_lot
from apps.purchasing import services as purchasing
from apps.purchasing.tests.factories import draft_order, line, raw_material
from apps.reporting import exports
from apps.reporting import services as reporting
from apps.reporting.api.views import DASHBOARDS
from apps.reporting.models import ReportJob
from apps.reporting.reports import REPORTS, Column, ReportDefinition

# Raporlama testlerinin gerçek akışı (mal kabulden sevkiyata): her raporda satır olur.
from apps.reporting.tests.conftest import chain, commit, staff  # noqa: F401

pytestmark = pytest.mark.django_db

NAME = "probe_reports"
BASE = "/api/v1/reporting"
PAGE = {"page_size": 500}
NONE = "-"
EMPTY = "none"
# Bugünkü kayıt defterleri; yeni pano ya da rapor bu sayıları ve anlık görüntüyü değiştirir.
DASHBOARD_COUNT = 5
REPORT_COUNT = 7
# Tutar taşıyan pano alanları: bugün yalnız yönetim panosunda (Karar D-15). Öteki panolarda
# tutar yok; onların farkı `vs_admin` durumunda izlenir.
MONEY_FIELDS: dict[str, tuple[str, ...]] = {
    "management": ("stock_value", "approvals.purchase_orders.total_try"),
}
REPORT_FIELDS = (
    "list_columns",
    "page.status",
    "page.columns",
    "page.row_keys",
    "page.row_count",
    "page.summary",
    "xlsx.status",
    "xlsx.columns",
    "xlsx.summary",
    "pdf.status",
    "pdf.columns",
    "pdf.summary",
)
FORMAT_NOTE = (
    "Her durum: {değer: o değeri alan personalar}. Değerlerin anlamı test_probe_reports.py "
    "başındaki açıklamada."
)

Capture = Callable[..., AbstractContextManager[Any]]
Cases = dict[str, dict[str, str]]
PdfCall = tuple[list[str], list[str]]


# --- anlık görüntü dosyası -------------------------------------------------------------------


def encode(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Dosyada her durum `{değer: "persona persona ..."}` biçimindedir (PERSONAS sırasıyla)."""
    data: dict[str, Any] = {"_format": FORMAT_NOTE}
    for case, values in cases.items():
        groups: dict[str, list[str]] = {}
        for persona in PERSONAS:
            value = values[persona]
            assert isinstance(value, str), (case, persona, value)
            groups.setdefault(value, []).append(persona)
        data[case] = {value: " ".join(names) for value, names in groups.items()}
    return data


def decode(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        case: {persona: value for value, names in groups.items() for persona in names.split()}
        for case, groups in data.items()
        if not case.startswith("_")
    }


# --- yardımcılar -----------------------------------------------------------------------------


def words(items: Iterable[str]) -> str:
    values = sorted(items)
    return " ".join(values) if values else EMPTY


def columns_text(all_keys: Sequence[str], seen: Iterable[str]) -> str:
    """Görünen sütunlar, tanımdaki sütunlara göre: "all", ardından "-gizli" ve "+fazla"."""
    shown = set(seen)
    tokens = [f"-{key}" for key in sorted(set(all_keys) - shown)]
    tokens += [f"+{key}" for key in sorted(shown - set(all_keys))]
    return " ".join(["all", *tokens])


def compare(count: int, reference: int) -> str:
    if count == reference:
        return "same"
    return "fewer" if count < reference else "more"


def kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return "value"


def tree_diff(reference: Any, actual: Any, path: str = "") -> set[str]:
    """`actual`ın `reference`tan yapı farkları: eksik ya da fazla alan, tür (boş değer dahil) ve
    liste boyu. Değerler karşılaştırılmaz (bekleme süreleri istek zamanına bağlıdır)."""
    if kind(reference) != kind(actual):
        return {f"{path}:{kind(reference)}>{kind(actual)}"}
    found: set[str] = set()
    if isinstance(reference, dict):
        for key in sorted(set(reference) | set(actual)):
            sub = f"{path}.{key}" if path else key
            if key not in actual:
                found.add(f"-{sub}")
            elif key not in reference:
                found.add(f"+{sub}")
            else:
                found |= tree_diff(reference[key], actual[key], sub)
    elif isinstance(reference, list):
        if len(actual) != len(reference):
            found.add(f"{path}[]:{compare(len(actual), len(reference))}")
        for ref_item, act_item in zip(reference, actual, strict=False):
            found |= tree_diff(ref_item, act_item, f"{path}[]")
    return found


def diff_text(reference: Any, actual: Any) -> str:
    found = tree_diff(reference, actual)
    return " ".join(sorted(found)) if found else "same"


def presence(body: Any, path: str) -> str:
    """Alanın durumu: "value", "null" ya da "absent" (anahtar yok)."""
    value = body
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return "absent"
        value = value[key]
    return "null" if value is None else "value"


def content(response: Any) -> bytes:
    if response.streaming:
        return b"".join(response.streaming_content)
    return bytes(response.content)


def xlsx_layout(data: bytes, filter_count: int) -> tuple[list[str], list[str]]:
    """Excel dosyasının (tablo başlığı, özet etiketleri). Düzen `reporting.exports.to_xlsx`:
    başlık, rapor zamanı, filtreler, özet, boş satır, tablo başlığı, satırlar."""
    rows = list(load_workbook(io.BytesIO(data)).active.iter_rows(values_only=True))
    blank = next(i for i, row in enumerate(rows) if i > 0 and all(c is None for c in row))
    summary = [str(row[0]) for row in rows[2 + filter_count : blank]]
    header = [str(cell) for cell in rows[blank + 1] if cell is not None]
    return header, summary


def column_keys(definition: ReportDefinition, labels: Sequence[str]) -> list[str]:
    """Tablo başlığındaki etiketlerden sütun anahtarları. Tanımın sırası izlenir (QC raporunda iki
    sütunun adı "Karar"dır); tanımda olmayan etiket "?etiket" olur."""
    columns = list(definition.columns)
    keys: list[str] = []
    position = 0
    for label in labels:
        match = next((i for i in range(position, len(columns)) if columns[i].label == label), None)
        if match is None:
            keys.append(f"?{label}")
        else:
            keys.append(columns[match].key)
            position = match + 1
    return keys


def summary_keys(definition: ReportDefinition, labels: Sequence[str]) -> list[str]:
    inverse = {label: key for key, label in definition.summary_labels.items()}
    return [inverse.get(label, f"?{label}") for label in labels]


def clients_for(users: Mapping[str, User | None]) -> dict[str, APIClient]:
    clients: dict[str, APIClient] = {}
    for persona, user in users.items():
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        clients[persona] = client
    return clients


def export(client: APIClient, code: str, file_format: str, capture: Capture) -> Any:
    """Rapor dosyası ister; arka plan işi commit sonrası hemen çalışır (Celery eager)."""
    with capture(execute=True):
        return client.post(
            f"{BASE}/reports/{code}/export/", {"file_format": file_format}, format="json"
        )


def spy_pdf(monkeypatch: pytest.MonkeyPatch) -> list[PdfCall]:
    """PDF'e yazılan sütun ve özet anahtarlarını yakalar (`reporting.exports.to_pdf`). PDF'teki
    metin yazı tipi alt kümesiyle kodlandığından dosyadan okunamaz."""
    calls: list[PdfCall] = []
    original = exports.to_pdf

    def to_pdf(
        title: str, columns: Sequence[Column], rows: Iterable[dict[str, Any]], **kwargs: Any
    ) -> bytes:
        summary = kwargs.get("summary", ())
        calls.append(([c.key for c in columns], [str(item["key"]) for item in summary]))
        return original(title, columns, rows, **kwargs)

    monkeypatch.setattr(exports, "to_pdf", to_pdf)
    return calls


def money_data(make_user: Callable[..., User]) -> None:
    """Tutarlı veri: maliyetli bir lot ve onay bekleyen bir satın alma siparişi."""
    set_lot_cost(None, stocked_lot("10"), Decimal("2.5"), estimated=False)
    buyer = make_user(SATIN_ALMA)
    order = draft_order(buyer, [line(raw_material(), quantity="500", price="12")])
    purchasing.submit_for_approval(buyer, order)


@pytest.fixture
def report_files(db: None) -> Iterator[None]:
    """Sondanın ürettiği rapor dosyalarını test sonunda siler."""
    yield
    for job in ReportJob.objects.exclude(file=""):
        job.file.delete(save=False)


# --- panolar ---------------------------------------------------------------------------------


def dashboard_cases(clients: Mapping[str, APIClient]) -> Cases:
    """Pano listesi; her pano için açılır mı, admin'in gördüğünden farkı ve tutar alanları."""
    cases: Cases = {"dashboards.list": {}}
    for persona, client in clients.items():
        response = client.get(f"{BASE}/dashboards/")
        cases["dashboards.list"][persona] = (
            words(item["code"] for item in response.json())
            if response.status_code == 200
            else str(response.status_code)
        )
    for code in DASHBOARDS:
        bodies: dict[str, Any] = {}
        opened: dict[str, str] = {}
        for persona, client in clients.items():
            response = client.get(f"{BASE}/dashboards/{code}/")
            opened[persona] = str(response.status_code)
            if response.status_code == 200:
                bodies[persona] = response.json()
        cases[f"dashboard.{code}.status"] = opened
        cases[f"dashboard.{code}.vs_admin"] = {
            persona: diff_text(bodies["admin"], bodies[persona]) if persona in bodies else NONE
            for persona in clients
        }
        for field in MONEY_FIELDS.get(code, ()):
            cases[f"dashboard.{code}.money.{field}"] = {
                persona: presence(bodies[persona], field) if persona in bodies else NONE
                for persona in clients
            }
    return cases


# --- raporlar --------------------------------------------------------------------------------


def report_values(
    client: APIClient,
    definition: ReportDefinition,
    listed: Mapping[str, Any] | None,
    reference: Mapping[str, Any],
    capture: Capture,
    pdf_calls: list[PdfCall],
) -> dict[str, str]:
    """Bir personanın bir rapordaki kararları: listede sütunlar, ekran, Excel ve PDF."""
    code = definition.code
    all_keys = [c.key for c in definition.columns]
    values = dict.fromkeys(REPORT_FIELDS, NONE)
    if listed is not None:
        values["list_columns"] = columns_text(all_keys, (c["key"] for c in listed["columns"]))

    response = client.get(f"{BASE}/reports/{code}/", PAGE)
    values["page.status"] = str(response.status_code)
    if response.status_code == 200:
        page = response.json()
        values["page.columns"] = columns_text(all_keys, (c["key"] for c in page["columns"]))
        values["page.row_keys"] = columns_text(
            all_keys, {k for row in page["results"] for k in row}
        )
        values["page.row_count"] = compare(page["count"], reference["count"])
        values["page.summary"] = words(item["key"] for item in page["summary"])

    response = export(client, code, ReportJob.Format.XLSX, capture)
    values["xlsx.status"] = str(response.status_code)
    if response.status_code == 200:
        header, summary = xlsx_layout(content(response), len(reference["filters"]))
        values["xlsx.columns"] = columns_text(all_keys, column_keys(definition, header))
        values["xlsx.summary"] = words(summary_keys(definition, summary))

    pdf_calls.clear()
    response = export(client, code, ReportJob.Format.PDF, capture)
    values["pdf.status"] = str(response.status_code)
    if response.status_code == 200:
        assert content(response).startswith(b"%PDF")
        pdf_columns, pdf_summary = pdf_calls[-1] if pdf_calls else (["?"], ["?"])
        values["pdf.columns"] = columns_text(all_keys, pdf_columns)
        values["pdf.summary"] = words(pdf_summary)
    return values


def report_cases(
    clients: Mapping[str, APIClient], capture: Capture, pdf_calls: list[PdfCall]
) -> tuple[Cases, dict[str, Any]]:
    """Rapor listesi ve her rapor × persona kararları; admin'in rapor sayfaları da döner."""
    cases: Cases = {"reports.list": {}}
    listed: dict[str, dict[str, Any]] = {}
    for persona, client in clients.items():
        response = client.get(f"{BASE}/reports/")
        if response.status_code == 200:
            listed[persona] = {item["code"]: item for item in response.json()}
            cases["reports.list"][persona] = words(listed[persona])
        else:
            cases["reports.list"][persona] = str(response.status_code)
    references: dict[str, Any] = {}
    for code, definition in REPORTS.items():
        reference = clients["admin"].get(f"{BASE}/reports/{code}/", PAGE).json()
        assert reference["count"] > 0, f"{code}: veride satır yok, satır sondası boş kalır."
        references[code] = reference
        for persona, client in clients.items():
            entry = listed.get(persona, {}).get(code)
            values = report_values(client, definition, entry, reference, capture, pdf_calls)
            for field, value in values.items():
                cases.setdefault(f"report.{code}.{field}", {})[persona] = value
    return cases, references


# --- rapor dosyaları (arka plan işleri) ------------------------------------------------------


def job_cases(
    clients: Mapping[str, APIClient],
    users: Mapping[str, User | None],
    references: Mapping[str, Any],
    capture: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> Cases:
    """Kişinin istediği dosya (iş tamamlanır mı, hangi sütunlar), eski dosyası ve başkalarının
    dosyaları: listede görünür mü, ayrıntısı açılır mı, iner mi."""
    # Her dışa aktarım arka plan işi olsun (`reporting.services.SYNC_ROW_LIMIT`).
    monkeypatch.setattr(reporting, "SYNC_ROW_LIMIT", -1)
    cases: Cases = {}
    owners: dict[int, tuple[str, str, str]] = {}  # iş → (sahip, tür, rapor)
    requested: dict[tuple[str, str], int] = {}
    stale: dict[tuple[str, str], int] = {}
    for code in REPORTS:
        for persona, client in clients.items():
            response = export(client, code, ReportJob.Format.XLSX, capture)
            value = str(response.status_code)
            if response.status_code == 202:
                job_id = response.json()["id"]
                owners[job_id] = (persona, "requested", code)
                requested[(persona, code)] = job_id
                value += " " + client.get(f"{BASE}/jobs/{job_id}/").json()["status"]
            cases.setdefault(f"job.{code}.request", {})[persona] = value
        for persona, user in users.items():
            if user is None:
                continue
            response = export(clients["admin"], code, ReportJob.Format.XLSX, capture)
            assert response.status_code == 202, response.content
            job_id = response.json()["id"]
            # Eski dosya: admin'in hazırladığı iş kişiye geçirilir.
            ReportJob.objects.filter(pk=job_id).update(created_by=user)
            owners[job_id] = (persona, "stale", code)
            stale[(persona, code)] = job_id

    for persona, client in clients.items():
        response = client.get(f"{BASE}/jobs/", PAGE)
        if response.status_code != 200:
            for group in ("requested", "stale", "others"):
                cases.setdefault(f"jobs.list.{group}", {})[persona] = str(response.status_code)
        else:
            seen = [owners[job["id"]] for job in response.json()["results"]]
            own = [(kind_, code) for owner, kind_, code in seen if owner == persona]
            cases.setdefault("jobs.list.requested", {})[persona] = words(
                code for kind_, code in own if kind_ == "requested"
            )
            cases.setdefault("jobs.list.stale", {})[persona] = words(
                code for kind_, code in own if kind_ == "stale"
            )
            cases.setdefault("jobs.list.others", {})[persona] = words(
                f"{owner}:{kind_}:{code}" for owner, kind_, code in seen if owner != persona
            )
        for code in REPORTS:
            filter_count = len(references[code]["filters"])
            download, columns = NONE, NONE
            if (persona, code) in requested:
                response = client.get(f"{BASE}/jobs/{requested[(persona, code)]}/download/")
                download = str(response.status_code)
                if response.status_code == 200:
                    header, _ = xlsx_layout(content(response), filter_count)
                    keys = column_keys(REPORTS[code], header)
                    columns = columns_text([c.key for c in REPORTS[code].columns], keys)
            cases.setdefault(f"job.{code}.requested.download", {})[persona] = download
            cases.setdefault(f"job.{code}.requested.columns", {})[persona] = columns
            detail, download = NONE, NONE
            if (persona, code) in stale:
                job_id = stale[(persona, code)]
                response = client.get(f"{BASE}/jobs/{job_id}/")
                detail = str(response.status_code)
                if response.status_code == 200:
                    detail += f" can_download={str(response.json()['can_download']).lower()}"
                download = str(client.get(f"{BASE}/jobs/{job_id}/download/").status_code)
            cases.setdefault(f"job.{code}.stale.detail", {})[persona] = detail
            cases.setdefault(f"job.{code}.stale.download", {})[persona] = download

    # Başkasının dosyası: her sahibin stok durumu dosyası (köşegen kişinin kendisi, yukarıda).
    for owner, user in users.items():
        if user is None:
            continue
        job_id = stale[(owner, "stock-status")]
        for persona, client in clients.items():
            detail = download = NONE
            if persona != owner:
                detail = str(client.get(f"{BASE}/jobs/{job_id}/").status_code)
                download = str(client.get(f"{BASE}/jobs/{job_id}/download/").status_code)
            cases.setdefault(f"jobs.of.{owner}.detail", {})[persona] = detail
            cases.setdefault(f"jobs.of.{owner}.download", {})[persona] = download
    return cases


# --- testler ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("chain", "report_files")
def test_reports_match_snapshot(
    make_user: Callable[..., User],
    django_capture_on_commit_callbacks: Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert len(DASHBOARDS) == DASHBOARD_COUNT, "yeni pano: sondayı ve anlık görüntüyü güncelleyin"
    assert len(REPORTS) == REPORT_COUNT, "yeni rapor: sondayı ve anlık görüntüyü güncelleyin"
    money_data(make_user)
    users = make_personas()
    clients = clients_for(users)
    pdf_calls = spy_pdf(monkeypatch)
    cases = dashboard_cases(clients)
    report, references = report_cases(clients, django_capture_on_commit_callbacks, pdf_calls)
    cases.update(report)
    cases.update(
        job_cases(clients, users, references, django_capture_on_commit_callbacks, monkeypatch)
    )
    snapshot.check(NAME, cases, encode=encode, decode=decode)


def test_snapshot_file_is_complete() -> None:
    """Dosyada her pano ve rapor için durumlar var ve her persona her durumda bir kez geçer."""
    if snapshot.updating():
        pytest.skip("anlık görüntü yazılıyor")
    data = snapshot.load(NAME)
    for case, groups in data.items():
        if case.startswith("_"):
            continue
        names = " ".join(groups.values()).split()
        assert sorted(names) == sorted(PERSONAS), case
    cases = decode(data)
    for code in DASHBOARDS:
        assert f"dashboard.{code}.status" in cases, code
    for code in REPORTS:
        for field in REPORT_FIELDS:
            assert f"report.{code}.{field}" in cases, (code, field)
        assert f"job.{code}.stale.download" in cases, code
