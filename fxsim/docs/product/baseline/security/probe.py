import os, sys, time, json
S = __import__("tempfile").mkdtemp(prefix="fxsim-baseline-")   # never write beside this file: it lives in the repository
os.environ["FXSIM_DB"] = os.path.join(S, "probe.db")
os.environ["MT5_COMMON_FILES"] = os.path.join(S, "common")
os.makedirs(os.environ["MT5_COMMON_FILES"], exist_ok=True)
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-FAKEKEY-PROBE"
os.environ["OANDA_API_TOKEN"] = "oanda-FAKE-TOKEN"
sys.path.insert(0, "/home/user/claude-code-book-template/fxsim")
import app.server as srv
from app import db
from fastapi.testclient import TestClient
db.init_db()
c = TestClient(srv.app, raise_server_exceptions=False)

print("1. settings repr leaks key:", "sk-ant-FAKEKEY-PROBE" in repr(srv.settings), "| oanda:", "oanda-FAKE-TOKEN" in repr(srv.settings))

srv._DASH_PASS = "s3cret"; srv._DASH_USER = "admin"
for p in ["/", "/live", "/api/live", "/static/live.html", "/static/app.js", "/static/chart.umd.js", "/docs", "/openapi.json", "/redoc"]:
    print("2. no-creds GET", p, c.get(p).status_code)

# brute force: no lockout / rate limit
t = time.time(); codes = set()
for i in range(300):
    codes.add(c.get("/api/config", auth=("admin", f"guess{i}")).status_code)
print("3. 300 wrong guesses ->", codes, f"in {time.time()-t:.2f}s; then right:", c.get("/api/config", auth=("admin", "s3cret")).status_code)

# non-ascii password
srv._DASH_PASS = "ぱすわーど"
import base64
h = {"Authorization": "Basic " + base64.b64encode("admin:ぱすわーど".encode()).decode()}
print("4. non-ascii configured password, correct creds ->", c.get("/api/config", headers=h).status_code)
h = {"Authorization": "Basic " + base64.b64encode("admin:x".encode()).decode()}
print("4b. non-ascii configured password, wrong ascii creds ->", c.get("/api/config", headers=h).status_code)

srv._DASH_PASS = ""
# quick tunnel (method B) has no token env: request arriving with CF headers and no password
r = c.get("/api/live", headers={"Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-For": "203.0.113.9", "Host": "xxxx.trycloudflare.com"})
print("5. no password, request via quick-tunnel headers ->", r.status_code)

# POST content-type (CSRF surface) + path traversal in instrument
r = c.post("/api/backtest", content=json.dumps({"provider": "sample", "bars": 100}), headers={"Content-Type": "text/plain"})
print("6. POST text/plain ->", r.status_code, r.text[:160])
r = c.post("/api/backtest", json={"provider": "csv", "instrument": "../../../../etc/passwd", "bars": 100})
print("7. traversal instrument ->", r.status_code, r.text[:300])
open(os.path.join(S, "common", "steady_bars.csv"), "w").write("time,open,high,low,close\n")
r = c.post("/api/backtest", json={"provider": "csv", "instrument": os.path.join(S, "common", "steady_bars"), "bars": 100})
print("7b. absolute instrument ->", r.status_code, r.text[:300])
r = c.post("/api/backtest", json={"provider": "sample", "bars": "x"})
print("8. bars='x' ->", r.status_code, r.text[:200])
n0 = len(db.list_runs())
for _ in range(3):
    r = c.post("/api/backtest", json={"provider": "sample", "bars": 300})
print("9. 3 backtests -> status", r.status_code, "runs rows", n0, "->", len(db.list_runs()), "db bytes", os.path.getsize(os.environ["FXSIM_DB"]))
r = c.get("/api/live")
print("10. /api/live keys:", sorted(r.json().keys()))
# security headers
r = c.get("/live"); print("11. headers:", dict(r.headers))
