"""Olay adı sabitleri. Biçim: `<belge_ya_da_varlık>.<olay>` (küçük harf, alt çizgi).

Durum değişikliği olayları `StateMachine.event_name()` ile üretilir: `<makine_adı>.<yeni_durum>`
(ör. `production_order.approved`). Her modül kendi olaylarını buraya ekler, böylece dinleyen
modül yayınlayan modülü import etmeden adı bilir.
"""

# core — kimlik doğrulama
USER_LOGGED_IN = "user.logged_in"
USER_LOGGED_OUT = "user.logged_out"
USER_LOGIN_FAILED = "user.login_failed"

# recipes
RECIPE_VERSION_APPROVED = "recipe_version.approved"
RECIPE_VERSION_OBSOLETE = "recipe_version.obsolete"
