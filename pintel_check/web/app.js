// Фронт сознательно показывает ПОНЯТНОЕ, а сырьё целиком уходит в бэкенд.
const $ = s => document.querySelector(s);
const api = (p, b) => fetch(p, b ? {method:'POST', body:JSON.stringify(b),
  headers:{'Content-Type':'application/json'}} : {}).then(r => r.json());

let state = {id:null, res:null, est:null, apple:null, sickw:null, cfg:null};

const esc = s => String(s ?? '').replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
const money = (n, c) => (n==null ? '—' : n.toLocaleString('ru-RU') + ' ' + (c||'₸'));

// Цвет вердикта по детали. Отсутствие данных НЕ окрашиваем в плохое:
// «не прочиталось» и «заменено» — разные вещи.
function cls(v){
  if(/ОРИГИНАЛ|ИСПРАВЕН|ИДЕАЛ|ХОРОШИЙ/.test(v)) return 'v-ok';
  if(/ЗАМЕН|НЕОРИГ|СБОИ|ПРОБЛЕМ/.test(v)) return 'v-bad';
  if(/ВОПРОС|НЕПОЛНАЯ|РЕМОНТ/.test(v)) return 'v-warn';
  return 'muted';
}

async function poll(name, onDone, onTick){
  const t = setInterval(async () => {
    const j = await api('/api/job?name=' + name);
    if(onTick) onTick(j);
    if(j.готово){ clearInterval(t); onDone(j); }
  }, 900);
}

// ─────────── ЭТАП 1 ───────────
async function renderStage1(){
  const dev = await api('/api/device');
  state.cfg = await api('/api/config');
  if(!state.res){
    $('#stage1').innerHTML = `
      <div class="card">
        <h2>Этап 1 — подключение по кабелю</h2>
        ${dev.подключён
          ? `<div class="box ok">Телефон на связи. Можно начинать.</div>`
          : `<div class="box warn">${esc(dev.почему)}</div>`}
        <p class="hint">Снимается паспорт аппарата, износ батареи, вердикты по деталям,
        юридический статус. Телефон не отключай до конца проверки.</p>
        <div class="btns"><button id="go" ${dev.подключён?'':'disabled'}>Снять данные</button>
        <button class="sec" id="refresh">Проверить подключение</button>
        <button class="sec" id="setup">Настройка компьютера</button></div>
      </div>
      <div id="setupbox"></div>`;
    $('#refresh').onclick = renderStage1;
    $('#go').onclick = startStage1;
    $('#setup').onclick = showSetup;
    return;
  }
  drawResults();
}

// Одна кнопка для продавца: что готово, чего не хватает и что нажать.
// Ничего из сети не качаем и не запускаем — только проверяем и объясняем.
async function showSetup(){
  $('#setupbox').innerHTML = `<div class="card"><h2>Настройка компьютера</h2>
    <div><span class="spin"></span>Проверяю…</div></div>`;
  const r = await api('/api/setup');
  const line = i => `<div class="row">
      <span class="k">${i.готово?'✅':(i.необязательно?'⚪':'⛔')} ${esc(i.что)}</span>
      <span class="v ${i.готово?'v-ok':(i.необязательно?'muted':'v-bad')}">${esc(i.где || i.почему || '')}</span></div>
    ${!i.готово && i.как_починить ? `<div class="hint" style="margin:2px 0 10px">${esc(i.как_починить)}
      ${i.ссылка?`<br><a href="${esc(i.ссылка)}" target="_blank" rel="noopener">${esc(i.ссылка)}</a>`:''}</div>`:''}`;
  $('#setupbox').innerHTML = `<div class="card">
    <h2>Настройка компьютера</h2>
    <div class="box ${r.всё_готово?'ok':'warn'}">
      ${r.всё_готово
        ? 'Всё готово. Можно принимать телефоны.'
        : `Осталось сделать: ${r.осталось}. Что именно — ниже.`}
    </div>
    <div style="margin-top:12px">${r.пункты.map(line).join('')}</div>
    <p class="hint">Система: ${esc(r.система)}, Python ${esc(r.python)}.
    Программа ничего не скачивает из интернета сама: это защита кассового
    компьютера. Что нужно поставить — написано выше со ссылкой.</p>
    <div class="btns" style="margin-top:12px">
      <button class="sec" id="recheck">Проверить ещё раз</button>
      <button class="sec" id="closesetup">Закрыть</button></div>
  </div>`;
  $('#recheck').onclick = showSetup;
  $('#closesetup').onclick = () => { $('#setupbox').innerHTML = ''; };
}

