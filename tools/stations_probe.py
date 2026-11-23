#!/usr/bin/env python3
"""
階段 A+：測站加密評估的探測腳本（只輸出摘要；不需要金鑰；不寫入任何資料檔）。

1. 國網中心資料集平台 moenviot：用 CKAN API 列出資源與實際 API 端點。
2. 民生公共物聯網 STA 主機：SSL 憑證效期、CORS 標頭；若憑證有效且可連線，統計台北範圍內的 PM2.5 感測器
   （數量、PM2.5 數值分布、0 值與異常值比例、資料新鮮度）。
憑證過期時只讀取憑證效期做診斷，不會在未驗證的連線上抓資料。
"""
import json
import math
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

UA = 'SafeAirRun-stations-probe/1.0 (GitHub Actions; manual)'
TPE = timezone(timedelta(hours=8))
BBOX = dict(min_lng=121.45, max_lng=121.67, min_lat=24.96, max_lat=25.21)
BBOX_EXT = dict(min_lng=121.35, max_lng=121.77, min_lat=24.87, max_lat=25.30)
OUT = []


def emit(s=''):
    OUT.append(str(s))
    print(s, flush=True)


def get(url, headers=None, timeout=40):
    h = {'User-Agent': UA, 'Accept': 'application/json'}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def hdr(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), None)


