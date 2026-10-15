"""Olay adı sabitleri. Biçim: `<belge_ya_da_varlık>.<olay>` (küçük harf, alt çizgi).

Durum değişikliği olayları `StateMachine.event_name()` ile üretilir: `<makine_adı>.<yeni_durum>`
(ör. `production_order.approved`). Her modül kendi olaylarını buraya ekler, böylece dinleyen
modül yayınlayan modülü import etmeden adı bilir.
"""

# core — kimlik doğrulama
USER_LOGGED_IN = "user.logged_in"
USER_LOGGED_OUT = "user.logged_out"
USER_LOGIN_FAILED = "user.login_failed"

# core — zamanlanmış işler (Celery Beat). Her sabah 07:00'de yayınlanır; modüller kendi günlük
# kontrollerini bu olaya bağlar (ör. inventory: SKT'si yaklaşan lotlar, minimum stok altı).
DAILY_CHECK = "system.daily_check"

# Faz 1 iş akışı olayları. Payload sözleşmesi docs/DECISIONS.md'de ("İş akışı olay sözleşmesi").
# Durum geçişi olaylarında (`transition_status`) payload zaten {"model", "id", "number", ...}
# içerir.

# inventory
GOODS_RECEIPT_POSTED = "goods_receipt.posted"
LOT_RELEASED = "lot.released"
LOT_REJECTED = "lot.rejected"
LOTS_EXPIRING = "inventory.lots_expiring"
BELOW_MIN_STOCK = "inventory.below_min_stock"

# production
PRODUCTION_ORDER_APPROVED = "production_order.approved"
PRODUCTION_ORDER_MATERIAL_READY = "production_order.material_ready"
PRODUCTION_ORDER_CANCELLED = "production_order.cancelled"
PRODUCTION_BATCH_STARTED = "production_batch.started"
PRODUCTION_BATCH_COMPLETED = "production_batch.completed"
PRODUCTION_DEVIATION = "production.deviation"
PRODUCTION_LOW_YIELD = "production.low_yield"
