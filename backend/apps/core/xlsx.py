"""Excel çıktılarının ortak yardımcıları.

Doküman kontrol bilgisi (ISO 9001 md. 7.5): bant açıksa her sayfanın yazdırma alt bilgisine
doküman no, yayın tarihi ve revizyon, sağına "Sayfa x/y" yazılır; dosya özelliklerine doküman no ve
revizyon. Sayfadaki hücrelere dokunulmaz (satırlar kaymaz). Bant kapalıysa dosya bugünkü gibi kalır.

Kullanıcının yazdığı metin (`sheet_text`): "=" ile başlayan metni openpyxl formül hücresi yapar;
"+", "-", "@", sekme ya da satır başı ile başlayan metin de Excel'de hücre düzenlenince formül
sayılabilir. Bu metinler metin hücresi olarak yazılır ve tırnak önekiyle işaretlenir; hücrede
yazıldığı gibi görünür.
"""

from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet

from apps.core.coding.outputs import DocumentControl

FOOTER_SIZE = 8
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def sheet_text(sheet: Worksheet, value: Any) -> Any:
    """Serbest metni hücre değeri olarak döner: formül gibi başlayan metin, aynı metni gösteren
    metin hücresidir (`ws.append` hücreyi yerine koyar); öteki değerler olduğu gibi kalır."""
    if not isinstance(value, str) or not value.startswith(FORMULA_STARTS):
        return value
    cell = Cell(sheet)
    cell.value = value
    cell.data_type = "s"
    cell.quotePrefix = True
    return cell


def apply_document_control(workbook: Workbook, control: DocumentControl | None) -> None:
    if control is None:
        return
    for sheet in workbook.worksheets:
        footer = sheet.oddFooter
        footer.left.text = control.band()
        footer.left.size = FOOTER_SIZE
        footer.right.text = "Sayfa &P/&N"
        footer.right.size = FOOTER_SIZE
    workbook.properties.identifier = control.doc_code
    workbook.properties.version = control.revision_text
