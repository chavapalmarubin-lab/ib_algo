# IB Algo — Claude + Interactive Brokers paper-trading bot

A local Python project that connects **Claude Code** to the **Interactive Brokers API** to
scan, signal, and (optionally) place **paper** trades. Built from the approach taught across
the reference videos (Humbled Trader, Rachel Doji, Nate Herk, et al.). **Paper-only and
execution-OFF by default** — see Safety.

---

## THE HONEST FRAME (read first)
- **Setup is the easy part. The edge is the hard part.** In the Humbled Trader build, a strategy
  that backtested well on TradingView produced "very meh" results once wired to live execution —
  her own manual trading still beat the bot. The bot does not create an edge; it executes one you
  already have. We develop on paper for *weeks* before risking a cent.
- **A bot with no edge loses money faster and more consistently.** That's a direct quote from the
  source. Our job: build the plumbing cleanly, then test strategies honestly.
- The "$102k in a month" style videos are marketing. Treat results claims as unverified.

## SAFETY POSTURE (enforced in config.py)
- Connects to the **paper port (7497)** by default. A **live port is refused** unless you
  personally set `IB_ALLOW_LIVE=1`.
- **Order execution is OFF** (`IB_EXECUTION_ENABLED=0`) until you flip it on — the bot scans and
  signals but places no order, even paper, until then.
- A `KILL` file in the project halts the bot instantly.
- I (Claude) will **never place a live trade or move real money** for you. Live execution is your
  decision, your hands.

---

## PREREQUISITES (one-time)
1. **Trader Workstation (TWS)** or **IB Gateway** — IBKR's desktop app. Download from interactivebrokers.com.
2. **Python 3.12+** — already on your Mac (`/usr/local/bin/python3`).
3. **Claude Code / Claude desktop** — you already have this.

## STEP 1 — Create your IBKR PAPER account  *(you do this; I can't create accounts)*
Following the Ryan O'Connell + Humbled Trader videos. The exact wording on IBKR's site changes, so
follow the on-screen prompts; the shape is:
1. Go to interactivebrokers.com → open an account (the free **paper / demo** path; you do **not**
   need a funded account or a market-data subscription to paper trade).
2. Verify your email / identity as prompted.
3. In the client portal or TWS login, switch to / enable the **Paper Trading** account.
4. Log into **TWS** using your **paper** credentials. You'll see a simulated account (it may start
   with $1,000,000 of paper money — reset it to something realistic like $25–50k in account settings).

> Tell me when you're logged into TWS paper and I'll run the connection test with you.

## STEP 2 — Enable the API in TWS  *(you do this, once)*
In TWS: **File → Global Configuration → API → Settings**:
- ✅ Check **"Enable ActiveX and Socket Clients"**
- Set **Socket port = 7497** (this is the paper port; live would be 7496 — we are NOT using that)
- ✅ Add **127.0.0.1** to **Trusted IPs** (scroll down)
- Under **API → General**: leave **Read-Only API UNCHECKED** only when you're ready to let it place
  paper orders. Keep it **checked (read-only)** while we're just testing the connection.
- Click **Apply → OK**.

## STEP 3 — Python environment  *(I'll run these for you)*
```bash
cd ~/ib_algo
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then edit .env if needed
```

## STEP 4 — Test the connection (read-only)
With TWS running + logged into paper + API enabled:
```bash
python connect_test.py
```
Expect: `CONNECTED ✓`, your account NetLiquidation / BuyingPower, and open positions (0 to start).
This mirrors the first test in the Humbled Trader video ("tell me my buying power / open positions").

---

## THE BUILD ROADMAP (what we develop next, in order)
Straight from the consolidated video method:
1. **`rules.json`** — the strategy as data: universe, entry filters, exit logic, risk caps
   (e.g. "above prior-day high, prior close > 200-day; stop 1% below LoD; partial at 0.75R;
   break-even at 1R; trail under 5-min swing lows; risk 1%/trade, max 10% position").
2. **Universe + scanner** — a ticker list (e.g. S&P 500 or >$1B cap, >$3) → a pre-filter
   (e.g. top-20 gapped up >3%).
3. **The brain loop** — every N minutes during market hours: scan → decide → (if execution on)
   place entries, manage stops/partials/trails → force-flat before the close. *(This is a closed
   loop with a verifiable goal — same pattern as the rest of our systems.)*
4. **Telegram alerts** — the scan list + every fill + an end-of-day P&L summary to your phone.
5. **R-multiple dashboard** — track performance per trade, paper first.
6. **(Later) a small agent team** — separate scanner / risk / execution / journal agents, with a
   **separate verifier** (the maker-≠-auditor rule). Backtest on QuantConnect or locally before paper.

## ARCHITECTURE CHOICE (Tim Sergev video)
- **Local (this project):** TWS/IB Gateway running on your Mac, Python talks to it over the socket.
  Full control, your machine must be on. **We start here.**
- **QuantConnect (cloud):** hosted backtesting + deployment, doesn't need your machine running.
  Good for rigorous backtests later. We can add it as the backtest layer.

---
*This is educational tooling, not financial advice. Develop and prove every strategy on paper before
any real-money decision — which is always yours alone.*
