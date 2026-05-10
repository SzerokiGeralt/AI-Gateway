# AI Gateway

## Architektura

AI Gateway to bramka pośrednicząca między UI chat a Anthropic API, wzbogacona o **dwuwarstwową
lokalną warstwę DLP**. Każdy prompt zalogowanego użytkownika jest analizowany w pełni lokalnie:

1. **Warstwa 1 — deterministyczna**: Microsoft Presidio + polskie recognizery z walidacją sum
   kontrolnych (PESEL, NIP, REGON, IBAN PL, dowód osobisty) + pakiet wzorców sekretów (klucze
   AWS/GCP/OpenAI/Anthropic, tokeny GitHub/Slack, JWT, klucze prywatne, hasła w przypisaniach).
   Wykryte fragmenty są podmieniane na placeholdery `[REDACTED:<TYP>]`.
2. **Warstwa 2 — embedding similarity** (`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`,
   ~970 MB, CPU): liczy cosine similarity między promptem a etykietami zakazanych tematów
   z polityki admina. Score > progu ⇒ cała wiadomość zastępowana placeholderem (block-all).
   Deterministyczne, bez halucynacji modelu — jeśli prompt nie jest semantycznie blisko
   żadnej etykiety, score wyjdzie niski.

Wykryte naruszenia są logowane jako incydenty (z oryginalną treścią dostępną tylko w bazie),
a do zespołu bezpieczeństwa idzie alert mailowy w tle. Bezpieczna wersja promptu trafia
dalej streamem SSE do Anthropic Claude. Cała aplikacja stoi na FastAPI + SQLAlchemy 2.0
async, sesje JWT są walidowane przez Redis (umożliwia twardy logout), a komponenty
infrastrukturalne (PostgreSQL, Redis) są skonteneryzowane.

Awaria którejkolwiek warstwy DLP skutkuje **fail-closed** — prompt zwraca HTTP 503,
nigdy nie trafia niezweryfikowany do zewnętrznego API.

## Wymagania wstępne

- Docker 24+ i Docker Compose v2
- Wolne porty: **8000** (aplikacja); pozostałe usługi (db, redis) zostają w sieci wewnętrznej
- Klucz API do Anthropic (`sk-ant-...`)
- ~1.5 GB miejsca na modele DLP (`pl_core_news_md` + `paraphrase-multilingual-mpnet-base-v2`,
  pre-pobierane w trakcie `docker compose build`)

## Quick start

```bash
# 1. Skopiuj i uzupełnij konfigurację
cp .env.example .env
# Wygeneruj losowy JWT_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Wpisz wygenerowany ciąg do .env (pole JWT_SECRET_KEY)
# Wpisz swój ANTHROPIC_API_KEY
# (opcjonalnie) ustaw INITIAL_ADMIN_PASSWORD na coś własnego

# 2. Uruchom cały stos
docker compose up -d --build

# 3. Sprawdź health
curl http://localhost:8000/health

# 4. Pierwsze logowanie
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ChangeMeNow!"}'
```

Pierwsze konto administratora jest tworzone automatycznie przy pierwszym starcie aplikacji
(zmienne `INITIAL_ADMIN_USERNAME` i `INITIAL_ADMIN_PASSWORD` w `.env`). Po pierwszym
logowaniu **zmień hasło** przez `PATCH /admin/users/{id}` lub załóż nowego admina i usuń
seedowanego.

Modele DLP (spaCy `pl_core_news_md` + `paraphrase-multilingual-mpnet-base-v2`) są pobierane jednorazowo
podczas `docker compose build` (~1.5 GB). Pierwszy `up` jest dłuższy o czas warmupu modeli
przy starcie aplikacji (~3–8 s).

## Endpointy API

