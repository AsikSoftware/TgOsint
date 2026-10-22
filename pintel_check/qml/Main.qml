// Киоск Pintel Проверки. Экран видят клиенты: ничего «программистского».
// Логика в backend.py — здесь только отображение готовых строк.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    visible: true
    visibility: Window.FullScreen
    title: "Pintel Проверка"
    color: "#0C2440"

    // F11 — выйти из полного экрана (на точке обычно не нужно)
    Shortcut { sequence: "F11"; onActivated:
        win.visibility = (win.visibility === Window.FullScreen)
                         ? Window.Maximized : Window.FullScreen }

    // палитра
    readonly property color navy:  "#1A549D"
    readonly property color deep:  "#0C2440"
    readonly property color mid:   "#123C74"
    readonly property color sky:   "#2BA4DB"
    readonly property color canvasBg: "#F2F6FA"
    readonly property color ink:   "#122A44"
    readonly property color muted: "#5B7392"
    readonly property color line:  "#DCE6F0"
    readonly property color ok:    "#0F7F70"
    readonly property color warn:  "#A8671A"
    readonly property color bad:   "#C0352B"

    property string page: "main"     // main | settings | stage2 | stage3

    function toneColor(t) {
        return t === "ok" ? ok : t === "warn" ? warn : t === "bad" ? bad : ink
    }

    // ───────── кнопка в фирменном стиле ─────────
    component PBtn: Button {
        id: pb
        property bool secondary: false
        property color fg: secondary ? win.ink : "white"
        padding: 14
        leftPadding: 24; rightPadding: 24
        font.pixelSize: 17; font.bold: true
        contentItem: Text {
            text: pb.text; color: pb.fg
            font: pb.font; horizontalAlignment: Text.AlignHCenter
        }
        background: Rectangle {
            radius: 14
            color: pb.secondary ? "white" : (pb.down ? win.mid : win.navy)
            border.width: pb.secondary ? 1.5 : 0
            border.color: pb.down ? win.navy : win.line
            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }

    component Card: Rectangle {
        color: "white"; radius: 18
        border.width: 1.5; border.color: win.line
    }

    component RowLine: RowLayout {
        property string k; property string v; property string tone: ""
        Layout.fillWidth: true; spacing: 14
        Text { text: k; color: win.muted; font.pixelSize: 16
               Layout.preferredWidth: 180; wrapMode: Text.Wrap }
        Text { text: v; color: win.toneColor(tone); font.pixelSize: 16
               font.bold: true; Layout.fillWidth: true
               horizontalAlignment: Text.AlignRight; wrapMode: Text.Wrap }
    }

    component AlertBox: Rectangle {
        property string kind: "info"; property alias text: at.text
        Layout.fillWidth: true
        radius: 14
        implicitHeight: at.implicitHeight + 26
        color: kind === "bad" ? "#FBECEA" : kind === "warn" ? "#FDF3E3" : "#E8F4FB"
        border.width: 1.5
        border.color: kind === "bad" ? "#E8A9A3" : kind === "warn" ? "#E8C68C" : "#B8DEF2"
        Text { id: at; anchors.fill: parent; anchors.margins: 13
               color: kind === "bad" ? "#8E2219" : kind === "warn" ? "#7A4A12" : "#0F6B96"
               font.pixelSize: 16; font.bold: true; wrapMode: Text.Wrap
               verticalAlignment: Text.AlignVCenter }
    }

    // ═════════ ТЁМНАЯ СЦЕНА: ожидание / чтение ═════════
    Rectangle {
        anchors.fill: parent
        visible: page === "main" && (backend.state === "idle"
                 || backend.state === "reading" || backend.state === "error")
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0A1E38" }
            GradientStop { position: 0.55; color: win.deep }
            GradientStop { position: 1.0; color: win.mid }
        }

        // мягкое «свечение» за логотипом
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height) * 0.72
            height: width; radius: width / 2
            color: win.navy; opacity: 0.25
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { to: 0.38; duration: 2600; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.22; duration: 2600; easing.type: Easing.InOutSine }
            }
        }

        // ── ожидание телефона ──
        Column {
            anchors.centerIn: parent
            spacing: 42
            visible: backend.state === "idle"

            Rectangle {   // логотип на весь центр
                id: logoCard
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(win.width * 0.46, 660)
                height: width * 0.42
                radius: 34; color: "white"
                Image {
                    anchors.centerIn: parent
                    source: logoUrl
                    width: parent.width * 0.78
                    fillMode: Image.PreserveAspectFit
                    smooth: true; mipmap: true
                }
                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    NumberAnimation { to: 1.03; duration: 2600; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0;  duration: 2600; easing.type: Easing.InOutSine }
                }
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 14
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Подключите iPhone кабелем"
                    color: "white"; font.pixelSize: 34; font.bold: true
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 10
                    Repeater {
                        model: 3
                        Rectangle {
                            width: 12; height: 12; radius: 6; color: win.sky
                            SequentialAnimation on opacity {
                                loops: Animation.Infinite
                                PauseAnimation { duration: index * 280 }
                                NumberAnimation { to: 0.15; duration: 420 }
                                NumberAnimation { to: 1.0;  duration: 420 }
                                PauseAnimation { duration: (2 - index) * 280 }
                            }
                        }
                    }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Проверка начнётся сама — это около минуты"
                    color: "#9FB8D8"; font.pixelSize: 19
                }
            }
        }

        // ── чтение телефона ──
        Column {
            anchors.centerIn: parent
            spacing: 36
            visible: backend.state === "reading"

            Item {   // вращающаяся дуга
                anchors.horizontalCenter: parent.horizontalCenter
                width: 120; height: 120
                Canvas {
                    id: arc
                    anchors.fill: parent
                    onPaint: {
                        var c = getContext("2d")
                        c.reset()
                        c.lineWidth = 9; c.lineCap = "round"
                        c.strokeStyle = win.sky
                        c.beginPath()
                        c.arc(width/2, height/2, width/2 - 8, 0, Math.PI * 1.35)
                        c.stroke()
                    }
                }
                RotationAnimator on rotation {
                    loops: Animation.Infinite; from: 0; to: 360; duration: 1100
                }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Читаю телефон…"
                color: "white"; font.pixelSize: 34; font.bold: true
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Не отключайте кабель. Обычно 20–40 секунд."
                color: "#9FB8D8"; font.pixelSize: 19
            }
        }

        // ── ошибка чтения ──
        Column {
            anchors.centerIn: parent
            spacing: 24
            width: Math.min(win.width * 0.6, 820)
            visible: backend.state === "error"
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Не получилось прочитать телефон"
                color: "white"; font.pixelSize: 30; font.bold: true
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: backend.errorText + "\nПереподключите кабель — попробую снова."
                color: "#9FB8D8"; font.pixelSize: 18; wrapMode: Text.Wrap
            }
        }

        // статус и шестерёнка
        Row {
            anchors.bottom: parent.bottom; anchors.left: parent.left
            anchors.margins: 26; spacing: 10
            visible: backend.state === "idle"
            Rectangle { width: 10; height: 10; radius: 5
                        anchors.verticalCenter: parent.verticalCenter
                        color: backend.phoneSeen ? win.ok : "#44608A" }
            Text { text: backend.phoneSeen ? "кабель вижу, жду «Доверять»" : "служба готова"
                   color: "#7E9BC2"; font.pixelSize: 15 }
        }
        Button {
            anchors.top: parent.top; anchors.right: parent.right
            anchors.margins: 22
            visible: backend.state === "idle"
            flat: true
            contentItem: Text { text: "⚙"; color: "#7E9BC2"; font.pixelSize: 30 }
            background: Rectangle { color: "transparent" }
            onClicked: { backend.checkDrivers(); page = "settings" }
        }
    }

    // ═════════ СВЕТЛАЯ СЦЕНА: результат ═════════
    Rectangle {
        anchors.fill: parent
        color: win.canvasBg
        visible: page === "main" && (backend.state === "result" || backend.state === "done")

        Flickable {
            anchors.fill: parent
            contentWidth: width
            contentHeight: col.height + 70
            clip: true

            ColumnLayout {
                id: col
                width: Math.min(parent.width - 60, 1180)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 28; spacing: 16

                // шапка: модель + итог
                RowLayout {
                    Layout.fillWidth: true; spacing: 18
                    Image { source: logoUrl; Layout.preferredHeight: 34
                            fillMode: Image.PreserveAspectFit; mipmap: true }
                    Text {
                        text: backend.result["модель"] ? backend.result["модель"]
                              + "  ·  " + backend.result["память"] : ""
                        color: win.ink; font.pixelSize: 26; font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        radius: 999
                        color: backend.result["итог"]
                               ? (backend.result["итог"].tone === "ok" ? "#E7F5F2"
                                  : backend.result["итог"].tone === "bad" ? "#FBECEA" : "#FDF3E3")
                               : "#E7F5F2"
                        implicitHeight: 42; implicitWidth: vt.implicitWidth + 40
                        Text { id: vt; anchors.centerIn: parent
                               text: backend.result["итог"] ? backend.result["итог"].вердикт : ""
                               color: backend.result["итог"]
                                      ? win.toneColor(backend.result["итог"].tone) : win.ok
                               font.pixelSize: 18; font.bold: true }
                    }
                }

                // цена — главное, крупно
                Card {
                    Layout.fillWidth: true
                    implicitHeight: priceCol.height + 44
                    ColumnLayout {
                        id: priceCol
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 22
                        spacing: 8
                        Repeater {
                            model: backend.priceInfo["отказ"] || []
                            AlertBox { kind: "bad"; text: modelData }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: backend.priceInfo["ready"] === true
                            Column {
                                spacing: 2
                                Text { text: "Предварительная оценка"
                                       color: win.muted; font.pixelSize: 16 }
                                Text { text: backend.priceInfo["итого"] || ""
                                       color: win.ok; font.pixelSize: 58; font.bold: true }
                            }
                            Item { Layout.fillWidth: true }
                            Column {
                                spacing: 4
                                Text { text: "база " + (backend.priceInfo["база"] || "")
                                       color: win.muted; font.pixelSize: 15
                                       horizontalAlignment: Text.AlignRight }
                                Repeater {
                                    model: backend.priceInfo["вычеты"] || []
                                    Text { text: modelData.k + "  " + modelData.v
                                           color: win.bad; font.pixelSize: 15
                                           horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }
                        Repeater {
                            model: backend.priceInfo["ready"] ? []
                                   : (backend.priceInfo["нехватка"] || [])
                            AlertBox { kind: "warn"; text: modelData }
                        }
                    }
                }

                // просьба зайти в «Запчасти и историю обслуживания»
                Rectangle {
                    Layout.fillWidth: true
                    visible: backend.appleInfo["state"] === "wait"
                    radius: 18; color: win.navy
                    implicitHeight: aCol.height + 40
                    ColumnLayout {
                        id: aCol
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 20
                        spacing: 6
                        RowLayout {
                            spacing: 12
                            Rectangle { width: 12; height: 12; radius: 6; color: win.sky
                                SequentialAnimation on opacity {
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 0.2; duration: 500 }
                                    NumberAnimation { to: 1.0; duration: 500 }
                                } }
                            Text { text: "Один шаг на телефоне — вердикт самой Apple"
                                   color: "white"; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            PBtn { text: "Пропустить"; secondary: true; padding: 8
                                   leftPadding: 16; rightPadding: 16
                                   font.pixelSize: 14
                                   onClicked: backend.skipApple() }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Настройки → Основные → Об этом устройстве → зайдите в «Запчасти и история обслуживания».\nВажен именно переход внутрь: если экран уже открыт — выйдите и зайдите снова. Я слушаю."
                            color: "#CFE2F5"; font.pixelSize: 16; wrapMode: Text.Wrap
                        }
                    }
                }

                // предупреждения
                Repeater {
                    model: backend.result["alerts"] || []
                    AlertBox { kind: modelData.kind; text: modelData.text }
                }
                Repeater {
                    model: (backend.sickwInfo["alerts"]) || []
                    AlertBox { kind: modelData.kind; text: modelData.text }
                }

                // карточки с данными
                GridLayout {
                    Layout.fillWidth: true
                    columns: width > 900 ? 2 : 1
                    columnSpacing: 16; rowSpacing: 16

                    Repeater {
                        model: backend.result["cards"] || []
                        Card {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            implicitHeight: cc.height + 40
                            ColumnLayout {
                                id: cc
                                anchors.left: parent.left; anchors.right: parent.right
                                anchors.top: parent.top; anchors.margins: 20
                                spacing: 9
                                Text { text: modelData.title.toUpperCase()
                                       color: win.muted; font.pixelSize: 13
                                       font.bold: true; font.letterSpacing: 1.2 }
                                Repeater {
                                    model: modelData.rows
                                    RowLine { k: modelData.k; v: modelData.v
                                              tone: modelData.tone }
                                }
                            }
                        }
                    }

                    // вердикт Apple
                    Card {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        visible: backend.appleInfo["state"] === "got"
                        implicitHeight: apc.height + 40
                        ColumnLayout {
                            id: apc
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.top: parent.top; anchors.margins: 20
                            spacing: 9
                            Text { text: "ВЕРДИКТ APPLE"; color: win.muted
                                   font.pixelSize: 13; font.bold: true
                                   font.letterSpacing: 1.2 }
                            Repeater {
                                model: backend.appleInfo["rows"] || []
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone }
                            }
                        }
                    }

                    // внешняя база
                    Card {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        visible: backend.sickwInfo["state"] !== "off"
                        implicitHeight: skc.height + 40
                        ColumnLayout {
                            id: skc
                            anchors.left: parent.left; anchors.right: parent.right
                            anchors.top: parent.top; anchors.margins: 20
                            spacing: 9
                            Text { text: "ВНЕШНЯЯ БАЗА"; color: win.muted
                                   font.pixelSize: 13; font.bold: true
                                   font.letterSpacing: 1.2 }
                            Text { visible: backend.sickwInfo["state"] === "wait"
                                   text: "Проверяю по базе Apple GSX…"
                                   color: win.muted; font.pixelSize: 16 }
                            Text { visible: backend.sickwInfo["state"] === "nokey"
                                   text: "Ключ Sickw не задан (⚙ Настройки)"
                                   color: win.warn; font.pixelSize: 16 }
                            Text { visible: backend.sickwInfo["state"] === "error"
                                   text: backend.sickwInfo["msg"] || ""
                                   color: win.bad; font.pixelSize: 15
                                   wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Repeater {
                                model: backend.sickwInfo["rows"] || []
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone }
                            }
                        }
                    }
                }

                // действия
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    spacing: 14
                    PBtn { text: "Ручные проверки →"; onClicked: page = "stage2" }
                    PBtn { text: "Завершить приёмку"; secondary: true
                           onClicked: page = "stage3" }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        // «готово» после этапа 3
        Rectangle {
            anchors.fill: parent
            visible: backend.state === "done"
            color: "#D9000000"
            Column {
                anchors.centerIn: parent
                spacing: 20
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "✓"; color: win.ok; font.pixelSize: 110; font.bold: true }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "Приёмка завершена и записана"
                       color: "white"; font.pixelSize: 30; font.bold: true }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "Отключите телефон — экран вернётся сам"
                       color: "#9FB8D8"; font.pixelSize: 18 }
            }
        }
    }

    // ═════════ ЭТАП 2: ручные проверки ═════════
    Rectangle {
        id: stage2Root
        anchors.fill: parent
        color: win.canvasBg
        visible: page === "stage2"
        property var marks: ({})

        Flickable {
            anchors.fill: parent
            contentWidth: width; contentHeight: s2col.height + 70; clip: true
            ColumnLayout {
                id: s2col
                width: Math.min(parent.width - 60, 980)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 28; spacing: 16
                Text { text: "Ручные проверки"; color: win.ink
                       font.pixelSize: 30; font.bold: true }
                Text { text: "Отметьте найденные проблемы. Веб-тест на телефоне: barcode-scan.duckdns.org/apps/diag.html"
                       color: win.muted; font.pixelSize: 16; wrapMode: Text.Wrap
                       Layout.fillWidth: true }

                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: backend.manualChecks
                        Rectangle {
                            property bool on: false
                            width: chipText.implicitWidth + 36; height: 48
                            radius: 14
                            color: on ? "#E8F4FB" : "white"
                            border.width: 1.5
                            border.color: on ? win.navy : win.line
                            Text { id: chipText; anchors.centerIn: parent
                                   text: modelData.label
                                   color: on ? win.navy : win.ink
                                   font.pixelSize: 15; font.bold: true }
                            MouseArea { anchors.fill: parent
                                onClicked: { parent.on = !parent.on
                                             stage2Root.marks[modelData.key] = parent.on } }
                        }
                    }
                }

                Card {
                    Layout.fillWidth: true
                    implicitHeight: fcol.height + 40
                    ColumnLayout {
                        id: fcol
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 20
                        spacing: 10
                        Text { text: "Цвет аппарата (по кабелю не определяется)"
                               color: win.muted; font.pixelSize: 15 }
                        TextField { id: colourField; Layout.fillWidth: true
                                    font.pixelSize: 17
                                    placeholderText: "чёрный, синий, титан…" }
                        Text { text: "Заметки приёмщика"
                               color: win.muted; font.pixelSize: 15 }
                        TextArea { id: notesField; Layout.fillWidth: true
                                   font.pixelSize: 16
                                   implicitHeight: 90
                                   background: Rectangle { radius: 12
                                       border.width: 1.5; border.color: win.line } }
                    }
                }

                RowLayout {
                    spacing: 14
                    PBtn { text: "Сохранить → финал"
                           onClicked: {
                               backend.saveStage2(stage2Root.marks,
                                                  colourField.text, notesField.text)
                               page = "stage3"
                           } }
                    PBtn { text: "← Назад"; secondary: true
                           onClicked: page = "main" }
                }
            }
        }
    }

    // ═════════ ЭТАП 3: финал ═════════
    Rectangle {
        anchors.fill: parent
        color: win.canvasBg
        visible: page === "stage3"
        ColumnLayout {
            width: Math.min(parent.width - 60, 760)
            anchors.centerIn: parent
            spacing: 16
            Text { text: "Финал приёмки"; color: win.ink
                   font.pixelSize: 30; font.bold: true }
            Card {
                Layout.fillWidth: true
                implicitHeight: f3.height + 44
                ColumnLayout {
                    id: f3
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.top: parent.top; anchors.margins: 22
                    spacing: 12
                    RowLine { k: "Аппарат"
                              v: (backend.result["модель"] || "") + " " +
                                 (backend.result["память"] || "") }
                    RowLine { k: "Предварительная цена"
                              v: backend.priceInfo["итого"] || "—"; tone: "ok" }
                    Text { text: "Итоговая цена, согласованная с клиентом"
                           color: win.muted; font.pixelSize: 15 }
                    TextField { id: finalPrice; Layout.fillWidth: true
                                font.pixelSize: 24; font.bold: true
                                inputMethodHints: Qt.ImhDigitsOnly
                                placeholderText: "сумма в тенге" }
                    RowLayout {
                        spacing: 10
                        Repeater {
                            model: ["Выкуп", "Trade-In"]
                            Rectangle {
                                property bool on: index === 0
                                width: 130; height: 46; radius: 14
                                color: on ? win.navy : "white"
                                border.width: 1.5
                                border.color: on ? win.navy : win.line
                                Text { anchors.centerIn: parent; text: modelData
                                       color: parent.on ? "white" : win.ink
                                       font.pixelSize: 15; font.bold: true }
                                MouseArea { anchors.fill: parent
                                    onClicked: {
                                        for (var i = 0; i < parent.parent.children.length; i++)
                                            if (parent.parent.children[i].on !== undefined)
                                                parent.parent.children[i].on = false
                                        parent.on = true
                                        win.buyMethod = modelData
                                    } }
                            }
                        }
                    }
                }
            }
            RowLayout {
                spacing: 14
                PBtn { text: "Завершить приёмку"
                       onClicked: { backend.saveStage3(finalPrice.text, win.buyMethod)
                                    page = "main" } }
                PBtn { text: "← Назад"; secondary: true; onClicked: page = "main" }
            }
        }
    }
    property string buyMethod: "Выкуп"

    // ═════════ НАСТРОЙКИ ═════════
    Rectangle {
        anchors.fill: parent
        color: win.canvasBg
        visible: page === "settings"
        Flickable {
            anchors.fill: parent
            contentWidth: width; contentHeight: stCol.height + 70; clip: true
            ColumnLayout {
                id: stCol
                width: Math.min(parent.width - 60, 900)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 28; spacing: 16

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Настройки"; color: win.ink
                           font.pixelSize: 30; font.bold: true }
                    Item { Layout.fillWidth: true }
                    PBtn { text: "← К работе"; secondary: true
                           onClicked: page = "main" }
                }

                // прайс
                Card {
                    Layout.fillWidth: true
                    implicitHeight: prc.height + 40
                    ColumnLayout {
                        id: prc
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 20
                        spacing: 10
                        Text { text: "ПРАЙС ИЗ GOOGLE ТАБЛИЦЫ"; color: win.muted
                               font.pixelSize: 13; font.bold: true; font.letterSpacing: 1.2 }
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            font.pixelSize: 15
                            color: backend.settingsInfo["обновлён"] ? win.ok : win.warn
                            text: backend.settingsInfo["обновлён"]
                                  ? "Обновлён " + backend.settingsInfo["обновлён"]
                                    + " · моделей: " + backend.settingsInfo["моделей"]
                                  : "Прайс ещё не загружался из таблицы"
                        }
                        Text {
                            visible: !!backend.settingsInfo["sa_email"]
                            Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                            font.pixelSize: 14; color: win.muted
                            text: "Сервис-аккаунт (поделитесь таблицей с ним): "
                                  + backend.settingsInfo["sa_email"]
                        }
                        Text {
                            visible: !backend.settingsInfo["sa_email"]
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            font.pixelSize: 14; color: win.muted
                            text: "Файл gservice.json не найден рядом с программой — работаю через открытую ссылку. Положите ключ сервис-аккаунта, чтобы таблица осталась закрытой."
                        }
                        TextField { id: sheetUrl; Layout.fillWidth: true
                                    font.pixelSize: 14
                                    text: backend.settingsInfo["sheet_url"] || "" }
                        PBtn { text: "Обновить прайс из таблицы"
                               onClicked: backend.syncPrices(sheetUrl.text) }
                        Text {
                            visible: backend.syncInfo["state"] !== "off"
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            font.pixelSize: 15
                            color: backend.syncInfo["state"] === "error" ? win.bad
                                   : backend.syncInfo["state"] === "ok" ? win.ok : win.muted
                            text: backend.syncInfo["msg"] || ""
                        }
                    }
                }

                // sickw
                Card {
                    Layout.fillWidth: true
                    implicitHeight: skSet.height + 40
                    ColumnLayout {
                        id: skSet
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 20
                        spacing: 10
                        Text { text: "КЛЮЧ SICKW"; color: win.muted
                               font.pixelSize: 13; font.bold: true; font.letterSpacing: 1.2 }
                        Text {
                            font.pixelSize: 15
                            color: backend.settingsInfo["sickw_tail"] ? win.ok : win.warn
                            text: backend.settingsInfo["sickw_tail"]
                                  ? "Ключ стоит: ····" + backend.settingsInfo["sickw_tail"]
                                  : "Ключ не задан — внешняя база выключена"
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            TextField { id: keyField; Layout.fillWidth: true
                                        font.pixelSize: 14
                                        placeholderText: "ключ API с sickw.com" }
                            PBtn { text: "Сохранить"
                                   onClicked: { backend.saveSickwKey(keyField.text)
                                                keyField.text = "" } }
                        }
                        PBtn { text: "Убрать ключ"; secondary: true
                               visible: !!backend.settingsInfo["sickw_tail"]
                               onClicked: backend.removeSickwKey() }
                    }
                }

                // драйверы
                Card {
                    Layout.fillWidth: true
                    implicitHeight: drv.height + 40
                    ColumnLayout {
                        id: drv
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.top: parent.top; anchors.margins: 20
                        spacing: 9
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "ДРАЙВЕРЫ И ИНСТРУМЕНТЫ"; color: win.muted
                                   font.pixelSize: 13; font.bold: true
                                   font.letterSpacing: 1.2 }
                            Item { Layout.fillWidth: true }
                            PBtn { text: "Проверить"; secondary: true; padding: 8
                                   leftPadding: 16; rightPadding: 16; font.pixelSize: 14
                                   onClicked: backend.checkDrivers() }
                        }
                        Text { visible: backend.drivers["state"] === "wait"
                               text: "Проверяю…"; color: win.muted; font.pixelSize: 15 }
                        Text { visible: !!backend.drivers["итог"]
                               text: backend.drivers["итог"]; font.pixelSize: 15
                               font.bold: true
                               color: backend.drivers["итог"] === "Всё готово." ? win.ok : win.warn }
                        Repeater {
                            model: backend.drivers["items"] || []
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 2
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone }
                                Text { visible: !!modelData.fix
                                       text: modelData.fix; color: win.muted
                                       font.pixelSize: 13; wrapMode: Text.Wrap
                                       Layout.fillWidth: true }
                            }
                        }
                    }
                }

                PBtn { text: "Закрыть программу"; secondary: true
                       onClicked: Qt.quit() }
            }
        }
    }
}
