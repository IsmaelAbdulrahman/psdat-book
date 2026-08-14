# PSDAT for Windows — native, installable, nothing else required

**`PSDAT_Setup.exe`** is a self-contained installer of the complete Python
edition. It needs **no Python, no MATLAB, no admin rights, and no experience**.

*If you received it as two pieces* (`PSDAT_Setup.exe.001` / `.002`, split for
delivery): put both in one folder together with `Make_PSDAT_Setup.bat` and
double-click the `.bat` — it joins them into `PSDAT_Setup.exe` and starts it.

1. Double-click `PSDAT_Setup.exe`.
   *Windows SmartScreen may ask once because the file is new and unsigned —
   click "More info → Run anyway".*
2. Confirm the prompt. PSDAT installs for the current user (under
   `%LOCALAPPDATA%\PSDAT`, ~430 MB), creates **Desktop** and **Start-menu**
   shortcuts (PSDAT, PSDAT Manual, Uninstall PSDAT), registers itself in
   **Apps & features**, and starts.
3. PSDAT opens in its own window (chromeless app window via Edge/Chrome,
   or the default browser otherwise). Close the window and the engine shuts
   itself down; launch again from the Desktop icon.

Everything runs locally and offline: the bundled runtime is CPython 3.12 with
NumPy 2.2.4, SciPy 1.15.2 and Matplotlib 3.10.1 (official builds with their
libraries included), plus the full PSDAT engine, all seven benchmarks,
MATPOWER import, FACTS, the fuzzy stabiliser, and the user manual PDF.

**Portable use (no install):** the setup file *is* a 7-Zip archive — right-click
`PSDAT_Setup.exe` → 7-Zip → "Extract to…", and run `PSDAT\PSDAT.exe` straight
from the extracted folder (USB stick friendly). Same app, no shortcuts, no
registry.

**Uninstall:** Start menu → *Uninstall PSDAT*, or Windows *Apps & features*.
Removes the program, shortcuts and registry entry; your exported results are
kept.

## Why the Python edition (your MATLAB question)

Correct: the MATLAB edition cannot become a free standalone. Running
`PSDAT_App.m` requires a MATLAB licence, and even MATLAB Compiler
deployments require every user to install MathWorks' multi-gigabyte MATLAB
Runtime. The Python edition has no such dependency — its whole runtime
travels inside this installer — which is why the Windows, Android, and
portable builds are all made from it. The MATLAB edition remains ideal for
users who already own MATLAB.

## How this installer is built (for the record / rebuilding)

Assembled on any OS, no Windows needed, from four public pieces:

| piece | source |
|---|---|
| CPython 3.12 for Windows | python-build-standalone (GitHub releases) |
| NumPy / SciPy / Matplotlib win64 + DLLs | WinPython *slim* (GitHub releases) — official PyPI builds |
| `PSDAT.exe` launcher | `windows_build/launcher.c`, cross-compiled with llvm-mingw |
| Setup wrapper | 7-Zip LZMA SDK `7zSD.sfx` + config + LZMA2 payload |

Layout installed: `PSDAT.exe` (native launcher) → `runtime\pythonw.exe
app\boot_psdat.py` → serves the GUI on localhost and opens the app window;
a watchdog exits the engine ~3 min after the window closes. The
`windows_build/` folder in this package carries the launcher source, the
installer scripts (`install.cmd`, `shortcuts.ps1`, `uninstall.cmd`,
`sfxconfig.txt`) and `boot_psdat.py`, so the whole build is reproducible.


## What's new (v2.4.1 feature port from PSDAT Mobile)

The Python edition (`python/psdat_gui.py`, also updated to the newest engine
revision with in/out-of-service switching) now includes everything added to the
mobile app:

- **Night theme** — View ▸ *Night theme (interface only)*: menus, panels,
  tables and dialogs go dark while the diagram workspace keeps its day
  appearance, so the heat map and exports look identical in both themes. The
  choice is remembered.
- **Studies tab reordered** — Optimal PMU Placement → Contingency →
  Short-Circuit → PV Curve (then CCT and Economic dispatch).
- **Heat map & colours** — the voltage-contour On/Off choice now persists
  across runs and launches; View ▸ *Component colours by value* colours buses,
  lines, machines and loads by the selected heat-map variable (with the
  colour-scale legend); diagram labels use adaptive field-coloured halos
  instead of white rings.
- **Projects** — File ▸ *Save project (.psdat)* bundles the diagram,
  parameters, power-flow results and study outputs (written to
  `Desktop/PSDAT_output/`); File ▸ *Open project / diagram…* opens `.psdat`
  projects **and** plain network `.json` files — fully compatible with the
  Android edition, so projects move between phone and PC.
- **SCADA operator mode** (Tools menu) — live telemetry on a 2 s scan with an
  alarm banner under the ribbon, click-any-component *Control & telemetry*
  dialogs with select-before-operate breaker/machine switching, load shedding,
  per-tag trends, an alarms + sequence-of-events console with CSV export,
  **WLS state estimation** with χ²/largest-normalized-residual bad-data
  detection (plus a one-click gross-error classroom experiment), and
  **disturbance drills** with a debrief — drills can be attached to a `.psdat`
  project to give a whole class the same scenario.

The MATLAB edition (`matlab/`) is unchanged; these features live in the web
GUI of the Python edition.
