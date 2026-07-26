# Graphify

Graphify — только инструмент разработки: он строит knowledge graph по коду и
документации Satellite. На runtime бота, Docker-образ и production-деплой он не
влияет.

Проект закреплён на `graphifyy==0.9.27`. Codex-навык уже хранится в
`.codex/skills/graphify/`; повторно устанавливать его в проект не требуется.
Git hooks намеренно не используются.

## Установка CLI

```bash
make graphify-install
```

Команда ставит изолированный CLI через `uv tool`, добавляет каталог инструментов
`uv` в shell `PATH` и печатает установленную версию. После первого запуска
откройте новую shell-сессию или перезапустите Codex, затем проверьте:

```bash
graphify --version
```

## Сборка и обновление

Первую полную сборку и семантическое обновление документации запускайте из
Codex:

```text
$graphify .
$graphify . --update
```

Код разбирается локально и детерминированно через tree-sitter AST. Документы
проходят семантический разбор через текущую модель Codex. Дополнительные API-ключи
для этого проекта не подключаются.

После изменений только в коде достаточно бесплатного AST-обновления:

```bash
make graphify-update
```

Проверить, остались ли изменённые документы, которым нужен semantic update:

```bash
make graphify-check
```

Полная сборка также создаёт локальный интерактивный
`graphify-out/graph.html`. Он не хранится в Git.

## Запросы

```bash
graphify query "Как устроено подключение календаря пользователя?"
graphify path "handle_web_app_connect()" "UserStore"
graphify explain "HandlerContext"
```

Для вопросов о кодовой базе Codex сначала использует `query`, `path` или
`explain`, а к исходникам переходит, если графа недостаточно.

## Что хранится в Git

| Файл | Назначение |
|------|------------|
| `graphify-out/graph.json` | Узлы, связи и source locations для запросов |
| `graphify-out/GRAPH_REPORT.md` | Hubs, сообщества, неожиданные связи и вопросы |
| `graphify-out/manifest.json` | Переносимая база для инкрементального обновления |
| `graphify-out/.graphify_labels.json` | Стабильные названия сообществ |

HTML, cache, cost, абсолютные пути локального Python/root и временные
`.graphify_*` файлы игнорируются.

## Границы корпуса и приватность

- `.codex/skills/graphify/` и `graphify-out/` исключены через
  `.graphifyignore`, чтобы инструмент не индексировал сам себя.
- Брендовый `satellite/analytics/assets/logo.png` не входит в граф: текущий
  корпус ограничен кодом и документацией.
- `.env.example` и `deploy/.env.example` Graphify намеренно пропускает как
  потенциально чувствительные. Защиту не обходить и файлы ради индексирования не
  переименовывать.
