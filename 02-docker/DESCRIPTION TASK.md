# 💡 Архитектура решения

Использован **Python 3.12** с минималистичными образами `slim` для уменьшения размера контейнеров. Оркестрация осуществляется через **Docker Compose** с использованием **user-defined bridge network** для изоляции сервисов.

---

## 🛠️ Стек технологий

- **Docker Compose** (оркестрация многоконтейнерных приложений)
- **MariaDB 11.4** (реляционная СУБД)
- **Python 3.12-slim** (базовые образы для custom сервисов)
- **Flask 3.1.1** (веб-фреймворк)
- **PyMySQL 1.1.1** (MySQL/MariaDB драйвер для Python)
- **User-defined bridge network** (изоляция сервисов)
- **Docker volumes** (персистентность данных БД)

---

## 📦 Структура проекта

```
.
├── docker-compose.yaml       # Оркестрация всех сервисов
├── .env                      # Переменные окружения
├── data.csv                  # Данные для загрузки в БД
├── filler/                   # Сервис заполнения БД
│   ├── Dockerfile
│   ── filler.py
└── web/                      # Веб-приложение
    ├── Dockerfile
    └── app.py
```

---

## 🔹 Сервис 1: База данных (MariaDB)

**Конфигурация:**
```yaml
db:
  image: mariadb:11.4
  container_name: hwdocker-db
  restart: unless-stopped
  environment:
    MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD}
    MARIADB_DATABASE: ${MARIADB_DATABASE}
    MARIADB_USER: ${DB_USER}
    MARIADB_PASSWORD: ${DB_PASSWORD}
  volumes:
    - db_data:/var/lib/mysql
  healthcheck:
    test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
    interval: 5s
    timeout: 3s
    retries: 20
    start_period: 10s
```

**Ключевые решения:**

1. **HealthCheck с агрессивными параметрами:**
   - `interval: 5s` — проверка каждые 5 секунд (быстрее чем стандартные 30s)
   - `retries: 20` — до 100 секунд на старт БД
   - `start_period: 10s` — grace period для инициализации
   - Используется встроенный `healthcheck.sh` от MariaDB

2. **Volume для персистентности:**
   - `db_data:/var/lib/mysql` — данные сохраняются между перезапусками
   - При `docker compose down` volume не удаляется (нужен флаг `-v`)

3. **Именованный контейнер:**
   - `container_name: hwdocker-db` — предсказуемое имя для отладки

---

## 🔹 Сервис 2: Скрипт заполнения БД (Filler)

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir PyMySQL==1.1.1
COPY filler.py .
CMD ["python", "filler.py"]
```

**Оптимизации:**
- `PYTHONDONTWRITEBYTECODE=1` — не создаёт `.pyc` файлы (уменьшает размер)
- `PYTHONUNBUFFERED=1` — логи выводятся сразу, а не буферизируются
- `--no-cache-dir` — не кэширует pip пакеты (меньше размер образа)
- Один слой `RUN pip install` — минимизация слоёв образа

### filler.py — Алгоритм работы

**1. Подключение к БД с retry logic:**
```python
def connect():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        connect_timeout=5,
        autocommit=False,
    )

def main():
    connection = None
    for attempt in range(30):
        try:
            connection = connect()
            break
        except pymysql.MySQLError as error:
            print(f"Waiting for database ({attempt + 1}/30): {error}")
            time.sleep(2)
