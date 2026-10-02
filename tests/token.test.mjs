import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { Contract, Interface, ZeroAddress, parseUnits } from "ethers";
import { compileFigurae } from "../scripts/compile.mjs";
import { createLocalChain } from "../scripts/local-chain.mjs";

let artifact;
let local;
let token;
const total = parseUnits("100000000000", 18);
const founders = parseUnits("30000000000", 18);
const distribution = parseUnits("70000000000", 18);

before(async () => {
  artifact = compileFigurae();
  local = await createLocalChain(artifact);
  token = await local.deploy();
});
after(async () => { if (local) await local.close(); });

test("Nome, simbolo, decimali e supply esatta", async () => {
  assert.equal(await token.name(), "Figurae");
  assert.equal(await token.symbol(), "FIG");
  assert.equal(await token.decimals(), 18n);
  assert.equal(await token.totalSupply(), total);
  assert.equal(await token.MAX_SUPPLY(), total);
});

test("Allocazione iniziale 30% proprietari e 70% distribuzione", async () => {
  assert.equal(await token.FOUNDERS_ALLOCATION(), founders);
  assert.equal(await token.DISTRIBUTION_ALLOCATION(), distribution);
  assert.equal(await token.balanceOf(local.addresses[0]), founders);
  assert.equal(await token.balanceOf(local.addresses[1]), distribution);
  assert.equal(await token.founderAllocation(local.addresses[0]), founders);
  assert.equal(await token.distributionWallet(), local.addresses[1]);
});

test("Trasferimento standard e supply conservata", async () => {
  const amount = parseUnits("1000", 18);
  await (await token.connect(local.signers[1]).transfer(local.addresses[2], amount)).wait();
  assert.equal(await token.balanceOf(local.addresses[2]), amount);
  assert.equal(await token.balanceOf(local.addresses[1]), distribution - amount);
  assert.equal(await token.totalSupply(), total);
});

test("Approval e transferFrom rispettano allowance", async () => {
  const approved = parseUnits("100", 18);
  const spent = parseUnits("60", 18);
  await (await token.connect(local.signers[2]).approve(local.addresses[3], approved)).wait();
  await (await token.connect(local.signers[3]).transferFrom(local.addresses[2], local.addresses[4], spent)).wait();
  assert.equal(await token.allowance(local.addresses[2], local.addresses[3]), approved - spent);
  assert.equal(await token.balanceOf(local.addresses[4]), spent);
  await assert.rejects(token.connect(local.signers[3]).transferFrom(local.addresses[2], local.addresses[4], approved));
});

test("Saldo insufficiente e destinatario zero vengono rifiutati", async () => {
  await assert.rejects(token.connect(local.signers[5]).transfer(local.addresses[4], 1));
  await assert.rejects(token.transfer(ZeroAddress, 1));
  assert.equal(await token.totalSupply(), total);
});

test("Il 30% è allocazione iniziale trasferibile", async () => {
  const amount = parseUnits("1", 18);
  await (await token.transfer(local.addresses[5], amount)).wait();
  assert.equal(await token.balanceOf(local.addresses[0]), founders - amount);
  assert.equal(await token.founderAllocation(local.addresses[0]), founders);
  assert.equal(await token.totalSupply(), total);
});

test("Emissioni successive non sono esposte né eseguibili", async () => {
  const names = artifact.abi.filter(entry => entry.type === "function").map(entry => entry.name);
  for (const forbidden of ["mint", "burn", "setTax", "pause", "blacklist", "owner", "upgradeTo"]) {
    assert.ok(!names.includes(forbidden));
  }
  const fakeMint = new Contract(await token.getAddress(), new Interface(["function mint(address,uint256)"]), local.signers[0]);
  await assert.rejects(fakeMint.mint(local.addresses[0], 1));
  assert.equal(await token.totalSupply(), total);
});
