// Debug Alpaca SDK
const Alpaca = require('@alpacahq/alpaca-trade-api');

// Monkeypatch
const http = require('http');
const https = require('https');
const origReq = https.request;
https.request = (...args) => {
  const url = typeof args[0] === 'string' ? args[0] : (args[0]?.hostname || '') + (args[0]?.path || '');
  console.log('HTTPS Request:', url.substring(0,100));
  return origReq.apply(https, args);
};

const a = new Alpaca({
  keyId: '***',
  secretKey: '***',
  paper: true,
  usePolygon: false
});

a.getAccount().then(acct => {
  console.log('Account:', acct.account_number, acct.status);
}).catch(err => {
  console.error('Error:', err.message);
});
