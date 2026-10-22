---
name: iphone-cable-parts-verdict
description: Что по кабелю с iPhone доступно и что нет; статусы проверок камеры одинаковы на всех аппаратах и в правила не годятся.
metadata:
  type: reference
---

**Закрытые каналы (не искать заново, проверено 2026-10-21):**
- Вердикт Apple «Запчасти и история обслуживания» по кабелю не отдаётся:
  AppleMobileRepair, RepairState, PartsHistory, ServiceHistory, AppleGenuineParts,
  AppleComponentValidation не отвечают; lockdown-домены по словам
  repair/service/genuine/part/replace пустые.
- MobileGestalt закрыт целиком: `idevicediagnostics mobilegestalt` на любой ключ
  возвращает `MobileGestaltDeprecated` с пустым значением.
- `diagnostics NAND` возвращает `NANDInfoDeprecated`.

**Работает:** `ideviceinfo -q ДОМЕН`, `idevicediagnostics ioregentry ИМЯ`,
`idevicediagnostics ioreg ПЛАН`.

**Why:** иначе эти три тупика исследуются заново каждый раз.

**How to apply:** имена записей НЕ угадывать — `ioreg IOService` отдаёт карту со
всеми именами (на iPhone 12 — 868 имён, ответили 701, 48 тысяч значений).
Угадыванием попадало 13 из 80. План — только карта, значений в нём нет
(`regEntry` — числовой id), поэтому каждое имя опрашивается отдельно.

Статусы `*ValidationStatus` в записи камеры в правила НЕ ГОДЯТСЯ. На двух разных
аппаратах (iPhone13,2 и iPhone14,5, разные владельцы) набор совпал символ в символ:
`CmCl=Pass, CmPM=Unknown, FCCl=Invalid, Savage=Pass, Yonkers=Unknown, Romeo=Valid`.
Это константа прошивки, а не признак телефона; правило по `FCCl=Invalid` помечало
бы фронтальную камеру подозрительной у каждого аппарата.

`MaxCapacity` — НЕ процент здоровья батареи, а константа шкалы: равна 100 даже
при 1687 циклах. Здоровье = `NominalChargeCapacity / DesignCapacity`
(на iPhone 12: 2248/2798 = 80%, столько же в Настройках).

Отличить сигнал от константы можно ТОЛЬКО сравнением нескольких аппаратов —
на одном это невидимо. Для этого есть ~/Downloads/compare.sh, харвестер
складывает каждый телефон в папку по UDID. См. [[macos-nema-timeout]].
