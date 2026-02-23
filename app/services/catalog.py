from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

SERVER_KEYS = ["de", "fi", "no", "nl"]
PROTOCOL_KEYS = ["hysteria", "vless", "wireguard"]
PAYMENT_KEYS = ["sbp", "cryptobot", "stars"]
CUSTOM_MONTH_OPTIONS = [1, 3, 12]
CUSTOM_DEVICE_OPTIONS = [1, 2, 3, 5, 10]
USD_TO_RUB_FALLBACK = Decimal("77")
USD_TO_STARS_FALLBACK = Decimal("66.67")


@dataclass(frozen=True)
class ReadyTariffPlan:
    code: str
    badge: str
    name: str
    recommended: bool
    description: str


@dataclass(frozen=True)
class ReadyTariffOption:
    plan_code: str
    months: int
    usd: Decimal
    rub: int
    stars: int
    devices: int
    speed: str
    traffic: str
    priority: str
    short_features: str

    @property
    def full_code(self) -> str:
        return f"{self.plan_code}_{self.months}m"


READY_PLANS: dict[str, ReadyTariffPlan] = {
    "entry": ReadyTariffPlan(
        code="entry",
        badge="🟢",
        name="ENTRY",
        recommended=False,
        description="Оптимально для одного устройства. Подходит для YouTube, Telegram, сайтов.",
    ),
    "standard": ReadyTariffPlan(
        code="standard",
        badge="🔵",
        name="STANDARD",
        recommended=True,
        description="Лучший выбор. Подходит для 4K видео, игр и нескольких устройств.",
    ),
    "premium": ReadyTariffPlan(
        code="premium",
        badge="🔴",
        name="PREMIUM",
        recommended=False,
        description="Максимальная скорость и приоритет. Для heavy-users и P2P.",
    ),
    "family": ReadyTariffPlan(
        code="family",
        badge="🟣",
        name="FAMILY",
        recommended=False,
        description="Для семьи или группы. Один аккаунт — много устройств.",
    ),
    "business_start": ReadyTariffPlan(
        code="business_start",
        badge="🟡",
        name="BUSINESS START",
        recommended=False,
        description="Для небольших команд: отдельные конфиги, статистика, админ-доступ.",
    ),
}

READY_PLAN_ORDER = ["entry", "standard", "premium", "family", "business_start"]

READY_OPTIONS: dict[tuple[str, int], ReadyTariffOption] = {
    ("entry", 1): ReadyTariffOption("entry", 1, Decimal("3.00"), 231, 200, 1, "До 30 Mbps", "300 GB", "Стандартный", "1 устройство • 300 GB • Оптимальная скорость"),
    ("entry", 3): ReadyTariffOption("entry", 3, Decimal("8.00"), 616, 533, 1, "До 30 Mbps", "300 GB", "Стандартный", "1 устройство • 300 GB • Оптимальная скорость"),
    ("entry", 12): ReadyTariffOption("entry", 12, Decimal("25.00"), 1925, 1667, 1, "До 30 Mbps", "300 GB", "Стандартный", "1 устройство • 300 GB • Оптимальная скорость"),
    ("standard", 1): ReadyTariffOption("standard", 1, Decimal("5.99"), 461, 399, 3, "До 100 Mbps", "Безлимит", "Средний", "3 устройства • Безлимит • До 100 Mbps"),
    ("standard", 3): ReadyTariffOption("standard", 3, Decimal("15.99"), 1231, 1066, 3, "До 100 Mbps", "Безлимит", "Средний", "3 устройства • Безлимит • До 100 Mbps"),
    ("standard", 12): ReadyTariffOption("standard", 12, Decimal("59.99"), 4619, 4000, 3, "До 100 Mbps", "Безлимит", "Средний", "3 устройства • Безлимит • До 100 Mbps"),
    ("premium", 1): ReadyTariffOption("premium", 1, Decimal("8.99"), 692, 599, 5, "Без ограничения скорости", "Безлимит", "Высокий", "5 устройств • Максимальная скорость • Приоритет"),
    ("premium", 3): ReadyTariffOption("premium", 3, Decimal("23.99"), 1847, 1600, 5, "Без ограничения скорости", "Безлимит", "Высокий", "5 устройств • Максимальная скорость • Приоритет"),
    ("premium", 12): ReadyTariffOption("premium", 12, Decimal("89.99"), 6929, 6000, 5, "Без ограничения скорости", "Безлимит", "Высокий", "5 устройств • Максимальная скорость • Приоритет"),
    ("family", 1): ReadyTariffOption("family", 1, Decimal("12.99"), 1000, 866, 10, "Безлимит", "Безлимит", "Выше Standard", "10 устройств • Безлимит • Для семьи"),
    ("family", 12): ReadyTariffOption("family", 12, Decimal("119.99"), 9239, 8000, 10, "Безлимит", "Безлимит", "Выше Standard", "10 устройств • Безлимит • Для семьи"),
    ("business_start", 1): ReadyTariffOption("business_start", 1, Decimal("29.99"), 2309, 1999, 5, "Бизнес-профиль", "По лимитам профиля", "Бизнес", "5 пользователей • Админ-панель • Статистика"),
}


def _round_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_usd(usd: Decimal) -> str:
    return f"{usd:.2f}"


def ready_plan_button_label(plan: ReadyTariffPlan) -> str:
    rec = " ⭐ Рекомендуемый" if plan.recommended else ""
    return f"{plan.badge} {plan.name}{rec}"


def ready_option_button_label(opt: ReadyTariffOption) -> str:
    return f"{opt.months} мес • ${format_usd(opt.usd)} • {opt.rub} ₽ • {opt.stars} ⭐"


def list_ready_plans() -> list[ReadyTariffPlan]:
    return [READY_PLANS[key] for key in READY_PLAN_ORDER]


def list_ready_options(plan_code: str) -> list[ReadyTariffOption]:
    options = [opt for (code, _), opt in READY_OPTIONS.items() if code == plan_code]
    return sorted(options, key=lambda o: o.months)


def get_ready_option(plan_code: str, months: int) -> ReadyTariffOption | None:
    return READY_OPTIONS.get((plan_code, months))


def build_ready_plan_code(plan_code: str, months: int) -> str:
    return f"ready:{plan_code}:{months}"


def parse_ready_plan_code(plan_code: str) -> ReadyTariffOption | None:
    if not plan_code.startswith("ready:"):
        return None
    parts = plan_code.split(":")
    if len(parts) != 3:
        return None
    try:
        months = int(parts[2])
    except ValueError:
        return None
    return get_ready_option(parts[1], months)


def build_custom_plan_code(server: str, protocol: str, months: int, devices: int) -> str:
    return f"custom:{server}:{protocol}:{months}:{devices}"


def parse_custom_plan_code(plan_code: str) -> tuple[str, str, int, int] | None:
    if not plan_code.startswith("custom:"):
        return None
    parts = plan_code.split(":")
    if len(parts) != 5:
        return None
    try:
        months = int(parts[3])
        devices = int(parts[4])
    except ValueError:
        return None
    return parts[1], parts[2], months, devices


def custom_pricing(months: int, devices: int) -> tuple[Decimal, int, int]:
    # Stub pricing formula: base $3/month + $0.90 per extra device per month.
    base = Decimal("3.00") * Decimal(months)
    extra = Decimal("0.90") * Decimal(max(devices - 1, 0)) * Decimal(months)
    usd = (base + extra).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rub = _round_int(usd * USD_TO_RUB_FALLBACK)
    stars = _round_int(usd * USD_TO_STARS_FALLBACK)
    return usd, rub, stars