async function startStage1(){
  $('#stage1').innerHTML = `<div class="card"><h2>Этап 1</h2>
    <div><span class="spin"></span>Читаю телефон. Это 20–40 секунд.</div></div>`;
  await api('/api/stage1', {});
  poll('stage1', j => {
    if(j.ошибка){
      $('#stage1').innerHTML = `<div class="card"><h2>Этап 1</h2>
        <div class="box bad">Не получилось: ${esc(j.ошибка)}</div>
        <button class="sec" id="again">Ещё раз</button></div>`;
      $('#again').onclick = renderStage1; return;
    }
    state.id = j.результат.id;
    state.res = j.результат.вердикты;
    state.est = j.результат.оценка;
    drawResults();
  });
}

function drawResults(){
  const r = state.res, p = r.паспорт, b = r.батарея;
  const parts = Object.entries(r.детали)
    .filter(([,v]) => v.вердикт !== 'НЕТ В МОДЕЛИ')
    .map(([k,v]) => `<div class="row"><span class="k">${esc(k)}</span>
      <span class="v ${cls(v.вердикт)}">${esc(v.вердикт)}${v.почему?`<br><span class="muted" style="font-size:12px">${esc(v.почему)}</span>`:''}</span></div>`).join('');

  const rows = (o) => Object.entries(o).map(([k,v]) =>
    `<div class="row"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></div>`).join('');

  $('#stage1').innerHTML = `
    <div class="card">
      <h2>Итог по аппарату</h2>
      <div class="h ${cls(r.итог.вердикт)}">${esc(r.итог.вердикт)}</div>
      <div class="muted">${esc(r.итог.почему)}</div>
      ${r.стоп.length?`<div class="box bad"><b>Не принимать / разобраться:</b><br>${r.стоп.map(esc).join('<br>')}</div>`:''}
      ${r.сделать.length?`<div class="box warn"><b>Сделать до приёмки:</b><br>${r.сделать.map(esc).join('<br>')}</div>`:''}
      ${r.внимание.length?`<div class="box warn"><b>Влияет на цену:</b><br>${r.внимание.map(esc).join('<br>')}</div>`:''}
    </div>

    <div id="pricebox"></div>

    <div class="grid">
      <div class="card"><h2>Паспорт</h2>${rows({
        'Модель': p.модель, 'Номер модели': p.номер_модели, 'Серийный номер': p.серийник,
        'Серийник платы': p.серийник_платы, 'IMEI': p.imei,
        'Память': p.память_гб + ' ГБ (свободно ' + p.свободно_гб + ')',
        'iOS': p.ios,
        'Цвет': p.цвет || 'по кабелю не определяется — впиши глазами'})}</div>

      <div class="card"><h2>Батарея</h2>${rows({
        'Износ': b.износ!=null ? b.износ + '%' : 'не определился',
        'Циклов': b.циклы, 'Ёмкость': b.ёмкость + ' из ' + b.завод + ' мА·ч заводских',
        'Наработка': (b.наработка_лет ?? '—') + ' лет',
        'Грелась до': (b.макс_темп ?? '—') + '°C'})}
        ${b.подделка.length?`<div class="box bad">${b.подделка.map(esc).join('<br>')}</div>`:''}
      </div>

      <div class="card"><h2>Детали</h2>${parts}
        <p class="hint">Сила доказательства разная: Face ID и Taptic проверены
        сопряжением с платой — подделать, не перепрошив плату, нельзя.
        Камеры и батарея — слабее. Фронтальная камера по кабелю не проверяется.</p>
      </div>

      <div class="card"><h2>Юридический статус</h2>${rows({
        'Найти iPhone': r.юридический.найти_iphone,
        'Активация': r.юридический.активация,
        'Пароль на телефоне': r.юридический.пароль ? 'стоит — попроси снять' : 'нет',
        'Корпоративный надзор': r.юридический.mdm ? 'ЕСТЬ (MDM)' : 'нет'})}</div>
    </div>

    <div class="card">
      <h2>Вердикт Apple по запчастям</h2>
      <div id="applebox">
        <p class="hint">Это ответ самой Apple, а не вывод по косвенным признакам:
        по каждому узлу «меняли или нет» и «деталь новая или б/у», плюс дата.
        Покрывает и то, до чего кабелю не добраться — заднее стекло, корпус, плату.</p>
        <button id="apple">Получить вердикт Apple</button>
      </div>
    </div>

    <div class="card">
      <h2>Внешняя база (Sickw)</h2>
      <div id="sickwbox">
        <p class="hint">Чёрный список, цвет, заводская конфигурация, даты покупки
        и активации, статусы оператора и iCloud. Независимо от телефона —
        подделке со стороны аппарата неподвластно. Запрос платный, около $0.10.</p>
        ${state.cfg.sickw_ключ
          ? `<button id="sickw">Проверить по IMEI (платно)</button>`
          : `<div class="box warn">Ключ Sickw не найден. Положи его в файл
             <code>~/.sickw_key</code> — в приложение он не вписывается.</div>`}
      </div>
    </div>

    <div class="card">
      <button id="next">Клиент согласен с ценой → этап 2</button>
    </div>`;

  drawPrice();
  const ab = $('#apple'); if(ab) ab.onclick = getApple;
  const sb = $('#sickw'); if(sb) sb.onclick = getSickw;
  $('#next').onclick = () => { showStage(2); renderStage2(); };
}

