# Technologie w AI Gateway — tłumaczenie po ludzku

Ten dokument tłumaczy wszystkie biblioteki, frameworki i modele, których używamy
w projekcie. Każda sekcja odpowiada na pytania: **co to jest, dlaczego tego użyliśmy,
co by się stało gdyby tego nie było**.

---

## 1. Co robi cały system w jednym akapicie

Pani Kasia z księgowości chce zapytać AI o coś przydatnego, ale przyzwyczaiła się
do publicznego ChatGPT i wkleja tam dane klientów. Tego nie wolno robić, bo to
łamie politykę firmy i RODO. AI Gateway stoi pomiędzy nią a publicznym AI:
przepuszcza pytanie najpierw przez **dwie lokalne warstwy bezpieczeństwa**,
które wycinają lub blokują wrażliwe dane, a dopiero potem (jeśli jest czysto)
wysyła pytanie do Anthropic Claude. Wszystko jest spakowane w Dockerze i działa
na firmowym serwerze.

---

## 2. Backend — co buduje samą aplikację

### FastAPI

Framework webowy do Pythona. To dzięki niemu mamy endpointy `/auth/login`,
`/chat/completions`, `/admin/users` itd. FastAPI jest wybrany dlatego, że:
- jest **asynchroniczny** (używa `async/await`) — jeden serwer obsługuje wiele
  równoczesnych requestów bez blokowania;
- automatycznie generuje dokumentację Swaggera pod `/docs`;
- używa Pydantic do walidacji — jak ktoś przyśle złe dane, serwer wraca z błędem
  zanim w ogóle wejdzie w naszą logikę.

Bez FastAPI musielibyśmy ręcznie pisać routing, walidację i dokumentację.

### Uvicorn

To **serwer**, który właściwie uruchamia aplikację FastAPI. FastAPI to tylko
opisanie endpointów — Uvicorn to silnik, który nasłuchuje na porcie 8000
i kieruje ruch do FastAPI. Analogia: FastAPI to przepis kucharski, Uvicorn
to kuchnia.

### Pydantic

Biblioteka do **walidacji danych**. Definiuje się klasę typu "tak ma wyglądać
request" (np. `ChatRequest` w [`schemas/chat.py`](ai_gateway/app/schemas/chat.py)),
a Pydantic sam sprawdza, czy klient przysłał odpowiednie pola, w odpowiednich
typach. Jeśli nie — automatyczna odpowiedź 422 z opisem błędu.

Bez Pydantic musielibyśmy w każdym endpoincie pisać "if not isinstance(body, dict)",
"if 'messages' not in body" — kilkadziesiąt linii dla każdego endpointu.

---

## 3. Baza danych

### PostgreSQL

Główna baza danych. Trzymamy w niej: użytkowników, polityki firmy, incydenty
DLP. Wybrana bo to najpopularniejsza relacyjna baza open source — ma transakcje,
indeksy, klucze obce, sprawdzone wszystko.

### SQLAlchemy 2.0 (w trybie async)

**ORM** — Object-Relational Mapper. Pozwala mówić do bazy w Pythonie zamiast
pisać SQL ręcznie:

```python
# Zamiast: "SELECT * FROM users WHERE username = 'admin'"
result = await session.execute(select(User).where(User.username == "admin"))
```

Wersja 2.0 z `async` współpracuje z FastAPI — zapytania do bazy nie blokują
serwera, kiedy baza odpowiada wolno.

### asyncpg

**Sterownik** PostgreSQL dla Pythona. To on faktycznie wysyła pakiety TCP do
bazy. SQLAlchemy zamienia nasz kod Pythonowy na SQL, asyncpg ten SQL przesyła
do PostgreSQL. Najszybszy sterownik Pythonowy do Postgresa.

### Alembic

Narzędzie do **migracji** bazy. Jak dodajemy nową kolumnę albo tabelę, Alembic
zapisuje to w pliku migracji ([`db/migrations/versions/`](ai_gateway/app/db/migrations/versions/)).
Przy każdym starcie aplikacji Docker wywołuje `alembic upgrade head`, który
sprawdza, czy schemat bazy jest aktualny i ewentualnie dokłada brakujące zmiany.

