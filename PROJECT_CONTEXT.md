# MSME Valuation Agent — Full Project Context

This document exists so that any LLM/session picking up this project later — with zero
prior conversation history — can understand exactly what was built, why, how every piece
is wired together, and what is and isn't done. It is intentionally exhaustive. If you are
an LLM reading this to make a change: read the whole thing before touching code, then go
read the specific file(s) you intend to change (this doc describes them but is not a
substitute for the source).

---

## 1. What this project is and why it exists

**Goal**: a conversational AI agent that estimates the valuation of a private Indian MSME
(micro/small/medium enterprise) by talking to the founder in natural language, then
producing a defensible valuation report — for a PPO (pre-placement offer) review / Deloitte
panel presentation context. The bar is "real and free," not "impressive-looking and fake."

**The core problem this project solves**: real-time financial data for private Indian
MSMEs does not exist through any free API — full stop. Tracxn, Venture Intelligence, CMIE
Prowash are paid (₹2–10L/year), no exceptions. What's actually free and real-time is
**listed company data** (NSE/BSE via yfinance). So the honest, defensible approach — and
the one actually used by boutique M&A advisors — is: find real listed peers in the same
sector, pull their real trading multiples (EV/EBITDA, EV/Revenue), apply those multiples to
the private company's financials, then apply a disclosed **private-company discount**
(illiquidity + lower governance/disclosure standards vs. listed peers). Every number in the
final report must be traceable to either a real peer's live data or a disclosed formula —
that traceability is the entire value proposition for an audience like a Deloitte panel.

**The one explicit architectural rule that must never be violated**: the LLM never touches
a number. It does conversation, extraction of free text into structured fields, and
narration of already-computed results. All arithmetic (multiples, discount, ranges) is
pure deterministic Python with no LLM involvement, so it's independently auditable and
unit-testable. See `app/services/valuation.py` — zero LLM calls, by design.

---

## 2. High-level architecture — 6 stages

Implemented as a single LangGraph `StateGraph` (`backend/app/agents/graph.py`), invoked
once per HTTP request (not a long-running process):

```
1. Interview Agent       (LLM)            — converses with founder, asks for missing fields
2. Profile Builder       (LLM, JSON mode) — extracts structured CompanyProfile from free text
3. Verification          (stub, no LLM)   — NOT implemented; profile always marked unverified
4. Live Peer Discovery   (deterministic)  — sector filter -> live tickers -> live yfinance pull -> similarity scoring -> top 5
5. Valuation Engine      (deterministic)  — median peer multiples -> EV -> equity value -> discount -> range
6. Report Writer         (LLM)            — narrates the already-computed numbers in plain English
```

In code, stages 1+2 are actually one LLM call (`extract_profile_node`), and stage 6 is the
LLM call inside `run_valuation_node`. There is no separate "ask_question" LLM call merged
in — see section 5 for the exact graph wiring, which is simpler than the original 6-node
mental model: 3 graph nodes, not 6.

---

## 3. Tech stack (exact versions, and *why* each was picked)

### Backend (`backend/`)
| Component | Choice | Why |
|---|---|---|
| Language | Python 3.11 (venv at `backend/.venv`) | Project uses a dedicated venv, NOT the global Python or any other project's venv (a different project `100d` had a venv that was active in the shell at session start — deliberately avoided to not pollute it) |
| Web framework | FastAPI 0.115.0 | Standard async-friendly Python API framework, trivial CORS setup for a separate frontend |
| Server | uvicorn 0.30.6 | Standard ASGI server for FastAPI |
| Validation | Pydantic 2.9.2 | All data models (`CompanyProfile`, `PeerCompany`, `ValuationResult`, etc.) |
| Orchestration | LangGraph 0.2.39 + langchain-core 0.3.10 | Explicit state machine for the interview-loop-then-pipeline flow, conditional edges for "ask more questions vs. proceed to valuation" |
| LLM | `openai` 1.68.2 with Groq OpenAI-compatible API | Free tier requested by user. **Model: `llama-3.3-70b-versatile`** (configurable via `GROQ_MODEL`) |
| Market data | `yfinance` **>=1.4.1** (upgraded from initial 0.2.43 pin) | Free, real, live financials for any NSE-listed ticker via Yahoo Finance |
| HTTP | `requests` 2.32.3 | Underlies yfinance's fallback backend and the NSE scraper |
| SSL fix | `pip-system-certs` (latest) | See section 7 — mandatory on this network |
| Testing | pytest 8.3.3 | Deterministic unit tests for valuation math and sector classification |