| Metoda | Ścieżka                  | Auth      | Opis                                                     |
|--------|--------------------------|-----------|----------------------------------------------------------|
| POST   | `/auth/login`            | —         | Logowanie, zwraca JWT i zakłada sesję w Redis            |
| POST   | `/auth/logout`           | Bearer    | Unieważnia sesję (czyści klucze `session:*`, `chat_history:*`) |
| GET    | `/me`                    | Bearer    | Informacje o zalogowanym użytkowniku                     |
| GET    | `/health`                | —         | Health check                                             |
| POST   | `/chat/completions`      | Bearer    | Czat — DLP → Anthropic, odpowiedź jako SSE               |
| GET    | `/admin/users`           | Admin     | Lista użytkowników (paginacja: `skip`, `limit`)          |
| POST   | `/admin/users`           | Admin     | Tworzy użytkownika                                       |
| PATCH  | `/admin/users/{id}`      | Admin     | Aktualizuje (`role`, `department`, `password`)           |
| DELETE | `/admin/users/{id}`      | Admin     | Usuwa użytkownika                                        |
| POST   | `/admin/policy`          | Admin     | Upload polityki DLP (multipart, pole `file`, .txt)       |
| GET    | `/admin/incidents`       | Admin     | Lista incydentów (paginacja: `skip`, `limit`)            |

Pełna interaktywna dokumentacja: `http://localhost:8000/docs`.

## Jak załadować politykę DLP

Polityka jest plikiem markdown zapisanym jako `.txt` z **wymaganymi sekcjami**. Klasyfikator zero-shot bierze
bullety z sekcji `# Tematy zabronione` jako etykiety NLI.

**Wzor pliku policy.txt**
- Sekcje to naglowki markdown (`# ...`).
- Lista tematow to bullety (`- ...`).
- Wymagana jest sekcja `# Tematy zabronione` z co najmniej jednym bullet pointem.
- Sekcje `# Tematy dozwolone` i `# Opis` sa opcjonalne.

**Jak dziala parsowanie**
- Parser rozpoznaje naglowki po slowach kluczowych (np. `zabronione`, `dozwolone`, `allowed`, `forbidden`).
- Bullety pod `# Tematy zabronione` trafiaja do listy zakazanych tematow.
- Bullety pod `# Tematy dozwolone` sa zapisywane, ale obecnie nie wplywaja na decyzje DLP.
- Tresc poza sekcjami trafia do opisu (informacyjnie).

```bash
# Plik markdown z polityką zapisany jako .txt
cat > company_policy.txt <<'EOF'
# Tematy zabronione
- numery PESEL, NIP, dowodów osobistych
- dane klientów (imię + nazwisko + dane kontaktowe)
- kod źródłowy oznaczony jako CONFIDENTIAL
- plany strategiczne i finansowe przed publikacją

# Tematy dozwolone
- ogólne pytania techniczne
- brainstorming
- pomoc w pisaniu nieobjętym tajemnicą

# Opis
Polityka bezpieczeństwa firmy ACME — wersja 1.0.
EOF

# Uzyskaj token admina
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ChangeMeNow!"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Załaduj politykę (.txt z markdown wewnątrz)
curl -X POST http://localhost:8000/admin/policy \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@company_policy.txt"
```

Walidacja: brak sekcji `# Tematy zabronione` z co najmniej jednym bulletem zwraca **HTTP 400**.
Każdy nowy upload tworzy nowy rekord — system zawsze używa **najnowszej** wersji.

## Wysłanie testowego promptu

```bash
TOKEN=...
curl -N -X POST http://localhost:8000/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Wyjaśnij prosto czym jest LLM"}]}'
```

Odpowiedź to strumień SSE — fragmenty `data: ...` zakończone `data: [DONE]`.

## Zmienne środowiskowe