Bez Alembica musielibyśmy ręcznie pamiętać, co zmieniliśmy w bazie i pisać
SQL-e na środowiska produkcyjne.

---

## 4. Sesje i cache

### Redis

**Baza in-memory** — wszystko trzyma w RAM, dlatego jest mikrosekundowo szybka.
Używamy jej do trzech rzeczy:
- **Sesje JWT** — gdy ktoś się wyloguje, kasujemy klucz `session:<id>` i jego
  token przestaje działać natychmiast (mimo że JWT z natury jest nieodwoływalny);
- **Historia chatu** — ostatnie 20 wiadomości użytkownika, żeby Claude miał
  kontekst rozmowy;
- **Konfiguracja** — np. adres email do wysyłki alertów (admin może go zmieniać
  w runtime bez restartu).

Bez Redisa musielibyśmy te rzeczy trzymać w PostgreSQL albo w pamięci procesu
(co by zniknęło przy restarcie).

---

## 5. Bezpieczeństwo i logowanie

### JWT + python-jose

**JSON Web Token** — kiedy się logujesz, dostajesz krótki ciąg znaków, który
zawiera Twoje ID i rolę, podpisane sekretem serwera. Wysyłasz go w nagłówku
`Authorization: Bearer ...` przy każdym żądaniu — serwer sprawdza podpis
i wie, kim jesteś, bez sięgania do bazy.

`python-jose` to biblioteka, która tworzy i weryfikuje te tokeny.

### bcrypt + passlib

**Hashowanie haseł**. Hasło użytkownika nigdy nie jest zapisane w bazie
w czystej formie — przechodzi przez bcrypt z kosztem 12 rund, co daje
1-stronowy "odcisk" o długości 60 znaków. Nawet jak ktoś wykradnie bazę,
nie pozna haseł.

`passlib` to wrapper, który ujednolica API różnych algorytmów hashujących.

### slowapi

**Rate limiting** — ograniczamy liczbę zapytań na endpoint `/chat/completions`
do 30 na minutę per użytkownik. Bez tego ktoś mógłby zalać Anthropic za nasze
pieniądze (klucz API ma limity ale opłata za tokeny rośnie).

### email-validator

Walidacja formatu adresów email — używana przez Pydantic, gdy admin ustawia
adres odbiorcy alertów.

---

## 6. Komunikacja z Anthropic Claude

### anthropic (SDK)

Oficjalna biblioteka Pythonowa do **Anthropic API**. Jednolinijkowo robi to,
co w surowym HTTP zajęłoby kilkanaście linii: tworzy request, dba o uwierzytelnienie,
parsuje odpowiedzi, obsługuje streaming.

### Server-Sent Events (SSE)

To **standard webowy do streamowania danych** z serwera do przeglądarki.
Zamiast czekać na pełną odpowiedź Claude, klient widzi token-po-tokenie,
jak w prawdziwym ChatGPT. Klucz: chat odpowiada od razu zamiast po 5-10
sekundach.

W kodzie to FastAPI `StreamingResponse` z Content-Type `text/event-stream`
i fragmentami w formacie `data: <tekst>\n`.

### httpx

Asynchroniczny klient HTTP. Anthropic SDK używa go pod spodem do faktycznego
wysyłania requestów. Działa tak jak `requests`, ale z `async/await`.

---

## 7. Warstwa DLP 1 — wykrywanie konkretnych danych (regex + matematyka)

To tutaj łapiemy PESEL, NIP, IBAN, klucze API. Ta warstwa **nie jest AI** —
to czyste regexy + walidacje matematyczne.

### Microsoft Presidio (presidio-analyzer)

**Framework do DLP** od Microsoftu. Daje silnik, do którego dorzucasz "rozpoznawacze"
(`PatternRecognizer`), a on przeszukuje tekst i mówi: "tu na pozycji 17-28 jest
PESEL z pewnością 0.4". Sami napisalibyśmy podobne narzędzie, ale Presidio:
- ma gotowy mechanizm normalizowania scores i deduplikacji;
- współpracuje z spaCy w roli silnika NLP;
- pozwala dodawać własne walidacje (np. checksumy).

