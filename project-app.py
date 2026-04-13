import pandas as pd
from sqlalchemy import create_engine
from flask import Flask, jsonify, render_template, request

from scripts.config import DATABASE_URL, FLASK_PORT
from scripts.queries import (
    get_dashboard_summary,
    get_daily_pnl,
    get_trades,
    get_symbol_breakdown,
    get_available_symbols
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
    symbol = request.args.get("symbol")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    return jsonify(get_dashboard_summary(symbol=symbol, start_date=start_date, end_date=end_date))

# P&L / Chart Data
@app.route('/api/daily-pnl')
def daily_pnl(): 
    symbol = request.args.get("symbol")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    return jsonify(get_daily_pnl(symbol=symbol, start_date=start_date, end_date=end_date))

# Trade Data 
@app.route('/api/trades')
def api_trades():
    limit = request.args.get("limit", default=50, type=int)
    symbol = request.args.get("symbol")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    return jsonify(get_trades(limit=limit, symbol=symbol, start_date=start_date, end_date=end_date))

# Retrive Symbol Information 
@app.route('/api/symbols')
def api_symbols():
    symbol = request.args.get("symbol")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    return jsonify(get_symbol_breakdown(symbol=symbol, start_date = start_date, end_date = end_date))

@app.route("/api/available-symbols")
def api_available_symbols():
    return jsonify(get_available_symbols())

if __name__ == '__main__':
    app.run( debug = True, port=FLASK_PORT)