#!/usr/bin/env node

/**
 * Hermes Trading Agent — Main Server
 *
 * A self-improving trading agent that:
 * 1. Receives TradingView webhook alerts
 * 2. Executes paper trades with configurable strategy
 * 3. Tracks performance metrics (Sharpe, win rate, profit factor, drawdown)
 * 4. Self-improves via Hermes Agent weekly review cycles
 * 5. Runs 24/7 on Railway
 */
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import getConfig from './config/index.js';
import routes from './api/routes.js';
import * as alpaca from './brokers/alpaca.js';

const config = getConfig();
const app = express();

// Middleware
app.use(helmet());
app.use(cors());
app.use(compression());
app.use(express.json({ limit: '1mb' }));
app.use(express.urlencoded({ extended: true }));

// Request logging
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const ms = Date.now() - start;
    console.log(`[${new Date().toISOString()}] ${req.method} ${req.path} ${res.statusCode} ${ms}ms`);
  });
  next();
});

// Routes
app.use('/', routes);

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Not found', path: req.path });
});

// Error handler
app.use((err, req, res, _next) => {
  console.error(`[Error] ${err.message}`, err.stack);
  res.status(500).json({
    error: 'Internal server error',
    message: config.env === 'production' ? 'Something went wrong' : err.message,
  });
});

// Auto-connect to Alpaca if API keys are set in environment
const alpacaKeyId = process.env.ALPACA_API_KEY_ID;
const alpacaSecret = process.env.ALPACA_SECRET_KEY;
if (alpacaKeyId && alpacaSecret) {
  try {
    alpaca.connect(alpacaKeyId, alpacaSecret, true);
    console.log(`  ║   Alpaca: Connected (paper mode)${' '.repeat(17)}║`);
  } catch (err) {
    console.log(`  ║   Alpaca: Connection failed - ${err.message.slice(0, 30)}${' '.repeat(10)}║`);
  }
} else {
  console.log(`  ║   Alpaca: Not configured (using paper)${' '.repeat(15)}║`);
}

// Start server
const server = app.listen(config.port, () => {
  console.log(`\n  ╔══════════════════════════════════════════╗`);
  console.log(`  ║   Hermes Self-Improving Trading Agent   ║`);
  console.log(`  ║   Running on port ${config.port.toString().padEnd(23)}║`);
  console.log(`  ║   Environment: ${config.env.padEnd(28)}║`);
  console.log(`  ║   Strategy: ${(config.strategy?.name || 'default').padEnd(29)}║`);
  console.log(`  ╚══════════════════════════════════════════╝\n`);

  if (config.env === 'development') {
    console.log(`  Local:  http://localhost:${config.port}`);
    console.log(`  Health: http://localhost:${config.port}/health\n`);
  }
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received — shutting down gracefully...');
  server.close(() => process.exit(0));
});

process.on('SIGINT', () => {
  console.log('SIGINT received — shutting down gracefully...');
  server.close(() => process.exit(0));
});

export default app;