Wbudowane recognizery (Email, CreditCard, IP, URL, Phone) bierzemy z paczki
`predefined_recognizers`.

### spaCy + pl_core_news_md

**Biblioteka NLP**, której Presidio używa pod spodem do rozumienia struktury
tekstu (gdzie jest zdanie, gdzie kończy się słowo, jaka część mowy). Bez NLP
Presidio nie umie zrobić context-aware decisions — np. że słowo "PESEL"
występujące przed liczbą wzmacnia pewność dopasowania.

`pl_core_news_md` to **polski model spaCy** rozmiaru "medium" (~40 MB).
Mniejszy `_sm` jest słabszy, większy `_lg` cięższy bez wyraźnego zysku
dla naszego case'u.

### Własne rozpoznawacze polskich identyfikatorów

W [`presidio_service.py`](ai_gateway/app/services/presidio_service.py)
napisaliśmy 5 własnych klas:
- **PESELRecognizer** — 11 cyfr + walidacja sumy kontrolnej (wagi 1,3,7,9,...);
- **NIPRecognizer** — 10 cyfr + walidacja sumy kontrolnej (wagi 6,5,7,2,...);
- **REGONRecognizer** — 9 lub 14 cyfr + checksum;
- **PolishIBANRecognizer** — `PL` + 26 cyfr + walidacja **mod-97**
  (standard ISO 13616);
- **PolishIDCardRecognizer** — 3 litery + 6 cyfr + checksum (standard
  polskiego dowodu osobistego).

Każdy z nich nie tylko sprawdza długość i format, ale **liczbowo weryfikuje
sumę kontrolną**. Dlatego "12345678901" (11 cyfr) nie jest fałszywie wykrywane
jako PESEL — checksum nie pasuje.

### Wzorce sekretów (klucze API i tokeny)

Dla kluczy nie ma checksum, ale są **bardzo charakterystyczne formaty**:
- klucze Anthropic: `sk-ant-api03-...`
- klucze AWS: `AKIA[16 znaków]`
- klucze GCP: `AIza[35 znaków]`
- tokeny GitHub: `ghp_[36-255 znaków]`
- tokeny Slack: `xox[abprs]-[10+ znaków]`
- JWT: `eyJ...eyJ...{podpis}`
- klucze prywatne: `-----BEGIN ... PRIVATE KEY-----`

Każdy z nich to osobny `PatternRecognizer` z dedykowanym regexem.

---

## 8. Warstwa DLP 2 — rozumienie tematu (embedding similarity)

To **jedyne miejsce, gdzie używamy AI**. Ale w bardzo prostej, jasno określonej
roli: sprawdzić, czy dwa kawałki tekstu znaczą podobne rzeczy.

Cała ta sekcja jest dłuższa od reszty, bo to najbardziej "magiczna" część
systemu. Warto ją zrozumieć dokładnie — wszystkie inne kawałki to klasyczne
backendowe klocki, ale tutaj dzieje się coś, co wygląda jak czytanie myśli.

### 8.1. Co próbujemy osiągnąć

Warstwa 1 (Presidio z regexami) świetnie łapie konkretne dane: PESEL, NIP,
klucz API. Ale nie pomoże, kiedy ktoś napisze:

> "Przygotuj prezentację z planami strategicznymi firmy na Q3"

Tu nie ma żadnego numeru, żadnego wzorca, żadnego klucza. Regex jest ślepy.
A jednak treść wycieka — to są wewnętrzne plany firmy. **Potrzebujemy
czegoś, co rozumie *o czym* tekst jest, nie tylko *jakie znaki* zawiera.**

Tym czymś jest **embedding similarity**.

### 8.2. Co to jest embedding — analogia "zapachu"

Wyobraź sobie, że każdemu zdaniu przypisujemy "zapach" — kombinację składników
znaczenia. Zdania o podobnym znaczeniu pachną podobnie:

