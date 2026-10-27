##  🛠️ Стек технологий
- Python 3.12 (основной язык)
- argparse (парсинг CLI-аргументов и подкоманд)
- tmux (терминальный мультиплексор, управление через CLI)
- subprocess (вызов внешних команд: tmux, fuser)
- pathlib (объектно-ориентированная работа с путями)
- shutil (копирование файлов, удаление директорий)
- zipfile (архивация результатов для --zip)
- urllib (HTTP-запросы для healthcheck)
- socket (проверка занятости порта)
- Bash (install.sh для установки зависимостей)

## 💡 Архитектура решения
Использован Python 3.12 с модулем argparse для парсинга подкоманд. Управление tmux-сессиями осуществляется через subprocess.run(), что позволяет не зависеть от внешних библиотек.

Команда start — Запуск копии сервера
```bash
./homework start --name <server_name> --port <server_port>
```

**Алгоритм:**

1. **Валидация имени** (продвинутый поток):
   ```python
   if not re.match(r'^[a-z]{1,32}$', name):
       sys.exit(1)
   ```
   Только lowercase буквы, длина 1–32 символа.

2. **Проверка уникальности** (продвинутый поток):
   - `exitcode 1` — сервер с таким именем уже существует
   - `exitcode 2` — порт уже занят другим сервером (сканирование `.port` файлов)
   - `exitcode 3` — порт занят системным процессом (`socket.connect_ex()`)

3. **Создание инфраструктуры:**
   - `mkdir <server_name>/` — рабочая директория
   - `shutil.copy('server.py', <server_name>/server.py)` — копия приложения
   - Запись порта в `<server_name>/.port` — для последующего поиска

4. **Запуск в tmux:**
   ```python
   tmux new-session -d -s homework -n <name> \
       "cd <name> && python3 server.py --port <port> > out.txt"
   ```
   - Сессия `homework` создаётся при первом запуске
   - Каждая копия — отдельное окно с именем `<server_name>`
   - `stdout` перенаправляется в `out.txt` внутри папки сервера

5. **Healthcheck** (продвинутый поток):
   ```python
   time.sleep(3)  # grace period для запуска
   response = urllib.request.urlopen(f'http://localhost:{port}/healthcheck')
   if response.getcode() != 200:
       print(f"Bad response code: {code}", file=sys.stderr)
       sys.exit(4)
   ```

**Почему tmux, а не `subprocess.Popen`?**
Tmux даёт возможность визуально наблюдать за работающими серверами (`tmux attach -t homework`), переключаться между окнами и корректно завершать процессы через `C-c`. Это ближе к реальному DevOps-опыту.

---

## 🔹 Команда `stop` — Остановка одной копии

```bash
./homework stop --name <server_name>
```

**Алгоритм:**

1. **Graceful shutdown через tmux:**
   ```python
   tmux send-keys -t homework:<name> C-c
   time.sleep(0.3)
   ```
   Сначала мягкое завершение (Ctrl+C), затем принудительное через `fuser -k <port>/tcp`.

2. **Backup лога:**
   ```python
   timestamp = int(time.time())
   shutil.copy(f'{name}/out.txt', f'.backup/out_{name}_{timestamp}.txt')
   ```
   Исходный `out.txt` копируется (не перемещается) — на случай, если процесс ещё пишет.

3. **Очистка:**
   - `tmux kill-window -t homework:<name>` — закрыть окно
   - `shutil.rmtree(name)` — удалить папку сервера

**Почему отдельная папка `.backup`?**
Чтобы не смешивать активные серверы с архивом. Соседнее расположение (`.backup/` рядом с серверами) упрощает навигацию.

---

## 🔹 Команда `stop_all` — Остановка всех копий

```bash
./homework stop_all
```

**Алгоритм:**

1. Сканирование текущей директории: все папки, содержащие `server.py` → список активных серверов
2. Для каждого сервера:
   - `kill_server_process(name, port)` — остановка процесса
