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
