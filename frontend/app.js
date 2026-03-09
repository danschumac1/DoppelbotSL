const $ = (s)=>document.querySelector(s);
const logEl = $('#log');
const statusEl = $('#status');
const roomLabel = $('#roomLabel');
const overlay = $('#overlay');
const voteOverlay = $('#voteOverlay');
const voteListEl = $('#voteList');
const voteTimerEl = $('#voteTimer');
const chatTimerEl = $('#chatTimer');

let ws = null;
let connected=false;
let currentRoom = '';
let currentPlayerId = '';
let currentUsername = '';
let isHost = false;
let chatTimerInterval = null;
let registrationData = null; // { displayName, participantId, age }

const SESSION_KEY = 'doppelbot_session';

function saveSession() {
  if (!currentRoom || !currentPlayerId) return;
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    roomId: currentRoom,
    playerId: currentPlayerId,
    username: currentUsername,
    isHost,
    registrationData,
  }));
}

function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

$('#closeVoteOverlay')?.addEventListener('click', () => {
  if (voteOverlay) voteOverlay.style.display = 'none';
  stopVoteCountdown();
});

// game UI state (from server)
let roomSnapshot = null; // last snapshot

// --- Registration ---
function showRegistration() {
  document.getElementById('registrationOverlay').style.display = 'grid';
  document.getElementById('regName').focus();
}

function submitRegistration() {
  const name = document.getElementById('regName').value.trim();
  const participantId = document.getElementById('regParticipantId').value.trim();
  const age = parseInt(document.getElementById('regAge').value, 10);
  const consent = document.getElementById('regConsent').checked;
  const errEl = document.getElementById('regError');

  errEl.style.display = 'none';
  errEl.textContent = '';

  if (!name) {
    errEl.textContent = 'Display name is required.';
    errEl.style.display = 'block';
    document.getElementById('regName').focus();
    return;
  }
  if (!age || isNaN(age) || age < 1) {
    errEl.textContent = 'Please enter your age.';
    errEl.style.display = 'block';
    document.getElementById('regAge').focus();
    return;
  }
  if (!consent) {
    errEl.textContent = 'You must consent to participate before continuing.';
    errEl.style.display = 'block';
    return;
  }

  registrationData = { displayName: name, participantId, age };
  document.getElementById('registrationOverlay').style.display = 'none';
  overlay.style.display = 'grid';
  loadRooms();
}

document.getElementById('btnRegister').addEventListener('click', submitRegistration);
document.getElementById('regName').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitRegistration();
});

function setStatus(ok){
  connected=ok;
  statusEl.innerHTML = ok
    ? '<span class="dot"></span> connected'
    : '<span class="dot red"></span> disconnected';
}

function escapeHtml(s){
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}


function renderVoteList(){
  if (!voteListEl) return;
  voteListEl.innerHTML = '';

  if (!roomSnapshot?.players) return;

  // Check if current player is eliminated
  const me = roomSnapshot.players.find(p => p.playerId === currentPlayerId);
  const isEliminated = !!me?.eliminated;

  // If you're eliminated, you shouldn't even be voting
  if (isEliminated) {
    const row = document.createElement('div');
    row.className = 'room-item';
    row.innerHTML = `
      <div>
        <div class="room-id monospace">Spectating</div>
        <div class="room-meta">You are eliminated and cannot vote.</div>
      </div>
    `;
    voteListEl.appendChild(row);
    return;
  }

  // Build list of eligible vote targets
  const targets = roomSnapshot.players.filter(p =>
    !p.eliminated &&                // cannot vote for eliminated players
    p.playerId !== currentPlayerId  // cannot vote for yourself
  );

  if (targets.length === 0) {
    const row = document.createElement('div');
    row.className = 'room-item';
    row.innerHTML = `
      <div>
        <div class="room-id monospace">No valid targets</div>
        <div class="room-meta">Waiting for next phase...</div>
      </div>
    `;
    voteListEl.appendChild(row);
    return;
  }

  targets.forEach(p => {
    const row = document.createElement('div');
    row.className = 'room-item';

    row.innerHTML = `
      <div>
        <div class="room-id monospace">${escapeHtml(p.username)} ${p.isHost ? '👑' : ''}</div>
        <div class="room-meta">${p.connected ? 'online' : 'disconnected'}</div>
      </div>
      <button class="btn primary">Vote</button>
    `;

    const btn = row.querySelector('button');
    btn.addEventListener('click', () => {
      castVote(p.playerId);
      btn.disabled = true;
      btn.textContent = "Voted";
      voteOverlay.style.display = 'none';
      stopVoteCountdown();
    });

    voteListEl.appendChild(row);
  });
}



