#Used for shared database connection/config helpers
from sqlalchemy import create_engine

DATABASE_URL = "postgresql://postgres:yourpassword@localhost:5432/trading"

engine = create_engine(DATABASE_URL)