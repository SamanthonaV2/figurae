import {
  BrowserProvider, Contract, ContractFactory, Interface, ZeroAddress,
  formatUnits, getAddress,
} from './assets/ethers.js';

const DECIMALS = 18;
const MAX_SUPPLY = 100_000_000_000n * 10n ** 18n;
const MAX_UINT256 = (1n << 256n) - 1n;
const RECEIPT_TIMEOUT_MS = 180_000;
const TOKEN_ABI = [
  'function name() view returns (string)',
  'function symbol() view returns (string)',
  'function decimals() view returns (uint8)',
  'function totalSupply() view returns (uint256)',
  'function MAX_SUPPLY() view returns (uint256)',
  'function FOUNDERS_ALLOCATION() view returns (uint256)',
  'function founderAllocation(address) view returns (uint256)',
  'function balanceOf(address) view returns (uint256)',
  'function transfer(address,uint256) returns (bool)',
  'event Transfer(address indexed from,address indexed to,uint256 value)',
];
const tokenInterface = new Interface(TOKEN_ABI);
const observers = new Set();
const observedProviders = new WeakSet();
let walletState = null;
let activeEthereum = null;
let provider = null;
let stateVersion = 0;

const networkNames = new Map([
  [1, 'Ethereum'], [11155111, 'Ethereum Sepolia'],
  [31337, 'Ethereum locale (Hardhat)'], [1337, 'Ethereum locale'],
]);

function networkName(chainId) {
  return networkNames.get(chainId) || `Rete EVM ${chainId}`;
}

