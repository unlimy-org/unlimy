from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message

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


async def replace_bot_message_with_photo(
    bot: Bot,
    repo: Repository,
    chat_id: int,
    tg_id: int,
    photo_path: str,
    caption: str,
    reply_markup,
    cache_key: str | None = None,
) -> Message:
    user = await repo.get_user(tg_id)
    if user and user.last_bot_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=user.last_bot_message_id)
        except TelegramBadRequest:
            pass

    photo_ref = None
    cache_kv_key = None
    if cache_key:
        cache_kv_key = f"media.{cache_key}.file_id"
        photo_ref = await repo.get_config_value(cache_kv_key)

    if photo_ref:
        sent = await bot.send_photo(chat_id=chat_id, photo=photo_ref, caption=caption, reply_markup=reply_markup)
    else:
        photo = FSInputFile(photo_path)
        sent = await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=reply_markup)
        if cache_kv_key and sent.photo:
            await repo.set_config_value(cache_kv_key, sent.photo[-1].file_id)
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
