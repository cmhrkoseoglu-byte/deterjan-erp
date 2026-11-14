"""İzin listesinin kendisi (plan §5.5, §10): her kayıt planın bir maddesine ve dondurulmuş bir
hücreye bağlıdır, açıldığı adım planın madde → adım eşlemesine uyar.

Sonraki adımların kayıtları bugün geçerli değildir (`step`); bu test onları da bugünden denetler:
yazım yanlışı ya da yanlış eski değer, maddenin adımına gelinmeden yakalanır. Yeni değeri açık
(`ANY`) bırakılan kayıt, adımı açılınca gözlenen değere sabitlenir: açık kalan kayıt sonraki
adımlarda o hücredeki her değişikliğe izin verirdi.
"""

import importlib
import re
from collections.abc import Callable, Iterable, Mapping
from functools import cache
from typing import Any

from apps.core.tests.access_contract import allowlist, snapshot
from apps.core.tests.access_contract.allowlist import ANY, MISSING, Allowed, matches

# Sıkıştırılmış saklanan anlık görüntülerin çözücüsü bu test modüllerindedir.
DECODERS = {
    "endpoints": "test_endpoints",
    "probe_audit": "test_probe_audit",
    "probe_records": "test_probe_records",
    "probe_reports": "test_probe_reports",
    "probe_workflow": "test_probe_workflow",
}
SNAPSHOTS = frozenset({*DECODERS, "probe_prices", "probe_rules"})

# Plan §10: §8 maddesi → açıldığı adımlar (16. madde Paket B'yi canlıya almadan önce, kod dışı).
ITEM_STEPS: dict[int, frozenset[int]] = {
    1: frozenset({8}),
    2: frozenset({8}),
    3: frozenset({8}),
    4: frozenset(range(2, 9)),
    5: frozenset({4}),
    6: frozenset({7}),
    7: frozenset({2, 5, 6}),
    8: frozenset({5}),
    9: frozenset({7, 8}),
    10: frozenset({7}),
    11: frozenset({7, 8}),
    12: frozenset({6}),
    13: frozenset({9}),
    14: frozenset({9}),
    15: frozenset({9}),
}
# Planın adıyla eklediği uç noktalar ve modeller → açıldıkları adımlar (plan §5.5'in listesi;
# §5.1, §5.2, §5.4, §5.6, §5.10). Liste kapalıdır; bu kayıtların hücreleri yenidir (`MISSING`).
PLANNED_ITEMS: dict[str, frozenset[int]] = {
    "yeni uç nokta: yetki kataloğu (plan §5.1)": frozenset({1}),
    "yeni model: kişiye özel yetki ve paket sürümü (plan §5.2)": frozenset({1}),
    "yeni uç nokta: iadelerin sevkiyat seçimi (plan §5.4)": frozenset({4}),
    # Plan dışı; sahibin onayladığı geri alma planına dayanır (DECISIONS 2026-11-14).
    "yeni uç nokta: dolum emrini geri alma (DECISIONS 2026-11-14)": frozenset({4}),
    "yeni model: kişiye özel yetki ve paket sürümü (plan §5.2, §5.6)": frozenset({6}),
    "yeni uç nokta: Yetkilerim (plan §5.10)": frozenset({9}),
    "yeni uç nokta: kişinin yetki matrisi (plan §5.10)": frozenset({9}),
    "yeni uç nokta: yetki geçmişi (plan §5.10)": frozenset({9}),
    "yeni uç nokta: Kim neyi görür raporu (plan §5.10)": frozenset({9}),
}
_ITEM = re.compile(r"^§8 madde (\d+)\b")
PIN = "adımı açıldı; yeni değer gözlenen değere sabitlenmeli (daraltmak onay istemez)."

Frozen = Mapping[str, Mapping[str, Any]]


@cache
def frozen(name: str) -> Frozen:
    """Dondurulmuş anlık görüntü, `{durum: {persona: değer}}` biçiminde."""
    module = DECODERS.get(name)
    decode = (
        importlib.import_module(f"apps.core.tests.access_contract.{module}").decode
        if module
        else None
    )
    data = snapshot.load(name, decode)
    return {case: values for case, values in data.items() if not case.startswith("_")}


def entry_errors(
    entries: Iterable[Allowed],
    frozen_for: Callable[[str], Frozen | None],
    *,
    current_step: int | None = None,
    planned: Mapping[str, frozenset[int]] = PLANNED_ITEMS,
) -> list[str]:
    """Plana ya da dondurulmuş anlık görüntüye bağlanamayan kayıtlar."""
    current = allowlist.CURRENT_STEP if current_step is None else current_step
    errors: list[str] = []
    for rule in entries:
        label = str(rule)
        found = _ITEM.match(rule.item)
        if found:
            number = int(found.group(1))
            steps = ITEM_STEPS.get(number)
            if steps is None:
                errors.append(f"{label}: §8'de böyle bir madde yok.")
            elif rule.step not in steps:
                errors.append(
                    f"{label}: madde {number} {sorted(steps)}. adımda açılır, kayıt "
                    f"{rule.step}. adımda."
                )
        elif rule.item in planned:
            if rule.step not in planned[rule.item]:
                errors.append(
                    f"{label}: planın eklediği kayıt {sorted(planned[rule.item])}. adımda açılır, "
                    f"kayıt {rule.step}. adımda."
                )
            if rule.old != MISSING:
                errors.append(f"{label}: planın eklediği kaydın hücresi yeni olmalı (MISSING).")
        else:
            errors.append(f"{label}: planın bir maddesine bağlı değil.")
        if rule.until is not None and rule.until < rule.step:
            errors.append(f"{label}: son adım ({rule.until}) ilk adımdan ({rule.step}) önce.")
        cases = frozen_for(rule.snapshot)
        if cases is None:
            errors.append(f"{label}: böyle bir anlık görüntü yok.")
            continue
        cells = [
            value
            for case, values in cases.items()
            if matches(rule.case, case)
            for persona, value in values.items()
            if matches(rule.persona, persona)
        ]
        if rule.old == MISSING:
            if cells:
                errors.append(
                    f"{label}: yeni durum diye yazılmış, anlık görüntüde {len(cells)} hücre var."
                )
        elif not cells:
            errors.append(f"{label}: anlık görüntüde eşleşen hücre yok.")
        elif rule.old != ANY and rule.old not in cells:
            errors.append(f"{label}: eşleşen hücrelerin hiçbirinde eski değer {rule.old!r} değil.")
        if rule.old != ANY and rule.old == rule.new:
            errors.append(f"{label}: eski ve yeni değer aynı.")
        active = rule.step <= current and (rule.until is None or current <= rule.until)
        if active and rule.new == ANY:
            errors.append(f"{label}: {PIN}")
    return errors


