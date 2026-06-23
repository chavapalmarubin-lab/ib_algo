"""core/ibdata.py — shared, read-only IBKR market data for all strategy agents.

One place every agent fetches bars, so the connection + contract specs live once.
Uses delayed data (type 3) and never places orders.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # ~/ib_algo (for config)
import config
from ib_insync import IB, Commodity, Stock


def _connect(cid_offset):
    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT,
               clientId=config.IB_CLIENT_ID + cid_offset, timeout=20)
    ib.reqMarketDataType(3)  # delayed if no live subscription
    return ib


def gold_daily(years="8", cid_offset=20):
    """[(YYYY-MM-DD, close)] daily spot-gold (XAUUSD CMDTY) bars from IBKR."""
    ib = _connect(cid_offset)
    try:
        c = Commodity("XAUUSD", "SMART", "USD")
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, endDateTime="", durationStr=f"{years} Y",
                                    barSizeSetting="1 day", whatToShow="MIDPOINT", useRTH=False)
        return [(str(b.date)[:10], float(b.close)) for b in bars]
    finally:
        ib.disconnect()


def gold_ohlc_daily(years="8", cid_offset=23):
    """[(YYYY-MM-DD, open, high, low, close)] daily spot-gold OHLC bars from IBKR (read-only)."""
    ib = _connect(cid_offset)
    try:
        c = Commodity("XAUUSD", "SMART", "USD")
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, endDateTime="", durationStr=f"{years} Y",
                                    barSizeSetting="1 day", whatToShow="MIDPOINT", useRTH=False)
        return [(str(b.date)[:10], float(b.open), float(b.high), float(b.low), float(b.close)) for b in bars]
    finally:
        ib.disconnect()


def gold_intraday(bar="15 mins", duration="6 M", cid_offset=24):
    """[(YYYY-MM-DD HH:MM, open, high, low, close)] intraday spot-gold bars from IBKR (read-only).
    bar e.g. '5 mins' / '15 mins' / '1 hour'. useRTH=False (gold trades ~24h)."""
    ib = _connect(cid_offset)
    try:
        c = Commodity("XAUUSD", "SMART", "USD")
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, endDateTime="", durationStr=duration,
                                    barSizeSetting=bar, whatToShow="MIDPOINT", useRTH=False)
        return [(str(b.date)[:16], float(b.open), float(b.high), float(b.low), float(b.close)) for b in bars]
    finally:
        ib.disconnect()


def stock_daily(symbol, years="5", cid_offset=21):
    """[(YYYY-MM-DD, close)] daily bars for a US stock (for the value agent later)."""
    ib = _connect(cid_offset)
    try:
        c = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(c)
        bars = ib.reqHistoricalData(c, endDateTime="", durationStr=f"{years} Y",
                                    barSizeSetting="1 day", whatToShow="TRADES", useRTH=True)
        return [(str(b.date)[:10], float(b.close)) for b in bars]
    finally:
        ib.disconnect()
