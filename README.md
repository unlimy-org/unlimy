# VPN Telegram Bot (MVP)

Телеграм-бот для продажи VPN с inline-сценарием и хранением состояния в PostgreSQL.

## Что реализовано
- Полностью inline UX: выбор тарифа, сервера, протокола и оплаты через кнопки.
- Мультиязычность: `ru`, `en`, `uz`, `kk`, `tg`.
- Один активный экран: предыдущее сообщение бота удаляется.
- Платежные ветки:
- `SBP` как локальная симуляция (`success`, `failed`, `cancel`).
- `Telegram Stars` через `send_invoice` (валюта `XTR`).
- `Crypto Bot` через API (`createInvoice`, `getInvoices`).
- После успешной оплаты создается `provisioning_job` (stub master -> slave).

## Технологии
- Python 3.12+
- aiogram 3
- asyncpg
- PostgreSQL 16 (через Docker Compose)

## Структура проекта
```text
app/
  main.py                 # Точка входа, DI и polling
  config.py               # Загрузка ENV в Settings
  handlers/start.py       # /start, кнопки, платежи, back-навигация
  keyboards/inline.py     # Inline клавиатуры
  locales/translations.py # Словари переводов и tr()
  db/repository.py        # Работа с БД + автосоздание таблиц
  services/
    catalog.py            # Справочники тарифов/цен/методов
    cryptobot.py          # Клиент Crypto Pay API
    provisioning.py       # Stub-оркестратор задач выдачи конфига
    ui.py                 # replace/delete bot message
docker-compose.yml        # PostgreSQL
requirements.txt
```

## Переменные окружения
Создайте `.env` из шаблона:

```bash
cp .env.example .env
```

Обязательные:
- `BOT_TOKEN`
- `DATABASE_URL`

Опциональные:
- `DEFAULT_LANGUAGE=ru`
- `STARS_ENABLED=true`
- `CRYPTOBOT_ENABLED=true`
- `CRYPTOBOT_TOKEN=...`
- `CRYPTOBOT_ASSET=USDT`
- `CRYPTOBOT_API_BASE=https://pay.crypt.bot/api`

## Локальный запуск
1. Поднять PostgreSQL:
```bash
docker compose up -d
```
2. Создать окружение и поставить зависимости:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
3. Запустить бота:
```bash
python3 -m app.main
```

Таблицы БД создаются автоматически при старте (`Repository._migrate()`).

## Бизнес-флоу
1. `/start` -> главное меню.
2. `Купить VPN` -> тариф -> сервер -> протокол -> метод оплаты -> summary.
3. `pay:start` создает заказ в `vpn_orders` со статусом `pending`.
4. Дальше зависит от платежного метода:
- `sbp`: локальная эмуляция результата.
- `stars`: invoice в Telegram, подтверждение через `successful_payment`.
- `cryptobot`: ссылка на оплату + ручная проверка статуса кнопкой.
5. При успехе:
- статус заказа `paid`
- запись в `payment_events`
- сброс `draft_orders`
- постановка задачи в `provisioning_jobs`

## Схема данных (кратко)
- `users`: язык, id последнего сообщения бота.
- `draft_orders`: незавершенный выбор пользователя.
- `vpn_orders`: финальные заказы и статус оплаты.
- `payment_events`: аудит платежных событий.
- `provisioning_jobs`: очередь задач подготовки VPN-конфига (stub).

## Что важно для разработчиков
- Любые текстовые сообщения (кроме `/start`) игнорируются намеренно.
- Навигация "Назад" не откатывает состояние `draft_orders`, только экран.
- В `PLAN_PRICES_STARS` сейчас значения отличаются от USD и заданы вручную.
- Реальной выдачи VPN-конфигов пока нет, только постановка stub-задачи.

## Полезные команды
```bash
# Проверка контейнера БД
docker compose ps

# Логи PostgreSQL
docker compose logs -f postgres

# Остановка окружения
docker compose down
```