function fail(message, code = 'WALLET_VALIDATION') {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function chainIdNumber(value) {
  let number;
  try {
    const integer = BigInt(value);
    if (integer <= 0n || integer > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error();
    number = Number(integer);
  } catch {
    fail('Chain ID non valido. Specifica un intero positivo.');
  }
  return number;
}

/** Exact validation: no floats, exponents, negative values, or truncation. */
export function parseQuantity(quantity) {
  if (typeof quantity !== 'string' || quantity.length > 100 || !/^\d+(?:\.\d{1,18})?$/.test(quantity)) {
    fail('Quantità non valida: usa cifre e un punto, con al massimo 18 decimali.');
  }
  const [whole, fractional = ''] = quantity.split('.');
  const units = BigInt(whole) * 10n ** 18n + BigInt(fractional.padEnd(18, '0'));
  if (units <= 0n) fail('La quantità deve essere maggiore di zero.');
  if (units > MAX_UINT256) fail('La quantità supera il limite del token.');
  return units;
}

export function validateAddress(value, label = 'Wallet') {
  let address;
  try {
    if (typeof value !== 'string') throw new Error();
    address = getAddress(value.trim());
  } catch {
    fail(`${label}: indirizzo Ethereum non valido (42 caratteri, prefisso 0x).`);
  }
  if (address === ZeroAddress) fail(`${label}: l’indirizzo zero non è ammesso.`);
  return address;
}

/** Shares are basis points of the TOTAL supply; 3,000 bps = 30%. */
export function validateConfig(config) {
  if (!config || typeof config !== 'object') fail('Configurazione del token assente.');
  if (typeof config.chain_id !== 'number' || !Number.isSafeInteger(config.chain_id)) {
    fail('Chain ID non valido. Specifica un intero positivo.');
  }
  const chain_id = chainIdNumber(config.chain_id);
  if (!Array.isArray(config.founders) || config.founders.length < 1 || config.founders.length > 50) {
    fail('Configura da 1 a 50 proprietari.');
  }
  const distribution_wallet = validateAddress(config.distribution_wallet, 'Wallet di distribuzione');
  const seen = new Set([distribution_wallet.toLowerCase()]);
  let total = 0;
  const founders = config.founders.map((founder, index) => {
    const address = validateAddress(founder?.address, `Proprietario ${index + 1}`);
    if (address.toLowerCase() === distribution_wallet.toLowerCase()) {
      fail('Il wallet di distribuzione deve essere distinto dai proprietari.');
    }
    if (seen.has(address.toLowerCase())) fail('Gli indirizzi dei proprietari devono essere distinti.');
    seen.add(address.toLowerCase());
    const bps = founder?.bps;
    if (typeof bps !== 'number' || !Number.isInteger(bps) || bps < 1 || bps > 3000) {
      fail(`Proprietario ${index + 1}: quota non valida; usa interi da 1 a 3.000 bps.`);
    }
    total += bps;
    return { address, bps };
  });
  if (total !== 3000) fail(`Le quote dei proprietari devono sommare 3.000 bps (30%); attualmente ${total}.`);
  return { chain_id, founders, distribution_wallet };
}

function validateTokenConfig(config) {
  if (!config || typeof config.chain_id !== 'number' || !Number.isSafeInteger(config.chain_id)) {
    fail('Configurazione della rete assente o non valida.');
  }
  return {
    chainId: chainIdNumber(config.chain_id),
    address: validateAddress(config.contract_address, 'Contratto Figurae'),
  };
}

function ethereum() {
  const injected = globalThis.window?.ethereum;
  if (!injected || typeof injected.request !== 'function') {
    fail('Wallet Ethereum assente. Installa MetaMask o un wallet compatibile, poi premi «Collega wallet».', 'WALLET_MISSING');
  }
  return injected;
}

function notifyObservers() {
  const state = getWalletState();
  for (const callback of observers) {
    // A rendering failure must not turn a completed wallet action into a failed action.
    try { callback(state); } catch (error) { console.error('Aggiornamento wallet non riuscito:', error); }
  }
}

function clearWallet() {
  stateVersion += 1;
  walletState = null;
  activeEthereum = null;
  provider = null;
  notifyObservers();
}

async function refreshWallet(injected) {
  if (injected !== activeEthereum || !walletState) return;
  const version = ++stateVersion;
  try {
    const [accounts, chain] = await Promise.all([
      injected.request({ method: 'eth_accounts' }),
      injected.request({ method: 'eth_chainId' }),
    ]);
    if (version !== stateVersion || injected !== activeEthereum) return;
    if (!Array.isArray(accounts) || !accounts.length) { clearWallet(); return; }
    const chainId = chainIdNumber(chain);
    walletState = { address: validateAddress(accounts[0]), chainId, networkName: networkName(chainId) };
    provider = new BrowserProvider(injected, 'any');
    notifyObservers();
  } catch {
    if (version === stateVersion && injected === activeEthereum) clearWallet();
  }
}

function attachObservers(injected) {
  if (observedProviders.has(injected) || typeof injected.on !== 'function') return;
  observedProviders.add(injected);
  injected.on('accountsChanged', () => { void refreshWallet(injected); });
  injected.on('chainChanged', () => { void refreshWallet(injected); });
  injected.on('disconnect', () => { if (injected === activeEthereum) clearWallet(); });
}

/** Call only in response to the user's "Collega wallet" click. */
export async function connectWallet() {
  try {
    const injected = ethereum();
    const accounts = await injected.request({ method: 'eth_requestAccounts' });
    if (!Array.isArray(accounts) || !accounts.length) fail('Il wallet non ha autorizzato alcun account.');
    const chainId = chainIdNumber(await injected.request({ method: 'eth_chainId' }));
    stateVersion += 1;
    walletState = { address: validateAddress(accounts[0]), chainId, networkName: networkName(chainId) };
    activeEthereum = injected;
    provider = new BrowserProvider(injected, 'any');
    attachObservers(injected);
    notifyObservers();
    return getWalletState();
  } catch (error) { throw friendlyError(error); }
}

export function getWalletState() {
  return walletState ? { ...walletState } : null;
}

/** Local disconnect only; account permissions remain managed inside the wallet. */
export function disconnectWallet() { clearWallet(); }

/** Returns an unsubscribe function. Does not prompt for account permission. */
export function observeWallet(callback) {
  if (typeof callback !== 'function') fail('Osservatore wallet non valido.');
  observers.add(callback);
  const injected = globalThis.window?.ethereum;
  if (injected && typeof injected.request === 'function') attachObservers(injected);
  callback(getWalletState());
  return () => observers.delete(callback);
}

async function requireWallet(expectedChainId) {
  if (!walletState || !activeEthereum || !provider) fail('Collega il wallet prima di continuare.', 'WALLET_DISCONNECTED');
  const injected = ethereum();
  if (injected !== activeEthereum) fail('Il wallet del browser è cambiato. Premi di nuovo «Collega wallet».');
  const [accounts, chain] = await Promise.all([
    injected.request({ method: 'eth_accounts' }),
    injected.request({ method: 'eth_chainId' }),
  ]);
  if (!Array.isArray(accounts) || !accounts.length) { clearWallet(); fail('Il wallet è scollegato. Collegalo di nuovo.'); }
  const address = validateAddress(accounts[0]);
  const chainId = chainIdNumber(chain);
  if (address !== walletState.address || chainId !== walletState.chainId) {
    stateVersion += 1;
    walletState = { address, chainId, networkName: networkName(chainId) };
    provider = new BrowserProvider(injected, 'any');
    notifyObservers();
  }
  if (chainId !== expectedChainId) {
    fail(`Rete errata: serve ${networkName(expectedChainId)} (chain ID ${expectedChainId}), il wallet usa ${networkName(chainId)} (chain ID ${chainId}). Seleziona la rete corretta nel wallet.`, 'WRONG_NETWORK');
  }
  return { address, chainId, provider, injected };
}

async function ensureSameWallet(context) {
  const current = await requireWallet(context.chainId);
  if (current.address !== context.address || current.injected !== context.injected) {
    fail('Il wallet attivo è cambiato durante l’operazione. Controlla l’account e riprova.', 'WALLET_CHANGED');
  }
  return current;
}

async function checkedToken(address, context) {
  const code = await context.provider.getCode(address);
  if (!code || code === '0x' || /^0x0*$/.test(code)) {
    fail('Nessun contratto a questo indirizzo sulla rete selezionata. Controlla indirizzo e chain ID.');
  }
  const token = new Contract(address, TOKEN_ABI, context.provider);
  let metadata;
  try {
    metadata = await Promise.all([
      token.name(), token.symbol(), token.decimals(), token.totalSupply(),
      token.MAX_SUPPLY(), token.FOUNDERS_ALLOCATION(),
    ]);
  } catch (error) {
    if (isTransportError(error)) throw error;
    fail('Il contratto non espone le funzioni richieste di Figurae. Controlla l’indirizzo.');
  }
  const [name, symbol, decimals, totalSupply, maxSupply, foundersAllocation] = metadata;
  if (name !== 'Figurae' || symbol !== 'FIG' || Number(decimals) !== DECIMALS ||
      totalSupply !== MAX_SUPPLY || maxSupply !== MAX_SUPPLY || foundersAllocation !== MAX_SUPPLY * 30n / 100n) {
    fail('Il contratto non corrisponde a Figurae: sono richiesti FIG, 18 decimali, 100 miliardi di token e 30% iniziale ai proprietari.');
  }
  return { token, totalSupply };
}

export async function readToken(address, chainId) {
  try {
    const target = validateAddress(address, 'Contratto Figurae');
    const context = await requireWallet(chainIdNumber(chainId));
    const { token, totalSupply } = await checkedToken(target, context);
    const [balance, founderAllocation, blockNumber] = await Promise.all([
      token.balanceOf(context.address), token.founderAllocation(context.address),
      context.provider.getBlockNumber(),
    ]);
    await ensureSameWallet(context);
    return {
      address: target, totalSupply: formatUnits(totalSupply, DECIMALS),
      founderAllocation: formatUnits(founderAllocation, DECIMALS),
      balance: formatUnits(balance, DECIMALS), currentWallet: context.address,
      chainId: context.chainId, blockNumber,
    };
  } catch (error) { throw friendlyError(error); }
}

/** The caller presents a confirmation dialog; MetaMask independently confirms gas and transaction. */
export async function deployToken(config, artifact) {
  let submittedHash;
  try {
    const normalized = validateConfig(config);
    if (!artifact || !Array.isArray(artifact.abi) || typeof artifact.bytecode !== 'string' ||
        !/^0x(?:[0-9a-fA-F]{2})+$/.test(artifact.bytecode)) {
      fail('Artefatto Solidity assente o non valido. Ricarica il contratto dal server locale.');
    }
    const context = await requireWallet(normalized.chain_id);
    const signer = await context.provider.getSigner(context.address);
    const factory = new ContractFactory(artifact.abi, artifact.bytecode, signer);
    await ensureSameWallet(context);
    const contract = await factory.deploy(
      normalized.founders.map(founder => founder.address),
      normalized.founders.map(founder => founder.bps), normalized.distribution_wallet,
    );
    const transaction = contract.deploymentTransaction();
    if (!transaction) fail('Il wallet non ha restituito una transazione di deployment.');
    submittedHash = transaction.hash;
    const receipt = await transaction.wait(1, RECEIPT_TIMEOUT_MS);
    assertReceipt(receipt);
    await ensureSameWallet(context);
    const address = validateAddress(await contract.getAddress(), 'Contratto creato');
    await checkedToken(address, context);
    const token = new Contract(address, [
      ...TOKEN_ABI, 'function distributionWallet() view returns (address)',
    ], context.provider);
    const distribution = getAddress(await token.distributionWallet());
    if (distribution !== normalized.distribution_wallet) fail('Il wallet di distribuzione on-chain non corrisponde alla configurazione.');
    for (const founder of normalized.founders) {
      const allocation = await token.founderAllocation(founder.address);
      if (allocation !== MAX_SUPPLY * BigInt(founder.bps) / 10_000n) {
        fail('Le allocazioni on-chain non corrispondono alla configurazione dei proprietari.');
      }
    }
    await ensureSameWallet(context);
    return { address, txHash: receipt.hash, chainId: context.chainId, blockNumber: receipt.blockNumber };
  } catch (error) { throw friendlyError(error, submittedHash); }
}

function assertReceipt(receipt) {
  if (!receipt) fail('Transazione non ancora confermata. Controlla l’hash sulla rete corretta.');
  if (Number(receipt.status) !== 1) fail('La transazione è fallita sulla blockchain: nessun trasferimento verificato.');
  if (!Number.isSafeInteger(receipt.blockNumber) || receipt.blockNumber <= 0) {
    fail('Ricevuta priva di un blocco confermato.');
  }
}

function assertTransfer(receipt, contractAddress, sender, recipient, units) {
  assertReceipt(receipt);
  if (getAddress(receipt.from) !== sender) fail('La transazione è stata inviata da un account diverso dal wallet collegato.');
  const matches = receipt.logs.filter(log => {
    if (typeof log.address !== 'string' || log.address.toLowerCase() !== contractAddress.toLowerCase()) return false;
    try {
      const event = tokenInterface.parseLog({ topics: log.topics, data: log.data });
      return event?.name === 'Transfer' && getAddress(event.args.from) === sender &&
        getAddress(event.args.to) === recipient && event.args.value === units;
    } catch { return false; }
  });
  if (matches.length !== 1) {
    fail('La ricevuta non contiene un unico evento Transfer Figurae con wallet, destinatario e quantità attesi. Trasferimento non verificato.');
  }
}

export async function transferToken(config, { recipient, quantity, onSubmitted } = {}) {
  let submittedHash;
  try {
    const target = validateTokenConfig(config);
    const destination = validateAddress(recipient, 'Destinatario');
    const units = parseQuantity(quantity);
    if (onSubmitted !== undefined && typeof onSubmitted !== 'function') {
      fail('La funzione di registrazione della transazione non è valida.');
    }
    const context = await requireWallet(target.chainId);
    const { token } = await checkedToken(target.address, context);
    const balance = await token.balanceOf(context.address);
    if (units > balance) fail('Saldo FIG insufficiente nel wallet collegato.');
    const signer = await context.provider.getSigner(context.address);
    await ensureSameWallet(context);
    const transaction = await token.connect(signer).transfer(destination, units);
    submittedHash = transaction.hash;
    if (onSubmitted) {
      try {
        await onSubmitted({
          txHash: submittedHash, recipient: destination,
          quantity: formatUnits(units, DECIMALS), chainId: context.chainId,
        });
      } catch {
        fail('La transazione è stata inviata, ma la registrazione locale non è riuscita. Recupera la verifica con l’hash; non inviare di nuovo.', 'WALLET_RECORDING_FAILED');
      }
    }
    const receipt = await transaction.wait(1, RECEIPT_TIMEOUT_MS);
    await ensureSameWallet(context);
    assertTransfer(receipt, target.address, context.address, destination, units);
    return {
      txHash: receipt.hash, recipient: destination, quantity: formatUnits(units, DECIMALS),
      chainId: context.chainId, blockNumber: receipt.blockNumber, from: context.address,
    };
  } catch (error) { throw friendlyError(error, submittedHash); }
}

/** Verifies token DELIVERY only; this does not verify a payment or a sale. */
export async function verifyTransfer(config, txHash, { recipient, quantity } = {}) {
  try {
    const target = validateTokenConfig(config);
    if (typeof txHash !== 'string' || !/^0x[0-9a-fA-F]{64}$/.test(txHash)) fail('Hash della transazione non valido.');
    const destination = validateAddress(recipient, 'Destinatario');
    const units = parseQuantity(quantity);
    const context = await requireWallet(target.chainId);
    await checkedToken(target.address, context);
    const receipt = await context.provider.getTransactionReceipt(txHash);
    await ensureSameWallet(context);
    assertTransfer(receipt, target.address, context.address, destination, units);
    return {
      txHash: receipt.hash, recipient: destination, quantity: formatUnits(units, DECIMALS),
      chainId: context.chainId, blockNumber: receipt.blockNumber, from: context.address,
    };
  } catch (error) { throw friendlyError(error); }
}

function isTransportError(error) {
  return ['NETWORK_ERROR', 'SERVER_ERROR', 'TIMEOUT', 'OFFCHAIN_FAULT'].includes(error?.code);
}

function friendlyError(error, submittedHash) {
  const code = error?.code ?? error?.error?.code ?? error?.info?.error?.code;
  let message;
  if (code === 4001 || code === 'ACTION_REJECTED' || error?.info?.error?.code === 4001) {
    message = 'Operazione annullata nel wallet. Nessuna conferma completata.';
  } else if (code === -32002 || error?.info?.error?.code === -32002) {
    message = 'Una richiesta è già aperta nel wallet. Apri MetaMask e completala o annullala.';
  } else if (code === 'INSUFFICIENT_FUNDS') {
    message = 'ETH insufficiente per le commissioni. Aggiungi ETH al wallet sulla rete selezionata.';
  } else if (['NETWORK_ERROR', 'SERVER_ERROR', 'TIMEOUT'].includes(code)) {
    message = 'La rete RPC del wallet non risponde. Controlla connessione e rete selezionata, poi riprova.';
  } else if (code === 'CALL_EXCEPTION') {
    message = 'Il contratto ha rifiutato l’operazione. Controlla rete, indirizzo, saldo e parametri.';
  } else if (code === 'TRANSACTION_REPLACED') {
    message = 'La transazione è stata sostituita o annullata nel wallet. Verifica la nuova transazione prima di continuare.';
  } else {
    message = error?.shortMessage || error?.message || 'Operazione wallet non riuscita.';
  }
  const friendly = new Error(submittedHash
    ? `Transazione inviata: ${submittedHash}. La conferma non è stata verificata. ${message} Controlla l’hash prima di ripetere l’operazione.`
    : message);
  friendly.code = code || 'WALLET_ERROR';
  if (submittedHash) friendly.txHash = submittedHash;
  return friendly;
}
