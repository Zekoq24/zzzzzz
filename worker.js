const { workerData, parentPort } = require('worker_threads');
const ethers = require('ethers');

const BATCH_SIZE = workerData.batchSize;
const seen = new Set();
const DEFAULT_PATH = "m/44'/60'/0'/0/0";

function generateBatch() {
  const wallets = [];

  for (let i = 0; i < BATCH_SIZE; i++) {
    const words = Array.from({ length: 12 }, () =>
      ethers.wordlists.en.getWord(Math.floor(Math.random() * 2048))
    );
    const phrase = words.join(' ');
    if (seen.has(phrase)) continue;

    let isValid = false;
    try {
      isValid = ethers.Mnemonic.isValidMnemonic(phrase);
    } catch (_) {
      continue;
    }
    if (!isValid) continue;

    seen.add(phrase);

    try {
      const wallet = ethers.HDNodeWallet.fromPhrase(phrase, '', DEFAULT_PATH);
      wallets.push({ mnemonic: phrase, address: wallet.address, privateKey: wallet.privateKey });
    } catch (_) {
      continue;
    }
  }

  parentPort.postMessage(wallets);
}

parentPort.on('message', (msg) => {
  if (msg === 'next') generateBatch();
});

generateBatch();