| Nazwa                    | Opis                                                       | Default                          |
|--------------------------|------------------------------------------------------------|----------------------------------|
| `APP_NAME`               | Nazwa aplikacji wyświetlana w `/health`                    | `AI Gateway`                     |
| `APP_ENV`                | Środowisko (`development` / `production`)                  | `development`                    |
| `DEBUG`                  | Tryb debug + verbose SQL log                               | `false`                          |
| `ALLOWED_ORIGINS`        | Lista origins CORS (po przecinku)                          | `http://localhost:3000`          |
| `JWT_SECRET_KEY`         | Sekret HMAC do JWT (min. 32 znaki, wygeneruj losowo)       | **brak — wymagane**              |
| `JWT_ALGORITHM`          | Algorytm podpisu JWT                                       | `HS256`                          |
| `JWT_EXPIRE_MINUTES`     | TTL access tokenu (minuty); jednocześnie TTL sesji w Redis | `60`                             |
| `DATABASE_URL`           | DSN PostgreSQL (`postgresql+asyncpg://...`)                | **wymagane** (compose ustawia)   |
| `REDIS_URL`              | URL Redis (`redis://host:port/db`)                         | `redis://redis:6379/0`           |
| `ANTHROPIC_API_KEY`      | Klucz API Anthropic                                        | **wymagane**                     |
| `ANTHROPIC_MODEL_NAME`   | Model Claude używany do odpowiedzi                         | `claude-sonnet-4-5`              |
| `DLP_CLASSIFIER_MODEL`   | Encoder dla warstwy 2 (sentence-transformers)              | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` |
| `DLP_CLASSIFIER_THRESHOLD` | Próg cosine similarity (0.0–1.0)                         | `0.55`                           |
| `SMTP_HOST`              | Host SMTP do alertów (puste = wyłączone)                   | *(puste)*                        |
| `SMTP_PORT`              | Port SMTP                                                  | `587`                            |
| `SMTP_USER`              | Użytkownik SMTP                                            | *(puste)*                        |
| `SMTP_PASSWORD`          | Hasło SMTP                                                 | *(puste)*                        |
| `SMTP_FROM`              | Adres `From:`                                              | wartość `SMTP_USER`              |
| `SMTP_TO`                | Adres odbiorcy alertów                                     | *(puste)*                        |
| `SMTP_USE_TLS`           | STARTTLS                                                   | `true`                           |
| `CHAT_RATE_LIMIT`        | Limit na `/chat/completions` (per user_id)                 | `30/minute`                      |
| `INITIAL_ADMIN_USERNAME` | Login pierwszego admina (seed)                             | `admin`                          |
| `INITIAL_ADMIN_PASSWORD` | Hasło pierwszego admina (seed) — **zmień po starcie**      | `ChangeMeNow!`                   |
| `POSTGRES_USER`          | Użytkownik bazy (compose)                                  | `gateway`                        |
| `POSTGRES_PASSWORD`      | Hasło bazy (compose)                                       | `gateway_secret_change_me`       |
| `POSTGRES_DB`            | Nazwa bazy (compose)                                       | `ai_gateway`                     |
| `APP_PORT`               | Port hosta dla aplikacji (compose)                         | `8000`                           |

## Struktura projektu

```
ai_gateway/
├── app/
│   ├── api/              # routery FastAPI
│   ├── core/             # config, security, deps, rate_limit
│   ├── db/               # baza, Alembic
│   ├── models/           # SQLAlchemy ORM
│   ├── schemas/          # Pydantic
│   ├── services/         # dlp_service (orkiestrator), presidio_service,
│   │                     # classifier_service, policy_parser, llm_service, mail_service
│   └── main.py
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Uwagi bezpieczeństwa

- Hasła hashowane bcryptem (12 rund).
- JWT zawiera `sub` (user_id UUID) oraz `role`. Logout unieważnia sesję serwerowo (Redis).
- Rate limit `30/minute` per `user_id` na `/chat/completions` (slowapi).
- **Oryginalne prompty** trafiają tylko do bazy (`security_incidents`) — nigdy do logów stdout
  ani do treści maili alertowych. Mail zawiera wyłącznie ID incydentu, ID użytkownika i powód.
- Wszystkie usługi infrastrukturalne są w wewnętrznej sieci `gateway_net` — żaden serwis
  poza `app` nie eksponuje portów na host.
- DLP działa w trybie **fail-closed**: awaria Presidio lub klasyfikatora skutkuje
  HTTP 503; prompt nigdy nie trafia niezweryfikowany do Anthropic. Brak załadowanej
  polityki nie jest awarią — wyłącza tylko warstwę 2 (klasyfikator); warstwa 1
  (Presidio: PII + sekrety) działa nadal.
- Dwuetapowa decyzja: naruszenie tematyczne ⇒ cała wiadomość zastąpiona; tylko PII/sekrety
  ⇒ punktowa redakcja `[REDACTED:<TYP>]`; oryginał zachowany **wyłącznie** w bazie
  (`security_incidents`) — nigdy nie trafia do logów ani maili.
