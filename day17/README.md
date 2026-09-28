# MCP-тулколлинг — день 17

Задание:

> Реализуйте свой MCP-сервер вокруг любого API (например: Яндекс.Трекер,
> Git, CRM, mock API). Сделайте: регистрацию инструмента, описание
> входных параметров, возврат результата. Подключите инструмент к своему
> агенту и: вызовите его из приложения, получите и используйте результат.
> Результат: агент делает вызов к MCP-инструменту и получает результат.

База — день 16 (Agent + реестр сессий + SQLite + MCP-хаб + два
stdio-демо-сервера + панель ручных вызовов). День 16 специально держал
инструменты вне запроса к модели; день 17 переворачивает ровно этот бит:
**модель видит все подключённые MCP-инструменты как функции и вызывает
их внутри хода**. Плюс новый MCP-сервер, который оборачивает настоящую
API-границу — mock-трекер задач по REST («Яндекс.Трекер» из примеров
задания).

Встроенная ось сравнения: переключатель «инструменты» в настройках даёт
A/B на одном вопросе — выключен → модель честно угадывает («нет доступа
к трекеру»), включён → вызывает `tracker__issue_list` и отвечает по
настоящим данным из SQLite.

## Архитектура

```
server.py (синхронный ThreadingHTTPServer, порт 7874)
   │  POST /api/chat      → Agent.send_stream — NDJSON:
   │                        start → tool_call/tool_result… → delta… → done
   │  GET  /api/mcp       → hub.servers()      (кэш статусов и инструментов)
   │  POST /api/mcp/call  → hub.call_tool(...) (ручные вызовы, как в дне 16)
   ▼
mcp_hub.py — daemon-поток владеет asyncio-циклом; по живому mcp.Client
   на запись реестра. call_tool — синхронный фасад над
   run_coroutine_threadsafe.
   │
   ├─ py-tools  stdio  sys.executable day17/tools_server.py    (mcp v2)
   ├─ ts-tools  stdio  node ts-tools/…/cli.mjs server.ts       (SDK 1.30.0)
   └─ tracker   stdio  sys.executable day17/tracker_server.py  (mcp v2)
         │  при старте поднимает tracker_api.py потоком ВНУТРИ своего
         │  процесса: ThreadingHTTPServer на 127.0.0.1:<эфемерный порт>
         ▼
      tracker_api.py — REST + SQLite (day17/data/tracker.db, WAL):
         GET /issues?status=   GET /issues/{id}   POST /issues
         PATCH /issues/{id}    POST /issues/{id}/comments
```

«MCP вокруг API» буквально: инструменты `tracker` — это HTTP-клиенты
REST-сервиса, а не функции с прямым доступом к базе. API живёт внутри
MCP-процесса: хаб и так его порождает, отдельный жизненный цикл не нужен,
сирот не остаётся (умрёт родитель — умрёт и API-поток).

## Тулколлинг-цикл

1. При старте (`HUB.start()`) `server.py` строит `OPENAI_TOOLS`: по каждому
   серверу в статусе `ok` каждый инструмент → OpenAI function spec
   `{"type":"function","function":{"name":"srv__tool","description":…,
   "parameters":…}}`. Имя неймспейсится через `__` — `py-tools__add` и
   `ts-tools__add` не сталкиваются. `parameters` пропускается через
   allowlist-ключей (`type/properties/required/items/enum/…`):
   `$schema`, `title` и прочий нестандартный багаж срезается — GLM-парсеры
   к нему чувствительны.
2. Пока у сессии включён `tools` (по умолчанию вкл.), каждый запрос несёт
   `tools=OPENAI_TOOLS`. Стрим остаётся стримом: `delta.tool_calls`
   собираются по `index` (id/name/arguments приезжают фрагментами).
3. `finish_reason == "tool_calls"` → агент эмитит `tool_call`, исполняет
   вызов через `tool_call`-адаптер (split `__` → `HUB.call_tool` → текст),
   эмитит `tool_result`, дописывает в рабочие сообщения
   `assistant.tool_calls` + `tool`-сообщения — и просит модель снова.
4. Цикл ограничен `MAX_TOOL_ROUNDS = 5`; на исчерпании — финальный запрос
   вообще без `tools`, модель обязана ответить текстом.
5. Ошибки — данные, а не падение хода: `is_error`, битый JSON аргументов,
   неизвестное имя, мёртвый сервер → текст «Ошибка: …» в `tool`-сообщении,
   модель реагирует сама.

Хранение — **meta-only**: в `history`/`messages` остаются только
`user`/`assistant` (tool-роли валидны только внутри хода — восстановленные
из базы они ломали бы протокол). Трасса вызовов лежит в
`meta.tool_calls` ассистентского ответа
(`[{server, tool, arguments, ok, preview, latency_ms}]`) и переживает
снапшот/перезагрузку через штатный механизм meta-in-history. Счётчик
токенов суммирует usage по всем хопам хода, `meta.tool_rounds` показывает
число раундов. Тоггл хранится в новой колонке `sessions.tools`
(свежая база, миграции не нужны).

