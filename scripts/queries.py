from decimal import Decimal
from scripts.db import fetch_all_dicts, fetch_one_dict


def _convert_decimals(value):
    """
    Recursively converts Decimal values into float for JSON serialization.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _convert_decimals(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_decimals(v) for v in value]
    return value


def get_dashboard_summary() -> dict:
    """
    Returns high-level dashboard metrics based on completed trades.
    """
    query = """
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
    """
    row = fetch_one_dict(query)

    summary = {
        "total_trades": row.get("total_trades", 0) or 0,
        "total_shares": row.get("total_shares", 0) or 0,
        "gross_pl": row.get("gross_pl", 0) or 0,
        "total_fees": row.get("total_fees", 0) or 0,
        "net_pl": row.get("net_pl", 0) or 0,
        "winning_trades": row.get("winning_trades", 0) or 0,
        "losing_trades": row.get("losing_trades", 0) or 0,
        "win_rate": row.get("win_rate", 0) or 0,
    }
    return _convert_decimals(summary)


def get_daily_pnl() -> list[dict]:
    """
    Returns daily net P/L from completed trades.
    """
    query = """
    SELECT
        entry_time::date AS trade_date,
        ROUND(COALESCE(SUM(net_pl), 0), 2) AS net_pl,
        COUNT(*) AS total_trades
    FROM public.trades
    GROUP BY entry_time::date
    ORDER BY trade_date
    """
    return _convert_decimals(fetch_all_dicts(query))


def get_trades(limit: int = 50) -> list[dict]:
    """
    Returns recent completed trades.
    """
    query = """
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
    ORDER BY exit_time DESC
    LIMIT :limit
    """
    return _convert_decimals(fetch_all_dicts(query, {"limit": limit}))


def get_symbol_breakdown() -> list[dict]:
    """
    Returns symbol-level stats from completed trades.
    """
    query = """
    SELECT
        symbol,
        COUNT(*) AS trades,
        COALESCE(SUM(total_shares), 0) AS total_shares,
        ROUND(COALESCE(SUM(gross_pl), 0), 2) AS gross_pl,
        ROUND(COALESCE(SUM(total_fees), 0), 2) AS total_fees,
        ROUND(COALESCE(SUM(net_pl), 0), 2) AS net_pl
    FROM public.trades
    GROUP BY symbol
    ORDER BY net_pl DESC, symbol
    """
    return _convert_decimals(fetch_all_dicts(query))