function drawPrice(){
  const e = state.est;
  if(!e) return;
  $('#pricebox').innerHTML = `<div class="card">
    <h2>Предварительная оценка</h2>
    ${e.отказ.length ? `<div class="box bad"><b>${e.отказ.map(esc).join('<br>')}</b></div>` : ''}
    ${e.база_известна ? `
      <div class="row"><span class="k">База по модели и памяти</span>
        <span class="v">${money(e.база, e.валюта)}</span></div>
      ${e.вычеты.map(d => `<div class="ded"><span>${esc(d.за_что)}</span>
        <span class="m">${money(d.сумма, e.валюта)}</span></div>`).join('')}
      <div class="row" style="margin-top:8px"><span class="k">К выплате</span>
        <span class="price">${money(e.итого, e.валюта)}</span></div>`
    : `<div class="box warn">${e.чего_не_хватает.map(esc).join('<br>')}<br>
        <span class="muted">Цифры в prices.json — заглушки. Я не стал выдумывать
        ваш прайс: ошибка в базовой цене дороже ошибки в диагностике.</span></div>
       ${e.вычеты.length?`<div class="hint">Вычеты, которые уже посчитаны:</div>
       ${e.вычеты.map(d=>`<div class="ded"><span>${esc(d.за_что)}</span>
         <span class="m">${money(d.сумма,e.валюта)}</span></div>`).join('')}`:''}`}
  </div>`;
}

async function getApple(){
  $('#applebox').innerHTML = `<div class="box ok">
    <b>На телефоне открой:</b><br>
    Настройки → Основные → Об этом устройстве → <b>зайди</b> в «Запчасти и история обслуживания».<br>
    <span class="muted">Нужен именно переход внутрь. Если экран уже открыт —
    выйди назад и зайди снова: Настройки кэшируют ответ.</span></div>
    <div style="margin-top:10px"><span class="spin"></span><span id="t">жду…</span></div>`;
  await api('/api/apple', {id: state.id});
  poll('apple', j => {
    const items = j.результат && j.результат.детали;
    if(j.ошибка || !items || !Object.keys(items).length){
      $('#applebox').innerHTML = `<div class="box warn">Вердикт не появился.
        Либо в раздел не зашли, либо модель его не показывает: на iPhone 11 это
        только батарея и экран, на XR/XS/SE — только батарея, старше — ничего.</div>
        <button class="sec" id="apple">Попробовать снова</button>`;
      $('#apple').onclick = getApple; return;
    }
    state.apple = items;
    const list = Object.values(items).sort((a,b)=>a.код-b.код).map(v =>
      `<div class="row"><span class="k">${esc(v.деталь)}</span>
       <span class="v ${v.меняли?'v-bad':'v-ok'}">${v.меняли
         ? 'МЕНЯЛИ' + (v.бу?' — Б/У деталь':' — новая') + (v.дата?`<br><span class="muted" style="font-size:12px">${esc(v.дата)}</span>`:'')
         : 'не меняли'}</span></div>`).join('');
    $('#applebox').innerHTML = list;
    repriceAndDraw();
  });
}

