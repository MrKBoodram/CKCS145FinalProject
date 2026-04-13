import pandas as pd
from sqlalchemy import create_engine
from flask import Flask, jsonify, render_template, request

from scripts.config import DATABASE_URL, FLASK_PORT
from scripts.queries import (
    get_dashboard_summary,
    get_daily_pnl,
    get_trades,
    get_symbol_breakdown
)

# engine = create_engine("postgresql://postgres:yourpassword@localhost:5432/trading")

engine = create_engine(DATABASE_URL)

app = Flask (__name__)

# Dashboard - Main Page
@app.route('/')
def index():
    return render_template('index.html')

# Top Cards
@app.route('/api/summary')
def api_summary():
    return jsonify(get_dashboard_summary())

# P&L / Chart Data
@app.route('/api/daily-pnl')
def daily_pnl(): 
    return jsonify(get_daily_pnl())

# Trade Data 
@app.route('/api/trades')
def api_trades():
    limit = request.args.get("limit", default=50, type=int)
    return jsonify(get_trades(limit=limit))

# Retrive Symbol Information 
@app.route('/api/symbols')
def api_symbols():
    return jsonify(get_symbol_breakdown())

if __name__ == '__main__':
    app.run( debug = True, port=FLASK_PORT)