let voteTimerInterval = null;

function startVoteCountdown(voteEndsAt){
  stopVoteCountdown();
  const label = voteTimerEl;
  if (!label) return;

  function tick(){
    if (!voteEndsAt) { label.textContent = ''; return; }
    const now = Math.floor(Date.now()/1000);
    const left = Math.max(0, voteEndsAt - now);
    const m = Math.floor(left/60);
    const s = left % 60;
    label.textContent = `Time left: ${m}:${String(s).padStart(2,'0')}`;

    if (left <= 0) {
      // backend will resolve; we just show waiting
      label.textContent = 'Time left: 0:00';
    }
  }

  tick();
  voteTimerInterval = setInterval(tick, 250);
}

function stopVoteCountdown(){
  if (voteTimerInterval) clearInterval(voteTimerInterval);
  voteTimerInterval = null;
}


function startChatCountdown(chatEndsAt){
  stopChatCountdown();
  if (!chatTimerEl) return;

  function tick(){
    if (!chatEndsAt) { chatTimerEl.textContent = ''; return; }
    const now = Math.floor(Date.now()/1000);
    const left = Math.max(0, chatEndsAt - now);
    const m = Math.floor(left/60);
    const s = left % 60;
    chatTimerEl.textContent = `Chat: ${m}:${String(s).padStart(2,'0')}`;
    if (left <= 0) chatTimerEl.textContent = `Chat: 0:00`;
  }

  tick();
  chatTimerInterval = setInterval(tick, 250);
}

function stopChatCountdown(){
  if (chatTimerInterval) clearInterval(chatTimerInterval);
  chatTimerInterval = null;
}




// Message rendering
function appendMsg(kind, name, text){
  const wrap=document.createElement('div'); wrap.className=`msg ${kind}`;
  const showName = (kind === 'ai' || kind === 'system') ? name : ''; // show other user/system labels
  wrap.innerHTML =
    `<div class="avatar">${kind==='you'?'You':(kind==='system'?'SYS':'AI')}</div>
     <div class="bubble">
       ${showName ? `<div class="meta">${escapeHtml(showName)}</div>` : ''}
       <div>${escapeHtml(text)}</div>
     </div>`;
  logEl.appendChild(wrap);
  logEl.scrollTop=logEl.scrollHeight;
}

// --- Minimal "Game Controls" injected into existing UI ---
function ensureControls(){
  if ($('#gameControls')) return;

  const head = document.querySelector('.chat-wrap .head');
  const ctrls = document.createElement('div');
  ctrls.id = 'gameControls';
  ctrls.className = 'actions';
  ctrls.style.gap = '8px';
  ctrls.style.marginLeft = '10px';

  ctrls.innerHTML = `
    <button class="btn primary" id="btnStartGame" title="Host only">Start</button>
    <button class="btn" id="btnEndChat" title="Host only">End Chat</button>
    <span id="phaseBadge" class="monospace" style="opacity:.8"></span>
  `;

  head.appendChild(ctrls);

  $('#btnStartGame').addEventListener('click', startGame);
  $('#btnEndChat').addEventListener('click', endChat);
}

function updateControlsFromSnapshot(){
  ensureControls();
  if (!roomSnapshot) return;

  const phase = roomSnapshot.phase;
  const round = roomSnapshot.round;
  $('#phaseBadge').textContent = phase ? `${phase}${round ? ` R${round}` : ''}` : '';

  // enable/disable buttons based on state
  $('#btnStartGame').disabled = !(isHost && phase === 'LOBBY');
  $('#btnEndChat').disabled = !(isHost && phase === 'CHAT');
}

// --- REST helpers ---
async function joinRoomFlow(roomId) {
  const room = String(roomId || '').trim().toUpperCase();
  if (!room) return;

  const res = await fetch(`/api/rooms/${encodeURIComponent(room)}/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      displayName: registrationData?.displayName || '',
      participantId: registrationData?.participantId || '',
      age: registrationData?.age || 0,
    })
  });

  if (!res.ok) {
    alert(`Failed to join room: ${res.status}`);
    return;
  }

  const data = await res.json();
  currentRoom = data.roomId;
  currentPlayerId = data.playerId;
  currentUsername = data.username;
  isHost = !!data.isHost;
  roomSnapshot = data.snapshot || null;

  saveSession();

  // UI
  roomLabel.textContent = currentRoom;
  overlay.style.display = 'none';
  logEl.innerHTML = '';

  appendMsg('system', 'System', `Joined as ${currentUsername}${isHost ? ' (host)' : ''}.`);

  connectWebSocket(currentRoom, currentPlayerId);
}

async function startGame(){
  if (!currentRoom || !currentPlayerId) return;
  const res = await fetch(`/api/rooms/${encodeURIComponent(currentRoom)}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ playerId: currentPlayerId })
  });

  if (!res.ok) {
    const txt = await res.text().catch(()=> '');
    alert(`Start failed: ${res.status}\n${txt}`);
    return;
  }
  appendMsg('system', 'System', 'Game started.');
}

