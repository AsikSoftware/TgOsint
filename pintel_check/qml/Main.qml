// Киоск Pintel Проверки — тёмное стекло в духе iOS.
// Экран видят клиенты: ничего «программистского». Логика в backend.py,
// QML только рисует готовые строки.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    visible: true
    visibility: Window.FullScreen
    title: "Pintel Проверка"
    color: "#061427"

    Shortcut { sequence: "F11"; onActivated:
        win.visibility = (win.visibility === Window.FullScreen)
                         ? Window.Maximized : Window.FullScreen }

    // ───── палитра «стекло на тёмном» ─────
    readonly property color txt:    "#F4F8FD"
    readonly property color mutedC: "#9FB4CF"
    readonly property color dimC:   "#6C83A6"
    readonly property color accent: "#4FC3F7"
    readonly property color okC:    "#37D9A0"
    readonly property color warnC:  "#FFC56F"
    readonly property color badC:   "#FF7A6B"
    readonly property color glass:  Qt.rgba(1, 1, 1, 0.07)
    readonly property color glassHi: Qt.rgba(1, 1, 1, 0.12)
    readonly property color edge:   Qt.rgba(1, 1, 1, 0.14)

    property string page: "main"     // main | settings | stage2 | stage3
    property string buyMethod: "Выкуп"

    function toneColor(t) {
        return t === "ok" ? okC : t === "warn" ? warnC : t === "bad" ? badC : txt
    }

    // часы для стартового экрана
    property string clockStr: ""
    property string dateStr: ""
    Timer {
        interval: 1000; running: true; repeat: true; triggeredOnStart: true
        onTriggered: {
            var d = new Date()
            clockStr = Qt.formatTime(d, "hh:mm")
            dateStr = Qt.locale("ru_RU").toString(d, "dddd, d MMMM")
            dateStr = dateStr.charAt(0).toUpperCase() + dateStr.slice(1)
        }
    }

    // ═════════ компоненты ═════════

    component FadeItem: Item {
        property bool active: false
        anchors.fill: parent
        visible: opacity > 0.01
        opacity: active ? 1 : 0
        scale: active ? 1 : 0.985
        Behavior on opacity { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        Behavior on scale   { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    }

    component GlassCard: Rectangle {
        color: win.glass
        radius: 24
        border.width: 1
        border.color: win.edge
        // блик по верхней грани — то самое «стекло»
        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right
                      leftMargin: parent.radius; rightMargin: parent.radius }
            height: 1; color: Qt.rgba(1, 1, 1, 0.22)
        }
    }

    component GBtn: Button {
        id: gb
        property bool primary: false
        property bool danger: false
        padding: 13; leftPadding: 26; rightPadding: 26
        font.pixelSize: 16; font.bold: true
        scale: gb.down ? 0.965 : 1.0
        Behavior on scale { NumberAnimation { duration: 90 } }
        contentItem: Text {
            text: gb.text
            color: gb.primary ? "#06203A" : (gb.danger ? win.badC : win.txt)
            font: gb.font; horizontalAlignment: Text.AlignHCenter
        }
        background: Rectangle {
            radius: 999
            gradient: gb.primary ? grad : null
            color: gb.primary ? "transparent"
                   : (gb.down ? win.glassHi : win.glass)
            border.width: gb.primary ? 0 : 1
            border.color: gb.danger ? Qt.rgba(1, 0.48, 0.42, 0.45) : win.edge
            Gradient { id: grad
                GradientStop { position: 0; color: "#7ADCFF" }
                GradientStop { position: 1; color: "#2BA4DB" } }
        }
    }

    component GField: TextField {
        color: win.txt
        placeholderTextColor: Qt.rgba(1, 1, 1, 0.32)
        font.pixelSize: 16
        selectionColor: win.accent
        selectedTextColor: "#06203A"
        padding: 13; leftPadding: 16
        background: Rectangle {
            radius: 14; color: Qt.rgba(0, 0, 0, 0.25)
            border.width: 1
            border.color: parent.activeFocus ? win.accent : win.edge
            Behavior on border.color { ColorAnimation { duration: 150 } }
        }
    }

    component SectionTitle: Text {
        font.pixelSize: 13; font.bold: true; font.letterSpacing: 1.6
        color: win.dimC
    }

    component RowLine: RowLayout {
        property string k; property string v; property string tone: ""
        Layout.fillWidth: true; spacing: 14
        Text { text: k; color: win.mutedC; font.pixelSize: 16
               Layout.preferredWidth: 185; wrapMode: Text.Wrap }
        Text { text: v; color: win.toneColor(tone); font.pixelSize: 16
               font.bold: true; Layout.fillWidth: true
               horizontalAlignment: Text.AlignRight; wrapMode: Text.Wrap }
    }

    component AlertBox: Rectangle {
        property string kind: "info"; property alias text: at.text
        Layout.fillWidth: true
        radius: 16
        implicitHeight: at.implicitHeight + 28
        color: kind === "bad" ? Qt.rgba(1, 0.36, 0.30, 0.16)
             : kind === "warn" ? Qt.rgba(1, 0.72, 0.33, 0.14)
             : Qt.rgba(0.31, 0.76, 0.97, 0.13)
        border.width: 1
        border.color: kind === "bad" ? Qt.rgba(1, 0.48, 0.42, 0.40)
                    : kind === "warn" ? Qt.rgba(1, 0.77, 0.43, 0.38)
                    : Qt.rgba(0.31, 0.76, 0.97, 0.35)
        Text { id: at; anchors.fill: parent; anchors.margins: 14
               color: kind === "bad" ? "#FFB4AB" : kind === "warn" ? "#FFDCA8" : "#A8DFFF"
               font.pixelSize: 16; font.bold: true; wrapMode: Text.Wrap
               verticalAlignment: Text.AlignVCenter }
    }

    // ═════════ ЖИВОЙ ФОН — один на все экраны ═════════
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#050F1F" }
            GradientStop { position: 0.5; color: "#081B34" }
            GradientStop { position: 1.0; color: "#0D2B52" }
        }
    }
    Item {   // дрейфующие цветные блики
        anchors.fill: parent
        Rectangle {
            id: blob1
            width: win.width * 0.55; height: width; radius: width / 2
            color: "#2BA4DB"; opacity: 0.20
            x: -width * 0.25; y: -height * 0.25
            SequentialAnimation on x { loops: Animation.Infinite
                NumberAnimation { to: win.width * 0.15; duration: 16000; easing.type: Easing.InOutSine }
                NumberAnimation { to: -blob1.width * 0.25; duration: 16000; easing.type: Easing.InOutSine } }
            SequentialAnimation on opacity { loops: Animation.Infinite
                NumberAnimation { to: 0.30; duration: 9000; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.18; duration: 9000; easing.type: Easing.InOutSine } }
        }
        Rectangle {
            id: blob2
            width: win.width * 0.5; height: width; radius: width / 2
            color: "#6C5CE7"; opacity: 0.16
            x: win.width - width * 0.5; y: win.height - height * 0.55
            SequentialAnimation on y { loops: Animation.Infinite
                NumberAnimation { to: win.height * 0.35; duration: 19000; easing.type: Easing.InOutSine }
                NumberAnimation { to: win.height - blob2.height * 0.55; duration: 19000; easing.type: Easing.InOutSine } }
        }
        Rectangle {
            width: win.width * 0.33; height: width; radius: width / 2
            color: "#19C2A8"; opacity: 0.12
            x: win.width * 0.6; y: -height * 0.4
        }
    }

    // ═════════ СТАРТ: часы + логотип ═════════
    FadeItem {
        active: page === "main" && backend.state === "idle"

        Column {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -win.height * 0.02
            spacing: 34

            Column {   // часы как на локскрине
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 2
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: win.clockStr
                    color: win.txt; font.pixelSize: 108
                    font.weight: Font.Light; font.letterSpacing: 2
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: win.dateStr
                    color: win.mutedC; font.pixelSize: 21
                }
            }

            Rectangle {   // логотип в стеклянной пластине
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(win.width * 0.36, 520)
                height: width * 0.36
                radius: 30
                color: Qt.rgba(1, 1, 1, 0.94)
                border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.5)
                Image {
                    anchors.centerIn: parent
                    source: logoUrl
                    width: parent.width * 0.74
                    fillMode: Image.PreserveAspectFit
                    smooth: true; mipmap: true
                }
                SequentialAnimation on scale { loops: Animation.Infinite
                    NumberAnimation { to: 1.025; duration: 2800; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0;   duration: 2800; easing.type: Easing.InOutSine } }
            }

            Rectangle {   // пилюля-подсказка
                anchors.horizontalCenter: parent.horizontalCenter
                width: hintRow.implicitWidth + 56; height: 58
                radius: 999
                color: win.glass; border.width: 1; border.color: win.edge
                Row {
                    id: hintRow
                    anchors.centerIn: parent
                    spacing: 14
                    Text { text: ""; anchors.verticalCenter: parent.verticalCenter
                           color: win.txt; font.pixelSize: 22 }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Подключите iPhone кабелем"
                        color: win.txt; font.pixelSize: 21; font.bold: true
                    }
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 7
                        Repeater { model: 3
                            Rectangle {
                                width: 8; height: 8; radius: 4; color: win.accent
                                SequentialAnimation on opacity { loops: Animation.Infinite
                                    PauseAnimation { duration: index * 260 }
                                    NumberAnimation { to: 0.15; duration: 400 }
                                    NumberAnimation { to: 1.0;  duration: 400 }
                                    PauseAnimation { duration: (2 - index) * 260 } } } }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Проверка начнётся сама и займёт около минуты"
                color: win.dimC; font.pixelSize: 16
            }
        }

        Row {   // статус внизу
            anchors { bottom: parent.bottom; left: parent.left; margins: 28 }
            spacing: 10
            Rectangle { width: 9; height: 9; radius: 5
                        anchors.verticalCenter: parent.verticalCenter
                        color: backend.phoneSeen ? win.okC : win.dimC }
            Text { text: backend.phoneSeen ? "кабель вижу — нажмите «Доверять» на телефоне"
                                           : "система готова"
                   color: win.dimC; font.pixelSize: 14 }
        }
        Button {   // шестерёнка
            anchors { top: parent.top; right: parent.right; margins: 24 }
            width: 52; height: 52
            contentItem: Text { text: "⚙"; color: win.dimC; font.pixelSize: 26
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter }
            background: Rectangle { radius: 26; color: win.glass
                                    border.width: 1; border.color: win.edge }
            onClicked: { backend.checkDrivers(); page = "settings" }
        }
    }

    // ═════════ ЧТЕНИЕ ═════════
    FadeItem {
        active: page === "main" && backend.state === "reading"
        Column {
            anchors.centerIn: parent
            spacing: 38
            Item {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 130; height: 130
                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        var c = getContext("2d"); c.reset()
                        c.lineWidth = 8; c.lineCap = "round"
                        var g = c.createLinearGradient(0, 0, width, height)
                        g.addColorStop(0, "#7ADCFF"); g.addColorStop(1, "#2BA4DB")
                        c.strokeStyle = g
                        c.beginPath()
                        c.arc(width/2, height/2, width/2 - 9, 0, Math.PI * 1.4)
                        c.stroke()
                    }
                }
                RotationAnimator on rotation { loops: Animation.Infinite
                                               from: 0; to: 360; duration: 1000 }
            }
            Text { anchors.horizontalCenter: parent.horizontalCenter
                   text: "Читаю телефон…"
                   color: win.txt; font.pixelSize: 36; font.weight: Font.Light }
            Text { anchors.horizontalCenter: parent.horizontalCenter
                   text: "Не отключайте кабель · обычно 20–40 секунд"
                   color: win.mutedC; font.pixelSize: 18 }
        }
    }

    // ═════════ ОШИБКА ЧТЕНИЯ ═════════
    FadeItem {
        active: page === "main" && backend.state === "error"
        GlassCard {
            anchors.centerIn: parent
            width: Math.min(win.width * 0.55, 760)
            height: errCol.height + 56
            Column {
                id: errCol
                anchors.centerIn: parent
                width: parent.width - 64
                spacing: 14
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "⚠"; color: win.warnC; font.pixelSize: 54 }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "Не получилось прочитать телефон"
                       color: win.txt; font.pixelSize: 26; font.bold: true }
                Text { width: parent.width
                       horizontalAlignment: Text.AlignHCenter
                       text: backend.errorText + "\nПереподключите кабель — попробую снова."
                       color: win.mutedC; font.pixelSize: 16; wrapMode: Text.Wrap }
            }
        }
    }

    // ═════════ РЕЗУЛЬТАТ ═════════
    FadeItem {
        active: page === "main" && (backend.state === "result" || backend.state === "done")

        Flickable {
            anchors.fill: parent
            contentWidth: width
            contentHeight: col.height + 80
            clip: true
            ColumnLayout {
                id: col
                width: Math.min(parent.width - 72, 1200)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 34; spacing: 16

                // шапка
                RowLayout {
                    Layout.fillWidth: true; spacing: 16
                    Rectangle {
                        width: 118; height: 44; radius: 14
                        color: Qt.rgba(1, 1, 1, 0.92)
                        Image { anchors.centerIn: parent; source: logoUrl
                                width: parent.width - 22
                                fillMode: Image.PreserveAspectFit; mipmap: true }
                    }
                    Text {
                        text: backend.result["модель"]
                              ? backend.result["модель"] + "  ·  " + backend.result["память"] : ""
                        color: win.txt; font.pixelSize: 28; font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        radius: 999
                        color: Qt.rgba(1, 1, 1, 0.07)
                        border.width: 1
                        border.color: backend.result["итог"]
                            ? Qt.alpha(win.toneColor(backend.result["итог"].tone), 0.55) : win.edge
                        implicitHeight: 44; implicitWidth: vt.implicitWidth + 44
                        Text { id: vt; anchors.centerIn: parent
                               text: backend.result["итог"] ? backend.result["итог"].вердикт : ""
                               color: backend.result["итог"]
                                      ? win.toneColor(backend.result["итог"].tone) : win.okC
                               font.pixelSize: 17; font.bold: true }
                    }
                }

                // ЦЕНА — герой экрана
                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: priceCol.height + 48
                    ColumnLayout {
                        id: priceCol
                        anchors { left: parent.left; right: parent.right; top: parent.top
                                  margins: 24 }
                        spacing: 10
                        Repeater { model: backend.priceInfo["отказ"] || []
                                   AlertBox { kind: "bad"; text: modelData } }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: backend.priceInfo["ready"] === true
                            Column {
                                spacing: 0
                                SectionTitle { text: "ПРЕДВАРИТЕЛЬНАЯ ОЦЕНКА" }
                                Text { text: backend.priceInfo["итого"] || ""
                                       color: win.okC; font.pixelSize: 72
                                       font.weight: Font.DemiBold
                                       font.letterSpacing: -1 }
                            }
                            Item { Layout.fillWidth: true }
                            Column {
                                spacing: 5
                                Text { text: "база " + (backend.priceInfo["база"] || "")
                                       color: win.mutedC; font.pixelSize: 15
                                       anchors.right: parent.right }
                                Repeater { model: backend.priceInfo["вычеты"] || []
                                    Text { text: modelData.k + "   " + modelData.v
                                           color: win.badC; font.pixelSize: 15
                                           anchors.right: parent.right } }
                            }
                        }
                        Repeater {
                            model: backend.priceInfo["ready"] ? []
                                   : (backend.priceInfo["нехватка"] || [])
                            AlertBox { kind: "warn"; text: modelData }
                        }
                    }
                }

                // инструкция: вердикт Apple
                Rectangle {
                    Layout.fillWidth: true
                    visible: backend.appleInfo["state"] === "wait"
                    radius: 24
                    color: Qt.rgba(0.17, 0.45, 0.77, 0.30)
                    border.width: 1; border.color: Qt.rgba(0.48, 0.76, 1, 0.45)
                    implicitHeight: aCol.height + 44
                    ColumnLayout {
                        id: aCol
                        anchors { left: parent.left; right: parent.right; top: parent.top
                                  margins: 22 }
                        spacing: 8
                        RowLayout {
                            spacing: 12
                            Rectangle { width: 11; height: 11; radius: 6; color: win.accent
                                SequentialAnimation on opacity { loops: Animation.Infinite
                                    NumberAnimation { to: 0.2; duration: 480 }
                                    NumberAnimation { to: 1.0; duration: 480 } } }
                            Text { text: "Один шаг на телефоне — вердикт самой Apple"
                                   color: win.txt; font.pixelSize: 20; font.bold: true }
                            Item { Layout.fillWidth: true }
                            GBtn { text: "Пропустить"; padding: 8
                                   leftPadding: 18; rightPadding: 18; font.pixelSize: 14
                                   onClicked: backend.skipApple() }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "Настройки → Основные → Об этом устройстве → зайдите в «Запчасти и история обслуживания». Важен именно переход внутрь: если экран уже открыт — выйдите и зайдите снова. Я слушаю."
                            color: "#C9E2F8"; font.pixelSize: 16; wrapMode: Text.Wrap
                        }
                    }
                }

                Repeater { model: backend.result["alerts"] || []
                           AlertBox { kind: modelData.kind; text: modelData.text } }
                Repeater { model: (backend.sickwInfo["alerts"]) || []
                           AlertBox { kind: modelData.kind; text: modelData.text } }

                // карточки
                GridLayout {
                    Layout.fillWidth: true
                    columns: width > 920 ? 2 : 1
                    columnSpacing: 16; rowSpacing: 16

                    Repeater {
                        model: backend.result["cards"] || []
                        GlassCard {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            implicitHeight: cc.height + 44
                            ColumnLayout {
                                id: cc
                                anchors { left: parent.left; right: parent.right
                                          top: parent.top; margins: 22 }
                                spacing: 9
                                SectionTitle { text: modelData.title.toUpperCase() }
                                Repeater { model: modelData.rows
                                    RowLine { k: modelData.k; v: modelData.v
                                              tone: modelData.tone } }
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        visible: backend.appleInfo["state"] === "got"
                        implicitHeight: apc.height + 44
                        ColumnLayout {
                            id: apc
                            anchors { left: parent.left; right: parent.right
                                      top: parent.top; margins: 22 }
                            spacing: 9
                            SectionTitle { text: "ВЕРДИКТ APPLE" }
                            Repeater { model: backend.appleInfo["rows"] || []
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone } }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        visible: backend.sickwInfo["state"] !== "off"
                        implicitHeight: skc.height + 44
                        ColumnLayout {
                            id: skc
                            anchors { left: parent.left; right: parent.right
                                      top: parent.top; margins: 22 }
                            spacing: 9
                            SectionTitle { text: "ВНЕШНЯЯ БАЗА" }
                            Text { visible: backend.sickwInfo["state"] === "wait"
                                   text: "Проверяю по базе Apple GSX…"
                                   color: win.mutedC; font.pixelSize: 16 }
                            Text { visible: backend.sickwInfo["state"] === "nokey"
                                   text: "Ключ Sickw не задан (⚙ Настройки)"
                                   color: win.warnC; font.pixelSize: 16 }
                            Text { visible: backend.sickwInfo["state"] === "error"
                                   text: backend.sickwInfo["msg"] || ""
                                   color: win.badC; font.pixelSize: 15
                                   wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Repeater { model: backend.sickwInfo["rows"] || []
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone } }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 14
                    GBtn { text: "Ручные проверки  →"; primary: true
                           onClicked: page = "stage2" }
                    GBtn { text: "Завершить приёмку"; onClicked: page = "stage3" }
                    Item { Layout.fillWidth: true }
                }
            }
        }

        // «готово»
        Rectangle {
            anchors.fill: parent
            visible: backend.state === "done"
            color: Qt.rgba(0.02, 0.06, 0.12, 0.88)
            Column {
                anchors.centerIn: parent
                spacing: 22
                Rectangle {
                    id: okBadge
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 140; height: 140; radius: 70
                    color: Qt.rgba(0.22, 0.85, 0.63, 0.15)
                    border.width: 2; border.color: win.okC
                    Text { anchors.centerIn: parent; text: "✓"
                           color: win.okC; font.pixelSize: 74; font.bold: true }
                    scale: visible ? 1 : 0.3
                    Behavior on scale { NumberAnimation { duration: 450
                                        easing.type: Easing.OutBack } }
                }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "Приёмка завершена и записана"
                       color: win.txt; font.pixelSize: 30; font.weight: Font.Light }
                Text { anchors.horizontalCenter: parent.horizontalCenter
                       text: "Отключите телефон — экран вернётся сам"
                       color: win.mutedC; font.pixelSize: 17 }
            }
        }
    }

    // ═════════ ЭТАП 2 ═════════
    FadeItem {
        id: stage2Root
        active: page === "stage2"
        property var marks: ({})

        Flickable {
            anchors.fill: parent
            contentWidth: width; contentHeight: s2col.height + 80; clip: true
            ColumnLayout {
                id: s2col
                width: Math.min(parent.width - 72, 1000)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 34; spacing: 16
                Text { text: "Ручные проверки"; color: win.txt
                       font.pixelSize: 34; font.weight: Font.Light }
                Text { text: "Отметьте найденные проблемы. Веб-тест на телефоне: barcode-scan.duckdns.org/apps/diag.html"
                       color: win.mutedC; font.pixelSize: 16; wrapMode: Text.Wrap
                       Layout.fillWidth: true }

                Flow {
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: backend.manualChecks
                        Rectangle {
                            property bool on: false
                            width: chipText.implicitWidth + 40; height: 50
                            radius: 999
                            color: on ? Qt.rgba(0.31, 0.76, 0.97, 0.22) : win.glass
                            border.width: 1
                            border.color: on ? win.accent : win.edge
                            Behavior on color { ColorAnimation { duration: 130 } }
                            Text { id: chipText; anchors.centerIn: parent
                                   text: modelData.label
                                   color: on ? win.accent : win.txt
                                   font.pixelSize: 15; font.bold: true }
                            MouseArea { anchors.fill: parent
                                onClicked: { parent.on = !parent.on
                                             stage2Root.marks[modelData.key] = parent.on } }
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: fcol.height + 44
                    ColumnLayout {
                        id: fcol
                        anchors { left: parent.left; right: parent.right
                                  top: parent.top; margins: 22 }
                        spacing: 10
                        SectionTitle { text: "ЦВЕТ АППАРАТА (ПО КАБЕЛЮ НЕ ОПРЕДЕЛЯЕТСЯ)" }
                        GField { id: colourField; Layout.fillWidth: true
                                 placeholderText: "чёрный, синий, титан…" }
                        SectionTitle { text: "ЗАМЕТКИ ПРИЁМЩИКА" }
                        TextArea {
                            id: notesField; Layout.fillWidth: true
                            implicitHeight: 92
                            color: win.txt; font.pixelSize: 16
                            placeholderTextColor: Qt.rgba(1, 1, 1, 0.32)
                            background: Rectangle {
                                radius: 14; color: Qt.rgba(0, 0, 0, 0.25)
                                border.width: 1
                                border.color: notesField.activeFocus ? win.accent : win.edge }
                        }
                    }
                }

                RowLayout {
                    spacing: 14
                    GBtn { text: "Сохранить  →  финал"; primary: true
                           onClicked: {
                               backend.saveStage2(stage2Root.marks,
                                                  colourField.text, notesField.text)
                               page = "stage3" } }
                    GBtn { text: "←  Назад"; onClicked: page = "main" }
                }
            }
        }
    }

    // ═════════ ЭТАП 3 ═════════
    FadeItem {
        active: page === "stage3"
        ColumnLayout {
            width: Math.min(parent.width - 72, 780)
            anchors.centerIn: parent
            spacing: 16
            Text { text: "Финал приёмки"; color: win.txt
                   font.pixelSize: 34; font.weight: Font.Light }
            GlassCard {
                Layout.fillWidth: true
                implicitHeight: f3.height + 48
                ColumnLayout {
                    id: f3
                    anchors { left: parent.left; right: parent.right
                              top: parent.top; margins: 24 }
                    spacing: 12
                    RowLine { k: "Аппарат"
                              v: (backend.result["модель"] || "") + "  " +
                                 (backend.result["память"] || "") }
                    RowLine { k: "Предварительная цена"
                              v: backend.priceInfo["итого"] || "—"; tone: "ok" }
                    SectionTitle { text: "ИТОГОВАЯ ЦЕНА, СОГЛАСОВАННАЯ С КЛИЕНТОМ" }
                    GField { id: finalPrice; Layout.fillWidth: true
                             font.pixelSize: 26; font.bold: true
                             inputMethodHints: Qt.ImhDigitsOnly
                             placeholderText: "сумма в тенге" }
                    RowLayout {
                        spacing: 10
                        Repeater {
                            model: ["Выкуп", "Trade-In"]
                            Rectangle {
                                property bool on: index === 0
                                width: 140; height: 48; radius: 999
                                color: on ? Qt.rgba(0.31, 0.76, 0.97, 0.22) : win.glass
                                border.width: 1
                                border.color: on ? win.accent : win.edge
                                Text { anchors.centerIn: parent; text: modelData
                                       color: parent.on ? win.accent : win.txt
                                       font.pixelSize: 15; font.bold: true }
                                MouseArea { anchors.fill: parent
                                    onClicked: {
                                        for (var i = 0; i < parent.parent.children.length; i++)
                                            if (parent.parent.children[i].on !== undefined)
                                                parent.parent.children[i].on = false
                                        parent.on = true
                                        win.buyMethod = modelData } }
                            }
                        }
                    }
                }
            }
            RowLayout {
                spacing: 14
                GBtn { text: "Завершить приёмку"; primary: true
                       onClicked: { backend.saveStage3(finalPrice.text, win.buyMethod)
                                    page = "main" } }
                GBtn { text: "←  Назад"; onClicked: page = "main" }
            }
        }
    }

    // ═════════ НАСТРОЙКИ ═════════
    FadeItem {
        active: page === "settings"
        Flickable {
            anchors.fill: parent
            contentWidth: width; contentHeight: stCol.height + 80; clip: true
            ColumnLayout {
                id: stCol
                width: Math.min(parent.width - 72, 920)
                anchors.horizontalCenter: parent.horizontalCenter
                y: 34; spacing: 16

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Настройки"; color: win.txt
                           font.pixelSize: 34; font.weight: Font.Light }
                    Item { Layout.fillWidth: true }
                    GBtn { text: "←  К работе"; primary: true
                           onClicked: page = "main" }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: prc.height + 44
                    ColumnLayout {
                        id: prc
                        anchors { left: parent.left; right: parent.right
                                  top: parent.top; margins: 22 }
                        spacing: 10
                        SectionTitle { text: "ПРАЙС ИЗ GOOGLE ТАБЛИЦЫ" }
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            font.pixelSize: 15
                            color: backend.settingsInfo["обновлён"] ? win.okC : win.warnC
                            text: backend.settingsInfo["обновлён"]
                                  ? "Обновлён " + backend.settingsInfo["обновлён"]
                                    + " · моделей: " + backend.settingsInfo["моделей"]
                                  : "Прайс ещё не загружался из таблицы"
                        }
                        Text {
                            Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                            font.pixelSize: 14; color: win.mutedC
                            text: backend.settingsInfo["sa_email"]
                                  ? "Сервис-аккаунт (таблицей поделиться с ним): "
                                    + backend.settingsInfo["sa_email"]
                                  : "gservice.json не найден рядом с программой — работаю через открытую ссылку"
                        }
                        GField { id: sheetUrl; Layout.fillWidth: true
                                 font.pixelSize: 14
                                 text: backend.settingsInfo["sheet_url"] || "" }
                        GBtn { text: "Обновить прайс из таблицы"; primary: true
                               onClicked: backend.syncPrices(sheetUrl.text) }
                        Text {
                            visible: backend.syncInfo["state"] !== "off"
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                            font.pixelSize: 15
                            color: backend.syncInfo["state"] === "error" ? win.badC
                                   : backend.syncInfo["state"] === "ok" ? win.okC : win.mutedC
                            text: backend.syncInfo["msg"] || ""
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: skSet.height + 44
                    ColumnLayout {
                        id: skSet
                        anchors { left: parent.left; right: parent.right
                                  top: parent.top; margins: 22 }
                        spacing: 10
                        SectionTitle { text: "КЛЮЧ SICKW" }
                        Text {
                            font.pixelSize: 15
                            color: backend.settingsInfo["sickw_tail"] ? win.okC : win.warnC
                            text: backend.settingsInfo["sickw_tail"]
                                  ? "Ключ стоит: ····" + backend.settingsInfo["sickw_tail"]
                                  : "Ключ не задан — внешняя база выключена"
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            GField { id: keyField; Layout.fillWidth: true
                                     placeholderText: "ключ API с sickw.com" }
                            GBtn { text: "Сохранить"; primary: true
                                   onClicked: { backend.saveSickwKey(keyField.text)
                                                keyField.text = "" } }
                        }
                        GBtn { text: "Убрать ключ"; danger: true
                               visible: !!backend.settingsInfo["sickw_tail"]
                               onClicked: backend.removeSickwKey() }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: drv.height + 44
                    ColumnLayout {
                        id: drv
                        anchors { left: parent.left; right: parent.right
                                  top: parent.top; margins: 22 }
                        spacing: 9
                        RowLayout {
                            Layout.fillWidth: true
                            SectionTitle { text: "ДРАЙВЕРЫ И ИНСТРУМЕНТЫ" }
                            Item { Layout.fillWidth: true }
                            GBtn { text: "Проверить"; padding: 8
                                   leftPadding: 18; rightPadding: 18; font.pixelSize: 14
                                   onClicked: backend.checkDrivers() }
                        }
                        Text { visible: backend.drivers["state"] === "wait"
                               text: "Проверяю…"; color: win.mutedC; font.pixelSize: 15 }
                        Text { visible: !!backend.drivers["итог"]
                               text: backend.drivers["итог"]; font.pixelSize: 15
                               font.bold: true
                               color: backend.drivers["итог"] === "Всё готово."
                                      ? win.okC : win.warnC }
                        Repeater {
                            model: backend.drivers["items"] || []
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 2
                                RowLine { k: modelData.k; v: modelData.v
                                          tone: modelData.tone }
                                Text { visible: !!modelData.fix
                                       text: modelData.fix; color: win.dimC
                                       font.pixelSize: 13; wrapMode: Text.Wrap
                                       Layout.fillWidth: true }
                            }
                        }
                    }
                }

                GBtn { text: "Закрыть программу"; danger: true
                       onClicked: Qt.quit() }
            }
        }
    }
}
