from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.db import fetch_all_dicts, fetch_one_dict

# Timezone Constants and Helper Functions
EASTERN_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

def assume_utc_and_convert_to_eastern(dt):
    """
    Treats a naive datetime as UTC, then converts it to America/New_York.

    This is appropriate only if your current pipeline has been returning naive
    datetimes that Python/frontend were effectively treating like UTC.
    """
    if dt is None:
        return None

    if not isinstance(dt, datetime):
        return dt

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    return dt.astimezone(EASTERN_TZ)


def convert_row_datetimes_to_eastern(row: dict) -> dict:
    """
    Converts datetime fields in a row dictionary to Eastern time ISO strings.
    """
    converted = {}

    for key, value in row.items():
        if isinstance(value, datetime):
            eastern_dt = assume_utc_and_convert_to_eastern(value)
            converted[key] = eastern_dt.isoformat() if eastern_dt else None
        else:
            converted[key] = value

    return converted

# Convert Decimals to Floats for JSON Serialization

def _convert_decimals(value):
    """
    Recursively converts Decimal values into float for JSON serialization.
    Also converts datetime values into Eastern time ISO strings.
    """
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        eastern_dt = assume_utc_and_convert_to_eastern(value)
        return eastern_dt.isoformat() if eastern_dt else None

    if isinstance(value, dict):
        return {k: _convert_decimals(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_convert_decimals(v) for v in value]

    return value

# Trade Filters
def _build_trade_filters(symbol=None, start_date=None, end_date=None):
    conditions = []
    params = {}

    if symbol:
        conditions.append("symbol = :symbol")
        params["symbol"] = symbol

    if start_date:
        conditions.append("entry_time::date >= :start_date")
        params["start_date"] = start_date

    if end_date:
        conditions.append("entry_time::date <= :end_date")
        params["end_date"] = end_date

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    return where_clause, params


# Dashboard Summary

def get_dashboard_summary(symbol=None, start_date=None, end_date=None) -> dict:
    where_clause, params = _build_trade_filters(symbol, start_date, end_date)
    """
    Returns high-level dashboard metrics based on completed trades.
    """
    query = f"""
    SELECT
        COALESCE(COUNT(*), 0) AS total_trades,
        COALESCE(SUM(total_shares), 0) AS total_shares,
        COALESCE(SUM(gross_pl), 0) AS gross_pl,
        COALESCE(SUM(total_fees), 0) AS total_fees,
        COALESCE(SUM(net_pl), 0) AS net_pl,
        COALESCE(SUM(CASE WHEN net_pl > 0 THEN 1 ELSE 0 END), 0) AS winning_trades,
        COALESCE(SUM(CASE WHEN net_pl < 0 THEN 1 ELSE 0 END), 0) AS losing_trades,
        COALESCE(
            ROUND(AVG(CASE WHEN net_pl > 0 THEN 1.0 ELSE 0.0 END) * 100, 2),
            0
        ) AS win_rate
    FROM public.trades
    {where_clause}
    """
    row = fetch_one_dict(query, params)

    return _convert_decimals({
        "total_trades": row.get("total_trades", 0) or 0,
        "total_shares": row.get("total_shares", 0) or 0,
        "gross_pl": row.get("gross_pl", 0) or 0,
        "total_fees": row.get("total_fees", 0) or 0,
        "net_pl": row.get("net_pl", 0) or 0,
        "winning_trades": row.get("winning_trades", 0) or 0,
        "losing_trades": row.get("losing_trades", 0) or 0,
        "win_rate": row.get("win_rate", 0) or 0,
    })


def get_daily_pnl(symbol=None, start_date=None, end_date=None) -> list[dict]:
    where_clause, params = _build_trade_filters(symbol, start_date, end_date)
    """
    Returns daily net P/L from completed trades.
    """
    query = f"""
    SELECT
        entry_time::date AS trade_date,
        ROUND(COALESCE(SUM(net_pl), 0), 2) AS net_pl,
        COUNT(*) AS total_trades
    FROM public.trades
    {where_clause}
    GROUP BY entry_time::date
    ORDER BY trade_date
    """
    return _convert_decimals(fetch_all_dicts(query, params))


def get_trades(limit=50, symbol=None, start_date=None, end_date=None) -> list[dict]:
    where_clause, params = _build_trade_filters(symbol, start_date, end_date)
    params["limit"] = limit
    """
    Returns recent completed trades.
    """
    query = f"""
    SELECT
        symbol,
        side_open,
        entry_time,
        exit_time,
        total_shares,
        entry_avg_price,
        exit_avg_price,
        gross_pl,
        total_fees,
        net_pl
    FROM public.trades
    {where_clause}
    ORDER BY exit_time DESC
    LIMIT :limit
    """
    return _convert_decimals(fetch_all_dicts(query, params))


def get_symbol_breakdown(symbol=None, start_date=None, end_date=None) -> list[dict]:
    conditions = []
    params = {}

    if symbol:
        conditions.append("symbol = :symbol")
        params["symbol"] = symbol

    if start_date:
        conditions.append("entry_time::date >= :start_date")
        params["start_date"] = start_date

    if end_date:
        conditions.append("entry_time::date <= :end_date")
        params["end_date"] = end_date

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    """
    Returns symbol-level stats from completed trades.
    """
    query = f"""
    SELECT
        symbol,
        COUNT(*) AS trades,
        COALESCE(SUM(total_shares), 0) AS total_shares,
        ROUND(COALESCE(SUM(gross_pl), 0), 2) AS gross_pl,
        ROUND(COALESCE(SUM(total_fees), 0), 2) AS total_fees,
        ROUND(COALESCE(SUM(net_pl), 0), 2) AS net_pl
    FROM public.trades
    {where_clause}
    GROUP BY symbol
    ORDER BY COALESCE(SUM(net_pl), 0) DESC, symbol
    """
    return _convert_decimals(fetch_all_dicts(query, params))

def get_available_symbols() -> list[dict]:
    query = """
    SELECT DISTINCT symbol
    FROM public.trades
    WHERE symbol IS NOT NULL
    ORDER BY symbol
    """
    return _convert_decimals(fetch_all_dicts(query))