def _frozen_or_none(name: str) -> Frozen | None:
    return frozen(name) if name in SNAPSHOTS else None


def test_every_entry_is_tied_to_the_plan_and_a_frozen_cell() -> None:
    errors = entry_errors(allowlist.ALLOWED, _frozen_or_none)
    assert not errors, "İzin listesinde bağlanamayan kayıtlar:\n" + "\n".join(errors)


def test_entry_errors_catch_bad_entries() -> None:
    cases = {"rule [kendi önerisi]": {"admin": "ok", "depo": "403 permission_denied"}}

    def lookup(name: str) -> Frozen | None:
        return cases if name == "probe" else None

    good = Allowed(
        item="§8 madde 5",
        snapshot="probe",
        case="rule [kendi önerisi]",
        persona="admin",
        old="ok",
        step=4,
    )
    new = Allowed(item="yeni uç nokta: deneme", snapshot="probe", case="GET /yeni/", old=MISSING)
    planned = {"yeni uç nokta: deneme": frozenset({1})}
    assert entry_errors([good, new], lookup, current_step=0, planned=planned) == []

    bad = [
        Allowed(item="§8 madde 5", snapshot="probe", case="rule [kendi önerisi]", old="ok", step=3),
        Allowed(item="§8 madde 99", snapshot="probe", case="rule*", old="ok"),
        Allowed(item="plan dışı", snapshot="probe", case="rule*", old="ok"),
        Allowed(item="§8 madde 5", snapshot="yok", case="rule*", step=4),
        Allowed(item="§8 madde 5", snapshot="probe", case="rule [başkasının]", step=4),
        Allowed(
            item="§8 madde 5", snapshot="probe", case="rule*", persona="admin", old="403", step=4
        ),
        Allowed(item="yeni uç nokta: deneme", snapshot="probe", case="rule*", old=MISSING),
        Allowed(item="§8 madde 5", snapshot="probe", case="rule*", old="ok", new="ok", step=4),
        Allowed(item="§8 madde 5", snapshot="probe", case="rule*", old="ok", step=4, until=3),
        Allowed(
            item="yeni uç nokta: deneme", snapshot="probe", case="GET /x/", old=MISSING, step=2
        ),
        Allowed(
            item="yeni uç nokta: deneme", snapshot="probe", case="rule*", persona="admin", old="ok"
        ),
    ]
    errors = entry_errors(bad, lookup, current_step=0, planned=planned)

    # Hata satırı "<kayıt> [persona]: <neden>" biçimindedir.
    assert [error[error.index("]: ") + 3 :] for error in errors] == [
        "madde 5 [4]. adımda açılır, kayıt 3. adımda.",
        "§8'de böyle bir madde yok.",
        "planın bir maddesine bağlı değil.",
        "böyle bir anlık görüntü yok.",
        "anlık görüntüde eşleşen hücre yok.",
        "eşleşen hücrelerin hiçbirinde eski değer '403' değil.",
        "yeni durum diye yazılmış, anlık görüntüde 2 hücre var.",
        "eski ve yeni değer aynı.",
        "son adım (3) ilk adımdan (4) önce.",
        "planın eklediği kayıt [1]. adımda açılır, kayıt 2. adımda.",
        "planın eklediği kaydın hücresi yeni olmalı (MISSING).",
    ]


def test_open_values_must_be_pinned_once_their_step_opens() -> None:
    cases = {"rule": {"admin": "ok"}}

    def lookup(name: str) -> Frozen | None:
        return cases

    open_value = Allowed(item="§8 madde 5", snapshot="probe", case="rule", persona="admin", step=4)
    pinned = Allowed(
        item="§8 madde 5", snapshot="probe", case="rule", persona="admin", step=4, new="400 x"
    )
    ended = Allowed(
        item="§8 madde 5", snapshot="probe", case="rule", persona="admin", step=4, until=4
    )

    assert entry_errors([open_value], lookup, current_step=3) == []
    errors = entry_errors([open_value, pinned], lookup, current_step=4)
    assert [error[error.index("]: ") + 3 :] for error in errors] == [
        "adımı açıldı; yeni değer gözlenen değere sabitlenmeli (daraltmak onay istemez)."
    ]
    assert entry_errors([pinned, ended], lookup, current_step=5) == []
