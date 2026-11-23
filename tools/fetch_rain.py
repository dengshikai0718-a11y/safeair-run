#!/usr/bin/env python3
"""
降雨機率預報網格 → data/rain.json（由 GitHub Actions 每小時與 PM2.5 一起執行，產物只放進 Pages 部署，不 commit）。

- 資料：Open-Meteo 預報 API 的 precipitation_probability（免金鑰、非商業使用；每日 10,000 次、每小時 5,000 次、每分鐘 600 次；
  資料 CC BY 4.0，須標示出處）。降雨機率來自 0.25°（約 27 km）解析度的集合預報，網格只是「內插取樣點」，不代表有 1.5 km 的真實解析度。
- 網格定義與台北市界都從 index.html 讀取（CONFIG.RAIN.grid、TAIPEI_OUTLINE），網頁與腳本永遠一致。
- 只查詢「涵蓋台北市界所需」的節點（約 190 個），分批（每批 50 個、間隔 2 秒），每個節點取「目前台北整點」起共 15 個整點
  （網頁取其中 13 個＋2 個時間差緩衝）。
- 失敗（429、逾時、回應異常）會重試；仍失敗時沿用線上目前的 rain.json（--fallback-url）；也沒有就不輸出檔案（網頁會顯示「降雨預報暫時無法取得」）。
  降雨是選用功能，此腳本一律以 exit 0 結束，不會讓部署失敗。
- 線上檔案若在 --min-age-min 分鐘內才產生，直接沿用，不再呼叫 API（避免短時間內重複 push 消耗額度）。

本機使用：python3 tools/fetch_rain.py --out data/rain.json
"""
import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = 'https://api.open-meteo.com/v1/forecast'
UA = 'SafeAirRun/1.0 (GitHub Actions; hourly rain grid)'
TPE = timezone(timedelta(hours=8))
HOURS = 15      # 目前整點起共 15 個整點（網頁使用 13 個，另 2 個作為時間差緩衝）
BATCH = 50
HERE = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    print(msg, flush=True)


def read_index():
    return open(os.path.join(HERE, '..', 'index.html'), encoding='utf-8').read()


def load_config(html):
    """從 index.html 讀 CONFIG.RAIN.grid 與 TAIPEI_OUTLINE（單一資料來源）"""
    m = re.search(r'grid:\s*\{([^}]*)\}', html[html.index('RAIN:'):])
    grid = {k: float(v) for k, v in re.findall(r'(\w+):\s*(-?[\d.]+)', m.group(1))}
    for k in ('lat0', 'lng0', 'dLat', 'dLng', 'rows', 'cols'):
        assert k in grid, f'CONFIG.RAIN.grid 缺少 {k}'
    grid['rows'], grid['cols'] = int(grid['rows']), int(grid['cols'])
    blk = re.search(r'const TAIPEI_OUTLINE = \[(.*?)\];', html, re.S).group(1)
    poly = [(float(a), float(b)) for a, b in re.findall(r'\[([\d.]+),\s*([\d.]+)\]', blk)]
    return grid, poly


