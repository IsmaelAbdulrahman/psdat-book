#!/usr/bin/env python3
"""
make_mobile.py — build PSDAT Mobile: the complete Python edition running
entirely INSIDE the phone's browser (WebAssembly, no server, no install).

What it produces (default: ../mobile_dist):
  index.html      the full PSDAT page + the mobile bridge (engine-in-browser,
                  touch input, install banner, boot overlay)
  worker.js       a Web Worker that boots Pyodide (CPython compiled to
                  WebAssembly), loads NumPy + SciPy, mounts the PSDAT engine
                  files and serves every /api/* call the page makes
  engine/         the unmodified PSDAT python engine + bundled case files
  pyodide/        the Python runtime + numpy/scipy wheels  (put them here —
                  see PYODIDE NOTE below)
  manifest.json, sw.js, icon-*.png
                  Progressive-Web-App wrapper: "Add to Home screen" installs
                  PSDAT like an app, and after the first visit it runs fully
                  OFFLINE (the service worker caches everything).

PYODIDE NOTE: the runtime is not committed to the repo (75 MB). Download
pyodide-0.26.4.tar.bz2 from https://github.com/pyodide/pyodide/releases,
and copy into mobile_dist/pyodide/:  pyodide.js, pyodide.asm.js,
pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json, and the numpy,
scipy and openblas wheels/zips. (This script checks and tells you.)

Hosting: any static HTTPS host (GitHub Pages works) — or, on the phone
itself, Termux + `python -m http.server` and open http://localhost:8000.
Service workers require HTTPS or localhost; both options satisfy that.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else \
      os.path.join(os.path.dirname(HERE), 'mobile_dist')

ENGINE_FILES = ['psdat_gui.py', 'cases.py', 'system.py', 'units.py',
                'simulate.py', 'network.py', 'facts.py', 'design.py',
                'linearize.py',
                'IEEE9Bus.m', 'case14.m', 'case30.m', 'case39.m',
                'case57.m', 'case68_16m.m', 'case118.m', 'case300.m']

# Cache key: derived from the ENGINE + GUI content, so every rebuild with a
# changed app invalidates installed PWAs automatically (SW cache-first would
# otherwise pin users to the old build forever).
def _app_version():
    import hashlib
    h = hashlib.md5()
    for fn in ENGINE_FILES:
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                h.update(f.read())
    return 'psdat-mobile-' + h.hexdigest()[:10]

APP_VERSION = _app_version()

BRIDGE = r"""
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#1f3b73">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="apple-touch-icon" href="icon-192.png">
<style>#pyboot{position:fixed;inset:0;background:#f4f6fa;z-index:9999;display:flex;align-items:center;justify-content:center;font-family:Georgia,serif}
#pyboot .c{text-align:center;max-width:340px;padding:0 18px}
#pyboot .logo{font-size:34px;font-weight:700;color:#1f3b73;letter-spacing:.06em;margin-bottom:14px}
#pyboot .m{color:#41506a;font-size:14px;margin-bottom:10px;min-height:18px}
#pyboot .bar{height:6px;background:#dde4ee;border-radius:3px;overflow:hidden}
#pyboot .bar i{display:block;height:100%;width:0;background:#1f3b73;transition:width .4s}
#pyboot .s{color:#8a93a3;font-size:11px;margin-top:12px;line-height:1.5}</style>
<script>
/* ============ PSDAT Mobile bridge: the engine runs IN this browser ======= */
(function(){
 'use strict';
 var W=new Worker('worker.js'), seq=0, PEND={}, bootEl=null;
 function ui(msg,frac){
  if(!bootEl){bootEl=document.createElement('div');bootEl.id='pyboot';
   bootEl.innerHTML='<div class="c"><div class="logo">PSDAT</div><div class="m"></div>'+
    '<div class="bar"><i></i></div><div class="s">the complete analysis engine runs on this device — '+
    'the first launch fetches ~75\u00a0MB once, then PSDAT works fully offline</div></div>';
   (document.body||document.documentElement).appendChild(bootEl);}
  bootEl.querySelector('.m').textContent=msg;
  if(frac>=0)bootEl.querySelector('.bar i').style.width=(100*frac)+'%';
  if(frac<0)bootEl.querySelector('.bar').style.display='none';
  if(frac>=1)setTimeout(function(){if(bootEl){bootEl.remove();bootEl=null;}},350);}
 W.onmessage=function(e){var d=e.data;
  if(d.boot!==undefined){ui(d.boot,d.frac);return;}
  var r=PEND[d.id];delete PEND[d.id];if(r)r(d.res);};
 W.onerror=function(e){ui('engine failed to start: '+(e.message||e),-1);};
 function CALL(path,body){return new Promise(function(res){
  PEND[++seq]=res;W.postMessage({id:seq,path:path,body:body});});}
 var _fetch=window.fetch.bind(window);
 window.fetch=function(u,o){
  var url=(typeof u==='string')?u:((u&&u.url)||'');
  if(url.indexOf('/api/')===0)
   return CALL(url,(o&&o.body)?String(o.body):null).then(function(s){
    return new Response(s,{status:200,headers:{'Content-Type':'application/json'}});});
  return _fetch(u,o);};
 if('serviceWorker' in navigator)
  addEventListener('load',function(){navigator.serviceWorker.register('sw.js').catch(function(){});});
 /* ---------- touch input: 1 finger = draw/drag · 2 fingers = pan + pinch --- */
 addEventListener('DOMContentLoaded',function(){
  var el=document.getElementById('sld');if(!el)return;
  el.style.touchAction='none';
  function ev(t,x,y,btn){
   var tgt=document.elementFromPoint(x,y)||el;      // the shape under the finger,
   if(!el.contains(tgt))tgt=el;                     // so hit-testing by target works
   tgt.dispatchEvent(new MouseEvent(t,{clientX:x,clientY:y,
   button:btn||0,buttons:t==='mouseup'?0:(btn===1?4:1),bubbles:true,cancelable:true}));}
  var mode=0,px=0,py=0,pd=0;
  el.addEventListener('touchstart',function(e){e.preventDefault();var t=e.touches;
   if(t.length===1){mode=1;px=t[0].clientX;py=t[0].clientY;ev('mousedown',px,py,0);}
   else if(t.length>=2){if(mode===1)ev('mouseup',px,py,0);
    mode=2;px=(t[0].clientX+t[1].clientX)/2;py=(t[0].clientY+t[1].clientY)/2;
    pd=Math.hypot(t[0].clientX-t[1].clientX,t[0].clientY-t[1].clientY);
    ev('mousedown',px,py,1);}},{passive:false});
  el.addEventListener('touchmove',function(e){e.preventDefault();var t=e.touches;
   if(mode===1&&t.length===1){px=t[0].clientX;py=t[0].clientY;ev('mousemove',px,py,0);}
   else if(mode===2&&t.length>=2){
    var nx=(t[0].clientX+t[1].clientX)/2,ny=(t[0].clientY+t[1].clientY)/2;
    ev('mousemove',nx,ny,1);px=nx;py=ny;
    var nd=Math.hypot(t[0].clientX-t[1].clientX,t[0].clientY-t[1].clientY);
    if(pd>0&&Math.abs(nd-pd)>6){el.dispatchEvent(new WheelEvent('wheel',
     {clientX:nx,clientY:ny,deltaY:pd-nd,bubbles:true,cancelable:true}));pd=nd;}}},{passive:false});
  function end(e){e.preventDefault();
   if(mode===1)ev('mouseup',px,py,0);
   if(mode===2)ev('mouseup',px,py,1);
   if(e.touches&&e.touches.length===1){mode=1;px=e.touches[0].clientX;
    py=e.touches[0].clientY;ev('mousedown',px,py,0);}
   else mode=0;}
  el.addEventListener('touchend',end,{passive:false});
  el.addEventListener('touchcancel',end,{passive:false});});
 /* ---------- small screens: docks become edge tabs (tap to peek) ---------- */
 var fit=setInterval(function(){try{
  if(typeof LAY!=='undefined'&&LAY&&typeof applyLayout==='function'&&typeof PNS!=='undefined'){
   clearInterval(fit);
   if(Math.min(innerWidth,innerHeight)<640&&innerWidth<900){
    PNS.forEach(function(k){LAY.p[k].pin=0;});applyLayout(false);
    if(typeof fitView==='function')setTimeout(function(){fitView();},250);}}
 }catch(_){}} ,600);
})();
</script>
"""

WORKER = r"""/* PSDAT Mobile worker: boots Python-in-WebAssembly and serves /api/* */
var READY=false, Q=[];
self.onmessage=function(e){ if(READY) run(e.data); else Q.push(e.data); };
importScripts('pyodide/pyodide.js');
function send(m){ self.postMessage(m); }
var route=null;
async function boot(){
  send({boot:'starting the Python runtime\u2026',frac:.05});
  self.py = await loadPyodide({indexURL:'./pyodide/'});
  send({boot:'loading NumPy + SciPy\u2026',frac:.35});
  await py.loadPackage(['numpy','scipy']);
  send({boot:'mounting the PSDAT engine\u2026',frac:.8});
  var files=__ENGINE_FILES__;
  py.FS.mkdirTree('/psdat');
  for(var i=0;i<files.length;i++){
    var r=await fetch('engine/'+files[i]);
    py.FS.writeFile('/psdat/'+files[i], new Uint8Array(await r.arrayBuffer()));
  }
  send({boot:'importing the model library\u2026',frac:.9});
  await py.runPythonAsync(
"import sys, json\n"+
"sys.path.insert(0,'/psdat')\n"+
"import psdat_gui as G\n"+
"def _route(path, body):\n"+
"    if path=='/api/ping': return '{}'\n"+
"    try:\n"+
"        if path=='/api/meta': return json.dumps(G.api_meta(None), default=G._jsonable)\n"+
"        if path=='/api/scenario':\n"+
"            return json.dumps({'error':'RuntimeError: scenario studies need matplotlib and run in the desktop edition; every other analysis runs right here on this device'})\n"+
"        fn=G.ROUTES.get(path)\n"+
"        if fn is None: return json.dumps({'error':'unknown endpoint'})\n"+
"        req=json.loads(body) if body else {}\n"+
"        return json.dumps(fn(req), default=G._jsonable)\n"+
"    except Exception as e:\n"+
"        return json.dumps({'error': f'{type(e).__name__}: {e}'})\n");
  route = py.globals.get('_route');
  READY=true; send({boot:'ready',frac:1});
  for(var j=0;j<Q.length;j++) run(Q[j]); Q=[];
}
function run(m){ var res;
  try{ res = route(m.path, m.body); }
  catch(err){ res = JSON.stringify({error:String(err)}); }
  send({id:m.id, res:res});
}
boot().catch(function(err){ send({boot:'engine failed: '+err, frac:-1}); });
"""

MANIFEST = """{
  "name": "PSDAT — Power System Dynamic Analysis Toolbox",
  "short_name": "PSDAT",
  "description": "Transparent power-system analysis — power flow, dynamics, small-signal, FACTS and renewables — running entirely on this device.",
  "start_url": "./index.html",
  "scope": "./",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#f4f6fa",
  "theme_color": "#1f3b73",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
  ]
}
"""

SW = r"""/* PSDAT Mobile service worker: precache everything -> full offline app */
var CACHE='__VERSION__';
var ASSETS=__ASSETS__;
self.addEventListener('install',function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){return c.addAll(ASSETS);})
    .then(function(){return self.skipWaiting();}));});
