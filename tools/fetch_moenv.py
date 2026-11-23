#!/usr/bin/env python3
"""
環境部「空氣品質指標（AQI）」→ data/pm25.json（由 GitHub Actions 每小時執行，產物只放進 Pages 部署，不 commit）。

- 金鑰只從環境變數 MOENV_API_KEY 讀取；輸出一律把金鑰換成 ***。
- API 失敗（含「回應不是 JSON」：金鑰無效時環境部回 HTTP 200 加純文字）會重試，仍失敗時：
    1. 下載目前線上的 data/pm25.json 沿用（--fallback-url），避免部署把資料蓋掉；
    2. 也拿不到時：若 ALLOW_MISSING=true（push 觸發的部署）就不輸出資料檔、照常部署網站（網頁會降級為 Mock）；
       否則以非 0 結束，這次不部署（線上維持上一版）。
- 只保留網頁需要的欄位；pm2.5 / pm2.5_avg 都保留原值（非數值存 null），用哪一個由網頁決定。

本機使用：MOENV_API_KEY=你的金鑰 python3 tools/fetch_moenv.py --out data/pm25.json
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_BASE = 'https://data.moenv.gov.tw/api/v2/aqx_p_432'
UA = 'SafeAirRun/1.0 (GitHub Actions; hourly)'
KEY = os.environ.get('MOENV_API_KEY', '')
TAIPEI_BBOX = (121.45, 121.67, 24.96, 25.21)  # 與 index.html CONFIG.BBOX 相同（只用於摘要）


def safe(s):
    s = str(s)
    if KEY:
        s = s.replace(KEY, '***').replace(urllib.parse.quote(KEY, safe=''), '***')
    return s


def log(msg):
    print(safe(msg), flush=True)


def num(v):
    try:
        x = float(str(v).strip())
        return x if x == x and abs(x) != float('inf') else None
    except (TypeError, ValueError):
        return None


def to_iso(publish):
    """'2026/11/23 22:00:00'（台北時間）→ '2026-11-23T22:00:00+08:00'；無法解析回傳 None"""
    s = str(publish or '').strip().replace('-', '/')
    for fmt in ('%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%dT%H:%M:%S+08:00')
        except ValueError:
            pass
    return None


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, res.read()


def fetch_api(retries=3, wait=30):
    params = urllib.parse.urlencode({'format': 'json', 'limit': '1000', 'offset': '0', 'api_key': KEY})
    for i in range(1, retries + 1):
        try:
            status, body = http_get(f'{API_BASE}?{params}')
            data = json.loads(body.decode('utf-8-sig'))
            records = data if isinstance(data, list) else (data.get('records') if isinstance(data, dict) else None)
            if not isinstance(records, list) or not records:
                raise ValueError('回應中沒有測站資料')
            return records
        except Exception as e:  # noqa: BLE001
            log(f'第 {i}/{retries} 次呼叫失敗：{type(e).__name__}: {e}')
            if i < retries:
                time.sleep(wait)
    return None


def build(records):
    stations = []
    for r in records:
        low = {str(k).lower(): v for k, v in r.items()}
        lat, lng = num(low.get('latitude')), num(low.get('longitude'))
        t = to_iso(low.get('publishtime'))
        if lat is None or lng is None or t is None:
            continue
        stations.append({
            'id': str(low.get('siteid') or ''), 'name': str(low.get('sitename') or ''), 'county': str(low.get('county') or ''),
            'lat': round(lat, 6), 'lng': round(lng, 6),
            'pm25': num(low.get('pm2.5')), 'pm25Avg': num(low.get('pm2.5_avg')), 'time': t,
        })
    if not stations:
        raise ValueError('沒有可用的測站（座標或時間皆缺漏）')
    return {
        'source': '環境部環境資料開放平臺｜空氣品質指標(AQI) AQX_P_432',
        'license': '政府資料開放授權條款－第1版（https://data.gov.tw/license）',
        'fetchedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'publishTime': max(s['time'] for s in stations),
        'stations': stations,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data/pm25.json')
    ap.add_argument('--fallback-url', default='')
    args = ap.parse_args()
    allow_missing = os.environ.get('ALLOW_MISSING', '').lower() == 'true'
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)

    out = None
    if not KEY:
        log('::warning::找不到 MOENV_API_KEY')
    else:
        records = fetch_api()
        if records:
            try:
                out = build(records)
            except Exception as e:  # noqa: BLE001
                log(f'資料轉換失敗：{e}')
    if out:
        tp = [s for s in out['stations'] if TAIPEI_BBOX[0] <= s['lng'] <= TAIPEI_BBOX[1] and TAIPEI_BBOX[2] <= s['lat'] <= TAIPEI_BBOX[3]]
        avg_only = [s['name'] for s in out['stations'] if s['pm25'] is None and s['pm25Avg'] is not None]
        log(f'✅ 環境部資料：全台 {len(out["stations"])} 站、台北範圍框 {len(tp)} 站；資料時間 {out["publishTime"]}')
        if avg_only:
            log(f'pm2.5 缺值、改用移動平均的測站：{"、".join(avg_only)}')
    elif args.fallback_url:
        log(f'::warning::環境部 API 失敗，改沿用線上資料：{args.fallback_url}')
        try:
            status, body = http_get(f'{args.fallback_url}?t={int(time.time())}', timeout=20)
            prev = json.loads(body.decode('utf-8'))
            if isinstance(prev, dict) and prev.get('stations'):
                out = prev
                log(f'沿用線上資料（資料時間 {prev.get("publishTime")}）')
        except Exception as e:  # noqa: BLE001
            log(f'線上資料也無法取得：{type(e).__name__}: {e}')
    if out is None:
        if allow_missing:
            log('::warning::沒有 PM2.5 資料可部署；網站照常部署，網頁將降級為 Mock')
            return
        log('::error::沒有 PM2.5 資料可部署，本次不部署（線上維持上一版）')
        sys.exit(1)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    log(f'已寫入 {args.out}（{os.path.getsize(args.out):,} bytes）')


if __name__ == '__main__':
    main()
