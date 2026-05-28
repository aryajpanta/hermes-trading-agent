/**
 * TradingView Webhook Handler
 * Receives and validates alerts from TradingView.
 *
 * Expected alert payload format (configured in TradingView):
 * {
 *   "symbol": "BTCUSDT",
 *   "assetClass": "crypto",
 *   "action": "buy" | "sell" | "alert",
 *   "price": 50000,
 *   "strategy": "my_strategy",
 *   "message": "Custom message from TradingView alert"
 * }
 */
import getConfig from '../config/index.js';
import store from '../data/store.js';

const config = getConfig();

/**
 * Parse TradingView webhook payload.
 * TradingView sends JSON via POST — we validate the signature/secret and route it.
 */
export async function handleWebhook(reqBody) {
  // Validate webhook secret if configured
  if (config.webhookSecret) {
    const provided = reqBody?.secret || reqBody?.webhookSecret || '';
    if (provided !== config.webhookSecret) {
      store.append('webhook_errors', {
        timestamp: new Date().toISOString(),
        error: 'Invalid webhook secret',
        provided: provided ? `${provided.slice(0, 4)}...` : 'none',
      });
      return { valid: false, error: 'Invalid webhook secret' };
    }
  }

  // Normalize payload fields
  const alert = {
    symbol: (reqBody.symbol || '').toUpperCase(),
    assetClass: (reqBody.assetClass || 'crypto').toLowerCase(),
    action: (reqBody.action || reqBody.signal || reqBody.order_action || '').toLowerCase(),
    price: parseFloat(reqBody.price || reqBody.close || reqBody.entry || 0),
    strategy: reqBody.strategy || reqBody.strategy_name || 'default',
    message: reqBody.message || reqBody.alert_message || '',
    interval: reqBody.interval || reqBody.timeframe || '',
    volume: parseFloat(reqBody.volume || 0),
    indicators: {
      rsi: parseFloat(reqBody.rsi || 0) || undefined,
      macd: parseFloat(reqBody.macd || 0) || undefined,
      bbUpper: parseFloat(reqBody.bb_upper || 0) || undefined,
      bbLower: parseFloat(reqBody.bb_lower || 0) || undefined,
    },
    raw: reqBody,
  };

  // Validate required fields
  if (!alert.symbol) {
    store.append('webhook_errors', {
      timestamp: new Date().toISOString(),
      error: 'Missing symbol in webhook payload',
      payload: reqBody,
    });
    return { valid: false, error: 'Missing symbol' };
  }

  // Log incoming alert
  store.append('webhook_alerts', {
    timestamp: new Date().toISOString(),
    ...alert,
  });

  return { valid: true, alert };
}

/**
 * Get TradingView configuration instructions for the user.
 */
export function getTradingViewSetupGuide() {
  return {
    webhookUrl: `${config.env === 'production' ? 'https://' : 'http://'}your-railway-url.railway.app/webhook/tradingview`,
    instructions: `# TradingView Webhook Setup

## 1. Create an Alert in TradingView
1. Open a chart for the asset you want to trade
2. Click the alarm clock icon (Alerts)
3. Click "Create Alert"
4. Set your conditions

## 2. Configure the Webhook URL
In the alert creation dialog:
1. Check "Webhook URL"
2. Enter: YOUR_RAILWAY_URL/webhook/tradingview
3. Format the message as JSON:

{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{strategy.order.price}},
  "strategy": "my_strategy",
  "message": "{{ticker}} alert triggered"
}

## 3. Exchange Integration
For Moomoo integration with TradingView:
- Connect your Moomoo account via TradingView's broker integration
- Use TradingView's paper trading mode for testing
- The webhook will execute trades on the paper trading engine

## 4. Verify
Send a test alert and check the /api/trades endpoint to confirm receipt.
`,
  };
}

export default { handleWebhook, getTradingViewSetupGuide };
