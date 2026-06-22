"""strategy_scout.py — reviews + learns from crawled Reddit algo-trading content.

The "scout" reads what the Reddit crawler found and, for every post, asks a CHEAP open
model (GLM-5.2 on DeepInfra, DeepSeek fallback — NOT Opus) to:
  * decide whether the post contains a real, mechanical trading strategy,
  * extract entry / exit / params / timeframe,
  * judge it USE (codeable now) / MIMIC (good idea, needs work) / PASS (hype/none),
  * say what DATA it needs (daily / intraday / OHLC) so we know if it can drop into the lab.
Every verdict is appended to SCOUT_LEDGER.jsonl — that IS the learning: the scout never
re-reviews a post, and the ledger accumulates a growing, de-duplicated knowledge base of
strategy ideas + how codeable each is. Prints a digest of USE/MIMIC candidates each run.
Research only — it proposes; it never edits the lab or trades.
"""
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent      # ~/ib_algo
SCOUT = ROOT / "scout"
RAW = SCOUT / "reddit_raw.json"
LEDGER = SCOUT / "SCOUT_LEDGER.jsonl"
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
MODELS = ["zai-org/GLM-5.2", "deepseek-ai/DeepSeek-V3.2"]   # cheap open tier, fallback


def _key():
    p = pathlib.Path.home() / ".th_deepinfra_key"
    if p.exists():
        return p.read_text().strip()
    return os.getenv("DEEPINFRA_API_KEY", "").strip()


def chat(system, user, max_tokens=1600):
    """OpenAI-compatible DeepInfra call; tries GLM then DeepSeek; tolerates reasoning models."""
    key = _key()
    for model in MODELS:
        try:
            body = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}
            req = urllib.request.Request(DEEPINFRA_URL, data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
            msg = resp["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:                       # some reasoning models stash text here
                content = (msg.get("reasoning_content") or "").strip()
            if content:
                return content, model
        except Exception as e:
            last = repr(e)[:120]
            continue
    return "", None


def _post_field(p, *names, default=""):
    for n in names:
        if p.get(n):
            return p[n]
    return default


def reviewed_ids():
    done = set()
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            try:
                d = json.loads(line)
                if d.get("verdict") in ("USE", "MIMIC", "PASS"):   # parse failures retry
                    done.add(d.get("post_id"))
            except Exception:
                pass
    return done


PROMPT = """You review a Reddit post from an algorithmic-trading community and decide whether it contains a REAL, mechanical trading strategy a quant could code and backtest.

Return ONLY a JSON object (no prose, no markdown fence) with these keys:
{"has_strategy": true/false,
 "strategy_type": "trend|breakout|mean-reversion|momentum|SMC/ICT|seasonal|stat-arb|ML|options|other|none",
 "timeframe": "daily|4h|1h|15m|5m|1m|multi|unknown",
 "entry": "specific mechanical entry rule, or empty",
 "exit": "stop/target/exit rule, or empty",
 "params": "indicator lengths / RR / sessions mentioned, or empty",
 "data_needed": "daily-close|daily-OHLC|intraday|other",
 "codeable": "yes|partial|no",
 "signal_idea": "one line: how you'd implement make_signal(series, lookback)->{0,1}, or empty",
 "verdict": "USE|MIMIC|PASS",
 "why": "one short sentence"}

USE = mechanical + codeable now. MIMIC = good idea but needs defining/discretionary. PASS = hype, marketing, screenshot-only, or no actual rules. Do not invent rules that are not in the text."""


def review_post(p):
    title = _post_field(p, "title", "postTitle", default="")
    body = _post_field(p, "text", "body", "selftext", "content", "postText", default="")
    user = f"TITLE: {title}\n\nBODY:\n{body[:6000]}"
    out, model = chat(PROMPT, user)
    rec = {"model": model, "raw_ok": bool(out)}
    if out:
        obj = _extract_json(out)
        if obj is not None:
            rec.update(obj)
        else:
            rec["parse_error"] = out[:200]
    return rec


def _extract_json(text):
    """Find the first balanced {...} object in possibly-fenced, reasoning-prefixed text."""
    t = text.replace("```json", " ").replace("```", " ")
    start = t.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find("{", start + 1)
    return None


def main():
    if not RAW.exists():
        sys.exit(f"no crawl file at {RAW} — run the Reddit crawl first")
    posts = json.loads(RAW.read_text())
    done = reviewed_ids()
    new = [p for p in posts if _post_field(p, "id", "postId", "url", "link") not in done]
    print(f"scout: {len(posts)} crawled, {len(done)} already reviewed, {len(new)} new to review")

    counts = {"USE": 0, "MIMIC": 0, "PASS": 0}
    use_rows, mimic_rows = [], []
    for p in new:
        pid = _post_field(p, "id", "postId", "url", "link")
        title = _post_field(p, "title", "postTitle", default="(untitled)")
        r = review_post(p)
        v = r.get("verdict", "PASS")
        counts[v] = counts.get(v, 0) + 1
        row = {"ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
               "post_id": pid, "url": _post_field(p, "url", "link"),
               "subreddit": _post_field(p, "communityName", "subreddit", "community"),
               "score": _post_field(p, "upVotes", "score", "ups", default=0),
               "title": title, **r}
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row) + "\n")
        if v == "USE":
            use_rows.append(row)
        elif v == "MIMIC":
            mimic_rows.append(row)

    print(f"\n  verdicts this run: USE={counts.get('USE',0)} MIMIC={counts.get('MIMIC',0)} PASS={counts.get('PASS',0)}")
    print("\n  === USE — mechanical + codeable now ===")
    for r in use_rows:
        print(f"  • [{r.get('strategy_type')}/{r.get('data_needed')}] {r.get('title')[:70]}")
        print(f"      signal: {r.get('signal_idea','')[:110]}")
    print("\n  === MIMIC — good idea, needs work ===")
    for r in mimic_rows[:10]:
        print(f"  • [{r.get('strategy_type')}/{r.get('timeframe')}] {r.get('title')[:70]} — {r.get('why','')[:60]}")

    # learning summary across the WHOLE ledger
    allrows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    daily_use = [r for r in allrows if r.get("verdict") == "USE" and "daily" in str(r.get("data_needed"))]
    print(f"\n  LEDGER: {len(allrows)} posts reviewed all-time · {sum(1 for r in allrows if r.get('verdict')=='USE')} USE · "
          f"{len(daily_use)} of them daily-bar codeable (lab-ready candidates)")


if __name__ == "__main__":
    main()