### Frontend (`frontend/`)
| Component | Choice | Why |
|---|---|---|
| Build tool | Vite **5.4.21** (pinned `^5.4.11` in package.json) | `create-vite` initially scaffolded Vite 8 (rolldown-based, bleeding edge) which **failed to run** — broken native binding (`@rolldown/binding-win32-x64-msvc` missing) and requires Node 22.12+ while this machine has Node 22.11.0. Downgraded to stable Vite 5. |
| UI framework | React 19.2.7 + TypeScript | User-specified |
| Plugin | `@vitejs/plugin-react` **^4.3.4** (downgraded from `^6.0.2`) | v6 targets newer Vite; paired with Vite 5 for compatibility |
| Styling | Tailwind CSS v4 via `@tailwindcss/vite` plugin | User-specified ("React + Tailwind"), v4's Vite plugin avoids a separate PostCSS config file |
| Markdown | `react-markdown` ^10.1.0 | Added after initial build — the Gemini report narrative uses markdown headings (`## Valuation Report...`) and was rendering as literal text; this renders it properly |
| Node runtime | Node v22.11.0, npm 10.9.0 | Pre-existing on the machine; note Vite 5.4.21 and most tooling works fine on it, only Vite 8 demanded 22.12+ |

### Why NOT curl_cffi (yfinance's preferred backend)
`yfinance` prefers `curl_cffi` (browser TLS impersonation, avoids Yahoo rate-limiting/blocking).
It was tried, but its **bundled CA store is separate from the OS/Python trust store** and isn't
trusted on this network (see section 7). Fix: `YF_DISABLE_CURL_CFFI=1` env var (yfinance
respects this natively, no need to even uninstall the package) forces yfinance onto plain
`requests`, which IS patched to trust the system store via `pip-system-certs`. Set in
`backend/app/config.py` via `os.environ.setdefault(...)` before any yfinance import.

---

## 4. Directory structure and what every file does

