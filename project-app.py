import pandas as pd
from sqlalchemy import create_engine
from flask import Flask, render_template

from scripts.config import DATABASE_URL, FLASK_PORT

# engine = create_engine("postgresql://postgres:yourpassword@localhost:5432/trading")

engine = create_engine(DATABASE_URL)

app = Flask (__name__)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run( debug = True, port=FLASK_PORT)