#!/usr/bin/env python3
"""
Use Chrome CDP to create a TradingView alert with webhook programmatically.
"""
import json, time, os
import requests
import websocket

CDP_URL = "http://localhost:9222"
WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"
WEBHOOK_SECRET = open(os.path.expanduser('~/Desktop/Trading/.webhook_secret')).read().strip() if os.path.exists(os.path.expanduser('~/Desktop/Trading/.webhook_secret')) else "643946790e81c825a8c6878be88b166c258d068769910d4df2e9532c91fabc7d"

def get_tabs():
    return requests.get(f"{CDP_URL}/json").json()

def send_cdp(ws, method, params=None):
    msg_id = int(time.time() * 1000)
    cmd = {"id": msg_id, "method": method}
    if params: cmd["params"] = params
    ws.send(json.dumps(cmd))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id:
            return resp.get("result")

def get_cookies_from_chrome(ws, domain=".tradingview.com"):
    """Get cookies for a specific domain via CDP."""
    result = send_cdp(ws, "Network.getCookies", {"urls": [f"https://{domain.lstrip('.')}"]})
    return result.get("cookies", []) if result else []

def main():
    print("[1] Connecting to Chrome...")
    tabs = get_tabs()
    if not tabs:
        print("  No tabs found!")
        return
    
    # Find TradingView tab
    tv_tab = None
    for t in tabs:
        if 'tradingview.com' in t.get('url', ''):
            tv_tab = t
            break
    if not tv_tab:
        tv_tab = tabs[0]
    
    ws_url = tv_tab['webSocketDebuggerUrl']
    print(f"  Using tab: {tv_tab['title'][:50]}")
    
    ws = websocket.create_connection(ws_url, timeout=15)
    
    # Enable Network domain to access cookies
    send_cdp(ws, "Network.enable")
    
    # Get TradingView cookies
    cookies = get_cookies_from_chrome(ws, ".tradingview.com")
    print(f"\n[2] Got {len(cookies)} TradingView cookies")
    
    # Build cookie header
    cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    
    ws.close()
    
    # Also try accounts.google.com cookies for the auth
    print("\n[3] Checking TradingView session...")
    
    # Test if session works by calling TradingView API
    headers = {
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/148.0.0.0",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
        "Content-Type": "application/json"
    }
    
    # Try TradingView's alert API endpoint
    test_url = "https://www.tradingview.com/accounts/check/"

    print(f"[4] Testing session...")
    test_r = requests.get(test_url, headers=headers)
    print(f"  Check response: {test_r.status_code}")
    if test_r.status_code == 200:
        data = test_r.json()
        print(f"  Auth result: {json.dumps(data)[:200]}")
    
    # Try the TradingView alerts API
    print(f"\n[5] Fetching existing alerts...")
    
    # TV uses a different endpoint for alerts
    alerts_url = "https://www.tradingview.com/alerts/"
    alerts_r = requests.get(alerts_url, headers=headers)
    print(f"  Alerts page: {alerts_r.status_code}")
    
    # Try the REST API for alerts  
    # TradingView alert API endpoint discovered from network requests
    api_url = "https://www.tradingview.com/alert-service/alerts/list"
    list_r = requests.post(api_url, headers=headers, json={})
    print(f"  Alerts API: {list_r.status_code}")
    if list_r.status_code == 200:
        data = list_r.json()
        print(f"  Existing alerts: {json.dumps(data)[:300]}")
    
    # Try to CREATE an alert via the API
    print(f"\n[6] Creating BTCUSD alert with webhook...")
    
    create_url = "https://www.tradingview.com/alert-service/alerts/create"
    
    # Simple alert - price crosses 75000 on BTCUSD
    alert_payload = {
        "name": "Hermes AI - BTC Alert",
        "symbol": "BINANCE:BTCUSDT",
        "condition": {
            "fields": [
                "close",
                ">=",
                75000
            ],
            "time": 0
        },
        "actions": [
            {
                "type": "webhook",
                "url": WEBHOOK_URL,
                "body": json.dumps({
                    "symbol": "{{ticker}}",
                    "action": "buy",
                    "price": "{{close}}",
                    "assetClass": "crypto",
                    "secret": WEBHOOK_SECRET,
                    "message": "BTC crossed 75000"
                }),
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json"
                }
            }
        ],
        "options": {
            "expires": 0,
            "alertType": "price",
            "frequency": "once",
            "timeout": 0
        }
    }
    
    create_r = requests.post(create_url, headers=headers, json=alert_payload)
    print(f"  Create response: {create_r.status_code}")
    try:
        print(f"  Result: {json.dumps(create_r.json())[:300]}")
    except:
        print(f"  Raw: {create_r.text[:200]}")

if __name__ == "__main__":
    main()
