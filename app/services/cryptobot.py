from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class CryptoInvoice:
    invoice_id: int
    pay_url: str
    status: str


class CryptoBotError(Exception):
    pass


class CryptoBotClient:
    def __init__(self, token: str, api_base: str = "https://pay.crypt.bot/api") -> None:
        self.token = token
        self.api_base = api_base.rstrip("/")

    async def create_invoice(
        self,
        amount: str,
        asset: str,
        description: str,
        payload: str,
    ) -> CryptoInvoice:
        data = {
            "asset": asset,
            "amount": amount,
            "description": description,
            "payload": payload,
        }
        result = await self._request("createInvoice", data)
        return CryptoInvoice(
            invoice_id=int(result["invoice_id"]),
            pay_url=result["pay_url"],
            status=result.get("status", "active"),
        )

    async def get_invoice(self, invoice_id: int) -> Optional[CryptoInvoice]:
        result = await self._request("getInvoices", {"invoice_ids": str(invoice_id)})
        items = result.get("items", [])
        if not items:
            return None
        inv = items[0]
        return CryptoInvoice(
            invoice_id=int(inv["invoice_id"]),
            pay_url=inv.get("pay_url", ""),
            status=inv.get("status", "active"),
        )

    async def _request(self, method: str, data: dict) -> dict:
        headers = {"Crypto-Pay-API-Token": self.token}
        timeout = httpx.Timeout(12.0, connect=6.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.api_base}/{method}", headers=headers, json=data)
        if response.status_code >= 400:
            raise CryptoBotError(f"CryptoBot HTTP {response.status_code}: {response.text[:250]}")
        body = response.json()
        if not body.get("ok"):
            raise CryptoBotError(f"CryptoBot API error: {body}")
        return body.get("result", {})
