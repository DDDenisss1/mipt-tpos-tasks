## 💡 Архитектура решения

Решение реализовано в виде **Ansible-роли `service_state`**, которая настраивает nginx, создаёт JSON-файл состояния и обновляет время работы nginx через cron. Одна роль поддерживает **Ubuntu 26.04** и **CentOS 7** с учётом различий в пакетных менеджерах, репозиториях и именах служб.

HTTP-запрос `GET /service_data` обрабатывается непосредственно nginx: отдельное веб-приложение не требуется. Состояние хранится в `/opt/service_state.json`, а `uptime` вычисляется по времени жизни master-процесса nginx.

Принцип идемпотентности: **при неизменном `title` Ansible сохраняет JSON и не перезапускает nginx; при изменении `title` сбрасывает `uptime` и перезапускает nginx**.

---

## 🛠️ Стек технологий

- **Ansible** — управление конфигурацией; роль, handlers, templates, facts и условные задачи.
- **nginx** — HTTP-сервер на порту 80.
- **cron / cronie** — запуск обновления uptime каждую минуту.
- **jq** — изменение поля `uptime` в JSON без потери остальных полей.
- **POSIX shell** — скрипт расчёта uptime.
- **Docker + WSL2** — локальное тестирование на Ubuntu 26.04 и CentOS 7.
- **GitLab CI** — автоматическая проверка решения на обеих ОС.

---

## 📦 Структура проекта

```text
.
├── playbook.yml
└── roles/
    └── service_state/
        ├── defaults/
        │   └── main.yml
        ├── files/
        │   └── update_nginx_uptime.sh
        ├── handlers/
        │   └── main.yml
        ├── tasks/
        │   ├── main.yml
        │   ├── vault.yml
        │   ├── state.yml
        │   ├── nginx.yml
        │   ├── cron.yml
        │   └── services.yml
        └── templates/
            └── nginx.conf.j2
```

Локальные inventory-файлы с именами Docker-контейнеров в состав публикуемого решения не входят.

---

## 🔹 1. Точка входа и параметры

### `playbook.yml`

```yaml
---
- name: Configure service state
  hosts: all
  become: true

  roles:
    - service_state
```

Playbook применяет роль к целевым хостам. Повышение привилегий включено для обычных серверов; при локальном тестировании Docker-контейнеров, где пользователь уже `root`, оно отключалось в inventory через `ansible_become=false`.

### `defaults/main.yml`

```yaml
---
service_title: "Seems working"
service_json_path: /opt/service_state.json
service_port: 80
```

**Почему параметры вынесены в defaults?** Значение `title`, путь к JSON и порт можно изменить без редактирования задач роли. Для проверки изменения заголовка использовался параметр `-e` с JSON, чтобы корректно передавать строки с пробелами.

---

## 🔹 2. Установка пакетов и поддержка двух ОС

В `tasks/main.yml` используются условные задачи по `ansible_os_family`:

```yaml
- name: Install packages on Ubuntu
  ansible.builtin.apt:
    name:
      - nginx
      - cron
      - jq
    state: present
    update_cache: true
  when: ansible_os_family == "Debian"

- name: Install packages on CentOS
  ansible.builtin.yum:
    name:
      - nginx
      - cronie
      - jq
    state: present
  when: ansible_os_family == "RedHat"
```

**Особенности:**

- На Ubuntu используется `apt`, на CentOS — `yum`.
- Пакет планировщика в Ubuntu называется `cron`, в CentOS — `cronie` (служба `crond`).
- `state: present` не приводит к повторной установке пакетов, если они уже есть.

### Архивные репозитории CentOS 7

CentOS 7 завершил жизненный цикл, поэтому на чистом образе стандартные зеркала недоступны. Задачи `vault.yml` отключают устаревшие `mirrorlist` и заменяют адреса базовых репозиториев на **CentOS Vault 7.9.2009**. Отдельная задача `yum_repository` подключает архивный **EPEL 7**, из которого доступны необходимые пакеты, включая nginx и jq.

Задачи настройки репозиториев выполняются **до** установки пакетов и идемпотентны: на уже настроенном контейнере повторного изменения `.repo`-файлов нет.

---

## 🔹 3. Файл состояния и логика изменения title

В `tasks/state.yml` выполняются следующие действия:

1. `stat` проверяет существование `/opt/service_state.json` и размер файла.
2. `slurp` читает существующий непустой файл.
3. `b64decode | from_json` извлекает текущее значение `title`.
4. `copy` создаёт или перезаписывает JSON **только при отсутствии файла, пустом файле или изменении `title`**.
5. При создании/изменении состояния отправляется уведомление handler `Restart nginx`.

Условие обновления:

```yaml
when: >
  not service_state_stat.stat.exists
  or (service_state_stat.stat.size | int) == 0
  or current_service_title | default('') != service_title
notify: Restart nginx
```

