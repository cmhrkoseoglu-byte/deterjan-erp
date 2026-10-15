from typing import Any

import factory
from django.contrib.auth.models import Group

from apps.core.models import User
from apps.core.roles import ALL_ROLES

DEFAULT_PASSWORD = "Gizli.Sifre-123"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"kullanici{n}")
    full_name = factory.Faker("name", locale="tr_TR")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.django.Password(DEFAULT_PASSWORD)

    @factory.post_generation
    def roles(obj: User, create: bool, extracted: list[str] | None, **kwargs: Any) -> None:  # noqa: N805
        if not create or not extracted:
            return
        unknown = set(extracted) - set(ALL_ROLES)
        assert not unknown, (
            f"Tanımsız rol: {unknown}"
        )  # yazım hatası testi yanlış nedenle geçirmesin
        groups = [Group.objects.get_or_create(name=name)[0] for name in extracted]
        obj.groups.set(groups)
        obj.refresh_roles()