- "plany strategiczne firmy" → pachnie *biznesowo, wewnętrznie, długoterminowo*
- "prezentacja na Q3 z naszą strategią" → pachnie *biznesowo, wewnętrznie, długoterminowo*
- "co to jest REST API" → pachnie *technicznie, edukacyjnie, ogólnie*

Pierwsze dwa pachną podobnie, trzeci zupełnie inaczej.

W komputerze "zapach" zdania to **lista 768 liczb** (wektor). Model AI uczy się,
żeby dwa zdania o tym samym znaczeniu dawały podobne listy. Każda z tych 768
liczb mówi coś abstrakcyjnego o znaczeniu — np. "jak bardzo to jest o pieniądzach",
"jak bardzo to jest pytanie", "jak bardzo to jest o ludziach". Tych wymiarów
żaden człowiek nie nazywa, model sam wyuczył je z miliardów zdań.

Przykład wektorów (w rzeczywistości 768 liczb, tu skróciłem do 5):

```
"plany strategiczne firmy"       → [ 0.23, -0.41,  0.07,  0.18, -0.33, ... ]
"prezentacja na Q3 z strategią"  → [ 0.21, -0.39,  0.05,  0.20, -0.35, ... ]
"co to jest REST API"            → [-0.55,  0.18,  0.92, -0.41,  0.07, ... ]
```

Dwa pierwsze są niemal identyczne, trzeci jest w zupełnie innym miejscu
przestrzeni 768-wymiarowej.

### 8.3. Cosine similarity — jak mierzymy podobieństwo

Każdy wektor 768 liczb można wyobrazić sobie jako **strzałkę** wycelowaną
w jakimś kierunku w (bardzo wielowymiarowej) przestrzeni. Dwa zdania o podobnym
znaczeniu mają strzałki wycelowane w tę samą stronę.

**Cosine similarity** mierzy kąt między dwiema strzałkami — albo precyzyjniej,
cosinus tego kąta:

| Cosine | Co to znaczy |
|---|---|
| **1.0** | strzałki w tę samą stronę → zdania znaczą to samo |
| **0.7-0.9** | bliski kąt → ten sam temat, inne słowa |
| **0.4-0.6** | luźne podobieństwo → wspólne pojęcia, różny kontekst |
| **0.0-0.3** | strzałki prostopadłe → niepowiązane tematy |
| **negatywne** | strzałki przeciwne → przeciwne znaczenie (rzadko w praktyce) |

W naszym programie próg wynosi **0.55** — od tego momentu uznajemy, że tekst
jest tematycznie blisko etykiety polityki. Wartość znaleziona empirycznie:
przy 0.45 system był zbyt czuły (false-positive na neutralnych pytaniach),
przy 0.65 zbyt liberalny (puszczał subtelne naruszenia).

### 8.4. Jak to konkretnie działa w naszym programie

Krok po kroku, co się dzieje od momentu, kiedy admin wgrywa politykę,
do momentu, kiedy użytkownik dostaje (albo nie dostaje) odpowiedź.

**Krok 1 — Admin wgrywa politykę markdown**

Admin robi `POST /admin/policy` z plikiem `policy.md`:

```markdown
# Tematy zabronione
- plany strategiczne firmy i wewnętrzne decyzje biznesowe
- wewnętrzne ceny, marże handlowe i polityka rabatowa firmy
- wynagrodzenia pracowników, premie i wewnętrzne raporty kadrowe
- niepublikowane dane finansowe firmy: przychody, koszty, prognozy
...
```

Każdy bullet to **jedna etykieta** — opis pojedynczego tematu, którego nie
wolno wysyłać do zewnętrznego AI.

**Krok 2 — Parser wyciąga etykiety**

Plik [`policy_parser.py`](ai_gateway/app/services/policy_parser.py) parsuje
markdown i zwraca listę stringów (jeden string = jedna zakazana etykieta).
Z powyższego markdownu wyjdzie 7-8 stringów.

