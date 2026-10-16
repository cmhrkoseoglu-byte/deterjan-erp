"""Olay adı sabitleri. Biçim: `<belge_ya_da_varlık>.<olay>` (küçük harf, alt çizgi).

Durum değişikliği olayları `StateMachine.event_name()` ile üretilir: `<makine_adı>.<yeni_durum>`
(ör. `production_order.approved`). Her modül kendi olaylarını buraya ekler, böylece dinleyen
modül yayınlayan modülü import etmeden adı bilir.
"""

# core — kimlik doğrulama
USER_LOGGED_IN = "user.logged_in"
USER_LOGGED_OUT = "user.logged_out"
USER_LOGIN_FAILED = "user.login_failed"
# Faz 5: hatalı denemelerle kilitlenen hesap (yalnızca var olan kullanıcılar için).
USER_LOCKED = "user.locked"

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
LOT_BLOCKED = "lot.blocked"
GOODS_RECEIPT_CANCELLED = "goods_receipt.cancelled"
# costing (Faz 4, Adım 4.1): kaydedilmiş mal kabulde fiyat / ek masraf düzeltmesi; payload'da
# `number`, `note`, `lots` (lot sözlükleri). Costing bu lotların maliyetini yeniden hesaplar.
GOODS_RECEIPT_COST_CHANGED = "goods_receipt.cost_changed"
STOCK_ADJUSTMENT_POSTED = "stock_adjustment.posted"
LOTS_EXPIRING = "inventory.lots_expiring"
BELOW_MIN_STOCK = "inventory.below_min_stock"

# production
PRODUCTION_ORDER_APPROVED = "production_order.approved"
PRODUCTION_ORDER_MATERIAL_READY = "production_order.material_ready"
PRODUCTION_ORDER_CANCELLED = "production_order.cancelled"
PRODUCTION_ORDER_COMPLETED = "production_order.completed"
PRODUCTION_BATCH_STARTED = "production_batch.started"
PRODUCTION_BATCH_COMPLETED = "production_batch.completed"
PRODUCTION_DEVIATION = "production.deviation"
PRODUCTION_LOW_YIELD = "production.low_yield"

# recipes
RECIPE_VERSION_APPROVED = "recipe_version.approved"
RECIPE_VERSION_OBSOLETE = "recipe_version.obsolete"

# quality (Faz 2, Adım 2.1). Numune olayları durum makinesinden (`sample.<durum>`); payload'da
# numune alanlarına ek olarak `lot` (lot sözlüğü), `stage`, karar olaylarında `decision` bulunur.
SAMPLE_CREATED = "sample.created"
SAMPLE_IN_TEST = "sample.in_test"
SAMPLE_AWAITING_APPROVAL = "sample.awaiting_approval"
SAMPLE_DECIDED = "sample.decided"
SAMPLE_CANCELLED = "sample.cancelled"
SPECIFICATION_APPROVED = "specification.approved"
SPECIFICATION_OBSOLETE = "specification.obsolete"

# filling (Faz 2, Adım 2.2). Emir olayları durum makinesinden (`filling_order.<durum>`); parti
# olayları `filling_run.started` / `filling_run.completed` (payload'da `order`, `output_lot`).
FILLING_ORDER_APPROVED = "filling_order.approved"
FILLING_ORDER_MATERIAL_READY = "filling_order.material_ready"
FILLING_ORDER_CANCELLED = "filling_order.cancelled"
FILLING_ORDER_COMPLETED = "filling_order.completed"
FILLING_RUN_STARTED = "filling_run.started"
FILLING_RUN_COMPLETED = "filling_run.completed"
FILLING_BULK_VARIANCE = "filling.bulk_variance"

# sales (Faz 3, Adım 3.1). Sipariş olayları durum makinesinden (`sales_order.<durum>`); payload'da
# `customer_code`, `customer_name`. `sales_order.shortage` payload'ında `lines` (eksik ürünler) ve
# `reason`; `lot.expiring` günlük kontrolde SKT'si yaklaşan **rezerve** lotlar (`days`, `lots`).
SALES_ORDER_CONFIRMED = "sales_order.confirmed"
SALES_ORDER_CANCELLED = "sales_order.cancelled"
SALES_ORDER_CLOSED = "sales_order.closed"
SALES_ORDER_SHORTAGE = "sales_order.shortage"
SALES_ORDER_FULLY_RESERVED = "sales_order.fully_reserved"
RESERVED_LOTS_EXPIRING = "lot.expiring"
# returns (Faz 3, Adım 3.3). Belge olayları durum makinesinden (`customer_return.<durum>`);
# payload'da `customer_code`, `customer_name`, `lots` (lot sözlükleri, `disposition` ile).
# `customer_return.scrap_required`: imha kararı verilen satır var (depoya görev).
CUSTOMER_RETURN_RECEIVED = "customer_return.received"
CUSTOMER_RETURN_CLOSED = "customer_return.closed"
CUSTOMER_RETURN_CANCELLED = "customer_return.cancelled"
CUSTOMER_RETURN_SCRAP_REQUIRED = "customer_return.scrap_required"
# sales — sevkiyat (Faz 3, Adım 3.2). Durum olayları makineden (`shipment.<durum>`); payload'da
# `order` (sipariş özeti), `customer_code`, `customer_name`; `shipment.planned` ayrıca
# `order_fully_planned` (sipariş satırlarının tamamı açık ya da sevk edilmiş sevkiyatlarda mı).
# `shipment.dispatched` ayrıca `order_created_by_id` ve `lots`.
SHIPMENT_PLANNED = "shipment.planned"
SHIPMENT_PICKING = "shipment.picking"
SHIPMENT_LOADED = "shipment.loaded"
SHIPMENT_DISPATCHED = "shipment.dispatched"
SHIPMENT_CANCELLED = "shipment.cancelled"

