"""core/multidata.py — multi-asset, CACHED, read-only market data for the lab.

Why this exists: the lab used to be gold-only, so every result was hostage to one
regime (the 2018-26 gold bull). This module fetches a whole UNIVERSE of instruments
(metals, FX majors, equity-index ETFs, oil, bonds) through ONE IBKR connection and
caches each to a CSV. Backtests then read the CACHE — reproducible, fast, and no longer
dependent on a live TWS session. maker != auditor unchanged; this only supplies data.

  python -m core.multidata --fetch     # pull universe from IBKR, write data/universe/*.csv
  python -m core.multidata --list      # show what's cached
"""
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]   # ~/ib_algo
CACHE = ROOT / "data" / "universe"
SPEC_FILE = ROOT / "data" / "universe.json"

# Default universe — subscription-free IBKR historical (metals=MIDPOINT spot, FX=MIDPOINT,
# ETFs=TRADES/RTH for indices/oil/bonds). Edit data/universe.json to change without code edits.
DEFAULT_UNIVERSE = [
    {"name": "gold",   "kind": "commodity", "symbol": "XAUUSD", "exchange": "SMART", "currency": "USD", "what": "MIDPOINT", "rth": False, "asset_class": "metal"},
    {"name": "silver", "kind": "commodity", "symbol": "XAGUSD", "exchange": "SMART", "currency": "USD", "what": "MIDPOINT", "rth": False, "asset_class": "metal"},
    {"name": "eurusd", "kind": "forex", "symbol": "EURUSD", "exchange": "IDEALPRO", "currency": "USD", "what": "MIDPOINT", "rth": False, "asset_class": "fx"},
    {"name": "gbpusd", "kind": "forex", "symbol": "GBPUSD", "exchange": "IDEALPRO", "currency": "USD", "what": "MIDPOINT", "rth": False, "asset_class": "fx"},
    {"name": "usdjpy", "kind": "forex", "symbol": "USDJPY", "exchange": "IDEALPRO", "currency": "JPY", "what": "MIDPOINT", "rth": False, "asset_class": "fx"},
    {"name": "audusd", "kind": "forex", "symbol": "AUDUSD", "exchange": "IDEALPRO", "currency": "USD", "what": "MIDPOINT", "rth": False, "asset_class": "fx"},
    {"name": "spx_etf", "kind": "stock", "symbol": "SPY", "exchange": "SMART", "currency": "USD", "what": "TRADES", "rth": True, "asset_class": "equity"},
    {"name": "ndx_etf", "kind": "stock", "symbol": "QQQ", "exchange": "SMART", "currency": "USD", "what": "TRADES", "rth": True, "asset_class": "equity"},
    {"name": "oil_etf", "kind": "stock", "symbol": "USO", "exchange": "SMART", "currency": "USD", "what": "TRADES", "rth": True, "asset_class": "energy"},
    {"name": "bonds_etf", "kind": "stock", "symbol": "TLT", "exchange": "SMART", "currency": "USD", "what": "TRADES", "rth": True, "asset_class": "rates"},
]


def universe():
    if SPEC_FILE.exists():
        try:
            return json.loads(SPEC_FILE.read_text())["instruments"]
        except Exception:
            pass
    return DEFAULT_UNIVERSE


def _contract(spec):
    from ib_insync import Commodity, Forex, Stock
    k = spec["kind"]
    if k == "commodity":
        return Commodity(spec["symbol"], spec["exchange"], spec["currency"])
    if k == "forex":
        return Forex(spec["symbol"])
    if k == "stock":
        return Stock(spec["symbol"], spec["exchange"], spec["currency"])
    raise ValueError(f"unknown kind {k}")


def fetch_universe(years="8", cid_offset=40, log=print):
    """Connect ONCE, pull daily OHLC for every instrument. Returns {name: [(date,o,h,l,c)]}."""
    import config
    from ib_insync import IB
    ib = IB()
    ib.connect(config.IB_HOST, config.IB_PORT, clientId=config.IB_CLIENT_ID + cid_offset, timeout=20)
    ib.reqMarketDataType(3)
    out = {}
    try:
        for spec in universe():
            try:
                c = _contract(spec)
                ib.qualifyContracts(c)
                bars = ib.reqHistoricalData(c, endDateTime="", durationStr=f"{years} Y",
                                            barSizeSetting="1 day", whatToShow=spec["what"],
                                            useRTH=spec.get("rth", False))
                rows = [(str(b.date)[:10], float(b.open), float(b.high), float(b.low), float(b.close)) for b in bars]
                out[spec["name"]] = rows
                log(f"  {spec['name']:<10} {len(rows):>5} bars  {rows[0][0] if rows else '-'} .. {rows[-1][0] if rows else '-'}")
            except Exception as e:
                log(f"  {spec['name']:<10} FETCH FAILED: {e}")
    finally:
        ib.disconnect()
    return out


def cache_universe(years="8", cid_offset=40, log=print):
    CACHE.mkdir(parents=True, exist_ok=True)
    data = fetch_universe(years, cid_offset, log)
    for name, rows in data.items():
        if not rows:
            continue
        with open(CACHE / f"{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "high", "low", "close"])
            w.writerows(rows)
    log(f"cached {len(data)} instruments -> {CACHE}")
    return data


def load_cached(name):
    """[(date,open,high,low,close)] from cache, or [] if not cached."""
    fp = CACHE / f"{name}.csv"
    if not fp.exists():
        return []
    rows = []
    with open(fp) as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    return rows


def cached_names():
    if not CACHE.exists():
        return []
    return sorted(p.stem for p in CACHE.glob("*.csv"))


def closes(name):
    """[(date, close)] convenience."""
    return [(d, c) for d, o, h, l, c in load_cached(name)]


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        cache_universe()
    elif "--list" in sys.argv:
        for n in cached_names():
            rows = load_cached(n)
            print(f"  {n:<10} {len(rows):>5} bars  {rows[0][0]} .. {rows[-1][0]}")
    else:
        print(__doc__)
