import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { Interface, ZeroAddress, getAddress } from "ethers";
import { compileFigurae } from "../scripts/compile.mjs";
import { createLocalChain } from "../scripts/local-chain.mjs";

const SUPPLY = 100_000_000_000n * 10n ** 18n;
let chain;
let abi;

before(async () => {
  const artifact = compileFigurae();
  abi = new Interface(artifact.abi);
  chain = await createLocalChain(artifact);
});

after(async () => {
  if (chain) await chain.close();
});

function recipient(index) {
  return getAddress(`0x${(10_000n + BigInt(index)).toString(16).padStart(40, "0")}`);
}

async function rejectsWithError(founders, shares, distribution, errorName) {
  await assert.rejects(chain.deploy(founders, shares, distribution), error => {
    // Ganache includes constructor revert bytes in the failed estimateGas response.
    const data = error.data ?? error.info?.error?.data?.result;
    assert.equal(typeof data, "string", "expected constructor revert data");
    assert.equal(abi.parseError(data)?.name, errorName);
    return true;
  });
}

test("rejects no founders", async () => {
  await rejectsWithError([], [], chain.addresses[1], "InvalidFounderCount");
});

test("rejects mismatched founders and share arrays", async () => {
  await rejectsWithError([chain.addresses[0]], [], chain.addresses[1], "FounderArrayLengthMismatch");
});

test("rejects a zero distribution wallet", async () => {
  await rejectsWithError([chain.addresses[0]], [3000], ZeroAddress, "InvalidDistributionWallet");
});

test("rejects a zero founder wallet", async () => {
  await rejectsWithError([ZeroAddress], [3000], chain.addresses[1], "InvalidFounder");
});

test("rejects a founder who is also the distribution wallet", async () => {
  await rejectsWithError([chain.addresses[1]], [3000], chain.addresses[1], "FounderIsDistributionWallet");
});

test("rejects duplicate founder wallets", async () => {
  await rejectsWithError([chain.addresses[0], chain.addresses[0]], [1500, 1500], chain.addresses[1], "DuplicateFounder");
});

test("rejects a zero share even when the total is correct", async () => {
  await rejectsWithError([chain.addresses[0], chain.addresses[2]], [3000, 0], chain.addresses[1], "InvalidFounderShare");
});

for (const total of [1, 2999, 3001, 65535]) {
  test(`rejects a founders total of ${total} basis points`, async () => {
    await rejectsWithError([chain.addresses[0]], [total], chain.addresses[1], "InvalidFoundersShareTotal");
  });
}

test("rejects more than 50 founders", async () => {
  const founders = Array.from({ length: 51 }, (_, index) => recipient(index));
  await rejectsWithError(founders, Array(51).fill(60), chain.addresses[1], "InvalidFounderCount");
});

test("allocates 15% each to two founders and exactly 70% to distribution", async () => {
  const founders = [chain.addresses[0], chain.addresses[2]];
  const token = await chain.deploy(founders, [1500, 1500], chain.addresses[1]);
  for (const founder of founders) {
    assert.equal(await token.balanceOf(founder), SUPPLY * 15n / 100n);
    assert.equal(await token.founderAllocation(founder), SUPPLY * 15n / 100n);
  }
  assert.equal(await token.balanceOf(chain.addresses[1]), SUPPLY * 70n / 100n);
  assert.equal(await token.founderAllocation(chain.addresses[1]), 0n);
  assert.equal(await token.totalSupply(), SUPPLY);
});

test("unequal founders shares remain exact down to a single basis point", async () => {
  const founders = [chain.addresses[0], chain.addresses[2], chain.addresses[3]];
  const shares = [1, 2, 2997];
  const token = await chain.deploy(founders, shares, chain.addresses[1]);
  let totalFounders = 0n;
  for (let index = 0; index < founders.length; index += 1) {
    const expected = SUPPLY * BigInt(shares[index]) / 10_000n;
    assert.equal(await token.balanceOf(founders[index]), expected);
    assert.equal(await token.founderAllocation(founders[index]), expected);
    totalFounders += expected;
  }
  assert.equal(totalFounders, SUPPLY * 30n / 100n);
  assert.equal(await token.totalSupply(), SUPPLY);
});

test("allows exactly 50 founders with exact allocations and fixed total supply", async () => {
  const founders = Array.from({ length: 50 }, (_, index) => recipient(index));
  const token = await chain.deploy(founders, Array(50).fill(60), chain.addresses[1]);
  const expected = SUPPLY * 60n / 10_000n;
  for (const founder of founders) {
    assert.equal(await token.balanceOf(founder), expected);
    assert.equal(await token.founderAllocation(founder), expected);
  }
  assert.equal(expected * 50n, SUPPLY * 30n / 100n);
  assert.equal(await token.balanceOf(chain.addresses[1]), SUPPLY * 70n / 100n);
  assert.equal(await token.totalSupply(), SUPPLY);
});