function wsUrl(path) {
  const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
  return `${proto}://${location.host}${path}`;
}

function connectWebSocket(room, playerId) {
  if (ws) { try { ws.close(); } catch {} ws = null; }

  setStatus(false);
  ws = new WebSocket(wsUrl(`/ws/${encodeURIComponent(room)}/${encodeURIComponent(playerId)}`));

  ws.onopen = () => {
    setStatus(true);
    ensureControls();
    updateControlsFromSnapshot();
  };

  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); }
    catch { msg = { type: 'raw', data: ev.data }; }

    handleServerEvent(msg);
  };

  ws.onclose = () => {
    setStatus(false);
    appendMsg('system', 'System', 'Disconnected.');
  };

  ws.onerror = () => {
    setStatus(false);
  };
}

// --- Server event handler (new protocol) ---
function handleServerEvent(msg){
  const t = msg.type;

  if (t === 'error') {
    appendMsg('system', 'Error', msg.text || 'Unknown error');
    return;
  }

  if (t === 'room_snapshot') {
    roomSnapshot = msg.data || null;
    updateControlsFromSnapshot();

    // Also show a small roster in chat for now
    if (roomSnapshot?.players) {
      const roster = roomSnapshot.players
        .map(p => `${p.isHost ? '👑 ' : ''}${p.username}${p.connected ? '' : ' (dc)'}`)
        .join(', ');
      appendMsg('system', 'Room', `Players: ${roster}`);
    }
    applyPhaseUI();
    return;
  }

  if (t === 'phase_changed') {
    const ph = msg.data?.phase;
    const rd = msg.data?.round;
    appendMsg('system', 'Phase', `${ph}${rd ? ` — Round ${rd}` : ''}`);
    // snapshot usually follows, but update badge anyway
    if (roomSnapshot) {
      roomSnapshot.phase = ph;
      roomSnapshot.round = rd;
    }
    updateControlsFromSnapshot();
    applyPhaseUI();
    return;
  }

  if (t === 'elimination') {
  const d = msg.data || {};
  appendMsg('system', 'Elimination', `${d.eliminatedUsername || 'A player'} was eliminated.`);
  return;
}


  if (t === 'history' && Array.isArray(msg.messages)) {
    msg.messages.forEach(m => {
      const kind = (m.user === currentUsername) ? 'you' : 'ai';
      appendMsg(kind, m.user, m.text);
    });
    return;
  }

  if (t === 'system') {
    appendMsg('system', 'System', msg.text || '');
    return;
  }

  if (t === 'chat_message') {
    const d = msg.data || {};
    const name = d.user || '???';
    const kind = (name === currentUsername) ? 'you' : 'ai';
    appendMsg(kind, name, d.text || '');
    return;
  }

  if (t === 'vote_progress') {
    const d = msg.data || {};
    appendMsg('system', 'Vote', `Votes: ${d.submitted}/${d.total} (Round ${d.round})`);
    return;
  }

  if (t === 'game_over') {
    showScoreScreen(msg.data || {});
    return;
  }

  // legacy fallback
  if (t === 'chat') {
    const kind = (msg.user === currentUsername) ? 'you' : 'ai';
    appendMsg(kind, msg.user, msg.text || '');
    return;
  }
}


function applyPhaseUI(){
  if (!roomSnapshot) return;

  // lock input if eliminated
  const me = roomSnapshot.players?.find(p => p.playerId === currentPlayerId);
  const eliminated = !!me?.eliminated;

  // vote overlay
  if (roomSnapshot.phase === 'VOTE' && !eliminated) {
    if (voteOverlay) voteOverlay.style.display = 'grid';
    renderVoteList();
    startVoteCountdown(roomSnapshot.voteEndsAt);
  } else {
    if (voteOverlay) voteOverlay.style.display = 'none';
    stopVoteCountdown();
  }

  // chat timer
  if (roomSnapshot.phase === 'CHAT') {
    startChatCountdown(roomSnapshot.chatEndsAt);
  } else {
    stopChatCountdown();
    if (chatTimerEl) chatTimerEl.textContent = '';
  }

  // disable chat controls if eliminated
  const input = $('#input');
  const sendBtn = $('#send');

  if (input) input.disabled = eliminated;
  if (sendBtn) sendBtn.disabled = eliminated;

  if (input) {
    input.placeholder = eliminated
      ? 'Eliminated — spectating only'
      : 'Type a message… (Enter to send)';
  }
}




