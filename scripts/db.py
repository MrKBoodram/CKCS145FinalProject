#Used for shared database connection/config helpers
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from scripts.config import DATABASE_URL

# DATABASE_URL = "postgresql://postgres:yourpassword@localhost:5432/trading"

engine: Engine = create_engine(DATABASE_URL, future=True)

def fetch_all_dicts(query: str, params: dict | None = None) -> list[dict]:
    """
    Executes an SQL Query and returns all rows as dictionary. 
    """
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        return[dict(row._mapping) for row in result]

def fetch_one_dict(query: str, params: dict | None = None) -> dict:
    """
    Executes an SQL Query and returns one row as a dictionary.
    """
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        row = result.fetchone()
        return dict(row._mapping) if row else {}