```
val/
├── .gitignore                      — excludes .venv, .env, node_modules, __pycache__, etc.
├── .claude/settings.json           — permission allowlist for narrow safe dev commands
│                                      (pytest, uvicorn, npm install/dev/build, localhost curl).
│                                      Explicitly does NOT wildcard python/node interpreters
│                                      (arbitrary code execution risk) — see section 9.
├── system-ca-bundle.pem            — combined certifi + Windows cert-store PEM, used to fix
│                                      npm/node TLS on this network (NODE_EXTRA_CA_CERTS).
│                                      NOT committed-worthy long-term but currently present
│                                      at repo root; regenerate per-machine if missing (see
│                                      section 7 for the exact generation command).
├── README.md                       — quick run instructions + environment-fix summary
├── PROJECT_CONTEXT.md              — this file
│
├── backend/
│   ├── .venv/                     — dedicated Python 3.11 venv (NOT committed; gitignored)
│   ├── .env                       — GROQ_API_KEY=... (gitignored, contains the local key)
│   ├── .env.example               — template, key blank
│   ├── requirements.txt           — pinned deps, see section 3 table
│   ├── server.log                 — uvicorn output when run with `> server.log 2>&1 &`
│   ├── app/
│   │   ├── main.py                — FastAPI app instance, CORS (allows localhost:5173),
│   │   │                            mounts routers, GET /api/health
│   │   ├── config.py              — loads .env via python-dotenv; sets YF_DISABLE_CURL_CFFI=1;
│   │   │                            exposes GROQ_API_KEY, GROQ_MODEL, PRIVATE_COMPANY_DISCOUNT (0.25),
│   │   │                            TOP_N_PEERS (5)
│   │   ├── models.py              — Pydantic models: ChatTurn, CompanyProfile (with
│   │   │                            `.ebitda_margin` property and `.missing_required_fields()`
│   │   │                            method — required fields are company_name, sector,
│   │   │                            revenue_cr, ebitda_cr, debt_cr, city), PeerCompany,
│   │   │                            ValuationRange, ValuationResult, SessionState
│   │   ├── session_store.py       — in-memory dict (`_sessions: dict[str, SessionState]`),
│   │   │                            NO database, NO persistence across server restarts.
│   │   │                            create_session/get_session/save_session.
│   │   ├── agents/
│   │   │   ├── gemini_client.py   — thin Groq-backed OpenAI-compatible client, MODEL_NAME =
│   │   │   │                        "llama-3.3-70b-versatile" by default, generate_text(prompt)->str,
│   │   │   │                        generate_json(prompt)->dict, QuotaExceededError exception class,
│   │   │   │                        retries disabled to avoid burning quota on auto-retries
│   │   │   ├── prompts.py         — 3 prompt templates: EXTRACTION_PROMPT (conversation ->
│   │   │   │                        JSON profile fields), NEXT_QUESTION_PROMPT (profile +
│   │   │   │                        missing fields -> next natural-language question),
│   │   │   │                        REPORT_PROMPT (profile + peers + computed valuation ->
│   │   │   │                        markdown report; explicitly told not to recalculate numbers)
│   │   │   └── graph.py           — THE ORCHESTRATOR. GraphState TypedDict: history (list of
│   │   │                            {role, content} dicts), profile (dict), stage, 
│   │   │                            assistant_message, report. 3 nodes:
│   │   │                              - extract_profile_node: skips if history empty,
│   │   │                                otherwise calls generate_json(EXTRACTION_PROMPT) and
│   │   │                                merges non-null extracted fields into profile
│   │   │                              - ask_question_node: calls generate_text on
│   │   │                                NEXT_QUESTION_PROMPT, sets stage="interview"
│   │   │                              - run_valuation_node: classify_sector -> discover_peers
│   │   │                                -> compute_valuation -> generate_text(REPORT_PROMPT)
│   │   │                                -> sets stage="report_ready", builds report dict
│   │   │                            Routing: route_after_extract checks
│   │   │                            CompanyProfile(**profile).missing_required_fields() —
│   │   │                            if any missing -> ask_question, else -> run_valuation.
│   │   │                            get_graph() lazily compiles and caches a module-level
│   │   │                            singleton.
│   │   ├── services/
│   │   │   ├── valuation.py       — PURE DETERMINISTIC, NO LLM, NO NETWORK. compute_valuation
│   │   │   │                        (profile, peers) -> ValuationResult. Logic: collect
│   │   │   │                        ev_ebitda and ev_revenue lists from peers (only positive,
│   │   │   │                        non-null values); median EV/EBITDA preferred, falls back
│   │   │   │                        to median EV/Revenue if no EBITDA multiples; EV = median
│   │   │   │                        multiple × target metric; equity_pre_discount = EV - debt;
│   │   │   │                        equity_post_discount = equity_pre_discount × (1 -
│   │   │   │                        PRIVATE_COMPANY_DISCOUNT); range computed using P25/P75
│   │   │   │                        peer multiples (custom `_percentile` linear-interpolation
│   │   │   │                        function, no numpy dependency) through the same
│   │   │   │                        debt-subtract-then-discount formula. Every step appends a
│   │   │   │                        human-readable string to `methodology_notes` — this is the
│   │   │   │                        audit trail shown in the UI. Returns early with an empty
│   │   │   │                        result + explanatory note if no usable peer multiples or
│   │   │   │                        target financials exist.
│   │   │   ├── yfinance_service.py — fetch_financials(ticker, retries=2, delay_seconds=1.5) ->
│   │   │   │                        PeerFinancials | None. Wraps yf.Ticker(ticker).info, pulls
│   │   │   │                        marketCap/totalRevenue (converted rupees->crores via
│   │   │   │                        CR_PER_RUPEE = 1/1e7), enterpriseToEbitda,
│   │   │   │                        enterpriseToRevenue, ebitdaMargins, shortName/longName.
│   │   │   │                        Catches ALL exceptions (yfinance raises varied types),
│   │   │   │                        retries with delay, logs+returns None on persistent failure
│   │   │   │                        (e.g. invalid ticker -> Yahoo 404).
│   │   │   ├── nse_scraper.py     — get_peer_candidates(sector_tag) -> list[PeerCandidate].
│   │   │   │                        Tries _try_live_scrape() first: requests.Session(), GET
│   │   │   │                        nseindia.com/market-data/sme-emerge with full browser
│   │   │   │                        headers, then GET the unofficial
│   │   │   │                        /api/equity-stockIndices?index=SME%20EMERGE endpoint.
│   │   │   │                        **CONFIRMED BLOCKED** in this environment — nseindia.com
│   │   │   │                        runs Akamai Bot Manager (cookies AKA_A2/_abck/bm_sz
│   │   │   │                        observed; returns a JS-obfuscated "Resource not found"
│   │   │   │                        challenge page, not real 404s) — see section 7 for the
│   │   │   │                        actual diagnostic output. On any failure, falls back to
│   │   │   │                        _FALLBACK_SEED_LIST: a hardcoded dict of 5 sectors
│   │   │   │                        (Textiles, Pharma, Engineering, FMCG, Chemicals) each
│   │   │   │                        with 5-8 real NSE tickers, EVERY ONE individually
│   │   │   │                        validated live against yfinance before being hardcoded
│   │   │   │                        (29/30 candidates passed; SUVENPHAR.NS was dropped — see
│   │   │   │                        section 7 for the validation run). The ticker *list* is
│   │   │   │                        static in the fallback case; financials are still always
│   │   │   │                        pulled live.
│   │   │   └── peer_discovery.py  — DETERMINISTIC orchestration tying the above together.
│   │   │                            SECTOR_KEYWORDS: dict mapping free-text substrings (e.g.
│   │   │                            "textile", "yarn", "fmcg", "chemical") to the 5 internal
│   │   │                            sector tags. classify_sector(raw_text) does substring
│   │   │                            matching (lowercased), returns None if no match.
│   │   │                            discover_peers(profile): classify sector -> get candidate
│   │   │                            tickers from nse_scraper -> fetch_financials per ticker
│   │   │                            (skip if fetch fails) -> compute _similarity_score per
│   │   │                            peer (lower = more similar; sums a normalized revenue-gap
│   │   │                            term + an EBITDA-margin-gap term, each defaulting to a
│   │   │                            penalty value when data is missing) -> sort ascending ->
│   │   │                            return top TOP_N_PEERS (5).
│   │   └── routes/
│   │       ├── session.py         — POST /api/session: creates a SessionState, invokes the
│   │       │                        graph ONCE with empty history to get the opening greeting
│   │       │                        message (this is how the bot "speaks first" without
│   │       │                        needing a user message), catches QuotaExceededError with a
│   │       │                        canned fallback greeting, stores message in session
│   │       │                        history, returns {session_id, message}.
│   │       └── chat.py            — POST /api/chat {session_id, message}: 404 if session
│   │                                unknown; appends user ChatTurn to history; builds graph
│   │                                state from session; invokes graph; on QuotaExceededError,
│   │                                POPS the just-appended user message back off (so it isn't
│   │                                stuck waiting for a reply that never came) and returns a
│   │                                friendly rate-limit message instead of crashing; otherwise
│   │                                updates session.profile/.stage/.history/.report and
│   │                                returns {stage, message, profile, report}.
│   └── tests/
│       ├── test_valuation.py      — 5 tests, all pure (no network/LLM): basic EV/EBITDA
│       │                            valuation against hand-checked numbers; debt subtracted
│       │                            before discount; falls back to EV/Revenue when no EBITDA
│       │                            multiples exist; returns empty result gracefully when no
│       │                            peer has any usable multiple; returns no enterprise value
│       │                            when target profile itself lacks financials.
│       └── test_peer_discovery.py — 2 tests: classify_sector keyword matching; similarity
│                                    score ordering (closer peer scores lower than a wildly
│                                    different one).
│
└── frontend/
    ├── index.html                 — title "MSME Valuation Assistant"
    ├── vite.config.ts             — react() + tailwindcss() plugins; dev server proxies
    │                                /api/* to http://localhost:8000 (avoids CORS entirely
    │                                in dev — FastAPI's CORS config is effectively only a
    │                                backstop, not load-bearing in the dev proxy path)
    ├── package.json               — see section 3 table for pinned versions
    └── src/
        ├── main.tsx                — standard React 19 createRoot bootstrap (untouched
        │                              from scaffold apart from CSS import)
        ├── index.css               — `@import "tailwindcss";` + `body { margin: 0; }` —
        │                              replaced the entire create-vite v9 default boilerplate
        │                              (custom CSS vars, the whole landing-page styling)
        ├── App.tsx                 — root component. On mount, calls createSession(), stores
        │                              session_id + the opening greeting as the first message.
        │                              Renders EITHER the ChatWindow (while no report exists)
        │                              OR the ReportView (once a report arrives) — never both,
        │                              simple state-driven view switch, no router.
        ├── api/
        │   └── client.ts           — TypeScript interfaces mirroring the backend Pydantic
        │                              models EXACTLY field-for-field (PeerCompany,
        │                              ValuationRange, CompanyProfile, ValuationReport,
        │                              ChatResponse) + createSession()/sendMessage() fetch
        │                              wrappers hitting /api/session and /api/chat
        └── components/
            ├── MessageBubble.tsx   — role-based styling: user = indigo bg, right-aligned;
            │                          assistant = gray bg, left-aligned
            ├── ChatWindow.tsx      — owns local message list state (seeded from
            │                          initialMessages prop), auto-scrolls to bottom on new
            │                          message, Enter-to-send, disables input while a request
            │                          is in flight, shows a "Thinking..." bubble during the
            │                          wait, calls onReportReady(response) callback when
            │                          stage === 'report_ready'
            └── ReportView.tsx      — renders the final ValuationReport: headline range box
                                       (indigo), verification disclosure box (amber if
                                       unverified / green if verified — currently ALWAYS amber
                                       since verification is unimplemented), the LLM narrative
                                       via <ReactMarkdown>, a peer table (ticker/name/EV-EBITDA/
                                       EV-Revenue/margin/source), and the methodology_notes
                                       audit trail as a bulleted list with left-border styling
```

