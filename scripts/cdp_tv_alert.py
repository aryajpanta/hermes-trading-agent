#!/usr/bin/env python3
import json, time, os, sys
import requests
from websocket import create_connection

CDP_URL = "http://localhost:9222"
WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"
WEBHOOK_SECRET = "643946...bc7d"

class CDP:
    def __init__(self, ws_url):
        self.ws = create_connection(ws_url, timeout=30)
        self.msg_id = 1

    def cmd(self, method, params=None):
        mid = self.msg_id
        self.msg_id += 1
        cmd = {"id": mid, "method": method}
        if params:
            cmd["params"] = params
        self.ws.send(json.dumps(cmd))
        while True:
            resp = json.loads(self.ws.recv())
            if resp.get("id") == mid:
                return resp.get("result")

    def close(self):
        self.ws.close()

def main():
    print("=== TradingView Alert Setup ===")
    webhook_body = json.dumps({
        "symbol": "{{ticker}}",
        "action": "buy",
        "price": "{{close}}",
        "assetClass": "crypto",
        "secret": WEBHOOK_SECRET,
        "message": "{{ticker}} alert triggered"
    })

    # Try to open the alert dialog via CDP
    print("[1] Connecting to Chrome...")
    tabs = requests.get(f"{CDP_URL}/json").json()
    tv_tab = None
    for t in tabs:
        if "tradingview.com" in t.get("url", ""):
            tv_tab = t
            break
    if not tv_tab:
        tv_tab = tabs[0] if tabs else None
    
    if not tv_tab:
        print("  No Chrome tabs found!")
        print_instructions(webhook_body)
        return

    print(f"  Connected to: {tv_tab['title'][:50]}")
    cdp = CDP(tv_tab["webSocketDebuggerUrl"])
    cdp.cmd("Page.enable")
    cdp.cmd("Runtime.enable")

    # Navigate to chart
    print("[2] Loading BTCUSD chart...")
    cdp.cmd("Page.navigate", {"url": "https://www.tradingview.com/chart/?symbol=BTCUSD"})
    time.sleep(4)

    # Try to create alert via TradingView's internal API
    print("[3] Opening alert dialog...")
    result = cdp.cmd("Runtime.evaluate", {
        "expression": """
        (function() {
            var w = window;
            // Try to find the widget
            for (var k in w) {
                try {
                    if (w[k] && typeof w[k] === 'object' && w[k].chart && typeof w[k].chart === 'function') {
                        w[k].chart().executeActionById('createAlert');
                        return 'created';
                    }
                } catch(e) {}
            }
            return 'not_found';
        })()
        """,
        "returnByValue": True
    })

    val = result.get("result", {}).get("value", "unknown") if result else "error"
    print(f"  Widget result: {val}")

    if val == "created":
        time.sleep(2)
        print("[4] Alert dialog opened! Setting webhook URL...")
        cdp.eval_and_get = lambda js: cdp.cmd("Runtime.evaluate", {
            "expression": js, "returnByValue": True
        }).get("result", {}).get("value")

        # Type the webhook URL
        cdp.cmd("Runtime.evaluate", {
            "expression": f"""
            (function() {{
                var inputs = document.querySelectorAll('input[type="text"], input[type="url"], input:not([type])');
                for (var i = 0; i < inputs.length; i++) {{
                    var p = (inputs[i].placeholder || '').toLowerCase();
                    if (p.includes('webhook') || p.includes('url')) {{
                        inputs[i].value = '{WEBHOOK_URL}';
                        inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                        return 'typed_webhook_url';
                    }}
                }}
                return 'no_webhook_input_found';
            }})()
            """,
            "returnByValue": True
        })
        time.sleep(1)

        # Try to find the message textarea
        cdp.cmd("Runtime.evaluate", {
            "expression": f"""
            (function() {{
                var areas = document.querySelectorAll('textarea');
                for (var i = 0; i < areas.length; i++) {{
                    areas[i].value = {json.dumps(webhook_body)};
                    areas[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                    return 'typed_message';
                }}
                return 'no_textarea';
            }})()
            """,
            "returnByValue": True
        })

        time.sleep(1)
        print("  Webhook URL and message filled in!")
        print("  Check your Chrome browser - the alert dialog should be open with settings pre-filled.")
        print("  Click 'Create' to save the alert.")
    else:
        print()
        print_instructions(webhook_body)

    cdp.close()


def print_instructions(webhook_body):
    print()
    print("=" * 60)
    print("  CREATE ALERT MANUALLY IN YOUR CHROME BROWSER")
    print("=" * 60)
    print()
    print("1. In the TradingView tab already open in Chrome...")
    print("2. Click the alarm clock icon (Alerts) in the right toolbar")
    print("3. Click 'Create Alert'")
    print("4. Set condition: Price >= 75000 (or whatever you want)")
    print("5. Check 'Webhook URL' and paste:")
    print(f"   {WEBHOOK_URL}")
    print()
    print("6. In the Message field, paste this JSON:")
    print(f"   {webhook_body}")
    print()
    print("7. Click 'Create'")
    print()
    print("Done! The agent will receive alerts 24/7.")


if __name__ == "__main__":
    main()