Содержимое при создании или сбросе:

```json
{
  "title": "Seems working",
  "uptime": 0
}
```

**Почему используется проверка размера?** При разработке встретился существующий файл размером 0 байт. Попытка выполнить `from_json` для пустого содержимого приводила к ошибке. Проверка позволяет восстановить начальное состояние.

**Почему не используется безусловный `template` или `copy` при каждом запуске?** Такая запись могла бы обнулить uptime, который обновляет cron, и нарушить идемпотентность.

---

## 🔹 4. nginx: HTTP endpoint без отдельного приложения

### `templates/nginx.conf.j2`

```nginx
server {
    listen {{ service_port }} default_server;
    server_name _;

    location = /service_data {
        alias {{ service_json_path }};
        default_type application/json;
    }

    location / {
        return 404;
    }
}
```

**Ключевые решения:**

- `location = /service_data` — точное совпадение маршрута.
- `alias` — nginx напрямую читает файл состояния.
- `default_type application/json` — корректный `Content-Type`.
- `template` — позволяет задавать порт и путь к файлу через переменные роли.
- В `tasks/nginx.yml` удаляется стандартная конфигурация сайта, которая могла конфликтовать с `default_server`.

Проверка:

```bash
curl -i http://localhost:8080/service_data  # Ubuntu в локальном Docker
curl -i http://localhost:8081/service_data  # CentOS в локальном Docker
```

Ожидаемый результат — `HTTP/1.1 200 OK`, `Content-Type: application/json` и актуальное содержимое файла.

---

## 🔹 5. Обновление uptime через cron

В `tasks/cron.yml` устанавливается исполняемый скрипт:

```text
/usr/local/bin/update_nginx_uptime.sh
```

И создаётся задание пользователя `root`:

```cron
* * * * * /usr/local/bin/update_nginx_uptime.sh
```

### Алгоритм `update_nginx_uptime.sh`

1. Проверить существование JSON и `/var/run/nginx.pid`.
2. Прочитать PID master-процесса nginx.
3. Получить время жизни процесса в секундах через `ps -o etimes=`.
4. Перевести секунды в целые минуты.
5. Через `jq` обновить **только** ключ `uptime`.
6. Записать результат во временный файл, выставить права `0644` и заменить исходный файл командой `mv`.

Ключевой фрагмент:

```sh
NGINX_PID=$(cat "$PID_FILE")
SECONDS=$(ps -o etimes= -p "$NGINX_PID" | tr -d ' ')
MINUTES=$((SECONDS / 60))

TMP_FILE=$(mktemp /opt/.service_state.XXXXXX)
trap 'rm -f "$TMP_FILE"' EXIT

jq --argjson uptime "$MINUTES" \
  '.uptime = $uptime' \
  "$STATE_FILE" > "$TMP_FILE"

chmod 0644 "$TMP_FILE"
mv -f "$TMP_FILE" "$STATE_FILE"
```

**Почему отдельный скрипт?** Первоначально логика была записана одной длинной командой в crontab. Ручной запуск вычислял uptime корректно, но автоматическое обновление не подтвердилось. Выделение исполняемого скрипта упростило диагностику и обеспечило стабильное выполнение cron.

**Почему временный файл + `mv`?** Читатель не увидит частично записанный JSON: файл заменяется после завершения генерации. Это атомарная замена в пределах одной файловой системы.

**Почему uptime вычисляется через PID?** Значение отражает фактическое время жизни nginx в минутах, а не число запусков cron. Перезапуск nginx естественным образом начинает отсчёт заново.

---

## 🔹 6. Управление службами и обработчики

Роль учитывает два типа окружения:

| Среда | Управление службами |
|---|---|
| Linux с systemd | `ansible.builtin.systemd` с `enabled: true`, `state: started` |
| Тестовые Docker-контейнеры без systemd | Проверка процессов и прямой запуск `nginx`, `cron` / `crond` |

Для перезапуска nginx применены два обработчика с общим `listen: Restart nginx`:

- **С systemd** — `ansible.builtin.systemd` с `state: restarted`.
- **Без systemd** — проверка `nginx -t`, корректное завершение процесса `nginx -s quit`, ожидание освобождения PID-файла и новый запуск `nginx`.

Условные проверки `ansible_service_mgr` позволяют не использовать ручной запуск там, где доступен systemd.

**Почему nginx перезапускается при смене `title`?** Сам nginx способен отдавать новый JSON без рестарта. Но в задании предусмотрено обнуление времени работы nginx при изменении заголовка, поэтому уведомление handler отправляется **только при изменении состояния, управляемого Ansible**, а ежеминутная запись uptime не перезапускает сервер.

---

## 🔹 7. Идемпотентность

При повторном запуске с тем же `service_title`:

