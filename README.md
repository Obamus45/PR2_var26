# Вариант 26 — этапы 1–4

CLI-приложение на Python читает YAML-конфигурацию и анализирует граф зависимостей Ubuntu APT. Сетевые метаданные получаются и разбираются собственным кодом на стандартной библиотеке Python — без запуска `apt` и сторонних библиотек для получения зависимостей.

## Параметры YAML

| Ключ | Назначение |
|---|---|
| `package_name` | Имя корневого пакета |
| `repository` | URL APT suite/index или путь к тестовому графу |
| `test_mode` | `true` — читать локальный тестовый граф; `false` — обращаться к APT-репозиторию |
| `output_file` | Имя SVG-файла (понадобится на этапе визуализации) |
| `ascii_tree` | Флаг ASCII-дерева (понадобится на этапе визуализации) |
| `filter_substring` | Исключить узлы, имя которых содержит подстроку; пустая строка отключает фильтр |
| `reverse_dependencies` | `true` — вывести обратные зависимости; необязательный параметр, по умолчанию `false` |

Для обратной совместимости старые YAML-файлы без `reverse_dependencies` продолжают работать как раньше. Если параметр задан, он должен быть YAML boolean `true` или `false`.

## Запуск

Нужен Python 3.10+ и PyYAML для YAML-конфигурации.

```bash
python -m pip install -r requirements.txt
python app.py
python app.py --config config-reverse.yaml
```

## Этапы 3–4: алгоритмы

- Обычный режим строит транзитивный граф зависимостей обходом в ширину. Очередь обрабатывается рекурсивно; множество `visited` предотвращает повторный обход циклов. Циклические рёбра остаются в графе.
- Если `reverse_dependencies: true`, программа инвертирует все рёбра репозитория и тем же BFS обходит граф от заданного пакета. Выводятся прямые и транзитивные пакеты, которые зависят от корневого.
- `filter_substring` применяется в обоих режимах: совпавшие пакеты исключаются и не обходятся. Если фильтр совпадает с корневым пакетом, выводится ошибка.
- В APT-режиме обратный поиск требует построить индекс всех рёбер: для URL suite загружаются `Packages`-индексы его компонентов, после чего граф инвертируется. Если передан URL только одного Packages-файла, результат ограничен пакетами этого индекса.
- Альтернативы APT вида `foo | foo-compat` считаются потенциальными рёбрами для обоих вариантов; конкретный provider не выбирается.

## Тестовый режим

В тестовом режиме `repository` — путь к файлу ориентированного графа. Формат строки: `ПАКЕТ: ЗАВИСИМОСТЬ1, ЗАВИСИМОСТЬ2`; имена — большие латинские буквы. Пакет без зависимостей указывается как `E:`. Строки, начинающиеся с `#`, — комментарии. Узел, упомянутый только как зависимость, считается листом.

Файл `test-repository.txt` содержит ромб с циклом (`A -> B,C`, `B -> D`, `C -> D,E`, `D -> A`), цепочку (`F -> G`) и петлю (`H -> H`). Демонстрации:

```bash
python app.py --config config.yaml                 # BFS, ромб и цикл
python app.py --config config-chain.yaml            # обычный обход цепочки
python app.py --config config-self-cycle.yaml       # обычный обход самопетли
python app.py --config config-filter.yaml           # обычный BFS с фильтром C
python app.py --config config-reverse.yaml          # обратный BFS от B, цикл
python app.py --config config-reverse-chain.yaml    # кто зависит от G?
python app.py --config config-reverse-filter.yaml   # обратный BFS с фильтром D
```

Для `config-reverse.yaml` прямой обратный сосед `B` — `A`; далее обход обнаруживает `D` и `C`. Цикл `B -> A -> D -> B` отображается, но повторного обхода узлов нет.

## Реальный Ubuntu APT-репозиторий

`config-ubuntu.example.yaml` показывает обычный обход зависимостей `bash`; `config-ubuntu-reverse.example.yaml` — обратный обход в индексе Noble:

```bash
python app.py --config config-ubuntu.example.yaml
python app.py --config config-ubuntu-reverse.example.yaml
```

Для прямого reverse-примера проверенный результат: `bash <- gdm3 <- ubuntu-desktop` (также `ubuntu-desktop-minimal` зависит от `gdm3`). Укажите URL suite, например `https://archive.ubuntu.com/ubuntu/dists/noble/`, или прямой URL `Packages`/`Packages.gz`/`Packages.xz`/`Packages.bz2`. Для suite программа читает `Release`, берёт компоненты и предпочитает `amd64`. URL корня зеркала без `/dists/<suite>/` не сообщает выпуск Ubuntu.

## Проверки

```bash
python -m unittest -v
```

Автотесты покрывают YAML-валидацию, разбор APT Packages, построение прямого и обратного списка смежности, BFS-порядок, фильтрацию, листья и циклы.

## Коммиты

- Этап 1: `feat: add YAML-configured CLI prototype for variant 26 stage 1`
- Этап 2: `feat: fetch direct Ubuntu APT dependencies from Packages indexes`
- Этап 3: `feat: build recursive BFS dependency graph with filtering`
- Этап 4: `feat: list transitive reverse dependencies with BFS`
