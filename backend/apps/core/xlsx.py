"""Excel çıktılarında doküman kontrol bilgisi (ISO 9001 md. 7.5).

Bant açıksa her sayfanın yazdırma alt bilgisine doküman no, yayın tarihi ve revizyon, sağına
"Sayfa x/y" yazılır; dosya özelliklerine doküman no ve revizyon. Sayfadaki hücrelere dokunulmaz
(satırlar kaymaz). Bant kapalıysa dosya bugünkü gibi kalır.
"""

from openpyxl import Workbook

from apps.core.coding.outputs import DocumentControl

FOOTER_SIZE = 8


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