- `stat` и `slurp` читают существующее состояние.
- Задача `Create or reset service state` пропускается.
- nginx-конфигурация и cron-задание остаются неизменными.
- Handler `Restart nginx` не вызывается.
- Существующий PID nginx сохраняется, а uptime может продолжать увеличиваться по cron.

При изменении `service_title`:

- JSON получает новый заголовок и `uptime: 0`.
- Вызывается handler настоящего перезапуска nginx.
- После рестарта nginx получает новый PID, и отсчёт uptime начинается заново.

Пример проверки:

```bash
ansible-playbook -i inventory.ini playbook.yml \
  -e '{"service_title": "Seems working"}'

ansible-playbook -i inventory.ini playbook.yml \
  -e '{"service_title": "Seems working"}'
```

Второй запуск должен завершиться с `changed=0` при неизменной конфигурации и работающих службах.

---

## 🚀 Локальный запуск и проверка

Разработка велась в **WSL Ubuntu 22.04**; Ansible выполнялся из Python-venv на управляющей машине. Для тестирования были запущены отдельные контейнеры Ubuntu 26.04 и CentOS 7 с подключением через `community.docker.docker` без SSH.

В локальном inventory использовались `ansible_connection=community.docker.docker`, подходящий путь к Python и `ansible_become=false`, поскольку пользователь контейнера уже `root`.

Типовые команды:

```bash
# Синтаксис
ansible-playbook -i inventory.ini playbook.yml --syntax-check

# Проверка доступности узлов
ansible all -i inventory.ini -m ping

# Запуск на обеих ОС
ansible-playbook -i inventory.ini playbook.yml

# Проверка идемпотентности
ansible-playbook -i inventory.ini playbook.yml

# Изменение заголовка
ansible-playbook -i inventory.ini playbook.yml \
  -e '{"service_title": "Ansible Restart Test"}'
```

В примерах используется локальный `inventory.ini`, который не включён в публикуемый репозиторий и должен быть подготовлен под свои целевые хосты.

---

## 🧪 Результаты тестирования

| Сценарий | CentOS 7 | Ubuntu 26.04 |
|---|---|---|
| Установка на чистый контейнер | ✅ | ✅ |
| Повторный запуск без изменений | `changed=0` | `changed=0` |
| HTTP `GET /service_data` | `200 OK` | `200 OK` |
| Обновление uptime через cron | ✅ | ✅ |
| Изменение `title` и сброс uptime | ✅ | ✅ |
| Перезапуск nginx при смене `title` | ✅ | ✅ |

В GitLab CI обе проверочные задачи завершились со статусом **Passed**.

**Ограничение проверки:** локально CentOS 7 тестировался со штатным Python 2.7.5, а не с Python 2.6. Успешный CI подтверждает прохождение конкретных тестов курса, но не заменяет проверку на всех возможных версиях Python и вариантах системной конфигурации.

---

## ⚖️ Ключевые решения и компромиссы

| Решение | Альтернатива | Почему выбрано |
|---|---|---|
| Ansible role вместо монолитного playbook | Все задачи в `playbook.yml` | Разделение установки, состояния, nginx, cron и служб |
| nginx `alias` для JSON | Python/Flask API | Для статического файла отдельное приложение не нужно |
| Вычисление uptime по PID nginx | Инкремент счётчика | Значение связано с фактическим временем работы nginx |
| Скрипт вместо длинной строки crontab | Вся логика в `job` | Проще проверять и отлаживать |
| `jq` + временный файл + `mv` | Перезапись JSON на месте | Сохранение остальных полей и защита от частичной записи |
| `stat` + `slurp` + условный `copy` | Безусловная перезапись | Не сбрасывает uptime на повторном запуске |
| Handler только при изменении `title` | Рестарт при каждом обновлении файла | Не прерывает nginx при ежеминутном обновлении uptime |
| systemd / прямой запуск по условию | Только `systemd` | Работает в минимальных Docker-контейнерах без init-системы |
| CentOS Vault + архив EPEL | Стандартные зеркала CentOS 7 | Возможна установка пакетов на EOL-образе |

---

## 🔧 Возможные улучшения для production

1. **Поддерживаемые версии ОС.** CentOS 7 и его архивные репозитории использовать только для учебной совместимости; для production выбирать поддерживаемую систему.
2. **Управление конфигурацией сервисов.** В реальной инфраструктуре предпочтителен systemd; для контейнеров лучше отдельный процесс на контейнер или корректный init.
3. **Наблюдаемость.** Добавить журналирование ошибок uptime-скрипта и мониторинг доступности `/service_data`.
4. **Безопасность записи JSON.** Если состояние могут изменять несколько процессов одновременно, добавить синхронизацию и явно определить единственный источник истины для поля `title`.
5. **Автоматические интеграционные тесты.** Дополнить сценариями восстановления после пустого/повреждённого JSON, перезапуска служб и длительной работы cron.


