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


def get_live_rate(from_currency: str = "USD", to_currency: str = "INR") -> float:
    """Fetch live exchange rate using forex-python. Results are cached for 5 minutes."""
    import time
    cache_key = f"{from_currency}_{to_currency}"
    now = time.time()
    cached = _forex_cache.get(cache_key)
    if cached and (now - cached[1]) < 300:
        return cached[0]

    try:
        from forex_python.converter import CurrencyRates
        c = CurrencyRates()
        rate = c.get_rate(from_currency, to_currency)
        _forex_cache[cache_key] = (rate, now)
        logger.info("[Forex] Live rate %s→%s = %s", from_currency, to_currency, rate)
        return rate
    except Exception as exc:
        logger.warning("[Forex] Live rate fetch failed: %s — using fallback", exc)
        return _FALLBACK_RATES.get(f"{from_currency}_{to_currency}", 1.0)


# Fallback rates (used when live API is unavailable)
_FALLBACK_RATES = {
    "USD_INR": 83.50,
    "INR_USD": 0.012,
}


def _rate(category: str, provider: Optional[str]) -> Decimal:
    rates = _COST_PER_SECOND.get(category, {})
    return Decimal(str(rates.get(provider or "default", rates.get("default", 0.000001))))


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
) -> dict:
    """Calculate estimated cost for a call based on duration and providers."""
    stt = Decimal(str(stt_cost_add or 0)) + _rate("stt", stt_provider) * Decimal(str(duration_seconds))
    llm = Decimal(str(llm_cost_add or 0)) + _rate("llm", llm_provider) * Decimal(str(duration_seconds))
    tts = Decimal(str(tts_cost_add or 0)) + _rate("tts", tts_provider) * Decimal(str(duration_seconds))
    telephony = Decimal(str(telephony_cost_add or 0)) + _rate("telephony", telephony_provider) * Decimal(str(duration_seconds))
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
        rate = get_live_rate("USD", currency.upper())

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
