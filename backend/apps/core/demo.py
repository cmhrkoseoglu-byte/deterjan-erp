"""Demo verisi izni: geliştirme ortamı ya da eğitim ortamı (`TRAINING_MODE`)."""

from django.conf import settings
from django.core.management.base import CommandError

DEMO_NOT_ALLOWED = (
    "Demo verisi yalnızca geliştirme ortamında (DEBUG=True) ya da eğitim ortamında "
    "(TRAINING_MODE=true) yüklenir."
)


def demo_data_allowed() -> bool:
    """Demo kullanıcı ve demo verisi yüklenebilir mi? Canlı (gerçek veri) ortamda hayır."""
    return bool(settings.DEBUG or getattr(settings, "TRAINING_MODE", False))


def require_demo_allowed() -> None:
    """Demo komutlarının başında çağrılır; canlı ortamda komutu durdurur."""
    if not demo_data_allowed():
        raise CommandError(DEMO_NOT_ALLOWED)