def point_in_poly(lat, lng, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def needed_nodes(grid, poly):
    """涵蓋台北市界所需的節點：只要某個格子（4 個節點圍成）與市界重疊，4 個角落節點都需要"""
    need = set()
    for j in range(grid['rows'] - 1):
        for i in range(grid['cols'] - 1):
            la0, ln0 = grid['lat0'] + j * grid['dLat'], grid['lng0'] + i * grid['dLng']
            hit = any(point_in_poly(la0 + a / 4 * grid['dLat'], ln0 + b / 4 * grid['dLng'], poly) for a in range(5) for b in range(5))
            if not hit:  # 市界頂點落在格子內也算
                hit = any(la0 <= y <= la0 + grid['dLat'] and ln0 <= x <= ln0 + grid['dLng'] for y, x in poly)
            if hit:
                need.update({(j, i), (j + 1, i), (j, i + 1), (j + 1, i + 1)})
    return sorted(need)


def http_json(url, timeout=40):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def hour_key(dt):
    return dt.astimezone(TPE).strftime('%Y-%m-%dT%H:00')


def fetch_batch(points, retries=3, wait=20):
    params = urllib.parse.urlencode({
        'latitude': ','.join(f'{la:.4f}' for la, _ in points), 'longitude': ','.join(f'{ln:.4f}' for _, ln in points),
        'hourly': 'precipitation_probability', 'timezone': 'Asia/Taipei', 'forecast_days': '2',
    })
    for n in range(1, retries + 1):
        try:
            d = http_json(f'{API}?{params}')
            lst = d if isinstance(d, list) else [d]
            if len(lst) != len(points):
                raise ValueError(f'回傳 {len(lst)} 個地點，預期 {len(points)}')
            return lst
        except Exception as e:  # noqa: BLE001
            log(f'  第 {n}/{retries} 次失敗：{type(e).__name__}: {e}')
            if n < retries:
                time.sleep(wait * n)
    return None


def build():
    html = read_index()
    grid, poly = load_config(html)
    nodes = needed_nodes(grid, poly)
    log(f'網格 {grid["rows"]}×{grid["cols"]}（間距約 {grid["dLat"] * 110.95:.2f} km）；需查詢節點 {len(nodes)} 個')
    now = datetime.now(TPE)
    key0 = hour_key(now)
    values = [None] * (grid['rows'] * grid['cols'])
    got = 0
    hours = None
    for b in range(0, len(nodes), BATCH):
        chunk = nodes[b:b + BATCH]
        pts = [(grid['lat0'] + j * grid['dLat'], grid['lng0'] + i * grid['dLng']) for j, i in chunk]
        res = fetch_batch(pts)
        if res is None:
            log('  這一批失敗，放棄整份資料（避免只有部分區域有預報）')
            return None
        for (j, i), r in zip(chunk, res):
            h = r.get('hourly') or {}
            times, probs = h.get('time') or [], h.get('precipitation_probability') or []
            if key0 not in times:
                continue
            k = times.index(key0)
            seg = probs[k:k + HOURS]
            if len(seg) < HOURS:
                continue
            if hours is None:
                hours = times[k:k + HOURS]
            values[j * grid['cols'] + i] = [None if v is None else int(round(v)) for v in seg]
            got += 1
        if b + BATCH < len(nodes):
            time.sleep(2)
    if got < len(nodes) * 0.9 or hours is None:
        log(f'有效節點只有 {got}/{len(nodes)}，視為失敗')
        return None
    log(f'✅ 降雨預報：{got}/{len(nodes)} 個節點；時段 {hours[0]} ～ {hours[-1]}')
    return {
        'source': 'Open-Meteo｜precipitation_probability（降雨機率來源為 0.25° 集合預報）',
        'license': 'CC BY 4.0（https://open-meteo.com/）',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'grid': grid, 'hours': hours, 'values': values,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data/rain.json')
    ap.add_argument('--fallback-url', default='')
    ap.add_argument('--min-age-min', type=int, default=50)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)

    prev = None
    if args.fallback_url:
        try:
            prev = http_json(f'{args.fallback_url}?t={int(time.time())}', timeout=20)
            if not (isinstance(prev, dict) and prev.get('values')):
                prev = None
        except Exception as e:  # noqa: BLE001
            log(f'線上 rain.json 讀取失敗（可能是第一次部署）：{type(e).__name__}: {e}')
    if prev:
        try:
            age = (datetime.now(timezone.utc) - datetime.strptime(prev['fetchedAt'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)).total_seconds() / 60
            if age < args.min_age_min:
                log(f'線上 rain.json 只有 {age:.0f} 分鐘前產生（< {args.min_age_min}），直接沿用，不呼叫 API')
                out = prev
                json.dump(out, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                return
        except Exception:  # noqa: BLE001
            pass
    out = None
    try:
        out = build()
    except Exception as e:  # noqa: BLE001
        log(f'產生降雨網格失敗：{type(e).__name__}: {e}')
    if out is None and prev:
        log('::warning::Open-Meteo 失敗，沿用線上 rain.json（網頁會依資料時間判斷是否過期）')
        out = prev
    if out is None:
        log('::warning::沒有降雨預報可部署；網頁的降雨圖層會顯示「降雨預報暫時無法取得」')
        return
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    log(f'已寫入 {args.out}（{os.path.getsize(args.out):,} bytes）')


if __name__ == '__main__':
    main()
    sys.exit(0)
