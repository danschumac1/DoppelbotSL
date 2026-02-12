const $ = (s)=>document.querySelector(s);
const logEl = $('#log');
const statusEl = $('#status');
const roomLabel = $('#roomLabel');
const overlay = $('#overlay');
let ws = null; 
let connected=false; 
let currentRoom = '';
let currentUser = '';

function setStatus(ok){ connected=ok; statusEl.innerHTML = ok ? '<span class="dot"></span> connected' : '<span class="dot red"></span> disconnected'; }
function appendMsg(kind, name, text){
  const wrap=document.createElement('div'); wrap.className=`msg ${kind}`;
  const showName = kind === 'ai' ? name : ''; // optional: hide your own meta
  wrap.innerHTML =
    `<div class="avatar">${kind==='ai'?'AI':'You'}</div>
     <div class="bubble">
       ${showName ? `<div class="meta">${showName}</div>` : ''}
       <div>${escapeHtml(text)}</div>
     </div>`;
  logEl.appendChild(wrap); logEl.scrollTop=logEl.scrollHeight;
}

function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));}

function joinRoom(id){
  currentRoom=id;
  roomLabel.textContent=id;
  overlay.style.display='none';
  setStatus(false);
}

async function mockAiReply(userText){
  const delay=250+Math.random()*650; await new Promise(r=>setTimeout(r,delay));
  appendMsg('ai','DoppelBot (mock)',`You said: ${userText}`);
}

$('#send').addEventListener('click',send);
$('#input').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();send();}});
$('#clear').addEventListener('click',()=>{logEl.innerHTML='';});
$('#disconnect').addEventListener('click',()=>{
  if(ws){try{ws.close();}catch(_){}} ws=null; setStatus(false); appendMsg('ai','System','You have disconnected.');
  currentRoom=''; roomLabel.textContent='—';
  overlay.style.display='grid'; loadRooms();
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


function send(){
  const val=$('#input').value.trim(); if(!val) return; $('#input').value='';
  // generate a temporary name once per browser session
  const name = localStorage.getItem('tempName') ||
    (() => {
      const temp = 'Player-' + Math.floor(Math.random() * 1000);
      localStorage.setItem('tempName', temp);
      return temp;
    })();
  if (!ws || ws.readyState !== 1) {
  appendMsg('ai', 'System', 'Not connected. Join a room first.');
  return;
}

ws.send(JSON.stringify({ type: 'chat', text: val }));

}

async function loadRooms() {
  const list = document.getElementById('roomList');
  list.innerHTML = '';

  //Loading State
  const loading = document.createElement('div');
  loading.className = 'room-item';
  loading.innerHTML = '<div><div class="room-id monospace">Loading...</div></div>';
  list.appendChild(loading);

  try{
    const res = await fetch('/api/rooms', { method: 'GET' });
    if (!res.ok) throw new Error(`GET /api/rooms failed: ${res.status}`);

    const rooms = await res.json(); //[{id,users, lastActivity},...]
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
      row.className = 'room-item'
      row.innerHTML = `
        <div>
          <div class = "room-id monospace">${escapeHtml(id)}</div>
          <div class="room-meta">${users} online • active ${formatAge(last)} ago</div>
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

// Sidebar open/close
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

// “Play Game” should open the room select overlay (your existing overlay)
function goPlay(){
  showScreen('screenApp');       // go to main app screen
  overlay.style.display = 'grid'; // open room list overlay
  loadRooms();                    // refresh rooms
}

async function joinRoomFlow(roomId) {
  const room = String(roomId || '').trim().toUpperCase();
  if (!room) return;

  // Ask backend to join and assign unique userId
  const res = await fetch(`/api/rooms/${encodeURIComponent(room)}/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: '' }) // backend will default to "Player"
  });

  if (!res.ok) {
    alert(`Failed to join room: ${res.status}`);
    return;
  }

  const data = await res.json();
  currentRoom = data.roomId;
  currentUser = data.userId;

  // UI
  roomLabel.textContent = currentRoom;
  overlay.style.display = 'none';
  logEl.innerHTML = '';

  connectWebSocket(currentRoom, currentUser);
}

function wsUrl(path) {
  // Works for localhost + Cloudflare Tunnel (https -> wss)
  const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
  return `${proto}://${location.host}${path}`;
}

function connectWebSocket(room, user) {
  // Close old WS if any
  if (ws) { try { ws.close(); } catch {} ws = null; }

  setStatus(false);
  ws = new WebSocket(wsUrl(`/ws/${encodeURIComponent(room)}/${encodeURIComponent(user)}`));

  ws.onopen = () => {
    setStatus(true);
    appendMsg('ai', 'System', `Connected as ${user}`);
  };

  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { msg = { type: 'chat', user: '???', text: ev.data }; }

    if (msg.type === 'history' && Array.isArray(msg.messages)) {
      msg.messages.forEach(m => appendMsg(m.user === currentUser ? 'you' : 'ai', m.user, m.text));
      return;
    }

    if (msg.type === 'chat') {
      const kind = (msg.user === currentUser) ? 'you' : 'ai';
      appendMsg(kind, msg.user, msg.text);
      return;
    }

    if (msg.type === 'system') {
      appendMsg('ai', 'System', msg.text || '');
      return;
    }
  };

  ws.onclose = () => {
    setStatus(false);
    appendMsg('ai', 'System', 'Disconnected.');
  };

  ws.onerror = () => {
    setStatus(false);
  };
}

overlay.style.display='grid'; loadRooms(); setStatus(false);
