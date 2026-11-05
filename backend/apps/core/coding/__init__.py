"""Kodlama sistematiği: ana veri kodları, belge ve lot numaraları.

Plan: `docs/plan/kodlama-sistematigi.md`.

- `registry`: modüllerin `AppConfig.ready()` içinde kaydettiği kod türleri.
- `formats`: biçimin saf fonksiyonları (numara üretme, koddan sıra no okuma, doğrulama).
- `selectors`: etkin biçim, öneri, önizleme, eski kodla bulma.
- `services`: biçim değiştirme (yalnız admin), kodu alma, eski kodu saklama.
"""
