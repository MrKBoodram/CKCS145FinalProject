# Python Importer File to be run manually at the end of the trading day 
# Command to start PPro8 API: PPro8.exe -pproapi_port=8080
# Check in browser: http://localhost:8080/GetTransactions?user=YOUR_USER
# Note: PPro8 must still be running to work 
# To run the importer: import_trades.py

import hashlib
import json
import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import psycopg
import requests


# -----------------------------------------------------------------------------
# Configuration - Import from config.py
# -----------------------------------------------------------------------------

from scripts.config import DB_CONFIG, PPRO_BASE_URL, PPRO_USER_ID

# REQUEST_TIMEOUT_SECONDS = 20


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
        "message_type": record.get("Transaction") or record.get("MessageType"),
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
        "currency_charge_giveup": text_to_decimal(record.get("CurrencyChargeGiveup")),
        "currency_charge_act": text_to_decimal(record.get("CurrencyChargeAct")),
        "currency_charge_exec": text_to_decimal(record.get("CurrencyChargeExec")),
        "currency_charge_clear": text_to_decimal(record.get("CurrencyChargeClr")),
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
            via_api,
            raw_record,
            event_hash
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                  AND symbol IS NOT NULL
                GROUP BY symbol
                ORDER BY COUNT(*) DESC, symbol
                LIMIT 1
            ),
            'Initial summary build; refine realized P/L after validating real payloads.',
            NOW()
        FROM trade_events te
        WHERE te.user_id = %s
          AND te.trade_date = %s
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

            conn.commit()
            logger.info(
                "Import successful. Batch ID: %s | GetTransactions: %s | GetBlotter: %s",
                import_batch_id,
                tx_count,
                blotter_count,
            )

        except Exception as exc:
            conn.rollback()
            logger.exception("Import failed. Transaction rolled back. Error: %s", exc)
            raise


if __name__ == "__main__":
    import_end_of_day()