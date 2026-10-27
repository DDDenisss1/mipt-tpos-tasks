# 🐳 ДЗ #02: Docker — Контейнеризация веб-приложения с БД

## 📋 Условие задачи

Необходимо создать **два образа** и написать **docker-compose файл**, с помощью которых будут развернуты **три связанных сервиса**: база данных MariaDB, скрипт заполнения БД и веб-приложение. Все сервисы должны находиться в одной **user-defined bridge** сети.

## 🛠️ Стек технологий

- **Docker** (контейнеризация)
- **Docker Compose** (оркестрация многоконтейнерных приложений)
- **MariaDB** (реляционная СУБД)
- **Python 3.x** (скрипты заполнения БД и веб-сервер)
- **Flask** (веб-фреймворк)
- **Bash** (health checks, ожидание готовности сервисов)
- **User-defined bridge network** (изоляция сервисов)

---

### Сервисы

| Сервис | Образ | Назначение | Порт |
|---|---|---|---|
| **db** | `mariadb:latest` | Хранение данных (таблица `data`) | 3306 (внутри сети) |
| **filler** | Custom (Dockerfile) | Заполнение БД из `data.csv` | — (oneshot) |
| **web** | Custom (Dockerfile) | HTTP API для доступа к данным | 8000:8000 |

---

## 💡 Архитектура решения
```
┌─────────────────────────────────────────────────────────────┐
│                   Docker Network: app-net                    │
│                     (bridge, user-defined)                   │
─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────┐  │
│  │              │      │              │      │          │  │
│  │     db       │◄─────│   filler     │      │   web    │  │
│  │  (MariaDB)   │      │   (Python)   │      │  (Flask) │  │
│  │   Port:3306  │      │   (oneshot)  │      │ Port:8000│  │
│  │              │      │              │      │          │  │
│  └──────────────┘      └──────────────┘      └──────────┘  │
│         ▲                       │                  │        │
│         │                       │                  │        │
│         └───────────────────────┴──────────────────┘        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
        ▲
        │
   Host:8000
```

### 🔹 Сервис 1: База данных (MariaDB)

**Конфигурация:**
- Образ: `mariadb:latest`
- Название сервиса: `db`
- База данных: `ServiceDB`
- Таблица: `data` (колонки: `name` VARCHAR, `age` INT)

---

### 🔹 Сервис 2: Скрипт заполнения БД (Filler)

**Назначение:**
- Дождаться готовности MariaDB (через healthcheck)
- Подключиться к БД `ServiceDB`
- Создать таблицу `data` (если не существует)
- Загрузить данные из `data.csv`



---

### 🔹 Сервис 3: Веб-приложение (Flask)

**Назначение:**
- HTTP API для доступа к данным из БД
- Запускается на порту 8000
- Подключается к MariaDB через внутреннюю сеть

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY app.py .

# Экспозиция порта
EXPOSE 8000

# Запуск Flask-сервера
CMD ["python", "app.py"]
```

**app.py (Flask API):**
```python
from flask import Flask, jsonify
import pymysql
import os

app = Flask(__name__)

def get_db_connection():
    return pymysql.connect(
        host='db',
        user=os.environ['MYSQL_USER'],
        password=os.environ['MYSQL_PASSWORD'],
        database='ServiceDB'
    )

@app.route('/')
def index():
    """Главная страница"""
    return jsonify({
        "service": "Web API",
        "endpoints": {
            "/all": "Get all records",
            "/name/<name>": "Get records by name"
        }
    })

