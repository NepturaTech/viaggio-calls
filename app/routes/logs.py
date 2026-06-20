"""
Visor de logs en tiempo real — estilo consola VS Code.
Accesible en /logs desde el navegador.
"""
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

from app.utils.logging import LOG_FILE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>DELFOS — Logs</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }

  body {
    background:#1e1e1e;
    color:#d4d4d4;
    font-family:'Cascadia Code','Fira Code','Consolas','Courier New',monospace;
    font-size:12.5px;
    height:100vh;
    display:flex;
    flex-direction:column;
    overflow:hidden;
  }

  /* ── Barra superior ── */
  #topbar {
    background:#252526;
    border-bottom:1px solid #3e3e42;
    padding:0 12px;
    height:35px;
    display:flex;
    align-items:center;
    gap:10px;
    flex-shrink:0;
    user-select:none;
  }
  #topbar .title {
    font-size:11px;
    color:#cccccc;
    letter-spacing:0.8px;
    text-transform:uppercase;
  }
  .live-dot {
    width:7px; height:7px; border-radius:50%;
    background:#4ec9b0;
    flex-shrink:0;
    animation:pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { box-shadow:0 0 0 0 rgba(78,201,176,.6); }
    50%      { box-shadow:0 0 0 5px rgba(78,201,176,0); }
  }
  .sep { flex:1; }

  /* Filtros */
  #filters { display:flex; gap:6px; align-items:center; }
  #search {
    background:#3c3c3c;
    border:1px solid #3e3e42;
    color:#d4d4d4;
    padding:2px 8px;
    border-radius:3px;
    font-family:inherit;
    font-size:11px;
    width:160px;
    outline:none;
  }
  #search:focus { border-color:#007acc; }
  #search::placeholder { color:#6e6e6e; }

  .btn {
    background:#3c3c3c;
    border:1px solid #3e3e42;
    color:#cccccc;
    padding:2px 9px;
    border-radius:3px;
    cursor:pointer;
    font-family:inherit;
    font-size:11px;
    white-space:nowrap;
  }
  .btn:hover { background:#4d4d4d; }
  .btn.active { background:#0e639c; border-color:#1177bb; color:#fff; }

  /* ── Tabs de nivel ── */
  #tabs {
    background:#2d2d2d;
    border-bottom:1px solid #3e3e42;
    padding:0 12px;
    display:flex;
    gap:2px;
    flex-shrink:0;
    height:28px;
    align-items:flex-end;
  }
  .tab {
    padding:3px 12px;
    border-radius:3px 3px 0 0;
    cursor:pointer;
    font-size:11px;
    border:1px solid transparent;
    border-bottom:none;
    color:#969696;
    background:transparent;
    font-family:inherit;
  }
  .tab:hover { color:#cccccc; }
  .tab.active {
    background:#1e1e1e;
    border-color:#3e3e42;
    color:#cccccc;
  }
  .tab .count {
    display:inline-block;
    background:#3e3e42;
    border-radius:999px;
    padding:0 5px;
    font-size:10px;
    margin-left:4px;
  }
  .tab.warn .count { background:#ce9178; color:#1e1e1e; }
  .tab.err  .count { background:#f44747; color:#fff; }

  /* ── Área de logs ── */
  #log-wrap {
    flex:1;
    overflow-y:auto;
    overflow-x:hidden;
  }
  #log-wrap::-webkit-scrollbar { width:8px; }
  #log-wrap::-webkit-scrollbar-track { background:#1e1e1e; }
  #log-wrap::-webkit-scrollbar-thumb { background:#424242; border-radius:4px; }
  #log-wrap::-webkit-scrollbar-thumb:hover { background:#555; }

  table { width:100%; border-collapse:collapse; }
  tr { border-bottom:1px solid transparent; }
  tr:hover { background:#2a2d2e; }
  tr.hidden { display:none; }

  td { padding:1px 0; vertical-align:top; }
  td.ln   { color:#3e3e42; padding:0 6px; width:36px; text-align:right; font-size:11px; user-select:none; }
  td.ts   { color:#6a9955; white-space:nowrap; padding-right:10px; padding-left:8px; }
  td.lv   { width:56px; font-weight:bold; }
  td.mod  { color:#9cdcfe; white-space:nowrap; padding-right:10px; max-width:200px; overflow:hidden; text-overflow:ellipsis; }
  td.msg  { white-space:pre-wrap; word-break:break-all; padding-right:8px; color:#d4d4d4; }

  /* Colores por nivel */
  .lv-info     { color:#4fc1ff; }
  .lv-warning  { color:#ce9178; }
  .lv-error    { color:#f44747; }
  .lv-critical { color:#f44747; background:rgba(244,71,71,.15); }
  .lv-debug    { color:#6e6e6e; }

  /* Colores por contenido */
  .msg-ws     { color:#4ec9b0; }   /* WebSocket, TURNO */
  .msg-claude { color:#c586c0; }   /* Claude, stream, cache */
  .msg-call   { color:#dcdcaa; }   /* call, SID, PACIENTE */
  .msg-warn   { color:#ce9178; }
  .msg-error  { color:#f44747; }
  .msg-ok     { color:#6a9955; }   /* warmup, completado */

  /* Highlight de búsqueda */
  mark { background:#613315; color:#d4d4d4; border-radius:2px; }

  /* ── Barra inferior ── */
  #statusbar {
    background:#007acc;
    color:#fff;
    padding:2px 12px;
    font-size:11px;
    display:flex;
    gap:16px;
    flex-shrink:0;
  }
  #statusbar span { opacity:.85; }
  #statusbar span b { opacity:1; }
</style>
</head>
<body>

<div id="topbar">
  <div class="live-dot" id="dot"></div>
  <div class="title">DELFOS — Output (logs en tiempo real)</div>
  <div class="sep"></div>
  <div id="filters">
    <input id="search" type="text" placeholder="Filtrar logs…" oninput="applyFilter()">
    <button class="btn" id="btnScroll" onclick="toggleScroll()">⬇ Auto-scroll</button>
    <button class="btn" onclick="clearLogs()">🗑 Limpiar</button>
  </div>
</div>

<div id="tabs">
  <button class="tab active" onclick="setLevel('ALL')"  id="tab-ALL">Todos <span class="count" id="cnt-ALL">0</span></button>
  <button class="tab"        onclick="setLevel('INFO')" id="tab-INFO">INFO  <span class="count" id="cnt-INFO">0</span></button>
  <button class="tab warn"   onclick="setLevel('WARN')" id="tab-WARN">WARN  <span class="count warn" id="cnt-WARN">0</span></button>
  <button class="tab err"    onclick="setLevel('ERROR')"id="tab-ERROR">ERROR <span class="count err"  id="cnt-ERROR">0</span></button>
</div>

<div id="log-wrap">
  <table id="log-table"><tbody id="log-body"></tbody></table>
</div>

<div id="statusbar">
  <span id="st-conn">● Conectando…</span>
  <span>Líneas: <b id="st-lines">0</b></span>
  <span>Warns: <b id="st-warn">0</b></span>
  <span>Errors: <b id="st-err">0</b></span>
  <span id="st-cache" style="margin-left:auto"></span>
</div>

<script>
let autoScroll  = true;
let activeLevel = 'ALL';
let filterText  = '';
let lineNum     = 0;
let counts      = { ALL:0, INFO:0, WARN:0, ERROR:0 };
let warnTotal   = 0;
let errTotal    = 0;
let lastCacheWrite = 0;
let lastCacheRead  = 0;

const body   = document.getElementById('log-body');
const wrap   = document.getElementById('log-wrap');
const search = document.getElementById('search');

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function highlight(s){
  if(!filterText) return esc(s);
  const re = new RegExp('('+filterText.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','gi');
  return esc(s).replace(re,'<mark>$1</mark>');
}

function msgClass(msg, level){
  if(level==='WARNING' || level==='WARN') return 'msg-warn';
  if(level==='ERROR'   || level==='CRITICAL') return 'msg-error';
  const m = msg.toLowerCase();
  if(m.includes('websocket')||m.includes('conversationrelay')||m.includes('turno')||m.includes('session')) return 'msg-ws';
  if(m.includes('claude')||m.includes('stream')||m.includes('cache')||m.includes('openai')) return 'msg-claude';
  if(m.includes('call')||m.includes('sid')||m.includes('paciente')||m.includes('outbound')||m.includes('inbound')) return 'msg-call';
  if(m.includes('warmup')||m.includes('completado')||m.includes('loaded')||m.includes('ok')) return 'msg-ok';
  return '';
}

function parseLine(raw){
  // 2026-06-04 19:34:18 | INFO     | app.routes.xxx | message
  const m = raw.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*(\w+)\s*\|\s*([^|]+?)\s*\|\s*([\s\S]*)$/);
  if(m){
    const [,ts,level,mod,msg] = m;
    return { ts, level: level.trim(), mod: mod.trim(), msg: msg.trim() };
  }
  // raw uvicorn line
  const lvl = raw.includes('ERROR')||raw.includes('error')   ? 'ERROR'   :
              raw.includes('WARNING')||raw.includes('warn')   ? 'WARNING' :
              raw.includes('INFO')||raw.includes('startup')   ? 'INFO'    : 'DEBUG';
  return { ts:'', level:lvl, mod:'system', msg:raw.trim() };
}

function shouldShow(row){
  const lvl = row.dataset.level;
  const txt = row.dataset.raw;
  if(activeLevel !== 'ALL'){
    if(activeLevel==='WARN'  && !['WARNING','WARN'].includes(lvl)) return false;
    if(activeLevel==='ERROR' && !['ERROR','CRITICAL'].includes(lvl)) return false;
    if(activeLevel==='INFO'  && lvl!=='INFO') return false;
  }
  if(filterText && !txt.toLowerCase().includes(filterText.toLowerCase())) return false;
  return true;
}

function addLine(raw){
  if(!raw.trim()) return;
  const p = parseLine(raw);
  lineNum++;

  const lvlKey = ['WARNING','WARN'].includes(p.level) ? 'WARN' :
                 ['ERROR','CRITICAL'].includes(p.level) ? 'ERROR' : 'INFO';

  counts.ALL++;
  counts[lvlKey] = (counts[lvlKey]||0) + 1;
  if(lvlKey==='WARN')  warnTotal++;
  if(lvlKey==='ERROR') errTotal++;

  // Cache stats
  const cm = raw.match(/cache_read=(\d+).*cache_write=(\d+)/);
  if(cm){
    lastCacheRead  = parseInt(cm[1]);
    lastCacheWrite = parseInt(cm[2]);
    document.getElementById('st-cache').textContent =
      `Cache hit: ${lastCacheRead}t | write: ${lastCacheWrite}t`;
  }

  const tr = document.createElement('tr');
  tr.dataset.level = p.level;
  tr.dataset.raw   = raw;

  const lvCls = p.level==='INFO'     ? 'lv-info'    :
                p.level==='WARNING' ||
                p.level==='WARN'    ? 'lv-warning'  :
                p.level==='ERROR'   ? 'lv-error'    :
                p.level==='CRITICAL'? 'lv-critical' : 'lv-debug';

  const mCls = msgClass(p.msg, p.level);

  const shortMod = p.mod.split('.').pop();

  tr.innerHTML =
    `<td class="ln">${lineNum}</td>` +
    `<td class="ts">${p.ts ? p.ts.slice(11) : ''}</td>` +
    `<td class="lv ${lvCls}">${p.level.slice(0,4)}</td>` +
    `<td class="mod" title="${esc(p.mod)}">${esc(shortMod)}</td>` +
    `<td class="msg ${mCls}">${highlight(p.msg)}</td>`;

  if(!shouldShow(tr)) tr.classList.add('hidden');
  body.appendChild(tr);

  // Trim a 1000 líneas
  while(body.rows.length > 1000) body.deleteRow(0);

  // Actualizar contadores
  document.getElementById('cnt-ALL').textContent   = counts.ALL;
  document.getElementById('cnt-INFO').textContent  = counts.INFO||0;
  document.getElementById('cnt-WARN').textContent  = warnTotal;
  document.getElementById('cnt-ERROR').textContent = errTotal;
  document.getElementById('st-lines').textContent  = counts.ALL;
  document.getElementById('st-warn').textContent   = warnTotal;
  document.getElementById('st-err').textContent    = errTotal;

  if(autoScroll) wrap.scrollTop = wrap.scrollHeight;
}

function toggleScroll(){
  autoScroll = !autoScroll;
  const btn = document.getElementById('btnScroll');
  btn.classList.toggle('active', autoScroll);
  btn.textContent = autoScroll ? '⬇ Auto-scroll' : '— Scroll pausado';
}

function clearLogs(){
  body.innerHTML = '';
  lineNum = 0;
  counts  = { ALL:0, INFO:0, WARN:0, ERROR:0 };
  warnTotal = errTotal = 0;
  ['ALL','INFO','WARN','ERROR'].forEach(k=>document.getElementById('cnt-'+k).textContent=0);
  document.getElementById('st-lines').textContent = document.getElementById('st-warn').textContent =
  document.getElementById('st-err').textContent = '0';
}

function setLevel(lvl){
  activeLevel = lvl;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('tab-'+lvl).classList.add('active');
  applyFilter();
}

function applyFilter(){
  filterText = search.value.trim();
  // Re-colorear highlights
  for(const tr of body.rows){
    const p = parseLine(tr.dataset.raw);
    const mCls = msgClass(p.msg, p.level);
    const td = tr.cells[4];
    if(td){ td.className = 'msg '+mCls; td.innerHTML = highlight(p.msg); }
    tr.classList.toggle('hidden', !shouldShow(tr));
  }
}

document.getElementById('btnScroll').classList.add('active');

// SSE connection
const es = new EventSource('/logs/stream');
es.onopen = ()=>{
  document.getElementById('dot').style.background = '#4ec9b0';
  document.getElementById('st-conn').textContent  = '● En vivo';
};
es.onmessage = e => { addLine(e.data); };
es.onerror = ()=>{
  document.getElementById('dot').style.background = '#f44747';
  document.getElementById('st-conn').textContent  = '● Desconectado — reconectando…';
};

// Atajo de teclado: Ctrl+K = limpiar, Ctrl+F = enfocar filtro
document.addEventListener('keydown', e=>{
  if(e.ctrlKey && e.key==='k'){ e.preventDefault(); clearLogs(); }
  if(e.ctrlKey && e.key==='f'){ e.preventDefault(); search.focus(); }
});
</script>
</body>
</html>"""


@router.get("/logs", response_class=HTMLResponse, include_in_schema=False)
async def log_viewer():
    """Visor de logs en tiempo real — estilo VS Code."""
    return HTMLResponse(_HTML)


@router.get("/logs/stream", include_in_schema=False)
async def stream_logs():
    """SSE endpoint — sigue logs/logs.txt en tiempo real (tail -f)."""

    async def generate():
        try:
            while not LOG_FILE.exists():
                yield "data: [esperando logs/logs.txt…]\n\n"
                await asyncio.sleep(1)
            f = LOG_FILE.open("r", encoding="utf-8", errors="replace")
            try:
                # Últimas 80 líneas al conectar, luego seguir
                for line in f.readlines()[-80:]:
                    text = line.rstrip()
                    if text:
                        yield f"data: {text}\n\n"
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        text = line.rstrip()
                        if text:
                            yield f"data: {text}\n\n"
                    else:
                        await asyncio.sleep(0.5)
                        # Detectar rotación (RotatingFileHandler): el archivo se truncó
                        if LOG_FILE.exists() and LOG_FILE.stat().st_size < f.tell():
                            f.close()
                            f = LOG_FILE.open("r", encoding="utf-8", errors="replace")
            finally:
                f.close()
        except Exception as exc:
            yield f"data: [ERROR al leer logs.txt: {exc}]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering":"no",   # desactiva buffer de nginx para SSE
            "Connection":       "keep-alive",
        },
    )
