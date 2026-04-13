# Python Importer File to be run manually at the end of the trading day 
# Command to start PPro8 API: PPro8.exe -pproapi_port=8080
# Check in browser that API is accessible: http://localhost:8080/GetTransactions?user=YOUR_USER
# Note: PPro8 must still be running to work 
# To run the importer: python -m scripts.import_trades

import hashlib
import json
import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

import psycopg
import requests

MONEY_QUANT = Decimal("0.01")
PRICE_QUANT = Decimal("0.0001")

def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


# -----------------------------------------------------------------------------
# Configuration - Import from config.py
# -----------------------------------------------------------------------------

from scripts.config import DB_CONFIG, PPRO_BASE_URL, PPRO_USER_ID

REQUEST_TIMEOUT_SECONDS = 20


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------

def sha256_text(value: str) -> str:
    """
    Returns the SHA-256 hash of a string.

    Args:
        value: Input text to hash.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_ppro_datetime(value: Optional[str]) -> Optional[datetime]:
    """
    Parses a PPro datetime string into a Python datetime object.

    Supported formats include:
    - YYYYMMDD-HH:MM:SS.fff
    - YYYYMMDD-HH:MM:SS

    Args:
        value: Raw datetime string from PPro.

    Returns:
        Parsed datetime if successful, otherwise None.
    """
    if not value:
        return None

    cleaned = value.strip()
    formats = [
        "%Y%m%d-%H:%M:%S.%f",
        "%Y%m%d-%H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    logger.warning("Unable to parse datetime value: %s", value)
    return None


def text_to_int(value: Optional[str]) -> Optional[int]:
    """
    Converts a string value to an integer.

    Args:
        value: Input value.

    Returns:
        Integer if conversion succeeds, otherwise None.
    """
    if value in (None, "", "NULL"):
        return None

    try:
        return int(float(value))
    except (ValueError, TypeError):
        logger.debug("Unable to convert to int: %s", value)
        return None


def text_to_decimal(value: Optional[str]) -> Optional[Decimal]:
    """
    Converts a string value to a Decimal.

    Decimal is preferred over float for trading and financial data.

    Args:
        value: Input value.

    Returns:
        Decimal if conversion succeeds, otherwise None.
    """
    if value in (None, "", "NULL"):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        logger.debug("Unable to convert to Decimal: %s", value)
        return None


def text_to_bool(value: Optional[str]) -> Optional[bool]:
    """
    Converts common truthy and falsy string values to boolean.

    Args:
        value: Input value.

    Returns:
        Boolean if recognized, otherwise None.
    """
    if value in (None, ""):
        return None

    cleaned = str(value).strip().lower()

    if cleaned in {"1", "true", "yes", "y"}:
        return True
    if cleaned in {"0", "false", "no", "n"}:
        return False

    logger.debug("Unable to convert to bool: %s", value)
    return None


# -----------------------------------------------------------------------------
# PPro API helpers
# -----------------------------------------------------------------------------

def enable_json_output() -> None:
    """
    Attempts to enable JSON output on the local PPro API.

    If the endpoint is unavailable or unsupported in the current setup,
    the function logs the issue and continues without failing the import.
    """
    url = f"{PPRO_BASE_URL}/SetJsonOn?"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        logger.info("SetJsonOn request sent successfully.")
    except requests.RequestException as exc:
        logger.warning("SetJsonOn could not be confirmed: %s", exc)


def call_ppro_endpoint(endpoint: str, user_id: str) -> str:
    """
    Calls a PPro API endpoint and returns the raw response body.

    Args:
        endpoint: Endpoint name, such as 'GetTransactions' or 'GetBlotter'.
        user_id: Trader/user identifier recognized by PPro.

    Returns:
        Raw response body as text.

    Raises:
        requests.RequestException: If the HTTP request fails.
    """
    url = f"{PPRO_BASE_URL}/{endpoint}?user={user_id}"
    logger.info("Calling PPro endpoint: %s", url)

    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    logger.info("Received response from endpoint: %s", endpoint)
    return response.text


def detect_payload_format(payload: str) -> str:
    """
    Detects whether a payload appears to be JSON or XML.

    Args:
        payload: Raw API response body.

    Returns:
        'json' if payload looks like JSON, otherwise 'xml'.
    """
    stripped = payload.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "xml"


# -----------------------------------------------------------------------------
# Parsing helpers
# -----------------------------------------------------------------------------

def parse_xml_records(payload: str) -> List[Dict[str, Any]]:
    """
    Parses XML payload into a list of attribute-based records.

    This is a generic first-pass parser intended for PPro XML payloads.
    It collects any XML element that has attributes and treats those
    attributes as a row-like record.

    Args:
        payload: Raw XML response body.

    Returns:
        List of dictionaries representing parsed XML records.

    Raises:
        xml.etree.ElementTree.ParseError: If XML is malformed.
    """
    root = ET.fromstring(payload)
    records: List[Dict[str, Any]] = []

    for elem in root.iter():
        if elem.attrib:
            records.append(dict(elem.attrib))

    logger.info("Parsed %s XML records.", len(records))
    return records


def parse_json_records(payload: str) -> List[Dict[str, Any]]:
    """
    Parses JSON payload into a list of dictionaries.

    Args:
        payload: Raw JSON response body.

    Returns:
        List of dictionaries extracted from the JSON structure.

    Raises:
        json.JSONDecodeError: If JSON is malformed.
    """
    data = json.loads(payload)

    if isinstance(data, list):
        records = [item for item in data if isinstance(item, dict)]
        logger.info("Parsed %s JSON records from list payload.", len(records))
        return records

    if isinstance(data, dict):
        logger.info("Parsed 1 JSON record from dict payload.")
        return [data]

    logger.info("JSON payload contained no usable records.")
    return []


def parse_payload_to_records(payload: str) -> List[Dict[str, Any]]:
    """
    Parses a raw API payload into a list of record dictionaries.

    Args:
        payload: Raw XML or JSON response body.

    Returns:
        List of parsed records.
    """
    payload_format = detect_payload_format(payload)

    if payload_format == "json":
        return parse_json_records(payload)

    return parse_xml_records(payload)


# -----------------------------------------------------------------------------
# Normalization
# -----------------------------------------------------------------------------

def normalize_record(record: Dict[str, Any], source_type: str, user_id: str) -> Dict[str, Any]:
    """
    Normalizes a raw PPro record into the trade_events database schema.

    This function:
    - maps raw API field names to standardized database columns
    - converts types where appropriate
    - stores the original record in JSON form
    - computes a stable event hash for deduplication

    Args:
        record: Raw record dictionary from PPro.
        source_type: Source identifier, such as 'get_transactions' or 'get_blotter'.
        user_id: Trader/user identifier.

    Returns:
        Normalized record dictionary ready for insertion into trade_events.
    """
    market_dt = parse_ppro_datetime(
        record.get("MarketDateTime") or record.get("MktTime")
    )
    client_dt = parse_ppro_datetime(
        record.get("ClntTime") or record.get("ClientTime")
    )

    normalized: Dict[str, Any] = {
        "source_type": source_type,
        "user_id": user_id,
        "region_id": text_to_int(record.get("id") or record.get("RegionId")),
        "region_name": record.get("name") or record.get("RegionName"),
        "message_type": record.get("Message") or record.get("MessageType"),
        "message": record.get("Message"),
        "market_datetime": market_dt,
        "client_datetime": client_dt,
        "symbol": record.get("Symbol") or record.get("Sym"),
        "market": record.get("Market"),
        "gateway": record.get("Gateway") or record.get("GwName"),
        "destination": record.get("Destination"),
        "side": record.get("Side"),
        "order_class": record.get("OrdCls") or record.get("OrderClass"),
        "order_number": record.get("OrderNumber") or record.get("OrdrId"),
        "parent_order_number": record.get("ParentOrderNumber"),
        "market_id": text_to_int(record.get("MarketId")),
        "account": record.get("Account"),
        "info_code": record.get("InfoCode"),
        "order_status": record.get("OrdrSt") or record.get("OrderStatus"),
        "order_state": record.get("OrderState"),
        "info_text": record.get("InfoText"),
        "order_flags": record.get("OrderFlags"),
        "order_price": text_to_decimal(record.get("OrdPx")),
        "exec_price": text_to_decimal(record.get("ExecPx")),
        "price": text_to_decimal(record.get("Price")),
        "order_size": text_to_int(record.get("OrdSz")),
        "exec_size": text_to_int(record.get("ExecSz")),
        "fill_size": text_to_int(record.get("FilSz")),
        "open_size": text_to_int(record.get("OpenSz")),
        "shares": text_to_int(record.get("Shares")),
        "position": text_to_int(record.get("Position")),
        "currency_charge_giveup": text_to_decimal(
            record.get("ChargeGway") or record.get("CurrencyChargeGiveup")
        ),
        "currency_charge_act": text_to_decimal(
            record.get("ChargeAct") or record.get("CurrencyChargeAct")
        ),
        "currency_charge_exec": text_to_decimal(
            record.get("ChargeExec") or record.get("CurrencyChargeExec")
        ),
        "currency_charge_clear": text_to_decimal(
            record.get("ChargeClr") or record.get("CurrencyChargeClr")
        ),
        "charge_sec": text_to_decimal(record.get("ChargeSec")),
        "via_api": text_to_bool(record.get("ViaApi")),
        "raw_record": json.dumps(record, default=str),
    }

    event_key = {
        "source_type": normalized["source_type"],
        "user_id": normalized["user_id"],
        "order_number": normalized["order_number"],
        "market_datetime": str(normalized["market_datetime"]),
        "symbol": normalized["symbol"],
        "order_status": normalized["order_status"],
        "price": str(normalized["price"]),
        "exec_price": str(normalized["exec_price"]),
        "shares": normalized["shares"],
        "raw_record": record,
    }

    normalized["event_hash"] = sha256_text(
        json.dumps(event_key, sort_keys=True, default=str)
    )

    return normalized


# -----------------------------------------------------------------------------
# Database insert helpers
# -----------------------------------------------------------------------------

def insert_raw_api_event(
    cur: psycopg.Cursor,
    import_batch_id: uuid.UUID,
    source_type: str,
    user_id: str,
    payload: str,
) -> str:
    """
    Inserts a raw PPro payload into raw_api_events.

    Uses a payload hash for idempotency so the same raw response is not stored
    as a duplicate for the same source_type and user.

    Args:
        cur: Active psycopg database cursor.
        import_batch_id: Unique identifier for this import run.
        source_type: Source endpoint type.
        user_id: Trader/user identifier.
        payload: Raw API response body.

    Returns:
        The UUID of the inserted or matched raw_api_events row.
    """
    payload_format = detect_payload_format(payload)
    payload_hash = sha256_text(payload)
    trade_date = date.today()

    cur.execute(
        """
        INSERT INTO raw_api_events (
            import_batch_id,
            source_type,
            user_id,
            trade_date,
            payload_format,
            raw_payload,
            payload_hash
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_type, user_id, payload_hash)
        DO UPDATE SET pulled_at = NOW()
        RETURNING id
        """,
        (
            import_batch_id,
            source_type,
            user_id,
            trade_date,
            payload_format,
            payload,
            payload_hash,
        ),
    )

    raw_id = cur.fetchone()[0]
    logger.info("Stored raw payload for %s with id %s", source_type, raw_id)
    return raw_id


def insert_trade_event(
    cur: psycopg.Cursor,
    import_batch_id: uuid.UUID,
    raw_api_event_id: str,
    row: Dict[str, Any],
) -> None:
    """
    Inserts a normalized record into trade_events.

    Uses ON CONFLICT DO NOTHING to prevent duplicate event insertion based on
    the unique constraint on (source_type, user_id, event_hash).

    Args:
        cur: Active psycopg database cursor.
        import_batch_id: Unique identifier for this import run.
        raw_api_event_id: Foreign key reference to raw_api_events.id.
        row: Normalized trade event dictionary.
    """
    cur.execute(
        """
        INSERT INTO trade_events (
            import_batch_id,
            raw_api_event_id,
            source_type,
            user_id,
            region_id,
            region_name,
            message_type,
            message,
            market_datetime,
            client_datetime,
            symbol,
            market,
            gateway,
            destination,
            side,
            order_class,
            order_number,
            parent_order_number,
            market_id,
            account,
            info_code,
            order_status,
            order_state,
            info_text,
            order_flags,
            order_price,
            exec_price,
            price,
            order_size,
            exec_size,
            fill_size,
            open_size,
            shares,
            position,
            currency_charge_giveup,
            currency_charge_act,
            currency_charge_exec,
            currency_charge_clear,
            charge_sec,
            via_api,
            raw_record,
            event_hash
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
            %s, %s
        )
        ON CONFLICT (source_type, user_id, event_hash) DO NOTHING
        """,
        (
            import_batch_id,
            raw_api_event_id,
            row["source_type"],
            row["user_id"],
            row["region_id"],
            row["region_name"],
            row["message_type"],
            row["message"],
            row["market_datetime"],
            row["client_datetime"],
            row["symbol"],
            row["market"],
            row["gateway"],
            row["destination"],
            row["side"],
            row["order_class"],
            row["order_number"],
            row["parent_order_number"],
            row["market_id"],
            row["account"],
            row["info_code"],
            row["order_status"],
            row["order_state"],
            row["info_text"],
            row["order_flags"],
            row["order_price"],
            row["exec_price"],
            row["price"],
            row["order_size"],
            row["exec_size"],
            row["fill_size"],
            row["open_size"],
            row["shares"],
            row["position"],
            row["currency_charge_giveup"],
            row["currency_charge_act"],
            row["currency_charge_exec"],
            row["currency_charge_clear"],
            row["charge_sec"],
            row["via_api"],
            row["raw_record"],
            row["event_hash"],
        ),
    )


def rebuild_daily_summary(
    cur: psycopg.Cursor,
    import_batch_id: uuid.UUID,
    user_id: str,
    summary_date: date,
) -> None:
    """
    Rebuilds the daily_trade_summary row for a given user and date.

    This is an initial summary implementation that computes:
    - total rows
    - total trades based on fill-like statuses
    - distinct symbols
    - total shares
    - simple fee totals
    - top traded symbol

    Realized P/L logic will likely need refinement once live production payloads
    are inspected and validated.

    Args:
        cur: Active psycopg database cursor.
        import_batch_id: Unique identifier for this import run.
        user_id: Trader/user identifier.
        summary_date: Trading date being summarized.
    """
    cur.execute(
        """
        INSERT INTO daily_trade_summary (
            import_batch_id,
            summary_date,
            user_id,
            total_rows,
            total_trades,
            total_symbols,
            total_shares,
            gross_pl,
            net_pl,
            total_fees,
            winning_trades,
            losing_trades,
            breakeven_trades,
            top_symbol,
            source_notes,
            updated_at
        )
        SELECT
            %s,
            %s,
            %s,
            COUNT(*)::int,
            COUNT(*) FILTER (WHERE COALESCE(order_status, '') ILIKE '%%fill%%')::int,
            COUNT(DISTINCT symbol)::int,
            COALESCE(SUM(COALESCE(exec_size, shares, 0)), 0)::bigint,
            0,
            0,
            COALESCE(SUM(
                COALESCE(currency_charge_act, 0) +
                COALESCE(currency_charge_exec, 0) +
                COALESCE(currency_charge_clear, 0)
            ), 0),
            0,
            0,
            0,
            (
                SELECT symbol
                FROM trade_events te2
                WHERE te2.user_id = %s
                    AND te2.trade_date = %s
                    AND te2.source_type = 'get_transactions'
                    AND te2.order_state IN ('Filled', 'Partially Filled')
                    AND te2.side IN ('B', 'S', 'T')
                    AND te2.symbol IS NOT NULL
                GROUP BY symbol
                ORDER BY SUM(shares) DESC, symbol
                LIMIT 1
            ),
            'Initial summary build; refine realized P/L after validating real payloads.',
            NOW()
        FROM trade_events te
        WHERE te.user_id = %s
          AND te.trade_date = %s
          AND te.source_type = 'get_transactions'
          AND te.order_state IN ('Filled', 'Partially Filled')
          AND te.side IN ('B', 'S', 'T')
          AND te.symbol IS NOT NULL
        ON CONFLICT (summary_date, user_id)
        DO UPDATE SET
            import_batch_id = EXCLUDED.import_batch_id,
            total_rows = EXCLUDED.total_rows,
            total_trades = EXCLUDED.total_trades,
            total_symbols = EXCLUDED.total_symbols,
            total_shares = EXCLUDED.total_shares,
            gross_pl = EXCLUDED.gross_pl,
            net_pl = EXCLUDED.net_pl,
            total_fees = EXCLUDED.total_fees,
            winning_trades = EXCLUDED.winning_trades,
            losing_trades = EXCLUDED.losing_trades,
            breakeven_trades = EXCLUDED.breakeven_trades,
            top_symbol = EXCLUDED.top_symbol,
            source_notes = EXCLUDED.source_notes,
            updated_at = NOW()
        """,
        (
            import_batch_id,
            summary_date,
            user_id,
            user_id,
            summary_date,
            user_id,
            summary_date,
        ),
    )

    logger.info("Rebuilt daily summary for user=%s date=%s", user_id, summary_date)


# -----------------------------------------------------------------------------
# Main import workflow
# -----------------------------------------------------------------------------

def import_source(
    cur: psycopg.Cursor,
    import_batch_id: uuid.UUID,
    source_type: str,
    endpoint_name: str,
    user_id: str,
) -> int:
    """
    Imports a single PPro source endpoint into raw_api_events and trade_events.

    Steps:
    - call the endpoint
    - store the raw payload
    - parse the payload into records
    - normalize each record
    - insert normalized records with duplicate protection

    Args:
        cur: Active psycopg database cursor.
        import_batch_id: Unique identifier for this import run.
        source_type: Source label used in the database.
        endpoint_name: Actual PPro endpoint name.
        user_id: Trader/user identifier.

    Returns:
        Number of parsed records processed from the endpoint.
    """
    payload = call_ppro_endpoint(endpoint_name, user_id)
    raw_api_event_id = insert_raw_api_event(
        cur=cur,
        import_batch_id=import_batch_id,
        source_type=source_type,
        user_id=user_id,
        payload=payload,
    )

    records = parse_payload_to_records(payload)
    logger.info("Processing %s records from %s", len(records), endpoint_name)

    for record in records:
        normalized = normalize_record(
            record=record,
            source_type=source_type,
            user_id=user_id,
        )
        insert_trade_event(
            cur=cur,
            import_batch_id=import_batch_id,
            raw_api_event_id=raw_api_event_id,
            row=normalized,
        )

    return len(records)

# -----------------------------------------------------------------------------
# Tracks Trading Positions
# -----------------------------------------------------------------------------

@dataclass
class OpenPosition:
    """
    Tracks the currently open position for one symbol.

    Attributes:
        symbol: Ticker symbol.
        user_id: Trader/user identifier.
        side_open: LONG or SHORT once established.
        entry_time: Timestamp of the first opening execution.
        position_qty: Signed quantity. Positive for long, negative for short.
        avg_entry_price: Weighted average entry price for the currently open position.
        accumulated_fees: Running fees for the open trade.
        entry_order_numbers: Order numbers contributing to the opening side.
        exit_order_numbers: Order numbers contributing to the closing side.
    """
    symbol: str
    user_id: str
    side_open: str | None = None
    entry_time: datetime | None = None
    position_qty: int = 0
    avg_entry_price: Decimal = Decimal("0")
    accumulated_fees: Decimal = Decimal("0")
    entry_order_numbers: list[str] = field(default_factory=list)
    exit_order_numbers: list[str] = field(default_factory=list)


def decimal_or_zero(value: Any) -> Decimal:
    """
    Returns a Decimal value or zero if the input is None.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_event_fee(row):
    """
    Match PPro behavior:
    - round each component at event level
    - then sum
    """

    fee = (
        decimal_or_zero(row.get("currency_charge_act")) +
        decimal_or_zero(row.get("currency_charge_exec")) +
        decimal_or_zero(row.get("currency_charge_clear")) +
        decimal_or_zero(row.get("charge_sec"))
    )

    # 🔥 KEY FIX: round per event
    return quantize_money(fee)

