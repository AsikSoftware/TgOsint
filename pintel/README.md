# Pintel — ядро чтения iPhone и «врач»

Этап 1 новой системы: библиотека `pintel_core` (на ней будут киоск и сервер)
и консольная утилита `pintel-doctor`, которая снимает с телефона полный
сырой слепок, строит отчёт и показывает качество чтения.

## Что это даёт

- **Чтение на pymobiledevice3** — стандарт индустрии, чистый Python. Нужен
  только iTunes (служба Apple Mobile Device). Никаких MSYS2 и bin-папок.
- **Устойчивость к «первому разу»**: ожидание готовности после «Доверять»,
  повторы с паузами, двойное чтение диска с пометкой «первое чтение устарело».
- **Имена узлов не угадываются** — берутся с карты IORegistry самого телефона.
- **Слепок целиком** сохраняется в JSON: любой сбой на новой модели правится
  по файлу, а не по догадке.

## Как пользоваться на Windows

1. Поставьте iTunes с сайта Apple (не из Microsoft Store).
2. Распакуйте `pintel-doctor` из Releases, рядом положите `config.toml`
   (образец — `config.example.toml`) и `gservice.json`.
3. `pintel-doctor selfcheck` — драйвер, ключи, конфиг.
4. Подключите iPhone, разблокируйте, нажмите «Доверять»:
   `pintel-doctor snapshot --apple 120 --sickw`
   — слепок, отчёт, история обслуживания Apple (нужен переход в раздел на
   телефоне), проверка Sickw. Файлы — в `out\<дата>_<серийник>\`.
5. Пришлите папку `out\...` разработчику: `snapshot.json` + `report.txt`.

Другие команды: `wait`, `report файл.json`, `apple`, `sickw IMEI|balance`,
`price`, `fixtures`.

## Разработка

```
pip install -e . pytest
python -m pytest tests -q -s
python -m pintel_core.doctor fixtures
```
