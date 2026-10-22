# Серийники Port-Lightning — это серийники КАБЕЛЯ, не телефона

Проверено 2026-10-21 на трёх разных аппаратах (два iPhone 12 и iPhone 14 Pro),
подключённых ОДНИМ И ТЕМ ЖЕ кабелем:

    Port-Lightning/IORegistry/IOAccessoryAccessorySerialNumber     = FGJ4431GJXMLX7PAQ
    Port-Lightning/IORegistry/IOAccessoryInterfaceModuleSerialNumber = DWH4395BXH6LR7QAU

Значения совпали побайтово на всех трёх. Это физически невозможно для деталей
телефона — значит поля описывают кабель (рядом: IOAccessoryAccessoryName =
"USB-C to Lightning Cable (1m)", ModelNumber = A2561, Manufacturer = Apple, Inc.).

Формат у них ровно такой же 17-символьный, как у настоящих серийников деталей Apple,
поэтому они попадут в любой автоматический сбор серийников и будут меняться
при каждой смене кабеля → ложное "заменён разъём зарядки" на каждой приёмке.

Настоящая деталь телефона здесь: Port-Lightning/IORegistry/TriStarICClass
(= AppleCBTL1614 и на iPhone 12, и на iPhone 14 Pro — то есть слабо различает модели).