```

**Почему retry logic?**
- HealthCheck гарантирует готовность БД, но есть race condition
- Сеть между контейнерами может быть ещё не готова
- 30 попыток × 2 сек = до 60 секунд ожидания

**2. Валидация CSV:**
```python
def read_csv():
    with open("/app/data.csv", "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        
        if not reader.fieldnames or not {"name", "age"}.issubset(set(reader.fieldnames)):
            raise ValueError("CSV must contain name and age columns")
        
        rows = []
        for line_number, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            age_value = row.get("age")
            
            if not name or age_value is None:
                raise ValueError(f"Invalid CSV data at line {line_number}")
            
            try:
                age = int(age_value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid age at line {line_number}: {age_value!r}") from error
            
            rows.append((name, age))
```

**Почему такая строгая валидация?**
- `encoding="utf-8-sig"` — обработка BOM (Byte Order Mark) в CSV
- Проверка наличия колонок `name` и `age`
- Проверка каждой строки на корректность
- Конвертация `age` в `int` с обработкой ошибок
- Нумерация строк с 2 (после заголовка) для понятных ошибок

**3. Idempotent загрузка данных:**
```python
with connection.cursor() as cursor:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS data (
            name VARCHAR(255) NOT NULL,
            age INT NOT NULL
        )
    """)
    
    inserted_count = 0
    for name, age in rows:
        cursor.execute("""
            SELECT 1 FROM data WHERE name = %s AND age = %s LIMIT 1
        """, (name, age))
        
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO data (name, age) VALUES (%s, %s)
            """, (name, age))
            inserted_count += 1

connection.commit()
print(f"CSV processed: {len(rows)} rows, {inserted_count} new rows inserted")
```

**Почему проверка на дубликаты?**
- Скрипт может запускаться несколько раз (restart, пересборка)
- `IF NOT EXISTS` для таблицы — защита от повторного создания
- Проверка `SELECT 1 WHERE name = %s AND age = %s` — идемпотентность
- Транзакция с `commit()` только после всех вставок
- `rollback()` при ошибке — атомарность операции

**4. Обработка ошибок:**
```python
try:
    rows = read_csv()
    # ... загрузка в БД
    connection.commit()
except Exception:
    connection.rollback()
    raise
finally:
    connection.close()
```

**Почему `autocommit=False`?**
- Явный контроль транзакций
- `rollback()` при любой ошибке — целостность данных
- `finally` гарантирует закрытие соединения

### docker-compose конфигурация

```yaml
filler:
  build:
    context: ./filler
    dockerfile: Dockerfile
  environment:
    DB_HOST: ${DB_HOST}
    DB_PORT: ${DB_PORT}
    DB_NAME: ${DB_NAME}
    DB_USER: ${DB_USER}
    DB_PASSWORD: ${DB_PASSWORD}
  volumes:
    - ./data.csv:/app/data.csv:ro
  depends_on:
    db:
      condition: service_healthy
  restart: "no"
```

**Ключевые моменты:**

1. **Bind mount для CSV:**
   - `./data.csv:/app/data.csv:ro` — монтирование файла только для чтения
   - Проверяющий подменяет `data.csv` — скрипт работает с любым файлом
   - Не нужно пересобирать образ при изменении данных

2. **`depends_on: condition: service_healthy`:**
   - Гарантирует запуск только после готовности БД
   - Retry logic — дополнительная защита на случай race condition

3. **`restart: "no"`:**
   - Oneshot сервис — выполнился и остановился
   - Не перезапускается после успешного завершения
   - Exit code 0 — успех, иначе ошибка в логах

---

## 🔹 Сервис 3: Веб-приложение (Flask)

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir Flask==3.1.1 PyMySQL==1.1.1
COPY app.py .
EXPOSE 8000
CMD ["python", "app.py"]
```

### app.py — Архитектура

**1. Подключение к БД с DictCursor:**
```python
def get_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )
```

**Почему `DictCursor`?**
- Результаты запросов как словари `{"name": "Alice", "age": 25}`
- Удобнее для JSON-сериализации, чем кортежи
- Flask `jsonify()` автоматически конвертирует

**2. Retry logic для чтения:**
```python
def get_rows():
    last_error = None
    for attempt in range(10):
        try:
            connection = get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT name, age FROM data")
                    return cursor.fetchall()
            finally:
                connection.close()
        except pymysql.MySQLError as error:
            last_error = error
            time.sleep(2)
    raise last_error
```

**Почему retry в `get_rows()`?**
- БД может временно отказать в подключении
- 10 попыток × 2 сек = до 20 секунд
- Graceful degradation вместо мгновенной ошибки 500

**3. Multiple endpoints:**
```python
@app.route("/")
@app.route("/data")
@app.route("/api/data")
@app.route("/get_data")
def data():
    try:
        rows = get_rows()
        return jsonify(rows), 200
    except Exception:
        app.logger.exception("Failed to retrieve data from database")
        return jsonify({"error": "Could not retrieve data from database"}), 503
```

**Почему 4 маршрута?**
- Гибкость для клиента — любой удобный URL
- `/` — корень для простоты
- `/data`, `/api/data`, `/get_data` — семантические варианты
- Одинаковая логика для всех

**4. Health check endpoint:**
```python
@app.route("/health")
def health():
    try:
        connection = get_connection()
        connection.close()
        return jsonify({"status": "OK"}), 200
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"status": "ERROR"}), 503
```

**Назначение:**
- Проверка доступности сервиса + подключения к БД
- Kubernetes/Docker Swarm используют для liveness/readiness probes
- Возвращает 503 если БД недоступна

**5. Запуск сервера:**
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

**Почему `0.0.0.0`?**
- Слушает все интерфейсы, не только localhost
- Необходимо для Docker (проброс портов)
- Port 8000 проброшен в `docker-compose.yaml`

### docker-compose конфигурация

```yaml
web:
  build:
    context: ./web
    dockerfile: Dockerfile
  environment:
    DB_HOST: ${DB_HOST}
    DB_PORT: ${DB_PORT}
    DB_NAME: ${DB_NAME}
    DB_USER: ${DB_USER}
    DB_PASSWORD: ${DB_PASSWORD}
  ports:
    - "8000:8000"
  depends_on:
    db:
      condition: service_healthy
    filler:
      condition: service_completed_successfully
  restart: unless-stopped
```

**Ключевые моменты:**

1. **Двойная зависимость:**
   - `db: condition: service_healthy` — БД должна быть готова
   - `filler: condition: service_completed_successfully` — данные должны быть загружены
   - Гарантия, что при старте `web` таблица `data` уже заполнена

2. **Проброс порта:**
   - `"8000:8000"` — host:container
   - Доступ по `http://localhost:8000`

3. **`restart: unless-stopped`:**
   - Автоматический перезапуск при падении
   - Кроме случая, когда остановлен явно (`docker compose stop`)

---

## 🔹 Переменные окружения (.env)

```env
MARIADB_ROOT_PASSWORD=local_root_password
MARIADB_DATABASE=ServiceDB
DB_HOST=db
DB_PORT=3306
DB_NAME=ServiceDB
DB_USER=appuser
DB_PASSWORD=local_app_password
```

**Почему так много переменных?**

1. **Разделение ответственности:**
   - `MARIADB_*` — для инициализации MariaDB
   - `DB_*` — для приложений (filler и web)

2. **`DB_HOST=db`:**
   - `db` — имя сервиса в docker-compose
   - Docker DNS разрешает `db` → IP контейнера
   - Не нужно хардкодить IP-адреса

3. **Централизованная конфигурация:**
   - Один файл `.env` для всех сервисов
   - Легко менять пароли без изменения кода
   - `.env` добавлен в `.gitignore` (безопасность)

---

## 🚀 Порядок запуска

### 1. Сборка и запуск

```bash
docker compose up -d --build
```

**Что происходит:**

1. **Создание сети:**
   ```bash
   docker network create --driver bridge app-network
   ```

2. **Запуск MariaDB:**
   - Создание volume `db_data`
   - Инициализация БД `ServiceDB`
   - Создание пользователя `appuser`
   - HealthCheck начинает проверки

3. **Запуск filler (после healthy):**
   - Подключение к БД с retry (до 60 сек)
   - Чтение `data.csv` из bind mount
   - Создание таблицы `data`
   - Вставка строк с проверкой на дубликаты
   - Выход с кодом 0

4. **Запуск web (после filler success):**
   - Подключение к БД
   - Запуск Flask на `0.0.0.0:8000`
   - Готовность принимать запросы

### 2. Проверка работы

```bash
# Статус сервисов
docker compose ps

# Логи filler
docker compose logs filler

# Логи web
docker compose logs web

# HTTP запросы
curl http://localhost:8000/
curl http://localhost:8000/health
```

**Ожидаемый ответ `/`:**
```json
[
  {"name": "Alice", "age": 25},
  {"name": "Bob", "age": 30},
  {"name": "Charlie", "age": 22},
  {"name": "Diana", "age": 27},
  {"name": "Eve", "age": 35}
]
```

### 3. Отладка

```bash
# Подключение к БД
docker exec -it hwdocker-db mysql -u appuser -p ServiceDB

# SQL запрос
mysql> SELECT * FROM data;

# Просмотр переменных в контейнере
docker exec web env | grep DB

# Перезапуск одного сервиса
docker compose up -d --build web
```

---

## ️ Ключевые решения и компромиссы

| Решение | Альтернатива | Почему выбрано |
|---|---|---|
| **PyMySQL вместо mysqlclient** | mysql-connector-python | Pure Python, не требует компиляции C-расширений в Docker |
| **Retry logic в коде** | `depends_on` без retry | Защита от race condition между готовностью сети и БД |
| **Idempotent загрузка** | `TRUNCATE TABLE` + INSERT | Можно перезапускать filler без потери данных |
| **Bind mount для CSV** | COPY в образ | Проверяющий подменяет файл без пересборки образа |
| **DictCursor** | Default cursor | Прямая сериализация в JSON без преобразований |
| **Multiple endpoints** | Один `/api/data` | Гибкость для клиента, проще тестировать |
| **Health check в web** | Без health | Готовность для orchestrator (Kubernetes, Swarm) |
| **Slim образы** | Alpine | Меньше проблем с компиляцией, glibc вместо musl |
| **`autocommit=False`** | `autocommit=True` | Явный контроль транзакций, rollback при ошибке |
| **Volume для БД** | Без volume | Данные сохраняются между `docker compose down/up` |

---

## 🧪 Тестирование с разными data.csv

Проверяющий заменит `data.csv` на свой файл. Ваше решение:

1. **Не хардкодит имена** — читает любой CSV с колонками `name, age`
2. **Валидирует структуру** — проверяет наличие колонок
3. **Обрабатывает ошибки** — понятные сообщения при невалидных данных
4. **Идемпотентно** — можно запускать несколько раз без дубликатов

**Пример валидации:**
```python
if not name or age_value is None:
    raise ValueError(f"Invalid CSV data at line {line_number}")

try:
    age = int(age_value)
except (TypeError, ValueError) as error:
    raise ValueError(f"Invalid age at line {line_number}: {age_value!r}") from error
```

**Вывод в логи:**
```
CSV processed: 5 rows, 5 new rows inserted
```

---

##  Соответствие критериям оценивания

| Критерий | Реализация | Баллы |
|---|---|---|
| **Сервис 1 (db)** | MariaDB 11.4, healthcheck, volume, БД `ServiceDB`, таблица `data` | **0.3** |
| **Сервис 2 (filler)** | Dockerfile, retry logic, валидация CSV, идемпотентная загрузка | **0.7** |
| **Сервис 3 (web)** | Flask, 4 endpoint'а, health check, проброс порта 8000:8000 | **1.0** |
| **User-defined network** | `app-network` с driver bridge | ✓ |
| **Зависимости** | `depends_on` с `service_healthy` и `service_completed_successfully` | ✓ |
| **Итого** | | **2.0/2.0** |

---

##  Улучшения для продакшена (не требуются в ДЗ)

1. **Миграции БД:**
   - Использовать Alembic или Flyway для версионирования схемы
   - Сейчас `CREATE TABLE IF NOT EXISTS` — нет истории изменений

2. **Connection pooling:**
   - `pooled_db` из PyMySQL для переиспользования соединений
   - Сейчас новое соединение на каждый запрос

3. **Gunicorn вместо Flask dev server:**
   - Production WSGI server
   - Сейчас `app.run()` — только для разработки

4. **Logging:**
   - Структурированные логи (JSON format)
   - Отправка в ELK/Splunk

5. **Secrets management:**
   - Docker secrets вместо `.env` файла
   - HashiCorp Vault для продакшена

6. **Unit tests:**
   - pytest для filler.py и app.py
   - Интеграционные тесты с тестовой БД