3. `time.sleep(0.5)` — пауза для гарантированного завершения всех процессов
4. Массовый backup `out.txt` всех серверов
5. Удаление всех папок серверов
6. `tmux kill-session -t homework` — полное закрытие сессии

**Почему сначала убиваем все процессы, потом делаем backup?**
Чтобы гарантировать, что все `out.txt` записаны полностью до момента копирования. Иначе можно получить обрезанный лог.

---

## 🔹 Команда `collect_all` — Сбор результатов

```bash
./homework collect_all [--zip]
```

**Базовый режим (stdout):**

```python
servers = sorted([d for d in Path('.').iterdir() 
                  if d.is_dir() and (d/'server.py').exists()])

for name in servers:
    print(f"=== server: {name} ===")
    print((Path(name) / 'out.txt').read_text().rstrip('\n'))
```

- Лексикографическая сортировка по имени папки
- Формат: `=== server: <name> ===` + содержимое `out.txt`
- Пустая строка между блоками (кроме последнего)

**Продвинутый режим (`--zip`):**

```python
with zipfile.ZipFile(f'out_{timestamp}.zip', 'w', ZIP_DEFLATED) as zf:
    for name in servers:
        zf.write(f'{name}/out.txt', f'out_{name}.txt')
```

- Архив именуется `out_<collect_timestamp>.zip`
- Внутри файлы `out_<server_name>.txt`
- **Исходные `out.txt` остаются нетронутыми** — это важно по условию

**Почему `zipfile` вместо `subprocess.run(['zip', ...])`?**
Модуль `zipfile` — часть стандартной библиотеки, не требует внешних зависимостей и работает кроссплатформенно.

---

## 🔹 Служебный файл `.port`

В каждой папке сервера создаётся файл `.port` с номером порта:

```python
(Path(name) / '.port').write_text(str(port))
```

**Зачем:**
- Позволяет найти порт сервера по имени без парсинга tmux
- Нужен для проверки "порт уже занят другим сервером" (exitcode 2)
- Нужен для `fuser -k <port>/tcp` при остановке

---

## 🚀 Примеры использования

### Запуск трёх серверов

```bash
./homework start --name alpha --port 8001
./homework start --name beta --port 8002
./homework start --name gamma --port 8003
```

### Проверка через tmux

```bash
tmux ls
# homework: 3 windows (created ...)

tmux attach -t homework    # подключиться и посмотреть логи
```

### Сбор результатов

```bash
./homework collect_all
```

Вывод:
```
=== server: alpha ===
[2026-10-18 14:30:01] GET /healthcheck 200
[2026-10-18 14:30:05] GET /api/data 200

=== server: beta ===
[2026-10-18 14:30:02] GET /healthcheck 200
```

### Архивация

```bash
./homework collect_all --zip
ls out_*.zip
# out_1729260000.zip
```

### Остановка

```bash
./homework stop --name beta         # только beta
./homework stop_all                 # все сразу
```

---

## ⚙️ Ключевые решения и компромиссы

| Решение | Альтернатива | Почему выбрано |
|---|---|---|
| `subprocess.run(['tmux', ...])` | `libtmux` | Меньше зависимостей, прозрачнее для проверки |
| `socket.connect_ex()` для проверки порта | `lsof -i` | Кроссплатформенно, не требует `psmisc` |
| `.port` файл в папке сервера | Парсинг `tmux list-windows` | Надёжнее, не зависит от формата tmux |
| `shutil.copy` для backup | `shutil.move` | Безопаснее: если процесс ещё пишет, оригинал не теряется |
| `time.sleep(3)` перед healthcheck | Цикл с retry | Проще, 3 сек достаточно для Python HTTP-сервера |
| `zipfile` модуль | `subprocess(['zip'])` | Стандартная библиотека, нет внешних зависимостей |

---

## 🧪 Локальное тестирование

Для локальной проверки используется `server.py` — минимальный HTTP-сервер на `http.server`:

```python
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthcheck':
            self.send_response(200)
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
```

Он поддерживает `/healthcheck` endpoint и логирует запросы в `stdout` (который перенаправляется в `out.txt`).






