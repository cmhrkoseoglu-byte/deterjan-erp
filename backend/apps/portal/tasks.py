"""Portal arka plan işleri (Celery)."""

from celery import shared_task

from apps.portal import services


@shared_task(name="portal.send_email")
def send_portal_email(email_id: int) -> None:
    """Müşteriye portal e-postasını gönderir; hata olursa bekleyip yeniden dener (§4.5)."""
    if services.deliver_email(email_id):
        from apps.portal.models import OutboundEmail

        attempts = OutboundEmail.objects.filter(pk=email_id).values_list("attempts", flat=True)
        wait = services.EMAIL_RETRY_SECONDS * (attempts.first() or 1)
        send_portal_email.apply_async((email_id,), countdown=wait)