---

## 5. End-to-end data flow (one full conversation)

1. Frontend mounts -> `POST /api/session` -> backend creates `SessionState` (empty
   `CompanyProfile`, empty history) -> invokes graph with empty history -> 
   `extract_profile_node` no-ops (history empty) -> routes to `ask_question_node` (profile
   is all-None, so all required fields are "missing") -> LLM writes an opening greeting
   asking for company name + sector -> stored as first assistant `ChatTurn` -> returned to
   frontend as `{session_id, message}`.
2. User types an answer in `ChatWindow` -> `POST /api/chat {session_id, message}`.
3. Backend appends the user message to `session.history`, builds `graph_state` from the
   **entire** history + current profile dict, invokes the graph.
4. `extract_profile_node`: re-serializes the *whole* conversation to text, sends it through
  `EXTRACTION_PROMPT` (asks the LLM to extract ALL fields it can confidently determine from
   the full conversation, not just the latest message — this is deliberately re-extractive
   rather than incremental, which is simpler and self-correcting for short interviews).
   Non-null extracted fields overwrite the corresponding profile dict keys.
5. `route_after_extract`: builds a `CompanyProfile` from the updated dict, checks
   `missing_required_fields()`. If anything is still missing -> `ask_question_node` (asks
   for 1-2 more fields conversationally) -> graph ends, turn returns to user.
