# Figurae Console

Web app privata da eseguire sul proprio PC per gestire il progetto **Figurae (FIG)**, esplorare la demo **BlackChain AI**, annotare vendite e prezzi e preparare il white paper. Il backend Python conserva i dati in SQLite; l'interfaccia si apre nel browser. Node.js non serve per utilizzare l'app.

Figurae è un token ERC-20 con **100.000.000.000 FIG** creati alla distribuzione: **30.000.000.000 FIG ai fondatori**, complessivamente, e **70.000.000.000 FIG al wallet di distribuzione**. Il 30% è un'allocazione iniziale, non una quota mantenuta automaticamente dopo i trasferimenti. Non sono previste nuove emissioni, tasse sui trasferimenti o blocchi amministrativi degli indirizzi.

## Ethereum, QNT e BlackChain

**QNT è un token ERC-20 sulla rete Ethereum**, usato nell'ecosistema Quant. Non è una blockchain su cui distribuire direttamente Figurae. Figurae può essere distribuito su una rete EVM compatibile, inizialmente **Ethereum Sepolia** per le prove. L'app non integra l'API commerciale di Quant Overledger: un collegamento richiederebbe credenziali, configurazione e servizi separati. La scelta di Ethereum non crea da sola un'integrazione con Quant.

**BlackChain AI è il prototipo Python locale già creato**, visibile e utilizzabile nell'esploratore. Registra trasferimenti, stake, unstake e attestazioni IA firmate. Le sue unità, ricompense e saldi simulati sono indipendenti da FIG su Ethereum. Il contratto Figurae usa il consenso della rete ospitante e non aggiunge uno staking proprio. La demo locale non è un nodo Ethereum, un mercato o una blockchain pubblica distribuita.

## Avvio su PC

Serve **Python 3.10 o successivo**. Estrarre il progetto in una cartella e aprire il terminale in quella cartella.

Su Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Su Windows, nel Prompt dei comandi:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

Aprire **http://127.0.0.1:8000**. Al primo accesso l'app chiede di impostare una password; nei successivi accessi usa quella password. I dati sono conservati nella cartella `data/`. Lasciare aperto il terminale mentre si usa l'app; `Ctrl+C` arresta il server.

Dopo l'installazione si può usare `bash launch.sh` su Linux/macOS oppure `launch.bat` su Windows. Gli script usano l'ambiente `.venv` quando presente. Se la porta 8000 è occupata:

```bash
python run.py --port 8001
```

Per scegliere una cartella dati diversa:

```bash
python run.py --data-dir /percorso/ai/dati
```

Il server ascolta su `127.0.0.1`, accessibile dal PC sul quale è avviato. Il login usa un cookie di sessione e le operazioni di modifica richiedono un token CSRF. Le chiavi private del wallet Ethereum restano nel wallet del browser.

## Cosa contiene

| Sezione | Utilizzo |
| --- | --- |
| Dashboard | Supply, allocazione fondatori/distribuzione, stato del progetto, riepilogo vendite e ultimi valori inseriti. |
| BlackChain | Demo iniziale con quattro blocchi verificati, saldi, stake, transazioni, risultati IA; invio di nuove operazioni e creazione di blocchi locali. Importazione e esportazione del registro. |
| Token e wallet | Configurazione della rete EVM e del contratto, collegamento a MetaMask, lettura del token, distribuzione del contratto e trasferimenti FIG confermati nel wallet. |
| Vendite | Registro amministrativo di bozze, pagamenti annotati e consegne; prezzi e quantità precisi, hash della consegna salvato all'invio e esportazione CSV. |
| Prezzi | Storico dei prezzi inseriti manualmente, con fonte e data, ed esportazione CSV. |
| White paper | Bozza modificabile, download Markdown e stampa PDF tramite il browser. |
| Impostazioni | Backup JSON dei dati di progetto, esclusi password e sessioni. |

I prezzi sono **inseriti manualmente**: il grafico non è una quotazione di borsa e l'app non inventa un prezzo corrente. Il registro vendite non incassa pagamenti, non custodisce fondi e non verifica da solo un pagamento fiat. Lo stato di pagamento viene registrato dall'operatore; una consegna on-chain richiede una transazione wallet. La presenza di un hash annotato nel registro non sostituisce la verifica della transazione sull'esploratore della rete.

La disponibilità gestionale parte dai 70 miliardi FIG di distribuzione e sottrae gli ordini non annullati: è una prenotazione nel registro, non il saldo Ethereum del wallet. Il valore degli ordini pagati è espresso in EUR al prezzo scritto sull'ordine, anche quando si annota un pagamento in ETH o QNT; non è una conversione automatica di quelle valute.

La bozza del white paper descrive la supply, l'allocazione iniziale, il token e la demo locale. È da completare con le informazioni reali del progetto prima della pubblicazione; non contiene attestazioni di audit, adozione o quotazioni che non siano state dimostrate.

## Prova del token con MetaMask

1. Installare MetaMask nel browser, creare o utilizzare un wallet e selezionare **Sepolia**. Per le transazioni servono ETH di test su quella rete.
2. Aprire la sezione token dell'app e collegare il wallet. Verificare rete, indirizzi dei fondatori, quote complessive del 30% e wallet di distribuzione prima di confermare il deployment.
3. Confermare la transazione in MetaMask. Dopo la conferma, configurare o conservare nell'app l'indirizzo del contratto Figurae.
4. Leggere supply e saldi; provare un piccolo trasferimento FIG. Ogni trasferimento richiede la conferma di MetaMask e gas sulla rete selezionata.

