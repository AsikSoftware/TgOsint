---
name: iphone-part-pairing-checks
description: Четыре сверки сопряжения деталей iPhone по кабелю — сильнее серийников, их нельзя подделать без перепрошивки платы.
metadata:
  type: reference
---

Проверено побайтно на четырёх аппаратах (два iPhone 12, iPhone 14 Pro, iPhone 15,2).
Эти сверки сильнее проверки «серийник есть»: серийник можно прочитать с донорской
детали, а сопряжение — нет.

**Face ID.** `SavageSNUM[4:12] == FrontIRCameraSerialNumber` в записи камеры
(`AppleH13CamIn` / `AppleH10CamIn` / `AppleCamera` / `AppleH16CamIn`). Ловит даже
камеру, переставленную с другого живого iPhone. Сверять ТОЛЬКО это равенство:
`SavageDeviceID` и `SavageDeviceRev` — константы семейства чипа, различаются между
поколениями (`SavageNVMRev` = 0xaa на iPhone 12 и 0x00 на iPhone 14 Pro) и их
порядок байтов тоже непостоянен, так что их сверка даёт ложные срабатывания.

**Taptic Engine.** `AppleHapticsSupportArcEEPROM/ArcSerialNumber` (сторона модуля)
должен входить в `haptics-support-interface/pscl-cal` (сторона платы).

**Экран.** `product/coverglass-serial-number` (без хвостовых нулей) входит в
`product/raw-panel-serial-number`.

**Память.** Объём сходится в трёх местах: `AppleANS3NVMeController` (или ANS2 на
A13 и старше) `Controller Characteristics/capacity`, число в `Model Number`
(`APPLE SSD AP0064Z`) и `DOMAIN:com.apple.disk_usage/TotalDiskCapacity`.

**Прочее.** `BatteryCellDisconnectCount` — сколько раз снимали шлейф батареи,
признак вскрытия. `product/rosaline-serial-num` == `AppleProxHIDEventDriver/SerialNumber`.
Заводская ёмкость батареи одна на модель (iPhone13,2 = 2798, а не рекламные 2815).

**Why:** добыто перебором 48 тысяч значений и сравнением аппаратов; заново это
несколько часов.

**How to apply:** см. [[iphone-cable-parts-verdict]] про закрытые каналы.
Любая правка правил проверяется `~/Downloads/regress.sh` — он прогоняет логику
по всем собранным описям без телефонов и за один запуск ловил по три дефекта.
Подлинность фронтальной RGB-камеры по кабелю НЕ устанавливается: привязка
покрывает только ИК-камеру Face ID.