6. Once all 6 required fields are present (company_name, sector, revenue_cr, ebitda_cr,
   debt_cr, city) -> `run_valuation_node` fires:
   a. `classify_sector(profile.sector)` — keyword match against free text into one of 5 tags
   b. `discover_peers(profile)` — live tickers (scrape attempt, falls back to seed list) ->
      live yfinance pull per ticker -> similarity score -> top 5
   c. `compute_valuation(profile, peers)` — pure math, produces `ValuationResult` with a
      full `methodology_notes` audit trail
  d. `REPORT_PROMPT` sent to the LLM with the profile, peers, and **already-computed**
      valuation JSON, explicitly instructed not to alter any numbers — returns markdown narrative
   e. `stage` set to `"report_ready"`, `report` dict = `result.model_dump()` + `narrative` key
7. Backend updates `session.profile`/`.stage`/`.history`/`.report`, returns
   `{stage, message, profile, report}` to frontend.
8. `ChatWindow` sees `stage === 'report_ready'` and calls `onReportReady`, which lifts the
   report up to `App.tsx`, which swaps the view from `ChatWindow` to `ReportView`.

---

## 6. Required CompanyProfile fields (drives the interview loop)

From `models.py`, `CompanyProfile.missing_required_fields()` checks exactly these 6 — the
interview continues looping until ALL are non-null:
- `company_name`, `sector`, `revenue_cr`, `ebitda_cr`, `debt_cr`, `city`

