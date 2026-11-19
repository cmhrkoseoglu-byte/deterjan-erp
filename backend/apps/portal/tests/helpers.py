"""Portal testlerinin yardımcıları."""

from rest_framework.test import APIClient

from apps.core.models import User


def session_client(user: User, *, password_changed: bool = True) -> APIClient:
    """Oturumla giriş yapmış istemci (ara katmanlar `request.user`'ı görür)."""
    if password_changed and user.must_change_password:
        User.objects.filter(pk=user.pk).update(must_change_password=False)
        user.refresh_from_db()
    client = APIClient()
    client.force_login(user)
    return client
