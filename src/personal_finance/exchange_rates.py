"""Exchange-rate provider boundary and deterministic conversion helpers."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Protocol
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .schemas import ExchangeRateQuote


class ExchangeRateUnavailableError(RuntimeError):
    """Raised when a provider cannot supply a trustworthy quote."""


class UnsupportedCurrencyError(ValueError):
    """Raised when a provider does not support a requested currency."""


class ExchangeRateProvider(Protocol):
    """Boundary for providers that quote foreign currency in KRW."""

    name: str

    def get_rate(self, source_currency: str, rate_date: date) -> ExchangeRateQuote:
        """Return a quote normalized to KRW per one source-currency unit."""

    def get_supported_currencies(self, rate_date: date) -> list[str]:
        """Return provider-supported source currency codes for a date."""


def normalize_rate(raw_rate: str | Decimal, quoted_unit: int) -> Decimal:
    """Convert a provider's rate-per-unit-quantity into KRW per one unit."""
    if quoted_unit < 1:
        raise ValueError("quoted_unit must be positive.")
    try:
        amount = Decimal(str(raw_rate).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as error:
        raise ExchangeRateUnavailableError("Provider returned an invalid exchange rate.") from error
    if amount <= 0:
        raise ExchangeRateUnavailableError("Provider returned a non-positive exchange rate.")
    return amount / Decimal(quoted_unit)


def convert_to_krw(amount: Decimal, rate_per_source_unit: Decimal) -> int:
    """Convert a foreign amount to an integer KRW amount with explicit rounding."""
    if amount <= 0 or rate_per_source_unit <= 0:
        raise ValueError("amount and rate_per_source_unit must be positive.")
    return int((amount * rate_per_source_unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_currency_unit(value: str) -> tuple[str, int]:
    """Parse Korea Exim values such as ``JPY(100)`` without special cases."""
    match = re.fullmatch(r"([A-Z]{3})(?:\((\d+)\))?", value.strip().upper())
    if not match:
        raise ExchangeRateUnavailableError("Provider returned an invalid currency unit.")
    return match.group(1), int(match.group(2) or "1")


@dataclass(frozen=True)
class KoreaEximExchangeRateProvider:
    """Korea Exim JSON provider, configured only through an environment variable."""

    api_key: str | None = None
    timeout_seconds: int = 10

    name = "korea_exim"
    endpoint = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"

    def _payload(self, rate_date: date) -> list[dict[str, object]]:
        api_key = self.api_key or os.getenv("KOREA_EXIM_API_KEY")
        if not api_key:
            raise ExchangeRateUnavailableError("KOREA_EXIM_API_KEY is not configured.")
        query = urlencode({"authkey": api_key, "searchdate": rate_date.strftime("%Y%m%d"), "data": "AP01"})
        request = Request(f"{self.endpoint}?{query}", headers={"User-Agent": "myHappybot/0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed official endpoint
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ExchangeRateUnavailableError("Korea Exim exchange-rate request failed.") from error
        if not isinstance(payload, list):
            raise ExchangeRateUnavailableError("Korea Exim returned an unexpected response.")
        if payload and payload[0].get("result") not in (None, 1):
            raise ExchangeRateUnavailableError("Korea Exim rejected the exchange-rate request.")
        return [row for row in payload if isinstance(row, dict) and row.get("cur_unit")]

    def get_rate(self, source_currency: str, rate_date: date) -> ExchangeRateQuote:
        """Retrieve one normalized official quote for a requested calendar date."""
        currency = source_currency.upper()
        if currency == "KRW":
            return ExchangeRateQuote(
                provider=self.name,
                source_currency="KRW",
                rate_date=rate_date,
                rate_per_source_unit=Decimal("1"),
                quoted_unit=1,
            )
        rows = self._payload(rate_date)
        available: set[str] = set()
        for row in rows:
            parsed_currency, quoted_unit = parse_currency_unit(str(row["cur_unit"]))
            available.add(parsed_currency)
            if parsed_currency == currency:
                return ExchangeRateQuote(
                    provider=self.name,
                    source_currency=currency,
                    rate_date=rate_date,
                    rate_per_source_unit=normalize_rate(str(row.get("deal_bas_r", "")), quoted_unit),
                    quoted_unit=quoted_unit,
                )
        if rows and currency not in available:
            raise UnsupportedCurrencyError(f"Korea Exim does not support {currency}.")
        raise ExchangeRateUnavailableError("Korea Exim did not publish a rate for this date.")

    def get_supported_currencies(self, rate_date: date) -> list[str]:
        """List currencies returned by the provider for the requested date."""
        return sorted({parse_currency_unit(str(row["cur_unit"]))[0] for row in self._payload(rate_date)})


@dataclass(frozen=True)
class FakeExchangeRateProvider:
    """Deterministic provider used by tests and local demonstrations."""

    rates: Mapping[tuple[str, date], tuple[Decimal, int] | Decimal]
    name: str = "fake"

    def get_rate(self, source_currency: str, rate_date: date) -> ExchangeRateQuote:
        """Return a configured fake quote or a precise unavailable error."""
        currency = source_currency.upper()
        if currency == "KRW":
            return ExchangeRateQuote(
                provider=self.name,
                source_currency="KRW",
                rate_date=rate_date,
                rate_per_source_unit=Decimal("1"),
                quoted_unit=1,
            )
        configured = self.rates.get((currency, rate_date))
        if configured is None:
            raise ExchangeRateUnavailableError(f"No fake rate is configured for {currency} on {rate_date}.")
        if isinstance(configured, tuple):
            rate, unit = configured
        else:
            rate, unit = configured, 1
        return ExchangeRateQuote(
            provider=self.name,
            source_currency=currency,
            rate_date=rate_date,
            rate_per_source_unit=normalize_rate(rate, unit),
            quoted_unit=unit,
        )

    def get_supported_currencies(self, rate_date: date) -> list[str]:
        """List all fake currencies configured for the requested date."""
        return sorted({currency for currency, configured_date in self.rates if configured_date == rate_date})
