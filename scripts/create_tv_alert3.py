#!/usr/bin/env python3
"""
Get TV cookies and create alerts via their API.
"""
import json, sys, os, time
import requests
import websocket

CDP_URL = "http://localhost:9222"
WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"

# Get the secret from the file or use the known one
secret_path = os.path.expanduser("~/Desktop/Trading/.webhook_secret")
if os.path.exists(secret_path):
    with open(secret_path) as f:
        WEBHOOK_SECRET = f.read().strip()
else:
    WEBHOOK_SECRET = "..."
    print(f"Using hardcoded secret")

def get_session():
    """Get tradingview session cookies via CDP."""
    tabs = requests.get(f"{CDP_URL}/json").json()
    tv_tab = None
    for t in tabs:
        if 'tradingview.com' in t.get('url', ''):
            tv_tab = t
            break
    if not tv_tab:
        print("No tradingview tab!")
        return None
    
    ws = websocket.create_connection(tv_tab['webSocketDebuggerUrl'], timeout=10)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.recv()
    
    ws.send(json.dumps({
        "id": 2, "method": "Network.getCookies",
        "params": {"urls": ["https://www.tradingview.com"]}
    }))
    
    for _ in range(10):
        resp = json.loads(ws.recv())
        if resp.get('id') == 2:
            cookies = resp['result']['cookies']
            ws.close()
            return cookies
    ws.close()
    return None

def get_headers(cookies):
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    return {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/148.0.0.0 Safari/537.36",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/chart/",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

def main():
    print("[1] Getting session cookies...")
    cookies = get_session()
    if not cookies:
        print("  Failed!")
        return
    
    print(f"  sessionid: {[c['value'][:20] for c in cookies if c['name']=='sessionid'][0]}")
    headers = get_headers(cookies)
    
    print("\n[2] Probing API endpoints...")
    alerts_url = "https://www.tradingview.com/alert-service/alerts/"
    
    # List attempts
    for suffix in ["list", "get", ""]:
        url = alerts_url + suffix
        r = requests.post(url, headers=headers, json={}, timeout=10)
        print(f"  POST {suffix or '.'} -> {r.status_code}")
        try:
            data = r.json()
            print(f"    {json.dumps(data)[:150]}")
        except:
            pass
    
    print("\n[3] Creating alert on BTCUSD...")
    
    webhook_body = json.dumps({
        "symbol": "{{ticker}}",
        "action": "buy",
        "price": "{{close}}",
        "assetClass": "crypto",
        "secret": WEBHOOK_SECRET,
        "message": "BTC crossed 75000"
    })
    
    payload = {
        "name": "Hermes AI - BTC 75K Breakout",
        "symbol": "BINANCE:BTCUSDT",
        "condition": json.dumps({
            "fields": ["close", ">=", 75000],
            "time": 0
        }),
        "actions": json.dumps([{
            "text": webhook_body,
            "type": "webhook",
            "url": WEBHOOK_URL,
            "method": "POST",
            "headers": {"Content-Type": "application/json"}
        }]),
        "options": json.dumps({
            "expires": "2027-12-31T00:00:00.000Z",
            "alertType": "price",
            "frequency": "once",
            "timeout": 0
        })
    }
    
    r = requests.post(alerts_url + "create", headers=headers, json=payload, timeout=10)
    print(f"  Create response: {r.status_code}")
    try:
        resp = r.json()
        print(f"  {json.dumps(resp)[:300]}")
        if r.status_code == 200:
            print(f"\n  ✅ ALERT CREATED SUCCESSFULLY!")
    except:
        print(f"  Raw: {r.text[:200]}")
    
    # Also try with the raw data format (unwrapped)
    print("\n[4] Trying alternative payload format...")
    payload2 = {
        "name": "Hermes AI - BTC 75K",
        "symbol": "BINANCE:BTCUSDT",
        "condition": [["close", ">=", 75000]],
        "actions": [{"text": webhook_body, "type": "webhook", "url": WEBHOOK_URL, "method": "POST"}],
        "options": {"alertType": "price", "frequency": "once"}
    }
    
    r2 = requests.post(alerts_url + "create", headers=headers, json=payload2, timeout=10)
    print(f"  Create response: {r2.status_code}")
    try:
        resp2 = r2.json()
        print(f"  {json.dumps(resp2)[:300]}")
        if r2.status_code == 200:
            print(f"\n  ✅ ALERT CREATED SUCCESSFULLY!")
    except:
        print(f"  Raw: {r2.text[:200]}")

if __name__ == "__main__":
    main()
