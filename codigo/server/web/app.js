(() => {
'use strict';
const $ = id => document.getElementById(id);
const ALL_SLOTS = 0x3fffffff;
const token = location.hash.slice(1);
let state = {items: [], ips: []}, current = null, boxData = null, cursor = 0, boxIndex = 0;
let masks = [], filter = 0, busy = false, hotspotBusy = false, epoch = 0, sendingTarget = 0;
let dexData = null, dexState = null, dexGame = 'home', dexPool = 'all', dexSelected = 4, dexType = '', dexSaving = false;
let currentView = 'boxes', nativeTab = 'pokedex', nativeRows = [], nativeSnapshot = null;
let nativeHash = '', nativeCatalog = null, nativeEpoch = 0, nativeBusy = false;
let nativeCompletionHash = '', nativeCompletion = null;
const professorOakFameGuide = [
  'Leia a placa do lado de fora do Laboratório do Oak, em Pallet.',
  'Fale com o Prof. Oak dentro do laboratório de Pallet.',
  'Fale com o assistente do Oak dentro do laboratório de Pallet.',
  'Leia o Pokémon Journal na Escola de Viridian.',
  'Fale com Agatha no Indigo Plateau.',
  'Depois de vencer a Liga, volte ao laboratório de Pallet e fale com o assistente do Oak.'
];
const nativeStoryGuides = {
  game_clear: 'Derrote a Elite Four e o Campeão para entrar no Hall da Fama.',
  national_dex: 'Depois de vencer a Liga, registrar 60 espécies capturadas e visitar a Ilha Um, fale com Oak no laboratório de Pallet.',
  sevii_islands_1_3: 'Receba o Tri-Pass de Bill e viaje de barco pelas Ilhas Um, Dois e Três.',
  sevii_islands_4_7: 'No pós-jogo, obtenha a Pokédex Nacional e entregue a Ruby a Celio para receber o Rainbow Pass.',
  lostelle_rescued: 'Na Ilha Três, siga até Berry Forest, vença Hypno e leve Lostelle de volta ao pai.',
  sevii_detour_finished: 'Resgate Lostelle em Berry Forest e retorne ao porto da Ilha Três; a flag é marcada nessa volta.',
  rocket_warehouse_cleared: 'Na Ilha Cinco, derrote os administradores e a equipe Rocket que guardam o Armazém.',
  ruby_recovered: 'Explore Mt. Ember, alcance a caverna e recolha a Ruby.',
  sapphire_recovered: 'Abra a Dotted Hole na Ilha Seis com Cut, recolha a Sapphire e recupere-a de Gideon no Armazém Rocket.',
  tanoby_ruins_unlocked: 'Na Sevault Canyon, resolva o puzzle de pedras da Tanoby Key usando Strength; depois visite as ruínas ao sul da Ilha Sete.',
  johto_champion: 'Vença a Elite Four de Johto e o Campeão Lance para entrar no Hall da Fama.',
  kanto_unlocked: 'Depois de vencer a Liga de Johto, fale com o Prof. Oak em Pallet e viaje para Kanto.'
};
const nativeFameCheckerGuides = {
  'Professor Oak': professorOakFameGuide,
  Daisy: [
    'Fale com o assistente de Oak no laboratório de Pallet.',
    'Fale com o assistente do presidente do Fã-clube Pokémon, em Vermilion.',
    'Na Water Labyrinth da Ilha Cinco, aceite o ovo do senhor; choque o Togepi e mostre-o a ele.',
    'Leia o Pokémon Journal na Escola de Viridian.',
    'Fale com a senhora idosa da Mansão de Celadon que lhe deu o Tea.',
    'Leia o Pokémon Journal no Centro Pokémon da Ilha Quatro.'
  ],
  Brock: [
    'Leia a placa em frente ao Ginásio de Pewter.',
    'Derrote Brock no Ginásio de Pewter.',
    'Fale com o rapaz jovem em Pewter City.',
    'Fale com o garoto na Rota 4.',
    'Fale com o homem que escava fósseis no Mt. Moon.',
    'Leia o Pokémon Journal no Museu de Ciência de Pewter, na sala do Old Amber.'
  ],
  Misty: [
    'Leia a placa em frente ao Ginásio de Cerulean.',
    'Derrote Misty no Ginásio de Cerulean.',
    'Fale com Luis, o treinador do Ginásio de Cerulean.',
    'Fale com o jovem nas Ilhas Seafoam.',
    'Fale com a moça na Rota 25, em frente à casa de Bill.',
    'Leia o Pokémon Journal no Centro Pokémon de Cerulean.'
  ],
  'Lt. Surge': [
    'Leia a placa em frente ao Ginásio de Vermilion.',
    'Derrote Lt. Surge no Ginásio de Vermilion.',
    'Derrote Tucker, o treinador do Ginásio de Vermilion.',
    'A mesma batalha contra Tucker registra esta segunda pista ao terminar.',
    'Derrote Dwayne no Ginásio de Vermilion.',
    'Leia o Pokémon Journal no Centro Pokémon de Vermilion.'
  ],
  Erika: [
    'Leia a placa em frente ao Ginásio de Celadon.',
    'Derrote Erika no Ginásio de Celadon.',
    'Fale com Lola no Ginásio de Celadon.',
    'Fale com Tamia no Ginásio de Celadon.',
    'A vitória contra Erika também registra esta pista ao terminar a conversa pós-batalha.',
    'Leia o Pokémon Journal nos condomínios de Celadon.'
  ],
  Koga: [
    'Leia a placa em frente ao Ginásio de Fuchsia.',
    'Derrote Koga no Ginásio de Fuchsia.',
    'Fale com Kirk no Ginásio de Fuchsia.',
    'Fale com Charine, em Fuchsia City, perto da área Safari.',
    'Leia o Pokémon Journal na Casa do Guardião Safari, em Fuchsia.',
    'Fale com o homem idoso no descanso norte da Safari Zone.'
  ],
  Sabrina: [
    'Leia a placa em frente ao Ginásio de Saffron.',
    'Fale com o adolescente na Ilha Três.',
    'Derrote Sabrina no Ginásio de Saffron.',
    'A mesma vitória contra Sabrina registra esta segunda pista.',
    'Leia o Pokémon Journal no Centro Pokémon de Saffron.',
    'Derrote Tyron no Ginásio de Saffron.'
  ],
  Blaine: [
    'Leia a placa em frente ao Ginásio da Ilha Cinnabar.',
    'Derrote Blaine no Ginásio de Cinnabar.',
    'Derrote Derek no Ginásio de Cinnabar.',
    'Fale com a mulher na Ilha Cinnabar.',
    'Examine a foto de Blaine no Ginásio de Cinnabar.',
    'Leia o Pokémon Journal na casa do Resort Gorgeous, na Ilha Cinco.'
  ],
  Lorelei: [
    'Fale com Lorelei no Indigo Plateau.',
    'Essa mesma conversa antes da batalha também registra esta pista.',
    'Fale com o homem idoso no Pokémart da Ilha Quatro.',
    'Leia o Pokémon Journal no Centro Pokémon da Ilha Cinco.',
    'Fale com a menina na Ilha Quatro.',
    'Depois de derrotar a Equipe Rocket na Icefall Cave, fale com a senhora idosa na Ilha Quatro.'
  ],
  Bruno: [
    'Fale com Bruno no Indigo Plateau.',
    'Essa mesma conversa antes da batalha também registra esta pista.',
    'Leia o Pokémon Journal no Fã-clube de Treinadores, em Saffron.',
    'Fale com o lutador nas Ember Spa da Ilha Um.',
    'Fale com a mulher na Ilha Dois.',
    'Fale com o lutador na Sevault Canyon, na Ilha Sete.'
  ],
  Agatha: [
    'Fale com Agatha no Indigo Plateau.',
    'Fale com o faixa-preta no Centro Pokémon do Indigo Plateau.',
    'Depois de reabrir a Liga no pós-jogo, fale novamente com o faixa-preta no Centro Pokémon do Indigo Plateau.',
    'Leia o Pokémon Journal no Centro Pokémon da Ilha Sete.',
    'A conversa inicial com Agatha também registra esta pista.',
    'Fale com a senhora idosa no Pokémart da Ilha Seis.'
  ],
  Lance: [
    'Fale com Lance no Indigo Plateau.',
    'Essa mesma conversa antes da batalha também registra esta pista.',
    'Fale com a menina no Fã-clube de Treinadores, em Saffron.',
    'Fale com a menina no segundo andar da loja de departamentos de Celadon.',
    'Leia o Pokémon Journal no Centro Pokémon do Indigo Plateau.',
    'Depois de reabrir a Liga no pós-jogo, fale com o treinador no Indigo Plateau.'
  ],
  Bill: [
    'Fale com seu rival durante o encontro em Cerulean.',
    'Fale com o menino em Cerulean City.',
    'Fale com o homem idoso em Fuchsia City.',
    'Depois de consertar a máquina de Celio, converse com ele repetidamente no Centro Pokémon da Ilha Um até registrar esta pista.',
    'Continue conversando com Celio na Ilha Um até registrar esta outra pista; as falas podem sair em ordem diferente.',
    'Continue conversando com Celio na Ilha Um até registrar a terceira pista dele.'
  ],
  'Mr. Fuji': [
    'Fale com a menina em Lavender Town.',
    'Fale com o Rocket na Pokémon Tower de Lavender.',
    'Examine a revista em Lavender Town.',
    'Fale com o homem idoso em Lavender Town.',
    'Examine a foto de Blaine e Fuji no Ginásio de Cinnabar.',
    'Leia o Pokémon Journal no Centro Pokémon de Cinnabar.'
  ],
  Giovanni: [
    'Fale com Giovanni no esconderijo Rocket de Celadon.',
    'Fale com o cientista no 5.º andar da Silph Co.',
    'Fale com o cientista no 8.º andar da Silph Co.',
    'Derrote Giovanni no Ginásio de Viridian.',
    'Depois da vitória, fale com o guia do Ginásio de Viridian.',
    'Fale com Gideon no Armazém Rocket da Ilha Cinco.'
  ]
};
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
  else if (info.running) $('hotspot-state').textContent = `${info.ssid} · PC ${info.ip} · TCP ${info.consolePort ?? state.port ?? 40992} · internet compartilhada · rede local bloqueada · canal ${info.channel}${manageable ? '' : ' · controle disponível apenas neste PC'}`;
  else if (!manageable) $('hotspot-state').textContent = 'Controle disponível apenas no navegador aberto neste PC.';
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
function setMainView(view) {
  const leftNativeView = currentView === 'native' && view === 'boxes';
  currentView = view;
  $('boxes-view').hidden = view !== 'boxes'; $('dex-view').hidden = view !== 'dex';
  $('native-view').hidden = view !== 'native';
  for (const [id, active] of [['nav-boxes', view === 'boxes'], ['nav-dex', view === 'dex'], ['nav-native', view === 'native']]) {
    $(id).classList.toggle('active', active);
    if (active) $(id).setAttribute('aria-current', 'page'); else $(id).removeAttribute('aria-current');
  }
  if (view === 'dex') refreshDex();
  if (view === 'native') refreshNative();
  if (leftNativeView) refresh();
}
function nativeNode(tag, className, value) {
  const node = document.createElement(tag); if (className) node.className = className;
  if (value !== undefined) node.textContent = value; return node;
}
function nativeLocation(location) {
  if (!location) return 'Localização indisponível';
  if (location.area === 'party') return `Party · posição ${Number(location.slot) + 1}`;
  if (location.area === 'box') return `Box ${Number(location.box) + 1} · posição ${Number(location.slot) + 1}`;
  return 'Localização indisponível';
}
function nativeStatus(status) {
  return ({CONFIRMED: 'Confirmado', OBSERVED: 'Observado', INFERRED: 'Inferido'})[status] || 'Desconhecido';
}
function nativeJourneySymbol(kind) {
  const drawings = {
    champion: '<path fill="#f0c85b" stroke="#815c22" stroke-width="2" d="M10 7h8v4c0 5-2 8-4 9-2-1-4-4-4-9zm-4 1h4v3c0 3-1 5-3 5-2 0-3-2-3-5V9zm12 0h4v3c0 3-1 5-3 5-2 0-3-2-3-5V9zM12 20h4v4h5v3H7v-3h5z"/>',
    pokedex: '<path fill="#d94b51" stroke="#742d35" stroke-width="2" d="M9 3h12l3 4v18l-3 4H9l-3-4V7z"/><path fill="#e4edf4" stroke="#30465c" stroke-width="2" d="M9 7h12v11H9z"/><path fill="#5a91a6" d="M11 9h8v2h-8zm0 4h5v2h-5z"/><circle fill="#e5cf76" cx="15" cy="23" r="2"/>',
    boat: '<path fill="#79a9bd" stroke="#345a70" stroke-width="2" d="M4 19h24l-4 6H9z"/><path fill="#e9f0f5" stroke="#345a70" stroke-width="2" d="M10 11h12v8H10zM13 7h6v4h-6z"/><path fill="#d94b51" d="M14 13h4v4h-4z"/><path fill="#8bd3dc" d="M5 28c3-2 5-2 8 0s5 2 8 0 5-2 8 0v3H5z"/>',
    ruins: '<path fill="#bda675" stroke="#67563a" stroke-width="2" d="M4 9 16 3l12 6v3H4zM6 25h20v4H6z"/><path fill="#d7c499" stroke="#67563a" stroke-width="2" d="M7 13h4v11H7zm7 0h4v11h-4zm7 0h4v11h-4z"/><path fill="#7c6c4e" d="M3 29h26v3H3z"/>',
    jump: '<path fill="none" stroke="#7bbbd4" stroke-width="2.5" d="M6 8c13 0 4 16 18 16M26 8c-13 0-4 16-18 16"/><path fill="#e9eef5" stroke="#4b627a" stroke-width="2" d="m13 14 3-4 4 3 1 6-3 5-5-2-2-5z"/><circle fill="#263d56" cx="18" cy="15" r="1"/>',
    berries: '<path fill="#74a65d" stroke="#3d6741" stroke-width="2" d="M15 11c-5-7-9-2-8 1 4 0 6 2 8 4 2-2 5-4 9-4 1-3-4-8-9-1z"/><circle fill="#ca4c60" stroke="#7d2d45" stroke-width="2" cx="10" cy="20" r="5"/><circle fill="#e28d52" stroke="#855735" stroke-width="2" cx="20" cy="20" r="5"/><circle fill="#7388c4" stroke="#3d4d7e" stroke-width="2" cx="15" cy="26" r="5"/>'
  };
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 32 32'); svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false'); svg.innerHTML = drawings[kind] || '';
  return svg;
}
function nativeJourneyTile(item, state) {
  const stateLabel = ({complete: 'concluído', partial: 'parcial', missing: 'pendente', unknown: 'não detectável'})[state] || 'pendente';
  const tile = nativeNode('div', `native-journey-tile is-${state}`);
  tile.title = `${item.label}: ${stateLabel}`;
  tile.setAttribute('role', 'img'); tile.setAttribute('aria-label', tile.title);
  const visual = nativeNode('span', 'native-journey-visual');
  if (item.src) {
    const image = nativeNode('img', item.src.includes('trainer-tower') ? 'native-journey-tower-image' : ''); image.src = `/assets/${item.src}`; image.alt = '';
    image.loading = 'lazy'; visual.append(image);
  } else if (Number.isInteger(item.pokemonSprite)) {
    const sprite = nativeNode('span', 'native-journey-pokemon-sprite');
    sprite.style.cssText = spriteStyle(item.pokemonSprite); visual.append(sprite);
  } else visual.append(nativeJourneySymbol(item.symbol));
  tile.append(visual, nativeNode('span', 'native-journey-label', item.label));
  if (item.meta) tile.append(nativeNode('small', 'native-journey-meta', item.meta));
  return tile;
}
function nativeJourneyGroup(root, label, items) {
  const checks = items.flatMap(item => item.states || [item.state]);
  const done = checks.filter(state => state === 'complete').length;
  const unknown = checks.filter(state => state === 'unknown').length;
  const section = nativeNode('section', `native-journey-group${checks.length > 0 && done === checks.length ? ' is-complete' : ''}`);
  const count = `${done} / ${checks.length} completos${unknown ? ` · ${unknown} não detectáveis` : ''}`;
  const heading = nativeNode('div', 'native-journey-group-heading');
  heading.append(nativeNode('h4', '', label), nativeNode('span', '', count));
  const grid = nativeNode('div', 'native-journey-icons');
  for (const item of items) {
    const states = item.states || [item.state];
    const completed = states.filter(state => state === 'complete').length;
    const tileState = completed === states.length ? 'complete' : completed ? 'partial' :
      states.some(state => state === 'unknown') ? 'unknown' : 'missing';
    const tile = nativeJourneyTile(item, tileState);
    if (item.states) {
      tile.classList.add('has-clues');
      const completed = item.states.filter(state => state === 'complete').length;
      const clues = nativeNode('span', 'native-journey-clues');
      clues.setAttribute('aria-hidden', 'true');
      for (const state of item.states) clues.append(nativeNode('i', state === 'complete' ? 'is-complete' : state === 'unknown' ? 'is-unknown' : ''));
      tile.append(clues, nativeNode('small', 'native-journey-clue-count', `${completed}/6`));
      tile.setAttribute('aria-label', `${item.label}: ${completed} de 6 pistas`);
      tile.title = `${item.label}: ${completed} de 6 pistas`;
    }
    grid.append(tile);
  }
  section.append(heading, grid); root.append(section);
}
function nativeCompletionObjective(label, steps, meta = '') {
  const states = steps.map(step => step.state);
  const state = states.length && states.every(value => value === 'complete') ? 'complete' :
    states.length && states.every(value => value === 'unknown') ? 'unknown' :
      states.length && states.every(value => value === 'missing') ? 'missing' : 'partial';
  const mark = state === 'complete' ? '☑' : state === 'unknown' ? '◌' : state === 'partial' ? '◩' : '☐';
  const stateLabel = ({complete: 'Concluído', partial: 'Em progresso', missing: 'Pendente', unknown: 'Não detectável'})[state];
  const details = nativeNode('details', 'native-completion-objective');
  const summary = nativeNode('summary', 'native-completion-objective-summary');
  summary.append(nativeNode('span', `native-completion-mark is-${state}`, mark),
    nativeNode('strong', '', label),
    nativeNode('span', 'native-completion-state', meta || stateLabel));
  details.append(summary);
  const list = nativeNode('ul', 'native-completion-guide-list');
  steps.forEach(step => {
    const row = nativeNode('li', `is-${step.state}`);
    const stepMark = step.state === 'complete' ? '☑' : step.state === 'unknown' ? '◌' : '☐';
    row.append(nativeNode('span', 'native-completion-step-mark', stepMark),
      nativeNode('span', '', step.text));
    list.append(row);
  });
  details.append(list);
  return details;
}
async function refreshNative() {
  if (nativeBusy) return;
  const epochAtStart = ++nativeEpoch;
  try {
    const rows = await api('/api/native-saves/saves');
    if (epochAtStart !== nativeEpoch) return;
    nativeRows = rows;
    if (!nativeCatalog) {
      const response = await fetch('/assets/catalog.json');
      if (response.ok) nativeCatalog = await response.json();
    }
    const select = $('native-snapshot-select'), oldHash = nativeHash || select.value;
    select.replaceChildren();
    for (const row of nativeRows) {
      const state = row.state === 'supported' ? `${row.game} · válido`
        : row.state === 'invalid' ? `Arquivo inválido · ${row.reason || 'estrutura ou checksum inválido'}`
          : `Não suportado · ${row.reason || 'formato desconhecido'}`;
      select.add(new Option(`${row.filename} · ${state} · ${row.sha256.slice(0, 8)}`, row.sha256));
    }
    const chosen = nativeRows.find(row => row.sha256 === oldHash) || nativeRows.find(row => row.state === 'supported') || nativeRows[0];
    if (!chosen) {
      nativeHash = ''; nativeSnapshot = null; $('native-empty').hidden = false;
      $('native-summary').hidden = true; $('native-panel').hidden = true; return;
    }
    nativeHash = chosen.sha256; select.value = nativeHash;
    if (chosen.state !== 'supported') {
      nativeSnapshot = null; $('native-empty').hidden = true; $('native-summary').hidden = true;
      $('native-panel').hidden = false; $('native-panel').replaceChildren();
      const invalid = chosen.state === 'invalid';
      $('native-panel').append(nativeNode('h3', '', invalid ? 'Save preservado, mas inválido' : 'Save preservado, formato não suportado'), nativeNode('p', 'native-unknown-note', chosen.reason || 'Nenhum parser compatível reconheceu o arquivo.'));
      return;
    }
    await loadNativeSnapshot(chosen.sha256, epochAtStart);
  } catch (error) {
    $('native-empty').hidden = true; $('native-panel').hidden = false; $('native-panel').replaceChildren();
    $('native-panel').append(nativeNode('p', 'native-error', error.message));
  }
}
async function loadNativeSnapshot(hash, expectedEpoch = nativeEpoch) {
  nativeHash = hash;
  if (!hash) return;
  try {
    const snapshot = await api('/api/native-saves/snapshot?id=' + encodeURIComponent(hash));
    if (expectedEpoch !== nativeEpoch || nativeHash !== hash) return;
    nativeSnapshot = snapshot;
    if (nativeCompletionHash !== hash) { nativeCompletionHash = ''; nativeCompletion = null; }
    $('native-empty').hidden = true; $('native-summary').hidden = false;
    $('native-panel').hidden = false; await renderNativeSummary(); await renderNativePanel();
  } catch (error) {
    if (expectedEpoch !== nativeEpoch) return;
    nativeSnapshot = null; $('native-summary').hidden = true; $('native-panel').hidden = false;
    $('native-panel').replaceChildren(nativeNode('p', 'native-error', error.message));
  }
}
async function getNativeCompletion(hash = nativeHash) {
  if (nativeCompletionHash === hash && nativeCompletion) return nativeCompletion;
  const report = await api('/api/native-saves/completion?id=' + encodeURIComponent(hash));
  nativeCompletionHash = hash; nativeCompletion = report;
  return report;
}
async function renderNativeSummary() {
  const snapshot = nativeSnapshot, root = $('native-summary'); root.replaceChildren();
  if (!snapshot) return;
  const trainer = snapshot.trainer, play = trainer.playTime.value;
  let percent = '—';
  try { percent = `${(await getNativeCompletion(snapshot.saveHash)).percent}%`; } catch {}
  const cards = [
    ['Treinador', trainer.name.value || 'Nome não decodificado'],
    ['ID do Trainer Card', trainer.trainerId?.value == null ? 'Desconhecido' : String(trainer.trainerId.value).padStart(5, '0')],
    ['Pokédex', `${snapshot.pokedex.caughtCount} capturados · ${snapshot.pokedex.seenCount} vistos`],
    ['Badges', String(Object.values(snapshot.badges).flat().filter(row => row.acquired).length)],
    ['Tempo de jogo', play ? `${play.hours}h ${String(play.minutes).padStart(2, '0')}m` : 'Desconhecido']
  ];
  root.append(nativeNode('h3', 'native-game-title', `${snapshot.game} · ${trainer.name.value || 'Treinador'}`));
  const content = nativeNode('div', 'native-summary-content');
  const player = nativeNode('div', 'native-player-portrait');
  const female = trainer.gender?.value === 'female';
  const playerSprite = nativeNode('img', 'native-player-sprite');
  playerSprite.src = `/assets/native-player-${female ? 'leaf' : 'red'}.png`;
  playerSprite.alt = female ? 'Protagonista de FireRed, versão feminina' : 'Protagonista de FireRed, versão masculina';
  playerSprite.width = 160; playerSprite.height = 160; playerSprite.decoding = 'async';
  player.append(playerSprite);
  const grid = nativeNode('div', 'native-summary-grid');
  for (const [label, value] of cards) { const card = nativeNode('div', 'native-stat'); card.append(nativeNode('span', '', label), nativeNode('strong', '', value)); grid.append(card); }
  const caught = new Set(snapshot.pokedex.caught || []);
  const nationalDexExcluded = new Set([151, 249, 250, 251, 385, 386]);
  const kantoDexComplete = Array.from({length: 150}, (_, index) => index + 1).every(species => caught.has(species));
  const nationalDexComplete = Array.from({length: 386}, (_, index) => index + 1)
    .filter(species => !nationalDexExcluded.has(species)).every(species => caught.has(species));
  const minigames = snapshot.completionData?.minigames || {};
  const hallOfFame = snapshot.hallOfFame;
  const isFireRed = ['FR', 'LG', 'FRLG'].includes(snapshot.gameVersion);
  const starCriteria = isFireRed ? [
    {label: 'Entrar no Hall da Fama', earned: Number.isInteger(hallOfFame?.count) && hallOfFame.count > 0},
    {label: 'Completar a Pokédex de Kanto, exceto Mew', earned: kantoDexComplete},
    {label: 'Completar a Pokédex Nacional, exceto Mew, Lugia, Ho-Oh, Celebi, Jirachi e Deoxys', earned: nationalDexComplete},
    {label: 'Atingir 200 saltos consecutivos e 200 berries no Dodrio Berry Picking',
      earned: (minigames.pokemonJump?.jumpsInRow || 0) >= 200 && (minigames.dodrioBerryPicking?.berriesPicked || 0) >= 200}
  ] : [];
  const earnedStars = starCriteria.filter(item => item.earned).length;
  const completionCard = nativeNode('div', 'native-stat native-completion-stat');
  completionCard.append(nativeNode('span', '', 'Conclusão'));
  const completionValue = nativeNode('div', 'native-completion-value');
  completionValue.append(nativeNode('strong', 'native-completion-percent', percent));
  if (isFireRed) {
    const stars = nativeNode('div', 'native-trainer-stars');
    stars.setAttribute('role', 'img'); stars.setAttribute('aria-label', `Trainer Card: ${earnedStars} de 4 estrelas`);
    stars.title = starCriteria.map((item, index) => `${index + 1}. ${item.label}: ${item.earned ? 'obtida' : 'pendente'}`).join('\n');
    for (let index = 0; index < starCriteria.length; index++) {
      stars.append(nativeNode('span', `native-trainer-star${starCriteria[index].earned ? ' is-earned' : ''}`, '★'));
    }
    player.append(stars);
  }
  completionCard.append(completionValue); grid.append(completionCard);
  content.append(player, grid);
  root.append(content, nativeNode('small', 'native-hash', `SHA-256 ${snapshot.saveHash}`));
  if (snapshot.comparison) {
    const delta = snapshot.comparison, section = nativeNode('section', 'native-comparison');
    section.append(nativeNode('h4', '', 'Mudanças desde o snapshot anterior do mesmo treinador'));
    const time = value => {
      if (value == null) return '—';
      const absolute = Math.abs(value), sign = value > 0 ? '+' : value < 0 ? '−' : '';
      const hours = Math.floor(absolute / 3600), minutes = Math.floor((absolute % 3600) / 60);
      return `${sign}${hours}h ${String(minutes).padStart(2, '0')}m`;
    };
    const changes = [
      ['Badges', `+${delta.badgeAdditions.length} / −${delta.badgeRemovals.length}`],
      ['Tempo de jogo', time(delta.playTimeDeltaSeconds)]
    ];
    const changeGrid = nativeNode('div', 'native-change-grid');
    for (const [label, value] of changes) { const card = nativeNode('div', 'native-change'); card.append(nativeNode('span', '', label), nativeNode('strong', '', value)); changeGrid.append(card); }
    section.append(changeGrid);
    const badgeNames = [...delta.badgeAdditions.map(name => `+ ${name}`), ...delta.badgeRemovals.map(name => `− ${name}`)];
    if (badgeNames.length) section.append(nativeNode('p', 'native-change-detail', badgeNames.join(' · ')));
    section.append(nativeNode('small', 'native-change-evidence', 'Diferenças entre duas leituras; o instante do acontecimento pode estar entre os snapshots.'));
    root.append(section);
  }
}
async function renderNativePanel() {
  const root = $('native-panel'); root.replaceChildren();
  document.querySelectorAll('[data-native-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.nativeTab === nativeTab)));
  if (!nativeSnapshot) return;
  if (nativeTab === 'pokedex') return renderNativeDex(root);
  if (nativeTab === 'journey') return renderNativeJourney(root);
  if (nativeTab === 'completion') return renderNativeCompletion(root);
  if (nativeTab === 'miscellany') return renderNativeMiscellany(root);
  if (nativeTab === 'hall-of-fame') return renderNativeHallOfFame(root);
}
function renderNativeMiscellany(root) {
  const data = nativeSnapshot.miscellany || {};
  const trainers = data.trainerBattles || {};
  const hiddenItems = data.hiddenItems || {};
  root.append(nativeNode('h3', '', `${nativeSnapshot.game} · Miscelânea`));
  root.append(nativeNode('p', 'native-muted', 'Objetivos opcionais consultados diretamente nos flags do save. Eles ficam fora do percentual de completude principal.'));

  const grid = nativeNode('div', 'native-misc-grid');
  const trainerCard = nativeNode('article', `native-misc-card${trainers.state === 'supported' && trainers.defeated >= trainers.total ? ' is-complete' : ''}`);
  trainerCard.append(nativeNode('h4', '', 'Batalhas de treinadores'));
  trainerCard.append(nativeNode('strong', 'native-misc-value',
    trainers.state === 'supported' ? `${trainers.defeated} / ${trainers.total}` : 'Indisponível'));
  trainerCard.append(nativeNode('p', '', 'Registros de vitória dos treinadores definidos pelo jogo. O total conta IDs internos, incluindo variantes de revanche; não corresponde ao número de NPCs.'));
  grid.append(trainerCard);

  const itemCard = nativeNode('article', `native-misc-card${hiddenItems.state === 'supported' && hiddenItems.found >= hiddenItems.total ? ' is-complete' : ''}`);
  itemCard.append(nativeNode('h4', '', 'Itens ocultos permanentes'));
  itemCard.append(nativeNode('strong', 'native-misc-value',
    hiddenItems.state === 'supported' ? `${hiddenItems.found} / ${hiddenItems.total}` : 'Indisponível'));
  itemCard.append(nativeNode('p', '', 'Progresso dos itens únicos. Os 61 itens renováveis aparecem no cartão ao lado porque o jogo pode reativar os seus flags.'));
  grid.append(itemCard);

  const renewableCard = nativeNode('article', 'native-misc-card');
  renewableCard.append(nativeNode('h4', '', 'Itens ocultos renováveis'));
  renewableCard.append(nativeNode('strong', 'native-misc-value',
    hiddenItems.state === 'supported' ? `${hiddenItems.renewableAvailable} / ${hiddenItems.renewableTotal} disponíveis` : 'Indisponível'));
  renewableCard.append(nativeNode('p', '', 'Mostra quais flags estão disponíveis no ciclo atual. Após 1.500 passos, ao entrar em uma área de renovação, o jogo sorteia estes itens novamente; esse estado não revela se já foram coletados antes.'));
  grid.append(renewableCard);
  root.append(grid);

  const trainerList = Array.isArray(trainers.items) ? trainers.items : [];
  if (trainerList.length) {
    const details = nativeNode('details', 'native-misc-details');
    details.append(nativeNode('summary', '', `Ver os ${trainerList.length} registros de treinadores`));
    const search = nativeNode('input', 'native-search');
    search.type = 'search'; search.placeholder = 'Buscar treinador ou ID';
    search.setAttribute('aria-label', 'Buscar registro de treinador');
    details.append(search);
    const list = nativeNode('ul', 'native-misc-item-list');
    const draw = () => {
      list.replaceChildren();
      const query = search.value.trim().toLocaleLowerCase();
      const filtered = trainerList.filter(trainer => !query ||
        `${trainer.name} ${trainer.trainerId}`.toLocaleLowerCase().includes(query));
      for (const trainer of filtered) {
        const row = nativeNode('li', `native-misc-item${trainer.defeated ? ' is-found' : ''}`);
        row.append(nativeNode('span', 'native-misc-item-mark', trainer.defeated ? '✓' : '□'));
        const text = nativeNode('span', 'native-misc-item-text');
        text.append(nativeNode('strong', '', trainer.name),
          nativeNode('small', '', `ID ${trainer.trainerId} · ${trainer.defeated ? 'vitória registrada' : 'pendente'}`));
        row.append(text); list.append(row);
      }
      if (!filtered.length) list.append(nativeNode('li', 'native-empty-inline', 'Nenhum treinador corresponde à busca.'));
    };
    search.oninput = draw; draw(); details.append(list); root.append(details);
  }

  const items = Array.isArray(hiddenItems.items) ? hiddenItems.items : [];
  if (!items.length) {
    root.append(nativeNode('p', 'native-empty-inline', 'A lista de itens ocultos não está disponível neste snapshot.'));
    return;
  }
  const details = nativeNode('details', 'native-misc-details');
  details.append(nativeNode('summary', '', `Ver os ${items.length} itens ocultos por local`));
  const search = nativeNode('input', 'native-search');
  search.type = 'search'; search.placeholder = 'Buscar item ou local';
  search.setAttribute('aria-label', 'Buscar item oculto por nome ou local');
  details.append(search);
  const list = nativeNode('ul', 'native-misc-item-list');
  const draw = () => {
    list.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase();
    const filtered = items.filter(item => !query ||
      `${item.item} ${item.location}`.toLocaleLowerCase().includes(query));
    for (const item of filtered) {
      const renewable = item.renewable === true;
      const available = renewable && item.available === true;
      const row = nativeNode('li', `native-misc-item${renewable ? ' is-renewable' : item.found ? ' is-found' : ''}${available ? ' is-available' : ''}`);
      row.append(nativeNode('span', 'native-misc-item-mark', renewable ? available ? '●' : '○' : item.found ? '✓' : '□'));
      const text = nativeNode('span', 'native-misc-item-text');
      const state = renewable ? available ? 'disponível neste ciclo' : 'não ativo neste ciclo' : item.found ? 'encontrado' : 'pendente';
      text.append(nativeNode('strong', '', item.item), nativeNode('small', '', `${item.location} · ${state}`));
      row.append(text); list.append(row);
    }
    if (!filtered.length) list.append(nativeNode('li', 'native-empty-inline', 'Nenhum item corresponde à busca.'));
  };
  search.oninput = draw; draw(); details.append(list); root.append(details);
}
function renderNativeHallOfFame(root) {
  const hall = nativeSnapshot.hallOfFame || {};
  root.append(nativeNode('h3', '', `${nativeSnapshot.game} · Hall da Fama`));
  root.append(nativeNode('p', 'native-muted', 'As equipes mais recentes aparecem primeiro; o jogo não grava a data de cada entrada. O save registra espécie, apelido, nível e personalidade, então a natureza pode ser calculada; item e golpes usados na Liga não ficam guardados.'));
  if (hall.state === 'unknown') {
    root.append(nativeNode('p', 'native-unknown-note', hall.reason || 'Os setores do Hall da Fama não puderam ser lidos neste save.'));
    return;
  }
  if (hall.state === 'partial') {
    root.append(nativeNode('p', 'native-unknown-note', 'Alguns registros do Hall da Fama têm dados inválidos e foram omitidos.'));
  }
  const entries = Array.isArray(hall.entries) ? [...hall.entries].sort((a, b) => b.index - a.index) : [];
  root.append(nativeNode('p', 'native-hof-count', `${hall.count ?? entries.length} ${entries.length === 1 ? 'equipe registrada' : 'equipes registradas'} · limite do jogo: 50`));
  if (!entries.length) {
    root.append(nativeNode('p', 'native-empty-inline', 'Nenhuma equipe registrada no Hall da Fama neste save.'));
    return;
  }
  const grid = nativeNode('div', 'native-hof-grid');
  for (const entry of entries) {
    const card = nativeNode('article', 'native-hof-card');
    card.append(nativeNode('h4', '', `Entrada ${String(entry.index).padStart(2, '0')}`));
    const teamScroll = nativeNode('div', 'native-hof-team-scroll');
    const team = nativeNode('div', 'native-hof-team');
    for (const mon of entry.pokemon || []) {
      const member = nativeNode('div', 'native-hof-member');
      const sprite = nativeNode('span', 'native-hof-sprite');
      sprite.style.cssText = spriteStyle(mon.species, 2); sprite.setAttribute('aria-hidden', 'true');
      const identity = nativeNode('span', 'native-hof-identity');
      identity.append(nativeNode('strong', '', mon.nickname || mon.name),
        nativeNode('small', '', `${mon.name} · Nv. ${mon.level}`),
        nativeNode('small', 'native-hof-nature', `Natureza: ${mon.nature || 'desconhecida'}`));
      member.append(sprite, identity); team.append(member);
    }
    teamScroll.append(team); card.append(teamScroll); grid.append(card);
  }
  root.append(grid);
}
function renderNativeDex(root) {
  const snapshot = nativeSnapshot, dex = snapshot.pokedex;
  const totalSpecies = dex.totalSpecies || 493;
  const nationalUnlocked = dex.nationalDex === true;
  const dexTitle = dex.regionalSpecies && !nationalUnlocked ? 'Pokédex de Kanto' :
    totalSpecies === 386 || dex.nationalDex === true ? 'Pokédex Nacional' : 'Pokédex';
  const displaySpeciesCount = dex.regionalSpecies && !nationalUnlocked
    ? dex.regionalSpecies : totalSpecies;
  root.append(nativeNode('h3', '', `${snapshot.game} · ${dexTitle}`));
  const captured = new Set(dex.caught), seen = new Set(dex.seen);
  const observedBySpecies = new Map();
  for (const mon of snapshot.pokemon) {
    if (!observedBySpecies.has(mon.species)) observedBySpecies.set(mon.species, []);
    observedBySpecies.get(mon.species).push(mon);
  }
  const nationalDex = snapshot.story.national_dex;
  const nationalStatus = nationalDex?.state !== 'supported' ? 'estado desconhecido' :
    nationalDex.value ? 'desbloqueada' : 'não desbloqueada';
  const unseenCount = Array.from({length: displaySpeciesCount}, (_, index) => index + 1)
    .filter(id => !seen.has(id) && !captured.has(id)).length;
  root.append(nativeNode('p', 'native-muted', `${dex.caughtCount} capturados · ${dex.seenCount} vistos · ${unseenCount} não vistos · National Dex ${nationalStatus}.`));
  const legend = nativeNode('div', 'native-dex-legend');
  const legendItem = (label, kind) => {
    const item = nativeNode('span', `native-dex-legend-item ${kind}`);
    if (kind === 'caught') item.append(nativePokeBallIcon());
    else item.append(nativeNode('i', 'native-dex-legend-dot'));
    item.append(nativeNode('span', '', label)); legend.append(item);
  };
  legendItem('Capturado', 'caught'); legendItem('Visto', 'seen'); legendItem('Não visto', 'unseen');
  root.append(legend);
  root.append(nativeNode('p', 'native-dex-capture-date-note', 'O save FireRed não registra a data individual da captura; por isso ela não aparece nos cartões.'));
  const search = nativeNode('input', 'native-search'); search.type = 'search'; search.placeholder = 'Buscar número, espécie ou estado'; search.setAttribute('aria-label', 'Buscar espécie ou estado da Pokédex'); root.append(search);
  const list = nativeNode('div', 'native-dex-grid'); root.append(list);
  const names = nativeCatalog?.names || [];
  const draw = () => {
    list.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase();
    for (let id = 1; id <= displaySpeciesCount; id++) {
      const name = names[id] || `Espécie ${id}`;
      const isCaught = captured.has(id);
      const isSeen = seen.has(id) || isCaught;
      const state = isCaught ? 'capturado' : isSeen ? 'visto' : 'não visto';
      if (query && !String(id).includes(query) && !name.toLocaleLowerCase().includes(query) && !state.includes(query)) continue;
      const card = nativeNode('article', `native-dex-card is-${isCaught ? 'caught' : isSeen ? 'seen' : 'unseen'}`);
      const portrait = nativeNode('span', 'native-dex-portrait');
      const sprite = nativeNode('span', `native-dex-sprite${isSeen ? '' : ' is-unseen'}`);
      sprite.style.cssText = spriteStyle(id); sprite.setAttribute('aria-hidden', 'true');
      portrait.append(sprite);
      if (isCaught) {
        const ball = nativePokeBallIcon(); ball.classList.add('native-dex-caught-icon');
        ball.setAttribute('aria-label', 'Capturado'); ball.setAttribute('role', 'img'); portrait.append(ball);
      }
      const info = nativeNode('div', 'native-dex-info');
      info.append(nativeNode('strong', 'native-dex-name', name),
        nativeNode('span', 'native-dex-number', `#${String(id).padStart(3, '0')}`),
        nativeNode('span', `native-dex-state ${isCaught ? 'caught' : isSeen ? 'seen' : 'unseen'}`, state));
      card.append(portrait, info);
      const observed = observedBySpecies.get(id) || [];
      if (observed.length) {
        const details = observed.map(mon => `${nativeLocation(mon.location)} · ${nativeStatus(mon.identityStatus)}${mon.shiny ? ' · Brilhante' : ''}`);
        card.append(nativeNode('small', 'native-dex-detail', `${observed.length} no save: ${details.join(' | ')}`));
      }
      list.append(card);
    }
    if (!list.childElementCount) list.append(nativeNode('p', 'native-empty-inline', 'Nenhum Pokémon corresponde à busca.'));
  };
  search.oninput = draw; draw();
}
function nativePokeBallIcon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 20 20'); svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const upper = document.createElementNS(svg.namespaceURI, 'path');
  upper.setAttribute('d', 'M2 10a8 8 0 0 1 16 0H2z'); upper.setAttribute('fill', '#e5535b');
  const lower = document.createElementNS(svg.namespaceURI, 'path');
  lower.setAttribute('d', 'M2 10a8 8 0 0 0 16 0H2z'); lower.setAttribute('fill', '#f3f4f6');
  const outline = document.createElementNS(svg.namespaceURI, 'circle');
  outline.setAttribute('cx', '10'); outline.setAttribute('cy', '10'); outline.setAttribute('r', '8');
  outline.setAttribute('fill', 'none'); outline.setAttribute('stroke', '#26354a'); outline.setAttribute('stroke-width', '1.5');
  const band = document.createElementNS(svg.namespaceURI, 'path');
  band.setAttribute('d', 'M2 10h16'); band.setAttribute('stroke', '#26354a'); band.setAttribute('stroke-width', '1.7');
  const button = document.createElementNS(svg.namespaceURI, 'circle');
  button.setAttribute('cx', '10'); button.setAttribute('cy', '10'); button.setAttribute('r', '2.4');
  button.setAttribute('fill', '#f3f4f6'); button.setAttribute('stroke', '#26354a'); button.setAttribute('stroke-width', '1.3');
  svg.append(upper, lower, outline, band, button);
  return svg;
}
function renderNativeJourney(root) {
  const snapshot = nativeSnapshot, completion = snapshot.completionData || {};
  const item = (label, icon, state) => ({label, ...icon, state});
  const fieldState = field => field?.state !== 'supported' ? 'unknown' : field.value ? 'complete' : 'missing';
  const storyItem = (key, label, icon) => item(label, icon, fieldState(snapshot.story?.[key]));
  root.append(nativeNode('h3', '', `${snapshot.game} · Journey`));

  const badgeByName = new Map((snapshot.badges?.kanto || []).map(badge => [badge.name, badge]));
  const badges = [
    ['Boulder', 'Pedra', 'journey-badge-boulder.png'],
    ['Cascade', 'Cascata', 'journey-badge-cascade.png'],
    ['Thunder', 'Trovão', 'journey-badge-thunder.png'],
    ['Rainbow', 'Arco-íris', 'journey-badge-rainbow.png'],
    ['Soul', 'Alma', 'journey-badge-soul.png'],
    ['Marsh', 'Pântano', 'journey-badge-marsh.png'],
    ['Volcano', 'Vulcão', 'journey-badge-volcano.png'],
    ['Earth', 'Terra', 'journey-badge-earth.png']
  ].map(([badge, label, src]) => item(label, {src}, badgeByName.has(badge)
    ? badgeByName.get(badge).acquired ? 'complete' : 'missing' : 'unknown'));
  nativeJourneyGroup(root, 'Insígnias de Kanto', badges);

  nativeJourneyGroup(root, 'Kanto', [
    storyItem('game_clear', 'Liga Pokémon', {symbol: 'champion'}),
    storyItem('pokedex_received', 'Pokédex recebida', {symbol: 'pokedex'}),
    storyItem('national_dex', 'Receber Pokédex Nacional', {symbol: 'pokedex'})
  ]);

  const sevii = [
    ['sevii_islands_1_3', 'Ilhas 1–3', {src: 'journey-item-rainbow-pass.png'}],
    ['sevii_islands_4_7', 'Ilhas 4–7', {src: 'journey-item-rainbow-pass.png'}],
    ['lostelle_rescued', 'Lostelle', {src: 'journey-lostelle.png'}],
    ['sevii_detour_finished', 'Desvio Sevii', {symbol: 'boat'}],
    ['rocket_warehouse_cleared', 'Armazém Rocket', {src: 'journey-trainer-rocket.png'}],
    ['ruby_recovered', 'Ruby', {src: 'journey-item-ruby.png'}],
    ['sapphire_recovered', 'Sapphire', {src: 'journey-item-sapphire.png'}],
    ['tanoby_ruins_unlocked', 'Ruínas Tanoby', {symbol: 'ruins'}]
  ].map(([key, label, icon]) => storyItem(key, label, icon));
  nativeJourneyGroup(root, 'Ilhas Sevii', sevii);

  const caughtSpecies = Array.isArray(snapshot.pokedex?.caught)
    ? new Set(snapshot.pokedex.caught) : null;
  // FireRed/LeafGreen event availability: Mew was directly distributed to
  // FRLG saves, while Lugia, Ho-Oh, and Deoxys are reached through event tickets.
  // Celebi and Jirachi come from external distributions and are not FRLG events.
  const eventSpecies = [151, 249, 250, 386].map(species => {
    const label = nativeCatalog?.names?.[species] || `Espécie ${species}`;
    const state = !caughtSpecies ? 'unknown'
      : caughtSpecies.has(species) ? 'complete' : 'missing';
    return item(label, {pokemonSprite: species}, state);
  });
  nativeJourneyGroup(root, 'Eventos de FireRed/LeafGreen', eventSpecies);

  const regionalDexSpecies = new Set([...(caughtSpecies || [])].filter(species =>
    Number.isInteger(species) && species >= 1 && species <= 150));
  const nationalDexSpecies = new Set([...(caughtSpecies || [])].filter(species =>
    Number.isInteger(species) && species >= 1 && species <= 386 &&
    ![151, 249, 250, 251, 385, 386].includes(species)));
  const captureItem = (label, captured, total) => ({
    ...item(label, {symbol: 'pokedex'}, !caughtSpecies ? 'unknown' : captured.size >= total ? 'complete' : 'missing'),
    meta: caughtSpecies ? `${captured.size} / ${total} capturas` : 'Capturas indisponíveis'
  });
  nativeJourneyGroup(root, 'Capturas da Pokédex', [
    captureItem('Pokédex Regional', regionalDexSpecies, 150),
    captureItem('Pokédex Nacional', nationalDexSpecies, 380)
  ]);

  const famePeople = [
    ['Professor Oak', 'oak'], ['Daisy', 'daisy'], ['Brock', 'brock'], ['Misty', 'misty'],
    ['Lt. Surge', 'surge'], ['Erika', 'erika'], ['Koga', 'koga'], ['Sabrina', 'sabrina'],
    ['Blaine', 'blaine'], ['Lorelei', 'lorelei'], ['Bruno', 'bruno'], ['Agatha', 'agatha'],
    ['Lance', 'lance'], ['Bill', 'bill'], ['Mr. Fuji', 'fuji'], ['Giovanni', 'giovanni']
  ];
  const fameByPerson = new Map((completion.fameChecker || []).map(record => [record.person, record]));
  const fameItems = famePeople.map(([person, portrait]) => {
    const facts = fameByPerson.get(person)?.facts;
    const validFacts = Array.isArray(facts) && facts.length === 6 && facts.every(flag => typeof flag === 'boolean');
    const states = validFacts ? facts.map(flag => flag ? 'complete' : 'missing') : Array(6).fill('unknown');
    return {label: person, src: `journey-trainer-${portrait}.png`, states};
  });
  nativeJourneyGroup(root, 'Fame Checker', fameItems);

  const towerByMode = new Map((completion.trainerTower || []).map(record => [record.mode, record]));
  const towerModes = [
    ['Single', 'Individual'], ['Double', 'Duplas'], ['Knockout', 'Eliminação'], ['Mixed', 'Mista']
  ].map(([mode, label]) => {
    const record = towerByMode.get(mode), floors = record?.floorsCleared, prize = record?.receivedPrize;
    const known = Number.isInteger(floors) && floors >= 0 && floors <= 8 && typeof prize === 'boolean';
    return item(label, {src: 'journey-trainer-tower.png'}, !known ? 'unknown' : prize || floors === 8 ? 'complete' : 'missing');
  });
  nativeJourneyGroup(root, 'Trainer Tower', towerModes);

  const minigamesData = completion.minigames || {};
  const thresholdState = (value, target) => Number.isInteger(value) && value >= 0 && value <= 0xFFFF
    ? value >= target ? 'complete' : 'missing' : 'unknown';
  const minigames = [
    item('Pokémon Jump · 200 seguidos', {symbol: 'jump'}, thresholdState(minigamesData.pokemonJump?.jumpsInRow, 200)),
    item('Berry Picking · 200', {symbol: 'berries'}, thresholdState(minigamesData.dodrioBerryPicking?.berriesPicked, 200))
  ];
  nativeJourneyGroup(root, 'Minijogos', minigames);
}
async function renderNativeCompletion(root) {
  let report;
  try { report = await getNativeCompletion(nativeHash); }
  catch (error) { root.append(nativeNode('p', 'native-error', error.message)); return; }
  root.append(nativeNode('h3', '', `Completude · ${report.profile.name}`));
  const progress = nativeNode('div', 'native-completion-progress');
  progress.append(nativeNode('strong', '', `${report.completed} / ${report.total}`), nativeNode('span', '', 'critérios completos no perfil')); root.append(progress);
  root.append(nativeNode('p', report.completeWithinProfile ? 'native-complete' : 'native-muted', report.completeWithinProfile ? 'Todos os critérios deste perfil estão completos.' : 'As capturas entram no percentual e ficam detalhadas somente na Pokédex. Abra cada critério abaixo para ver como concluí-lo.'));
  root.append(nativeNode('p', 'native-unknown-note', report.profile.caveat || '100% do jogo não pode ser confirmado ainda: conteúdo e flags adicionais não estão todos modelados.'));
  const categoryGrid = nativeNode('div', 'native-completion-groups');
  const visibleGroups = (report.groups || []).filter(group => group.id !== 'pokedex');
  const missingIds = new Set((report.missing || []).map(item => item.id));
  const unknownIds = new Set((report.unknown || []).map(item => item.id));
  const criterionState = id => unknownIds.has(id) ? 'unknown' : missingIds.has(id) ? 'missing' : 'complete';
  const firered = ['FR', 'LG', 'FRLG'].includes(nativeSnapshot?.gameVersion);
  const badgeLeaders = {
    johto: {
      Zephyr: ['Falkner', 'Violet'], Hive: ['Bugsy', 'Azalea'], Plain: ['Whitney', 'Goldenrod'],
      Fog: ['Morty', 'Ecruteak'], Storm: ['Chuck', 'Cianwood'], Mineral: ['Jasmine', 'Olivine'],
      Glacier: ['Pryce', 'Mahogany'], Rising: ['Clair', 'Blackthorn']
    },
    kanto: {
      Boulder: ['Brock', 'Pewter'], Cascade: ['Misty', 'Cerulean'], Thunder: ['Lt. Surge', 'Vermilion'],
      Rainbow: ['Erika', 'Celadon'], Soul: ['Koga', 'Fuchsia'], Marsh: ['Sabrina', 'Saffron'],
      Volcano: ['Blaine', 'Cinnabar'], Earth: ['Giovanni', 'Viridian']
    }
  };
  const storyObjectives = firered ? [
    ['game_clear', 'Liga Pokémon', nativeStoryGuides.game_clear],
    ['national_dex', 'National Dex', nativeStoryGuides.national_dex],
    ['sevii_islands_1_3', 'Ilhas Sevii 1–3', nativeStoryGuides.sevii_islands_1_3],
    ['sevii_islands_4_7', 'Ilhas Sevii 4–7', nativeStoryGuides.sevii_islands_4_7],
    ['lostelle_rescued', 'Lostelle resgatada', nativeStoryGuides.lostelle_rescued],
    ['sevii_detour_finished', 'Desvio de Sevii', nativeStoryGuides.sevii_detour_finished],
    ['rocket_warehouse_cleared', 'Armazém Rocket', nativeStoryGuides.rocket_warehouse_cleared],
    ['ruby_recovered', 'Ruby', nativeStoryGuides.ruby_recovered],
    ['sapphire_recovered', 'Sapphire', nativeStoryGuides.sapphire_recovered],
    ['tanoby_ruins_unlocked', 'Ruínas Tanoby', nativeStoryGuides.tanoby_ruins_unlocked]
  ] : [
    ['johto_champion', 'Campeão de Johto', nativeStoryGuides.johto_champion],
    ['kanto_unlocked', 'Kanto desbloqueada', nativeStoryGuides.kanto_unlocked]
  ];
  const addObjective = (card, label, id, text, meta = '') =>
    card.append(nativeCompletionObjective(label, [{state: criterionState(id), text}], meta));

  for (const group of visibleGroups) {
    const isComplete = group.total > 0 && group.completed >= group.total && !group.unknown;
    const card = nativeNode('section', `native-completion-group${isComplete ? ' is-complete' : ''}`);
    card.append(nativeNode('h4', '', group.label));
    card.append(nativeNode('p', 'native-completion-count', `${group.completed} / ${group.total} completos${group.unknown ? ` · ${group.unknown} não detectáveis` : ''}`));
    if (group.id === 'badges') {
      for (const [region, badges] of Object.entries(nativeSnapshot?.badges || {})) {
        for (const badge of badges) {
          const [leader, city] = badgeLeaders[region]?.[badge.name] || [badge.name, region];
          const label = `${region === 'johto' ? 'Johto' : 'Kanto'} · Insígnia ${badge.name}`;
          addObjective(card, label, `badge:${region}:${badge.name}`,
            `Vença ${leader} no Ginásio de ${city} e receba a Insígnia ${badge.name}.`);
        }
      }
    } else if (group.id === 'story') {
      for (const [key, label, guide] of storyObjectives) {
        addObjective(card, label, `story:${key}`, guide);
      }
    } else if (group.id === 'fameChecker') {
      for (const [person, guide] of Object.entries(nativeFameCheckerGuides)) {
        const steps = guide.map((text, index) => ({
          text,
          state: criterionState(`fame:${person.toLowerCase().replace(/ /g, '-')}:${index + 1}`)
        }));
        const done = steps.filter(step => step.state === 'complete').length;
        const unknown = steps.filter(step => step.state === 'unknown').length;
        const meta = unknown ? `${done}/6 pistas · ${unknown} não detectáveis` : `${done}/6 pistas`;
        card.append(nativeCompletionObjective(person, steps, meta));
      }
    } else if (group.id === 'trainerTower') {
      const modes = new Map((nativeSnapshot?.completionData?.trainerTower || [])
        .map(record => [record.mode, record]));
      const names = {Single: 'Individual', Double: 'Duplas', Knockout: 'Eliminação', Mixed: 'Mista'};
      for (const [mode, name] of Object.entries(names)) {
        const record = modes.get(mode), floors = record?.floorsCleared;
        const meta = Number.isInteger(floors) ? `${Math.min(floors, 8)}/8 andares` : '';
        addObjective(card, name, `trainer-tower:${mode.toLowerCase()}`,
          `Na Trainer Tower, ao norte da Ilha Sete, escolha o modo ${name}, vença os oito andares e receba o prêmio.`, meta);
      }
    } else if (group.id === 'minigames') {
      const games = nativeSnapshot?.completionData?.minigames || {};
      const jump = games.pokemonJump?.jumpsInRow;
      const berries = games.dodrioBerryPicking?.berriesPicked;
      addObjective(card, 'Pokémon Jump', 'minigame:pokemon-jump',
        'No Joyful Game Corner da Ilha Dois, complete uma partida de Pokémon Jump com 200 saltos consecutivos.',
        Number.isInteger(jump) ? `${jump}/200 saltos` : 'recorde não detectável');
      addObjective(card, 'Dodrio Berry Picking', 'minigame:dodrio-berry-picking',
        'No Joyful Game Corner da Ilha Dois, apanhe pelo menos 200 frutas em uma partida de Dodrio Berry Picking.',
        Number.isInteger(berries) ? `${berries}/200 frutas` : 'recorde não detectável');
    } else if (group.id === 'collections') {
      const forms = new Set(nativeSnapshot?.collections?.unownForms || []);
      const steps = Array.from({length: 28}, (_, form) => ({
        text: `Encontre e registre Unown da forma ${form + 1} nas Ruínas de Alph.`,
        state: criterionState(`unown:${form}`)
      }));
      const known = nativeSnapshot?.collections?.unownStatus === 'supported';
      const done = steps.filter(step => step.state === 'complete').length;
      card.append(nativeCompletionObjective('Formas de Unown', steps,
        known ? `${forms.size}/28 formas` : `${done}/28 formas · não detectável`));
    }
    categoryGrid.append(card);
  }
  if (categoryGrid.childElementCount) {
    const heading = nativeNode('h4', 'native-completion-heading', 'Progresso por categoria');
    root.append(heading, categoryGrid);
  }
  const definition = nativeNode('details', 'native-definition'); definition.append(nativeNode('summary', '', 'Como este percentual é calculado'));
  const list = nativeNode('ul'); for (const item of report.profile.definition) list.append(nativeNode('li', '', item)); definition.append(list); root.append(definition);
}
function dexManualIds(game = dexGame) {
  if (!dexState) return [];
  return dexState.mode === 'unified' ? (dexState.unified || [])
    : game === 'home' ? Object.values(dexState.individual || {}).flat()
    : (dexState.individual[game] || []);
}
function dexManualCaptured(id) { return dexManualIds().includes(id); }
function dexServerCaptured(id) {
  return Boolean(dexState && (dexState.homeServerCaptured || dexState.serverCaptured ||
    Object.keys(dexState.homeServerCounts || dexState.serverCounts || {}).map(Number)).includes(id));
}
function dexCaptured(id) { return dexServerCaptured(id) || dexManualCaptured(id); }
function dexRegion() { return dexData.regions.find(region => region.games.includes(dexGame)); }
function dexRegionalRows() {
  if (dexGame === 'home') return dexData.species;
  const ids = new Set(dexRegion()?.speciesIds || []);
  return dexData.species.filter(mon => ids.has(mon.id));
}
function dexCounterValues() {
  const nationalIds = new Set(dexGame === 'home'
    ? dexData.species.map(mon => mon.id)
    : (dexData.nationalSpeciesIds || dexData.species.map(mon => mon.id)));
  const regionalIds = new Set(dexRegionalRows().map(mon => mon.id));
  const automatic = dexState.homeServerCaptured || dexState.serverCaptured || [];
  const nationalCaptured = new Set([...automatic, ...dexManualIds('home')]);
  const regionalCaptured = dexGame === 'home' ? nationalCaptured : new Set([...automatic, ...dexManualIds()]);
  return {
    regionalTotal: regionalIds.size, nationalTotal: nationalIds.size,
    regionalCaptured: [...regionalIds].filter(id => regionalCaptured.has(id)).length,
    nationalCaptured: [...nationalIds].filter(id => nationalCaptured.has(id)).length,
  };
}
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
  const counts = dexState.homeServerCounts || dexState.serverCounts || {};
  const regionalRows = dexRegionalRows();
  const counters = dexCounterValues();
  const available = isHome ? regionalRows : regionalRows.filter(mon => dexAvailableInGame(mon, dexGame));
  $('dex-generation').value = isHome ? 'home' : '1';
  $('dex-eyebrow').textContent = isHome ? 'POKÉMON HOME · CATÁLOGO NACIONAL' : 'KANTO · GERAÇÃO I';
  $('dex-intro-copy').textContent = isHome
    ? 'Acompanhe sua coleção nacional. As espécies recebidas pelo PC e as capturas registradas contam para a Pokédex.'
    : 'Pokémon enviados ao servidor são considerados capturados automaticamente; também podes registrar capturas por jogo.';
  $('dex-regional-total').textContent = `${counters.regionalCaptured} / ${counters.regionalTotal.toLocaleString('pt-BR')}`;
  $('dex-national-total').textContent = `${counters.nationalCaptured} / ${counters.nationalTotal.toLocaleString('pt-BR')}`;
  $('dex-regional-summary').textContent = isHome ? 'Coleção HOME · todas as espécies do catálogo'
    : `${dexRegion().name} · ${dexState.mode === 'unified' ? 'progresso unificado' : dexGameName(dexGame)}`;
  $('dex-national-summary').textContent = isHome
    ? 'Coleção nacional · reúne as capturas de todos os jogos'
    : counters.nationalTotal === counters.regionalTotal
      ? `Mesmo total da Regional · ${dexRegion().name}`
      : `Escopo Nacional · espécies conhecidas até a Geração ${dexData.generation}`;
  $('dex-list-title').textContent = isHome ? 'Pokémon HOME · catálogo nacional' : (dexPool === 'all' ? 'Pokédex regional completa' : `Disponíveis em ${dexGameName(dexGame)}`);
  $('dex-game-note').textContent = isHome
    ? `${counters.nationalTotal} espécies disponíveis no catálogo nacional.`
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
  const rows = regionalRows.filter(mon => {
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
  const counts = dexState.homeServerCounts || dexState.serverCounts || {}, inServer = Number(counts[mon.id] || 0) > 0;
  const automaticCapture = dexServerCaptured(mon.id);
  const capturedState = dexCaptured(mon.id);
  const manualCaptured = dexManualCaptured(mon.id);
  const detail = $('dex-detail'); detail.replaceChildren();
  const heading = dexNode('div', 'dex-detail-heading');
  const sprite = dexNode('span', 'dex-detail-sprite'); sprite.style.cssText = spriteStyle(mon.sprite); sprite.dataset.inServer = String(inServer); sprite.dataset.captured = String(capturedState);
  const identity = dexNode('div', 'dex-detail-identity');
  identity.append(dexNode('span', 'eyebrow', `Nº ${String(mon.id).padStart(3, '0')} · ${mon.generation === 1 ? 'GERAÇÃO I' : 'POKÉDEX NACIONAL'}`), dexNode('h3', '', mon.name));
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
  if (!mon.detailed) return;
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
    dexData = await api('/api/pokedex/catalog');
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
function spriteStyle(index, scale = 1) { const column = index % 32, row = Math.floor(index / 32); return `background-position:-${column * 68 * scale}px -${row * 60 * scale}px;background-size:${2176 * scale}px ${1740 * scale}px`; }
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
  $('sort-by').disabled = busy || !hasBank || !boxData; $('sort-box').disabled = busy || !hasBank || !boxData; $('compact-box').disabled = busy || !hasBank; $('living-dex').disabled = busy || !hasBank;
  $('box-label').textContent = hasBank ? 'BOX ' + (boxIndex + 1) : 'BOX'; $('box-name').textContent = boxData ? boxData.name : (hasBank ? 'Carregando…' : 'Selecione um banco'); $('box-position').textContent = hasBank ? `${boxIndex + 1} / ${current.offer.boxes}` : '—';
  const grid = $('pokemon-grid'); grid.replaceChildren();
  if (!boxData) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = hasBank ? 'Lendo a box…' : 'A box selecionada aparecerá aqui.'; grid.append(empty); }
  else boxData.pokemon.forEach((pokemon, slot) => {
    const button = document.createElement('button'); const selected = Boolean((masks[boxIndex] || 0) & (1 << slot));
    const description = pokemon.valid ? `${pokemon.name} · National Dex #${String(pokemon.species).padStart(3, '0')}${pokemon.level ? ` · Level ${pokemon.level}` : ''}` : (pokemon.occupied ? 'Registro desconhecido' : 'Vazio');
    button.className = 'pokemon-slot' + (selected ? ' selected' : '') + (slot === cursor ? ' cursor' : '') + (!pokemon.occupied ? ' empty' : ''); button.setAttribute('role', 'gridcell'); button.setAttribute('aria-label', `Slot ${slot + 1}: ${description}`); button.title = pokemon.occupied ? description : 'Vazio';
    const number = document.createElement('span'); number.className = 'slot-number'; number.textContent = slot + 1; button.append(number);
    if (pokemon.occupied) { const sprite = document.createElement('span'); sprite.className = 'sprite'; sprite.style.cssText = spriteStyle(pokemon.sprite); button.append(sprite); if (pokemon.level) { const level = document.createElement('span'); level.className = 'slot-level'; level.textContent = 'Lv. ' + pokemon.level; button.append(level); } const name = document.createElement('span'); name.className = 'slot-name'; name.textContent = pokemon.valid ? pokemon.name : 'Registro'; button.append(name); }
    else { const mark = document.createElement('span'); mark.className = 'empty-mark'; mark.textContent = '·'; button.append(mark); }
    button.onclick = () => mark(slot); grid.append(button);
  });
  const count = selectionStats(); $('selection-count').textContent = count.boxes ? `${count.slots} espaços em ${count.boxes} boxes` : 'Nenhuma'; $('to-ds').disabled = busy || !current || !count.boxes; $('to-3ds').disabled = busy || !current || !count.boxes; $('clear').disabled = busy || !count.boxes;
}
async function organize(action) {
  const boxAction = action === 'sort';
  if (busy || !current || (boxAction && !boxData)) return;
  const sourceId = current.id, selectedBox = boxIndex;
  const sortKey = $('sort-by').value;
  const body = action === 'sort'
    ? {id: sourceId, action, box: selectedBox, by: sortKey}
    : {id: sourceId, action};
  const sortLabel = {name: 'nome', level: 'level', id: 'ID do Pokémon'}[sortKey];
  busy = true; renderBanks(); renderBox();
  status(action === 'sort' ? `Ordenando a box por ${sortLabel}…`
    : action === 'compact' ? 'Otimizando os espaços de todas as boxes sem mudar a ordem…'
      : 'Mapeando o banco inteiro na Living Dex…');
  try {
    const result = await api('/api/organize', body);
    await refresh();
    const organized = state.items.find(item => item.id === result.id);
    if (organized) {
      await selectBank(organized, true);
      const nextBox = action === 'compact' ? Math.min(selectedBox, organized.offer.boxes - 1) : selectedBox;
      if ((boxAction || action === 'compact') && nextBox > 0 && nextBox < organized.offer.boxes) await loadBox(nextBox);
    }
    if (result.created) status(action === 'sort'
      ? `Nova cópia ordenada por ${sortLabel}; o banco original foi mantido.`
      : action === 'compact' ? `${result.occupied} Pokémon reunidos em ${result.boxes} boxes; ordem preservada e banco original mantido.`
        : `Living Dex mapeada em ${result.boxes} boxes; repetidos agrupados, ${result.occupied} Pokémon mantidos e o banco original preservado.`);
    else status(action === 'sort'
      ? `A box já estava ordenada por ${sortLabel}; a cópia existente foi mantida.`
      : action === 'compact' ? 'Uma cópia com todas as boxes otimizadas já existe; ela foi selecionada.'
        : 'Este banco já tinha o mesmo mapeamento; a cópia existente foi mantida.');
  } catch (error) { status(error.message, true); }
  finally { busy = false; renderBanks(); renderBox(); }
}
async function importNativeSave() {
  const file = $('native-file').files?.[0], button = $('native-import'), label = $('native-import-status');
  if (!file || nativeBusy) { label.textContent = 'Escolha um arquivo primeiro.'; return; }
  if (!file.size || file.size > 64 * 1024 * 1024) { label.textContent = 'O arquivo deve ter entre 1 byte e 64 MiB.'; return; }
  let imported = false;
  nativeBusy = true; button.disabled = true; label.textContent = 'Lendo e validando a cópia…';
  try {
    const response = await fetch('/api/native-saves/import', {method: 'POST', headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name)}, body: file});
    const result = await response.json(); if (!response.ok) throw Error(result.error || 'Não foi possível importar o arquivo.');
    nativeHash = result.sha256; label.textContent = result.state === 'supported'
      ? `${result.game} validado · ${result.summary?.pokemonCount ?? result.pokemonCount ?? 0} Pokémon · original preservado.`
      : `Cópia preservada como não suportada: ${result.reason || 'formato não reconhecido'}`;
    imported = true;
  } catch (error) { label.textContent = error.message; }
  finally {
    nativeBusy = false; button.disabled = false;
    if (imported) await refreshNative();
  }
}
async function refresh(manual = false) {
  try {
    state = await api('/api/state'); const address = state.ips?.join(' / ') || 'consulte a rede do PC'; $('connection').textContent = 'IP ' + address + ' · PIN ' + state.pin + ' · TCP ' + state.port; $('connection-short').textContent = state.ips?.length ? 'PIN ' + state.pin + ' · porta ' + state.port : 'Servidor local'; renderHotspot();
    if (current) { const updated = state.items.find(item => item.id === current.id); if (updated) current = updated; else { current = null; boxData = null; masks = []; } }
    renderBanks(); renderBox();
    if (!current && state.items.length) await selectBank(state.items[0]);
    if (currentView === 'dex') await refreshDex();
    if (manual) status('Lista atualizada.');
  } catch (error) { status(error.message, true); }
}
async function selectBank(item, force = false) {
  if (busy && !force) return; epoch++; current = item; boxIndex = 0; cursor = 0; masks = Array(item.offer.boxes).fill(0); boxData = null; $('box-select').replaceChildren();
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
$('nav-boxes').onclick = () => setMainView('boxes'); $('nav-dex').onclick = () => setMainView('dex'); $('nav-native').onclick = () => setMainView('native');
$('native-import').onclick = importNativeSave;
$('native-snapshot-select').onchange = () => { nativeHash = $('native-snapshot-select').value; nativeEpoch++; refreshNative(); };
document.querySelectorAll('[data-native-tab]').forEach(button => button.onclick = async () => { nativeTab = button.dataset.nativeTab; await renderNativePanel(); });
document.querySelectorAll('[data-filter]').forEach(button => button.onclick = () => { filter = Number(button.dataset.filter); document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button))); renderBanks(); });
$('clear').onclick = () => { masks.fill(0); renderBox(); }; $('to-ds').onclick = () => askSend(1); $('to-3ds').onclick = () => askSend(2); $('cancel-send').onclick = () => $('confirm').close(); $('confirm-send').onclick = send; $('credits').onclick = () => $('credits-dialog').showModal(); $('close-credits').onclick = () => $('credits-dialog').close();
$('sort-box').onclick = () => organize('sort'); $('compact-box').onclick = () => organize('compact'); $('living-dex').onclick = () => organize('living-dex');
renderBox(); refresh(); loadDexData(); setInterval(() => { if (!busy && currentView !== 'native') refresh(); }, 5000);
})();
