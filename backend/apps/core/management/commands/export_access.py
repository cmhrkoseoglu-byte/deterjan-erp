"""Yetki kataloğunu ön yüz için TypeScript'e ya da belgeler için Markdown'a yazar.

python manage.py export_access --format=ts --output ../frontend/src/auth/access.gen.ts
python manage.py export_access --format=ts --check ../frontend/src/auth/access.gen.ts
python manage.py export_access --format=markdown
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.access_export import to_markdown, to_typescript


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
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current.replace("\r\n", "\n") != text:
                raise CommandError(
                    f"{path} güncel değil. Yeniden üretin: python manage.py export_access "
                    f"--format={options['format']} --output {path}"
                )
            self.stdout.write(f"{path} güncel.")
            return
        if options["output"]:
            Path(options["output"]).write_text(text, encoding="utf-8", newline="\n")
            self.stdout.write(f"{options['output']} yazıldı.")
            return
        self.stdout.write(text, ending="")
