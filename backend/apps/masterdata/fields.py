from typing import Any

from django.db import models


class CodeField(models.CharField):
    """Kod alanı: baştaki/sondaki boşluklar atılır ve büyük harfe çevrilir. Böylece "kg" ile
    "KG" aynı kayıt sayılır. Barkoda uygun kalsın diye `i` → `I` çevrilir (`İ` değil)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 32)
        super().__init__(*args, **kwargs)

    def to_python(self, value: Any) -> Any:
        value = super().to_python(value)
        return normalize_code(value) if isinstance(value, str) else value

    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        value = getattr(model_instance, self.attname)
        if isinstance(value, str):
            value = normalize_code(value)
            setattr(model_instance, self.attname, value)
        return value


def normalize_code(value: str) -> str:
    """Kodu karşılaştırılabilir biçime getirir: boşluk temizliği + büyük harf."""
    return value.strip().upper()