def cert_info(host):
    """讀取憑證效期（只做診斷；不傳送任何請求）"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=host) as ss:
            pem = ssl.DER_cert_to_PEM_cert(ss.getpeercert(True))
        out = subprocess.run(['openssl', 'x509', '-noout', '-subject', '-issuer', '-dates', '-ext', 'subjectAltName'],
                             input=pem, capture_output=True, text=True).stdout
        return out.strip()
    except Exception as e:  # noqa: BLE001
        return f'無法取得憑證：{type(e).__name__}: {e}'


def verified_get(url, headers=None):
    """通過憑證驗證才回傳；失敗回傳 (None, 原因)"""
    try:
        s, h, b = get(url, headers)
        return s, h, b
    except Exception as e:  # noqa: BLE001
        reason = getattr(e, 'reason', e)
        return None, None, f'{type(e).__name__}: {reason}'


def in_box(lat, lng, b):
    return b['min_lat'] <= lat <= b['max_lat'] and b['min_lng'] <= lng <= b['max_lng']


# ---------------------------------------------------------------- 1. moenviot 資料集
def probe_dataset():
    emit('## 1. 國網中心資料集平台 moenviot')
    seen = []
    for base in ('https://scidm.nchc.org.tw', 'https://ark.nchc.org.tw'):
        url = f'{base}/api/3/action/package_show?id=moenviot'
        s, h, b = verified_get(url)
        emit(f'- `{url}` → {s if s else "失敗"}' + ('' if s else f'：{b}'))
        if s != 200:
            continue
        try:
            r = json.loads(b.decode('utf-8'))['result']
        except Exception as e:  # noqa: BLE001
            emit(f'  - 回應不是預期的 CKAN JSON：{e}')
            continue
        emit(f'- 標題：{r.get("title")}；最後更新：{r.get("metadata_modified")}；授權：{r.get("license_title")}')
        emit(f'- 說明：{(r.get("notes") or "").strip()[:500]}')
        for x in r.get('resources', []):
            emit(f'  - **{x.get("name")}**｜格式 {x.get("format")}｜更新 {x.get("last_modified") or x.get("created")}')
            emit(f'    - 網址：`{x.get("url")}`')
            if x.get('description'):
                emit(f'    - 說明：{x["description"].strip()[:300]}')
            seen.append(x.get('url') or '')
        break
    return seen


# ---------------------------------------------------------------- 2. STA
def candidates(resource_urls):
    hosts = ['https://sta.colife.org.tw', 'https://sta.ci.taiwan.gov.tw']
    paths = ['/STA_AirQuality_EPAIoT/v1.0', '/STA_AirQuality_v2/v1.0']
    c = [h + p for h in hosts for p in paths]
    for u in resource_urls:  # 資料集頁面列出的端點優先
        m = re.match(r'(https?://[^?#]*?/v\d+(?:\.\d+)?)(?:/|$)', u or '')
        if m and m.group(1) not in c:
            c.insert(0, m.group(1))
    return c


def probe_sta(resource_urls):
    emit()
    emit('## 2. 民生公共物聯網 STA（微型感測器）')
    hosts = []
    for base in candidates(resource_urls):
        host = urllib.parse.urlparse(base).hostname
        if host not in hosts:
            hosts.append(host)
    for host in hosts:
        emit(f'### 憑證：{host}')
        emit('```')
        emit(cert_info(host))
        emit('```')
    good = None
    for base in candidates(resource_urls):
        emit(f'### 端點：`{base}`')
        s, h, b = verified_get(base, {'Origin': 'https://dengshikai0718-a11y.github.io'})
        if s is None:
            emit(f'- ❌ 連線失敗（含憑證驗證）：{b}')
            continue
        emit(f'- HTTP {s}；`Access-Control-Allow-Origin`：`{hdr(h, "Access-Control-Allow-Origin")}`；Content-Type：`{hdr(h, "Content-Type")}`')
        emit(f'- 回應開頭：`{b[:300].decode("utf-8", "replace")}`')
        if s == 200 and good is None:
            good = base
    if not good:
        emit()
        emit('> 沒有可通過憑證驗證的 STA 端點，略過資料統計。')
        return
    stats(good)


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None


def loc_of(thing):
    for lo in (thing or {}).get('Locations', []) or []:
        loc = lo.get('location') or {}
        co = loc.get('coordinates') or (loc.get('geometry') or {}).get('coordinates')
        if isinstance(co, list) and len(co) >= 2 and all(isinstance(x, (int, float)) for x in co[:2]):
            return co[1], co[0]
    return None


def stats(base):
    emit()
    emit(f'### 台北範圍內的 PM2.5 感測器統計（`{base}`）')
    q = urllib.parse.urlencode({'$top': '3', '$expand': 'Thing/Locations,ObservedProperty'}, quote_via=urllib.parse.quote)
    s, h, b = verified_get(f'{base}/Datastreams?{q}')
    emit(f'- 取樣 Datastreams → HTTP {s}')
    if s != 200:
        emit(f'  - `{str(b)[:300]}`')
        return
    emit('```json')
    emit(b.decode('utf-8', 'replace')[:1800])
    emit('```')
    rows, url, pages = [], None, 0
    q = urllib.parse.urlencode({'$top': '1000', '$filter': "substringof('PM2.5',name)",
                                '$expand': 'Thing/Locations,Observations($top=1;$orderby=phenomenonTime desc)'}, quote_via=urllib.parse.quote, safe="$(),;=' ")
    url = f'{base}/Datastreams?{q}'
    while url and pages < 25:
        s, h, b = verified_get(url)
        if s != 200:
            emit(f'- 第 {pages + 1} 頁失敗 HTTP {s}：`{str(b)[:300]}`')
            break
        d = json.loads(b.decode('utf-8'))
        rows += d.get('value', [])
        url = d.get('@iot.nextLink')
        pages += 1
    emit(f'- 取得 PM2.5 Datastreams：{len(rows)} 筆（{pages} 頁{"，已達頁數上限" if url else ""}）')
    now = datetime.now(timezone.utc)
    ext, strict, vals = [], [], []
    for r in rows:
        ll = loc_of(r.get('Thing'))
        if not ll:
            continue
        lat, lng = ll
        obs = (r.get('Observations') or [{}])[0] if r.get('Observations') else {}
        res = obs.get('result')
        t = parse_time(obs.get('phenomenonTime') or obs.get('resultTime'))
        rec = dict(name=(r.get('Thing') or {}).get('name') or r.get('name'), lat=lat, lng=lng, res=res, t=t)
        if in_box(lat, lng, BBOX_EXT):
            ext.append(rec)
        if in_box(lat, lng, BBOX):
            strict.append(rec)
    emit(f'- 台北範圍框內：{len(strict)} 個；向外約 10 km：{len(ext)} 個')

    def summarize(label, lst):
        nums = [x for x in lst if isinstance(x['res'], (int, float))]
        zero = sum(1 for x in nums if x['res'] <= 0)
        big = sum(1 for x in nums if x['res'] > 500)
        ages = sorted(int((now - x['t']).total_seconds() // 60) for x in lst if x['t'])
        emit(f'- {label}：共 {len(lst)}；有數值 {len(nums)}；≤ 0：{zero}；> 500：{big}')
        if ages:
            emit(f'  - 資料距今（分鐘）：最新 {ages[0]}、中位數 {ages[len(ages) // 2]}、最舊 {ages[-1]}；≤ 60 分鐘 {sum(a <= 60 for a in ages)} 個、≤ 180 分鐘 {sum(a <= 180 for a in ages)} 個')
        good = [x['res'] for x in nums if 0 < x['res'] <= 500]
        if good:
            good.sort()
            emit(f'  - 有效值（0–500）：{len(good)} 個；最小 {good[0]}、中位數 {good[len(good) // 2]}、最大 {good[-1]}；P90 {good[int(len(good) * .9)]}')
    summarize('台北範圍框內', strict)
    summarize('向外約 10 km', ext)
    emit('| 名稱 | 緯度 | 經度 | PM2.5 | 資料時間（台北） |')
    emit('| :--- | ---: | ---: | ---: | :--- |')
    for x in sorted(strict, key=lambda x: str(x['name']))[:80]:
        emit(f'| {x["name"]} | {x["lat"]:.5f} | {x["lng"]:.5f} | {x["res"]} | {x["t"].astimezone(TPE):%m/%d %H:%M} |' if x['t'] else f'| {x["name"]} | {x["lat"]:.5f} | {x["lng"]:.5f} | {x["res"]} | — |')


def main():
    urls = probe_dataset()
    probe_sta(urls)
    emit()
    emit('> 本摘要只含公開資訊與統計；未使用金鑰、未儲存原始資料。')
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write('# 測站加密探測結果（階段 A+）\n\n' + '\n'.join(OUT) + '\n')


if __name__ == '__main__':
    main()
