"""Ana veri etiketleri: lokasyon etiketi (raf/tank, okutma içeriği `LOC:<kod>`) ve yazıcı deneme
etiketi. Ölçü 100 × 150 mm (Karar D-8)."""

from django.utils import timezone

from apps.core.labels import Barcode, Box, Element, Label, QRCode, Text
from apps.masterdata.models import Location, Printer

LABEL_WIDTH, LABEL_HEIGHT = 100.0, 150.0
MARGIN = 5.0
INNER = LABEL_WIDTH - 2 * MARGIN
LOCATION_PREFIX = "LOC:"


def barcode_module(data: str, width: float = INNER, preferred: float = 0.375) -> float:
    """Code128 barkodun genişliğe sığması için dar çubuk genişliği (mm). Alt sınır 0,25 mm
    (203 dpi'de 2 nokta)."""
    modules = 11 * (len(data) + 3) + 2
    return max(0.25, min(preferred, width / modules))


def location_label(location: Location, company_name: str = "") -> Label:
    data = f"{LOCATION_PREFIX}{location.code}"
    elements: list[Element] = [
        Text(MARGIN, MARGIN, company_name, size=8),
        Text(MARGIN, 12, "LOKASYON", size=10),
        Text(MARGIN, 18, location.code, size=30, bold=True, max_width=INNER),
        Text(MARGIN, 34, location.name, size=14, max_width=INNER),
        Text(
            MARGIN,
            42,
            f"{location.warehouse.code} - {location.warehouse.name}",
            size=10,
            max_width=INNER,
        ),
        Text(MARGIN, 48, location.get_location_type_display(), size=10, max_width=INNER),
        QRCode(27.5, 60, 45, data),
        Barcode(MARGIN, 115, 20, data=data, module=barcode_module(data), center_width=INNER),
    ]
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title=f"Lokasyon {location.code}")


def printer_test_label(printer: Printer) -> Label:
    now = timezone.localtime()
    elements: list[Element] = [
        Box(MARGIN, MARGIN, INNER, LABEL_HEIGHT - 2 * MARGIN),
        Text(10, 12, "Deneme etiketi", size=20, bold=True),
        Text(10, 25, f"{printer.code} - {printer.name}", size=11, max_width=80),
        Text(10, 32, f"{printer.host}:{printer.port} · {printer.dpi} dpi", size=10),
        Text(10, 39, f"{now:%d.%m.%Y %H:%M}", size=10),
        Text(10, 48, "Türkçe: ĞÜŞİÖÇ ğüşıöç", size=12),
        QRCode(30, 60, 40, "TEST"),
        Barcode(10, 112, 20, data="TEST-1234", center_width=80),
    ]
    return Label(LABEL_WIDTH, LABEL_HEIGHT, elements, title="Deneme etiketi")