## Трекер: REST API и пять инструментов

`tracker_api.py` — stdlib REST на `ThreadingHTTPServer`, порт выбирает ОС
(`127.0.0.1:0`, печатается в stderr MCP-сервера). SQLite в
`day17/data/tracker.db`, при пустой базе сидит 5 задач. Валидация →
4xx JSON.

`tracker_server.py` — `mcp.server.MCPServer` на stdio, пять инструментов
с типизированными схемами (enum-ы статусов/приоритетов — «описание входных
параметров» из задания):

| инструмент | параметры | REST-вызов |
|---|---|---|
| `issue_list` | `status?` ∈ open/in_progress/done | `GET /issues` |
| `issue_get` | `id` | `GET /issues/{id}` |
| `issue_create` | `title`, `description?`, `priority?` ∈ low/normal/high | `POST /issues` |
| `issue_set_status` | `id`, `status` | `PATCH /issues/{id}` |
| `issue_comment` | `id`, `text` | `POST /issues/{id}/comments` |

4xx API → `is_error` с читаемым текстом; MCP-сессия живёт.

## Проба моделей (`tool_probe.py`)

Перед разводкой прогоняем standalone-пробник: каждая модель × stream/plain
× один тривиальный инструмент с форсящим промптом. Запуск:
`env -u all_proxy -u ALL_PROXY .venv/bin/python day17/tool_probe.py`.

| модель | stream | plain | итог |
|---|---|---|---|
| deepseek-v4-flash | 1 вызов, `finish=tool_calls` | то же | работает — `tools_ok: true` |
| deepseek-v4-pro | 1 вызов, `finish=tool_calls` | то же | работает — `tools_ok: true` |
| glm-4.6 | 401 Authentication Failed | 401 | не проверена (нет баланса Z.ai) — `tools_ok: null` |
| glm-5.3 | 401 Authentication Failed | 401 | не проверена — `tools_ok: null` |

Флаг `tools_ok` в `MODELS` дублируется во фронтовых константах: модели с
`false` получили бы красное предупреждение у переключателя, `null` —
нейтральную пометку «на тулколлинг не проверена».

## Файлы

- **`tracker_api.py`** — `start_api()` → `(httpd, port)`; поток-демон,
  сид при пустой базе, JSON-валидация.
- **`tracker_server.py`** — MCP-сервер tracker; вверху модуля поднимает
  API-поток, дальше пять `@app.tool` на urllib.
- **`tool_probe.py`** — таблица «модель × режим → calls/finish/error».
- **`agent.py`** — `Agent(tools=, tool_call=, tools_enabled=)`; цикл
  раундов в `_run_single`, сборка фрагментов `tool_calls` в `_call_stream`,
  `MAX_TOOL_ROUNDS`, трасса в `meta.tool_calls`; `configure(tools_enabled=)`.
- **`server.py`** — порт **7874**; `sanitize_schema`/`build_openai_tools`,
  `call_mcp_tool`-адаптер («Ошибка: …» при любом сбое), `config.tools`
  в `parse_config`, проброс `tool_call`/`tool_result` в NDJSON.
- **`storage.py`** — `sessions.tools INTEGER DEFAULT 1` рядом с `layers`.
- **`mcp_hub.py`, `tools_server.py`, `ts-tools/`, `mcp_probe.py`** — без
  изменений из дня 16.

## Фронтенд

(dev-порт **5186**, прокси → 7874, localStorage `day17-*-v1`, `dist/`
закоммичен.)

- События `tool_call`/`tool_result` складываются в `chat.toolCalls[]` и
  рисуются раскрываемыми фазами (как заблокированные попытки дня 14):
  имя `srv__tool`, аргументы, статус (вызов…/ok/ошибка), превью результата.
  После `done` те же фазы восстанавливаются из `meta.tool_calls` — в том
  числе после перезагрузки страницы.
- В мета-строке ответа — «инструментов: N».
- В настройках — чекбокс «инструменты» (`config.tools`, по умолчанию вкл.,
  хранится в `sessions.tools` и переживает рестарт).
- Шапка правой панели пишет «модель видит N инструментов» (по ok-серверам)
  или «не видит — выключено в настройках».

## Запуск

```bash
pip install -r requirements.txt                 # mcp>=2.2,<3
cd day17/ts-tools && npm install && cd ../..    # нужно только для ts-tools

# если в шелле стоит all_proxy=socks5h://… — снимите его: httpx без socksio
# падает («Using SOCKS proxy, but 'socksio' is not installed»)
env -u all_proxy -u ALL_PROXY .venv/bin/python day17/server.py  # http://127.0.0.1:7874

cd day17/frontend && npm run dev    # dev-режим: http://localhost:5186
```

