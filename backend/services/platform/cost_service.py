import logging
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models.models import CostRecord, utc_now

logger = logging.getLogger(__name__)

# Approximate per-unit costs (USD). These should be replaced with actual
# provider pricing API lookups in production.
_COST_PER_SECOND = {
    "stt": {"deepgram": 0.00000059, "openai": 0.0000006, "sarvam": 0.0000005, "default": 0.0000006},
    "llm": {"mistral": 0.000002, "openai": 0.000003, "anthropic": 0.000003, "sarvam": 0.000001, "default": 0.000002},
    "tts": {"cartesia": 0.000001, "elevenlabs": 0.000002, "deepgram": 0.0000006, "sarvam": 0.0000005, "default": 0.000001},
    "telephony": {"twilio": 0.0000045, "plivo": 0.000004, "exotel": 0.0000035, "vobiz": 0.0000025, "default": 0.000004},
}

# In-memory cache for live forex rate to avoid repeated API calls.
_forex_cache: dict[str, tuple[float, float]] = {}  # "USD_INR" -> (rate, timestamp)


def get_live_rate(
    from_currency: str = "USD",
    to_currency: str = "INR",
    session: Optional[Session] = None,
    company_id: Optional[int] = None,
) -> float:
    """Fetch live exchange rate using APILayer endpoints and public fallbacks. Cached for 5 minutes."""
    import time
    import requests
    from config import settings
    from credentials_service import get_credential

    from_curr = from_currency.upper()
    to_curr = to_currency.upper()

    if from_curr == to_curr:
        return 1.0

    cache_key = f"{from_curr}_{to_curr}"
    now = time.time()
    cached = _forex_cache.get(cache_key)
    if cached and (now - cached[1]) < 300:
        return cached[0]

    # Resolve API key from company settings/credentials database with environment fallback
    api_key = None
    if session and company_id:
        api_key = get_credential(session, company_id, "API_LAYER_API_KEY")
    if not api_key:
        api_key = settings.API_LAYER_API_KEY

    # Try 1: APILayer Exchange Rates Data API
    if api_key:
        try:
            url = f"https://api.apilayer.com/exchangerates_data/latest?base={from_curr}&symbols={to_curr}"
            headers = {"apikey": api_key}
            res = requests.get(url, headers=headers, timeout=5)
            if res.ok:
                data = res.json()
                if data.get("success") and "rates" in data:
                    rate = float(data["rates"][to_curr])
                    _forex_cache[cache_key] = (rate, now)
                    logger.info("[Forex] Live rate (ExchangeRatesData) %s→%s = %s", from_curr, to_curr, rate)
                    return rate
        except Exception as exc:
            logger.warning("[Forex] APILayer Exchange Rates Data API failed: %s", exc)

    # Try 2: APILayer Currency Data API
    if api_key:
        try:
            url = f"https://api.apilayer.com/currency_data/live?source={from_curr}&currencies={to_curr}"
            headers = {"apikey": api_key}
            res = requests.get(url, headers=headers, timeout=5)
            if res.ok:
                data = res.json()
                if data.get("success") and "quotes" in data:
                    quote_key = f"{from_curr}{to_curr}"
                    rate = float(data["quotes"][quote_key])
                    _forex_cache[cache_key] = (rate, now)
                    logger.info("[Forex] Live rate (CurrencyData) %s→%s = %s", from_curr, to_curr, rate)
                    return rate
        except Exception as exc:
            logger.warning("[Forex] APILayer Currency Data API failed: %s", exc)

    # Try 3: pages.dev currency api fallback
    try:
        url = f"https://latest.currency-api.pages.dev/v1/currencies/{from_curr.lower()}.json"
        res = requests.get(url, timeout=5)
        if res.ok:
            data = res.json()
            rates_dict = data.get(from_curr.lower(), {})
            if to_curr.lower() in rates_dict:
                rate = float(rates_dict[to_curr.lower()])
                _forex_cache[cache_key] = (rate, now)
                logger.info("[Forex] Live rate (PagesDev) %s→%s = %s", from_curr, to_curr, rate)
                return rate
    except Exception as exc:
        logger.warning("[Forex] PagesDev fallback failed: %s", exc)

    # Try 4: jsdelivr currency api fallback
    try:
        url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{from_curr.lower()}.json"
        res = requests.get(url, timeout=5)
        if res.ok:
            data = res.json()
            rates_dict = data.get(from_curr.lower(), {})
            if to_curr.lower() in rates_dict:
                rate = float(rates_dict[to_curr.lower()])
                _forex_cache[cache_key] = (rate, now)
                logger.info("[Forex] Live rate (JsDelivr) %s→%s = %s", from_curr, to_curr, rate)
                return rate
    except Exception as exc:
        logger.warning("[Forex] JsDelivr fallback failed: %s", exc)

    # Final Fallback rates with transitivity (via USD)
    logger.warning("[Forex] All live sources failed, using hardcoded fallback/transitive lookup for %s", cache_key)
    if cache_key in _FALLBACK_RATES:
        return _FALLBACK_RATES[cache_key]
    try:
        rate_from_usd = 1.0 if from_curr == "USD" else (_FALLBACK_RATES.get(f"{from_curr}_USD") or (1.0 / _FALLBACK_RATES.get(f"USD_{from_curr}") if _FALLBACK_RATES.get(f"USD_{from_curr}") else None))
        rate_to_usd = 1.0 if to_curr == "USD" else (_FALLBACK_RATES.get(f"USD_{to_curr}") or (1.0 / _FALLBACK_RATES.get(f"{to_curr}_USD") if _FALLBACK_RATES.get(f"{to_curr}_USD") else None))
        if rate_from_usd is not None and rate_to_usd is not None:
            return float(rate_from_usd * rate_to_usd)
    except Exception:
        pass
    return _FALLBACK_RATES.get(cache_key, 1.0)


