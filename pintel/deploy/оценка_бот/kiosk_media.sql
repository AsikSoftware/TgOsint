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

-- Сделка приходит в эти колонки, а не кнопкой под карточкой в Telegram.
-- Как было: программа слала посылку файлом в чат, и бот получал её ТОЛЬКО когда кто-то
-- нажимал кнопку (свои исходящие сообщения бот не видит). Чат мог оказаться недоступен —
-- «bot was blocked by the user», «chat not found», — и тогда сделку нельзя было создать
-- вовсе: сотрудник стоял с телефоном клиента в руках. Теперь посылку кладёт сюда наш
-- сервер (он рядом с этой базой), а бот забирает её отсюда и создаёт сделку сам.
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS parcel TEXT;          -- JSON посылки, ждёт бота
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS parcel_at TIMESTAMPTZ; -- когда положили
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS parcel_error TEXT;    -- почему не создалась — видно на кассе

-- бот спрашивает её часто: «есть ли непринятые посылки»
CREATE INDEX IF NOT EXISTS kiosk_media_parcel_idx ON kiosk_media (parcel_at)
    WHERE parcel IS NOT NULL;

-- Порядок с 12.11.2026: привязка сотрудника в начале сделки, автоцена ДО сделки, медиа —
-- после «Отправить на оценку» на кассе.
--   quote_request — касса просит цену: та же посылка, что потом станет сделкой. Кладёт её наш
--                   сервер, бот забирает (как и parcel) и считает своим прайсом.
--   quote         — ответ бота: {"цена": 185000 | null, "почему": "…", "запрос": "<метка>"}.
--   media_asked   — когда бот сам попросил у привязанного сотрудника фото и видео. По ней он
--                   не просит дважды и после перезапуска знает, от кого ждёт медиа.
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS quote_request TEXT;
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS quote_at TIMESTAMPTZ;
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS quote TEXT;
ALTER TABLE kiosk_media ADD COLUMN IF NOT EXISTS media_asked TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS kiosk_media_quote_idx ON kiosk_media (quote_at)
    WHERE quote_request IS NOT NULL;
-- «от кого ждём медиа» бот спрашивает по чату сотрудника
CREATE INDEX IF NOT EXISTS kiosk_media_chat_idx ON kiosk_media (chat_id)
    WHERE device_id IS NULL;
