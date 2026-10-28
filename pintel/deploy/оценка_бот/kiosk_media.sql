-- Обмен медиа между приложением на точке и ботом Оценки.
-- Одна таблица, код Оценки её не трогает. Ставить сначала на pintel_ocenka_test.
CREATE TABLE IF NOT EXISTS kiosk_media (
    id        SERIAL PRIMARY KEY,
    code      VARCHAR(16) UNIQUE NOT NULL,     -- то, что уходит в ссылку: /start p<code>
    point     VARCHAR(50),                     -- точка, где завели код
    created   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id   INTEGER REFERENCES users (id),   -- кто открыл ссылку = оценщик сделки
    chat_id   BIGINT,
    video     VARCHAR(200),                    -- file_id видео: без него сделка не открывается
    photos    TEXT,                            -- file_id фото через «||», как в devices.photo_phone
    done      BOOLEAN NOT NULL DEFAULT false,
    device_id INTEGER                          -- проставляется, когда сделка создана
);

CREATE INDEX IF NOT EXISTS kiosk_media_code_idx ON kiosk_media (code);
CREATE INDEX IF NOT EXISTS kiosk_media_created_idx ON kiosk_media (created);
