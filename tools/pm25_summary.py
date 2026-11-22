#!/usr/bin/env python3
"""
PM2.5 資料來源欄位摘要腳本（不把完整 JSON 印進對話 / 終端機）。

用法：
  python3 tools/pm25_summary.py https://pm25.lass-net.org/data/last-all-airbox.json
  python3 tools/pm25_summary.py 本機檔案.json

輸出：所有欄位名稱與出現比例、PM2.5 與經緯度的數值範圍與空值數、
時間戳記格式與時區範例、資料新鮮度、台北範圍框內站數，以及 3 筆範例測站。
欄位名稱可用參數覆寫：--pm s_d0 --lat gps_lat --lon gps_lon --ts timestamp --list feeds
"""
import argparse, collections, datetime as dt, json, re, sys, urllib.request

BBOX = dict(min_lng=121.45, max_lng=121.67, min_lat=24.96, max_lat=25.21)

def load(src):
    if re.match(r"https?://", src):
        with urllib.request.urlopen(src, timeout=30) as r:
            print(f"HTTP {r.status}  Access-Control-Allow-Origin={r.headers.get('Access-Control-Allow-Origin')!r}  "
                  f"Last-Modified={r.headers.get('Last-Modified')!r}")
            raw = r.read()
    else:
        raw = open(src, "rb").read()
    print(f"大小：{len(raw):,} bytes")
    return json.loads(raw)

def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--list", default="feeds")
    ap.add_argument("--pm", default="s_d0"); ap.add_argument("--lat", default="gps_lat")
    ap.add_argument("--lon", default="gps_lon"); ap.add_argument("--ts", default="timestamp")
    a = ap.parse_args()
    d = load(a.src)
    top = {k: (f"list[{len(v)}]" if isinstance(v, list) else v if not isinstance(v, dict) else "{…}") for k, v in d.items()} if isinstance(d, dict) else type(d).__name__
    print("最上層：", top)
    rows = d[a.list] if isinstance(d, dict) else d
    n = len(rows)
    cnt = collections.Counter(k for r in rows for k in r)
    print(f"\n測站數：{n}\n欄位出現比例：")
    for k, c in cnt.most_common():
        print(f"  {k:<14}{c * 100 / n:5.0f}%")
    for k in (a.pm, a.lat, a.lon):
        vals = [r.get(k) for r in rows]
        nums = [x for x in map(num, vals) if x is not None]
        print(f"\n{k}：缺漏/null={sum(v is None for v in vals)}  非數值={sum(v is not None and num(v) is None for v in vals)}  "
              f"範圍={min(nums) if nums else '—'}～{max(nums) if nums else '—'}  型別={collections.Counter(type(v).__name__ for v in vals)}")
    pm = [num(r.get(a.pm)) for r in rows]
    print(f"{a.pm} 等於 0：{sum(x == 0 for x in pm if x is not None)}  <0：{sum(x < 0 for x in pm if x is not None)}  >500：{sum(x > 500 for x in pm if x is not None)}")
    ts = [str(r.get(a.ts, "")) for r in rows]
    fmts = collections.Counter(re.sub(r"\d", "9", t) for t in ts)
    print(f"\n時間戳記格式：{dict(fmts.most_common(5))}\n範例：{sorted(ts)[:1]} … {sorted(ts)[-1:]}")
    now = dt.datetime.now(dt.timezone.utc); ages = []
    for t in ts:
        try:
            ages.append((now - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).total_seconds() / 60)
        except ValueError:
            pass
    if ages:
        print(f"資料年齡（分鐘）：最新 {min(ages):.0f}、最舊 {max(ages):.0f}、≤60 分鐘 {sum(x <= 60 for x in ages)} 站")
    tp = [r for r in rows if (la := num(r.get(a.lat))) is not None and (lo := num(r.get(a.lon))) is not None
          and BBOX["min_lat"] <= la <= BBOX["max_lat"] and BBOX["min_lng"] <= lo <= BBOX["max_lng"]]
    print(f"台北範圍框內：{len(tp)} 站，其中 {a.pm}=0 者 {sum(num(r.get(a.pm)) == 0 for r in tp)} 站")
    print("\n範例測站（前 12 個欄位）：")
    for r in (tp or rows)[:3]:
        print(" ", {k: r[k] for k in list(r)[:12]})

if __name__ == "__main__":
    sys.exit(main())
