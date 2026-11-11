"""Yetki kataloğunu ön yüz için TypeScript'e ya da belgeler için Markdown'a yazar.

Backend konteyneri ön yüzün kaynaklarını salt okunur görür; dosya depo kökünden, çıktı konteynerin
dışına yönlendirilerek üretilir (`access_export.REGENERATE`):

- `export_access --format=ts` (ekrana; yönlendirme ile `frontend/src/auth/access.gen.ts`)
- `export_access --format=ts --check ../frontend/src/auth/access.gen.ts` (CI)
- `export_access --format=markdown`
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.access_export import REGENERATE, regenerate_hint, to_markdown, to_typescript


class Command(BaseCommand):
    help = "Yetki kataloğunu TypeScript (ön yüz) ya da Markdown (belgeler) olarak yazar."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--format", choices=["ts", "markdown"], default="ts")
        parser.add_argument("--output", help="Çıktıyı bu dosyaya yazar (verilmezse ekrana).")
        parser.add_argument(
            "--check", metavar="DOSYA", help="Dosya güncel değilse hata verir (CI için)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        text = to_typescript() if options["format"] == "ts" else to_markdown()
        if options["check"]:
            path = Path(options["check"])
            hint = (
                REGENERATE
                if options["format"] == "ts"
                else regenerate_hint(options["format"], options["check"])
            )
            if not path.exists():
                raise CommandError(f"{path} bulunamadı. {hint}")
            current = path.read_text(encoding="utf-8")
            if current.replace("\r\n", "\n") != text:
                raise CommandError(f"{path} güncel değil. {hint}")
            self.stdout.write(f"{path} güncel.")
            return
        if options["output"]:
            Path(options["output"]).write_text(text, encoding="utf-8", newline="\n")
            self.stdout.write(f"{options['output']} yazıldı.")
            return
        self.stdout.write(text, ending="")
