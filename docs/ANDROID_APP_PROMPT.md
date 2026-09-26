# Prompt — App Android nativa per ArbitrageSniper

> Copia **solo** il blocco recintato qui sotto e incollalo a un agente di coding
> (Cursor, Claude Code, ecc.). È autosufficiente: l’agente non deve fare domande
> per partire, e non deve inventare un’architettura diversa da quella scritta.
>
> Questo file è la specifica. Non modifica il sistema in esecuzione. Se cambi
> gli endpoint in `arbitrage_sniper/web/app.py`, aggiorna la sezione
> `CONTRATTO API` prima di rilanciare il prompt.
>
> Il prompt cross-platform React Native resta in
> [`MOBILE_APP_PROMPT.md`](MOBILE_APP_PROMPT.md). **Questo documento lo
> sostituisce quando il target è solo Android nativo** (Kotlin + Compose) con
> scheduler controllato dall’utente.

---

```prompt
ROLE
Sei uno Staff Android Engineer (Kotlin, Jetpack Compose) e uno Staff Backend
Engineer (Python, FastAPI). Consegni software production-grade: tipizzazione
forte, migrazioni additive, test, e nessuna regressione sul sistema esistente.
Lavori in autonomia. Chiedi una decisione solo se ha un costo irreversibile
(es. un piano di hosting a pagamento). In ogni altro caso scegli l’opzione
già fissata in questo prompt.

CONTESTO — SISTEMA ESISTENTE ("ArbitrageSniper")
Repository Python già funzionante. Scanner di annunci usati di attrezzatura
fotografica. Hai accesso in lettura a tutto il repo: riusa il codice, non
riscriverlo.

Flusso attuale:

  provider buy-side ──▶ matching ──▶ arbitrage ──▶ Telegram
  (Subito, eBay.it,     (word-boundary)  (MPB margin   + SQLite seen_ads.db
   Back Market, FB,                      OPPURE finestra
   OLX, Publi24,                         di prezzo)
   Vinted EU)
  benchmark: MPB floor, eBay sold avg, F64 retail. Prezzi normalizzati in EUR.

File che DEVI trattare come fonte di verità (leggi prima di scrivere codice):

- main.py                         orchestratore CLI / GitHub Actions
- thresholds.json                 target, finestre di prezzo, providers.enabled, channels
- arbitrage_sniper/models.py      Item, Benchmark, Alert, price_in_range
- arbitrage_sniper/arbitrage.py   trigger risk-zero + cap MAX_GAIN_PCT
- arbitrage_sniper/matching.py    filtri accessori e modelli sbagliati
- arbitrage_sniper/database.py    SQLite seen_ads + run_log + bot_state
- arbitrage_sniper/targets.py     CRUD target e provider abilitati
- arbitrage_sniper/notifier.py    alert Telegram HTML
- arbitrage_sniper/browser.py     Playwright async + stealth
- arbitrage_sniper/web/app.py     REST già esposta (contratto sotto)
- arbitrage_sniper/web/scan_runner.py   scan on-demand, un solo job alla volta
- arbitrage_sniper/providers/*    nomi: subito, ebay_it, backmarket, facebook, olx, publi24, vinted
- .github/workflows/sniper.yml    cron */15, committa seen_ads.db
- .github/workflows/commands.yml  poller Telegram */5
- tests/                          pytest: non devono rompersi

Regola di trigger (invariata):

  buy_price <= mpb_price * MPB_MARGIN (default 0.90)
  AND gain% <= MAX_GAIN_PCT (default 500)
  OPPURE, se il target ha price_min/price_max, l’alert scatta quando il
  prezzo è dentro la finestra. Ogni annuncio che matcha per nome viene
  comunque salvato, anche fuori finestra (flag in_range).

VINCOLO ARCHITETTURALE — NON NEGOZIABILE
Lo scraping NON gira sul telefono. Vietato:

- portare Playwright, Chromium o playwright-stealth su Android;
- scrapare marketplace da WebView, OkHttp o da un servizio in foreground;
- usare WorkManager / AlarmManager come esecutore dello scrape.

Motivo: i provider dipendono da un browser stealth, delay 2–6 s, cookie
Facebook, e un run può durare molti minuti. Su Android questo viola batteria,
policy di Play, anti-bot dei siti, e non è riproducibile.

Architettura obbligatoria, a due piani:

  ┌──────────────────────── Android (control plane) ────────────────────────┐
  │ Compose UI · token cifrato · cache Room · FCM · "Scansiona ora"         │
  │ · frequenza salvata sul server · annunci salvati ("interessanti")       │
  └─────────────── HTTPS + Bearer ──────────────────────────────────────────┘
                                    │
  ┌──────────────────────── Worker Python (data plane) ─────────────────────┐
  │ Processo unico: uvicorn + FastAPI esistente + APScheduler               │
  │ ScanRunner esistente (Playwright) · SQLite su volume persistente        │
  │ Telegram invariato · push FCM in aggiunta                               │
  └─────────────────────────────────────────────────────────────────────────┘

Il telefono è solo interfaccia e telecomando. Il worker è l’unico processo
che chiama i provider e scrive seen_ads.db.

PERCHÉ NON GITHUB ACTIONS COME SCHEDULER DELL’APP
sniper.yml ha il cron fissato a */15 dentro il YAML. L’app non può cambiarlo
senza un commit, e GitHub ritarda i cron. Quindi:

- La frequenza scelta nell’app vive in thresholds.json (blocco "schedule")
  ed è applicata da APScheduler dentro il processo API.
- GitHub Actions resta com’è finché il worker hostato non è verificato.
- Quando il worker è il proprietario dello schedule, disattiva SOLO il
  trigger `schedule:` di sniper.yml (lascia workflow_dispatch). Non
  cancellare il file. Documenta il passaggio in docs/ANDROID.md.
- Non far convivere due writer sullo stesso seen_ads.db. Il worker hostato
  usa un volume proprio. Il DB committato nel git resta quello di GHA finché
  GHA è il writer. Non mischiare i due file.

SOLUZIONE SCRAPING (compatibile col codice attuale)
Riusa ScanRunner e main.Sniper. Non duplicare il loop di scrape.

1. Nel lifespan di FastAPI, avvia un AsyncIOScheduler (libreria APScheduler,
   aggiungila a requirements.txt con versione pinnata).
2. All’avvio leggi lo schedule da thresholds.json. Se mode == "interval" e
   enabled == true, registra un job interval.
3. Il job chiama la stessa funzione di POST /api/scan con mode="all" e
   providers=null (cioè il set abilitato). Se ScanRunner è già running,
   non accodare: registra uno skip (contatore + timestamp) e esci. Il 409
   attuale di "a scan is already running" resta il comportamento corretto.
4. Un lock unico: scan manuale, scan schedulato e scan Telegram non devono
   sovrapporsi. Se oggi il lock è solo in-process (ScanRunner), estendilo
   con un file lock o un BEGIN IMMEDIATE su SQLite così anche un main.py
   lanciato da GHA nello stesso volume fallisce in modo pulito invece di
   corrompere il DB. Non introdurre Redis.
5. Provider, matching, arbitrage, currency, notifier Telegram: zero rewrite.
   L’unica aggiunta sul percorso alert è un fan-out opzionale verso FCM
   dopo l’invio Telegram (se TELEGRAM fallisce, tenta comunque FCM e
   viceversa; un canale morto non blocca l’altro).
6. Facebook resta opzionale: available=false se FACEBOOK_COOKIES_PATH manca,
   come già fa _provider_available.

SOLUZIONE DATI (compatibile con seen_ads.db)
Resta SQLite, stesso file, stesso stile di migrazione ALTER TABLE già usato
in database.py (_MIGRATIONS). Vietato Postgres in questo lavoro. Vietato
spostare lo schema su un ORM.

Tabelle esistenti da non rompere: seen_ads, run_log, bot_state.

Aggiunte additive:

  saved_items (
    unique_key  TEXT PRIMARY KEY,          -- stessa chiave di seen_ads
    note        TEXT NOT NULL DEFAULT '',
    saved_at    INTEGER NOT NULL           -- epoch seconds
  )

  push_tokens (
    token       TEXT PRIMARY KEY,          -- FCM registration token
    updated_at  INTEGER NOT NULL
  )

  schedule_state (riga singola, id = 1) (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    last_started_at     INTEGER,
    last_finished_at    INTEGER,
    last_status         TEXT,               -- idle|running|done|error|skipped_overlap
    last_error          TEXT,
    next_run_at         INTEGER,
    skipped_overlap     INTEGER NOT NULL DEFAULT 0
  )

Lo schedule CONFIG (non lo stato) sta in thresholds.json, accanto a
providers, così un git pull continua a descrivere cosa tracciare:

  "schedule": {
    "mode": "manual",
    "interval_minutes": 30,
    "enabled": false
  }

Default se il blocco manca: mode "manual", enabled false, interval_minutes 30.
Così un deploy nuovo non parte a scrapare da solo finché l’utente non attiva
la frequenza. Il cron GHA, finché lasciato acceso, continua a essere
indipendente da questo blocco (non far dipendere sniper.yml da "schedule",
altrimenti spegni gli scan esistenti per sbaglio).

Intervalli ammessi, e solo questi: 15, 30, 60, 120, 180, 360, 720, 1440
(minuti). Rifiuta qualsiasi altro valore con HTTP 400 e un messaggio che
elenca i valori leciti. Il minimo 15 esiste perché un run con i delay di
cortesia può durare diversi minuti e i siti hanno rate limit.

Modi:

- "manual": enabled deve essere false. Nessun job APScheduler. POST /api/scan
  continua a funzionare.
- "interval": enabled true, interval_minutes uno dei valori sopra. Il prossimo
  run è last_finished_at + interval, oppure now + interval se non c’è ancora
  uno storico. Cambiare l’intervallo dall’app rischedula subito, senza
  riavviare il processo.

Sul client, Room è una CACHE, non la fonte di verità:

  items        specchio di GET /api/items (upsert per unique_key)
  saved_items  specchio di GET /api/saved
  targets      specchio di GET /api/targets
  meta         chiave/valore: last_sync_epoch, api_base_url

Senza rete l’app mostra l’ultima cache e disabilita le azioni di scrittura
con un messaggio esplicito. Al ritorno della rete, le scritture non vanno
in coda silenziosa: l’utente ripreme l’azione (niente outbox in questa
versione, per non avere conflitti col DB del worker).

"Informazione interessante" = un annuncio già presente in seen_ads che
l’utente marca come salvato, con una nota opzionale (max 500 caratteri).
Il salvataggio sopravvive a reinstallazione dell’app perché sta sul server.
Non creare un secondo archivio di annunci scollegato da unique_key: se
l’annuncio non è in seen_ads, POST save risponde 404.

AUTH (singolo utente, niente OAuth)
Questo è un tool personale. Non implementare login multi-utente.

- Env API_TOKEN sul worker (segreto lungo, generato, mai committato).
- Se API_TOKEN è vuoto, tutti gli endpoint /api/* rispondono 503 con
  detail "API_TOKEN is not configured". Non lasciare l’API aperta.
- Il client manda Authorization: Bearer <token>.
- Token assente o sbagliato: 401.
- Eccezione: nessuna. Anche /api/stats richiede il token.
- Sul telefono il token sta in EncryptedSharedPreferences
  (androidx.security:security-crypto). Mai in DataStore in chiaro, mai nei
  log, mai in Crashlytics.
- La dashboard web locale (GET / e gli static) può restare senza auth SOLO
  quando l’host è 127.0.0.1. Se il bind non è loopback, anche la UI web
  richiede il bearer. Documenta il comportamento. I test esistenti che
  chiamano l’API senza token vanno aggiornati per settare API_TOKEN nel
  fixture e mandare l’header: non disabilitare l’auth nei test con un flag
  che poi resta acceso in produzione.

PUSH
- POST /api/push/register { "token": "<fcm>" } sostituisce/aggiorna il token.
- DELETE /api/push/register con lo stesso body lo rimuove.
- All’alert, dopo Telegram, invia una data message FCM (HTTP v1) se esiste
  almeno un token e se FCM_SERVICE_ACCOUNT_JSON è configurato. Se il secret
  FCM manca, logga un warning e continua: gli alert Telegram non si bloccano.
- Payload data (tutte stringhe): unique_key, title, price, currency, link,
  platform, safe_gain, target_label. Il tap apre il dettaglio annuncio.
- Canale Android "deals" con importance HIGH.

CONTRATTO API
Base: il servizio FastAPI già in arbitrage_sniper/web/app.py. JSON. Bearer
su ogni /api/*. Mantieni i codici e i body già usati. Estendi, non rinominare.

Già implementati (riusali, firma attuale):

- GET    /api/stats
         { total_seen, total_alerted, total_in_range, total_targets }
- GET    /api/targets
         { targets: [{ index, id, label, queries, price_min, price_max,
            price_label, mpb_id, mpb_floor, channel, chat_id, topic_id,
            include, exclude }] }
- POST   /api/targets            { query, price_min?, price_max? }   → 201
         409 se il target esiste già
- PATCH  /api/targets/{id}       { price_min?, price_max?, mpb_id?, mpb_floor?,
                                   channel?, clear_price_min?, clear_price_max? }
- DELETE /api/targets/{id}
- GET    /api/items?target&in_range&alerted&platform&q&sort&desc&limit&offset
         sort ∈ last_seen | first_seen | price | safe_gain
         item: { unique_key, platform, ad_id, title, price, link, alerted,
           safe_gain, target_label, currency, condition, image_url, location,
           in_range, mpb_price, ebay_price, f64_price, reason, first_seen,
           last_seen }
         risposta: { items, total, limit, offset }
- GET    /api/filters            { targets: string[], platforms: string[] }
- GET    /api/providers          { providers: [{ name, label, available, enabled }] }
- POST   /api/providers          { enabled: string[] | null }   null = tutti
- POST   /api/scan               { mode: "all"|"query", query?, providers? } → 202
         409 se un scan è già in corso
- GET    /api/scan               { state: idle|running|done|error, mode, query,
           providers, message, started_at, finished_at, scanned, new, alerts,
           error }
- POST   /api/clear?q            { ok, removed }

Nuovi, obbligatori, stesso stile (dict JSON, HTTPException con detail stringa):

- GET  /api/schedule
       { mode, interval_minutes, enabled, allowed_intervals: [15,30,60,120,180,360,720,1440],
         last_started_at, last_finished_at, last_status, last_error,
         next_run_at, skipped_overlap }
- PUT  /api/schedule
       body: { mode: "manual"|"interval", interval_minutes?: number }
       Regole: mode=manual forza enabled=false e non richiede interval
       (se presente, deve comunque essere un valore ammesso, altrimenti 400).
       mode=interval richiede interval_minutes ammesso e setta enabled=true.
       Risposta: lo stesso shape di GET. Effetto immediato sullo scheduler.
- GET  /api/saved?limit&offset
       { items: [ item + { note, saved_at } ], total, limit, offset }
       Gli item sono il join saved_items ⋈ seen_ads. Ordine: saved_at DESC.
- PUT  /api/items/{unique_key}/save
       body: { note?: string }   note default ""
       404 se unique_key non è in seen_ads
       400 se note supera 500 caratteri
       Upsert. Risposta: { ok: true, unique_key, note, saved_at }
- DELETE /api/items/{unique_key}/save
       200 { ok: true, removed: 0|1 } anche se non era salvato (idempotente)
- POST /api/push/register        { token } → { ok: true }
       400 se token vuoto o più lungo di 4096
- DELETE /api/push/register      { token } → { ok: true, removed: 0|1 }

OpenAPI: /openapi.json deve includere i nuovi path. Il client Android NON
va generato a mano campo per campo se puoi generare i DTO da quello schema;
se la generazione complica la build, scrivi i DTO a mano ma con un test che
fallisce quando un campo obbligatorio dello schema sparisce.

APP ANDROID — STACK BLOCCATO
Modulo nuovo: android/  (Gradle Kotlin DSL). Non usare Expo, React Native,
Flutter, o Kotlin Multiplatform.

- Kotlin 2.x, JVM target 17, minSdk 26, targetSdk 35, compileSdk 35
- Jetpack Compose + Material 3, Navigation Compose
- Hilt
- Retrofit + OkHttp + kotlinx.serialization (o Moshi; una sola libreria)
- Room (cache)
- DataStore Preferences solo per preferenze NON segrete (tema, lingua)
- EncryptedSharedPreferences per API base URL? No: la base URL sta in
  DataStore (non è un segreto). Il token sta cifrato.
- Coil per le immagini
- Firebase Messaging (FCM)
- WorkManager: un solo periodic work, minimo 15 minuti, che fa GET /api/items
  e GET /api/saved e aggiorna Room. Non lancia scan. Rispetta i vincoli di
  rete. Se l’utente non ha completato l’onboarding, il work non è schedulato.
- Coroutines + StateFlow. Niente RxJava.
- ApplicationId: com.arbitragesniper.app
- Lingue: values/strings.xml (inglese, default) e values-it/strings.xml
  (italiano completo). L’utente principale è italiano: ogni stringa visibile
  esiste in entrambe le lingue. Niente stringhe hardcoded nei composable.
- Tema: dark di default, light disponibile. Colori allineati alla dashboard:
  background #0B0F17, surface #131A26, primary #4F8CFF, success #22C98B,
  warning #FFB020, danger #FF5D6C. Dynamic color disattivato, così i colori
  del prodotto non cambiano col wallpaper.

SCHERMATE (tutte raggiungibili, niente placeholder)
Bottom bar: Home, Annunci, Salvati, Target. Impostazioni e Pianificazione
si aprono dalla Home (icone in top bar) e restano nel back stack.

1. Onboarding (solo al primo avvio, o se manca il token)
   - Campo base URL (validazione: http/https, niente path oltre la root)
   - Campo token (password visual toggle)
   - Pulsante "Verifica" che chiama GET /api/stats. Successo → salva e vai
     alla Home. 401 → messaggio "Token rifiutato". Rete assente → messaggio
     con il codice/timeout, nessun crash.
   - Toggle "Attiva notifiche" che chiede POST_NOTIFICATIONS (API 33+) e
     registra il token FCM solo dopo il grant.

2. Home
   - Quattro numeri: target, visti, in range, alert (da /api/stats).
   - Card schedule: modalità, intervallo, prossimo run (orario locale),
     esito ultimo run (scanned / new / alerts, oppure errore).
   - Pulsante primario "Scansiona ora".
     Stati: idle → preme → running (disabilitato, progress, testo dello
     status.message) → done oppure error. Polling GET /api/scan ogni 2 s
     mentre state==running, stop quando done|error|idle. Se 409, mostra
     "Una scansione è già in corso" e attaccati al polling dello stato.
   - Pull-to-refresh su stats + schedule.

3. Pianificazione
   - Due scelte esclusive: "Solo manuale" e "Automatico".
   - In automatico, una lista di chip con SOLO gli intervalli ammessi,
     etichette umane in italiano ("15 minuti", "30 minuti", "1 ora",
     "2 ore", "3 ore", "6 ore", "12 ore", "1 giorno").
   - Salva con PUT /api/schedule. Errore 400 mostrato inline.
   - Testo di aiuto: la scansione gira sul server anche a telefono spento;
     il telefono non scrapa.

4. Annunci
   - Lista paginata (limit 50, offset, append). Immagine, titolo, prezzo
     formattato con currency, piattaforma, badge alerted / in range /
     fuori range, gain risk-zero se presente.
   - Filtri: target, piattaforma, in range, solo alert, testo libero.
     Sort: più recenti, prezzo, guadagno. I filtri usano i query param
     già esistenti, non filtrano solo in memoria sulla pagina corrente.
   - Tap → dettaglio. Stella → PUT save. Stella piena se già salvato
     (lo sai dal set di unique_key restituito da GET /api/saved, tenuto
     in memoria dopo la sync).
   - Link: Custom Tabs. Azione "Condividi" con Intent.ACTION_SEND.
   - Vuoto, errore, loading (skeleton): tutti e tre esistono.

5. Dettaglio annuncio
   - Tutti i campi dell’item, più nota editabile se salvato.
   - Salva / rimuovi. La nota si persiste con PUT (debounce non richiesto:
     pulsante "Salva nota").
   - Se l’item è solo in cache e il server risponde 404 al save, togli la
     stella e spiega che l’annuncio non è più nello storico.

6. Salvati
   - Solo gli item in saved_items. Swipe o pulsante per DELETE save.
   - Nota visibile in seconda riga. Tap → stesso dettaglio.
   - Vuoto: testo che spiega che si salva dalla lista annunci.

7. Target
   - Lista con label e price_label.
   - Aggiungi: un campo testo che accetta le stesse forme del bot, più
     due campi numerici opzionali min/max in EUR. Esempi nel placeholder:
     "Sony A7 III", "Canon R6". I numeri vanno nel body price_min/price_max,
     non parsati due volte se l’utente ha già compilato i campi. Se i campi
     numerici sono vuoti e la query contiene un suffisso "400-700", "<900"
     o ">300", parsali come fa commands.py e manda i numeri nel JSON (non
     lasciarli dentro la query). Riusa la stessa grammatica del bot; se
     porti il parser, mettilo in un unico posto lato server
     (funzione già usata da /add) ed esponilo o chiamalo da POST /api/targets
     quando query contiene il suffisso e price_min/price_max sono null.
   - Modifica finestra inline (clear_price_min / clear_price_max per
     azzerare).
   - Elimina con conferma.
   - 409 in creazione: mostra il detail del server.

8. Sorgenti
   - Elenco provider da GET /api/providers. Switch enabled.
   - Se available=false (facebook senza cookie): switch disabilitato e
     caption "Richiede configurazione sul server".
   - POST /api/providers con la lista dei name accesi. Lista vuota non è
     ammessa lato UI: se l’utente spegne l’ultimo, ripristina e avvisa.
     (Il server tratta null/vuoto come "tutti abilitati": non mandare []
     per dire "nessuno".)

9. Impostazioni
   - Base URL, sostituisci token, tema (sistema / scuro / chiaro), lingua
     (sistema / it / en), notifiche on/off, esci (cancella token cifrato,
     cancella Room, cancella il work di sync, torna all’onboarding).
   - "Cancella visti" chiama POST /api/clear con dialog di conferma che
     spiega che la prossima scansione ri-notifica. Seconda azione
     "Cancella per testo" manda ?q=.

COMPORTAMENTO SCHEDULER VISTO DALL’APP
- "Scansiona ora" funziona sia in manuale sia in automatico.
- In automatico, il prossimo orario mostrato si aggiorna dopo PUT e dopo
  il passaggio dello scan a done/error (ri-leggi GET /api/schedule).
- Se last_status == "skipped_overlap", la Home lo dice in modo visibile
  ("ciclo saltato: la precedente era ancora in corso"), non lo tratta
  come successo.
- Nessun allarme locale che rifà lo scrape. WorkManager sincronizza solo
  la cache, anche quando la modalità è manuale.

HOSTING DEL WORKER
Aggiungi Dockerfile alla root, basato su un’immagine Python 3.12 compatibile
con Playwright (Ubuntu 22.04: su 24.04 libasound2 non si installa, è già
documentato in sniper.yml). Il container:

- installa requirements + `python -m playwright install --with-deps chromium`
- esegue `uvicorn arbitrage_sniper.web.app:app --host 0.0.0.0 --port 8000`
- monta un volume su /data
- env: DATA_DIR=/data, e fai sì che DB_PATH e THRESHOLDS_PATH rispettino
  DATA_DIR se è settata (oggi sono fissi alla root del repo in config.py:
  introduci l’override senza cambiare il default locale)
- copia thresholds.json nel volume al primo avvio se assente, non
  sovrascriverlo se già presente
- healthcheck: GET /health che risponde 200 { "ok": true } SENZA auth,
  e non fa scrape

docs/ANDROID.md spiega, in italiano:

- come costruire l’APK debug
- variabili API_BASE_URL non esiste nel binary: si inserisce in onboarding
- secret da mettere sull’host: API_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
  EBAY_APP_TOKEN opzionale, FACEBOOK_COOKIES_PATH opzionale,
  FCM_SERVICE_ACCOUNT_JSON opzionale
- come passare da GHA a worker (disattivare il cron, non i comandi Telegram:
  commands.yml può restare, ma avvisa che /scan da Telegram e lo scheduler
  condividono il lock)
- un compose di esempio con il volume /data

Non scegliere tu un provider a pagamento e non creare account. Il Dockerfile
più il compose sono il deliverable di deploy. Fly.io/Render restano una
nota, non uno script che pubblica.

TEST — BACKEND (pytest, i test vecchi restano verdi)
Aggiungi tests/test_schedule.py e tests/test_saved.py (nomi esatti):

- GET /api/schedule senza blocco nel JSON → default manual/30/enabled false
- PUT interval 30 → enabled true, next_run_at valorizzato, file JSON aggiornato
- PUT interval 10 → 400, file non cambiato
- PUT mode manual → enabled false, e lo scheduler non ha job attivi
  (verifica lo stato interno, non solo il JSON)
- due POST /api/scan concorrenti: il secondo è 409
- un tick di scheduler mentre un scan è running incrementa skipped_overlap
  e non lancia un secondo browser (mock di ScanRunner.start)
- PUT save su unique_key inesistente → 404
- PUT save con nota di 501 caratteri → 400
- PUT save poi GET /api/saved restituisce l’item con la nota
- DELETE save due volte → seconda risposta removed=0 e 200
- richiesta /api/stats senza bearer → 401
- API_TOKEN vuoto → 503
- /health senza bearer → 200

I test non aprono Playwright e non toccano la rete. Usa tmp_path per il DB
e per thresholds.json, come fanno già i test della dashboard.

TEST — ANDROID
- Test JVM del mapper di intervalli (minuti → etichetta it/en) e del parser
  della finestra di prezzo se lo duplichi sul client (meglio non duplicarlo:
  vedi la nota nel punto Target).
- Test Compose: Home con state running disabilita "Scansiona ora".
- Test Compose: Pianificazione in modalità manuale non mostra i chip come
  selezionabili per il salvataggio automatico (i chip non partono finché
  non scegli Automatico).
- Un test strumentato o Robolectric del repository: una risposta /api/saved
  finisce in Room e sopravvive a una nuova query.

Non aggiungere Maestro/Detox. Non configurare EAS. La CI GitHub del modulo
android esegue :app:testDebugUnitTest e ktlint (o detekt, uno solo). Se
l’emulatore non è disponibile in CI, i test strumentati restano locali e
documentati, non falliscono la pipeline per assenza di emulator.

DEFINITION OF DONE (tutti, nessuno escluso)
1. `python -m pytest tests/ -q` è verde, inclusi i test nuovi.
2. POST /api/scan e il job APScheduler chiamano ScanRunner e non un nuovo
   scraper.
3. Dall’app, in modalità manuale, nessuno scan parte da solo in 30 minuti
   di processo acceso (test sul contatore di start: resta 0 se non premi
   il bottone e non chiami POST).
4. Dall’app, PUT interval 15 fa partire un solo scan al tick, e un secondo
   tick sovrapposto incrementa skipped_overlap.
5. Un annuncio salvato con nota è leggibile da GET /api/saved dopo aver
   cancellato i dati dell’app e rifatto l’onboarding con lo stesso token.
6. Senza rete, Home e Salvati mostrano la cache Room e non crashano.
7. Telegram continua a ricevere gli alert. La dashboard web locale continua
   ad aprire i target e gli annunci.
8. Nessuna dipendenza Playwright nel modulo android (grep su android/ non
   deve trovare playwright, chromium, subito.it, vinted.).
9. Token assente dal repo (grep API_TOKEN= valori reali: zero). .env.example
   documenta API_TOKEN e FCM_SERVICE_ACCOUNT_JSON come vuoti.
10. README root linka docs/ANDROID_APP_PROMPT.md e docs/ANDROID.md.

FUORI SCOPE (non farli, anche se sembrano utili)
- iOS, React Native, account multipli, Postgres, billing
- storico prezzi / sparkline
- biometria
- coda offline delle scritture
- nuove fonti di scraping
- riscrittura dei selettori CSS dei provider
- pubblicazione su Play Console

ORDINE DI LAVORO (commit separati, nello stesso branch)
1. Backend: DATA_DIR, /health, auth bearer, test auth. Non rompere il default
   locale (API_TOKEN vuoto in dev locale della sola UI web su 127.0.0.1 è
   l’unica eccezione già descritta; i test coprono il 503 quando il token
   è vuoto E la richiesta non è loopback — se è più semplice, fai 503 sempre
   quando il token è vuoto e aggiorna i test esistenti. Scegli questa seconda
   opzione: 503 sempre se API_TOKEN è vuoto. La dashboard locale si usa
   settando API_TOKEN anche in .env. Aggiorna .env.example e il README della
   dashboard in un paragrafo.)
2. Backend: schedule + APScheduler + saved_items + test.
3. Backend: push register + fan-out FCM dietro interfaccia iniettabile
   (nei test un fake). Dockerfile + compose + docs/ANDROID.md.
4. Android: onboarding, Home, scan now, schedule.
5. Android: annunci, dettaglio, salvati, target, sorgenti, impostazioni, cache.
6. CI del modulo android + link nel README.

OUTPUT
Alla fine di ogni commit riassumi: cosa è cambiato, come si verifica, cosa
manca. Non dichiarare il lavoro finito se un punto del DEFINITION OF DONE è
aperto.
```

