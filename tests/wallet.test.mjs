import test from 'node:test';
import assert from 'node:assert/strict';
import {
  validateConfig, validateAddress, parseQuantity, connectWallet,
  observeWallet, disconnectWallet, getWalletState, readToken,
  transferToken,
} from '../web/wallet.js';

const founder = '0x1111111111111111111111111111111111111111';
const founder2 = '0x2222222222222222222222222222222222222222';
const distribution = '0x3333333333333333333333333333333333333333';
const validConfig = () => ({
  chain_id: 11155111,
  founders: [{ address: founder, bps: 3000 }],
  distribution_wallet: distribution,
});

test('30% initial allocation is exactly 3,000 bps of total supply', () => {
  const config = validConfig();
  config.founders = [{ address: founder, bps: 1000 }, { address: founder2, bps: 2000 }];
  assert.deepEqual(validateConfig(config), config);
  assert.equal(config.founders.reduce((sum, row) => sum + row.bps, 0), 3000);
});

test('supply-scale and one-wei token quantities use exact BigInt arithmetic', () => {
  assert.equal(parseQuantity('100000000000'), 100_000_000_000n * 10n ** 18n);
  assert.equal(parseQuantity('0.000000000000000001'), 1n);
  assert.equal(parseQuantity('123.456789123456789123'), 123456789123456789123n);
  assert.equal(parseQuantity('0001.5'), 1500000000000000000n);
});

test('rejects lossy, negative, zero, or non-fixed-decimal quantities', () => {
  for (const quantity of ['0', '0.000', '-1', '1e18', '1,5', '1.', '.1', ' 1', '1 ', '0.0000000000000000001', '', 'NaN', 1, null]) {
    assert.throws(() => parseQuantity(quantity), undefined, String(quantity));
  }
  assert.throws(() => parseQuantity(((1n << 256n) - 1n).toString()));
});

test('rejects zero, malformed, and invalid-checksum addresses', () => {
  assert.equal(validateAddress(founder), founder);
  for (const address of [null, '', 'alice.eth', '0x12', '0x0000000000000000000000000000000000000000', '0x52908400098527886E0F7030069857D2E4169Ee7']) {
    assert.throws(() => validateAddress(address));
  }
});

test('rejects overlapping distribution wallet, duplicate founders, and shares outside 30%', () => {
  const variants = [
    { founders: [] },
    { founders: Array.from({ length: 51 }, (_, i) => ({ address: `0x${(i + 1).toString(16).padStart(40, '0')}`, bps: 1 })) },
    { founders: [{ address: distribution, bps: 3000 }] },
    { founders: [{ address: founder, bps: 1000 }, { address: founder, bps: 2000 }] },
    { founders: [{ address: founder, bps: 0 }] },
    { founders: [{ address: founder, bps: 3001 }] },
    { founders: [{ address: founder, bps: 2999 }] },
    { founders: [{ address: founder, bps: '3000' }] },
    { founders: [{ address: founder, bps: 2999.5 }] },
    { distribution_wallet: '0x0000000000000000000000000000000000000000' },
  ];
  for (const variant of variants) assert.throws(() => validateConfig({ ...validConfig(), ...variant }));
});

test('accepts exactly 50 distinct founders whose allocations sum to 30%', () => {
  const config = validConfig();
  config.founders = Array.from({ length: 50 }, (_, i) => ({ address: `0x${(i + 1).toString(16).padStart(40, '0')}`, bps: 60 }));
  assert.equal(validateConfig(config).founders.length, 50);
});

test('rejects invalid chain IDs and does not mutate configuration', () => {
  for (const chain_id of [0, -1, 1.5, NaN, Infinity, '1', Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => validateConfig({ ...validConfig(), chain_id }));
  }
  const config = validConfig();
  Object.freeze(config.founders[0]);
  Object.freeze(config.founders);
  Object.freeze(config);
  assert.equal(validateConfig(config).chain_id, 11155111);
});

test('wallet lifecycle prompts only on explicit connect and attaches each listener once', async () => {
  const listeners = new Map();
  const calls = [];
  let accounts = [founder];
  let chain = '0xaa36a7';
  globalThis.window = { ethereum: {
    async request({ method }) {
      calls.push(method);
      if (method === 'eth_accounts' || method === 'eth_requestAccounts') return accounts;
      if (method === 'eth_chainId') return chain;
      throw new Error(`Unexpected RPC ${method}`);
    },
    on(event, callback) {
      assert.equal(listeners.has(event), false);
      listeners.set(event, callback);
    },
  } };
  const states = [];
  const unsubscribe = observeWallet(state => states.push(state));
  const unsubscribe2 = observeWallet(() => {});
  assert.equal(calls.length, 0);
  assert.equal(getWalletState(), null);
  assert.equal((await connectWallet()).chainId, 11155111);
  assert.equal(calls.filter(method => method === 'eth_requestAccounts').length, 1);
  assert.equal(listeners.size, 3);
  accounts = [founder2];
  listeners.get('accountsChanged')(accounts);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(getWalletState().address, founder2);
  chain = '0x1';
  listeners.get('chainChanged')(chain);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(getWalletState().chainId, 1);
  await assert.rejects(readToken(distribution, 11155111), /Rete errata.*11155111.*chain ID 1/);
  disconnectWallet();
  listeners.get('accountsChanged')([founder]);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(getWalletState(), null);
  assert.equal(states.at(-1), null);
  unsubscribe(); unsubscribe2();
  delete globalThis.window;
});

test('missing wallet and user cancellation have actionable Italian errors', async () => {
  await assert.rejects(connectWallet(), /Installa MetaMask/);
  globalThis.window = { ethereum: { async request() { throw Object.assign(new Error('Rejected'), { code: 4001 }); } } };
  await assert.rejects(connectWallet(), /annullata nel wallet/);
  delete globalThis.window;
});

test('an invalid submission recorder is rejected before requesting any wallet transaction', async () => {
  let requests = 0;
  globalThis.window = { ethereum: { async request() { requests++; throw new Error('Unexpected wallet request'); } } };
  await assert.rejects(transferToken(
    { chain_id: 11155111, contract_address: distribution },
    { recipient: founder, quantity: '1', onSubmitted: 42 },
  ), /registrazione della transazione non è valida/);
  assert.equal(requests, 0);
  delete globalThis.window;
});
