#!/usr/bin/env python3
"""
PSDAT Desktop — open the full Interactive Lab as a standalone application
window (no address bar, no tabs; looks and behaves like a desktop program).

    python PSDAT_Desktop.py        (or double-click it)

Nothing here touches the internet: the lab is served by YOUR Python on
127.0.0.1 (this computer only) and rendered by the display engine already
installed with your operating system (Edge on Windows, Safari/Chrome on
macOS, Chromium/Firefox on Linux). Works with the network cable unplugged.

To turn this into a single-file PSDAT.exe that runs on ANY Windows PC
with nothing installed (no Python, no MATLAB), run PSDAT_MakeApp.bat once.
"""
import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser

if sys.stdout is None:                     # console-less runs (pythonw / the
    sys.stdout = open(os.devnull, 'w')     # packaged PSDAT.exe): keep every
if sys.stderr is None:                     # print() safe
    sys.stderr = open(os.devnull, 'w')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import psdat_gui as G


def free_port(start=8642):
    for p in range(start, start + 60):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    return start


PSDAT_ICON_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
                   "<rect width='64' height='64' rx='12' fill='#1f3b73'/>"
                   "<circle cx='32' cy='20' r='10' fill='none' stroke='#fff' stroke-width='4.5'/>"
                   "<line x1='32' y1='30' x2='32' y2='40' stroke='#fff' stroke-width='4.5'/>"
                   "<rect x='12' y='40' width='40' height='8' rx='2' fill='#fff'/></svg>")


def _qt_binding():
    """Import a Qt binding with its WebEngine. Returns (name, modules) or
    (None, reasons)."""
    reasons = []
    try:                                    # newest first: PySide6 bundles
        from PySide6.QtCore import Qt as QtC, QUrl                    # noqa
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtWebEngineWidgets import QWebEngineView
        return 'PySide6', (QtC, QUrl, QIcon, QApplication, QMainWindow, QWebEngineView)
    except Exception as e:
        reasons.append(f'PySide6: {e}')
    try:
        from PySide2.QtCore import Qt as QtC, QUrl                    # noqa
        from PySide2.QtGui import QIcon
        from PySide2.QtWidgets import QApplication, QMainWindow
        from PySide2.QtWebEngineWidgets import QWebEngineView
        return 'PySide2', (QtC, QUrl, QIcon, QApplication, QMainWindow, QWebEngineView)
    except Exception as e:
        reasons.append(f'PySide2: {e}')
    try:
        from PyQt5.QtCore import Qt as QtC, QUrl                      # noqa
        from PyQt5.QtGui import QIcon
        from PyQt5.QtWidgets import QApplication, QMainWindow
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        return 'PyQt5', (QtC, QUrl, QIcon, QApplication, QMainWindow, QWebEngineView)
    except Exception as e:
        reasons.append(f'PyQt5(+PyQtWebEngine): {e}')
    return None, reasons


def _qt_self_install():
    """One-time setup of the native-window component. `pip install PySide2`
    has no packages for Python >= 3.11 and PyQt5 alone lacks the window
    engine (PyQtWebEngine) — so if no binding imports, install PySide6
    (which bundles everything) into THIS Python. Needs internet once.
    Returns True if an install was attempted and succeeded."""
    if getattr(sys, 'frozen', False):
        return False
    print('  native window component not found — one-time setup:')
    print('  installing PySide6 into this Python (needs internet once) ...')
    if os.name == 'nt':                     # visible cue when there is no console
        try:
            import ctypes
            threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(
                0, 'PSDAT one-time setup: installing the native window '
                   'component (PySide6).\nThe app opens automatically in '
                   'about a minute — you can close this message.',
                'PSDAT', 0x40), daemon=True).start()
        except Exception:
            pass
    try:
        flags = 0x08000000 if os.name == 'nt' else 0   # no console flash
        r = subprocess.run([sys.executable, '-m', 'pip', 'install',
                            '--quiet', 'PySide6'], timeout=600,
                           creationflags=flags)
        return r.returncode == 0
    except TypeError:                       # creationflags not supported
        r = subprocess.run([sys.executable, '-m', 'pip', 'install',
                            '--quiet', 'PySide6'], timeout=600)
        return r.returncode == 0
    except Exception as e:
        print(f'  install failed: {e}')
        return False