async function getSickw(){
  const imei = state.res.паспорт.imei;
  if(!confirm(`Отправить IMEI ${imei} в Sickw?\n\nЗапрос платный (~$0.10) и списывается даже при неудаче.`)) return;
  $('#sickwbox').innerHTML = `<div><span class="spin"></span>Спрашиваю внешнюю базу…</div>`;
  await api('/api/sickw', {id: state.id, imei});
  poll('sickw', j => {
    if(j.ошибка){
      $('#sickwbox').innerHTML = `<div class="box bad">${esc(j.ошибка)}</div>
        <button class="sec" id="sickw">Повторить</button>`;
      $('#sickw').onclick = getSickw; return;
    }
    const s = j.результат; state.sickw = s;
    const bad = s.чёрный_список && !/^(CLEAN|CLEAR)$/i.test(s.чёрный_список.trim());
    $('#sickwbox').innerHTML = `
      ${bad?`<div class="box bad"><b>ЧЁРНЫЙ СПИСОК: ${esc(s.чёрный_список)} — не принимать</b></div>`:''}
      ${/^ON$/i.test(s.icloud||'')?`<div class="box warn">iCloud включён — клиент должен выйти из Apple ID</div>`:''}
      <div class="row"><span class="k">Модель с завода</span><span class="v">${esc(s.модель_строка||'—')}</span></div>
      <div class="row"><span class="k">Цвет с завода</span><span class="v">${esc(s.цвет||'не вычленился')}</span></div>
      <div class="row"><span class="k">Объём с завода</span><span class="v">${s.объём_гб?s.объём_гб+' ГБ':'—'}</span></div>
      <div class="row"><span class="k">Чёрный список</span><span class="v ${bad?'v-bad':'v-ok'}">${esc(s.чёрный_список||'—')}</span></div>
      <div class="row"><span class="k">iCloud</span><span class="v">${esc(s.icloud||'—')}</span></div>
      <div class="row"><span class="k">SIM-lock</span><span class="v">${esc(s.sim_lock||'—')}</span></div>
      <div class="row"><span class="k">Оператор</span><span class="v">${esc(s.оператор||'—')}</span></div>
      <div class="row"><span class="k">Гарантия</span><span class="v">${esc(s.гарантия||'—')}</span></div>
      <div class="row"><span class="k">Дата покупки</span><span class="v">${esc(s.дата_покупки||'—')}</span></div>`;
    repriceAndDraw();
  });
}

async function repriceAndDraw(){
  const j = await api('/api/price', {id: state.id});
  if(j.оценка){ state.est = j.оценка; drawPrice(); }
}

// ─────────── ЭТАП 2 ───────────
const MANUAL = [
  ['экран_пятна',   'Экран: пятна, засветы, выгорание'],
  ['экран_битые',   'Экран: битые пиксели'],
  ['тач_мертвые',   'Тачскрин: мёртвые зоны'],
  ['корпус',        'Корпус: вмятины, сколы, глубокие царапины'],
  ['стекло_зад',    'Заднее стекло: трещины'],
  ['камеры_рабочие','Камеры дают картинку (основная, широкая, фронтальная)'],
  ['динамик',       'Динамик и микрофон работают'],
  ['вибро',         'Вибрация работает'],
  ['кнопки',        'Кнопки и переключатель звука работают'],
  ['зарядка',       'Заряжается и держит кабель'],
  ['faceid_работ',  'Face ID разблокирует'],
  ['влага',         'Признаки влаги или вскрытия на вид'],
];