def get_event_exec_qty(row: Dict[str, Any]) -> int:
    """
    Returns the actual executed quantity for an event row.
    Prefers execution-specific fields over generic shares.
    """
    if row.get("exec_size") is not None and int(row["exec_size"]) > 0:
        return int(row["exec_size"])
    if row.get("fill_size") is not None and int(row["fill_size"]) > 0:
        return int(row["fill_size"])
    return int(row["shares"])

def fetch_execution_events(cur: psycopg.Cursor, user_id: str) -> list[Dict[str, Any]]:
    """
    Fetches execution-related rows from trade_events using GetTransactions only.

    This avoids double counting duplicate execution rows also present in GetBlotter.
    """
    cur.execute(
        """
        SELECT
            user_id,
            symbol,
            side,
            order_state,
            shares,
            price,
            market_datetime,
            order_number,
            currency_charge_giveup,
            currency_charge_act,
            currency_charge_exec,
            currency_charge_clear,
            charge_sec,
            source_type
        FROM public.trade_events
        WHERE user_id = %s
          AND source_type = 'get_transactions'
          AND order_state IN ('Filled', 'Partially Filled')
          AND symbol IS NOT NULL
          AND side IN ('B', 'S', 'T')
          AND shares IS NOT NULL
          AND price IS NOT NULL
          AND market_datetime IS NOT NULL
        ORDER BY symbol, market_datetime, order_number
        """,
        (user_id,),
    )

    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def build_completed_trades(events: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """
    Builds completed trades from canonical execution events.

    Supports:
    - long and short trades
    - partial fills
    - multi-fill entries and exits
    - scaling in and scaling out

    A trade is completed when net position returns to zero.
    """
    completed_trades: list[Dict[str, Any]] = []
    positions: dict[tuple[str, str], Dict[str, Any]] = {}

    for row in events:
        symbol = row["symbol"]
        user_id = row["user_id"]
        key = (user_id, symbol)

        qty = get_event_exec_qty(row)
        price = decimal_or_zero(row["price"])
        side = row["side"]
        event_time = row["market_datetime"]
        order_number = row["order_number"]
        fee = compute_event_fee(row)

        if side == "B":
            signed_qty = qty
        elif side in ("S", "T"):
            signed_qty = -qty
        else:
            continue

        if key not in positions or not positions[key]:
            positions[key] = {
                "symbol": symbol,
                "user_id": user_id,
                "entry_time": None,
                "side_open": None,
                "position": 0,
                "entry_qty": 0,
                "entry_value": Decimal("0"),
                "exit_qty": 0,
                "exit_value": Decimal("0"),
                "fees": Decimal("0"),
                "entry_orders": [],
                "exit_orders": [],
            }

        pos = positions[key]

        if pos["position"] == 0:
            pos["entry_time"] = event_time
            pos["side_open"] = "LONG" if signed_qty > 0 else "SHORT"

        pos["fees"] += fee

        same_direction = (
            (pos["position"] >= 0 and signed_qty > 0) or
            (pos["position"] <= 0 and signed_qty < 0)
        )

        if same_direction:
            pos["entry_qty"] += qty
            pos["entry_value"] += price * Decimal(qty)

            if order_number:
                pos["entry_orders"].append(order_number)

            pos["position"] += signed_qty
            continue

        close_qty = min(abs(pos["position"]), abs(signed_qty))

        pos["exit_qty"] += close_qty
        pos["exit_value"] += price * Decimal(close_qty)

        if order_number:
            pos["exit_orders"].append(order_number)

        pos["position"] += signed_qty

        if pos["position"] == 0 and pos["entry_qty"] > 0 and pos["exit_qty"] > 0:
            entry_avg = quantize_price(pos["entry_value"] / Decimal(pos["entry_qty"]))
            exit_avg = quantize_price(pos["exit_value"] / Decimal(pos["exit_qty"]))

            closed_shares = min(pos["entry_qty"], pos["exit_qty"])
            side_open = pos["side_open"]

            if side_open == "LONG":
                gross_pl = (exit_avg - entry_avg) * Decimal(closed_shares)
            else:
                gross_pl = (entry_avg - exit_avg) * Decimal(closed_shares)

            completed_trades.append({
                "user_id": user_id,
                "symbol": symbol,
                "side_open": side_open,
                "entry_time": pos["entry_time"],
                "exit_time": event_time,
                "entry_avg_price": quantize_money(entry_avg),
                "exit_avg_price": quantize_money(exit_avg),
                "total_shares": closed_shares,
                "gross_pl": quantize_money(gross_pl),
                "total_fees": quantize_money(pos["fees"]),
                "net_pl": quantize_money(gross_pl - pos["fees"]),
                "entry_order_numbers": pos["entry_orders"],
                "exit_order_numbers": pos["exit_orders"],
                "source_notes": "Fill-aware trade reconstruction",
            })

            positions[key] = {}

    return completed_trades


def clear_trades_table(cur: psycopg.Cursor, user_id: str) -> None:
    """
    Clears existing derived trades for a user before rebuilding.
    """
    cur.execute(
        "DELETE FROM public.trades WHERE user_id = %s",
        (user_id,),
    )


def insert_completed_trade(
    cur: psycopg.Cursor,
    import_batch_id: uuid.UUID,
    trade: Dict[str, Any],
) -> None:
    """
    Inserts one completed trade into the trades table.
    """
    cur.execute(
        """
        INSERT INTO public.trades (
            import_batch_id,
            user_id,
            symbol,
            side_open,
            entry_time,
            exit_time,
            entry_avg_price,
            exit_avg_price,
            total_shares,
            gross_pl,
            total_fees,
            net_pl,
            entry_order_numbers,
            exit_order_numbers,
            source_notes
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            import_batch_id,
            trade["user_id"],
            trade["symbol"],
            trade["side_open"],
            trade["entry_time"],
            trade["exit_time"],
            trade["entry_avg_price"],
            trade["exit_avg_price"],
            trade["total_shares"],
            trade["gross_pl"],
            trade["total_fees"],
            trade["net_pl"],
            trade["entry_order_numbers"],
            trade["exit_order_numbers"],
            trade["source_notes"],
        ),
    )


def rebuild_trades(cur: psycopg.Cursor, import_batch_id: uuid.UUID, user_id: str) -> int:
    """
    Rebuilds derived completed trades from canonical execution events.
    """
    events = fetch_execution_events(cur, user_id)
    completed = build_completed_trades(events)

    clear_trades_table(cur, user_id)

    for trade in completed:
        insert_completed_trade(cur, import_batch_id, trade)

    logger.info("Rebuilt %s completed trades for user=%s", len(completed), user_id)
    return len(completed)

# -----------------------------------------------------------------------------
# Import End of Day
# -----------------------------------------------------------------------------

def import_end_of_day() -> None:
    """
    Executes the full end-of-day import workflow.

    Workflow:
    1. Attempt to enable JSON output in PPro
    2. Generate a unique import batch ID
    3. Start a database transaction
    4. Import GetTransactions
    5. Import GetBlotter
    6. Rebuild the daily summary
    7. Commit if all steps succeed
    8. Roll back the transaction if any step fails

    Raises:
        Exception: Re-raises any exception after rollback so the failure is visible.
    """
    import_batch_id = uuid.uuid4()
    today = date.today()

    logger.info("Starting end-of-day import. Batch ID: %s", import_batch_id)

    enable_json_output()

    with psycopg.connect(**DB_CONFIG) as conn:
        try:
            with conn.cursor() as cur:
                tx_count = import_source(
                    cur=cur,
                    import_batch_id=import_batch_id,
                    source_type="get_transactions",
                    endpoint_name="GetTransactions",
                    user_id=PPRO_USER_ID,
                )

                blotter_count = import_source(
                    cur=cur,
                    import_batch_id=import_batch_id,
                    source_type="get_blotter",
                    endpoint_name="GetBlotter",
                    user_id=PPRO_USER_ID,
                )

                rebuild_daily_summary(
                    cur=cur,
                    import_batch_id=import_batch_id,
                    user_id=PPRO_USER_ID,
                    summary_date=today,
                )

                trade_count = rebuild_trades(
                    cur=cur,
                    import_batch_id=import_batch_id,
                    user_id=PPRO_USER_ID,
                )

            conn.commit()
            logger.info(
                "Import successful. Batch ID: %s | GetTransactions: %s | GetBlotter: %s | Trades: %s",
                import_batch_id,
                tx_count,
                blotter_count,
                trade_count,
            )

        except Exception as exc:
            conn.rollback()
            logger.exception("Import failed. Transaction rolled back. Error: %s", exc)
            raise


if __name__ == "__main__":
    import_end_of_day()