import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    default_language: str = "en"
    master_node_url: str = "http://127.0.0.1:6767"
    config_poll_interval_sec: int = 15
    stars_enabled: bool = True
    cryptobot_enabled: bool = False
    cryptobot_token: str = ""
    cryptobot_asset: str = "USDT"
    cryptobot_api_base: str = "https://pay.crypt.bot/api"
    support_admin_ids: tuple[int, ...] = ()



def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    default_language = os.getenv("DEFAULT_LANGUAGE", "en").strip().lower()
    master_node_url = os.getenv("MASTER_NODE_URL", "http://127.0.0.1:6767").strip()
    config_poll_interval_sec = int(os.getenv("CONFIG_POLL_INTERVAL_SEC", "15").strip())
    stars_enabled = os.getenv("STARS_ENABLED", "true").strip().lower() == "true"
    cryptobot_enabled = os.getenv("CRYPTOBOT_ENABLED", "false").strip().lower() == "true"
    cryptobot_token = os.getenv("CRYPTOBOT_TOKEN", "").strip()
    cryptobot_asset = os.getenv("CRYPTOBOT_ASSET", "USDT").strip().upper()
    cryptobot_api_base = os.getenv("CRYPTOBOT_API_BASE", "https://pay.crypt.bot/api").strip()
    raw_support_admin_ids = os.getenv("SUPPORT_ADMIN_IDS", "").strip()
    support_admin_ids: tuple[int, ...] = tuple(
        int(item.strip())
        for item in raw_support_admin_ids.split(",")
        if item.strip().isdigit()
    )

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set")
    if not database_url:
        raise ValueError("DATABASE_URL is not set")

    return Settings(
        bot_token=bot_token,
        database_url=database_url,
        default_language=default_language,
        master_node_url=master_node_url,
        config_poll_interval_sec=config_poll_interval_sec,
        stars_enabled=stars_enabled,
        cryptobot_enabled=cryptobot_enabled,
        cryptobot_token=cryptobot_token,
        cryptobot_asset=cryptobot_asset,
        cryptobot_api_base=cryptobot_api_base,
        support_admin_ids=support_admin_ids,
    )
