# VPN Telegram Bot (MVP)

Телеграм-бот для продажи VPN с inline-сценарием и хранением состояния в PostgreSQL.

## Что реализовано
- Полностью inline UX с чистыми последовательными экранами.
- Единственная команда пользователя: `/start`. Дальше вся навигация только inline-кнопками.
- После `/start` главное меню: `Купить VPN`, `Мои покупки`, `Мои конфиги`, `Сменить язык`.
- После `Купить VPN` 3 кнопки: `Готовые тарифы`, `Создать свой тариф`, `Назад`.
- Ветка `Готовые тарифы`: сначала выбор семейства тарифа, затем длительности, затем оплата.
- Ветка `Создать свой тариф`: страна -> сервер (с ping) -> протокол -> длительность -> количество подключений -> оплата.
- После оплаты бот отправляет задачу на мастер-ноду (`localhost:6767`) и опрашивает статус каждые 15 секунд до готовности конфига.
- Есть история заказов (из таблицы оплат) и список конфигов с возможностью обновить конфиг без оплаты.
- Мультиязычность: `ru`, `en`, `uz`, `kk`, `tg`.
- Один активный экран: предыдущее сообщение бота удаляется.
- Платежные ветки:
- `SBP` как локальная симуляция (`success`, `failed`, `cancel`).
- `Telegram Stars` через `send_invoice` (валюта `XTR`).
- `Crypto Bot` через API (`createInvoice`, `getInvoices`).

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
    catalog.py            # Каталог готовых тарифов + формула custom тарифа
    cryptobot.py          # Клиент Crypto Pay API
    master_node.py        # Клиент мастер-ноды (create/poll/renew/servers)
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
- `MASTER_NODE_URL=http://127.0.0.1:6767`
- `CONFIG_POLL_INTERVAL_SEC=15`
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

## Mock master-node (для локальных тестов)
Можно поднять простой mock API мастер-ноды на `127.0.0.1:6767`:

```bash
python3 -m app.mock_master_node
```

Он реализует:
- `GET /servers`
- `POST /configs/create`
- `GET /tasks/{task_id}`
- `POST /configs/renew`

Полезные env для mock:
- `MOCK_MASTER_HOST=127.0.0.1`
- `MOCK_MASTER_PORT=6767`
- `MOCK_TASK_DELAY_SEC=5`
- `MOCK_FAIL_RATE=0`

## Управление ценами без кода
Бот поддерживает overrides цен через таблицу `config_kv` (напрямую в БД, без изменения кода).

Ключи, которые используются:
- `pricing.usd_to_rub`
- `pricing.usd_to_stars`
- `pricing.plan.<plan_code>.usd`
- `pricing.custom.base_usd_per_month`
- `pricing.custom.extra_device_usd_per_month`

## Бизнес-флоу
1. `/start` -> главное меню.
2. `Купить VPN` -> `Готовые тарифы` или `Создать свой тариф`.
3. `Готовые тарифы`: семейство тарифа -> длительность -> оплата -> summary.
4. `Создать свой тариф`: страна -> протокол -> длительность -> устройства -> оплата -> summary.
5. `pay:start` создает заказ в `vpn_orders` со статусом `pending`.
6. Дальше зависит от платежного метода:
- `sbp`: локальная эмуляция результата.
- `stars`: invoice в Telegram, подтверждение через `successful_payment`.
- `cryptobot`: ссылка на оплату + ручная проверка статуса кнопкой.
7. При успехе:
- статус заказа `paid`
- запись в `payment_events`
- сброс `draft_orders`
- создание `connection` и запуск задачи создания конфига на мастер-ноде

## Схема данных (кратко)
- `users`: язык и id последнего сообщения бота.
- `draft_orders`: незавершенный выбор пользователя.
- `vpn_orders`: финальные заказы и статус оплаты.
- `payment_events`: аудит платежных событий.
- `connections`: созданные VPN-конфиги и их статус/задача на мастер-ноде.

## Что важно для разработчиков
- Любые текстовые сообщения (кроме `/start`) и любые другие команды игнорируются намеренно.
- Навигация "Назад" не откатывает состояние `draft_orders`, только экран.
- Для `custom` тарифа цена считается формулой-заглушкой в `app/services/catalog.py`.
- Выдача конфига берется из ответа мастер-ноды, технические детали отправляются в логи.

## Полезные команды
```bash
# Проверка контейнера БД
docker compose ps

# Логи PostgreSQL
docker compose logs -f postgres

# Остановка окружения
docker compose down
```
