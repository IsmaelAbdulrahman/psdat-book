# PSDAT — Power System Dynamic Analysis Toolbox

**A transparent, computational approach to the dynamics of renewable-dominated grids.**

📘 **[Read the book (free PDF)](book/Power-System-Dynamics-of-Renewable-Dominated-Grids.pdf)**  ·  🌐 **[Project site](https://ismaelabdulrahman.github.io/psdat-book/)**  ·  📱 **[Mobile app (free, closed testing)](https://ismaelabdulrahman.github.io/psdat-book/#app)**

---

This repository holds the complete, open toolbox behind the graduate textbook
*Power System Dynamics of Renewable-Dominated Grids: A Transparent, Computational
Approach with PSDAT* — the Python reference implementation, a MATLAB edition with
numerical parity, and the book itself as a free PDF.

The premise is simple: **the equations printed in the book and the code that solves
them are, by construction, the same.** Nothing is hidden behind a compiled solver.
Every model, algorithm and numerical result in the text is reproducible here.

## What's inside

| Folder | Contents |
|---|---|
| [`book/`](book/) | The complete textbook, free PDF — 24 chapters, 5 appendices, worked examples and hands-on labs. |
| [`python/`](python/) | The Python reference implementation: engine, GUI, studies, cases, and Windows packaging scripts. |
| [`matlab/`](matlab/) | The MATLAB edition — same models, same results, verified against the Python engine. |
| [`android/`](android/) | Notes on **PSDAT Mobile**, the free companion app. |
| [`docs/`](docs/) | Source of the project website. |

## The book

*Power System Dynamics of Renewable-Dominated Grids* is a graduate textbook and
research reference built around this toolbox. It runs from the algebraic network
and the synchronous machine, through excitation, governors and fuzzy control, into
inverter-based resources — grid-following and grid-forming converters, PV, wind,
storage — and then into transient, small-signal, voltage and frequency stability,
FACTS, damping control, PMUs, security and economics.

**[⬇ Download the PDF](book/Power-System-Dynamics-of-Renewable-Dominated-Grids.pdf)**

Structure: 7 parts · 24 chapters · appendices covering the PSDAT reference, test-system
data, mathematical background, worked solutions and a glossary. Each chapter opens with
learning objectives and closes with problems; worked examples and PSDAT laboratories are
indexed in their own front-matter lists.

## Desktop software

### Python

```bash
git clone https://github.com/ismaelabdulrahman/psdat-book.git
cd psdat-book/python
pip install -r requirements.txt
python psdat_gui.py
```

On Windows you can instead double-click `Run PSDAT.bat`. See
[`python/WINDOWS.md`](python/WINDOWS.md) for the portable, zero-install build.

Requires Python 3.9 or newer. Core dependencies are NumPy, SciPy and Matplotlib;
the desktop window uses a Qt binding (PyQt5 / PySide6) when one is available and
falls back to your browser otherwise.

Also included:

- `PSDAT_MAIN.ipynb` — the toolbox driven from a notebook.
- `psdat_tour.ipynb` — a short guided tour.
- `test_parity.py`, `test_units.py`, `test_design.py` — the parity and unit tests.
- Bundled MATPOWER-format cases: IEEE 9, 14, 30, 39, 57, 118 and 300-bus, plus the
  Kundur two-area and 16-machine 68-bus systems.

### MATLAB

Add [`matlab/`](matlab/) to your MATLAB path and run:

```matlab
PSDAT_App        % the graphical application
PSDAT_Demo       % a scripted demonstration
PSDAT_SelfTest   % verify the installation
PSDAT_Parity     % check numerical parity against the Python engine
```

MATPOWER is optional. `PSDAT_BuildSimulink` and `PSDAT_RunSimulink` generate and run
an equivalent Simulink model where Simulink is available.

## PSDAT Mobile

The same engine runs on Android — interactive single-line diagram, power flow with a
live heat map, transient and small-signal studies, a photovoltaic laboratory, a guided
theory section, and a supervisory SCADA mode with state estimation. It works fully
offline once installed, in night or day theme.

The app is **free** and currently in **closed testing** on Google Play.
See [`android/README.md`](android/README.md) or the
[project site](https://ismaelabdulrahman.github.io/psdat-book/#app) for how to join the
tester list.

## Citation

If you use PSDAT or the book in academic work, please cite:

```bibtex
@article{abdulrahman2020psdat,
  author  = {Abdulrahman, Ismael},
  title   = {{MATLAB}-Based Programs for Power System Dynamic Analysis},
  journal = {IEEE Open Access Journal of Power and Energy},
  volume  = {7},
  pages   = {59--69},
  year    = {2020},
  doi     = {10.1109/OAJPE.2019.2954205}
}

@book{abdulrahman2026psdatbook,
  author    = {Abdulrahman, Ismael Khorshed},
  title     = {Power System Dynamics of Renewable-Dominated Grids:
               A Transparent, Computational Approach with PSDAT},
  edition   = {First},
  year      = {2026},
  publisher = {Self-published},
  url       = {https://ismaelabdulrahman.github.io/psdat-book/}
}
```

See also [`CITATION.cff`](CITATION.cff).

## License

- **Code** (`python/`, `matlab/`, `docs/`) — [MIT](LICENSE). Use, adapt and
  redistribute freely, including commercially, with attribution.
- **Book and written content** (`book/`) — © 2026 Ismael Khorshed Abdulrahman,
  **all rights reserved**. Free to read and download for personal, educational
  and research use; redistribution or derivative versions require prior written
  permission. See [LICENSE-CONTENT](LICENSE-CONTENT).

## Author

**Dr. Ismael Khorshed Abdulrahman**
Department of Technical Information Systems Engineering,
Erbil Technical Engineering College, Erbil Polytechnic University,
Erbil 44001, Kurdistan Region, Iraq
· `ismael.abdulrahman@epu.edu.iq`

Ph.D. in Electrical and Computer Engineering, Tennessee Technological University, USA (2019).

## Contributing

Corrections to the models, the code or the book are welcome — please open an issue
describing what you found, with the chapter or file it relates to.
