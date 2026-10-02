import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import solc from "solc";

export const projectRoot = fileURLToPath(new URL("../", import.meta.url));

export function compileFigurae() {
  const sourceName = "contracts/Figurae.sol";
  const input = {
    language: "Solidity",
    sources: { [sourceName]: { content: fs.readFileSync(path.join(projectRoot, sourceName), "utf8") } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] } }
    }
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input), {
    import(importPath) {
      if (!importPath.startsWith("@openzeppelin/contracts/")) {
        return { error: `Import non consentito: ${importPath}` };
      }
      const modulesRoot = path.resolve(projectRoot, "node_modules");
      const resolved = path.resolve(modulesRoot, importPath);
      if (!resolved.startsWith(`${modulesRoot}${path.sep}`)) return { error: "Import fuori dal progetto" };
      try {
        return { contents: fs.readFileSync(resolved, "utf8") };
      } catch {
        return { error: `Import non trovato: ${importPath}` };
      }
    }
  }));
  const errors = (output.errors ?? []).filter(error => error.severity === "error");
  if (errors.length) throw new Error(errors.map(error => error.formattedMessage).join("\n"));
  const contract = output.contracts[sourceName].Figurae;
  return {
    contractName: "Figurae",
    sourceName,
    compilerVersion: solc.version(),
    evmVersion: "shanghai",
    abi: contract.abi,
    bytecode: `0x${contract.evm.bytecode.object}`,
    deployedBytecode: `0x${contract.evm.deployedBytecode.object}`
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const artifact = compileFigurae();
    const outputPath = path.join(projectRoot, "contracts/Figurae.json");
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, JSON.stringify(artifact, null, 2) + "\n");
    console.log(`Figurae compilato: ${outputPath}`);
    console.log(`Solidity ${artifact.compilerVersion}, EVM ${artifact.evmVersion}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
