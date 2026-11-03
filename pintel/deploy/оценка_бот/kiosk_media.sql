-- Обмен медиа между приложением на точке и ботом Оценки.
-- Одна таблица, код Оценки её не трогает. Ставить сначала на pintel_ocenka_test.
-- Файл можно запускать повторно: всё, что уже есть, пропускается.
CREATE TABLE IF NOT EXISTS kiosk_media (
    id        SERIAL PRIMARY KEY,
    code      VARCHAR(16) UNIQUE NOT NULL,     -- то, что уходит в ссылку: /start p<code>
    created   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id   INTEGER REFERENCES users (id),   -- кто открыл ссылку = оценщик сделки
    chat_id   BIGINT,
    shop_id   INTEGER REFERENCES shops (id),   -- точка сделки: приходит в посылке с точки
    video     VARCHAR(200),                    -- file_id видео: без него сделка не открывается
    photos    TEXT,                            -- file_id фото через «||», как в devices.photo_phone
    checks    TEXT,                            -- отметки проверок руками (JSON) — только от старых сборок
    done      BOOLEAN NOT NULL DEFAULT false,
    device_id INTEGER                          -- проставляется, когда сделка создана
);

-- для баз, где таблица уже стояла без точки (её больше не выбирают: шлёт программа)
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS shop_id INTEGER REFERENCES shops (id);
-- а колонка `point` (имя точки строкой) не нужна вовсе: её никто не писал с тех пор, как
-- точку присылает программа своим shop_id. В базах, где таблица уже стояла, её убирают
-- руками: ALTER TABLE kiosk_media DROP COLUMN IF EXISTS point;
-- и без отметок проверок руками: {"keys": true, "water": false, …} либо {"sealed": true}.
-- Нужна только точкам со СТАРОЙ сборкой программы: там эти пункты ещё спрашивает бот кнопками.
-- Новая отмечает их на своём экране и присылает в посылке, и обработчик без колонки работает.
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS checks TEXT;

CREATE INDEX IF NOT EXISTS kiosk_media_code_idx ON kiosk_media (code);
CREATE INDEX IF NOT EXISTS kiosk_media_created_idx ON kiosk_media (created);