**Krok 3 — Pierwszy chat request po wgraniu polityki**

Kiedy ktoś wyśle pierwsze pytanie po wgraniu nowej polityki, klasyfikator
musi zamienić każdą etykietę na wektor 768 liczb. To robi funkcja
`_embed_labels()` w [`classifier_service.py`](ai_gateway/app/services/classifier_service.py):

```python
@lru_cache(maxsize=8)
def _embed_labels(labels: Tuple[str, ...]) -> np.ndarray:
    model = _get_model()
    return model.encode(
        list(labels),
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
```

Wynik to **macierz 8×768** — 8 etykiet, każda jako wektor o 768 wymiarach.

**`@lru_cache` to bardzo ważna sztuczka**: model przepuszcza etykiety przez
sieć neuronową raz, wynik zostaje w pamięci. Przy kolejnych requestach z tą
samą polityką nic się już nie liczy — bierzemy gotową macierz z cache.
Inaczej każdy chat request kosztowałby dodatkowe 200-500 ms.

**Krok 4 — Użytkownik wysyła prompt**

Pani Kasia pisze: "Przygotuj prezentację z planami strategicznymi na Q3".

W [`dlp_service.py`](ai_gateway/app/services/dlp_service.py) prompt najpierw
przechodzi przez Presidio (warstwa 1) — żadnego PESELa nie ma, więc nic się
nie wycina. Tekst dla klasyfikatora to po prostu oryginalny prompt.

**Krok 5 — Encoder zamienia prompt na wektor**

```python
text_emb = model.encode(
    text,
    normalize_embeddings=True,
    convert_to_numpy=True,
)
```

Sieć neuronowa mpnet przepuszcza prompt przez ~12 warstw, na końcu wypluwając
wektor 768 liczb. To trwa ~50-100 ms na CPU.

**Krok 6 — Mnożenie macierzy = liczenie similarity dla wszystkich etykiet naraz**

```python
sims = label_embs @ text_emb
```

Operator `@` w Pythonie to **mnożenie macierzy**. `label_embs` ma kształt
`(8, 768)`, `text_emb` ma kształt `(768,)`. Wynik `sims` ma kształt `(8,)` —
osiem liczb, po jednej dla każdej etykiety.

Dlaczego jedno mnożenie macierzy daje cosine similarity? Bo wcześniej
**znormalizowaliśmy wektory** (parametr `normalize_embeddings=True`) — wtedy
iloczyn skalarny dwóch wektorów *jest* cosine similarity. To trik z liniowej
algebry, ale w praktyce: jedna linia kodu, mikrosekunda obliczeń, gotowe
wszystkie 8 score'ów.

**Krok 7 — Wybór najwyższego score**

```python
top_idx = int(np.argmax(sims))
top_label = candidate_labels[top_idx]
top_score = float(sims[top_idx])
```

`np.argmax(sims)` zwraca indeks największej liczby w tablicy. Bierzemy etykietę
o najwyższym score i sam score.

**Krok 8 — Decyzja: blokować czy puścić**

```python
if top_score >= th:  # th = 0.55 z .env
    return ClassificationResult(True, top_label, top_score, all_scores)
return ClassificationResult(False, None, top_score, all_scores)
```

Jeśli najwyższy score przebił próg 0.55 → naruszenie tematyczne. W naszym
przykładzie ("Przygotuj prezentację z planami strategicznymi na Q3") wynik
będzie mniej więcej taki:

| Etykieta | Score |
|---|---|
| plany strategiczne firmy i wewnętrzne decyzje biznesowe | **0.78** ← top |
| niepublikowane dane finansowe firmy | 0.42 |
| wewnętrzne ceny, marże handlowe i polityka rabatowa firmy | 0.31 |
| wynagrodzenia pracowników, premie i wewnętrzne raporty kadrowe | 0.18 |
| ... |

0.78 > 0.55 → naruszenie. `matched_label = "plany strategiczne firmy..."`.

**Krok 9 — `dlp_service` zamienia całą wiadomość na placeholder**

