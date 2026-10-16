"""`django.contrib.admin` yerine kullanılan uygulama yapılandırması.

Ayrı modüldedir: `INSTALLED_APPS` yüklenirken içe aktarılır, bu sırada modeller ve formlar henüz
yüklenemez (yönetim sitesi `admin_site.py`'de, `ready()` sırasında yüklenir)."""

from django.contrib.admin.apps import AdminConfig


class ERPAdminConfig(AdminConfig):
    """Varsayılan yönetim sitesi `ERPAdminSite`: giriş sınırı ve iki aşamalı doğrulama."""

    default_site = "apps.core.admin_site.ERPAdminSite"
