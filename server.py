"""Cloud Run entry point: POST /price {"sheet": "<id or url>", "token": "<PRICER_TOKEN>"} starts a pricing run and returns at once;
the run writes progress and results into the sheet. GET / is a health check.

Deploy with the Dockerfile. Settings that matter: CPU always allocated (the run continues after the response), max instances 1,
env var PRICER_TOKEN, and a service account that the sheet is shared with."""
import json, os, threading, datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import price_sheet

TOKEN = os.environ.get("PRICER_TOKEN", "")
LOCK = threading.Lock()


def job(sheet):
    try:
        sh = price_sheet.open_sheet(sheet)
        price_sheet.run_job(sh, "Cloud Run " + dt.datetime.now().strftime("%H:%M:%S"))
    except Exception as e:                       # noqa
        print("job failed:", e, flush=True)
    finally:
        LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, text):
        body = text.encode(); self.send_response(code); self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._reply(200, "lobo pricer ok" if not LOCK.locked() else "lobo pricer busy")

    def do_POST(self):
        if self.path.rstrip("/") != "/price": return self._reply(404, "not found")
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except ValueError:
            return self._reply(400, "bad json")
        if not TOKEN or data.get("token") != TOKEN: return self._reply(403, "bad token")
        if not data.get("sheet"): return self._reply(400, "sheet missing")
        if not LOCK.acquire(blocking=False): return self._reply(409, "a run is already in progress")
        threading.Thread(target=job, args=(data["sheet"],), daemon=True).start()
        self._reply(202, "started")

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("listening on", port, "token set" if TOKEN else "WARNING: PRICER_TOKEN not set, every request will be refused", flush=True)
    ThreadingHTTPServer(("", port), Handler).serve_forever()