```python
if topic_violation:
    sanitized = "[CALA_TRESC_ZABLOKOWANA_PRZEZ_DLP]"
```

Cała oryginalna wiadomość znika. To jest decyzja **block_all** — w przeciwieństwie
do wyciętego pojedynczego PESELa, tu nie ma czego zostawiać, bo cały prompt
*jest* o zakazanym temacie.

**Krok 10 — Incydent w bazie i mail do bezpieczeństwa**

Oryginalny prompt zapisuje się w PostgreSQL (tabela `security_incidents`)
z powodem naruszenia. SMTP w tle wysyła krótki email do zespołu — bez treści
promptu, tylko ID incydentu i powód.

**Krok 11 — Do Claude leci placeholder**

Anthropic dostaje wiadomość `[CALA_TRESC_ZABLOKOWANA_PRZEZ_DLP]` z systemowym
promptem informującym, że treść została wycięta. Claude odpowiada
informacyjnie, np. "Twoja wiadomość zawierała poufne dane, została zablokowana
przez DLP".

### 8.5. Konkretny przykład z liczbami — dlaczego to działa

Porównajmy dwie wiadomości i zobaczmy realne scores:

**Prompt A (powinien przejść)**: *"Co to jest REST API i jak różni się od GraphQL?"*

| Etykieta polityki | Score |
|---|---|
| plany strategiczne firmy | 0.12 |
| wewnętrzne ceny, marże | 0.08 |
| wynagrodzenia pracowników | 0.05 |
| niepublikowane dane finansowe firmy | 0.09 |
| wewnętrzny kod CONFIDENTIAL | 0.21 |
| treść umów handlowych | 0.06 |
| wewnętrzne procedury bezpieczeństwa | 0.14 |

Najwyższy 0.21 — daleko od progu 0.55. **Przechodzi.**

**Prompt B (powinien być zablokowany)**: *"Jakie są nasze wewnętrzne marże na produkty enterprise?"*

| Etykieta polityki | Score |
|---|---|
| plany strategiczne firmy | 0.38 |
| **wewnętrzne ceny, marże** | **0.71** ← top |
| wynagrodzenia pracowników | 0.22 |
| niepublikowane dane finansowe firmy | 0.45 |
| wewnętrzny kod CONFIDENTIAL | 0.18 |
| treść umów handlowych | 0.31 |
| wewnętrzne procedury bezpieczeństwa | 0.25 |

0.71 > 0.55 → **block_all**, powód: "wewnętrzne ceny, marże".

Zauważ, że 0.45 i 0.38 dla innych etykiet to nie przypadek — "niepublikowane
dane finansowe" to *również* w pewnym sensie ten temat. Ale model jest mądry
i wybiera najbliższą etykietę.

### 8.6. Konkretne biblioteki i modele — co robi co

Teraz, kiedy rozumiesz mechanikę, krótko o konkretnych narzędziach.

**`sentence-transformers`** — biblioteka Pythonowa, która sprawia, że ten
cały proces (tekst → wektor → similarity) jest jedno-linijkowy. Bez niej
musielibyśmy ręcznie ładować model przez `transformers`, robić tokenizację,
poolingu, normalizacji — kilkadziesiąt linii kodu zamiast `model.encode()`.

**`paraphrase-multilingual-mpnet-base-v2`** — konkretny model, który zamienia
tekst na wektor. Rozłóżmy nazwę:

- **paraphrase** — model był dotrenowywany na zadaniu "rozpoznaj parafrazy"
  (zdania o tym samym znaczeniu napisane różnymi słowami). To dokładnie
  to, co chcemy: "marże enterprise" i "wewnętrzne ceny" mają być uznane
  za bliskie, mimo że nie dzielą żadnego słowa.
- **multilingual** — był uczony na 50+ językach, w tym na polskim.
  Niezbędne — większość modeli sentence-transformers jest tylko angielska.
- **mpnet** — architektura sieci neuronowej (od Microsoftu, rok 2020).
  Lepsza niż BERT, lepsza niż starszy MiniLM dla polskich tekstów.