# purchasing (Faz 4, Adım 4.2). Durum olayları makinelerden (`purchase_request.<durum>`,
# `purchase_order.<durum>`). Talep payload'ı: `material_code`, `material_name`, `unit`, `quantity`,
# `need_date`, `source`, `reason`. Sipariş onay olayları (`pending_approval`, `approved`, `draft`)
# ayrıca `supplier_name`, `currency`, `total`, `total_try`, `expected_date`, `lines`; mal kabul
# geçişleri (`partially_received`, `received`) `receipt_number`.
PURCHASE_REQUEST_CREATED = "purchase_request.created"
PURCHASE_REQUEST_ORDERED = "purchase_request.ordered"
PURCHASE_REQUEST_CANCELLED = "purchase_request.cancelled"
PURCHASE_ORDER_PENDING_APPROVAL = "purchase_order.pending_approval"
PURCHASE_ORDER_APPROVED = "purchase_order.approved"
PURCHASE_ORDER_RETURNED = "purchase_order.draft"
PURCHASE_ORDER_SENT = "purchase_order.sent"
PURCHASE_ORDER_PARTIALLY_RECEIVED = "purchase_order.partially_received"
PURCHASE_ORDER_RECEIVED = "purchase_order.received"
PURCHASE_ORDER_CANCELLED = "purchase_order.cancelled"

# maintenance (Faz 4, Adım 4.4). İş emri olayları durum makinesinden
# (`maintenance_work_order.<durum>`); payload'da `equipment_code`, `equipment_name`, `title`,
# `kind`, `source`, `responsible_role`, `due_date`, `open_task` (False: tek adımda girilen kayıt).
# Duruş olaylarında `equipment_code`, `equipment_name`, `reason`, `reason_display`, `started_at`,
# `ended_at`, `minutes`, `note`. `maintenance.overdue`: günlük kontrolde süresi geçmiş planlar.
MAINTENANCE_WORK_ORDER_CREATED = "maintenance_work_order.created"
MAINTENANCE_WORK_ORDER_IN_PROGRESS = "maintenance_work_order.in_progress"
MAINTENANCE_WORK_ORDER_COMPLETED = "maintenance_work_order.completed"
MAINTENANCE_WORK_ORDER_CANCELLED = "maintenance_work_order.cancelled"
DOWNTIME_STARTED = "downtime.started"
DOWNTIME_ENDED = "downtime.ended"
MAINTENANCE_OVERDUE = "maintenance.overdue"

# hse (Faz 4, Adım 4.5). Olay kaydı olayları durum makinesinden (`incident.<durum>`); payload'da
# `incident_type`, `incident_type_display`, `occurred_at`, `place`, `injury`, `severity`.
# `hse.storage_limit_exceeded`: lokasyonda tehlike sınıfı limiti aşıldı (`location_code`,
# `hazard_class`, `hazard_class_display`, `quantity_kg`, `limit_kg`).
INCIDENT_CREATED = "incident.created"
INCIDENT_INVESTIGATING = "incident.investigating"
INCIDENT_CLOSED = "incident.closed"
INCIDENT_CANCELLED = "incident.cancelled"
STORAGE_LIMIT_EXCEEDED = "hse.storage_limit_exceeded"

# reporting (Faz 4, Adım 4.3). Arka plan rapor işi bitti ya da hata verdi. Payload:
# `{"model": "reporting.reportjob", "id", "repr", "report_code", "title", "file_format",
# "row_count", "requested_by_id", "error"}`; bildirim yalnızca raporu isteyen kişiye gider.
REPORT_JOB_DONE = "report_job.done"
REPORT_JOB_FAILED = "report_job.failed"

# ops — sistem izleme (Faz 5, Adım 5.5). Payload: `check` (sabit kod: backup, restore_test, disk,
# cpu, queue, worker, beat), `title`, `detail`. Aynı uyarı `OPS_ALERT_REPEAT_MINUTES` içinde
# tekrarlanmaz; sorun geçince bir kez `ops.recovered`.
OPS_ALERT = "ops.alert"
OPS_RECOVERED = "ops.recovered"

# golive (Faz 5, Adım 5.6). Kullanıcı "Sorun bildir" ile sorun bildirdi; admin rolüne görev açılır.
# Payload: `{"model": "golive.problemreport", "id", "number", "summary", "reporter", "page_url"}`.
PROBLEM_REPORTED = "problem_report.created"
