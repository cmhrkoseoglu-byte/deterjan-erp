from django.apps import AppConfig


class PersonnelConfig(AppConfig):
    name = "apps.personnel"
    label = "personnel"
    verbose_name = "Personel"

    def ready(self) -> None:
        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("PU", label="Puantaj", model="personnel.attendancemonth")
        register_document_type("BR", label="Bordro", model="personnel.payrollrun")

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output
        from apps.personnel import pdf

        for key, label, formats, code in (
            (pdf.ATTENDANCE_OUTPUT, "Puantaj çizelgesi", ("Excel",), "FR-IK-001"),
            (pdf.PAYROLL_OUTPUT, "Ön bordro (bordro listesi)", ("PDF", "Excel"), "FR-IK-002"),
            (pdf.EMPLOYER_COST_OUTPUT, "İşveren maliyeti tablosu", ("PDF",), "FR-IK-003"),
            (pdf.PAYSLIP_OUTPUT, "Ücret hesap pusulası", ("PDF",), "FR-IK-004"),
        ):
            register_output(
                key,
                label=label,
                group="Personel",
                formats=formats,
                suggested_code=code,
                # Puantaj çizelgesi şablonu sürüm 2: YG sütunu, "Çalışma saatleri" sayfası ve kod
                # açıklamaları (2026-11-12).
                template_version=2 if key == pdf.ATTENDANCE_OUTPUT else 1,
            )