- **base** — rozmiar modelu (~278 milionów parametrów, ~970 MB pliku).
  Mniejsza wersja `MiniLM-L12` ma 117M parametrów i 384-wymiarowy wektor —
  testowaliśmy ją, ale dla polskiego za słabo różnicowała etykiety.
- **v2** — druga wersja, bardziej dokładna od v1.

Każdy `model.encode(zdanie)` to przepuszczenie tekstu przez tę sieć — ~50-100 ms
na CPU dla jednego zdania.

**PyTorch (CPU)** — silnik liczbowy, na którym **fizycznie** działa sieć
neuronowa. Każde mnożenie wewnątrz mpnet to operacja na PyTorch tensorach.
Dlaczego CPU, nie GPU: 50-100 ms na CPU jest wystarczająco szybko dla naszej
skali (kilkadziesiąt chat requestów na minutę), GPU dawałby 10x przyspieszenie
ale kosztowałby 5000+ zł i komplikacje w Dockerze. Nie warto.

**NumPy** — biblioteka do tablic liczbowych. Po dostaniu wektorów z PyTorcha
konwertujemy je do NumPy (`convert_to_numpy=True`), bo na NumPy łatwiej
i czytelniej liczyć cosine similarity (`label_embs @ text_emb`), argmax,
filtrowanie. NumPy pod spodem to skompilowane C, prędkość taka sama.

### 8.7. Dlaczego to akurat zamiast LLM-a

W trakcie projektu próbowaliśmy trzech podejść:

1. **Lokalny LLM (qwen2.5:7b w Ollamie)** — pierwsza wersja. Daliśmy mu
   politykę i prompt, prosiliśmy o JSON z decyzją. Halucynował, mylił
   pojęcia, nie odróżniał "rozmowy o PESEL-u" od "ujawnienia PESEL-u".
   Średnio 70% trafialności.

2. **Zero-shot NLI (mDeBERTa)** — drugie podejście. Zadawaliśmy modelowi
   pytanie "czy ten tekst dotyczy [etykieta]?" i braliśmy probability.
   Działał lepiej, ale dla krótkich polskich tekstów dawał *score 1.00 dla
   losowych etykiet* (np. "Klient ma PESEL X, jak go zarejestrować" →
   score 1.00 dla "kod CONFIDENTIAL"). Niestabilny, mnóstwo false-positive.

3. **Embedding similarity (obecne)** — to, co opisałem wyżej. Działa,
   bo mierzy realną semantyczną bliskość, a nie pewność modelu w klasyfikacji.

Co konkretnie zyskujemy z embedding similarity:

| Cecha | Embedding similarity | LLM / NLI |
|---|---|---|
| Determinizm | ten sam prompt → ten sam score zawsze | różne wyniki dla tego samego promptu |
| Halucynacje | nie ma czego halucynować | częste |
| Interpretowalność | score = realna bliskość semantyczna | "model jest 80% pewny... czego?" |
| Tuning | jeden próg, łatwy do strojenia | tuning hipotezy + progu + parametrów |
| Szybkość | ~100 ms na CPU | 1-5 s na małym LLM |
| Rozmiar | 970 MB | 5+ GB |
| Wymaga GPU | nie | praktycznie tak |

---

## 9. Email i alerty

### aiosmtplib

**Asynchroniczny klient SMTP**. Kiedy DLP wykryje incydent, wysyłamy email do
zespołu bezpieczeństwa — w **tle** (przez `BackgroundTasks` FastAPI), żeby nie
blokować odpowiedzi dla użytkownika. `aiosmtplib` mówi do serwera SMTP w trybie
`async`, czyli czekanie na potwierdzenie od Gmaila nie zamraża reszty serwera.

### python-multipart

Parser dla **multipart/form-data** — formatu, który przeglądarka używa do
wysłania pliku. Wykorzystywane przy uploadzie polityki (`POST /admin/policy`
z plikiem `.md`). Bez tego FastAPI nie umiałby odbierać plików.

---

## 10. Konteneryzacja

### Docker + Docker Compose

