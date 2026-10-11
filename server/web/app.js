(() => {
'use strict';
const $ = id => document.getElementById(id);
const ALL_SLOTS = 0x3fffffff;
const token = location.hash.slice(1);
let state = {items: [], ips: []}, current = null, boxData = null, cursor = 0, boxIndex = 0;
let masks = [], filter = 0, busy = false, epoch = 0, sendingTarget = 0;
async function api(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: {Authorization: 'Bearer ' + token, ...(body ? {'Content-Type': 'application/json'} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'O servidor não respondeu.');
  return data;
}
function status(message, error = false) {
  $('status-detail').textContent = message;
  $('status-detail').dataset.error = error ? '1' : '0';
  $('status').textContent = error ? 'Atenção' : (message.split(/[.!?]/, 1)[0] || message).slice(0, 54);
  $('status').dataset.error = error ? '1' : '0';
}
function popcount(value) { let count = 0; while (value) { count += value & 1; value >>>= 1; } return count; }
function selectionStats() {
  let slots = 0, boxes = 0;
  masks.forEach((mask, index) => {
    if (!mask) return;
    boxes++;
    if (index === boxIndex && boxData) boxData.pokemon.forEach((pokemon, slot) => { if (pokemon.occupied && (mask & (1 << slot))) slots++; });
    else slots += popcount(mask);
  });
  return {slots, boxes};
}
function spriteStyle(index) { const column = index % 32, row = Math.floor(index / 32); return `background-position:-${column * 68}px -${row * 60}px;background-size:2176px 1740px`; }
function renderBanks() {
  const search = $('search').value.trim().toLowerCase();
  const rows = state.items.filter(item => (!filter || item.target === filter) && (!search || (item.label + ' ' + item.id).toLowerCase().includes(search)));
  $('banks').replaceChildren();
  $('total-count').textContent = state.items.length;
  $('ds-count').textContent = state.items.filter(item => item.target === 1).length;
  $('3ds-count').textContent = state.items.filter(item => item.target === 2).length;
  for (const item of rows) {
    const button = document.createElement('button'); button.className = 'bank'; button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(current?.id === item.id)); button.disabled = busy;
    const name = document.createElement('strong'); name.textContent = item.label;
    const detail = document.createElement('small'); detail.textContent = (item.target === 1 ? 'DS' : '3DS') + ' · ' + item.offer.boxes + ' boxes · ' + item.offer.occupied + ' Pokémon';
    const delivery = document.createElement('small'); delivery.textContent = (item.delivered ? 'Entregue · backup mantido' : 'Pendente para ' + (item.target === 1 ? 'DS' : '3DS')) + ' · ' + item.id.slice(0, 8);
    button.append(name, detail, delivery); button.onclick = () => selectBank(item); $('banks').append(button);
  }
  if (!rows.length) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = state.items.length ? 'Nenhum banco neste filtro.' : 'Nenhum banco recebido. Envie um banco pelo console.'; $('banks').append(empty); }
}
function renderBox() {
  const hasBank = Boolean(current);
  $('workspace-title').textContent = hasBank ? current.label : 'Nenhum banco selecionado';
  $('workspace-subtitle').textContent = hasBank ? `${current.offer.boxes} boxes · ${current.offer.occupied} Pokémon · original preservado` : 'Escolha uma cópia na lista para começar.';
  $('box-select').disabled = busy || !hasBank; $('prev-box').disabled = busy || !hasBank; $('next-box').disabled = busy || !hasBank;
  $('box-label').textContent = hasBank ? 'BOX ' + (boxIndex + 1) : 'BOX'; $('box-name').textContent = boxData ? boxData.name : (hasBank ? 'Carregando…' : 'Selecione um banco'); $('box-position').textContent = hasBank ? `${boxIndex + 1} / ${current.offer.boxes}` : '—';
  const grid = $('pokemon-grid'); grid.replaceChildren();
  if (!boxData) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = hasBank ? 'Lendo a box…' : 'A box selecionada aparecerá aqui.'; grid.append(empty); }
  else boxData.pokemon.forEach((pokemon, slot) => {
    const button = document.createElement('button'); const selected = Boolean((masks[boxIndex] || 0) & (1 << slot));
    button.className = 'pokemon-slot' + (selected ? ' selected' : '') + (slot === cursor ? ' cursor' : '') + (!pokemon.occupied ? ' empty' : ''); button.setAttribute('role', 'gridcell'); button.setAttribute('aria-label', `Slot ${slot + 1}: ${pokemon.occupied ? (pokemon.valid ? pokemon.name : 'registro') : 'vazio'}`); button.title = pokemon.occupied ? (pokemon.valid ? pokemon.name : 'Registro desconhecido') : 'Vazio';
    const number = document.createElement('span'); number.className = 'slot-number'; number.textContent = slot + 1; button.append(number);
    if (pokemon.occupied) { const sprite = document.createElement('span'); sprite.className = 'sprite'; sprite.style.cssText = spriteStyle(pokemon.sprite); button.append(sprite); const name = document.createElement('span'); name.className = 'slot-name'; name.textContent = pokemon.valid ? pokemon.name : 'Registro'; button.append(name); }
    else { const mark = document.createElement('span'); mark.className = 'empty-mark'; mark.textContent = '·'; button.append(mark); }
    button.onclick = () => mark(slot); grid.append(button);
  });
  const count = selectionStats(); $('selection-count').textContent = count.boxes ? `${count.slots} espaços em ${count.boxes} boxes` : 'Nenhuma'; $('to-ds').disabled = busy || !current || !count.boxes; $('to-3ds').disabled = busy || !current || !count.boxes; $('clear').disabled = busy || !count.boxes;
}
async function refresh(manual = false) {
  try {
    state = await api('/api/state'); const address = state.ips?.join(' / ') || 'consulte a rede do PC'; $('connection').textContent = 'IP ' + address + ' · PIN ' + state.pin + ' · TCP ' + state.port; $('connection-short').textContent = state.ips?.length ? 'PIN ' + state.pin + ' · porta ' + state.port : 'Servidor local';
    if (current) { const updated = state.items.find(item => item.id === current.id); if (updated) current = updated; else { current = null; boxData = null; masks = []; } }
    renderBanks(); renderBox(); if (!current && state.items.length) await selectBank(state.items[0]); if (manual) status('Lista atualizada.');
  } catch (error) { status(error.message, true); }
}
async function selectBank(item) {
  if (busy) return; epoch++; current = item; boxIndex = 0; cursor = 0; masks = Array(item.offer.boxes).fill(0); boxData = null; $('box-select').replaceChildren();
  for (let index = 0; index < item.offer.boxes; index++) $('box-select').add(new Option('Box ' + (index + 1), String(index)));
  renderBanks(); renderBox(); await loadBox(0);
}
async function loadBox(index) {
  if (!current || !current.offer.boxes) return; const requestEpoch = ++epoch, id = current.id; index = (index + current.offer.boxes) % current.offer.boxes; boxIndex = index; cursor = 0; boxData = null; $('box-select').value = String(index); renderBox();
  try { const data = await api('/api/box?id=' + encodeURIComponent(id) + '&box=' + index); if (requestEpoch !== epoch || !current || current.id !== id) return; boxData = data; $('box-select').options[index].textContent = 'Box ' + (index + 1) + ' — ' + data.name; renderBox(); status('Cópia verificada. Marque Pokémon ou boxes para encaminhar.'); }
  catch (error) { if (requestEpoch === epoch) { renderBox(); status(error.message, true); } }
}
function mark(slot = cursor) { if (busy || !boxData) return; cursor = slot; if (boxData.pokemon[slot].occupied) masks[boxIndex] ^= 1 << slot; renderBox(); }
function markBox() { if (busy || !boxData) return; let occupiedMask = 0; boxData.pokemon.forEach((pokemon, slot) => { if (pokemon.occupied) occupiedMask |= 1 << slot; }); masks[boxIndex] = masks[boxIndex] === occupiedMask ? 0 : occupiedMask; renderBox(); }
function markAll() { if (busy || !current) return; masks.fill(masks.every(mask => mask === ALL_SLOTS) ? 0 : ALL_SLOTS); renderBox(); }
function askSend(target) { const count = selectionStats(); if (busy || !current || !count.boxes) return; sendingTarget = target; $('confirm-title').textContent = 'Enviar seleção ao ' + (target === 1 ? 'DS' : '3DS') + '?'; $('confirm-description').textContent = `Serão guardadas ${count.boxes} boxes como backup e enviadas diretamente ao listener do console. O console exibirá a confirmação antes de gravar.`; $('destination-ip').value = localStorage.getItem('chest-link-destination-ip') || ''; $('destination-pin').value = localStorage.getItem('chest-link-destination-pin') || ''; $('confirm').showModal(); }
async function send() {
  $('confirm').close(); if (busy) return; busy = true; renderBanks(); renderBox(); status('Guardando e enviando seleção ao console…');
  try { const ip = $('destination-ip').value.trim(), pinText = $('destination-pin').value.trim(); if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip) || !/^\d{6}$/.test(pinText)) throw Error('Informe o IP e o PIN exibidos no console.'); localStorage.setItem('chest-link-destination-ip', ip); localStorage.setItem('chest-link-destination-pin', pinText); const result = await api('/api/send-direct', {id: current.id, target: sendingTarget, masks: [...masks], ip, pin: Number(pinText)}); await refresh(); status(`Console confirmou a cópia ${result.id.slice(0, 8)}: ${result.occupied} Pokémon em ${result.boxes} boxes. Banco criado: ${result.bank}.`); }
  catch (error) { status(error.message, true); }
  finally { busy = false; renderBanks(); renderBox(); }
}
function moveCursor(delta) { cursor = (cursor + delta + 30) % 30; renderBox(); }
document.addEventListener('keydown', event => {
  if (busy || !current || !document.activeElement?.classList.contains('pokemon-slot')) return; const key = event.key.toLowerCase(); if (!['arrowleft', 'arrowright', 'arrowup', 'arrowdown', ' ', 'a', 'y', 'x', 'l', 'r', 'escape'].includes(key)) return; event.preventDefault();
  if (key === 'arrowleft') moveCursor(-1); else if (key === 'arrowright') moveCursor(1); else if (key === 'arrowup') moveCursor(-6); else if (key === 'arrowdown') moveCursor(6); else if (key === ' ' || key === 'a') mark(); else if (key === 'y') markBox(); else if (key === 'x') markAll(); else if (key === 'l') loadBox(boxIndex - 1); else if (key === 'r') loadBox(boxIndex + 1); else if (key === 'escape') { masks.fill(0); renderBox(); }
});
$('box-select').onchange = () => { if (!busy) loadBox(Number($('box-select').value)); }; $('prev-box').onclick = () => { if (!busy) loadBox(boxIndex - 1); }; $('next-box').onclick = () => { if (!busy) loadBox(boxIndex + 1); }; $('refresh').onclick = () => refresh(true); $('search').oninput = renderBanks;
document.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => { filter = Number(button.dataset.filter); document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); renderBanks(); });
$('clear').onclick = () => { masks.fill(0); renderBox(); }; $('to-ds').onclick = () => askSend(1); $('to-3ds').onclick = () => askSend(2); $('cancel-send').onclick = () => $('confirm').close(); $('confirm-send').onclick = send; $('credits').onclick = () => $('credits-dialog').showModal(); $('close-credits').onclick = () => $('credits-dialog').close();
renderBox(); refresh(); setInterval(() => { if (!busy) refresh(); }, 5000);
})();
