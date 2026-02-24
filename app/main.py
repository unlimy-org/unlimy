import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import load_settings
from app.db.repository import Repository
from app.handlers.start import router
from app.services.cryptobot import CryptoBotClient
from app.services.master_node import MasterNodeClient


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    settings = load_settings()
    repo = await Repository.create(settings.database_url)
    master_node_client = MasterNodeClient(settings.master_node_url)
    cryptobot_client = None
    if settings.cryptobot_enabled and settings.cryptobot_token:
        cryptobot_client = CryptoBotClient(
            token=settings.cryptobot_token,
            api_base=settings.cryptobot_api_base,
        )

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.include_router(router)

    # Dependency injection for handlers
    dp["repo"] = repo
    dp["master_node_client"] = master_node_client
    dp["default_language"] = settings.default_language
    dp["config_poll_interval_sec"] = settings.config_poll_interval_sec
    dp["stars_enabled"] = settings.stars_enabled
    dp["cryptobot_enabled"] = settings.cryptobot_enabled
    dp["cryptobot_asset"] = settings.cryptobot_asset
    dp["cryptobot_client"] = cryptobot_client
    dp["support_admin_ids"] = set(settings.support_admin_ids)

    try:
        await dp.start_polling(bot)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