**Konteneryzacja** całej aplikacji. Zamiast instalować Pythona, PostgreSQL,
Redisa ręcznie na serwerze, opisujemy w plikach (`Dockerfile`, `docker-compose.yml`),
jak każdy z nich ma być uruchomiony — i jednym `docker compose up` mamy
działający stos.

Konkretnie mamy 4 kontenery:
- **app** — sama aplikacja FastAPI (Python 3.12);
- **db** — PostgreSQL 16;
- **redis** — Redis 7;
- **frontend** — UI w osobnym katalogu.

Wszystkie żyją w prywatnej sieci `gateway_net` — żaden poza `app` (i ewentualnie
`frontend`) nie wystawia portu na zewnątrz.

### Python 3.12 (slim)

Wersja Pythona, na której uruchamiamy aplikację. **slim** to wariant obrazu
Dockera, który ma tylko podstawowe biblioteki systemowe — mniejszy obraz,
szybszy build.

---

## 11. Architektura w jednym schemacie

```
   przeglądarka użytkownika (Pani Kasia)
                │
                ▼
   ┌─────────────────────┐
   │ FastAPI + Uvicorn   │   ← Python, async, pyt. JWT i rate limit
   └──────────┬──────────┘
              │
              ▼
   ┌──────────────────────────────────────────┐
   │ DLP - WARSTWA 1 (deterministyczna)       │
   │ Presidio + spaCy(pl) + custom recognizery│
   │ • PESEL/NIP/IBAN/dowód: regex + checksum │
   │ • klucze API: regex                      │
   │ • email/telefon: wbudowane Presidio      │
   │ → znalezione fragmenty wycinamy          │
   └──────────────┬───────────────────────────┘
                  │
                  ▼
   ┌──────────────────────────────────────────┐
   │ DLP - WARSTWA 2 (semantyczna)            │
   │ sentence-transformers + mpnet-base       │
   │ • prompt → wektor 768D                   │
   │ • zakazane tematy z polityki → wektory   │
   │ • cosine similarity > 0.55 = naruszenie  │
   │ → cała wiadomość blokowana               │
   └──────────────┬───────────────────────────┘
                  │
                  ▼ (jeśli OK lub po sanityzacji)
   ┌─────────────────────┐
   │ Anthropic Claude    │   ← anthropic SDK + httpx + SSE
   └──────────┬──────────┘
              │
              ▼ (streaming)
        odpowiedź do przeglądarki

   na boku:
   - PostgreSQL: użytkownicy, polityka, incydenty
   - Redis: sesje, historia chatu, konfig
   - SMTP (aiosmtplib): alerty bezpieczeństwa w tle
```

---

## 12. Dlaczego dwie warstwy zamiast jednego AI

To jest kluczowa decyzja architektoniczna. Mogliśmy zrobić wszystko jednym
LLM-em (jak było pierwotnie z qwen2.5:7b w Ollamie). Ale:

| Cecha | Jeden LLM | Dwie warstwy |
|---|---|---|
| Wykrywanie PESEL | "wydaje mi się że to PESEL" — 70-90% | matematycznie pewne — 100% |
| Pamięć i CPU | duży model = dużo zasobów | regex jest darmowy, encoder mały |
| Determinizm | te same dane czasem różny werdykt | regex zawsze ten sam wynik |
| Tłumaczenie decyzji | "model tak uznał" | "PESEL ma checksum X, suma kontrolna nie pasuje" |
| Halucynacje | częste | regex nie halucynuje |
| Kontekst tematyczny | LLM rozumie, ale powoli | encoder rozumie szybko |

**Właściwy podział pracy**: regex robi 80% pracy szybko i deterministycznie
(każdy konkretny identyfikator), AI zajmuje się 20% gdzie regex nie ma szans
(pyta o plany strategiczne, marże, kod CONFIDENTIAL — to są pojęcia, nie wzorce).

To wzorzec używany w prawdziwych systemach DLP (Microsoft Purview, Google
DLP API, AWS Macie) — żaden z nich nie polega na jednym LLM.
