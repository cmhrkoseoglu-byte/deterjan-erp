"""Sistem rolleri (CLAUDE.md §5). Her rol bir Django `Group`; grup adı rol kodudur."""

ADMIN = "admin"
YONETIM = "yonetim"
PLANLAMA = "planlama"
DEPO = "depo"
URETIM = "uretim"
LABORATUVAR = "laboratuvar"
DOLUM = "dolum"
SEVKIYAT = "sevkiyat"
SATIN_ALMA = "satin_alma"

# Rol kodu -> kullanıcıya görünen ad
ROLE_LABELS: dict[str, str] = {
    ADMIN: "Sistem Yöneticisi",
    YONETIM: "Yönetim",
    PLANLAMA: "Planlama",
    DEPO: "Depo",
    URETIM: "Üretim",
    LABORATUVAR: "Laboratuvar",
    DOLUM: "Dolum",
    SEVKIYAT: "Sevkiyat",
    SATIN_ALMA: "Satın Alma",
}

ALL_ROLES: tuple[str, ...] = tuple(ROLE_LABELS)
