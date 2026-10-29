# Работа с GitHub в этом проекте

Пошагово: как внести правку, собрать exe, выпустить релиз и что делать, когда сборка
упала. Команды можно выполнять как есть.

**Репозиторий:** `AsikSoftware/TgOsint`
**Рабочая ветка:** `claude/new-session-1hqkrp` — разрабатывать и пушить **только в неё**.
**Workflow:** `.github/workflows/build-doctor.yml`, называется «Сборка Pintel».

---

## 1. Главное в двух словах

Сборка **не запускается сама**. В workflow есть триггер на push, но каждый коммит мы
помечаем `[skip ci]`, и он не срабатывает. Сборку запускают **вручную**, когда она нужна.

Одна сборка делает всё сразу: прогоняет тесты, собирает три `.exe`, выкладывает их
артефактами и **создаёт релиз** с тегом `doctor-<номер>`. Отдельно релизить не надо.

Номер — это `run_number` GitHub: сквозной счётчик запусков. Он растёт и на упавших
сборках, поэтому в тегах бывают пропуски (например, за `doctor-49` идёт `doctor-51`).
Это нормально.

---

## 2. Порядок работы: от правки до exe

### Шаг 1. Прогнать тесты локально — ДО пуша

```bash
cd pintel
python -m pytest -q
```

Должно быть «345 passed» (число растёт). **Красные тесты не пушим.**

Отдельно проверьте, что ничего не сломалось там, где нет Qt: лёгкий job в CI не ставит
PySide6, и оконный тест, импортирующий его напрямую, валит всю сборку. Проверка:

```bash
mkdir -p /tmp/безqt
echo "raise ModuleNotFoundError(\"No module named 'PySide6'\", name='PySide6')" > /tmp/безqt/PySide6.py
PYTHONPATH=/tmp/безqt python -m pytest tests -q
```

Должно быть «passed» и несколько «skipped», без единой ошибки импорта. Если упало —
в новом тестовом файле не хватает строки:

```python
pytest.importorskip("PySide6")        # до любого импорта из PySide6
```

### Шаг 2. Закоммитить

```bash
cd /home/user/TgOsint          # коммитим из корня репозитория, не из pintel/
git add -A
git commit -F- <<'MSG'
Короткая строка: что изменилось и зачем

Подробности: что было сломано, почему чинилось именно так, что проверено. [skip ci]

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: <ссылка на сессию>
MSG
```

`[skip ci]` обязателен — иначе push запустит сборку сам, не дождавшись, пока вы
закончите серию коммитов.

### Шаг 3. Запушить

```bash
git push -u origin claude/new-session-1hqkrp
```

Если push упал по сети — повторить до 4 раз с паузами 2, 4, 8, 16 секунд.
**Никогда не делать force-push.**

### Шаг 4. Запустить сборку

Через инструмент GitHub (если он есть):

```
mcp__github__actions_run_trigger
  method: run_workflow
  owner: AsikSoftware
  repo: TgOsint
  workflow_id: build-doctor.yml
  ref: claude/new-session-1hqkrp
```

То же самое через `gh` — это тот же вызов REST:

```bash
gh api --method POST \
  repos/AsikSoftware/TgOsint/actions/workflows/build-doctor.yml/dispatches \
  -f ref=claude/new-session-1hqkrp
```

Ответ пустой (HTTP 204) — это успех.

> Все остальные команды в этом документе проверены на живом репозитории. Эту —
> проверить, не запустив сборку, нельзя, поэтому отмечаю: рабочий путь, которым
> пользовались, — вызов через инструмент GitHub выше; форма с `gh api` обращается
> к тому же endpoint REST. Проверено, что workflow на месте и запускается вручную:
> `gh api repos/AsikSoftware/TgOsint/actions/workflows/build-doctor.yml --jq '.state'`
> отвечает `active`.

### Шаг 5. Узнать номер запуска и дождаться

```bash
sleep 3
id=$(gh api "repos/AsikSoftware/TgOsint/actions/runs?branch=claude/new-session-1hqkrp&event=workflow_dispatch&per_page=1" \
     --jq '.workflow_runs[0].id')
echo "Сборка: https://github.com/AsikSoftware/TgOsint/actions/runs/$id"

for i in $(seq 1 60); do
  s=$(gh api repos/AsikSoftware/TgOsint/actions/runs/$id --jq '.status+"|"+(.conclusion//"—")')
  case "$s" in completed*) echo "ЗАВЕРШЕНА: $s"; break;; esac
  sleep 20
done
```

Сборка идёт **около 6–8 минут**. Ждать её лучше фоновой командой, а не блокировать себя.

### Шаг 6. Забрать результат

Если `completed|success` — релиз уже создан. Проверить:

```bash
gh api repos/AsikSoftware/TgOsint/releases/latest \
  --jq '.tag_name+" | "+([.assets[].name]|join(", "))'
```

Ожидаемый ответ: `doctor-NN | pintel-doctor_Windows_x64.zip, pintel-kiosk_Windows_x64.zip, pintel-server_Windows_x64.zip`

Скачать архивы, чтобы отдать человеку:

```bash
mkdir -p /tmp/сборка && cd /tmp/сборка
for a in $(gh api repos/AsikSoftware/TgOsint/actions/runs/$id/artifacts \
           --jq '.artifacts[] | select(.name|test("kiosk|doctor")) | .id'); do
  gh api "repos/AsikSoftware/TgOsint/actions/artifacts/$a/zip" > "w$a.zip"
  unzip -o -q "w$a.zip" && rm -f "w$a.zip"
done
ls -la
```

Артефакт GitHub — это zip внутри zip, поэтому распаковываем один слой: внутри лежат
готовые `pintel-kiosk_Windows_x64.zip` и `pintel-doctor_Windows_x64.zip`.