def qt_window(url):
    """TRUE native desktop window (Qt): own frame, own taskbar icon, its own
    process — no browser involved at all. Self-installs PySide6 on first run
    if no Qt binding is present."""
    name, mods = _qt_binding()
    if name is None:
        for r in mods:
            print('  ' + r)
        if _qt_self_install():
            name, mods = _qt_binding()
    if name is None:
        print('  no native window available — using the app-window fallback.')
        print('  To get the fully native window, run once:  pip install PySide6')
        return False
    QtC, QUrl, QIcon, QApplication, QMainWindow, QWebEngineView = mods
    if os.name == 'nt':                     # own taskbar identity on Windows
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('EPU.PSDAT')
        except Exception:
            pass
    elif hasattr(os, 'geteuid') and os.geteuid() == 0:
        os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS',
                              '--no-sandbox --disable-gpu')
    print(f'  opening native window via {name} QtWebEngine ...')
    try:
        QApplication.setAttribute(QtC.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(QtC.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    app = QApplication(sys.argv[:1] or ['PSDAT'])
    app.setApplicationName('PSDAT')
    app.setApplicationDisplayName('PSDAT')
    icon = None
    try:                                    # window / taskbar icon from the SVG
        import tempfile
        icf = os.path.join(tempfile.gettempdir(), 'psdat_icon.svg')
        with open(icf, 'w') as f:
            f.write(PSDAT_ICON_SVG)
        icon = QIcon(icf)
        app.setWindowIcon(icon)
    except Exception:
        pass
    win = QMainWindow()
    win.setWindowTitle('PSDAT — Power System Dynamics Analysis Toolbox')
    if icon is not None:
        win.setWindowIcon(icon)
    view = QWebEngineView(win)
    win.setCentralWidget(view)
    try:                                    # let the lab's F11 full-screen
        st = view.settings()                # editing mode drive the window
        attr = None
        for holder in (st, getattr(st, 'WebAttribute', None)):
            attr = getattr(holder, 'FullScreenSupportEnabled', attr)
        if attr is not None:
            st.setAttribute(attr, True)

        def _fs(req):
            try:
                req.accept()
                if req.toggleOn():
                    win.showFullScreen()
                else:
                    win.showNormal()
            except Exception:
                pass
        view.page().fullScreenRequested.connect(_fs)
    except Exception:
        pass
    view.load(QUrl(url))
    win.resize(1460, 920)
    win.show()
    if hasattr(app, 'exec'):                # Qt6 removed exec_()
        app.exec()
    else:
        app.exec_()                         # returns when the window is closed
    return True


def app_browser():
    """Find a browser that supports --app= application windows."""
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    lad = os.environ.get('LocalAppData', '')
    cands = [
        os.path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(lad, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
        '/usr/bin/microsoft-edge',
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def watchdog(srv):
    """Shut the engine down only after a LONG idle with no contact from the
    window, so a closed app doesn't leave an orphan server — but a merely
    minimised / backgrounded window (whose heartbeat the browser throttles)
    is never killed under the user. 20 min is well beyond any timer throttling."""
    while True:
        time.sleep(15)
        if time.time() - G.LASTREQ[0] > 1200:
            try:
                srv.shutdown()
            finally:
                os._exit(0)


def main():
    port = free_port()
    srv = G.ThreadingHTTPServer(('127.0.0.1', port), G.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    time.sleep(0.4)
    url = f'http://127.0.0.1:{port}'
    print('PSDAT Desktop')
    print(f'  engine running locally at {url}  (this computer only — no internet used)')
    if qt_window(url):                      # native Qt window (PySide2 / PyQt5)
        srv.shutdown()
        return
    br = app_browser()
    if br:
        print(f'  opening application window via {os.path.basename(br)} ...')
        proc = subprocess.Popen([br, f'--app={url}', '--window-size=1440,900'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        # if the browser was already running, the launcher returns at once;
        # keep serving (the idle watchdog exits when the window closes)
        print('  window handed over. Close this console (or Ctrl+C) to stop the engine.')
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        print('  no app-mode browser found — opening in the default browser instead.')
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    srv.shutdown()


if __name__ == '__main__':
    main()