**Без Node**: без `ts-tools/node_modules` запись `ts-tools` покажет
`error` в `/api/mcp`; остальные серверы и тулколлинг работают.

## Демо-сценарий

1. «Какие задачи сейчас открыты в трекере?» → модель вызывает
   `tracker__issue_list {status:"open"}`, отвечает списком из базы.
2. «Создай задачу "Проверить MCP-вызов" с высоким приоритетом» →
   `tracker__issue_create`; задача появляется в `tracker.db` и видна
   через `POST /api/mcp/call` → `tracker/issue_list`.
3. «Сколько будет 2+2? Посчитай инструментом» → `py-tools__add` или
   `ts-tools__add` (неймспейсинг на паре одинаковых инструментов виден
   прямо в фазе вызова).
4. Снять чекбокс «инструменты» и повторить (1) → модель отвечает без
   вызовов и честно говорит, что доступа к трекеру нет. Вернуть чекбокс —
   снова реальные данные.

## Smoke-команды

```bash
# статус реестра (три сервера)
curl -s http://127.0.0.1:7874/api/mcp | python -m json.tool

# ручной вызов — минуя модель
curl -s -X POST http://127.0.0.1:7874/api/mcp/call \
  -H 'Content-Type: application/json' \
  -d '{"server":"tracker","tool":"issue_list","arguments":{"status":"open"}}'

# чат с тулколлингом (probe-модель): в NDJSON видны tool_call/tool_result
curl -sN -X POST http://127.0.0.1:7874/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"какие задачи открыты?",
       "config":{"model":"deepseek-v4-flash","tools":true}}'
```

## Проверено

- `day17/offline_check.py` — без сети и node: двуххоповый тулколлинг на
  фейковом стриме (tool_call → tool_result → tool-сообщения → ответ),
  битый JSON/`is_error`/исключение рантайма → текст «Ошибка: …» в
  tool-сообщении, кап `MAX_TOOL_ROUNDS` → финальный хоп без `tools`,
  `tools_enabled=False` → один хоп без `tools`, история после тул-хода —
  только user/assistant + `meta.tool_calls`, снапшот-тоггл и трасса
  переживают save/load; плюс весь набор дня 16 (in-process хаб и пр.).
- Живой прогон на deepseek-v4-flash: «какие задачи открыты» →
  `tracker__issue_list` → ответ с реальными #3/#5; `tools:false` →
  один хоп, ноль tool-событий; рестарт сервера — `tools` сессии и
  `meta.tool_calls` восстановлены из базы.
- `tool_probe.py` — таблица выше: обе deepseek-модели вызывают инструмент
  в обоих режимах; GLM не проверены (401, нужен баланс Z.ai).

## Принятые решения (и что отвергнуто)

- **REST API внутри MCP-процесса** (поток + эфемерный порт), а не
  отдельный сервис: хаб и так порождает процесс, своего жизненного цикла
  у API нет, сирот не остаётся. Отвергнуто: инструменты напрямую в
  SQLite — тогда ничто не «вокруг API», а HTTP-hop стоит ~60 строк
  stdlib и делает посылку задания буквальной.
- **Спеки строятся один раз при старте** из кэша ok-серверов: сервер,
  умерший в середине сессии, оставляет спек, но его вызов возвращает
  «Ошибка: …» — для модели это информативнее, чем тихое исчезновение
  инструмента.
- **`srv__tool` неймспейсинг**: OpenAI имена функций — `^[a-zA-Z0-9_-]+$`,
  `-` в id серверов легален, `__` делит однозначно. Пара `py-tools__add` /
  `ts-tools__add` оставлена специально — показывает, зачем префикс.
- **Инъекция рантайма в Agent** (`tool_call=callable`), а не импорт хаба:
  та же точка подмены, что `client=`, — офлайн-проверка гоняет цикл на
  фейках без MCP и asyncio.
- **Трасса — meta-only**: `tool`-сообщения существуют только внутри хода;
  восстановленные из базы они были бы протокольно невалидны без своего
  `assistant.tool_calls`. Схема messages не менялась вообще.
- **Цикл ограничен (5) + финальный хоп без tools**: страховка от
  бесконечного цикла/разового бюджета; демо-цепочки короче.
- **Тоггл по умолчанию вкл.**: день про рабочий вызов; выключение —
  встроенный A/B, а не скрытая фича.
- **Ошибки инструментов — данные для модели**: `is_error`, битый JSON,
  неизвестное имя, мёртвый сервер → текст в `tool`-сообщении, ход живёт
  (наследие философии дня 16 «error — строка, не исключение»).
