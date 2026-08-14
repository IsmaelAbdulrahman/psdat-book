"""PSDAT Windows boot: start the bundled engine, open the app window,
exit cleanly when the window closes.  No console, no Python knowledge needed.
Run by PSDAT.exe via the bundled runtime's pythonw.exe."""
import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

BASE_PORT = 8642


def alive(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ping', timeout=0.6):
            return True
    except Exception:
        return False


def free_port(p0=BASE_PORT):
    for p in range(p0, p0 + 32):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', p))
            s.close()
            return p
        except OSError:
            s.close()
    return p0


def open_window(url):
    """Prefer a chromeless app window (Edge is on every Windows 10/11);
    fall back to the default browser."""
    profile = os.path.join(os.path.expandvars(r'%LOCALAPPDATA%'), 'PSDAT', 'webprofile')
    for exe in (os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
                os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
                os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
                os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe')):
        if os.path.isfile(exe):
            try:
                subprocess.Popen([exe, f'--app={url}', f'--user-data-dir={profile}',
                                  '--window-size=1500,900',
                                  '--no-first-run', '--no-default-browser-check'])
                return
            except Exception:
                pass
    webbrowser.open(url)


# ---- single instance: if PSDAT is already running, just open its window ----
if alive(BASE_PORT):
    open_window(f'http://127.0.0.1:{BASE_PORT}')
    sys.exit(0)

import psdat_gui as G
from http.server import ThreadingHTTPServer

PORT = free_port()
URL = f'http://127.0.0.1:{PORT}'
srv = ThreadingHTTPServer(('127.0.0.1', PORT), G.H)

# ---- watchdog: the page pings /api/ping while its window is open; when the
# window closes the pings stop and the engine exits by itself. ----
G.LASTREQ[0] = time.time()


def watchdog():
    grace = time.time() + 300           # generous first-launch grace period
    while True:
        time.sleep(10)
        if time.time() < grace:
            continue
        if time.time() - G.LASTREQ[0] > 180:
            os._exit(0)


threading.Thread(target=watchdog, daemon=True).start()
threading.Timer(0.9, lambda: open_window(URL)).start()
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
