from __future__ import annotations


TOKEN = {
    "name": "Figurae", "symbol": "FIG", "decimals": 18,
    "max_supply": "100000000000", "founders_supply": "30000000000",
    "distribution_supply": "70000000000", "standard": "ERC-20",
    "ai_integration": "branding_only", "additional_minting": False,
    "public_deployment_verified": False,
}


def render_whitepaper(fields: dict, settings: dict, version: int, updated_at: str) -> str:
    owners = "\n".join(
        f"- {f['address'] or 'Wallet da configurare'}: {f['bps']} bps della supply totale."
        for f in settings["founders"]
    )
    return f"""# Figurae (FIG) — whitepaper di lavoro

Versione {version} · Aggiornato {updated_at}

## Progetto

{settings['project_description']}

### Missione

{fields['mission']}

### Utility

{fields['utility']}

## Tokenomics

Figurae è un token ERC-20 con 18 decimali. La supply fissa iniziale e massima è **100.000.000.000 FIG**.
Il contratto non include emissioni successive, commissioni sui trasferimenti o congelamento degli indirizzi.

- Fondatori: **30.000.000.000 FIG (30%)**, allocazione aggregata iniziale.
- Distribuzione: **70.000.000.000 FIG (70%)**.

Il 30% dei fondatori è un'allocazione al momento della creazione del contratto, non una quota mantenuta dopo trasferimenti o vendite. Non è previsto vesting automatico nel contratto corrente.

{owners}

Wallet di distribuzione: {settings['distribution_wallet'] or 'da configurare'}.

## Rete e distribuzione

Rete selezionata nella console: {settings['network_name']} (chain ID {settings['chain_id']}).
Indirizzo del contratto registrato: {settings['contract_address'] or 'non configurato'}.
Il deploy pubblico e lo stato del contratto non sono verificati dal backend. L'indirizzo inserito è un dato di configurazione; il wallet nel browser permette le interazioni con Ethereum.

## Intelligenza artificiale, BlackChain e Quant

L'ispirazione IA di Figurae riguarda il branding: il token non contiene un modello IA e non promette rendimenti o capacità IA autonome.
BlackChain è un registro PoS **locale e separato**, con wallet deterministici dimostrativi e un classificatore di sentiment didattico. Non esiste un bridge tra BlackChain e FIG né consenso distribuito implementato.
QNT è il token ERC-20 di Quant su Ethereum. Figurae non gira su QNT. La console non implementa una connessione a Quant Overledger: la denominazione QNT nelle vendite è solo una valuta di pagamento annotata manualmente.

## Vendita e consegna

{fields['sale_policy']}

Gli ordini riservano quantità del wallet di distribuzione; la console registra stati, riferimenti di pagamento e hash dichiarati dal gestore.
Una vendita completata è una consegna registrata dal gestore. Nell’interfaccia, il wallet verifica ricevuta, contratto, mittente, destinatario e quantità; il backend non esegue una verifica indipendente sulla rete. Il pagamento è confermato manualmente dal gestore.
I prezzi e le statistiche sono dati locali manuali: non quotazioni di exchange, prezzi di mercato certificati o liquidità disponibile.

## Roadmap

{fields['roadmap']}

## Limiti e rischi del progetto

Il prezzo può variare fino alla perdita completa del valore. Non sono garantiti profitto, liquidità o quotazione su exchange.
Il contratto e l'eventuale vendita pubblica richiedono verifiche tecniche e delle regole applicabili al progetto prima dell'uso reale. Questo documento è una bozza modificabile, non una dichiarazione di approvazione o di conformità.

## Note

{fields['notes'] or 'Nessuna nota aggiuntiva.'}

Sito: {settings['website'] or 'da definire'}
Contatto: {settings['contact'] or 'da definire'}
"""
