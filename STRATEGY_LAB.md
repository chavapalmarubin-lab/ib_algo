# STRATEGY LAB — the self-improving quant research loop (IBKR paper)

The purpose of the paper account: **test many strategies, learn which ones work, keep developing models** —
on real market data, with zero money at risk, riding the existing Trading Hearts infrastructure. This is the
loop doctrine (`agents/LOOP_ENGINEERING_DOCTRINE.md`) applied to trading: a closed loop with a verifiable goal,
a separate auditor, and externalized state.

---

## THE LOOP (DAME)
- **D — Trigger:** every morning before the US open (scheduled), + on demand.
- **A — Agents (makers):** the morning scan surfaces candidate setups; each *strategy* is a signal-maker.
- **M — Verifiable goal (auditor):** `core/engine.py` runs walk-forward IS/OOS + Monte-Carlo and judges every
  strategy against fixed gates (Sharpe ≥ 1.0, DD ≤ 20%, ruin ≤ 1%). **The maker never grades itself.**
- **E — State / memory:** `agents/STRATEGY_LEDGER.jsonl` — every verdict, every day. "What works" = strategies
  that keep passing / scoring high OOS; "what doesn't" decays down the leaderboard. This is the learning.

```
  morning scan ─► strategy hypotheses ─► core gate (auditor) ─► STRATEGY_LEDGER ─► leaderboard + track record
        ▲                                                                                   │
        └──────────────────────  iterate: promote winners, retire losers  ◄────────────────┘
```

## WHAT EXISTS NOW (built today, runnable)
- `core/ibdata.py` — shared read-only IBKR data (gold + stocks).
- `core/engine.py` — the auditor: vol-target backtest, walk-forward, Monte-Carlo, gates (ported from TH Quant).
- `agents/gold_quant/` — strategy #1 (real-yield gold), already gated → OOS Sharpe 0.52, FAIL (honest).
- `agents/lab.py` — runs **all** registered strategies, writes the ledger, prints leaderboard + track record.
  Ships with 3 gold strategies to compare: real-yield, trend-MA, donchian breakout. Add one = one list entry.
- `agents/value/` — stub for the fundamentals (PEGY undervalued/overvalued) agent.

## STRATEGY HYPOTHESES TO TEST (from the videos + Reddit)
The digested videos are mostly **intraday gold** setups — concrete, testable:
- **Trend-follow** (ride trends / MA) → `gold_trend_ma` (built).
- **Breakout / momentum** → `gold_donchian` (built).
- **SMC / ICT structure:** Change-of-Character (CHoCH) break-of-structure entries, **supply/demand zones**,
  **liquidity sweeps** on the 15-min — to add as intraday signals once we pull intraday bars.
- **Real-yield macro** (TH Quant) → `gold_realyield` (built).
- Reddit/`r/algotrading` edges → folded in as new STRATEGIES entries after the crawl.
> Honest frame: most retail "strategies" have no real edge. The gate is there precisely to kill the ~95% that
> don't survive walk-forward + Monte-Carlo. A FAIL is the system working.

## LEVERAGE THE TH INFRASTRUCTURE
- **GeoMatrix** (geopolitical/macro signals, `geomatrix-nightly-refresh`) → a *regime* input: condition a
  strategy on the macro regime (e.g. only take gold-long when GeoMatrix risk/real-yield regime agrees). This is
  TH Quant's parked "thesis B" (regime-conditional) — the lab is where we test it cheaply.
- **News crawler** (`th-character-news-daily`, Supabase `news_articles`) → the morning scan's news/sentiment layer.
- **Loop doctrine + cast_learning pattern** → the STRATEGY_LEDGER is to strategies what cast_learning is to the cast.
- **CFO** → track API/data cost of the lab; **compliance** stays trivially satisfied (research only, no public posts).

## NEXT BUILD STEPS (in order)
1. **Morning scan agent** — pre-open: pull overnight gold move + GeoMatrix regime + news; emit a watch note.
2. **Intraday bars** in `core/ibdata` (5/15-min) → add the SMC/breakout intraday strategies the videos teach.
3. **Regime overlay** — wire GeoMatrix as a gating condition (test thesis B without overfitting).
4. **Schedule** `lab.py` daily (07:00 ET) → the ledger grows → weekly "what's working" report.
5. Only after a strategy clears the gate **out-of-sample for weeks** does it become paper-execution-eligible —
   and live execution always remains the CEO's hands.

---
*Research only. Develop and prove on paper; the gate decides; a human decides to ever risk money.*
