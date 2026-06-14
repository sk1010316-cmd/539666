"""
build_data.py
1) 抓取今彩539近期開獎，輸出 data.json
2) 每天替四種方法記錄「明日推薦」並對前一日評分（live_log，累積在 repo）
資料來源：台灣彩券官網（taiwanlottery 套件）。
"""
import json
import os
import re
import random
from datetime import datetime, timezone, timedelta
from TaiwanLottery import TaiwanLotteryCrawler

MONTHS_BACK = 12
WINDOW = 20                       # 近期視窗，需與 index.html 一致
METHODS = ["hot", "cold", "balanced", "random"]
TZ = timezone(timedelta(hours=8))
DATA_FILE = "data.json"


# ---------- 抓資料 ----------
def year_months(n):
    now = datetime.now(TZ)
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def norm_date(v):
    nums = re.findall(r"\d+", str(v))
    if len(nums) >= 3:
        y, mo, d = nums[0], nums[1], nums[2]
        if len(y) <= 3:
            y = str(int(y) + 1911)
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return str(v)


def extract_numbers(rec):
    for k, v in rec.items():
        if "獎號" in str(k) and isinstance(v, list):
            try:
                return [int(x) for x in v][:5]
            except Exception:
                pass
    for v in rec.values():
        if isinstance(v, list) and len(v) >= 5:
            try:
                return [int(x) for x in v][:5]
            except Exception:
                pass
    return None


def extract_date(rec):
    for k, v in rec.items():
        if "日期" in str(k) or "date" in str(k).lower():
            return norm_date(v)
    return None


def extract_period(rec):
    for k, v in rec.items():
        if "期別" in str(k) or "period" in str(k).lower():
            return str(v)
    return ""


def fetch_draws():
    crawler = TaiwanLotteryCrawler()
    seen = {}
    for y, m in year_months(MONTHS_BACK):
        try:
            res = crawler.daily_cash([str(y), f"{m:02d}"])
        except Exception as e:
            print(f"skip {y}-{m:02d}: {e}")
            continue
        if not res:
            continue
        for rec in res:
            nums = extract_numbers(rec)
            date = extract_date(rec)
            if not nums or len(nums) != 5 or not date:
                continue
            seen[date] = {"date": date, "period": extract_period(rec), "n": sorted(nums)}
    return sorted(seen.values(), key=lambda d: d["date"])


# ---------- 推薦引擎（須與 index.html 對齊）----------
def compute_stats(history, window):
    total = len(history)
    rs = history[-window:] if window else history
    arr = []
    for num in range(1, 40):
        count = recent = 0
        last = -1
        for d in range(total):
            if num in history[d]:
                count += 1
                last = d
        for row in rs:
            if num in row:
                recent += 1
        gap = total if last == -1 else total - 1 - last
        arr.append((num, count, recent, gap))
    return arr, total


def recommend(history, window, method, seed=0):
    arr, total = compute_stats(history, window)
    if total == 0 and method != "random":
        return []
    if method == "hot":
        s = sorted(arr, key=lambda x: (-x[2], -x[1], x[0]))
    elif method == "cold":
        s = sorted(arr, key=lambda x: (-x[3], x[0]))
    elif method == "balanced":
        counts = [x[1] for x in arr]
        gaps = [x[3] for x in arr]
        clo, chi = min(counts), max(counts)
        glo, ghi = min(gaps), max(gaps)

        def sc(x):
            nf = (x[1] - clo) / (chi - clo) if chi > clo else 0
            ng = (x[3] - glo) / (ghi - glo) if ghi > glo else 0
            return nf + ng

        s = sorted(arr, key=lambda x: (-sc(x), x[0]))
    else:  # random（以日誌長度為種子，保證可重現）
        rng = random.Random(seed)
        pool = list(range(1, 40))
        rng.shuffle(pool)
        return sorted(pool[:3])
    return sorted([x[0] for x in s[:3]])


# ---------- 雲端推薦日誌 ----------
def update_live_log(prev_log, draws):
    log = list(prev_log) if prev_log else []
    ns = [d["n"] for d in draws]
    if not ns:
        return log

    have_base = {e["base_date"] for e in log}
    latest = draws[-1]["date"]

    # 以「最新已知開獎」為基準，替下一期記錄四法推薦（每個基準日只記一次）
    if latest not in have_base and len(ns) >= WINDOW:
        for m in METHODS:
            picks = recommend(ns, WINDOW, m, seed=len(ns))
            log.append({
                "base_date": latest, "method": m, "picks": picks,
                "hits": None, "grade_date": None,
            })

    # 對尚未評分的紀錄評分（找 base_date 之後的第一期）
    by_date = {d["date"]: d["n"] for d in draws}
    dates = sorted(by_date)
    for e in log:
        if e["hits"] is None:
            nxt = next((dt for dt in dates if dt > e["base_date"]), None)
            if nxt:
                actual = set(by_date[nxt])
                e["hits"] = len(set(e["picks"]) & actual)
                e["grade_date"] = nxt
    return log


def main():
    draws = fetch_draws()

    prev_log = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                prev_log = json.load(f).get("live_log", [])
        except Exception:
            prev_log = []

    live_log = update_live_log(prev_log, draws)

    out = {
        "game": "今彩539",
        "updated": datetime.now(TZ).isoformat(timespec="seconds"),
        "count": len(draws),
        "window": WINDOW,
        "draws": draws,
        "live_log": live_log,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(draws)} draws, live_log {len(live_log)} entries")


if __name__ == "__main__":
    main()
