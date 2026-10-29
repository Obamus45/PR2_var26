# Вариант 26 — этап 1: минимальный CLI-прототип

Реализовано приложение на Python, читающее параметры из YAML, проверяющее их и выводящее все настройки в формате `ключ: значение`. На этом этапе загрузки данных о пакетах и построения графа нет.

## Параметры конфигурации

| Ключ YAML | Назначение | Проверка |
|---|---|---|
| `package_name` | Имя анализируемого пакета | Непустое; латинские буквы, цифры, `.`, `+`, `_`, `-` |
| `repository` | URL репозитория либо путь к тестовому файлу | При `test_mode: true` — существующий файл; иначе — URL `http(s)://` |
| `test_mode` | Режим тестового репозитория | Только YAML boolean `true` или `false` |
| `output_file` | Имя файла изображения графа | Только имя файла с расширением `.svg` |
| `ascii_tree` | Выводить ли зависимости ASCII-деревом | Только YAML boolean `true` или `false` |
| `filter_substring` | Подстрока фильтрации | Строка; пустая строка отключает фильтрацию |

Все шесть параметров обязательны. Неизвестные ключи, отсутствующие значения, синтаксические ошибки YAML и ошибки чтения конфигурации приводят к диагностике в stderr и коду завершения `2`.

## Запуск

Нужен Python 3.10+.

```bash
python -m pip install -r requirements.txt
python app.py                 # читает config.yaml из текущего каталога
python app.py --config config.yaml
```

Пример успешного запуска из каталога проекта (значения берутся из `config.yaml`):

```text
package_name: demo-app
repository: ./test-repository.txt
test_mode: true
output_file: dependencies.svg
ascii_tree: true
filter_substring: ''
```

Для обычного режима укажите URL и выключите тестовый режим:

```yaml
package_name: bash
repository: https://archive.ubuntu.com/ubuntu/
test_mode: false
output_file: bash-dependencies.svg
ascii_tree: false
filter_substring: ""
```

## Демонстрация ошибок параметров

Для проверки замените значение соответствующего ключа в конфигурации и запустите `python app.py --config config.yaml`:

- `package_name: "bad name!"` → сообщение о недопустимом имени;
- `repository: ./missing.txt` при `test_mode: true` → сообщение, что тестовый файл не найден;
- `repository: not-a-url` при `test_mode: false` → сообщение о требуемом HTTP(S)-URL;
- `test_mode: "yes"` → ошибка типа, ожидается `true` или `false` без кавычек;
- `output_file: graph.png` (или `output_file: ../graph.svg`) → ошибка имени/расширения;
- `ascii_tree: 1` → ошибка типа, ожидается boolean;
- `filter_substring: 123` → ошибка типа, ожидается строка;
- удалите обязательный ключ или добавьте неизвестный, например `typo: value` → будет указано отсутствующее/неизвестное поле;
- испортите YAML-синтаксис или укажите несуществующий файл конфигурации → отдельная диагностическая ошибка.

## Тесты

```bash
python -m unittest -v
```

Набор проверяет успешную конфигурацию, валидацию каждого пользовательского параметра, а также обязательные и неизвестные ключи.

## Коммит

Предлагаемое сообщение по Conventional Commits: `feat: add YAML-configured CLI prototype for variant 26 stage 1`.
