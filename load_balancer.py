#!/usr/bin/env python3
"""
Cloud Load Balancing Demonstrator   (U23CS702 - Mini Project, Reg. No. 301)
---------------------------------------------------------------------------
Runs 4 real backend HTTP servers (ports 9001-9004) and a load balancer
(port 8080) that distributes requests using 5 algorithms, with health
checks, automatic failover and a live request-distribution dashboard.

Run   :  python load_balancer.py
Open  :  http://localhost:8080
Needs :  Python 3.8+ only (no pip install).
"""
import json, random, threading, time, zlib, urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

LB_PORT = 8080
ThreadingHTTPServer.request_queue_size = 128

# Backend pool: weight = relative capacity, latency = simulated processing time (s)
SERVERS = [
    {"name": "Server-1", "port": 9001, "weight": 5, "latency": 0.05},
    {"name": "Server-2", "port": 9002, "weight": 3, "latency": 0.10},
    {"name": "Server-3", "port": 9003, "weight": 2, "latency": 0.20},
    {"name": "Server-4", "port": 9004, "weight": 1, "latency": 0.40},
]
for i, s in enumerate(SERVERS):
    s.update(id=i, up=True, healthy=True, active=0, total=0, errors=0, ms_sum=0.0, cur=0)

ALGOS = {
    "round_robin": "Round Robin",
    "weighted_rr": "Weighted Round Robin",
    "least_connections": "Least Connections",
    "ip_hash": "IP Hash",
    "random": "Random",
}
lock = threading.Lock()
state = {"algo": "round_robin", "rr": 0, "total": 0, "dropped": 0}
log = deque(maxlen=12)