// --- Actions (send chat, end chat, vote) ---
function send(){
  const val=$('#input').value.trim();
  if(!val) return;
  $('#input').value='';

  if (!ws || ws.readyState !== 1) {
    appendMsg('system', 'System', 'Not connected. Join a room first.');
    return;
  }

  ws.send(JSON.stringify({ type: 'send_chat', data: { text: val } }));
}

function endChat(){
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'end_chat' }));
}

function openVoteOverlay(){
  document.getElementById('voteOverlay').style.display = 'grid';
  renderVoteList();
  startVoteCountdown(roomSnapshot?.voteEndsAt);
}


function castVote(targetPlayerId){
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'cast_vote', data: { targetPlayerId } }));
  appendMsg('system', 'Vote', `You voted for ${targetPlayerId.slice(0,8)}…`);
}

$('#send').addEventListener('click',send);
$('#input').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();send();}});
$('#clear').addEventListener('click',()=>{logEl.innerHTML='';});

$('#disconnect').addEventListener('click',()=>{
  if(ws){try{ws.close();}catch(_){}} ws=null;
  setStatus(false);
  appendMsg('system','System','You have disconnected.');
  currentRoom=''; roomLabel.textContent='—';
  currentPlayerId=''; currentUsername=''; isHost=false;
  roomSnapshot=null;
  clearSession();
  overlay.style.display='grid';
  loadRooms();
});

$('#openRoomSelect').addEventListener('click',()=>{overlay.style.display='grid';loadRooms();});
$('#closeOverlay').addEventListener('click',()=>{overlay.style.display='none';});
$('#refreshRooms').addEventListener('click',loadRooms);

$('#hamburger').addEventListener('click', openSidebar);
$('#closeSidebar').addEventListener('click', closeSidebar);
$('#backdrop').addEventListener('click', closeSidebar);

$('#navRules').addEventListener('click', () => { closeSidebar(); showScreen('screenRules'); });
$('#navAbout').addEventListener('click', () => { closeSidebar(); showScreen('screenAbout'); });
$('#navPlay').addEventListener('click', () => { closeSidebar(); goPlay(); });

$('#btnPlayFromRules').addEventListener('click', goPlay);
$('#btnOpenMenu').addEventListener('click', openSidebar);

$('#createRoom').addEventListener('click', async () =>{
  let id = $('#newRoomId').value.trim().toUpperCase();
  if (!id) id = Math.random().toString(36).slice(2, 8).toUpperCase();

  const res = await fetch('/api/rooms',{
    method: 'POST',
    headers: { 'Content-Type': 'application/json'},
    body: JSON.stringify({id})
  });

  if(!res.ok){
    alert(`Failed to create room: ${res.status}`);
    return;
  }

  await joinRoomFlow(id);
});

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-join]');
  if (!btn) return;
  const roomId = btn.getAttribute('data-join');
  await joinRoomFlow(roomId);
});

async function loadRooms() {
  const list = document.getElementById('roomList');
  list.innerHTML = '';

  const loading = document.createElement('div');
  loading.className = 'room-item';
  loading.innerHTML = '<div><div class="room-id monospace">Loading...</div></div>';
  list.appendChild(loading);

  try{
    const res = await fetch('/api/rooms', { method: 'GET' });
    if (!res.ok) throw new Error(`GET /api/rooms failed: ${res.status}`);

    const rooms = await res.json();
    list.innerHTML = '';

    if(!Array.isArray(rooms) || rooms.length === 0){
      const empty = document.createElement('div');
      empty.className = 'room-item';
      empty.innerHTML = `
        <div>
          <div class="room-id monospace">No rooms yet</div>
          <div class="room-meta">Create one on the right</div>
        </div>
      `;
      list.appendChild(empty);
      return;
    }

    rooms.forEach(r => {
      const id = String(r.id || '').toUpperCase();
      const users = Number(r.users ?? 0);
      const last = Number(r.lastActivity ?? 0);

      const row = document.createElement('div');
      row.className = 'room-item';
      row.innerHTML = `
        <div>
          <div class="room-id monospace">${escapeHtml(id)}</div>
          <div class="room-meta">${users} players • active ${formatAge(last)} ago</div>
        </div>
        <button class="btn primary" data-join="${escapeHtml(id)}">Join</button>
      `;
      list.appendChild(row);
    });

  } catch(err){
    list.innerHTML = '';
    const bad = document.createElement('div');
    bad.className = 'room-item';
    bad.innerHTML = `
      <div>
        <div class="room-id monospace">Error loading rooms</div>
        <div class="room-meta">${escapeHtml(String(err.message || err))}</div>
      </div>
      <button class="btn" id="retryRooms">Retry</button>
    `;
    list.appendChild(bad);

    $('#retryRooms')?.addEventListener('click', loadRooms);
  }
}

