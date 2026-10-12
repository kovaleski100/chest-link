(() => {
'use strict';
const $ = id => document.getElementById(id);
const ALL_SLOTS = 0x3fffffff;
const token = location.hash.slice(1);
let state = {items: [], ips: []}, current = null, boxData = null, cursor = 0, boxIndex = 0;
let masks = [], filter = 0, busy = false, hotspotBusy = false, epoch = 0, sendingTarget = 0;
let dexData = null, dexState = null, dexGame = 'home', dexPool = 'all', dexSelected = 4, dexType = '', dexSaving = false;
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
function renderHotspot(info = state.hotspot || {}) {
  const card = $('hotspot-toggle').closest('.ds-hotspot');
  card.dataset.running = String(Boolean(info.running));
  const button = $('hotspot-toggle');
  const manageable = Boolean(info.canManage);
  button.textContent = info.running ? 'Encerrar rede para consoles' : 'Iniciar rede para consoles';
  button.classList.toggle('danger', Boolean(info.running));
  button.disabled = hotspotBusy || busy || !info.available || !manageable;
  if (!info.available) $('hotspot-state').textContent = info.reason || 'Hotspot indisponível neste computador.';
  else if (!manageable) $('hotspot-state').textContent = 'Controle disponível apenas no navegador aberto neste PC.';
  else if (info.running) $('hotspot-state').textContent = `${info.ssid} · PC ${info.ip} · internet compartilhada · rede local bloqueada · canal ${info.channel}`;
  else $('hotspot-state').textContent = info.reason || 'Desligada. Ao iniciar, o DS usará esta rede em vez do roteador.';
}
function requestHotspotStart() {
  if (busy || hotspotBusy || !state.hotspot?.available || !state.hotspot?.canManage) return;
  $('hotspot-dialog').showModal();
}
async function changeHotspot(action) {
  if (busy || hotspotBusy || !state.hotspot?.canManage) return;
  $('hotspot-dialog').close(); hotspotBusy = true; renderHotspot();
  status(action === 'start' ? 'Iniciando a rede local para consoles…' : 'Encerrando a rede local…');
  try {
    const result = await api('/api/hotspot', {action});
    state.hotspot = result; renderHotspot();
    status(result.running ? `Rede ${result.ssid} ativa. Usa o IP ${result.ip} no console.` : 'Rede local encerrada.');
  } catch (error) { status(error.message, true); }
  finally { hotspotBusy = false; await refresh(); renderHotspot(); }
}
function setMainView(showDex) {
  $('boxes-view').hidden = showDex; $('dex-view').hidden = !showDex;
  $('nav-boxes').classList.toggle('active', !showDex); $('nav-dex').classList.toggle('active', showDex);
  $('nav-boxes').removeAttribute('aria-current'); $('nav-dex').removeAttribute('aria-current');
  (showDex ? $('nav-dex') : $('nav-boxes')).setAttribute('aria-current', 'page');
  if (showDex) refreshDex();
}
function dexManualCaptured(id) {
  if (!dexState || dexGame === 'home') return false;
  const list = dexState.mode === 'unified' ? dexState.unified : dexState.individual[dexGame];
  return (list || []).includes(id);
}
function dexServerCaptured(id) {
  return Boolean(dexState && (dexState.serverCaptured || Object.keys(dexState.serverCounts || {}).map(Number)).includes(id));
}
function dexCaptured(id) { return dexServerCaptured(id) || dexManualCaptured(id); }
function dexGameName(id) { return dexData.games.find(game => game.id === id)?.name || id; }
function dexNode(tag, className, value) {
  const node = document.createElement(tag); if (className) node.className = className;
  if (value !== undefined) node.textContent = value; return node;
}
function showDexError(message) {
  $('dex-error-message').textContent = message;
  $('dex-error').hidden = false;
}
function clearDexError() { $('dex-error').hidden = true; }
function dexAvailableInGame(mon, game) { return (mon.availableIn || []).includes(game); }
function renderGamePicker() {
  const picker = $('dex-games'); picker.replaceChildren();
  picker.dataset.catalog = dexGame === 'home' ? 'home' : 'games';
  const games = dexGame === 'home' ? [{id: 'home', name: 'Pokémon HOME', set: 'Catálogo nacional'}] : dexData.games;
  $('dex-game-label').textContent = dexGame === 'home' ? 'Catálogo' : 'Jogo';
  for (const game of games) {
    const button = dexNode('button', 'dex-game-card');
    button.type = 'button'; button.dataset.game = game.id;
    button.setAttribute('aria-pressed', String(game.id === dexGame));
    button.setAttribute('aria-label', game.id === 'home' ? 'Catálogo Pokémon HOME' : `Pokémon ${game.name}`);
    if (game.id === 'home') button.classList.add('dex-home-card');
    let cover;
    if (game.id === 'home') {
      cover = dexNode('span', 'pokemon-home-mark'); cover.setAttribute('aria-hidden', 'true');
      cover.append(dexNode('span', 'pokemon-home-ball'), dexNode('span', 'pokemon-home-word', 'HOME'));
    } else {
      cover = dexNode('img'); cover.src = `/assets/${game.cover}`; cover.alt = ''; cover.width = 66; cover.height = 66;
    }
    const name = dexNode('strong', '', game.name);
    const version = dexNode('small', '', game.set);
    const label = dexNode('span', 'dex-game-name');
    label.append(name, version);
    button.append(cover, label);
    button.onclick = () => {
      if (game.id === 'home') { dexGame = 'home'; dexPool = 'all'; }
      else { dexGame = game.id; }
      $('dex-generation').value = dexGame === 'home' ? 'home' : '1';
      renderGamePicker(); renderDex();
    };
    picker.append(button);
  }
}
function renderDex() {
  if (!dexData || !dexState) return;
  const isHome = dexGame === 'home';
  const counts = dexState.serverCounts || {}, totalSpecies = Object.keys(counts).filter(id => counts[id] > 0).length;
  const totalCopies = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const manualCapturedForCounter = dexState.mode === 'unified'
    ? (dexState.unified || [])
    : (isHome ? Object.values(dexState.individual || {}).flat() : (dexState.individual[dexGame] || []));
  const capturedSpecies = new Set([...manualCapturedForCounter, ...(dexState.serverCaptured || Object.keys(counts).map(Number))]).size;
  const available = isHome ? dexData.species : dexData.species.filter(mon => dexAvailableInGame(mon, dexGame));
  $('dex-generation').value = isHome ? 'home' : '1';
  $('dex-eyebrow').textContent = isHome ? 'POKÉMON HOME · CATÁLOGO NACIONAL' : 'KANTO · GERAÇÃO I';
  $('dex-intro-copy').textContent = isHome
    ? 'Pokémon presentes em uma cópia do servidor já contam como capturados. O catálogo começa com a primeira geração.'
    : 'Pokémon enviados ao servidor são considerados capturados automaticamente; também podes registrar capturas por jogo.';
  $('dex-server-total').textContent = `${totalSpecies} / ${dexData.species.length}`;
  $('dex-server-copies').textContent = isHome
    ? `${totalCopies} exemplares Gen I · contagem limitada às espécies já integradas`
    : `${totalCopies} exemplares Gen I encontrados nas cópias`;
  $('dex-captured-total').textContent = `${capturedSpecies} / ${dexData.species.length}`;
  $('dex-captured-summary').textContent = isHome
    ? `inclui espécies encontradas nas cópias do servidor`
    : `inclui ${new Set(dexState.serverCaptured || Object.keys(counts).map(Number)).size} no servidor · ${dexState.mode === 'unified' ? 'progresso unificado' : dexGameName(dexGame)}`;
  $('dex-list-title').textContent = isHome ? 'Pokémon HOME · espécies integradas' : (dexPool === 'all' ? 'Pokédex completa' : `Disponíveis em ${dexGameName(dexGame)}`);
  $('dex-game-note').textContent = isHome
    ? `${dexData.species.length} espécies estão disponíveis neste catálogo inicial. As próximas gerações serão adicionadas depois.`
    : `${available.length} espécies podem ser obtidas em ${dexGameName(dexGame)} sem depender de troca com outra versão. A lista inclui evoluções.`;
  $('dex-pool-control').hidden = isHome;
  document.querySelectorAll('[data-mode]').forEach(button => { button.disabled = isHome; });
  $('dex-exclusive').disabled = isHome || (dexPool === 'available' && dexGame === 'yellow');
  $('dex-exclusive').closest('label').classList.toggle('disabled', $('dex-exclusive').disabled);
  if ($('dex-exclusive').disabled) $('dex-exclusive').checked = false;
  document.querySelectorAll('[data-game]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.game === dexGame)));
  document.querySelectorAll('[data-pool]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.pool === dexPool)));
  document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(!isHome && button.dataset.mode === dexState.mode)));
  const search = $('dex-search').value.trim().toLowerCase();
  const onlyExclusive = $('dex-exclusive').checked;
  const rows = dexData.species.filter(mon => {
    const matchesSearch = !search || mon.name.toLowerCase().includes(search) || String(mon.id).padStart(3, '0').includes(search.replace(/^#/, ''));
    const matchesType = !dexType || mon.types.includes(dexType);
    const availableInGame = !isHome && dexAvailableInGame(mon, dexGame);
    const exclusive = mon.exclusiveTo === dexGame || !availableInGame;
    return matchesSearch && matchesType && (isHome || dexPool === 'all' || availableInGame) &&
      (!onlyExclusive || (!isHome && (dexPool === 'available' ? mon.exclusiveTo === dexGame : exclusive)));
  });
  if (rows.length && !rows.some(mon => mon.id === dexSelected)) dexSelected = rows[0].id;
  $('dex-result-count').textContent = rows.length;
  const grid = $('dex-grid'); grid.replaceChildren();
  for (const mon of rows) {
    const inServer = Number(counts[mon.id] || 0) > 0;
    const automaticCapture = dexServerCaptured(mon.id);
    const capturedState = dexCaptured(mon.id);
    const card = dexNode('article', 'dex-card' + (mon.id === dexSelected ? ' selected' : ''));
    const main = dexNode('button', 'dex-card-main'); main.type = 'button'; main.onclick = () => { dexSelected = mon.id; renderDex(); };
    const sprite = dexNode('span', 'dex-sprite'); sprite.style.cssText = spriteStyle(mon.sprite); sprite.dataset.inServer = String(inServer); sprite.dataset.captured = String(capturedState);
    const identity = dexNode('span', 'dex-card-identity');
    identity.append(dexNode('small', 'dex-number', '#' + String(mon.id).padStart(3, '0')), dexNode('strong', '', mon.name));
    const types = dexNode('span', 'dex-card-types'); mon.types.forEach(type => types.append(dexNode('i', 'type-chip', type)));
    const server = dexNode('span', 'dex-server-mark' + (inServer ? ' present' : ''), inServer ? 'No servidor' : 'Não transferido');
    main.append(sprite, identity, types, server); card.append(main);
    const captured = dexNode('button', 'dex-capture' + (capturedState ? ' done' : ''), capturedState ? '✓ Capturado' : '+ Marcar captura');
    captured.type = 'button'; captured.disabled = dexSaving || automaticCapture;
    captured.onclick = event => { event.stopPropagation(); toggleDexCaptured(mon.id); };
    captured.hidden = isHome;
    card.append(captured); grid.append(card);
  }
  if (!rows.length) grid.append(dexNode('p', 'dex-empty', 'Nenhum Pokémon corresponde aos filtros.'));
  renderDexDetail();
}
function renderDexDetail() {
  const mon = dexData.species.find(item => item.id === dexSelected); if (!mon) return;
  const isHome = dexGame === 'home';
  const counts = dexState.serverCounts || {}, inServer = Number(counts[mon.id] || 0) > 0;
  const automaticCapture = dexServerCaptured(mon.id);
  const capturedState = dexCaptured(mon.id);
  const manualCaptured = dexManualCaptured(mon.id);
  const detail = $('dex-detail'); detail.replaceChildren();
  const heading = dexNode('div', 'dex-detail-heading');
  const sprite = dexNode('span', 'dex-detail-sprite'); sprite.style.cssText = spriteStyle(mon.sprite); sprite.dataset.inServer = String(inServer); sprite.dataset.captured = String(capturedState);
  const identity = dexNode('div', 'dex-detail-identity');
  identity.append(dexNode('span', 'eyebrow', `Nº ${String(mon.id).padStart(3, '0')} · GERAÇÃO I`), dexNode('h3', '', mon.name));
  const types = dexNode('div', 'dex-detail-types'); mon.types.forEach(type => types.append(dexNode('i', 'type-chip', type)));
  identity.append(types); heading.append(sprite, identity); detail.append(heading);
  const stateLine = dexNode('div', 'dex-state-line');
  stateLine.append(dexNode('span', 'dex-server-mark' + (inServer ? ' present' : ''), inServer ? `No servidor · ${counts[mon.id]}` : (automaticCapture ? 'Recebido pelo servidor' : 'Ainda não transferido')));
  const captureDescription = automaticCapture
    ? (manualCaptured ? `Capturado em ${dexState.mode === 'unified' ? 'todos os jogos' : dexGameName(dexGame)} · também recebido pelo servidor` : 'Capturado automaticamente pelo servidor')
    : (isHome ? 'Selecione um jogo para acompanhar capturas' : (manualCaptured ? `Capturado em ${dexState.mode === 'unified' ? 'todos os jogos' : dexGameName(dexGame)}` : 'Não marcado como capturado'));
  stateLine.append(dexNode('span', 'dex-check-state', captureDescription));
  detail.append(stateLine);
  if (!isHome && mon.exclusiveTo) detail.append(dexNode('p', 'dex-version-tag', `Exclusivo de ${dexGameName(mon.exclusiveTo)} em Red/Blue.`));
  if (!isHome && mon.unobtainableIn.includes(dexGame)) detail.append(dexNode('p', 'dex-version-tag', `Não disponível normalmente em ${dexGameName(dexGame)}; obtenível por troca a partir de Red/Blue.`));
  if (!isHome) {
    const toggleLabel = manualCaptured ? 'Desmarcar captura registrada' : (automaticCapture ? `Registrar também em ${dexState.mode === 'unified' ? 'progresso unificado' : dexGameName(dexGame)}` : 'Marcar como capturado');
    const toggle = dexNode('button', 'button ' + (manualCaptured ? 'secondary' : 'primary'), toggleLabel);
    toggle.type = 'button'; toggle.disabled = dexSaving; toggle.onclick = () => toggleDexCaptured(mon.id); detail.append(toggle);
  }
  const source = dexNode('a', 'dex-source-link', 'Ficha completa na Pokémon Database ↗');
  source.href = mon.pokemonDb; source.target = '_blank'; source.rel = 'noopener noreferrer'; detail.append(source);
  renderEvolution(mon, detail);
  if (!isHome) {
    detail.append(dexNode('div', 'dex-section-heading', 'Onde encontrar'));
    const encounters = mon.encounters[dexGame] || [];
    if (!encounters.length) detail.append(dexNode('p', 'muted', 'Não aparece diretamente em locais de captura deste jogo; confira a linha evolutiva ou a Pokédex completa.'));
    for (const encounter of encounters) {
    const row = dexNode('div', 'encounter-row');
    const info = dexNode('div', 'encounter-info');
    info.append(dexNode('strong', '', encounter.area), dexNode('small', '', `${encounter.method} · Nv. ${encounter.levels[0]}${encounter.levels[1] !== encounter.levels[0] ? '–' + encounter.levels[1] : ''}`));
    row.append(info, dexNode('b', 'encounter-rate', encounter.rate === null ? 'Especial' : `${encounter.rate}%`));
    if (encounter.rate !== null) {
      const bar = dexNode('div', 'encounter-bar'); const fill = dexNode('span'); fill.style.width = `${Math.max(2, Math.min(100, encounter.rate))}%`; bar.append(fill);
      detail.append(row, bar);
    } else detail.append(row);
    }
  }
}
function renderEvolution(mon, detail) {
  detail.append(dexNode('div', 'dex-section-heading', 'Linha evolutiva'));
  const chain = dexData.evolutionChains.find(row => row.paths.some(path => path.species.includes(mon.id)));
  const paths = (chain?.paths || []).filter(path => path.species.length > 1);
  if (!paths.length) {
    detail.append(dexNode('p', 'muted evolution-none', 'Não evolui na primeira geração.'));
    return;
  }
  const speciesById = new Map(dexData.species.map(item => [item.id, item]));
  for (const path of paths) {
    const line = dexNode('div', 'evolution-path');
    path.species.forEach((speciesId, index) => {
      const stageMon = speciesById.get(speciesId);
      if (!stageMon) return;
      const stage = dexNode('button', 'evolution-stage' + (speciesId === mon.id ? ' current' : ''));
      stage.type = 'button'; stage.title = `Ver ${stageMon.name}`;
      const sprite = dexNode('span', 'evolution-sprite'); sprite.style.cssText = spriteStyle(stageMon.sprite);
      const label = dexNode('span', 'evolution-label');
      label.append(dexNode('small', '', '#' + String(speciesId).padStart(3, '0')), dexNode('strong', '', stageMon.name));
      stage.append(sprite, label); stage.onclick = () => { dexSelected = speciesId; renderDex(); };
      line.append(stage);
      if (index < path.species.length - 1) {
        const bridge = dexNode('span', 'evolution-bridge');
        bridge.append(dexNode('small', '', path.methods[index] || 'Evolui'), dexNode('b', '', '→'));
        line.append(bridge);
      }
    });
    detail.append(line);
  }
}
async function refreshDex() {
  if (!dexData) return;
  try { dexState = await api('/api/pokedex'); clearDexError(); renderDex(); }
  catch { showDexError('Confira se o servidor está atualizado e tente novamente.'); }
}
async function toggleDexCaptured(speciesId) {
  if (dexSaving || !dexState || dexGame === 'home') return;
  dexSaving = true; renderDex();
  try { dexState = await api('/api/pokedex', {mode: dexState.mode, game: dexGame, species: speciesId, captured: !dexManualCaptured(speciesId)}); renderDex(); }
  catch (error) { status(error.message, true); }
  finally { dexSaving = false; renderDex(); }
}
async function changeDexMode(mode) {
  if (dexSaving || !dexState || dexGame === 'home' || mode === dexState.mode) return;
  dexSaving = true; renderDex();
  try { dexState = await api('/api/pokedex', {mode, game: dexGame, species: dexSelected, captured: dexCaptured(dexSelected)}); renderDex(); }
  catch (error) { status(error.message, true); }
  finally { dexSaving = false; renderDex(); }
}
async function loadDexData() {
  try {
    const response = await fetch('/assets/dex-gen1.json'); if (!response.ok) throw Error('Não foi possível carregar os dados da Pokédex.');
    dexData = await response.json();
    renderGamePicker();
    const types = [...new Set(dexData.species.flatMap(mon => mon.types))].sort();
    for (const type of types) $('dex-type').add(new Option(type, type));
    await refreshDex();
  } catch { showDexError('Não foi possível carregar os dados locais. Atualize a página e tente novamente.'); }
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
  const rows = state.items.filter(item => (!filter || (filter === 3 ? item.target === 0 : item.target === filter)) && (!search || (item.label + ' ' + item.id).toLowerCase().includes(search)));
  $('banks').replaceChildren();
  $('total-count').textContent = state.items.length;
  $('ds-count').textContent = state.items.filter(item => item.target === 1 && !item.delivered && !item.queue_cleared).length;
  $('3ds-count').textContent = state.items.filter(item => item.target === 2 && !item.delivered && !item.queue_cleared).length;
  $('unassigned-count').textContent = state.unassigned ?? state.items.filter(item => item.target === 0).length;
  const pending = Number(state.ds || 0) + Number(state.threeds || 0);
  $('pending-count').textContent = pending;
  $('clear-pending').disabled = busy || pending === 0;
  for (const item of rows) {
    const button = document.createElement('button'); button.className = 'bank'; button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(current?.id === item.id)); button.disabled = busy;
    const name = document.createElement('strong'); name.textContent = item.label;
    const destination = item.target === 0 ? 'Sem destino · escolher no PC ao enviar' : (item.target === 1 ? 'DS' : '3DS');
    const detail = document.createElement('small'); detail.textContent = destination + ' · ' + item.offer.boxes + ' boxes · ' + item.offer.occupied + ' Pokémon';
    const delivery = document.createElement('small'); delivery.textContent = item.target === 0 ? 'Cópia original mantida no PC · ' + item.id.slice(0, 8) : (item.queue_cleared ? 'Backup no servidor · fora da fila' : (item.delivered ? 'Entregue · backup mantido' : 'Pendente para ' + (item.target === 1 ? 'DS' : '3DS'))) + ' · ' + item.id.slice(0, 8);
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
    state = await api('/api/state'); const address = state.ips?.join(' / ') || 'consulte a rede do PC'; $('connection').textContent = 'IP ' + address + ' · PIN ' + state.pin + ' · TCP ' + state.port; $('connection-short').textContent = state.ips?.length ? 'PIN ' + state.pin + ' · porta ' + state.port : 'Servidor local'; renderHotspot();
    if (current) { const updated = state.items.find(item => item.id === current.id); if (updated) current = updated; else { current = null; boxData = null; masks = []; } }
    renderBanks(); renderBox(); if (!current && state.items.length) await selectBank(state.items[0]); if (!$('dex-view').hidden) await refreshDex(); if (manual) status('Lista atualizada.');
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
function askClearPending() {
  const pending = Number(state.ds || 0) + Number(state.threeds || 0);
  if (busy || !pending) return;
  const copies = pending === 1 ? '1 cópia pendente' : `${pending} cópias pendentes`;
  $('clear-pending-description').textContent = `Isso tirará ${copies} da fila de envio. Os pacotes e Pokémon continuam guardados no servidor e na Pokédex; depois, você pode selecionar a cópia e enviá-la novamente.`;
  $('clear-pending-dialog').showModal();
}
async function clearPending() {
  $('clear-pending-dialog').close(); if (busy) return; busy = true; renderBanks(); renderBox(); status('Limpando pendências de envio…');
  try { const result = await api('/api/clear-pending', {}); busy = false; await refresh(); status(`${result.cleared} pendência${result.cleared === 1 ? '' : 's'} removida${result.cleared === 1 ? '' : 's'} da fila; backups mantidos no servidor.`); }
  catch (error) { status(error.message, true); }
  finally { busy = false; renderBanks(); renderBox(); }
}
function moveCursor(delta) { cursor = (cursor + delta + 30) % 30; renderBox(); }
document.addEventListener('keydown', event => {
  if (busy || !current || !document.activeElement?.classList.contains('pokemon-slot')) return; const key = event.key.toLowerCase(); if (!['arrowleft', 'arrowright', 'arrowup', 'arrowdown', ' ', 'a', 'y', 'x', 'l', 'r', 'escape'].includes(key)) return; event.preventDefault();
  if (key === 'arrowleft') moveCursor(-1); else if (key === 'arrowright') moveCursor(1); else if (key === 'arrowup') moveCursor(-6); else if (key === 'arrowdown') moveCursor(6); else if (key === ' ' || key === 'a') mark(); else if (key === 'y') markBox(); else if (key === 'x') markAll(); else if (key === 'l') loadBox(boxIndex - 1); else if (key === 'r') loadBox(boxIndex + 1); else if (key === 'escape') { masks.fill(0); renderBox(); }
});
$('box-select').onchange = () => { if (!busy) loadBox(Number($('box-select').value)); }; $('prev-box').onclick = () => { if (!busy) loadBox(boxIndex - 1); }; $('next-box').onclick = () => { if (!busy) loadBox(boxIndex + 1); }; $('refresh').onclick = () => refresh(true); $('search').oninput = renderBanks;
$('clear-pending').onclick = askClearPending; $('cancel-clear-pending').onclick = () => $('clear-pending-dialog').close(); $('confirm-clear-pending').onclick = clearPending;
$('hotspot-toggle').onclick = () => state.hotspot?.running ? changeHotspot('stop') : requestHotspotStart();
$('cancel-hotspot').onclick = () => $('hotspot-dialog').close();
$('confirm-hotspot').onclick = () => changeHotspot('start');
document.querySelectorAll('[data-pool]').forEach(button => button.onclick = () => { dexPool = button.dataset.pool; renderDex(); });
document.querySelectorAll('[data-mode]').forEach(button => button.onclick = () => changeDexMode(button.dataset.mode));
$('dex-generation').onchange = () => {
  if ($('dex-generation').value === 'home') { dexGame = 'home'; dexPool = 'all'; }
  else { dexGame = 'red'; dexPool = 'available'; }
  renderGamePicker(); renderDex();
};
$('dex-search').oninput = renderDex; $('dex-type').onchange = () => { dexType = $('dex-type').value; renderDex(); }; $('dex-exclusive').onchange = renderDex;
$('dex-retry').onclick = () => dexData ? refreshDex() : loadDexData();
$('nav-boxes').onclick = () => setMainView(false); $('nav-dex').onclick = () => setMainView(true);
document.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => { filter = Number(button.dataset.filter); document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); renderBanks(); });
$('clear').onclick = () => { masks.fill(0); renderBox(); }; $('to-ds').onclick = () => askSend(1); $('to-3ds').onclick = () => askSend(2); $('cancel-send').onclick = () => $('confirm').close(); $('confirm-send').onclick = send; $('credits').onclick = () => $('credits-dialog').showModal(); $('close-credits').onclick = () => $('credits-dialog').close();
renderBox(); refresh(); loadDexData(); setInterval(() => { if (!busy) refresh(); }, 5000);
})();
