# VPN Telegram Bot (MVP)

MVP Telegram bot for VPN sales:
- inline-only flow (no text dialogs)
- multilingual UI (RU/EN/UZ/KK/TG)
- clean step-by-step screens (previous bot message is deleted)
- PostgreSQL for users, draft orders, final orders, and payment event logs
- master->slave provisioning queue stub (after payment)
- payment modes:
  - SBP as local simulator (success/failed/cancel)
  - Telegram Stars (real invoice flow)
  - Crypto Bot (real invoice + status check)

## Stack
- Python 3.11+
- aiogram 3
- PostgreSQL

## Quick start
1. Copy env:
```bash
cp .env.example .env
```
2. Set `BOT_TOKEN` in `.env`.
3. Configure payment vars in `.env`:
```env
STARS_ENABLED=true
CRYPTOBOT_ENABLED=true
CRYPTOBOT_TOKEN=your_crypto_pay_api_token
CRYPTOBOT_ASSET=USDT
CRYPTOBOT_API_BASE=https://pay.crypt.bot/api
```
4. Start PostgreSQL:
```bash
docker compose up -d
```
5. Install deps:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
6. Run bot:
```bash
python -m app.main
```

## Flow
`/start` -> Main menu  
`Buy VPN` -> Plan -> Server -> Protocol -> Payment -> Summary -> Start payment  
Payment branch:
- `SBP` -> local simulation (success/failed/cancel)
- `Telegram Stars` -> Telegram invoice (XTR) -> auto confirmation
- `Crypto Bot` -> external invoice link -> check payment
`Change language` -> Language list -> Main menu

Back button exists on each step.

## Notes
- Any user text message is ignored except `/start`.
- User language is auto-detected from Telegram `language_code` on first `/start`.
- On successful payment, user sees a purchase-confirmation screen with selected plan/server/protocol/payment (placeholder text can be replaced later).
- On successful payment, master node creates a stub provisioning task for slave node config generation and shows task info to user.