function renderStage2(){
  $('#stage2').innerHTML = `
    <div class="card">
      <h2>Этап 2 — то, что по кабелю не проверить</h2>
      <p class="hint">Кабель отвечает на «оригинал или нет», но не на
      «работает или нет». Эти проверки требуют рук и глаз.</p>
      <div class="box ok">Открой на телефоне веб-тест:
        <code>barcode-scan.duckdns.org/apps/diag.html</code><br>
        <span class="muted">Экран, тачскрин, мультитач, динамик с микрофоном,
        обе камеры, датчики, геолокация — автоматически в браузере телефона.</span></div>
    </div>
    <div class="card">
      <h2>Отметь найденное</h2>
      ${MANUAL.map(([k,t]) => `<label class="chk"><input type="checkbox" data-k="${k}"><span>${esc(t)}</span></label>`).join('')}
      <div style="margin-top:12px">
        <div class="k muted" style="margin-bottom:6px">Цвет аппарата (по кабелю не определяется)</div>
        <input type="text" id="colour" placeholder="например: чёрный, синий, титан…">
      </div>
      <div style="margin-top:12px">
        <div class="k muted" style="margin-bottom:6px">Заметки приёмщика</div>
        <textarea id="notes" rows="3" placeholder="что ещё заметил"></textarea>
      </div>
    </div>
    <div class="card">
      <div class="btns"><button id="save2">Сохранить и перейти к финалу</button>
      <button class="sec" id="back1">Назад к этапу 1</button></div>
    </div>`;
  $('#back1').onclick = () => { showStage(1); drawResults(); };
  $('#save2').onclick = async () => {
    const r = {};
    document.querySelectorAll('#stage2 input[type=checkbox]').forEach(c => r[c.dataset.k] = c.checked);
    r.цвет = $('#colour').value.trim();
    r.заметки = $('#notes').value.trim();
    await api('/api/stage2', {id: state.id, результаты: r});
    showStage(3); renderStage3();
  };
}

// ─────────── ЭТАП 3 ───────────
function renderStage3(){
  $('#stage3').innerHTML = `
    <div class="card">
      <h2>Этап 3 — финал</h2>
      <p class="hint">Здесь будет связка с Pintel Оценка, Pay и МойСкладом:
      создание сделки, карточка товара, выплата. Пока — ручная фиксация,
      всё уже записано в базу приёмок.</p>
      <div class="row"><span class="k">Аппарат</span>
        <span class="v">${esc(state.res.паспорт.модель)} · ${esc(state.res.паспорт.серийник)}</span></div>
      <div class="row"><span class="k">Вердикт</span>
        <span class="v ${cls(state.res.итог.вердикт)}">${esc(state.res.итог.вердикт)}</span></div>
      <div class="row"><span class="k">Предварительная цена</span>
        <span class="v">${money(state.est && state.est.итого, state.est && state.est.валюта)}</span></div>
      <div style="margin-top:14px">
        <div class="k muted" style="margin-bottom:6px">Итоговая цена, согласованная с клиентом</div>
        <input type="text" id="final" inputmode="numeric" placeholder="введи сумму">
      </div>
      <div style="margin-top:12px">
        <div class="k muted" style="margin-bottom:6px">Способ выкупа</div>
        <select id="method"><option>Выкуп</option><option>Trade-In</option></select>
      </div>
      <div style="margin-top:14px">
        <div class="btns"><button id="save3">Завершить приёмку</button>
        <button class="sec" id="back2">Назад к этапу 2</button></div>
      </div>
      <div id="done3"></div>
    </div>`;
  $('#back2').onclick = () => { showStage(2); renderStage2(); };
  $('#save3').onclick = async () => {
    await api('/api/stage3', {id: state.id, данные: {
      итоговая_цена: $('#final').value.trim(), способ: $('#method').value}});
    $('#done3').innerHTML = `<div class="box ok" style="margin-top:12px">
      Приёмка №${state.id} завершена и записана.</div>
      <button class="sec" style="margin-top:10px" id="newone">Следующий телефон</button>`;
    $('#newone').onclick = () => { state = {cfg: state.cfg}; showStage(1); renderStage1(); };
  };
}

function showStage(n){
  [1,2,3].forEach(i => {
    $('#stage'+i).hidden = (i !== n);
    const s = $('#s'+i);
    s.className = 'step' + (i === n ? ' on' : (i < n ? ' done' : ''));
  });
}

renderStage1();
