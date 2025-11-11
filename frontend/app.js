const $ = (s)=>document.querySelector(s);
const logEl = $('#log');
const statusEl = $('#status');
const roomLabel = $('#roomLabel');
const overlay = $('#overlay');
let ws = null; let connected=false; let currentRoom = '';

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

const mockRooms = ()=>[
  {id:'LOBBY',users:3,updated:'just now'},
  {id:'ALPHA1',users:1,updated:'2m ago'},
  {id:'BETA42',users:5,updated:'8m ago'}];

async function loadRooms(){
  const data=mockRooms(); const list=$('#roomList'); list.innerHTML='';
  data.forEach(r=>{
    const row=document.createElement('div'); row.className='room-item';
    row.innerHTML=`<div><div class="room-id monospace">${r.id}</div><div class="room-meta">${r.users} online • ${r.updated}</div></div><button class="btn primary" data-join="${r.id}">Join</button>`;
    list.appendChild(row);
  });
}

function joinRoom(id){ currentRoom=id; roomLabel.textContent=id; overlay.style.display='none'; setStatus(true); }

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
$('#createRoom').addEventListener('click',()=>{let id=$('#newRoomId').value.trim().toUpperCase(); if(!id){id=Math.random().toString(36).slice(2,8).toUpperCase();} joinRoom(id);});
document.addEventListener('click',e=>{const btn=e.target.closest('[data-join]'); if(btn){joinRoom(btn.getAttribute('data-join'));}});

function send(){
  const val=$('#input').value.trim(); if(!val) return; $('#input').value='';
  // generate a temporary name once per browser session
  const name = localStorage.getItem('tempName') ||
    (() => {
      const temp = 'Player-' + Math.floor(Math.random() * 1000);
      localStorage.setItem('tempName', temp);
      return temp;
    })();
  appendMsg('you',name,val);
  const mode=$('#mode').value;
  if(mode==='mock'||!ws){mockAiReply(val);} else if(ws&&ws.readyState===1){ws.send(JSON.stringify({type:'chat',text:val}));}
}

overlay.style.display='grid'; loadRooms(); setStatus(false);
