#!/usr/bin/env python3
"""
環境部「空氣品質指標（AQI）」資料集探測腳本（階段 A 第 1 時段，只輸出摘要）。

- 金鑰只從環境變數 MOENV_API_KEY 讀取；所有輸出都會把金鑰替換成 ***，不會印出金鑰。
- 不寫入任何資料檔（原始資料不落地、不 commit）。
- 在 GitHub Actions 中另外把摘要寫進 $GITHUB_STEP_SUMMARY（執行頁面的 Summary 區塊）。

本機測試（不連網）：python3 tools/moenv_probe.py --file 範例.json
"""
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

API_BASE = 'https://data.moenv.gov.tw/api/v2/aqx_p_432'
TPE = timezone(timedelta(hours=8))
# 與 index.html CONFIG.BBOX 相同的台北範圍框，以及向外約 10 km 的「含鄰近新北」範圍框
BBOX = dict(min_lng=121.45, max_lng=121.67, min_lat=24.96, max_lat=25.21)
BBOX_EXT = dict(min_lng=121.35, max_lng=121.77, min_lat=24.87, max_lat=25.30)
SPOTS = [  # 階段 A 時 index.html 的 5 個跑點（現為 SPOTS 的 id 1–5；只用於計算最近測站距離）
    ('大安森林公園', 25.02970, 121.53629), ('大佳河濱公園', 25.07471, 121.54111),
    ('國立中正紀念堂', 25.03556, 121.52024), ('花博公園新生園區', 25.06999, 121.53124),
    ('青年公園', 25.02306, 121.50526),
]

KEY = os.environ.get('MOENV_API_KEY', '')
OUT = []  # 摘要（Markdown），最後同時印出並寫入 GITHUB_STEP_SUMMARY


def safe(text):
    """把金鑰（含 URL 編碼後的樣子）替換成 ***"""
    s = str(text)
    if KEY:
        s = s.replace(KEY, '***').replace(urllib.parse.quote(KEY, safe=''), '***')
    return s


def emit(line=''):
    OUT.append(safe(line))


def haversine(lat1, lng1, lat2, lng2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def in_box(lat, lng, b):
    return b['min_lat'] <= lat <= b['max_lat'] and b['min_lng'] <= lng <= b['max_lng']


def parse_time(s):
    """環境部時間字串（例如 2026/11/23 15:00:00 或 2026-11-23 15:00）視為台北時間"""
    s = str(s or '').strip()
    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TPE)
        except ValueError:
            pass
    return None


def load_outline():
    """從 index.html 讀出 TAIPEI_OUTLINE（[緯度, 經度]），用來估算市內各點到最近測站的距離分布"""
    try:
        html = open(os.path.join(os.path.dirname(__file__), '..', 'index.html'), encoding='utf-8').read()
        block = re.search(r'const TAIPEI_OUTLINE = \[(.*?)\];', html, re.S).group(1)
        return [(float(a), float(b)) for a, b in re.findall(r'\[([\d.]+),\s*([\d.]+)\]', block)]
    except Exception:  # noqa: BLE001 — 讀不到就略過這一段分析
        return None


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


