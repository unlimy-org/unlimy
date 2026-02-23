from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.db.repository import Repository


async def replace_bot_message(
    bot: Bot,
    repo: Repository,
    chat_id: int,
    tg_id: int,
    text: str,
    reply_markup,
) -> Message:
    user = await repo.get_user(tg_id)
    if user and user.last_bot_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=user.last_bot_message_id)
        except TelegramBadRequest:
            pass

    sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    await repo.set_last_bot_message_id(tg_id, sent.message_id)
    return sent


async def delete_last_bot_message(
    bot: Bot,
    repo: Repository,
    chat_id: int,
    tg_id: int,
) -> None:
    user = await repo.get_user(tg_id)
    if user and user.last_bot_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=user.last_bot_message_id)
        except TelegramBadRequest:
            pass
