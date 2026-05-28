import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import YAML from 'yaml';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');

// Load .env if present (Railway sets env vars natively)
try {
  const envPath = path.join(ROOT, '.env');
  if (fs.existsSync(envPath)) {
    const envContent = fs.readFileSync(envPath, 'utf-8');
    for (const line of envContent.split('\n')) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#')) {
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          const val = trimmed.slice(eqIdx + 1).trim();
          if (!process.env[key]) {
            process.env[key] = val;
          }
        }
      }
    }
  }
} catch {}

export function getConfig() {
  const strategyPath = process.env.STRATEGY_CONFIG_PATH ||
    path.join(ROOT, 'data/strategy/config.yaml');

  let strategy = {};
  try {
    const raw = fs.readFileSync(strategyPath, 'utf-8');
    strategy = YAML.parse(raw) || {};
  } catch {
    strategy = {};
  }

  return {
    port: parseInt(process.env.PORT || '8080', 10),
    env: process.env.NODE_ENV || 'development',
    webhookSecret: process.env.WEBHOOK_SECRET || '',
    paperBalance: parseFloat(process.env.PAPER_BALANCE_USD || '100000'),
    binanceApiKey: process.env.BINANCE_API_KEY || '',
    binanceApiSecret: process.env.BINANCE_API_SECRET || '',
    exchangeRateApiKey: process.env.EXCHANGE_RATE_API_KEY || '',
    dataDir: path.join(ROOT, 'data'),
    strategy,
    root: ROOT,
  };
}

export default getConfig;