def fetch():
    params = {'format': 'json', 'limit': '1000', 'offset': '0', 'api_key': KEY}
    url = f'{API_BASE}?{urllib.parse.urlencode(params)}'
    emit('## 1. API 請求')
    emit(f'- 網址：`{API_BASE}?format=json&limit=1000&offset=0&api_key=***`')
    req = urllib.request.Request(url, headers={'User-Agent': 'SafeAirRun-probe/1.0 (GitHub Actions)', 'Accept': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read()
            status, headers = res.status, dict(res.headers.items())
    except urllib.error.HTTPError as e:
        body, status, headers = e.read(), e.code, dict(e.headers.items())
    except Exception as e:  # noqa: BLE001
        emit(f'- ❌ 連線失敗：{type(e).__name__}: {e}')
        return None
    ms = int((time.time() - t0) * 1000)
    emit(f'- HTTP 狀態：{status}；耗時 {ms} ms；大小 {len(body):,} bytes')
    for h in ('Content-Type', 'Access-Control-Allow-Origin', 'Cache-Control', 'Last-Modified', 'ETag',
              'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'Retry-After'):
        v = next((val for k, val in headers.items() if k.lower() == h.lower()), None)
        if v is not None:
            emit(f'- 回應標頭 `{h}`：`{v}`')
    try:
        return json.loads(body.decode('utf-8-sig'))
    except Exception:  # noqa: BLE001
        emit(f'- ❌ 回應不是 JSON，前 200 字：`{body[:200].decode("utf-8", "replace")}`')
        return None


def summarize(data):
    emit()
    emit('## 2. 回應格式')
    if isinstance(data, dict):
        emit(f'- 最外層為物件，鍵：`{", ".join(data.keys())}`')
        for k in ('total', 'limit', 'offset', 'resource_id', 'include_total', 'resource_format'):
            if k in data:
                emit(f'  - `{k}` = `{data[k]}`')
        records = data.get('records') or data.get('Records') or []
        fields = data.get('fields') or []
        if fields:
            emit('- `fields`（欄位定義）：' + '、'.join(
                f"`{f.get('id')}`({(f.get('info') or {}).get('label', '')})" if isinstance(f, dict) else f'`{f}`' for f in fields))
    elif isinstance(data, list):
        emit('- 最外層為陣列')
        records = data
    else:
        emit('- ❌ 無法辨識的格式')
        return
    emit(f'- 記錄數：{len(records)}')
    if not records:
        return
    keys = list(records[0].keys())
    emit(f'- 記錄欄位名稱（{len(keys)} 個，依原始大小寫）：`{"`、`".join(keys)}`')
    emit('- 第一筆範例（公開資料）：')
    emit('```json')
    emit(json.dumps(records[0], ensure_ascii=False, indent=1))
    emit('```')

    def get(r, *names):
        low = {k.lower(): v for k, v in r.items()}
        for n in names:
            if n.lower() in low:
                return low[n.lower()]
        return None

    rows, bad_coord, bad_pm = [], 0, 0
    for r in records:
        lat, lng = num(get(r, 'latitude')), num(get(r, 'longitude'))
        pm = num(get(r, 'pm2.5'))
        if lat is None or lng is None:
            bad_coord += 1
            continue
        if pm is None:
            bad_pm += 1
        rows.append(dict(site=get(r, 'sitename'), sid=get(r, 'siteid'), county=get(r, 'county'), lat=lat, lng=lng, pm=pm,
                         pm_avg=num(get(r, 'pm2.5_avg')), aqi=get(r, 'aqi'), status=get(r, 'status'),
                         t=get(r, 'publishtime'), raw_pm=get(r, 'pm2.5')))
    emit(f'- 全台測站：{len(rows)}；座標缺漏 {bad_coord}；PM2.5 非數值（空白、ND 等）{bad_pm}')
    counties = {}
    for x in rows:
        counties[x['county']] = counties.get(x['county'], 0) + 1
    emit('- 各縣市測站數：' + '、'.join(f'{k} {v}' for k, v in sorted(counties.items(), key=lambda kv: -kv[1])))

    now = datetime.now(TPE)
    times = [parse_time(x['t']) for x in rows]
    good = [t for t in times if t]
    emit()
    emit('## 3. 資料時間與新鮮度')
    emit(f'- 執行時間（台北）：{now:%Y-%m-%d %H:%M}')
    if good:
        emit(f'- publishtime 範圍：{min(good):%Y-%m-%d %H:%M} ～ {max(good):%Y-%m-%d %H:%M}（原始格式例：`{rows[0]["t"]}`）')
        emit(f'- 最新資料距今：{int((now - max(good)).total_seconds() // 60)} 分鐘；最舊：{int((now - min(good)).total_seconds() // 60)} 分鐘')
    else:
        emit(f'- ❌ 無法解析 publishtime（原始值例：`{rows[0]["t"]}`）')

    emit()
    emit('## 4. 台北範圍框內（含鄰近新北）測站')
    ext = [x for x in rows if in_box(x['lat'], x['lng'], BBOX_EXT)]
    strict = [x for x in ext if in_box(x['lat'], x['lng'], BBOX)]
    emit(f'- 台北範圍框（經度 121.45–121.67、緯度 24.96–25.21）內：**{len(strict)} 站**')
    emit(f'- 向外約 10 km（經度 121.35–121.77、緯度 24.87–25.30）內：**{len(ext)} 站**')
    emit()
    emit('| 測站 | 編號 | 縣市 | 緯度 | 經度 | PM2.5 | PM2.5 移動平均 | AQI | 狀態 | 資料時間 | 台北範圍框內 |')
    emit('| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :---: |')
    for x in sorted(ext, key=lambda x: (not in_box(x['lat'], x['lng'], BBOX), str(x['county']), str(x['site']))):
        emit(f"| {x['site']} | {x['sid']} | {x['county']} | {x['lat']:.5f} | {x['lng']:.5f} | {x['raw_pm']} | "
             f"{'' if x['pm_avg'] is None else x['pm_avg']} | {x['aqi']} | {x['status']} | {x['t']} | "
             f"{'✓' if in_box(x['lat'], x['lng'], BBOX) else ''} |")

    usable = [x for x in ext if x['pm'] is not None and x['pm'] > 0]
    emit()
    emit('## 5. 距離分析（供 IDW 規則參考，只用向外 10 km 內 PM2.5 有效的測站）')
    emit(f'- 有效測站：{len(usable)}')
    if usable:
        emit()
        emit('| 跑點 | 最近測站 | 距離 | 3 km 內站數 | 5 km 內站數 |')
        emit('| :--- | :--- | ---: | ---: | ---: |')
        for name, la, ln in SPOTS:
            ds = sorted((haversine(la, ln, x['lat'], x['lng']), x['site']) for x in usable)
            emit(f'| {name} | {ds[0][1]} | {ds[0][0] / 1000:.2f} km | {sum(d <= 3000 for d, _ in ds)} | {sum(d <= 5000 for d, _ in ds)} |')
        poly = load_outline()
        if poly:
            pts = []
            lat = 24.955
            while lat <= 25.215:
                lng = 121.455
                while lng <= 121.67:
                    if point_in_poly(lat, lng, poly):
                        pts.append(min(haversine(lat, lng, x['lat'], x['lng']) for x in usable))
                    lng += 0.003
                lat += 0.0027
            emit(f'- 台北市界內約 300 m 格點 {len(pts)} 個，到最近有效測站的距離分布：')
            for r in (2000, 3000, 4000, 5000, 6000, 8000):
                emit(f'  - ≤ {r // 1000} km：{sum(d <= r for d in pts) / len(pts) * 100:.1f}%')
            emit(f'  - 最遠：{max(pts) / 1000:.2f} km')


def main():
    if '--file' in sys.argv:
        data = json.load(open(sys.argv[sys.argv.index('--file') + 1], encoding='utf-8-sig'))
        emit('## 1. API 請求')
        emit('- （本機測試：讀取檔案，未連網）')
    else:
        if not KEY:
            print('❌ 找不到環境變數 MOENV_API_KEY（請確認 GitHub Secrets 名稱與 workflow 設定）')
            sys.exit(1)
        data = fetch()
    if data is not None:
        summarize(data)
    emit()
    emit('> 本摘要只含公開資料與統計；未輸出金鑰、未儲存原始資料。')
    text = '\n'.join(OUT)
    print(text)
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('# 環境部 AQI 探測結果\n\n' + text + '\n')
    if data is None:
        sys.exit(1)


if __name__ == '__main__':
    main()
