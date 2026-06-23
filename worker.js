const { workerData, parentPort } = require('worker_threads');
const { ethers } = require('ethers');

const BATCH_SIZE = workerData.batchSize;
const seen = new Set();

function generateBatch() {
  const wallets = [];
  for (let i = 0; i < BATCH_SIZE; i++) {
    const words = Array.from({ length: 12 }, () =>
      ethers.wordlists.en.getWord(Math.floor(Math.random() * 2048))
    );
    const mnemonic = words.join(' ');
    if (!ethers.utils.isValidMnemonic(mnemonic) || seen.has(mnemonic)) continue;
    seen.add(mnemonic);

    const hdNode = ethers.utils.HDNode.fromMnemonic(mnemonic, '')
      .derivePath(ethers.utils.defaultPath);

    wallets.push({ mnemonic, address: hdNode.address, privateKey: hdNode.privateKey });
  }
  parentPort.postMessage(wallets);
}

parentPort.on('message', (msg) => {
  if (msg === 'next') generateBatch();
});

generateBatch();
