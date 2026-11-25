#!/bin/bash
# Сборка кассы для мака — прямо на маке, без GitHub.
#
# Зачем: для windows-точек сборку делает GitHub, потому что windows-машины у нас нет. А мак
# есть, и гонять ради него работу на стороне незачем: здесь это три минуты, и программу сразу
# видно живьём (владелец, 25.11.2026).
#
# Запуск из корня репозитория (TgOsint/pintel):
#   tools/build_mac.sh            — метку взять у последнего релиза GitHub
#   tools/build_mac.sh doctor-113 — поставить метку руками
#   tools/build_mac.sh local      — без метки релиза: такая сборка сама не обновляется
#
# Что делает: собирает .app, кладёт внутрь метку сборки, прогоняет самопроверку собранной
# программы (не исходников — сборка doctor-85 ушла на точки без чтения panic full, и поймала
# это только она), проверяет, что внутрь попали оконная часть Qt, шрифты и страница теста
# телефона, и кладёт готовое в ~/Applications.
set -e
cd "$(dirname "$0")/.."

PY="../.venv/bin/python"
APP="dist/pintel-kiosk.app"
TAG="$1"

if [ -z "$TAG" ]; then
  TAG=$(gh release view --repo AsikSoftware/TgOsint --json tagName -q .tagName 2>/dev/null || echo local)
fi

echo "== сборка (метка: $TAG)"
"$PY" -m PyInstaller --clean --noconfirm pintel-kiosk.spec > /tmp/pintel_mac_build.log 2>&1 \
  || { tail -30 /tmp/pintel_mac_build.log; echo "!! сборка не прошла"; exit 1; }

echo "== метка сборки"
"$PY" -c "import json, io, sys; io.open('$APP/Contents/MacOS/build_info.json', 'w', encoding='utf-8').write(json.dumps({'тег': sys.argv[1]}, ensure_ascii=False))" "$TAG"

echo "== самопроверка собранной программы"
OUT=$(mktemp)
"$APP/Contents/MacOS/pintel-kiosk" --selftest "$OUT"
cat "$OUT"
grep -q "не загрузилось: 0" "$OUT" || { echo "!! часть модулей связи с телефоном не грузится"; exit 1; }
rm -f "$OUT"

echo "== что внутри"
for F in "Contents/Frameworks/PySide6/Qt/plugins/platforms/libqcocoa.dylib" \
         "Contents/Resources/pintel_core/assets/diag.html" \
         "Contents/Resources/pintel_kiosk/assets/fonts/Inter-Medium.ttf"; do
  [ -f "$APP/$F" ] || { echo "!! в сборке нет $F"; exit 1; }
done

echo "== ставим в ~/Applications"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/pintel-kiosk.app"
cp -R "$APP" "$HOME/Applications/pintel-kiosk.app"
xattr -dr com.apple.quarantine "$HOME/Applications/pintel-kiosk.app" 2>/dev/null || true

echo
echo "Готово: ~/Applications/pintel-kiosk.app ($(du -sh "$APP" | cut -f1), метка $TAG)"
echo "Запуск: open ~/Applications/pintel-kiosk.app"