Проверить, что метка сборки попала внутрь киоска:

```bash
unzip -p pintel-kiosk_Windows_x64.zip pintel-kiosk/build_info.json
# {"тег": "doctor-NN"}
```

---

## 3. Когда сборка упала

### Найти, где именно

```bash
gh api repos/AsikSoftware/TgOsint/actions/runs/$id/jobs \
  --jq '.jobs[] | select(.conclusion=="failure")
        | .name + " :: " + ([.steps[] | select(.conclusion=="failure") | .name] | join(", "))'
```

Ответ вида `server-tests :: Тесты ядра и сервера` или `build :: Дымовой тест exe`.

### Прочитать лог

```bash
jid=$(gh api repos/AsikSoftware/TgOsint/actions/runs/$id/jobs \
      --jq '.jobs[] | select(.conclusion=="failure") | .id')
gh api repos/AsikSoftware/TgOsint/actions/jobs/$jid/logs \
  | grep -E "FAILED|Error|assert|^E " | head -30
```

Лог большой — без `grep` он забьёт весь контекст.

### Что падало раньше и почему

| Симптом | Причина |
|---|---|
| `ModuleNotFoundError: No module named 'PySide6'` в `server-tests` | новый оконный тест без `pytest.importorskip("PySide6")` |
| `NameError` в дымовом тесте exe | функция обращается к переменной, которой в ней нет; тестов на печать отчёта не было |
| Сборка вообще не запускается, `workflow_dispatch` пропал | **сломан YAML**: однострочный `run:` с `": "` внутри — YAML считает строку парой ключ-значение. Писать блочным скаляром (`run: |`). Есть тест, который это ловит |
| Контрольные суммы не сходятся на Windows | считать по тексту с **LF**: checkout на Windows делает CRLF |

**Починили — повторяем весь цикл с шага 1.** Перезапускать упавшую сборку (`rerun`) не
надо: код изменился, нужен новый запуск.

---

## 4. Что делает сборка внутри

**Job 1 — `server-tests`** (Linux, ~1 мин): ставит зависимости, гоняет `pytest tests -q`,
прогоняет миграции на чистой базе. Qt здесь нет.

**Job 2 — `build`** (Windows, ~6 мин), идёт только если первый прошёл:
1. тесты ядра на архивных слепках — регрессия по эталонам;
2. PyInstaller собирает `pintel-doctor`, `pintel-server`, `pintel-kiosk`;
3. **дымовые тесты**: доктор запускается и печатает отчёт по архивному слепку; касса
   поднимается и отвечает на `/healthz`, `/login`, `/static/app.css`; у киоска
   проверяется, что exe вообще собрался;
4. в киоск кладётся `build_info.json` с тегом — по нему работает самообновление;
5. три архива уходят артефактами;
6. создаётся релиз `doctor-<номер>` с теми же тремя архивами.

Дымовые тесты — это сетка, которая ловит то, чего не видят обычные тесты: например,
отчёт доктора падал с `NameError`, хотя все 312 тестов были зелёными.

---

## 5. Релизы и обновление точек

Релиз создаётся сам, руками ничего делать не надо. Точки с заполненным `update_token`
при запуске спрашивают у GitHub `releases/latest` и, если номер больше своего, ставят
новую сборку и перезапускаются.

### Как откатить плохую сборку

**Не удаляйте релиз.** Удаление сделает `latest` указывающим назад, а киоск **отказывается
ставить версию старее своей** — это сделано специально, чтобы точки не съезжали на старое.
То есть удаление релиза ничего не откатит: точки, успевшие взять плохую сборку, на ней и
останутся.

Правильный откат — **вперёд**: вернуть код (`git revert` или обычная правка), прогнать
тесты, запушить и собрать заново. Новый номер больше, точки подтянут его сами.

Если надо срочно вернуть одну точку — распаковать на ней архив нужного релиза поверх
папки программы. `kiosk.toml` при этом сохранится: копия настроек лежит в
`%LOCALAPPDATA%\PintelKiosk`.

---

## 6. Правила, которые нарушать нельзя

* **Только ветка `claude/new-session-1hqkrp`.** В другие не пушить без явного разрешения.
* **Pull request не создавать**, пока не попросят.
* **Force-push запрещён.**
* **Секреты не коммитить.** `kiosk.toml`, `server.toml`, `config.toml`, `gservice.json`
  уже в `.gitignore`. Ключ Sickw и JSON Google живут только на сервере. Токены GitHub
  никуда не записывать.
* **Красные тесты не пушить.** Сборка всё равно упадёт, только через 7 минут.
* **Каждый коммит — `[skip ci]`**, сборку запускать вручную.

---

## 7. Короткая шпаргалка

```bash
# 1. проверить
cd pintel && python -m pytest -q

# 2. закоммитить и запушить
cd /home/user/TgOsint
git add -A && git commit -m "Что сделано [skip ci]"
git push -u origin claude/new-session-1hqkrp

# 3. собрать
gh api --method POST \
  repos/AsikSoftware/TgOsint/actions/workflows/build-doctor.yml/dispatches \
  -f ref=claude/new-session-1hqkrp

# 4. найти запуск
gh api "repos/AsikSoftware/TgOsint/actions/runs?branch=claude/new-session-1hqkrp&event=workflow_dispatch&per_page=1" \
  --jq '.workflow_runs[0] | .id, .html_url'

# 5. статус
gh api repos/AsikSoftware/TgOsint/actions/runs/<id> --jq '.status+"|"+(.conclusion//"—")'

# 6. релиз
gh api repos/AsikSoftware/TgOsint/releases/latest --jq '.tag_name'
```
