#!/usr/bin/env python3
"""
Use CDP HTTP endpoints (no websocket) to get cookies from Chrome,
then create a TradingView alert via their API directly in the browser.
"""
import json, sys, os, time
import requests

CDP_URL = "http://localhost:9222"
WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"
WEBHOOK_SECRET = "643946790e81c825a8c6878be88b166c258d068769910d4df2e9532c91fabc7d"

def get_tabs():
    r = requests.get(f"{CDP_URL}/json")
    return r.json()

def get_cookies_via_fetch():
    """
    Use CDP's devtools endpoint to execute JS and return session cookies.
    We navigate to a special devtools URL that acts as a proxy to the page.
    """
    tabs = get_tabs()
    for t in tabs:
        url = t.get('url', '')
        if 'tradingview.com' in url:
            tab_id = t['id']
            
            # CDP has a special endpoint to evaluate JS
            # There isn't an HTTP endpoint for this, but we can use the websocket
            # or we can use Puppeteer's alternative: the /json/activate/{tabId} endpoint
            
            # Let me try to get cookies via a different approach
            # Chrome stores cookies in a way we can fetch via the devtools API
            
            # Actually, let me try websocket one more time with a simpler approach
            print(f"  Found TV tab: {t['title'][:50]}")
            return tab_id

def main_simple():
    """Simplest approach: Tell the user the steps directly."""
    
    # First, let's try to open the alert dialog on the TradingView page
    # by using an HTTP GET to trigger navigation to the alerts page
    print("[1] Opening Chrome with TradingView chart...")
    
    # Navigate the TradingView tab to the BTCUSD chart
    tabs = get_tabs()
    tv_tab = None
    for t in tabs:
        if 'tradingview.com' in t.get('url', ''):
            tv_tab = t
            break
    
    if not tv_tab:
        print("  No TradingView tab found!")
        return
    
    ws_url = tv_tab['webSocketDebuggerUrl']
    print(f"  Tab: {tv_tab['title'][:50]}")
    
    # Use websocket with a simpler approach - just get cookies
    import websocket
    ws = websocket.create_connection(ws_url, timeout=10)
    
    # Send Network.enable
    cmd_id = 1
    ws.send(json.dumps({"id": cmd_id, "method": "Network.enable"}))
    
    # Wait for response
    resp = None
    for _ in range(3):
        try:
            resp = json.loads(ws.recv())
            print(f"  Got response: {resp.get('method', resp.get('id', ''))}")
            if resp.get('id') == cmd_id:
                break
        except:
            break
    
    # Get cookies for tradingview.com
    cookie_cmd_id = 2
    ws.send(json.dumps({
        "id": cookie_cmd_id,
        "method": "Network.getCookies",
        "params": {"urls": ["https://www.tradingview.com"]}
    }))
    
    for _ in range(10):
        try:
            resp = json.loads(ws.recv())
            if resp.get('id') == cookie_cmd_id:
                cookies = resp.get('result', {}).get('cookies', [])
                print(f"  Got {len(cookies)} cookies!")
                
                # Find the session cookie
                for c in cookies:
                    if c['name'] in ('sessionid', 'sessionid_sign'):
                        print(f"  {c['name']}: {c['value'][:20]}...")
                
                # Build cookie string
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                
                # Now use these cookies to call TradingView API
                print("\n[2] Testing TradingView session via API...")
                headers = {
                    "Cookie": cookie_str,
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/148.0.0.0",
                    "Origin": "https://www.tradingview.com",
                    "Referer": "https://www.tradingview.com/",
                    "Content-Type": "application/json"
                }
                
                # Check session
                r = requests.get("https://www.tradingview.com/accounts/check/", headers=headers)
                print(f"  Session check: {r.status_code} - {r.text[:100]}")
                
                if r.status_code == 200 and r.json().get('user'):
                    user = r.json()['user']
                    print(f"  Logged in as: {user.get('username', user.get('email', 'unknown'))}")
                    
                    # Now create an alert!
                    print("\n[3] Creating BTCUSD alert...")
                    create_url = "https://www.tradingview.com/alert-service/alerts/create"
                    
                    alert_payload = {
                        "name": "Hermes AI - BTC Breakout",
                        "symbol": "BINANCE:BTCUSDT",
                        "condition": json.dumps([
                            ["close", ">=", 75000]
                        ]),
                        "actions": json.dumps([
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
                                "headers": {"Content-Type": "application/json"}
                            }
                        ]),
                        "options": json.dumps({
                            "expires": "2027-12-31T23:59:00Z",
                            "alertType": "price",
                            "frequency": "once"
                        })
                    }
                    
                    r2 = requests.post(create_url, headers=headers, json=alert_payload)
                    print(f"  Alert creation: {r2.status_code}")
                    try:
                        print(f"  Response: {json.dumps(r2.json())[:300]}")
                    except:
                        print(f"  Raw: {r2.text[:200]}")
                else:
                    print(f"  Session check failed or not logged in")
                break
        except:
            break
    
    ws.close()

if __name__ == "__main__":
    main_simple()
