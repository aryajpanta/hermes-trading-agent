#!/usr/bin/env python3
"""Fill TradingView alert dialog and create the alert."""
import json, time, sys
import requests
from websocket import create_connection

WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"
WEBHOOK_SECRET = "643946790e81c825a8c6878be88b166c258d068769910d4df2e9532c91fabc7d"
WEBHOOK_BODY = json.dumps({
    "symbol": "{{ticker}}",
    "action": "buy",
    "price": "{{close}}",
    "assetClass": "crypto",
    "secret": WEBHOOK_SECRET,
    "message": "{{ticker}} alert triggered"
})

tabs = requests.get("http://localhost:9222/json").json()
tv_tab = None
for t in tabs:
    if "tradingview.com" in t.get("url", ""):
        tv_tab = t
        break
if not tv_tab:
    print("No TradingView tab!")
    sys.exit(1)

ws = create_connection(tv_tab["webSocketDebuggerUrl"], timeout=10)
msg_id = 1

def cmd(method, params=None):
    global msg_id
    mid = msg_id; msg_id += 1
    req = {"id": mid, "method": method}
    if params: req["params"] = params
    ws.send(json.dumps(req))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == mid:
            return resp.get("result")

def js(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return r.get("result", {}).get("value") if r else None

cmd("Runtime.enable")
cmd("DOM.enable")
time.sleep(1)

# Check what dialog is showing
print("[1] Checking alert dialog...")
dialog_info = js("""
(function() {
    var dialogs = [];
    document.querySelectorAll('*').forEach(function(el) {
        var cn = (el.className || '').toLowerCase();
        if ((cn.includes('dialog') || cn.includes('modal')) && el.offsetParent !== null && el.children.length > 0) {
            var text = (el.textContent || '').replace(/\\s+/g, ' ').trim().substring(0, 300);
            dialogs.push({class: cn.substring(0, 40), text: text.substring(0, 150)});
        }
    });
    return JSON.stringify(dialogs.slice(0, 3));
})()
""")
print(f"  Dialogs: {dialog_info}")

# Fill in the fields
print("\n[2] Filling webhook URL...")
result = js(f"""
(function() {{
    var filled = [];
    // Fill text inputs
    var inputs = document.querySelectorAll('input[type="text"], input:not([type])');
    inputs.forEach(function(el) {{
        if (el.offsetParent !== null) {{
            var orig = el.value;
            el.value = "{WEBHOOK_URL}";
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            filled.push('input: ' + orig.substring(0, 20) + ' -> ' + el.value.substring(0, 20));
        }}
    }});
    return JSON.stringify(filled);
}})()
""")
print(f"  {result}")

# Fill message/textarea
print("\n[3] Filling message JSON...")
result = js(f"""
(function() {{
    var filled = [];
    var areas = document.querySelectorAll('textarea');
    areas.forEach(function(el) {{
        if (el.offsetParent !== null) {{
            el.value = JSON.stringify({json.loads(WEBHOOK_BODY)});
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            filled.push('textarea filled');
        }}
    }});
    // Also try contenteditable divs
    document.querySelectorAll('[contenteditable="true"]').forEach(function(el) {{
        el.textContent = JSON.stringify({json.loads(WEBHOOK_BODY)});
        filled.push('contenteditable filled');
    }});
    return JSON.stringify(filled);
}})()
""")
print(f"  {result}")

# Check the webhook checkbox
print("\n[4] Enabling webhook checkbox...")
result = js("""
(function() {
    var labels = document.querySelectorAll('label');
    var found = false;
    labels.forEach(function(l) {
        var txt = (l.textContent || '').toLowerCase();
        if (txt.includes('webhook') && !found) {
            var cb = l.querySelector('input[type="checkbox"], [role="switch"]');
            if (cb) {
                if (!cb.checked) {
                    cb.click();
                    cb.checked = true;
                }
                found = true;
            } else {
                // Maybe it's a switch/button
                var sw = l.querySelector('[role="switch"], [class*="switch"]');
                if (sw) { sw.click(); found = true; }
                else { l.click(); found = true; }
            }
        }
    });
    return found ? 'webhook_enabled' : 'no_webhook_label';
})()
""")
print(f"  {result}")

time.sleep(1)

# Find and click Create button
print("\n[5] Clicking Create...")
result = js("""
(function() {
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').toLowerCase().trim();
        if (txt === 'create' || txt.includes('create alert') || txt === 'ok' || txt.includes('save')) {
            if (btns[i].offsetParent !== null) {
                btns[i].click();
                return 'clicked_' + txt;
            }
        }
    }
    // Try searching more broadly
    var all = document.querySelectorAll('[class*="dialog"] button, button');
    for (var i = 0; i < all.length; i++) {
        if (all[i].offsetParent !== null) {
            var t = (all[i].textContent || '').toLowerCase().trim();
            if (t === 'create' || t === 'ok' || t.includes('create') || t.includes('save')) {
                all[i].click();
                return 'clicked_alt_' + t;
            }
        }
    }
    return 'no_create_button_found';
})()
""")
print(f"  {result}")

time.sleep(2)

# Final status
print("\n[6] Final status...")
status = js("""
(function() {
    var dialogs = document.querySelectorAll('[class*="dialog"]');
    var openCount = 0;
    dialogs.forEach(function(d) { if (d.offsetParent !== null) openCount++; });
    var bodyText = document.body.innerText.substring(0, 200).replace(/\\s+/g, ' ').trim();
    return JSON.stringify({openDialogs: openCount, text: bodyText});
})()
""")
print(f"  {status}")

ws.close()
print("\nDone! Check your Chrome browser to see the result.")