# Fallback rates (used when live API is unavailable)
_FALLBACK_RATES = {
    "USD_INR": 83.50,
    "INR_USD": 0.012,
    "USD_EUR": 0.93,
    "EUR_USD": 1.08,
    "USD_GBP": 0.79,
    "GBP_USD": 1.27,
    "USD_AUD": 1.51,
    "AUD_USD": 0.66,
    "USD_CAD": 1.37,
    "CAD_USD": 0.73,
    "USD_SGD": 1.35,
    "SGD_USD": 0.74,
    "USD_JPY": 157.00,
    "JPY_USD": 0.0064,
    "USD_AED": 3.67,
    "AED_USD": 0.27,
    "USD_CNY": 7.25,
    "CNY_USD": 0.14,
}


def _get_twilio_live_rate() -> Optional[float]:
    """Fetch live outbound voice pricing from Twilio API (Option B fallback)."""
    from config import settings
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        return None
    try:
        import requests
        # Query the India Voice Country Pricing
        url = "https://pricing.twilio.com/v1/Voice/Countries/IN"
        res = requests.get(url, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN), timeout=3)
        if res.ok:
            data = res.json()
            outbound = data.get("outbound_minutes", [])
            if outbound:
                price = float(outbound[0].get("price", 0.00024))
                # Twilio returns rate per minute, convert to per second
                return price / 60.0
    except Exception as exc:
        logger.warning("[CostService] Twilio live pricing lookup failed: %s", exc)
    return None


def get_provider_rate(
    category: str,
    provider: Optional[str],
    model_or_voice: Optional[str] = None,
    session: Optional[Session] = None,
    company_id: Optional[int] = None,
) -> Decimal:
    """Get rate per second for a provider.
    
    1. Option A (Database lookup per company)
    2. Option B (Live API / backup lookup)
    3. Final Fallback (Hardcoded _COST_PER_SECOND)
    """
    if not provider:
        provider = "default"

    # 1. Option A: Database lookup (if session and company_id are provided)
    if session and company_id:
        try:
            from models.models import ProviderRate
            # Try to find specific model_or_voice first
            if model_or_voice:
                stmt = select(ProviderRate).where(
                    ProviderRate.company_id == company_id,
                    ProviderRate.category == category,
                    ProviderRate.provider == provider,
                    ProviderRate.model_or_voice == model_or_voice,
                    ProviderRate.is_active == True,
                )
                rate_record = session.exec(stmt).first()
                if rate_record:
                    return rate_record.rate_per_second

            # Try to find general provider rate
            stmt = select(ProviderRate).where(
                ProviderRate.company_id == company_id,
                ProviderRate.category == category,
                ProviderRate.provider == provider,
                ProviderRate.model_or_voice == None,
                ProviderRate.is_active == True,
            )
            rate_record = session.exec(stmt).first()
            if rate_record:
                return rate_record.rate_per_second
        except Exception as db_exc:
            logger.warning("[CostService] DB rate lookup failed: %s", db_exc)

    # 2. Option B: Live API lookups
    if category == "telephony" and provider == "twilio":
        twilio_live = _get_twilio_live_rate()
        if twilio_live is not None:
            return Decimal(str(twilio_live))

    # 3. Final Fallback: Hardcoded dictionary
    rates = _COST_PER_SECOND.get(category, {})
    fallback_val = rates.get(provider, rates.get("default", 0.000001))
    return Decimal(str(fallback_val))


