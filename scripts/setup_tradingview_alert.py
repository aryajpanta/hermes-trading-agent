#!/usr/bin/env python3
"""
Connect to Chrome via CDP and create a TradingView alert with webhook.
"""
import json
import time
import requests
import websocket

CDP_URL = "http://localhost:9222"
WEBHOOK_URL = "https://hermes-trading-agent-production-890e.up.railway.app/webhook/tradingview"
WEBHOOK_SECRET = "643946790e81c825a8c6878be88b166c258d068769910d4df2e9532c91fabc7d"

def get_tabs():
    r = requests.get(f"{CDP_URL}/json")
    return r.json()

def find_or_open_tradingview_tab(tabs):
    """Find existing TradingView tab or return the first available tab."""
    for t in tabs:
        url = t.get('url', '')
        if 'tradingview.com' in url and 'chart' in url:
            print(f"  Found TradingView chart tab: {t['title'][:50]}")
            return t
    # Try any TradingView tab
    for t in tabs:
        url = t.get('url', '')
        if 'tradingview.com' in url:
            print(f"  Found TradingView tab: {t['title'][:50]}")
            return t
    # Fallback: use first tab
    if tabs:
        print(f"  Using first available tab: {tabs[0]['title'][:50]}")
        return tabs[0]
    return None

def send_cdp(ws, method, params=None):
    """Send a CDP command and return the result."""
    msg_id = int(time.time() * 1000)
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    ws.send(json.dumps(cmd))
    
    # Wait for response with matching id
    while True:
        response = json.loads(ws.recv())
        if response.get("id") == msg_id:
            return response.get("result")

def main():
    print("[*] Connecting to Chrome via CDP...")
    tabs = get_tabs()
    if not tabs:
        print("  No tabs found!")
        return
    
    tab = find_or_open_tradingview_tab(tabs)
    if not tab:
        print("  No tab available!")
        return
    
    ws_url = tab['webSocketDebuggerUrl']
    print(f"[*] Connecting to tab via WebSocket...")
    ws = websocket.create_connection(ws_url, timeout=30)
    
    # Enable necessary domains
    send_cdp(ws, "Page.enable")
    send_cdp(ws, "Runtime.enable")
    send_cdp(ws, "DOM.enable")
    
    # Check current URL
    result = send_cdp(ws, "Runtime.evaluate", {
        "expression": "window.location.href"
    })
    current_url = result.get("result", {}).get("value", "")
    print(f"[*] Current URL: {current_url}")
    
    # If not on a chart page, navigate to one
    if "chart" not in current_url:
        print("[*] Navigating to chart page (BTCUSD)...")
        send_cdp(ws, "Page.navigate", {
            "url": "https://www.tradingview.com/channel/chart/?symbol=BTCUSD"
        })
        time.sleep(3)
    
    # Try to navigate directly to a symbol chart
    print("[*] Opening BTCUSD chart...")
    send_cdp(ws, "Page.navigate", {
        "url": "https://www.tradingview.com/chart/?symbol=BTCUSD"
    })
    time.sleep(4)
    
    # Check if we're signed in
    result = send_cdp(ws, "Runtime.evaluate", {
        "expression": "document.querySelector('.tv-header__user-menu-button') ? 'signed in' : 'not signed in'"
    })
    auth_status = result.get("result", {}).get("value", "unknown")
    print(f"[*] Auth status: {auth_status}")
    
    if auth_status == "not signed in":
        print("[!] Not signed in! Checking page state...")
        # Try to see what's on the page
        result = send_cdp(ws, "Runtime.evaluate", {
            "expression": "document.title"
        })
        print(f"  Page title: {result.get('result', {}).get('value', '')}")
    
    # Wait for all network requests to settle
    time.sleep(3)
    
    # Try using TradingView's widget API to create an alert
    print("[*] Attempting to set up an alert via TradingView widget API...")
    
    # First, check if the chart widget is available
    result = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            if (typeof widget !== 'undefined') {
                return 'widget found';
            }
            if (typeof TradingView !== 'undefined') {
                return 'TradingView global found';
            }
            return 'no widget API found';
        })()
        """
    })
    widget_status = result.get("result", {}).get("value", "error")
    print(f"[*] Widget status: {widget_status}")
    
    # Try to access the chart through the TradingView API
    # TradingView exposes the chart via window.tvWidget or through the window
    result = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            let widget = null;
            // Try to find the widget in various places
            if (window.tvWidget) widget = window.tvWidget;
            else if (window.chartWidget) widget = window.chartWidget;
            else {
                // Search through all window keys for TradingView widgets
                for (let key in window) {
                    try {
                        if (window[key] && typeof window[key] === 'object' && window[key].chart) {
                            widget = window[key];
                            break;
                        }
                    } catch(e) {}
                }
            }
            if (widget) {
                try {
                    widget.chart().executeActionById('createAlert');
                    return 'alert dialog opened via widget API';
                } catch(e) {
                    return 'widget found but error: ' + e.message;
                }
            }
            // Try clicking the alert button
            const alertBtn = document.querySelector('[data-name="show-alerts-dialog"]') || 
                             document.querySelector('.alert-button') ||
                             document.querySelector('[class*="alert"]') ||
                             document.querySelector('[data-tooltip="Alerts"]');
            if (alertBtn) {
                alertBtn.click();
                return 'alert button clicked';
            }
            return 'could not find alert button or widget';
        })()
        """
    })
    result_value = result.get("result", {}).get("value", "error")
    print(f"[*] Alert creation attempt: {result_value}")
    
    # Let's also try to navigate through the UI more carefully
    print("\n[*] Attempting UI-based alert creation...")
    
    # First, look for the alerts panel or button
    result = send_cdp(ws, "Runtime.evaluate", {
        "expression": """
        (function() {
            // Look for alerts-related elements
            const elements = [];
            // Check toolbar buttons
            document.querySelectorAll('button, [role="button"], [class*="button"]').forEach(el => {
                const text = el.textContent || '';
                const cls = el.className || '';
                const dataName = el.getAttribute('data-name') || '';
                const tooltip = el.getAttribute('data-tooltip') || '';
                if (text.toLowerCase().includes('alert') || 
                    cls.toLowerCase().includes('alert') ||
                    dataName.toLowerCase().includes('alert') ||
                    tooltip.toLowerCase().includes('alert')) {
                    elements.push({
                        tag: el.tagName,
                        className: cls.substring(0, 60),
                        text: text.substring(0, 40),
                        dataName: dataName,
                        tooltip: tooltip
                    });
                }
            });
            return JSON.stringify(elements.slice(0, 5));
        })()
        """
    })
    buttons_info = result.get("result", {}).get("value", "[]")
    print(f"  Alert-related elements found: {buttons_info[:200]}")
    
    ws.close()
    print("\n[*] Done. The TradingView chart should be loaded.")

if __name__ == "__main__":
    main()
