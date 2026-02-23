import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import load_settings
from app.db.repository import Repository
from app.handlers.start import router
from app.services.cryptobot import CryptoBotClient
from app.services.provisioning import ProvisioningService


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    repo = await Repository.create(settings.database_url)
    provisioning_service = ProvisioningService(repo)
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
    dp["provisioning_service"] = provisioning_service
    dp["default_language"] = settings.default_language
    dp["stars_enabled"] = settings.stars_enabled
    dp["cryptobot_enabled"] = settings.cryptobot_enabled
    dp["cryptobot_asset"] = settings.cryptobot_asset
    dp["cryptobot_client"] = cryptobot_client

    try:
        await dp.start_polling(bot)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