Optional/not gating completion: `years_operating`, `business_model`, `gstin`,
`nse_sector_tag` (this last one is set programmatically by `classify_sector`, never asked
of the user).

`ebitda_margin` is a computed `@property` (ebitda_cr / revenue_cr), not a stored field.

---

## 7. Environment quirks discovered this session — read before debugging "it doesn't work"

This network runs a **TLS-inspecting proxy**. Every TLS stack that doesn't trust the
Windows OS certificate store fails with `CERTIFICATE_VERIFY_FAILED` / `unable to get local
issuer certificate`. This single root cause manifested differently in 4 different tools:

1. **pip**: fixed per-invocation with `--trusted-host pypi.org --trusted-host
   files.pythonhosted.org --trusted-host pypi.python.org` (skips verification for those 3
   hosts only — used for every `pip install` in this project).
2. **Python's `ssl`/`requests` (used by yfinance's fallback backend, and by the NSE
   scraper)**: fixed persistently by installing `pip-system-certs`, which monkey-patches
   `ssl.SSLContext` to pull trust from the Windows certificate store at runtime. One-time
   `pip install`, no code changes needed afterward.
3. **curl_cffi (yfinance's preferred backend)**: NOT fixed by `pip-system-certs` — it
   bundles its own CA store independent of Python's `ssl` module. Worked around instead by
   forcing yfinance to skip curl_cffi entirely: `os.environ.setdefault("YF_DISABLE_CURL_CFFI",
   "1")` in `app/config.py` (yfinance's own `_http.py` reads this env var and falls back to
   plain `requests`, which IS covered by fix #2).
4. **Groq/OpenAI REST client**: relies on HTTPS requests and the Windows trust store.
  Python-side TLS problems are handled by `pip-system-certs`; the Groq client in
  `gemini_client.py` uses the OpenAI-compatible REST API directly.
5. **npm/Node** (separate problem, same root cause): Node bundles its own CA list too.
   Fixed by exporting a combined PEM (certifi's public CAs + the Windows ROOT/CA stores, via
   Python's `ssl.enum_certificates`) to `system-ca-bundle.pem` at the repo root, then setting
   `NODE_EXTRA_CA_CERTS=<path to that file>` before any `npm install`/`npm run dev`/`npm run
   build` invocation. Exact generation command used:
   ```python
   import ssl, certifi
   with open('system-ca-bundle.pem', 'w', encoding='ascii') as f:
       f.write(open(certifi.where(), encoding='ascii').read())
       for store in ('CA', 'ROOT'):
           for cert_der, encoding, trust in ssl.enum_certificates(store):
               if encoding == 'x509_asn':
                   f.write(ssl.DER_cert_to_PEM_cert(cert_der))
   ```
   (Originally tried Node 24's `--use-system-ca` flag first — **not available in Node
   22.11.0**, hence the manual PEM export instead.)

**If you move this project to a different machine/network without this proxy, none of
fixes #2-5 will be harmful (they're inert if there's nothing to work around), but you can
remove them if you want a "cleaner" setup. Fix #1 (pip --trusted-host) would simply not be
needed anymore.**

### NSE live scrape — confirmed blocked, not a bug

Diagnostic evidence from this session: a request to
`https://www.nseindia.com/market-data/sme-emerge` with full browser headers returned cookies
`AKA_A2`, `_abck`, `bm_sz` (Akamai Bot Manager signatures) and a body that is a JS-obfuscated
"Resource not found" page — i.e. Akamai's bot-challenge page, not a genuine 404. This means
nseindia.com actively blocks non-browser HTTP clients regardless of headers. This is true in
production too, not just this sandbox — real systems that need NSE's SME list either run a
real headless browser with stealth plugins (adversarial, fragile, ToS-questionable — NOT
pursued here) or pay for a data vendor. The fallback seed list is therefore not a workaround
for *this session's* limitations — it's the realistic permanent behavior of this
architecture. `nse_scraper.py`'s docstring says this explicitly.

### Groq rate limits — still relevant on free usage

The configured key (see `backend/.env`, NOT committed to git but present on disk) can still
hit provider-side rate limits if the app is exercised heavily. The current default model is
`llama-3.3-70b-versatile` via `GROQ_MODEL`, and the setting remains configurable so the app
can be adjusted without code changes if quota or rate-limit behavior changes.

The app handles quota exhaustion gracefully (see `gemini_client.QuotaExceededError`,
caught in both `routes/session.py` and `routes/chat.py`) — it does NOT crash with a 500, it
returns a clear "rate limited" message in the chat. Retries are explicitly disabled in
`gemini_client.py` so a single logical app call does not spiral into repeated quota usage.

---

## 8. Design decisions and the reasoning behind them (so future changes don't undo intent)

- **Why in-memory session store, no database**: explicit MVP choice — conversation state is
  ephemeral and small; adding Postgres/Redis would be infrastructure for infrastructure's
  sake at this stage. Restarting the backend loses all sessions; that's accepted, not a bug.
- **Why static seed list AND live scrape attempt, not just one**: the user was explicitly
  warned that NSE has no official free API and was asked to choose; they chose "live scrape
  primary" specifically so the architecture's *claim* of being live remains true and
  testable, with the seed list only as a safety net — not because the team expected the
  scrape to actually succeed against Akamai.
- **Why GST/MCA verification is unimplemented rather than faked**: the user was told plainly
  that free GST/MCA verification APIs don't realistically exist without paid GSP/third-party
  access, and chose to disclose this honestly (`verified: false`, `verification_note` shown
  in every report) rather than build something fragile or misleading. Do not "complete" this
  by wiring up a sketchy scraping-based GST checker without raising it with the user first —
  this was a deliberate scope cut, not an oversight.
- **Why the interview LLM call re-extracts the WHOLE conversation every turn** rather than
  incrementally merging just the latest message: simpler (no incremental-merge logic to get
  wrong), and self-correcting if the founder corrects an earlier answer later in the
  conversation. Trade-off: slightly more tokens per call, irrelevant given the tiny
  conversation lengths involved (a handful of turns).
- **Why `_similarity_score` is a simple additive formula, not anything fancier**: it only
  needs to rank peers, not produce a calibrated probability — and it needs to be in plain
  Python so it's part of the "deterministic, auditable" half of the system, same constraint
  that keeps the LLM away from `valuation.py`.
- **Why the EV/Revenue fallback exists in `compute_valuation`**: not every NSE peer reports
  a sane EV/EBITDA (e.g. negative/near-zero EBITDA companies), so relying solely on
  EV/EBITDA could leave zero usable peers for some sectors. EV/Revenue is the standard
  secondary multiple in real valuation practice.
- **Why the frontend has no router/multiple pages**: there are exactly two views (chat,
  report) and they're mutually exclusive within one session — a router would be unjustified
  complexity for two `if` branches in `App.tsx`.

---

## 9. Things explicitly NOT done (don't assume they exist)

- No GST/MCA verification (see above) — `verified` is hardcoded `false` everywhere it's
  constructed in `models.py`'s default.
- No persistence beyond process lifetime (no DB).
- No auth/multi-tenancy — anyone with a session_id can chat in it; there's no user accounts.
- No retry/backoff UI for the rate-limit case beyond the one canned message — the user has
  to manually resend after waiting.
- No automated frontend tests (no Vitest/Jest/RTL) — verification so far has been: backend
  pytest (deterministic logic) + manual Playwright-driven screenshots (see section 10) for
  the UI, run once during the initial build, not wired into CI.
- No CI/CD pipeline, no deployment config (no Dockerfile, no Railway/Render config despite
  being mentioned as options in early planning) — this is local-dev-only as of this writing.
- `.claude/settings.json` permission allowlist deliberately does NOT include wildcards for
  any interpreter (`python`, `node`, etc.) — granting that would be equivalent to blanket
  arbitrary-code-execution approval. Only narrow, fixed-shape commands (pytest invocation,
  uvicorn startup, npm install/dev/build, localhost curl) are allowlisted.

---

## 10. How this was verified (so you know what "working" actually means here)

- `backend/tests/`: 7 pytest unit tests, all passing, cover `valuation.py` math and
  `peer_discovery.py`'s sector classification + similarity ordering. Zero network/LLM calls
  in these tests — they're pure-function tests.
- Live data pull verified manually against real tickers (TCS.NS, SUTLEJTEX.NS,
  NITINSPIN.NS, and 27 others during seed-list curation) — confirmed real company names,
  multiples, and financials returned.
- Full pipeline (interview -> extraction -> peer discovery -> valuation -> report) run
  end-to-end via a throwaway script simulating a 4-turn founder conversation (textile
  company, Surat) — reached a complete report with real peer tickers (Nitin Spinners,
  Trident, Vardhman Textiles, KPR Mill, RSWM) and a coherent audit trail. Script was deleted
  after use (not part of the repo).
- HTTP layer verified via `curl` against the running `uvicorn` server: `/api/health`,
  `/api/session`, `/api/chat` (including the graceful quota-exceeded path, which returns
  HTTP 200 with a friendly message, not a 500).
- Frontend verified via a headless-Chromium Playwright script (using the machine's existing
  installed Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe` via
  `playwright-core`, avoiding a fresh Chromium download) driving the real dev server at
  `localhost:5173` proxying to the real backend at `localhost:8000`. Screenshots confirmed:
  chat UI renders and accepts input, message bubbles style correctly, and (via a temporary
  mock-data preview page, since live LLM testing was blocked by quota that day) the
  `ReportView` component renders the valuation range, verification disclosure, markdown
  narrative, peer table, and audit trail correctly. The temporary preview files
  (`report-preview.html`, `src/report-preview.tsx`) and the scratch verification folder were
  deleted/cleaned up after use — they are NOT part of the repo. If you need to re-verify
  `ReportView` visually without live LLM calls, recreate a similar mock-data harness rather
  than expecting one to already exist.
- `npm run build` (TypeScript + Vite production build) confirmed clean, zero type errors.

---

## 11. Quick reference: how to extend this safely

- **Adding a new sector**: add an entry to both `SECTOR_KEYWORDS` (peer_discovery.py, maps
  free-text keywords to a tag) and `_FALLBACK_SEED_LIST` (nse_scraper.py, maps the same tag
  to real tickers). Validate every new ticker against live yfinance before hardcoding it —
  follow the pattern used originally (a throwaway validation script looping over candidates,
  printing OK/FAIL, dropping failures) rather than guessing ticker symbols.
- **Swapping the LLM model**: change `GROQ_MODEL` in `backend/.env` or
  `backend/.env.example`.
- **Implementing real GST/MCA verification**: would touch `models.py`'s `verified`/
  `verification_note` defaults, add a new service module under `app/services/`, and a new
  graph node between `extract_profile_node` and `run_valuation_node` — but raise this with
  the user first, since the "honest disclosure over fake verification" stance was a
  deliberate choice, not a placeholder waiting to be filled in.
- **Persisting sessions to a real DB**: replace `session_store.py`'s dict with whatever
  store you choose — `SessionState` is already a clean Pydantic model, so serialization is
  straightforward; nothing else in the codebase should need to change.