def calculate_call_cost(
    duration_seconds: int,
    stt_provider: Optional[str] = None,
    llm_provider: Optional[str] = None,
    tts_provider: Optional[str] = None,
    telephony_provider: Optional[str] = None,
    stt_cost_add: float = 0.0,
    llm_cost_add: float = 0.0,
    tts_cost_add: float = 0.0,
    telephony_cost_add: float = 0.0,
    session: Optional[Session] = None,
    company_id: Optional[int] = None,
) -> dict:
    """Calculate estimated cost for a call based on duration, providers, and db/api rates."""
    stt_rate = get_provider_rate("stt", stt_provider, session=session, company_id=company_id)
    llm_rate = get_provider_rate("llm", llm_provider, session=session, company_id=company_id)
    tts_rate = get_provider_rate("tts", tts_provider, session=session, company_id=company_id)
    telephony_rate = get_provider_rate("telephony", telephony_provider, session=session, company_id=company_id)

    stt = Decimal(str(stt_cost_add or 0)) + stt_rate * Decimal(str(duration_seconds))
    llm = Decimal(str(llm_cost_add or 0)) + llm_rate * Decimal(str(duration_seconds))
    tts = Decimal(str(tts_cost_add or 0)) + tts_rate * Decimal(str(duration_seconds))
    telephony = Decimal(str(telephony_cost_add or 0)) + telephony_rate * Decimal(str(duration_seconds))
    total = stt + llm + tts + telephony
    return {
        "stt_cost": stt,
        "llm_cost": llm,
        "tts_cost": tts,
        "telephony_cost": telephony,
        "total_cost": total,
    }



def save_cost_record(session: Session, company_id: int, **kwargs) -> CostRecord:
    """Create and save a CostRecord row. Expected kwargs:
    interaction_id, lead_id, agent_id, call_task_id, duration_seconds,
    stt_cost, llm_cost, tts_cost, telephony_cost, total_cost, currency,
    stt_provider, llm_provider, tts_provider, telephony_provider, notes.
    """
    record = CostRecord(
        company_id=company_id,
        interaction_id=kwargs.get("interaction_id"),
        lead_id=kwargs.get("lead_id"),
        agent_id=kwargs.get("agent_id"),
        call_task_id=kwargs.get("call_task_id"),
        duration_seconds=kwargs.get("duration_seconds", 0),
        stt_cost=kwargs.get("stt_cost", Decimal("0.000000")),
        llm_cost=kwargs.get("llm_cost", Decimal("0.000000")),
        tts_cost=kwargs.get("tts_cost", Decimal("0.000000")),
        telephony_cost=kwargs.get("telephony_cost", Decimal("0.000000")),
        total_cost=kwargs.get("total_cost", Decimal("0.000000")),
        currency=kwargs.get("currency", "USD"),
        stt_provider=kwargs.get("stt_provider"),
        llm_provider=kwargs.get("llm_provider"),
        tts_provider=kwargs.get("tts_provider"),
        telephony_provider=kwargs.get("telephony_provider"),
        notes=kwargs.get("notes"),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_cost_breakdown(session: Session, company_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, agent_id: Optional[int] = None, currency: str = "USD") -> list[dict]:
    """Aggregate cost records into daily breakdown rows.

    If currency is not "USD", live forex-python API fetches the conversion
    rate on demand and all values are returned in the target currency.
    """
    q = select(CostRecord).where(CostRecord.company_id == company_id)
    if agent_id:
        q = q.where(CostRecord.agent_id == agent_id)
    records = session.exec(q.order_by(CostRecord.created_at.desc())).all()

    from collections import defaultdict
    daily: dict[str, dict] = defaultdict(lambda: {
        "total_calls": 0, "total_minutes": 0.0,
        "stt_cost": 0.0, "llm_cost": 0.0, "tts_cost": 0.0,
        "telephony_cost": 0.0, "total_cost": 0.0,
    })

    for r in records:
        day = r.created_at.strftime("%Y-%m-%d")
        if start_date and day < start_date:
            continue
        if end_date and day > end_date:
            continue
        d = daily[day]
        d["total_calls"] += 1
        d["total_minutes"] += r.duration_seconds / 60.0
        d["stt_cost"] += float(r.stt_cost)
        d["llm_cost"] += float(r.llm_cost)
        d["tts_cost"] += float(r.tts_cost)
        d["telephony_cost"] += float(r.telephony_cost)
        d["total_cost"] += float(r.total_cost)

    # Convert to target currency on demand
    rate = 1.0
    if currency.upper() != "USD":
        rate = get_live_rate("USD", currency.upper(), session=session, company_id=company_id)

    result = []
    for date_str in sorted(daily.keys(), reverse=True):
        d = daily[date_str]
        converted = {k: v * rate for k, v in d.items() if isinstance(v, (int, float))}
        cost_per_minute = converted["total_cost"] / converted["total_minutes"] if converted["total_minutes"] > 0 else 0.0
        result.append({
            "date": date_str,
            "currency": currency.upper(),
            "total_calls": d["total_calls"],
            "total_minutes": round(converted["total_minutes"], 2),
            "stt_cost": round(converted["stt_cost"], 6),
            "llm_cost": round(converted["llm_cost"], 6),
            "tts_cost": round(converted["tts_cost"], 6),
            "telephony_cost": round(converted["telephony_cost"], 6),
            "total_cost": round(converted["total_cost"], 6),
            "cost_per_minute": round(cost_per_minute, 6),
        })
    return result
