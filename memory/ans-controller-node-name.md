---
name: ans-controller-node-name
description: Имя узла NVMe-контроллера в IORegistry зависит от процессора, одного имени не хватает.
metadata:
  type: reference
---

Контроллер накопителя называется по-разному в зависимости от SoC:
`AppleANS2CGNVMeController` (A13), `AppleANS3NVMeController` (A14),
`AppleANS3CGv2Controller` (A15, A16).

**Why:** запрос одного имени молча не находит ничего на половине моделей, и
проверка объёма памяти тихо пропускается — выглядит как «данных нет», хотя
данные есть.

**How to apply:** перебирать весь список, как это сделано для записи камеры
(`AppleH13CamIn` / `AppleH10CamIn` / `AppleCamera` / `AppleH16CamIn`).
Имена для конкретного аппарата всегда можно снять с него самого:
`idevicediagnostics ioreg IOService` отдаёт карту со всеми именами узлов.
См. [[iphone-part-pairing-checks]].
