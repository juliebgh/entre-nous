'use strict';

const $ = s => document.querySelector(s);
const el = $('#main'),
  sheet = $('#sheet'),
  net = $('#network');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[c]);
const cat = {
  decouverte: 'Découverte',
  profondeur: 'Profondeur',
  seduction: 'Séduction',
  sans_filtre: 'Sans filtre · 18+'
};
const levels = {
  leger: 'Léger',
  audacieux: 'Audacieux',
  intense: 'Intense'
};
const modes = {
  miroir: 'Miroir',
  dans_ta_tete: 'Dans ta tête'
};
let state = null,
  screen = 'home',
  choice = null,
  fingerprint = '',
  syncAt = 0,
  serverAt = 0,
  toastTimer,
  draft = null,
  resumeRequired = true,
  pending = false,
  queue = Promise.resolve(),
  pollQueued = false;
const invite = new URLSearchParams(location.search).get('salon') || '';
const button = (id, title, style = '') => '<button id="' + id + '" class="btn ' + style + '">' + title + '</button>';
const wrap = (label, title, content) => '<section class="board"><p class="kicker">' + label + '</p><h1>' + title + '</h1>' + content + '</section>';
function notify(message) {
  $('#toast').textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').textContent = '', 3800);
}
function modal(title, body) {
  $('#modaltitle').textContent = title;
  $('#modalbody').innerHTML = body;
  sheet.showModal();
}
$('#close').onclick = () => sheet.close();
$('#prefs').onclick = () => {
  modal('Paramètres', '<label class="check"><input id="motion" type="checkbox">Réduire les animations</label><p class="hint">Le réglage d’accessibilité de ton appareil est également respecté.</p>');
  $('#motion').checked = document.documentElement.classList.contains('still');
  $('#motion').onchange = e => {
    document.documentElement.classList.toggle('still', e.target.checked);
    try {
      localStorage.setItem('en-motion', e.target.checked ? 'off' : 'on');
    } catch {}
  };
};
try {
  document.documentElement.classList.toggle('still', localStorage.getItem('en-motion') === 'off');
} catch {}
function help() {
  modal('Comment jouer', '<ol><li>Crée un salon et partage le lien avec ton partenaire. Chacun joue sur son appareil.</li><li>En <strong>Miroir</strong>, réponds pour toi, puis devine son choix. Dans <strong>Dans ta tête</strong>, commence par ta prédiction.</li><li>Validez chacun votre choix avant la fin du temps. Tu peux passer librement.</li><li>Les deux écrans révèlent ensemble les choix. Chaque prédiction exacte rapporte deux points.</li></ol><p>Les défis sont facultatifs. Chacun peut les refuser. L’univers Sans filtre exige deux accords explicites.</p>');
}
function home() {
  screen = 'home';
  el.innerHTML = '<section class="hero"><div><p class="kicker">Jeu de cartes à deux</p><h1>Entre <em>Nous</em></h1><p class="lead">Une question, deux regards. Réponds pour toi, puis découvre à quel point tu sais lire l’autre.</p><div class="actions">' + button('create', 'Créer une partie', 'primary') + button('join', 'Rejoindre') + '</div><button id="help" class="textbtn">Comment jouer</button></div><div class="art" aria-hidden="true"><div class="backcard behind"><div class="orb">✧</div></div><div class="backcard front"><span class="corner">✧</span><div class="orb">✧</div><span class="corner end">✧</span></div></div></section>';
  $('#create').onclick = () => entry(false);
  $('#join').onclick = () => entry(true);
  $('#help').onclick = help;
}
function entry(join) {
  screen = join ? 'join' : 'create';
  el.innerHTML = wrap('Salon privé', join ? 'Rejoindre une partie' : 'Créer une partie', '<form class="panel stack" id="entry"><label class="field">Ton pseudonyme<input id="name" name="name" maxlength="24" autocomplete="off" required></label>' + (join ? '<label class="field">Code du salon<input id="code" name="code" value="' + esc(invite) + '" maxlength="12" autocapitalize="characters" spellcheck="false" autocomplete="off" required></label>' : '<p class="muted compact">Tu recevras un lien privé à partager avec la personne de ton choix.</p>') + button('enter', join ? 'Rejoindre le salon' : 'Créer le salon', 'primary') + '</form><button class="textbtn" id="back">Retour à l’accueil</button>');
  $('#back').onclick = home;
  $('#entry').onsubmit = e => {
    e.preventDefault();
    const name = $('#name').value.trim();
    if (!name) {
      notify('Choisis un pseudonyme.');
      return;
    }
    mutate(join ? 'join' : 'create', join ? {
      name,
      code: $('#code').value.trim().toUpperCase()
    } : {
      name
    });
  };
  $('#name').focus();
}
function schedule(fn) {
  const result = queue.then(fn, fn);
  queue = result.catch(() => {});
  return result;
}
async function api(path, body) {
  const opts = {
    credentials: 'same-origin',
    cache: 'no-store',
    signal: AbortSignal.timeout(9000)
  };
  if (body !== undefined) {
    opts.method = 'POST';
    opts.headers = {
      'Content-Type': 'application/json'
    };
    opts.body = JSON.stringify(body);
  }
  const begin = performance.now();
  const res = await fetch('/api/' + path, opts);
  const data = await res.json();
  if (!res.ok) {
    const error = new Error(data.error || 'La demande a échoué.');
    error.status = res.status;
    throw error;
  }
  syncAt = performance.now();
  serverAt = data.serverNow + (syncAt - begin) / 2000;
  net.hidden = true;
  return data;
}
function lost(e) {
  if (e.status === 401 || e.status === 404 || e.status === 410) {
    if (state) {
      state = null;
      draft = null;
      fingerprint = '';
      home();
      notify('Ce salon a expiré ou ta session est terminée.');
    }
    return;
  }
  net.hidden = false;
  net.textContent = 'Connexion interrompue. Reconnexion en cours… Le chronomètre du salon continue.';
}
function mutate(path, body) {
  if (pending) return;
  pending = true;
  const submit = $('#enter');
  if (submit) submit.disabled = true;
  schedule(async () => {
    try {
      const data = await api(path, body);
      if (path === 'create' || path === 'join') {
        history.replaceState(null, '', location.pathname);
        draft = null;
      }
      if (body.action === 'settings') draft = null;
      apply(data, true);
    } catch (e) {
      if (!e.status) lost(e);
      notify(e.status ? e.message : 'Impossible de joindre le salon. Réessaie lorsque la connexion revient.');
      if (state) {
        apply(state, true);
        await poll();
      }
    } finally {
      pending = false;
      if (submit) submit.disabled = false;
    }
  });
}
function act(action, extra = {}) {
  if (state) mutate('act', {
    action,
    turn: state.turn,
    ...extra
  });
}
async function poll() {
  try {
    apply(await api('state'));
  } catch (e) {
    lost(e);
  }
}
function apply(s, force = false) {
  const previous = state;
  state = s;
  screen = 'game';
  if (!previous || previous.turn !== s.turn) {
    choice = null;
    if (s.phase !== 'lobby') draft = null;
  }
  const digest = JSON.stringify([s.code, s.seat, s.players, s.phase, s.turn, s.round, s.settings, s.adult, s.locked, s.scores, s.history, s.challenge, s.replay, s.online]);
  if (!force && digest === fingerprint) {
    clock();
    return;
  }
  fingerprint = digest;
  if (s.phase === 'lobby') lobby();else if (s.phase === 'self' || s.phase === 'predict') play();else if (s.phase === 'reveal') reveal();else if (s.phase === 'challenge') challenge();else if (s.phase === 'final') finalPage();
  if (s.players.length === 2 && s.online && s.online[1 - s.seat] === false) {
    el.insertAdjacentHTML('afterbegin', '<p class="notice" role="status">' + esc(s.players[1 - s.seat]) + ' est hors ligne. Sa place est réservée. Le temps continue et les choix non validés expirent sans pénalité.</p>');
  }
  clock();
  if (previous && previous.phase !== s.phase) el.focus({
    preventScroll: true
  });
}
function selected(a, b) {
  return a === b ? ' selected' : '';
}
function checked(a) {
  return a ? ' checked' : '';
}
function lobby() {
  const s = state,
    host = s.seat === 0,
    cfg = draft || s.settings;
  let settings;
  if (host) {
    settings = '<form id="settingsForm" class="panel stack"><h2 class="compact">La partie</h2><label class="field">Mode de jeu<select id="mode">' + Object.entries(modes).map(([k, v]) => '<option value="' + k + '"' + selected(cfg.mode, k) + '>' + v + '</option>').join('') + '</select></label><div class="grid2"><label class="field">Temps par phase<select id="preset">' + [[15, 'Rapide · 15 s'], [30, 'Normal · 30 s'], [45, 'Réflexion · 45 s'], [0, 'Personnalisé']].map(([v, label]) => '<option value="' + v + '"' + selected([15, 30, 45].includes(cfg.duration) ? cfg.duration : 0, v) + '>' + label + '</option>').join('') + '</select></label><label class="field">Secondes<input id="duration" type="number" min="10" max="90" required value="' + esc(cfg.duration) + '"></label></div><label class="field">Nombre de manches<input type="number" id="rounds" min="1" max="20" required value="' + esc(cfg.rounds) + '"></label><fieldset><legend>Univers</legend>' + Object.entries(cat).map(([k, v]) => '<label class="check"><input type="checkbox" value="' + k + '" name="cat"' + checked(cfg.categories.includes(k)) + '>' + v + '</label>').join('') + '</fieldset><label class="check"><input id="challenges" type="checkbox"' + checked(cfg.challenges) + '>Proposer des défis entre les manches</label>' + button('saveSettings', 'Enregistrer les réglages') + '</form>';
  } else {
    settings = '<section class="panel"><h2>La partie</h2><p>' + esc(modes[cfg.mode]) + ' · ' + esc(cfg.rounds) + ' manche(s) · ' + esc(cfg.duration) + ' s par phase</p><p>' + cfg.categories.map(k => esc(cat[k])).join(' · ') + '</p><p class="hint compact">Défis ' + (cfg.challenges ? 'activés' : 'désactivés') + '</p></section>';
  }
  const adults = s.adult.filter(Boolean).length;
  el.innerHTML = wrap('Salon privé', 'Salle d’attente', '<section class="panel"><p class="kicker">Code d’invitation</p><div class="row"><strong class="code">' + esc(s.code) + '</strong>' + button('share', 'Inviter') + '</div><p class="hint compact">' + s.players.map(esc).join(' et ') + ' · ' + s.players.length + '/2</p></section>' + settings + '<section class="panel"><h2>Sans filtre · 18+</h2><label class="check"><input id="adult" type="checkbox"' + checked(s.adult[s.seat]) + '>Je confirme avoir 18 ans ou plus et j’accepte cet univers.</label><p class="hint compact">' + adults + '/2 accord(s). Les deux joueurs doivent accepter pour inclure ces cartes.</p></section>' + (host ? button('start', 'Lancer la partie', 'primary') : '<p role="status">En attente du lancement par ' + esc(s.players[0]) + '.</p>'));
  $('#share').onclick = share;
  $('#adult').onchange = e => act('adult', {
    value: e.target.checked
  });
  if (!host) return;
  const read = () => ({
    mode: $('#mode').value,
    duration: Number($('#duration').value),
    rounds: Number($('#rounds').value),
    categories: Array.from(document.querySelectorAll('[name=cat]:checked'), c => c.value),
    challenges: $('#challenges').checked
  });
  const update = () => {
    draft = read();
    $('#start').disabled = s.players.length < 2 || JSON.stringify(draft.categories) !== JSON.stringify(s.settings.categories) || Object.keys(draft).filter(k => k !== 'categories').some(k => draft[k] !== s.settings[k]);
    $('#saveSettings').textContent = 'Enregistrer les réglages';
  };
  $('#settingsForm').oninput = update;
  $('#preset').onchange = e => {
    if (Number(e.target.value)) $('#duration').value = e.target.value;else $('#duration').focus();
    update();
  };
  $('#duration').oninput = () => {
    $('#preset').value = [15, 30, 45].includes(Number($('#duration').value)) ? $('#duration').value : '0';
  };
  $('#settingsForm').onsubmit = e => {
    e.preventDefault();
    const settings = read();
    if (!settings.categories.length) {
      notify('Choisis au moins un univers.');
      return;
    }
    act('settings', {
      settings
    });
  };
  $('#start').disabled = s.players.length < 2 || !!draft;
  $('#start').onclick = () => act('start');
}
async function share() {
  const url = new URL('/', location.origin);
  url.searchParams.set('salon', state.code);
  try {
    if (navigator.share) await navigator.share({
      title: 'Entre Nous',
      url: url.href
    });else {
      await navigator.clipboard.writeText(url.href);
      notify('Lien d’invitation copié.');
    }
  } catch (e) {
    if (e.name !== 'AbortError') modal('Inviter', '<label class="field">Lien à partager<input readonly value="' + esc(url.href) + '"></label>');
  }
}
function other() {
  return 1 - state.seat;
}
function bar() {
  return '<div class="bar"><span>Manche ' + esc(state.round) + ' sur ' + esc(state.settings.rounds) + '</span><span id="clock" class="clock"></span></div><div class="timer" aria-hidden="true"><span id="progress"></span></div>';
}
function clock() {
  if (!state || !$('#clock')) return;
  const seconds = state.deadline == null ? null : Math.max(0, state.deadline - serverAt - (performance.now() - syncAt) / 1000);
  $('#clock').textContent = seconds === null ? '' : Math.ceil(seconds) + ' s';
  $('#progress').style.width = (seconds === null ? 0 : Math.min(100, seconds / (state.phase === 'reveal' ? 18 : state.phase === 'challenge' ? state.challenge.text ? 60 : 30 : state.settings.duration) * 100)) + '%';
}
function scores() {
  return '<section class="panel"><h2>Scores</h2>' + state.players.map((p, i) => '<div class="scoreline"><span>' + esc(p) + (i === state.seat ? ' · toi' : '') + '</span><strong class="points">' + esc(state.scores[i]) + ' pt' + (state.scores[i] > 1 ? 's' : '') + '</strong></div>').join('') + '</section>';
}
function play() {
  const s = state,
    c = s.card,
    predict = s.phase === 'predict',
    locked = s.locked[s.seat];
  const caption = predict ? 'Ta prédiction' : 'Ta réponse personnelle',
    target = predict ? 'Quel choix fera ' + esc(s.players[other()]) + ' ?' : 'Que choisirais-tu ?';
  el.innerHTML = wrap(esc(modes[s.settings.mode]), caption, bar() + '<article class="playingcard"><p class="kicker">' + esc(cat[c.category]) + '</p><h2>' + esc(c.question) + '</h2>' + (locked ? '<p role="status" class="selection">✓ ' + (predict ? 'Prédiction verrouillée' : 'Réponse verrouillée') + '</p><p class="muted compact">La manche reprend ensemble dès la seconde validation ou à la fin du temps.</p>' : '<p>' + target + '</p><div class="stack">' + c.choices.map((a, i) => '<button class="choice" data-choice="' + i + '" aria-pressed="' + (choice === i) + '">' + esc(a) + '</button>').join('') + '</div>') + '</article>' + (locked ? '' : '<div class="actions">' + button('lock', 'Valider mon choix', 'primary') + button('pass', 'Passer', 'ghost') + '</div>'));
  if (locked) return;
  $('#lock').disabled = choice === null;
  document.querySelectorAll('[data-choice]').forEach(b => b.onclick = () => {
    choice = Number(b.dataset.choice);
    document.querySelectorAll('[data-choice]').forEach(a => a.setAttribute('aria-pressed', String(a === b)));
    $('#lock').disabled = false;
  });
  $('#lock').onclick = () => {
    if (choice !== null) act('answer', {
      choice
    });
  };
  $('#pass').onclick = () => act('answer', {
    choice: null
  });
}
function lineResult(r, i) {
  const c = r.card,
    answer = r.answers[i],
    guess = r.predictions[i],
    pts = r.points[i];
  return '<div><h3>' + esc(state.players[i]) + '</h3><p class="compact">Réponse personnelle · <strong>' + esc(answer == null ? 'Passée' : c.choices[answer]) + '</strong></p><p class="compact">Prédiction pour ' + esc(state.players[1 - i]) + ' · ' + esc(guess == null ? 'Passée' : c.choices[guess]) + '</p><p class="points scorepop">+' + esc(pts) + ' point' + (pts > 1 ? 's' : '') + '</p></div>';
}
function historyBlock() {
  return state.history.length ? '<details class="panel"><summary>Historique des manches (' + state.history.length + ')</summary>' + state.history.map(r => '<details><summary>' + esc(r.round) + ' · ' + esc(r.card.question) + '</summary>' + state.players.map((_, i) => lineResult(r, i)).join('') + '</details>').join('') + '</details>' : '';
}
function reveal() {
  const s = state,
    r = s.history[s.history.length - 1];
  el.innerHTML = wrap('Révélation', 'Vos deux regards', bar() + '<article class="playingcard reveal"><p class="kicker">' + esc(cat[r.card.category]) + '</p><h2>' + esc(r.card.question) + '</h2>' + s.players.map((_, i) => lineResult(r, i)).join('') + '</article>' + scores() + (s.seat === 0 ? '<label class="check"><input id="bonus" type="checkbox"' + checked(s.settings.challenges) + '>Activer les défis</label>' : '') + button('next', s.locked[s.seat] ? 'En attente de l’autre…' : 'Continuer', 'primary') + historyBlock());
  $('#next').disabled = s.locked[s.seat];
  $('#next').onclick = () => act('next');
  if ($('#bonus')) $('#bonus').onchange = e => act('bonus', {
    value: e.target.checked
  });
}
function challenge() {
  const s = state,
    c = s.challenge;
  const detail = c.text ? '<h2>' + esc(c.text) + '</h2><p class="hint">Tu peux refuser ou remplacer cette proposition à tout moment.</p><div class="actions">' + button('next', s.locked[s.seat] ? 'En attente de l’autre…' : 'Terminé', 'primary') + button('replace', 'Remplacer') + '</div>' : '<h2>Quel niveau vous tente ?</h2><p>Suggestion selon vos scores · <strong>' + esc(levels[c.recommended]) + '</strong></p><div class="stack">' + Object.entries(levels).map(([k, v]) => '<button class="choice" data-level="' + k + '" aria-pressed="' + (c.levelVotes[s.seat] === k) + '">' + v + '</button>').join('') + '</div><p class="hint">Choix de ' + esc(s.players[other()]) + ' · ' + esc(levels[c.levelVotes[other()]] || 'en attente') + '. Le défi apparaît quand vous avez choisi le même niveau.</p>';
  el.innerHTML = wrap('Bonus', 'Défi à deux', bar() + '<article class="playingcard">' + detail + '</article>' + button('decline', 'Passer le défi', 'ghost'));
  document.querySelectorAll('[data-level]').forEach(b => b.onclick = () => act('level', {
    value: b.dataset.level
  }));
  $('#decline').onclick = () => act('decline');
  if ($('#next')) {
    $('#next').disabled = s.locked[s.seat];
    $('#next').onclick = () => act('next');
  }
  if ($('#replace')) $('#replace').onclick = () => act('replace');
}
function finalPage() {
  const s = state,
    tied = s.scores[0] === s.scores[1],
    leader = s.players[s.scores[0] > s.scores[1] ? 0 : 1];
  el.innerHTML = wrap('Fin de partie', 'Ce que vous avez deviné', '<article class="playingcard reveal"><p class="kicker">' + s.history.length + ' manche(s) jouée(s)</p><h2>' + (tied ? 'Vous terminez à égalité.' : esc(leader) + ' remporte la partie.') + '</h2>' + s.players.map((p, i) => '<div class="scoreline"><div><strong>' + esc(p) + '</strong><br><small>' + s.stats[i].correct + ' / ' + s.stats[i].attempts + ' prédictions exactes · ' + (s.stats[i].rate == null ? 'aucun taux' : esc(s.stats[i].rate) + ' %') + '</small></div><strong class="points">' + s.scores[i] + ' pts</strong></div>').join('') + '</article>' + button('replay', s.replay[s.seat] ? 'En attente de l’autre…' : 'Rejouer ensemble', 'primary') + ' <button class="textbtn" id="newRoom">Changer de salon</button>' + historyBlock());
  $('#replay').disabled = s.replay[s.seat];
  $('#replay').onclick = () => act('replay');
  $('#newRoom').onclick = () => switchSalon(false);
}
function switchSalon(join) {
  state = null;
  choice = null;
  draft = null;
  fingerprint = '';
  resumeRequired = false;
  if (join) entry(true);else home();
}
async function restoreSession() {
  try {
    const data = await api('state');
    resumeRequired = false;
    apply(data, true);
    if (invite && data.code !== invite.toUpperCase() && !sheet.open) {
      modal('Un autre salon est déjà ouvert', '<p>Tu as reçu une invitation pour le salon <strong>' + esc(invite) + '</strong>. Rejoindre ce salon remplacera ton accès au salon actuel sur cet appareil.</p><div class="actions">' + button('keep', 'Rester ici') + button('change', 'Ouvrir l’invitation', 'primary') + '</div>');
      $('#keep').onclick = () => {
        sheet.close();
        history.replaceState(null, '', location.pathname);
      };
      $('#change').onclick = () => {
        sheet.close();
        switchSalon(true);
      };
    }
  } catch (e) {
    if ([401, 404, 410].includes(e.status)) {
      resumeRequired = false;
      if (invite) entry(true);else home();
    } else lost(e);
  }
}
async function init() {
  el.innerHTML = wrap('Entre Nous', 'Ouverture du jeu', '<p role="status">Recherche de ton salon…</p>');
  await schedule(restoreSession);
  const refresh = () => {
    if (!state && !resumeRequired || document.hidden || pollQueued) return;
    pollQueued = true;
    schedule(() => resumeRequired ? restoreSession() : poll()).finally(() => pollQueued = false);
  };
  setInterval(refresh, 700);
  document.addEventListener('visibilitychange', refresh);
  window.addEventListener('online', () => {
    net.hidden = true;
    refresh();
  });
  window.addEventListener('offline', () => lost(new Error()));
  setInterval(clock, 150);
}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
init();