# ------------------------------------------------------------------ backends
def make_backend(s):
    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if not s["up"]:                       # simulated crashed server
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path.startswith("/work"):
                time.sleep(s["latency"] * random.uniform(0.8, 1.2))
            body = json.dumps({"server": s["name"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Backend


# ------------------------------------------------------- balancing algorithms
def pick(client, exclude=()):
    """Choose a backend. Must be called while holding `lock`."""
    pool = [s for s in SERVERS if s["healthy"] and s["id"] not in exclude]
    if not pool:
        return None
    a = state["algo"]
    if a == "round_robin":
        state["rr"] += 1
        return pool[state["rr"] % len(pool)]
    if a == "weighted_rr":                        # smooth weighted round robin
        total = sum(s["weight"] for s in pool)
        for s in pool:
            s["cur"] += s["weight"]
        best = max(pool, key=lambda s: s["cur"])
        best["cur"] -= total
        return best
    if a == "least_connections":
        return min(pool, key=lambda s: s["active"])
    if a == "ip_hash":                            # same client -> same server
        return pool[zlib.crc32(client.encode()) % len(pool)]
    return random.choice(pool)


def health_checker():
    while True:
        for s in SERVERS:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{s['port']}/health", timeout=1).read()
                ok = True
            except Exception:
                ok = False
            s["healthy"] = ok
        time.sleep(2)


def fire_burst(n):
    def one(_):
        req = urllib.request.Request(
            f"http://127.0.0.1:{LB_PORT}/work",
            headers={"X-Client-ID": f"192.168.1.{random.randint(1, 20)}"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(one, range(n)))


# ------------------------------------------------------------ load balancer
class LB(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = DASHBOARD.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/work":
            self.route_request()
        elif path == "/api/state":
            with lock:
                self.send_json({
                    "algo": state["algo"], "algos": ALGOS, "total": state["total"],
                    "dropped": state["dropped"], "log": list(log),
                    "servers": [{
                        "id": s["id"], "name": s["name"], "port": s["port"],
                        "weight": s["weight"], "up": s["up"], "healthy": s["healthy"],
                        "active": s["active"], "total": s["total"], "errors": s["errors"],
                        "avg_ms": round(s["ms_sum"] / s["total"]) if s["total"] else 0,
                    } for s in SERVERS]})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/algo" and q.get("name", [""])[0] in ALGOS:
            with lock:
                state["algo"] = q["name"][0]
        elif u.path == "/api/toggle":                  # simulate crash / recovery
            sid = int(q.get("id", ["-1"])[0])
            if 0 <= sid < len(SERVERS):
                SERVERS[sid]["up"] = not SERVERS[sid]["up"]
        elif u.path == "/api/burst":
            n = min(int(q.get("n", ["50"])[0]), 1000)
            threading.Thread(target=fire_burst, args=(n,), daemon=True).start()
        elif u.path == "/api/reset":
            with lock:
                state.update(total=0, dropped=0, rr=0)
                log.clear()
                for s in SERVERS:
                    s.update(total=0, errors=0, ms_sum=0.0, cur=0)
        self.send_json({"ok": True})

    def route_request(self):
        client = self.headers.get("X-Client-ID") or self.client_address[0]
        t0, tried = time.time(), []
        while True:
            with lock:
                s = pick(client, tried)
                if s:
                    s["active"] += 1
                else:
                    state["dropped"] += 1
            if not s:
                return self.send_json({"error": "no healthy servers"}, 503)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{s['port']}/work", timeout=3).read()
                ok = True
            except Exception:
                ok = False
            ms = (time.time() - t0) * 1000
            with lock:
                s["active"] -= 1
                if ok:
                    s["total"] += 1
                    s["ms_sum"] += ms
                    state["total"] += 1
                    log.appendleft({"client": client, "server": s["name"], "ms": round(ms)})
                else:                                   # failover: mark down, retry another
                    s["errors"] += 1
                    s["healthy"] = False
                    tried.append(s["id"])
            if ok:
                return self.send_json({"served_by": s["name"], "ms": round(ms)})


DASHBOARD = """<!doctype html><html><head><meta charset="utf-8">
<title>Cloud Load Balancing Demonstrator</title><style>
:root{--bg:#0f172a;--card:#1e293b;--tx:#e2e8f0;--mut:#94a3b8;--ok:#22c55e;--bad:#ef4444}
*{box-sizing:border-box}body{margin:0;padding:20px;font:14px system-ui,sans-serif;background:var(--bg);color:var(--tx)}
h1{margin:0 0 4px;font-size:22px}.sub{color:var(--mut);margin-bottom:16px}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:var(--card);padding:12px;border-radius:10px;margin-bottom:14px}
select,button{font:inherit;padding:7px 12px;border-radius:6px;border:1px solid #334155;background:#0f172a;color:var(--tx);cursor:pointer}
button:hover{background:#334155}.stat{margin-left:auto;color:var(--mut)}.stat b{color:var(--tx)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:14px}
.card{background:var(--card);border-radius:10px;padding:14px;border-top:4px solid}
.card h3{margin:0 0 6px;display:flex;justify-content:space-between}.badge{font-size:12px;padding:2px 8px;border-radius:99px}
.up{background:#14532d;color:#86efac}.down{background:#7f1d1d;color:#fca5a5}
.row{display:flex;justify-content:space-between;color:var(--mut);margin:3px 0}.row b{color:var(--tx)}
.track{height:10px;background:#0f172a;border-radius:5px;margin:10px 0 4px;overflow:hidden}.fill{height:100%;transition:width .4s}
.two{display:grid;grid-template-columns:2fr 1fr;gap:12px}@media(max-width:800px){.two{grid-template-columns:1fr}}
.panel{background:var(--card);border-radius:10px;padding:14px}.panel h4{margin:0 0 8px;color:var(--mut)}
canvas{width:100%;height:200px}.log{font:12px ui-monospace,monospace;color:var(--mut);line-height:1.7}
</style></head><body>
<h1>Cloud Load Balancing Demonstrator</h1>
<div class="sub">Load balancer :8080 &rarr; 4 backend servers :9001-9004 &middot; health checks every 2 s &middot; automatic failover</div>
<div class="bar">
 <label>Algorithm <select id="algo"></select></label>
 <button onclick="burst(50)">Send 50 requests</button>
 <button onclick="burst(200)">Send 200 requests</button>
 <button onclick="post('/api/reset')">Reset counters</button>
 <span class="stat">Total served: <b id="total">0</b> &middot; Dropped: <b id="dropped">0</b></span>
</div>
<div class="grid" id="cards"></div>
<div class="two"><div class="panel"><h4>Requests per second (per server)</h4><canvas id="ch" width="700" height="200"></canvas></div>
<div class="panel"><h4>Latest routing decisions</h4><div class="log" id="log"></div></div></div>
<script>
const COL=['#38bdf8','#a78bfa','#f59e0b','#f472b6'];let prev=null,hist=[];
const post=(p)=>fetch(p,{method:'POST'});const burst=n=>post('/api/burst?n='+n);
document.getElementById('algo').onchange=e=>post('/api/algo?name='+e.target.value);
async function tick(){
 const s=await (await fetch('/api/state')).json();
 const sel=document.getElementById('algo');
 if(!sel.options.length)for(const k in s.algos)sel.add(new Option(s.algos[k],k));
 if(document.activeElement!==sel)sel.value=s.algo;
 document.getElementById('total').textContent=s.total;document.getElementById('dropped').textContent=s.dropped;
 const sum=s.servers.reduce((a,x)=>a+x.total,0)||1;
 document.getElementById('cards').innerHTML=s.servers.map(x=>{
  const ok=x.up&&x.healthy;
  return `<div class="card" style="border-color:${COL[x.id]}"><h3>${x.name}<span class="badge ${ok?'up':'down'}">${ok?'HEALTHY':'DOWN'}</span></h3>
  <div class="row">Port / Weight<b>${x.port} / ${x.weight}</b></div><div class="row">Active connections<b>${x.active}</b></div>
  <div class="row">Requests served<b>${x.total}</b></div><div class="row">Avg response<b>${x.avg_ms} ms</b></div>
  <div class="track"><div class="fill" style="width:${(x.total/sum*100).toFixed(1)}%;background:${COL[x.id]}"></div></div>
  <div class="row">Share of traffic<b>${(x.total/sum*100).toFixed(1)}%</b></div>
  <button onclick="post('/api/toggle?id=${x.id}')">${x.up?'Simulate crash':'Recover server'}</button></div>`}).join('');
 document.getElementById('log').innerHTML=s.log.map(l=>`${l.client} &rarr; ${l.server} (${l.ms} ms)`).join('<br>');
 const cur=s.servers.map(x=>x.total);
 if(prev){hist.push(cur.map((v,i)=>Math.max(0,v-prev[i])));if(hist.length>60)hist.shift();draw();}
 prev=cur;
}
function draw(){
 const c=document.getElementById('ch'),g=c.getContext('2d'),W=c.width,H=c.height;g.clearRect(0,0,W,H);
 const mx=Math.max(5,...hist.flat());g.strokeStyle='#334155';g.fillStyle='#94a3b8';g.font='11px sans-serif';
 for(let i=0;i<=4;i++){const y=H-20-(H-30)*i/4;g.beginPath();g.moveTo(30,y);g.lineTo(W,y);g.stroke();g.fillText(Math.round(mx*i/4),2,y+4);}
 for(let k=0;k<4;k++){g.strokeStyle=COL[k];g.lineWidth=2;g.beginPath();
  hist.forEach((h,i)=>{const x=30+(W-30)*i/59,y=H-20-(H-30)*h[k]/mx;i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke();}
}
setInterval(tick,1000);tick();
</script></body></html>"""


def main():
    for s in SERVERS:
        srv = ThreadingHTTPServer(("127.0.0.1", s["port"]), make_backend(s))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=health_checker, daemon=True).start()
    print(f"Backends running on ports {[s['port'] for s in SERVERS]}")
    print(f"Load balancer dashboard: http://localhost:{LB_PORT}   (Ctrl+C to stop)")
    try:
        ThreadingHTTPServer(("0.0.0.0", LB_PORT), LB).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