L'app non distribuisce automaticamente il token e non dispone delle chiavi private Ethereum. Cambiare rete o usare un contratto su Ethereum mainnet comporta transazioni reali e costi di gas reali; il percorso iniziale è Sepolia. Un token distribuito non crea automaticamente un mercato, liquidità o una quotazione. Il contratto Solidity e il relativo artefatto sono inclusi per la verifica del codice e del deployment.

Per le consegne degli ordini, l'hash è registrato appena il wallet invia la transazione. Se la conferma si interrompe, aprire **Verifica consegna** sullo stesso ordine: il wallet controlla ricevuta, contratto, mittente, destinatario e quantità prima di completare l'ordine. Non inviare nuovamente i token finché l'esito dell'hash esistente è incerto. Una stessa transazione non può essere associata a due ordini. La console non sostituisce automaticamente una transazione annullata, sostituita o fallita.

## GitHub e backup

Questo progetto è pronto per un **repository GitHub privato**. Eseguire l'app localmente anche dopo aver clonato il repository; GitHub ospita il codice, non esegue questo backend Python. Pubblicare l'HTML su GitHub Pages non rende privata l'app e non offre il database, il backend o questo sistema di login.

La cartella `data/` è esclusa da Git: contiene database, configurazione, sessioni e dati di progetto. Anche backup JSON ed esportazioni CSV possono contenere dati di clienti o operazioni: conservarli fuori dal repository. Il backup esportato dall'app non include password e sessioni; conservarlo in una posizione privata. Prima di aggiornamenti del progetto, creare un backup dalla schermata impostazioni oppure arrestare il server e copiare l'intera cartella dati.

Per pubblicare solo il codice in un repository privato già creato:

```bash
git init
git add .
git status
git commit -m "Add Figurae Console"
git branch -M main
git remote add origin https://github.com/TUO-ACCOUNT/TUO-REPOSITORY.git
git push -u origin main
```

Controllare l'elenco di `git status` prima del commit, soprattutto se si usa una cartella dati personalizzata. Non sono stati creati repository o deployment pubblici da questa app.

## Verifica e struttura

Per installare le dipendenze dei test ed eseguirli:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Sono stati verificati **19 test delle API**: autenticazione, persistenza, contabilità precisa, consegne registrate, CSV, white paper, backup e verifica del registro firmato.

Per sviluppare e verificare anche il contratto Solidity, serve **Node.js 24 o successivo**. Questo strumento è facoltativo: l'app usa l'artefatto del contratto già incluso e funziona normalmente con il solo Python.

```bash
npm ci --ignore-scripts
npm run compile
npm test
```

`npm run compile` compila `contracts/Figurae.sol` e rigenera **`contracts/Figurae.json`**, lo stesso ABI/bytecode utilizzato dal backend e dal wallet. Le versioni sono fissate nel lockfile: Solidity 0.8.30, OpenZeppelin 5.4.0, ethers 6.15.0 e Ganache 7.9.2. Dopo modifiche al contratto, ricompilare e verificare i test prima di distribuire una nuova emissione.

`npm test` esegue **32 test JavaScript**: **22 del contratto** su una catena Ganache temporanea e **10 del wallet** per quantità esatte, destinatari, quote e ciclo di collegamento. Insieme ai 19 test API sono **51 test automatici superati**. Questi test non distribuiscono un token su una rete pubblica.

Per verificare soltanto il modulo wallet, senza installare il toolkit Solidity:

```bash
node --test --test-isolation=none tests/wallet.test.mjs
```

È stata verificata anche l'interfaccia nel browser: le sei sezioni, registrazione di prezzi e vendite, annotazione del pagamento, transazione stake e creazione di un blocco locale, modifica/esportazione del white paper, persistenza al ricaricamento e visualizzazione mobile senza scorrimento orizzontale.

Per ripetere questa verifica facoltativa, installare Playwright e il solo browser Chromium:

```bash
python -m pip install playwright
python -m playwright install chromium
python scripts/browser-smoke.py
```

Lo script avvia e arresta un'istanza di prova sulla **porta 8187**, con una cartella dati temporanea separata da quella dell'utente. La porta deve essere libera. Il test del browser non usa MetaMask e non verifica deployment o trasferimenti su una rete pubblica.

Le dipendenze runtime sono FastAPI, Uvicorn, Pydantic e cryptography. `httpx` serve ai test; non è richiesto per l'uso quotidiano. Il file `requirements.txt` fissa intervalli compatibili, quindi può essere installata una versione più recente all'interno di tali intervalli.

Versioni utilizzate per le verifiche: Python 3.12, FastAPI 0.141.1, Uvicorn 0.52.1, Pydantic 2.13.4, cryptography 50.0.0, httpx 0.28.1; Node.js 24.19.0 per i test JavaScript. La libreria ethers 6.15.0 è inclusa nell'app.

- `run.py`: avvio locale.
- `backend/`: autenticazione, persistenza e API.
- `web/`: interfaccia e libreria ethers inclusa, senza dipendenze CDN a runtime.
- `blackchain/`: motore Python del prototipo Proof of Stake.
- `contracts/`: contratto Figurae, ABI e bytecode per il wallet.
- `scripts/`: compilazione Solidity, catena EVM temporanea e verifica facoltativa del browser.
- `tests/`: verifiche del backend, del contratto Solidity e del wallet.
- `package.json` e `package-lock.json`: toolkit Node.js facoltativo per sviluppare il contratto.
- `data/`: dati locali creati all'avvio e ignorati da Git.

La demo IA usa un piccolo classificatore di sentiment basato su pesi di parole, non un modello addestrato. Le attestazioni firmate identificano il worker che dichiara il risultato; non provano che l'inferenza sia corretta. BlackChain non implementa rete P2P o finalità distribuita e usa wallet dimostrativi; non destinarvi fondi reali.