self.addEventListener('activate',function(e){
  e.waitUntil(caches.keys().then(function(ks){
    return Promise.all(ks.filter(function(k){return k!==CACHE;})
      .map(function(k){return caches.delete(k);}));})
    .then(function(){return self.clients.claim();}));});
self.addEventListener('fetch',function(e){
  if(e.request.method!=='GET')return;
  e.respondWith(caches.match(e.request,{ignoreSearch:true}).then(function(hit){
    return hit||fetch(e.request);}));});
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    # ---- engine ----------------------------------------------------------
    eng = os.path.join(OUT, 'engine')
    os.makedirs(eng, exist_ok=True)
    for f in ENGINE_FILES:
        shutil.copy2(os.path.join(HERE, f), eng)
    # ---- page ------------------------------------------------------------
    sys.path.insert(0, HERE)
    import psdat_gui as G
    page = G.PAGE
    k = page.index('<script>')                    # the single big app script
    page = page[:k] + BRIDGE + page[k:]
    open(os.path.join(OUT, 'index.html'), 'w').write(page)
    # ---- worker ----------------------------------------------------------
    import json as _json
    open(os.path.join(OUT, 'worker.js'), 'w').write(
        WORKER.replace('__ENGINE_FILES__', _json.dumps(ENGINE_FILES)))
    # ---- manifest + icons -------------------------------------------------
    open(os.path.join(OUT, 'manifest.json'), 'w').write(MANIFEST)
    try:
        from PIL import Image
        ico = Image.open(os.path.join(HERE, 'PSDAT.ico'))
        ico = ico.convert('RGBA')
        for s in (192, 512):
            im = Image.new('RGBA', (s, s), (31, 59, 115, 255))
            g = ico.resize((int(s * .78),) * 2, Image.LANCZOS)
            im.paste(g, ((s - g.width) // 2,) * 2, g)
            im.save(os.path.join(OUT, f'icon-{s}.png'))
    except Exception as e:
        print('icon generation skipped:', e)
    # ---- pyodide presence + service worker --------------------------------
    pyo = os.path.join(OUT, 'pyodide')
    need = ['pyodide.js', 'pyodide.asm.js', 'pyodide.asm.wasm',
            'python_stdlib.zip', 'pyodide-lock.json']
    if not (os.path.isdir(pyo) and all(os.path.isfile(os.path.join(pyo, f)) for f in need)):
        print('\n!! pyodide/ runtime is missing or incomplete in', pyo)
        print('   download pyodide-0.26.4.tar.bz2 from')
        print('   https://github.com/pyodide/pyodide/releases and copy in:')
        print('   ' + ', '.join(need) + ' + the numpy/scipy/openblas wheels')
    assets = ['./', 'index.html', 'worker.js', 'manifest.json',
              'icon-192.png', 'icon-512.png']
    assets += ['engine/' + f for f in ENGINE_FILES]
    if os.path.isdir(pyo):
        assets += ['pyodide/' + f for f in sorted(os.listdir(pyo))
                   if not f.endswith('.metadata')]
    open(os.path.join(OUT, 'sw.js'), 'w').write(
        SW.replace('__VERSION__', APP_VERSION)
          .replace('__ASSETS__', _json.dumps(assets)))
    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(OUT) for f in fs)
    print(f'PSDAT Mobile built -> {OUT}  ({total//1024//1024} MB, '
          f'{len(assets)} cached assets)')
    print('host the folder on any static HTTPS server (or Termux localhost) '
          'and open index.html')


if __name__ == '__main__':
    main()