---

## Come si usa

1. Apri un agente sul repository ArbitrageSniper.
2. Incolla il blocco `prompt` così com’è, senza riassumerlo.
3. Lascialo lavorare nell’ordine dei 6 commit. Il primo rischio vero è
   l’auth che rompe i test della dashboard: il prompt gli dice di aggiornarli,
   non di spegnere il controllo.
4. Non chiedergli di scrapare dal telefono. Se propone WebView o WorkManager
   come motore di scrape, è fuori specifica: rifallo partire dal vincolo
   architetturale.

## Decisioni già prese (per non riaprirle)

| Scelta | Perché |
| --- | --- |
| Kotlin + Compose, solo Android | È il target chiesto. Il prompt React Native resta l’alternativa cross-platform. |
| Scraping sul worker Python attuale | Playwright non è un runtime Android. I provider restano quelli già scritti. |
| Frequenza sul server (APScheduler), non sul telefono | Il cron di GitHub non è modificabile dall’app, e a telefono spento un WorkManager non parte. |
| Minimo 15 minuti, valori discreti | Un run reale dura minuti e i siti vanno rispettati. Evita un campo libero che manda 1 minuto. |
| SQLite additive + Room come cache | Stesso `seen_ads.db` e stesse migrazioni ALTER. I salvati stanno sul server, quindi sopravvivono alla reinstallazione. |
| Token singolo | Tool personale. OAuth multi-utente è nel roadmap SaaS, non qui. |
| Default schedule `manual` | Un deploy nuovo non deve mettersi a scrapare finché non lo attivi tu. Il cron GHA esistente non dipende da questo flag. |