function formatAge(seconds) {
  if(!isFinite(seconds) || seconds < 0) return '0s';
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

function showScreen(id){
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function openSidebar(){
  $('#sidebar').classList.add('open');
  $('#backdrop').classList.add('show');
  $('#sidebar').setAttribute('aria-hidden', 'false');
  $('#backdrop').setAttribute('aria-hidden', 'false');
}
function closeSidebar(){
  $('#sidebar').classList.remove('open');
  $('#backdrop').classList.remove('show');
  $('#sidebar').setAttribute('aria-hidden', 'true');
  $('#backdrop').setAttribute('aria-hidden', 'true');
}

function goPlay(){
  showScreen('screenApp');
  overlay.style.display = 'grid';
  loadRooms();
}

// --- Score Screen ---
function showScoreScreen(data) {
  const aiWon = !!data.aiWon;
  const aiUsernames = Array.isArray(data.aiUsernames) ? data.aiUsernames : (data.aiUsername ? [data.aiUsername] : []);
  const remaining = Array.isArray(data.remaining) ? data.remaining : [];
  const eliminated = Array.isArray(data.eliminated) ? data.eliminated : [];

  // Winner banner
  const winnerEl = document.getElementById('scoreWinner');
  if (aiWon) {
    winnerEl.textContent = 'The AI Wins!';
    winnerEl.style.color = 'var(--accent)';
  } else {
    winnerEl.textContent = 'Humans Win!';
    winnerEl.style.color = '#6ddf8a';
  }

  // AI reveal
  const aiLabel = aiUsernames.length === 1 ? 'The AI was' : 'The AIs were';
  document.getElementById('scoreAiReveal').textContent = `${aiLabel}: ${aiUsernames.join(', ') || 'Unknown'}`;

  // Survivors list
  const survivorsEl = document.getElementById('scoreSurvivors');
  survivorsEl.innerHTML = '';
  if (remaining.length === 0) {
    survivorsEl.innerHTML = '<span style="color:var(--muted)">None</span>';
  } else {
    remaining.forEach(p => {
      const row = document.createElement('div');
      row.className = 'room-item';
      row.style.padding = '8px 10px';
      row.innerHTML = `
        <span class="monospace">${escapeHtml(p.username)}</span>
        ${p.isAi ? '<span style="color:var(--accent); font-size:12px">AI</span>' : ''}
      `;
      survivorsEl.appendChild(row);
    });
  }

  // Eliminated list
  const eliminatedEl = document.getElementById('scoreEliminated');
  eliminatedEl.innerHTML = '';
  if (eliminated.length === 0) {
    eliminatedEl.innerHTML = '<span style="color:var(--muted)">None</span>';
  } else {
    eliminated.forEach(p => {
      const row = document.createElement('div');
      row.className = 'room-item';
      row.style.padding = '8px 10px';
      row.innerHTML = `
        <span class="monospace" style="color:var(--muted)">${escapeHtml(p.username)}</span>
        ${p.isAi ? '<span style="color:var(--accent); font-size:12px">AI</span>' : ''}
      `;
      eliminatedEl.appendChild(row);
    });
  }

  document.getElementById('scoreOverlay').style.display = 'grid';
}

document.getElementById('btnPlayAgain').addEventListener('click', () => {
  document.getElementById('scoreOverlay').style.display = 'none';
  clearSession();
  overlay.style.display = 'grid';
  loadRooms();
});

// On load, check for a saved session and reconnect if one exists
(function restoreSession() {
  const s = loadSession();
  if (!s || !s.roomId || !s.playerId) {
    showRegistration();
    setStatus(false);
    return;
  }

  // Restore client state from the saved session
  currentRoom = s.roomId;
  currentPlayerId = s.playerId;
  currentUsername = s.username || '';
  isHost = !!s.isHost;
  registrationData = s.registrationData || null;

  roomLabel.textContent = currentRoom;
  showScreen('screenApp');
  setStatus(false);
  appendMsg('system', 'System', `Reconnecting to ${currentRoom} as ${currentUsername}...`);
  connectWebSocket(currentRoom, currentPlayerId);
})();
