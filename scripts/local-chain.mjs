import ganache from "ganache";
import { BrowserProvider, ContractFactory } from "ethers";

// In-memory chain only. It never opens a server or connects to a public network.
export async function createLocalChain(artifact, accountCount = 6) {
  const engine = ganache.provider({
    logging: { quiet: true },
    chain: { chainId: 31337, hardfork: "shanghai" },
    wallet: { totalAccounts: accountCount }
  });
  const provider = new BrowserProvider(engine);
  provider.pollingInterval = 10;
  const signers = await Promise.all(Array.from({ length: accountCount }, (_, index) => provider.getSigner(index)));
  const addresses = await Promise.all(signers.map(signer => signer.getAddress()));
  return {
    provider,
    signers,
    addresses,
    async deploy(founders = [addresses[0]], sharesBps = [3000], distribution = addresses[1]) {
      const factory = new ContractFactory(artifact.abi, artifact.bytecode, signers[0]);
      const token = await factory.deploy(founders, sharesBps, distribution);
      await token.waitForDeployment();
      return token;
    },
    async close() {
      provider.destroy();
      await engine.disconnect();
    }
  };
}