@app.route('/all')
def get_all():
    """Получить все записи из таблицы data"""
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT name, age FROM data")
            results = cursor.fetchall()
        conn.close()
        return jsonify({"count": len(results), "data": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/name/<name>')
def get_by_name(name):
    """Получить записи по имени"""
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                "SELECT name, age FROM data WHERE name = %s",
                (name,)
            )
            results = cursor.fetchall()
        conn.close()
        return jsonify({"count": len(results), "data": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
```

**docker-compose.yaml:**
```yaml
web:
  build:
    context: ./web
    dockerfile: Dockerfile
  container_name: web
  ports:
    - "8000:8000"
  environment:
    MYSQL_USER: ${MYSQL_USER:-appuser}
    MYSQL_PASSWORD: ${MYSQL_PASSWORD:-apppassword}
  depends_on:
    db:
      condition: service_healthy
    filler:
      condition: service_completed_successfully
  networks:
    - app-net
  restart: unless-stopped
```

**Почему `depends_on: filler: condition: service_completed_successfully`?**
- Веб-сервер должен запуститься **после** заполнения БД
- Иначе при запросе `/all` таблица может быть пустой
- `service_completed_successfully` — специальный condition для oneshot-сервисов

---

## 📁 Структура проекта

```
.
├── docker-compose.yaml          # Оркестрация всех сервисов
── .env                         # Переменные окружения (продвинутый поток)
── data.csv                     # Данные для загрузки в БД
├── filler/                      # Сервис заполнения БД
│   ├── Dockerfile
│   └── filler.py
└── web/                         # Веб-приложение
    ├── Dockerfile
    └── app.py
```

---

## 🚀 Запуск и проверка

### 1. Сборка и запуск

```bash
docker compose up -d --build
```

**Что происходит:**
1. Docker Compose создаёт сеть `app-net` (user-defined bridge)
2. Запускается `db` (MariaDB), начинается healthcheck
3. После готовности БД запускается `filler`
4. После успешного завершения `filler` запускается `web`

### 2. Проверка статуса

```bash
docker compose ps
```

Ожидаемый вывод:
```
NAME      IMAGE            COMMAND                  STATUS
db        mariadb:latest   "docker-entrypoint.s…"   Up (healthy)
filler    filler:latest    "python filler.py"       Exited (0)
web       web:latest       "python app.py"          Up
```

### 3. Проверка логов

```bash
# Логи всех сервисов
docker compose logs

# Логи конкретного сервиса
docker compose logs filler
docker compose logs web
```

### 4. HTTP-запросы к веб-серверу

```bash
# Главная страница
curl http://localhost:8000/

# Все записи
curl http://localhost:8000/all

# Записи по имени
curl http://localhost:8000/name/Alice
```

**Пример ответа `/all`:**
```json
{
  "count": 5,
  "data": [
    {"name": "Alice", "age": 25},
    {"name": "Bob", "age": 30},
    {"name": "Charlie", "age": 35}
  ]
}
```

### 5. Проверка базы данных

```bash
# Подключение к MariaDB
docker exec -it db mysql -u appuser -p ServiceDB

# В MySQL:
mysql> SELECT * FROM data LIMIT 5;
+---------+------+
| name    | age  |
+---------+------+
| Alice   |   25 |
| Bob     |   30 |
+---------+------+
```

### 6. Остановка

```bash
# Остановка всех сервисов
docker compose down

# Остановка с удалением томов (БД)
docker compose down -v
```

---

**Общие требования:**
- Все сервисы в одной user-defined bridge сети
- `filler` запускается после готовности `db` (healthcheck)
- `web` запускается после успешного завершения `filler`
- Порт 8000 проброшен на хост
- Система работает и отдаёт данные

---

## 🔐 .env файл

Для безопасного хранения паролей создайте `.env`:

```env
# Database credentials
MYSQL_ROOT_PASSWORD=supersecretrootpass
MYSQL_USER=appuser
MYSQL_PASSWORD=secureapppassword

# Application settings
FLASK_ENV=production
```

**Почему `.env` лучше хардкода?**
- Пароли не попадают в git (добавьте `.env` в `.gitignore`)
- Легко менять конфигурацию без изменения кода
- Соответствует best practices (12-factor app)

**Использование в docker-compose.yaml:**
```yaml
environment:
  MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
  MYSQL_USER: ${MYSQL_USER}
  MYSQL_PASSWORD: ${MYSQL_PASSWORD}
```

---

## ⚙️ Ключевые решения и компромиссы

| Решение | Альтернатива | Почему выбрано |
|---|---|---|
| **User-defined bridge network** | Default bridge | DNS resolution по имени сервиса, лучшая изоляция |
| **HealthCheck для db** | `sleep 10` в filler | Declarative, надёжный, стандарт Docker |
| **depends_on: condition** | `restart: on-failure` | Явное указание зависимостей, не требует retry |
| **PyMySQL вместо mysqlclient** | mysql-connector-python | PyMySQL pure Python, легче компилировать в Docker |
| **Flask вместо FastAPI** | FastAPI | Проще для учебной задачи, меньше кода |
| **Slim образы Python** | Alpine | Меньше проблем с компиляцией C-библиотек (mysqlclient) |

---

**Важно:**
- В `docker-compose.yaml` должно быть прописано `build:` для сервисов `filler` и `web`
- Образы будут собираться автоматически при `docker compose up --build`
- Система должна работать с **любым** `data.csv` (не хардкодить имена)

---

## 💡 Полезные команды

```bash
# Посмотреть сеть
docker network inspect app-net

# Подключиться к контейнеру
docker exec -it web bash

# Пересобрать один сервис
docker compose up -d --build filler

# Очистить всё (контейнеры, сети, volumes)
docker compose down -v --remove-orphans

# Посмотреть переменные окружения в контейнере
docker exec web env | grep MYSQL
```
