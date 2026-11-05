from typing import Any

from django.db import models


class CodeField(models.CharField):
    """Kod alanı: baştaki/sondaki boşluklar atılır ve büyük harfe çevrilir. Böylece "kg" ile
    "KG" aynı kayıt sayılır. Barkoda uygun kalsın diye `i` → `I` çevrilir (`İ` değil).

    `upper=False`: büyük/küçük harf korunur, yalnızca boşluklar atılır. Standart kodlarda
    harf büyüklüğü anlam taşıyorsa kullanılır (H/P/EUH: `H360Fd` ile `H360FD` farklı ifadelerdir).
    """

    def __init__(self, *args: Any, upper: bool = True, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 32)
        self.upper = upper
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> Any:
        name, path, args, kwargs = super().deconstruct()
        if not self.upper:
            kwargs["upper"] = False
        return name, path, args, kwargs

    def normalize(self, value: str) -> str:
        return normalize_code(value) if self.upper else value.strip()

    def to_python(self, value: Any) -> Any:
        value = super().to_python(value)
        return self.normalize(value) if isinstance(value, str) else value

    def pre_save(self, model_instance: models.Model, add: bool) -> Any:
        value = getattr(model_instance, self.attname)
        if isinstance(value, str):
            value = self.normalize(value)
            setattr(model_instance, self.attname, value)
        return value


def normalize_code(value: str) -> str:
    """Kodu karşılaştırılabilir biçime getirir: boşluk temizliği + büyük harf."""
    return value.strip().upper()
