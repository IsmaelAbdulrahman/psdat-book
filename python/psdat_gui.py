#!/usr/bin/env python3
"""
PSDAT Interactive Lab — browser GUI for the PSDAT toolbox.

    python3 psdat_gui.py            # then open http://localhost:8642
    python3 psdat_gui.py 8080       # custom port

No dependencies beyond the toolbox itself (numpy); the interface is served
by the Python standard library and rendered with hand-drawn SVG charts, so
it works offline in any classroom.  Close the terminal to stop the server.
"""
import json
import io
import os
import math
import sys
import base64
import time
import threading
import contextlib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
try:
    import cases
    import units as UN
    import facts
    import design as DS
    from system import System
    from linearize import linearize, modes
    from simulate import simulate, cloud_profile, gust_profile
except ModuleNotFoundError as _e:
    raise ModuleNotFoundError(
        str(_e) + " — psdat_gui.py is part of the PSDAT python folder and "
        "must stay together with cases.py, units.py, system.py, linearize.py, "
        "simulate.py, design.py, studies.py, figstyle.py and the case files "
        "(IEEE9Bus.m, case68_16m.m). Copy or run the WHOLE folder, not single "
        "files.") from _e

UNIT_TYPES = ['SG', 'SGP', 'SGF', 'SG6G', 'SG6', 'SG6P', 'SG4G', 'SG4', 'SG2',
              'GFM', 'GFL', 'PV-GFL',
              'PV-GFM', 'BESS-GFM', 'BESS-GFL', 'WT4-GFL', 'WT4-GFM', 'WT3', 'WT1', 'WT2']
UNIT_INFO = {
    'SG': 'Synchronous generator — full: 2-axis sub-transient machine + exciter (AVR) + governor (11 states)',
    'SGP': 'SG full + power-system stabiliser (PSS): washout + 2-stage lead-lag on Δω into the AVR [Sauer&Pai ch.8; IEEE PSS1A] (14 states)',
    'SGF': 'SG full + FUZZY-LOGIC stabiliser (intelligent control): 25-rule Sugeno inference on washed Δω and its derivative — a nonlinear gain-scheduled PD surface into the AVR; linear near the operating point, saturating for large swings [Hsu&Cheng 1990; El-Metwally&Malik 1995] (13 states)',
    'SG6G': 'SG reduced — one-axis flux-decay + AVR + governor [Sauer&Pai] (8 states)',
    'SG6': 'SG reduced — one-axis flux-decay + AVR exciter, NO governor (constant Pm) (6 states)',
    'SG6P': 'SG one-axis + AVR + PSS — the classic Heffron-Phillips damping demo (add PSS damping to a high-gain exciter) (9 states)',
    'SG4G': 'SG reduced — two-axis + governor, NO exciter (constant Efd) (6 states)',
    'SG4': 'SG reduced — two-axis, NO exciter, NO governor (constant Efd & Pm) [Sauer&Pai 6.3] (4 states)',
    'SG2': 'SG reduced — classical constant-E′ swing model, no exciter/governor [Sauer&Pai 6.4] (2 states: δ, ω)',
    'GFM': 'Grid-forming converter: droop/virtual-synchronous-machine, ideal DC source (3)',
    'GFL': 'Grid-following converter: PLL + current control, ideal DC source; optional IEEE 1547-2018 grid support — Volt-VAR / const-PF (qmode), Volt-Watt (Kvw), Freq-Watt (Kfw) (4)',
    'PV-GFL': 'PV plant: single-diode array + DC-link + MPPT (Vmp tracking) behind GFL; optional IEEE 1547-2018 grid support — Volt-VAR / const-PF (qmode), and Volt-Watt/Freq-Watt via MPPT curtailment (Kvw/Kfw) (7)',
    'PV-GFM': 'Curtailed PV with headroom behind a grid-forming converter (4)',
    'BESS-GFM': 'Battery: state of charge + capability window behind GFM — virtual inertia (4)',
    'BESS-GFL': 'Battery behind GFL with fast frequency response (droop + RoCoF, deadband); optional IEEE 1547-2018 Volt-VAR / const-PF (qmode) + Volt-Watt (Kvw) (7)',
    'WT4-GFL': 'Type-4 wind: Cp(λ,β) aero, 2-mass shaft, pitch, MPPT behind GFL (+synthetic inertia) (12)',
    'WT4-GFM': 'Type-4 wind behind a grid-forming converter — rotor supplies real inertia (9)',
    'WT3': 'Type-3 DFIG: 3rd-order induction machine + vector-controlled rotor converter (10)',
    'WT1': 'Type-1 fixed-speed induction generator + shunt compensation (5)',
    'WT2': 'Type-2: Type-1 + controlled external rotor resistance (6)',
}
SYSTEMS = {'IEEE9': 'IEEE 9-bus (3 machines)',
           'IEEE14': 'IEEE 14-bus (5 machines)',
           'IEEE30': 'IEEE 30-bus (6 machines)',
           'IEEE39': 'New England 39-bus (10 machines)',
           'IEEE57': 'IEEE 57-bus (7 machines)',
           'Kundur2A': 'Kundur two-area (4 machines)',
           'NE68': '68-bus NETS-NYPS (16 machines)'}
PRESETS = {
    'IEEE9': {'All SG': ['SG'] * 3, '78% GFL': ['SG', 'GFL', 'GFL'],
              '78% GFM': ['SG', 'GFM', 'GFM'],
              'RES mix': ['BESS-GFM', 'WT4-GFL', 'PV-GFL']},
    'IEEE14': {'All SG': ['SG'] * 5, '40% GFM': ['SG', 'GFM', 'SG', 'GFM', 'SG']},
    'IEEE30': {'All SG': ['SG'] * 6, '50% GFM': ['SG', 'GFM', 'SG', 'GFM', 'SG', 'GFM']},
    'IEEE57': {'All SG': ['SG'] * 7, 'RES mix': ['SG', 'GFM', 'GFL', 'SG', 'PV-GFL', 'WT4-GFM', 'SG']},
    'Kundur2A': {'All SG': ['SG'] * 4, 'GFL @ G2,G4': ['SG', 'GFL', 'SG', 'GFL'],
                 'GFM @ G2,G4': ['SG', 'GFM', 'SG', 'GFM'],
                 'BESS @ G2': ['SG', 'BESS-GFM', 'SG', 'SG']},
    'NE68': {'All SG': ['SG'] * 16,
             'NETS 8x GFM-RES': ['BESS-GFM', 'WT4-GFM'] * 4 + ['SG'] * 8,
             'NETS 8x GFL-RES': ['PV-GFL', 'WT4-GFL'] * 4 + ['SG'] * 8},
}
SCEN_INFO = {
    'validate': 'Base-case validation table across the three systems (fast)',
    'pv_cloud': 'Cloud transient over a PV plant: GFL vs curtailed GFM (~1 min)',
    'wind_types': 'The SAME gust on Type-1 / Type-3 / Type-4 turbines (~2 min)',
    'bess_inertia': 'GFM battery: virtual-inertia sweep + SOC-depletion collapse (~2 min)',
    'ffr': 'Battery fast-frequency response: droop-gain sweep (~2 min)',
    'pod': 'Damp the Kundur inter-area mode from a battery (POD design) (fast)',
    'penetration': 'GFL vs GFM displacement routes on the 9-bus (fast)',
    'syn_inertia': 'Type-4 synthetic inertia and its recovery dip (~1.5 min)',
    'mix68': '68-bus wind/PV/BESS displacement, modal comparison (~1 min)',
}


def make_case(name):
    return {'IEEE9': cases.ieee9, 'IEEE14': cases.ieee14, 'IEEE30': cases.ieee30,
            'IEEE39': cases.ieee39, 'IEEE57': cases.ieee57,
            'Kundur2A': cases.kundur2a, 'NE68': cases.ne68}[name]()


# ---------------------------------------------------- parameter catalogue
SG_PARAMS = ['H', 'Xd', 'Xdp', 'Xdpp', 'Xq', 'Xqp', 'Xqpp', 'Td0p', 'Td0pp',
             'Tq0p', 'Tq0pp', 'Rs', 'Xls', 'Dm', 'KA', 'TA', 'KE', 'TE',
             'KF', 'TF', 'Ax', 'Bx', 'TCH', 'TSV', 'RD']
PDESC = {
    # synchronous machine
    'H': 'inertia constant (s, machine base)', 'Xd': 'd-axis synchronous reactance (pu)',
    'Xdp': "d-axis transient reactance X'd", 'Xdpp': "d-axis sub-transient X''d",
    'Xq': 'q-axis synchronous reactance', 'Xqp': "q-axis transient X'q",
    'Xqpp': "q-axis sub-transient X''q", 'Td0p': "T'do open-circuit time constant (s)",
    'Td0pp': "T''do (s)", 'Tq0p': "T'qo (s)", 'Tq0pp': "T''qo (s)",
    'Rs': 'stator resistance (pu)', 'Xls': 'stator leakage reactance (pu)',
    'Dm': 'mechanical damping coefficient', 'KA': 'exciter (AVR) gain',
    'TA': 'exciter time constant (s)', 'KE': 'exciter constant',
    'TE': 'exciter field time constant (s)', 'KF': 'stabiliser gain',
    'TF': 'stabiliser time constant (s)', 'Ax': 'saturation coefficient A',
    'Bx': 'saturation coefficient B', 'TCH': 'steam-chest time constant (s)',
    'TSV': 'governor valve time constant (s)', 'RD': 'governor droop (pu)',
    'Srating': 'machine MVA rating (pu of 100 MVA; sets inertia weighting)',
    # converters
    'Hv': 'GFM virtual inertia constant (s)', 'Dp': 'GFM damping / P-droop gain',
    'wc': 'reactive-power filter cutoff (rad/s)', 'mq': 'reactive droop gain',
    'Rc': 'coupling resistance (pu)', 'Xc': 'coupling reactance (pu)',
    'Kp': 'PLL proportional gain', 'Ki': 'PLL integral gain',
    'Ti': 'current-loop time constant (s)',
    'Imax': 'current limit (pu of unit rating)', 'Sconv': 'converter MVA (blank = dispatch)',
    # PV
    'voc': 'array open-circuit voltage (pu of Vmp)', 'isc': 'array short-circuit current (pu of Imp)',
    'Cdc': 'DC-link capacitor constant (plant pu-s)', 'Kpdc': 'DC-voltage PI: proportional',
    'Kidc': 'DC-voltage PI: integral', 'Tm': 'MPPT tracking lag (s)',
    'G0': 'initial irradiance (pu of 1000 W/m2)', 'curt': 'curtailment headroom fraction (PV-GFM)',
    'Tav': 'available-power measurement lag (s)',
    'qmode': 'reactive control mode: 0 = constant-Q · 1 = Volt-VAR · 2 = constant power factor [IEEE 1547-2018]',
    'Kqv': 'Volt-VAR droop gain (pu reactive per pu voltage; needs qmode=1) [IEEE 1547-2018 Table 8]',
    'Vdb': 'Volt-VAR voltage deadband half-width (pu; 0 = no deadband)',
    'Qmax': 'reactive-power capability limit (pu of unit rating)',
    'Kvw': 'Volt-Watt droop gain (pu active per pu voltage; curtails on over-voltage) [IEEE 1547-2018 §5.14.6]',
    'Vvw': 'Volt-Watt voltage threshold (pu; active-power curtailment begins above this)',
    'Kfw': 'Frequency-Watt droop gain (pu active per pu frequency) [IEEE 1547-2018 §6.4]',
    'fdb': 'Frequency-Watt frequency deadband half-width (pu; 0 = no deadband)',
    # battery
    'Eh': 'storage duration at rated power (h)', 'eta': 'one-way efficiency',
    'SOC0': 'initial state of charge (0..1)', 'SOCmin': 'minimum usable SOC',
    'SOCmax': 'maximum usable SOC', 'dSOC': 'capability-fade width near limits',
    'Pmax': 'power rating (pu; blank = 1.5x dispatch)',
    'Kf': 'FFR droop gain (pu P per pu f)', 'db': 'FFR deadband (pu frequency)',
    'Tf': 'FFR delivery lag (s)', 'Tw': 'RoCoF washout time constant (s)',
    'Kr': 'RoCoF response gain (0 = off)',
    # wind
    'Ht': 'turbine inertia constant (s)', 'Hg': 'generator inertia constant (s)',
    'Ksh': 'shaft stiffness (pu torque/el.rad)', 'Dsh': 'shaft damping',
    'lam_r': 'optimal tip-speed ratio', 'Cpmax': 'maximum power coefficient',
    'c': 'Cp(lambda,beta) coefficients c1..c6 (comma list)',
    'Kpp': 'pitch PI proportional (deg per pu speed)', 'Kip': 'pitch PI integral',
    'Tp': 'pitch actuator lag (s)', 'bmax': 'maximum pitch angle (deg)',
    'TPo': 'MPPT power-order lag (s)', 'vw0': 'initial wind speed (pu of rated)',
    'kopt': 'MPPT constant: P* = kopt*w^3',
    'syn_in': 'synthetic inertia on/off (WT4-GFL)', 'Ksi': 'synthetic-inertia gain',
    'Tsi': 'synthetic-inertia washout (s)',
    'Xm': 'magnetising reactance (pu, machine base)', 'Xlr': 'rotor leakage reactance',
    'Rr': 'rotor resistance', 'KpT': 'rotor P/torque loop: proportional',
    'KiT': 'rotor P/torque loop: integral', 'KpV': 'rotor Q loop: proportional',
    'KiV': 'rotor Q loop: integral', 'Smach': 'machine MVA (pu; blank = dispatch/0.9)',
    'Rext_max': 'max external rotor resistance (pu)', 'KpR': 'rotor-R PI proportional',
    'KiR': 'rotor-R PI integral',
}
TYPE_DEFS = {
    'GFM': lambda: dict(UN.GFM_DEF), 'GFL': lambda: {**UN.GFL_DEF, **UN.GS_DEF},
    'PV-GFL': lambda: {**UN.GFL_DEF, **UN.PV_DEF, **UN.GS_DEF},
    'PV-GFM': lambda: {**UN.GFM_DEF, **UN.PV_DEF},
    'BESS-GFM': lambda: {**UN.GFM_DEF, **UN.BESS_DEF},
    'BESS-GFL': lambda: {**UN.GFL_DEF, **UN.BESS_DEF},
    'WT4-GFL': lambda: {**UN.GFL_DEF, **UN.WT4_DEF},
    'WT4-GFM': lambda: {**UN.GFM_DEF, **UN.WT4_DEF},
    'WT3': lambda: dict(UN.WT3_DEF), 'WT1': lambda: dict(UN.WT1_DEF),
    'WT2': lambda: dict(UN.WT2_DEF),
}


def api_params(req):
    """Parameter catalogue for unit k of the chosen mix: names, effective
    default values (Kundur auto-scaling included), and descriptions.
    Works for built-in systems and for diagram networks."""
    k = int(req['k'])
    if req.get('net'):
        case = net_to_case(req['net'])
        mix = [g['tag'] for g in req['net']['gens']]
        sysname = None
    else:
        sysname, mix = req['system'], req['mix']
        case = make_case(sysname)
    tag = mix[k]
    out = []
    if tag.startswith('SG'):               # SG, SG6, SG4, SG2 share the machine params
        i = int(case.gen_bus[k]) - 1
        for nm in SG_PARAMS:
            out.append(dict(name=nm, value=float(case.machine[nm][i]),
                            desc=PDESC.get(nm, ''), kind='num'))
        out.append(dict(name='Srating', value=float(case.Sbase_gen[k]),
                        desc=PDESC['Srating'], kind='num'))
        if tag in ('SGP', 'SG6P'):         # power-system-stabiliser gains
            import units as _U
            ov = (req.get('prm') or {}).get(str(k)) or \
                 (req.get('prm') or {}).get(k) or {}
            pss = _U._pss_params(ov)       # effective (default or overridden)
            for nm, dsc in (('Kpss', 'PSS gain on Δω speed signal (0 disables the stabiliser)'),
                            ('Tw', 'PSS washout time constant (s) — blocks steady-state bias'),
                            ('T1', 'PSS lead time constant (s) — phase advance'),
                            ('T2', 'PSS lag time constant (s) — the /( ) of each lead-lag stage')):
                out.append(dict(name=nm, value=float(pss[nm]), desc=dsc, kind='num'))
        if tag == 'SGF':                   # fuzzy-logic stabiliser scales
            import units as _U
            ov = (req.get('prm') or {}).get(str(k)) or \
                 (req.get('prm') or {}).get(k) or {}
            fz = _U._fz_params(ov)         # effective (default or overridden)
            for nm, dsc in (('Ke', 'fuzzy input scale on washed Δω — maps ±1/Ke pu speed deviation onto the full NB…PB universe'),
                            ('Kde', 'fuzzy input scale on dΔω/dt (acceleration channel — sets the phase-lead, like a PD derivative gain)'),
                            ('Ku', 'output gain: stabilising signal = Ku × fuzzy surface, clipped at ±0.12 pu into the AVR'),
                            ('Tw', 'washout time constant (s) — blocks steady-state bias'),
                            ('Td', 'derivative-filter time constant (s) — realizable s/(1+sTd)')):
                out.append(dict(name=nm, value=float(fz[nm]), desc=dsc, kind='num'))
    else:
        p = TYPE_DEFS[tag]()
        if sysname == 'Kundur2A':          # effective (auto-scaled) defaults
            if 'GFM' in tag:
                p.update(cases.GFM_K)
            if 'GFL' in tag:
                p.update(cases.GFL_K)
        for nm, v in p.items():
            if nm == 'c':
                out.append(dict(name='c', value=','.join(str(x) for x in v),
                                desc=PDESC['c'], kind='text'))
            elif nm == 'syn_in':
                out.append(dict(name=nm, value=bool(v), desc=PDESC[nm], kind='bool'))
            elif v is None:
                out.append(dict(name=nm, value='', desc=PDESC.get(nm, ''), kind='text'))
            else:
                out.append(dict(name=nm, value=float(v), desc=PDESC.get(nm, ''), kind='num'))
    return dict(tag=tag, params=out)


def api_paramsall(req):
    """Every unit's parameter catalogue in ONE call — feeds the Data tab
    (parameters & input data) on the right-hand side."""
    m = len(req['net']['gens']) if req.get('net') else \
        len(make_case(req['system']).gen_bus)
    return dict(units=[api_params(dict(req, k=k)) for k in range(m)])


# ------------------------------------------------ single-line diagrams ---
IEEE9_XY = [[300, 540], [80, 120], [520, 120], [300, 440], [170, 360],
            [430, 360], [170, 210], [300, 130], [430, 210]]
KUNDUR_XY = [[90, 250], [270, 430], [810, 250], [630, 430], [180, 250],
             [270, 250], [360, 250], [450, 250], [540, 250], [630, 250],
             [720, 250]]
N68_XY = [[550, 358], [691, 139], [852, 182], [885, 440], [960, 491], [849, 593], [766, 620], [588, 501], [493, 592], [378, 367], [368, 298], [422, 135], [367, 60], [126, 436], [60, 369], [70, 280], [351, 103], [114, 289], [859, 465], [920, 484], [806, 513], [818, 566], [773, 580], [761, 523], [561, 469], [527, 494], [547, 436], [492, 521], [504, 546], [441, 302], [405, 338], [393, 271], [343, 247], [333, 188], [266, 161], [391, 164], [664, 446], [323, 300], [204, 97], [218, 428], [149, 407], [109, 355], [299, 81], [240, 93], [213, 133], [244, 298], [373, 417], [288, 434], [179, 294], [130, 223], [159, 174], [654, 401], [465, 382], [551, 390], [630, 361], [679, 299], [648, 233], [686, 185], [626, 183], [581, 210], [475, 220], [806, 204], [750, 182], [765, 218], [783, 250], [749, 316], [769, 387], [772, 467]]
LAYOUTS = {'IEEE9': IEEE9_XY, 'Kundur2A': KUNDUR_XY, 'NE68': N68_XY}


def auto_layout(n, branch):
    """Deterministic force-directed (Fruchterman-Reingold) layout for systems
    that ship without a hand-drawn schematic (IEEE 14/30/57).  The user can
    refine it from the Layout menu, exactly as in the MATLAB edition."""
    if n <= 1:
        return [[400.0, 400.0]] * max(n, 1)
    th = np.arange(n) * 2 * np.pi / n
    r0 = 4.0 * np.sqrt(n)
    XY = np.c_[r0 * np.cos(th), r0 * np.sin(th)]           # circular seed
    ed = branch[:, :2].astype(int) - 1
    ed = ed[(ed[:, 0] >= 0) & (ed[:, 1] >= 0) & (ed[:, 0] < n) & (ed[:, 1] < n)]
    k = 1.3 * r0 / np.sqrt(n)
    for it in range(300):
        D = np.zeros((n, 2))
        for i in range(n):                                # repulsion (all pairs)
            d = XY[i] - XY
            d2 = (d * d).sum(1); d2[i] = np.inf; d2 = np.maximum(d2, 0.01)
            D[i] += (d * (k * k / d2)[:, None]).sum(0)
        for a, b in ed:                                   # attraction (edges)
            d = XY[a] - XY[b]; dd = max(float(np.hypot(*d)), 0.01)
            D[a] -= d * (dd / k); D[b] += d * (dd / k)
        temp = r0 * 0.15 * (1 - it / 300) + 0.5           # cooling
        dl = np.hypot(D[:, 0], D[:, 1]); dl = np.maximum(dl, 0.01)
        XY = XY + D / dl[:, None] * np.minimum(dl, temp)[:, None]
    XY -= XY.min(0)
    XY *= 720.0 / max(float(XY.max()), 1.0)
    XY += 60.0
    return [[round(float(x), 1), round(float(y), 1)] for x, y in XY]


def default_md(S):
    """Typical round-number synchronous machine (rating S MVA) converted to
    the 100-MVA system base — for machines ADDED in the diagram editor."""
    k = S / 100.0
    return dict(H=5.0 * k, Xd=1.8 / k, Xdp=0.30 / k, Xdpp=0.25 / k,
                Xq=1.7 / k, Xqp=0.55 / k, Xqpp=0.25 / k, Td0p=8.0,
                Td0pp=0.03, Tq0p=0.4, Tq0pp=0.05, Rs=0.0025 / k,
                Xls=0.2 / k, Dm=0.0, KA=20.0, TA=0.2, KE=1.0, TE=0.314,
                KF=0.063, TF=0.35, Ax=0.0039, Bx=1.555, TCH=0.1, TSV=0.05,
                RD=0.05)


def net_to_case(net):
    """Build a Case from a diagram-editor network description."""
    buses = net['buses']
    gens = net['gens']
    brs = net['branches']
    n = len(buses)
    m = len(gens)
    if m == 0:
        raise ValueError('the network needs at least one generator')
    if n == 0:
        raise ValueError('the network needs at least one bus')
    if not brs and n > 1:
        raise ValueError('connect the buses with lines first')
    tmap = {'slack': 3, 'pv': 2, 'pq': 1}
    bt = np.array([tmap.get(b.get('type', 'pq'), 1) for b in buses])
    gb = np.array([int(g['bus']) for g in gens])
    offg = [bool(g.get('off')) for g in gens]     # in/out-of-service generators
    if np.sum(bt == 3) == 0:
        bt[gb[0] - 1] = 3                    # first generator bus -> slack
    elif np.sum(bt == 3) > 1:
        first = np.where(bt == 3)[0][0]
        bt[bt == 3] = 2
        bt[first] = 3
    for k, b in enumerate(gb):              # in-service generator buses regulate V
        if not offg[k] and bt[b - 1] == 1:
            bt[b - 1] = 2
    for k, b in enumerate(gb):              # a bus whose only unit is out of service -> PQ
        if offg[k] and bt[b - 1] != 3 and not any(gb[j] == b and not offg[j] for j in range(m)):
            bt[b - 1] = 1
    Pd = np.array([float(b.get('Pd', 0)) for b in buses]) / 100.0
    Qd = np.array([float(b.get('Qd', 0)) for b in buses]) / 100.0
    bs = np.array([float(b.get('Bs', 0)) for b in buses]) / 100.0
    Vm0 = np.array([float(b.get('Vset', 1.0) or 1.0) for b in buses])
    def _brow(br):
        if br.get('off'):                    # out of service -> open circuit (row kept for index alignment)
            return [br['f'], br['t'], 9999.0, 9999.0, 0.0]
        return [br['f'], br['t'], float(br.get('r', 0)),
                float(br.get('x', 0.05)), float(br.get('b', 0))]
    branch = np.array([_brow(br) for br in brs], float)
    if np.any(branch[:, 3] == 0):
        raise ValueError('every line needs a nonzero reactance x')
    tap = np.array([0.0 if br.get('off') else float(br.get('tap', 0) or 0) for br in brs])
    Pg = np.array([0.0 if offg[k] else float(g.get('Pg', 0))
                   for k, g in enumerate(gens)]) / 100.0
    Vg = np.array([float(g.get('Vset', 1.0) or 1.0) for g in gens])
    Srat = np.array([float(g.get('S', 0) or max(abs(g.get('Pg', 0)), 50.0) / 0.8)
                     for g in gens])
    machine = {}
    dflt = default_md(100.0)
    for key in dflt:
        machine[key] = np.full(n, dflt[key], float)
    for k, g in enumerate(gens):
        md = g.get('md') or default_md(Srat[k])
        i = gb[k] - 1
        for key, v in md.items():
            if key in machine:
                machine[key][i] = float(v)
    raw = []                                          # FACTS devices (shunt + series + combined)
    for d in (net.get('facts') or []):
        typ = str(d.get('type', '')).upper()
        if typ in facts.SHUNT:                        # SVC / STATCOM — attach at a bus
            dd = facts.default_facts(typ, float(d.get('Vref', 1.0) or 1.0))
            dd.update(d); dd['type'] = typ; dd['bus'] = int(dd.get('bus', 0))
            if 1 <= dd['bus'] <= n:
                raw.append(dd)
        elif typ in facts.SERIES:                     # TCSC / TSSC / SSSC — sit on a line
            dd = facts.default_facts(typ)
            dd.update(d); dd['type'] = typ
            dd['f'] = int(dd.get('f', 0)); dd['t'] = int(dd.get('t', 0))
            if 1 <= dd['f'] <= n and 1 <= dd['t'] <= n and dd['f'] != dd['t']:
                raw.append(dd)
        elif typ in facts.COMBINED:                   # UPFC / IPFC — expanded below
            dd = facts.default_facts(typ, float(d.get('Vref', 1.0) or 1.0))
            dd.update(d); dd['type'] = typ
            if typ == 'UPFC':
                dd['bus'] = int(dd.get('bus', 0)); dd['f'] = int(dd.get('f', 0)); dd['t'] = int(dd.get('t', 0))
                ok = (1 <= dd['bus'] <= n and 1 <= dd['f'] <= n and 1 <= dd['t'] <= n and dd['f'] != dd['t'])
            else:                                     # IPFC — line 1 required, line 2 optional (set in editor)
                dd['f'] = int(dd.get('f', 0)); dd['t'] = int(dd.get('t', 0))
                dd['f2'] = int(dd.get('f2', 0)); dd['t2'] = int(dd.get('t2', 0))
                ok = (1 <= dd['f'] <= n and 1 <= dd['t'] <= n and dd['f'] != dd['t'])
            if ok:
                raw.append(dd)
    facts_dev = facts.expand_combined(raw)            # UPFC->STATCOM+SSSC, IPFC->SSSC+SSSC
    case = cases.Case(net.get('name', 'custom'), m, n, 2 * np.pi * 60, bt,
                      Pd, Qd, Vm0, gb, Pg, Vg, branch, tap=tap,
                      gs=np.zeros(n), bs=bs, machine=machine, Sbase_gen=Srat,
                      facts=facts_dev)
    if (not np.all(np.isfinite(case.V0))) or case.V0.min() < 0.5 or case.V0.max() > 1.6:
        raise ValueError('power flow did not converge — check impedances, '
                         'loads and that the network is fully connected')
    return case


def api_netload(req):
    """Export a built-in system as an editable diagram (with layout and the
    current sidebar unit mix)."""
    sysname = req['system']
    case = make_case(sysname)
    mix = req.get('mix') or ['SG'] * case.m
    XY = LAYOUTS.get(sysname) or auto_layout(case.n, case.branch)
    inv = {3: 'slack', 2: 'pv', 1: 'pq'}
    buses = []
    for i in range(case.n):
        buses.append(dict(x=XY[i][0], y=XY[i][1], type=inv[int(case.bus_type[i])],
                          Vset=round(float(case.Vm0[i]), 4),
                          Pd=round(float(case.Pd[i] * 100), 1),
                          Qd=round(float(case.Qd[i] * 100), 1),
                          Bs=0.0 if case.bs is None else round(float(case.bs[i] * 100), 1)))
    brs = []
    for k in range(case.branch.shape[0]):
        br = case.branch[k]
        rate = 0.0
        if case.branch.shape[1] > 5 and float(br[5]) > 0:
            rate = round(float(br[5]), 1)              # MATPOWER RATE_A (MVA)
        brs.append(dict(f=int(br[0]), t=int(br[1]), r=round(float(br[2]), 5),
                        x=round(float(br[3]), 5), b=round(float(br[4]), 5),
                        rate=rate,
                        tap=0 if case.tap is None else round(float(case.tap[k]), 4)))
    gens = []
    taken = set()
    for k in range(case.m):
        i = int(case.gen_bus[k]) - 1
        md = {key: round(float(case.machine[key][i]), 6) for key in case.machine}   # machine data lives at the terminal bus
        # place the generator on the least-crowded side of its bus: opposite
        # the resultant direction of the connected branches (and of the load,
        # which hangs below), snapped to the nearest compass direction
        vx = vy = 0.0
        for br in brs:
            o = None
            if br['f'] == i + 1:
                o = XY[br['t'] - 1]
            elif br['t'] == i + 1:
                o = XY[br['f'] - 1]
            if o is not None:
                d = math.hypot(o[0] - XY[i][0], o[1] - XY[i][1]) or 1.0
                vx += (o[0] - XY[i][0]) / d
                vy += (o[1] - XY[i][1]) / d
        if buses[i]['Pd'] or buses[i]['Qd']:
            vy += 0.8
        # perpendicular tap (SLD convention): the horizontal bar takes its
        # machine above or below, on the side away from lines and loads
        uy = 1.0 if vy < -0.15 else -1.0
        gx, gy = XY[i][0], XY[i][1] + uy * 64
        while (gx, gy) in taken:
            gx += 42
        taken.add((gx, gy))
        gens.append(dict(bus=int(case.gen_bus[k]), tag=mix[k] if k < len(mix) else 'SG',
                         Pg=round(float(case.Pg_sched[k] * 100), 1),
                         Vset=round(float(case.Vg_sched[k]), 4),
                         S=round(float(case.Sbase_gen[k]), 1), md=md, x=gx, y=gy))
    return dict(name=sysname, buses=buses, branches=brs, gens=gens)


def api_pf(req):
    """Power flow of the drawn network + branch flows for the SLD overlay."""
    case = net_to_case(req['net'])
    meth = str(req.get('pfmethod', 'nr') or 'nr').lower()
    pfinfo = None
    if meth not in ('nr', 'newton', '') and not case.facts:   # FACTS regulation is solved by the case (NR); keep that result
        from network import power_flow as _pf
        V, th, Pg, Qg, pfinfo = _pf(
            case.Ybus, case.bus_type, case.Pd, case.Qd, case.Vm0,
            case.gen_bus, case.Pg_sched, case.Vg_sched, method=meth,
            branch=case.branch, tap=case.tap, report=True)
        case.Pg, case.Qg = Pg, Qg     # so the reported Pg/Qg match the solver
    else:
        V, th = case.V0, case.TH0
        # report NR's own iteration count for the pedagogical comparison
        _, _, _, _, pfinfo = __import__('network').power_flow(
            case.Ybus, case.bus_type, case.Pd, case.Qd, case.Vm0,
            case.gen_bus, case.Pg_sched, case.Vg_sched, method='nr',
            branch=case.branch, tap=case.tap, report=True)
    Vc = V * np.exp(1j * th)
    # a DC-coupled UPFC (P-Q mode) removes its own line and controls the corridor:
    # report the commanded P/Q on that branch, not the phantom admittance flow.
    pqline = {}
    for d in getattr(case, '_upfc_pq', []) or []:
        pqline[(int(d.get('f', 0)), int(d.get('t', 0)))] = (float(d.get('Pset', 0.0)),
                                                            float(d.get('Qset', 0.0)))
    for d in getattr(case, '_ipfc_pq', []) or []:      # DC-coupled IPFC corridors
        rep = d.get('_rep', {}) or {}
        pqline[(int(d.get('f', 0)), int(d.get('t', 0)))] = (float(d.get('P1set', 0.0)),
                                                            float(d.get('Q1set', 0.0)))
        S2 = rep.get('S2', 0j)
        if int(d.get('f2', 0)) and int(d.get('t2', 0)):
            pqline[(int(d['f2']), int(d['t2']))] = (float(getattr(S2, 'real', 0.0)),
                                                    float(getattr(S2, 'imag', 0.0)))
    flows = []
    for k in range(case.branch.shape[0]):
        br = case.branch[k]
        f, t = int(br[0]) - 1, int(br[1]) - 1
        key = (f + 1, t + 1); keyr = (t + 1, f + 1)
        if key in pqline or keyr in pqline:               # UPFC-controlled corridor
            P, Q = pqline.get(key) or pqline.get(keyr)
            flows.append(dict(Pf=round(P, 1), Qf=round(Q, 1), Pt=round(P, 1), loss=0.0, upfc=True))
            continue
        r, x, b = br[2], br[3], br[4]
        a = 1.0 if (case.tap is None or case.tap[k] == 0) else case.tap[k]
        y = 1 / (r + 1j * x)
        bc = 1j * b / 2
        Sf = Vc[f] * np.conj((y + bc) / (a * a) * Vc[f] - y / np.conj(a) * Vc[t])
        St = Vc[t] * np.conj((y + bc) * Vc[t] - y / a * Vc[f])
        flows.append(dict(Pf=round(float(Sf.real * 100), 1),
                          Qf=round(float(Sf.imag * 100), 1),
                          Pt=round(float(St.real * 100), 1),
                          Qt=round(float(St.imag * 100), 1),
                          loss=round(float((Sf + St).real * 100), 2),
                          Qloss=round(float((Sf + St).imag * 100), 2)))
    facts_out = []
    for d in case.facts:
        typ = str(d['type']).upper()
        if typ in facts.SHUNT:
            facts_out.append(dict(kind='shunt', type=typ, bus=int(d['bus']),
                V=round(float(V[int(d['bus']) - 1]), 4), Q=round(float(d.get('_Q', 0.0) * 100), 1),
                B=(round(float(d.get('_B', 0.0)), 3) if typ == 'SVC' else None),
                I=(round(float(d.get('_I', 0.0)), 3) if typ == 'STATCOM' else None),
                sat=bool(d.get('_sat', False)),
                parent=d.get('_parent'), ptype=d.get('_ptype')))
        elif typ in facts.SERIES:
            facts_out.append(dict(kind='series', type=typ, f=int(d['f']), t=int(d['t']),
                kcomp=round(float(d.get('_kc', d.get('kcomp', 0.0))), 3),
                Xc=round(float(d.get('_Xc', 0.0)), 4), Vse=float(d.get('_Vse', 0.0)),
                Iline=float(d.get('_I', 0.0)), Pline=float(d.get('_Pline', 0.0)),
                sat=bool(d.get('_satV', False)),
                parent=d.get('_parent'), ptype=d.get('_ptype')))
    return dict(V=[round(float(v), 4) for v in V],
                th=[round(float(np.degrees(t)), 2) for t in th],
                Pg=[round(float(case.Pg[int(b) - 1] * 100), 1) for b in case.gen_bus],
                Qg=[round(float(case.Qg[int(b) - 1] * 100), 1) for b in case.gen_bus],
                flows=flows,
                pf=pfinfo, facts=facts_out,
                Ptot=round(float(sum(case.Pg[int(b) - 1] for b in case.gen_bus) * 100), 1),
                Pload=round(float(case.Pd.sum() * 100), 1))


def build_system(req):
    """Case + System with per-unit GUI overrides applied: SG (and rating)
    overrides act on the case data, converter/source overrides go through
    the parameter mechanism (on top of any Kundur auto-scaling).
    Accepts either a built-in `system` name or a diagram `net`."""
    if req.get('net'):
        case = net_to_case(req['net'])
        mix = [g['tag'] for g in req['net']['gens']]
        sysname = None
    else:
        case = make_case(req['system'])
        mix = req['mix']
        sysname = req['system']
    user = {int(k): dict(v) for k, v in (req.get('prm') or {}).items() if v}
    conv = {}
    for k, ov in user.items():
        if 'Srating' in ov:
            case.Sbase_gen[k] = float(ov.pop('Srating'))
        if mix[k].startswith('SG'):       # SG and all reduced/PSS variants
            i = int(case.gen_bus[k]) - 1
            pss = {}
            for key, val in ov.items():
                if key in case.machine:            # machine data -> case
                    case.machine[key][i] = float(val)
                elif key in ('Kpss', 'Tw', 'T1', 'T2',    # PSS gains -> prm
                             'Ke', 'Kde', 'Ku', 'Td'):    # fuzzy-PSS scales -> prm
                    pss[key] = float(val)
            if pss:
                conv[k] = pss                      # flows through plist to init
        else:
            if isinstance(ov.get('c'), str):
                ov['c'] = tuple(float(x) for x in ov['c'].split(','))
            for key in ('Pmax', 'Sconv', 'Smach'):
                if key in ov and ov[key] in ('', None):
                    ov[key] = None
                elif key in ov:
                    ov[key] = float(ov[key])
            if 'syn_in' in ov:
                ov['syn_in'] = bool(ov['syn_in'])
            conv[k] = ov
    plist = [conv.get(k) for k in range(len(mix))]
    if sysname:
        plist = auto_prm(sysname, mix, plist)
    return System(case, mix, plist), case, mix


def auto_prm(sysname, mix, user_prm):
    """Kundur units replace 900-MVA machines: scale converter parameters to
    the machine size automatically (as in the paper), unless overridden."""
    prm = [dict(user_prm[k]) if user_prm and user_prm[k] else {} for k in range(len(mix))]
    if sysname == 'Kundur2A':
        for k, tag in enumerate(mix):
            if not tag.startswith('SG'):
                base = {}
                if 'GFM' in tag:
                    base.update(cases.GFM_K)
                if 'GFL' in tag:
                    base.update(cases.GFL_K)
                base.update(prm[k])
                prm[k] = base
    return [p if p else None for p in prm]


def _ds(arr, npts=1200):
    a = np.asarray(arr, float)
    if a.size <= npts:
        return a.tolist()
    idx = np.linspace(0, a.size - 1, npts).astype(int)
    return a[idx].tolist()


# ------------------------------------------------------------ API handlers
def api_meta(_):
    return dict(ui=_load_pref(), systems=SYSTEMS, unit_types=UNIT_TYPES, unit_info=UNIT_INFO,
                presets=PRESETS, scenarios=SCEN_INFO,
                m={'IEEE9': 3, 'IEEE14': 5, 'IEEE30': 6, 'IEEE39': 10, 'IEEE57': 7,
                   'Kundur2A': 4, 'NE68': 16})


def api_linearize(req):
    s, case, _mix = build_system(req)
    R = linearize(s)
    ev = R['ev']
    names = s.state_names()
    spd = s.speed_states()                 # (k, col, M, kind) per inertial unit
    md = []
    W = np.linalg.inv(R['evec'])
    for i, lam in enumerate(ev):
        f = lam.imag / (2 * np.pi)
        if f < 0.02 or f > 8:
            continue
        z = -lam.real / abs(lam) * 100
        p = np.abs(R['evec'][:, i] * W[i, :])
        p = p / p.max()
        top = np.argsort(p)[::-1][:8]
        # mode shape: speed-state eigenvector components (compass plot)
        shape = []
        if spd:
            vv = np.array([R['evec'][col, i] for (_, col, _, _) in spd])
            mx = np.max(np.abs(vv))
            if mx > 0:
                vv = vv / mx
            for (k, _, _, _), v in zip(spd, vv):
                shape.append([f"G{s.units[k]['bus'] + 1}",
                              round(float(v.real), 3), round(float(v.imag), 3)])
        md.append(dict(f=round(f, 4), z=round(z, 2),
                       re=round(lam.real, 4), im=round(lam.imag, 4),
                       part=[[names[j], round(float(p[j]), 3)] for j in top],
                       shape=shape))
    md.sort(key=lambda d: d['z'])
    return dict(ev=[[round(l.real, 4), round(l.imag, 4)] for l in ev],
                modes=md, nstates=int(s.NX),
                unstable=int(np.sum(ev.real > 1e-6)),
                Heff=round(float(s.eff_inertia()), 2),
                pen=round(float(s.penetration()), 1),
                res=float(s.equilibrium_residual()))


def api_simulate(req):
    s, case, mix = build_system(req)
    d = req.get('dist', {})
    meth = str(d.get('method', 'rk4') or 'rk4')
    kind = d.get('kind', 'load')
    solver_note = None
    if kind in ('fault', 'trip') and meth.lower() not in ('rk4', 'psdat', ''):
        # a bolted fault / line outage is a discontinuous, stiff network event
        # best handled by the built-in partitioned integrator; the adaptive
        # SciPy solvers are for the smooth disturbances (load/gen/cloud/gust).
        solver_note = f"{meth} not used for {kind}; ran built-in RK4 (suited to switching events)"
        meth = 'rk4'
    kw = dict(tsim=float(d.get('tsim', 12.0)), dt=2e-3, method=meth)
    t1 = float(d.get('t1', 1.0))
    t2v = d.get('t2', '')
    t2 = float(t2v) if str(t2v).strip() not in ('', 'inf') else None
    mag = float(d.get('mag', 0.15))
    loc = int(d.get('loc', 1))
    if kind == 'load':
        kw.update(t_dist=t1, t_off=t2, dPload={loc - 1: mag})
    elif kind == 'fault':
        kw.update(fault=(loc - 1, 1 / (1j * max(mag, 1e-3)), t1,
                         t2 if t2 else t1 + 0.1))
    elif kind == 'trip':
        fb, tb = int(d.get('loc', 7)), int(d.get('loc2', 8))
        kw.update(line_trip=(fb, tb, t1, t2 if t2 else 1e9))
    elif kind == 'gen':
        kw.update(t_dist=t1, t_off=t2, gen_dist={loc - 1: mag})
    elif kind == 'cloud':
        tag = s.units[loc - 1]['tag']
        if not tag.startswith('PV'):
            raise ValueError(f"unit G{loc} is {tag} — a cloud needs a PV unit "
                             f"(set G{loc} to PV-GFL or PV-GFM in the sidebar)")
        kw.update(G_prof={loc - 1: cloud_profile(t1, depth=mag)})
    elif kind == 'gust':
        tag = s.units[loc - 1]['tag']
        if not tag.startswith('WT'):
            raise ValueError(f"unit G{loc} is {tag} — a gust needs a wind unit "
                             f"(WT1/WT2/WT3/WT4-GFL/WT4-GFM)")
        u = s.units[loc - 1]['aux']
        base = u['src']['vw0'] if 'src' in u else u.get('vw0', 0.9)
        kw.update(vw_prof={loc - 1: gust_profile(t1, A=mag, base=base)})
    # suppress the harmless FP-overflow chatter a divergent (unstable) run emits
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        T, X, Z = simulate(s, **kw)
    # Guard against a dynamically-unstable operating point: some benchmarks with
    # the built-in GENERIC dynamic data (e.g. IEEE57) have an AVR/exciter mode in
    # the right half-plane, so the response physically diverges. Detect the
    # runaway, truncate to the meaningful pre-divergence transient and flag it —
    # far better than returning inf or a nonsensical 1e76 plot.
    bad = (~np.isfinite(X).all(axis=1)) | (np.abs(X) > 1e6).any(axis=1)
    if bad.any():
        kcut = max(int(np.argmax(bad)), 2)
        T, X, Z = T[:kcut], X[:kcut], Z[:kcut]
        _dn = ('the response diverges — this operating point is dynamically '
               'unstable with the current data (an AVR/exciter mode). Raise/lower '
               'the exciter gain KA or add a PSS in the sidebar to stabilise it.')
        solver_note = (solver_note + '; ' + _dn) if solver_note else _dn
    fc = s.coi_freq(X)
    names = s.state_names()
    metrics = None
    if fc is not None:
        dev = np.where(np.abs(fc - fc[0]) > 0.002)[0]
        rocof = None
        if dev.size:
            i0 = dev[0]
            i1 = min(len(T) - 1, i0 + int(0.25 / max(T[1] - T[0], 1e-6)))
            if i1 > i0:
                rocof = round(float((fc[i1] - fc[i0]) / (T[i1] - T[i0])), 4)
        metrics = dict(nadir=round(float(np.min(fc)), 4),
                       peak=round(float(np.max(fc)), 4),
                       rocof=rocof, fend=round(float(fc[-1]), 4))
    out = dict(t=_ds(T), names=names, method=meth, nsteps=int(len(T)),
               solver_note=solver_note,
               fCOI=None if fc is None else _ds(fc),
               nadir=None if fc is None else round(float(np.min(fc)), 4),
               metrics=metrics)
    # per-unit speed traces + requested extra states
    sp = {}
    for k, un in enumerate(s.units):
        tag = un['tag']
        if tag == 'SG' or tag.startswith('SG'):
            col = un['xsl'].start + un['names'].index('omega')
            sp[f"G{un['bus'] + 1} ({tag})"] = _ds(X[:, col] / case.ws * 60)
        elif tag == 'GFM' or tag.endswith('-GFM'):
            sp[f"G{un['bus'] + 1} ({tag})"] = _ds(X[:, un['xsl'].start + 1] / case.ws * 60)
    out['speeds'] = sp
    extra = {}
    for nm in req.get('watch', [])[:4]:
        if nm in names:
            extra[nm] = _ds(X[:, names.index(nm)])
    out['watch'] = extra
    return out


def api_states(req):
    """Names of every differential state of the current model (diagram +
    fleet), so the Time-domain watch list is a PICK LIST, never typed."""
    if not req.get('net') and not req.get('mix'):      # bare call: all-SG fleet
        req = dict(req, mix=['SG'] * len(make_case(req['system']).gen_bus))
    s, _case, _mix = build_system(req)
    return dict(names=s.state_names())


def api_scenario(req):
    import studies
    name = req['name']
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figs')
    buf = io.StringIO()
    before = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    with contextlib.redirect_stdout(buf):
        studies.run(name, outdir=outdir)
    imgs = []
    if os.path.isdir(outdir):
        cand = [f for f in os.listdir(outdir) if f.startswith('sc_') and name.split('_')[0] in f] or \
               sorted(set(os.listdir(outdir)) - before)
        for f in sorted(set(cand)):
            p = os.path.join(outdir, f)
            if f.endswith('.png') and os.path.isfile(p):
                imgs.append('data:image/png;base64,' +
                            base64.b64encode(open(p, 'rb').read()).decode())
    return dict(text=buf.getvalue(), images=imgs[:3])


# ------------------------------------------------- additional analyses ---
def api_sweep(req):
    """Parameter sweep of ONE unit parameter: root-locus data + the damping
    of the least-damped oscillatory mode in the chosen band per value."""
    k = int(req['unit'])
    pname = req['param']
    vals = np.linspace(float(req['vfrom']), float(req['vto']),
                       int(min(max(int(req.get('n', 9)), 3), 15)))
    f1, f2 = [float(x) for x in req.get('band', [0.1, 8.0])]
    loci = []
    curve = []
    for v in vals:
        r2 = dict(req)
        prm = {kk: dict(vv) for kk, vv in (req.get('prm') or {}).items()}
        prm.setdefault(str(k), {})[pname] = float(v)
        r2['prm'] = prm
        s, _, _ = build_system(r2)
        R = linearize(s)
        ev = [l for l in R['ev'] if l.imag >= -1e-9 and l.real > -15
              and abs(l.imag) / 2 / np.pi < 8.5]
        loci.append([[round(l.real, 4), round(l.imag, 4)] for l in ev])
        cand = [(-l.real / abs(l) * 100, l.imag / 2 / np.pi) for l in R['ev']
                if f1 < l.imag / 2 / np.pi < f2]
        z, f = min(cand) if cand else (None, None)
        curve.append([round(float(v), 5),
                      None if z is None else round(z, 3),
                      None if f is None else round(f, 4)])
    return dict(values=[round(float(v), 5) for v in vals], loci=loci, curve=curve)


def api_pod(req):
    """Residue-based POD design from the GUI: rank candidate actuators,
    design for the least-damped mode in the band, verify on the exact
    closed loop."""
    s, case, _ = build_system(req)
    R = linearize(s)
    f1, f2 = [float(x) for x in req.get('band', [0.2, 2.0])]
    cand = sorted([l for l in R['ev'] if f1 < l.imag / 2 / np.pi < f2],
                  key=lambda l: -l.real / abs(l))
    if not cand:
        raise ValueError(f'no oscillatory mode in {f1}-{f2} Hz — widen the band')
    lam0 = cand[0]
    elig = [k for k, un in enumerate(s.units)
            if un['tag'] == 'SG' or un['tag'] == 'GFM' or un['tag'].endswith('-GFM')]
    if not elig:
        raise ValueError('no SG or GFM-type unit to actuate — add one to the mix')
    act = int(req['act'])
    if act not in elig:
        raise ValueError(f"G{s.units[act]['bus']+1} is {s.units[act]['tag']} — "
                         "the POD actuator must be an SG or GFM-type unit")
    meas = req.get('meas', {'type': 'local'})
    if meas.get('type') == 'diff':
        h = DS.diff_speed_output(s, int(meas['a']), int(meas['b']))
    else:
        h = DS.speed_output(s, int(meas.get('a', act)))
    C = DS.output_matrix(R, h)
    B = DS.input_matrix(R, units=elig)
    res, lam, i = DS.residues(R, B, C, lam0)
    ranking = [[f"G{s.units[k]['bus'] + 1} ({s.units[k]['tag']})",
                float(abs(res[j])), round(float(np.degrees(np.angle(res[j]))), 1)]
               for j, k in enumerate(elig)]
    j_act = elig.index(act)
    pod = DS.pod_design(res[j_act], lam, zeta_target=float(req.get('zt', 0.15)))
    Acl = DS.closed_loop(R, B[:, j_act], C, pod)
    evcl = np.linalg.eig(Acl)[0]
    z1, lam1 = DS.damping_of(evcl, lam)
    return dict(target=dict(f=round(lam.imag / 2 / np.pi, 4),
                            z=round(-lam.real / abs(lam) * 100, 2)),
                ranking=ranking,
                pod=dict(K=round(pod['K'], 2), Tw=pod['Tw'], T1=round(pod['T1'], 4),
                         T2=round(pod['T2'], 4), nc=pod['nc']),
                achieved=dict(f=round(lam1.imag / 2 / np.pi, 4), z=round(z1, 2)),
                unstable=int(np.sum(evcl.real > 1e-6)),
                ev_open=[[round(l.real, 4), round(l.imag, 4)] for l in R['ev']],
                ev_closed=[[round(l.real, 4), round(l.imag, 4)] for l in evcl])


def api_bode(req):
    """Frequency response from a unit's power set-point to a frequency
    signal, from the exact linearized model."""
    s, case, _ = build_system(req)
    R = linearize(s)
    k = int(req['inp'])
    B = DS.input_matrix(R, units=[k])
    out = req.get('out', {'type': 'coi'})
    if out.get('type') == 'unit':
        h = DS.speed_output(s, int(out['a']))
    else:
        spd = s.speed_states()
        if not spd:
            raise ValueError('no inertial unit for a COI output')
        den = sum(M for (_, _, M, _) in spd)
        ws = s.case.ws

        def h(x, z, spd=spd, den=den, ws=ws):
            return sum(M * x[col] for (_, col, M, _) in spd) / den / ws - 1.0
    C = DS.output_matrix(R, h)
    fr = np.logspace(np.log10(float(req.get('fmin', 0.05))),
                     np.log10(float(req.get('fmax', 10.0))), 140)
    A = R['A']
    I = np.eye(A.shape[0])
    mag = []
    ph = []
    b = B[:, 0]
    for f in fr:
        Hjw = (C @ np.linalg.solve(1j * 2 * np.pi * f * I - A, b)).item()
        mag.append(round(20 * np.log10(max(abs(Hjw), 1e-12)), 3))
        ph.append(round(float(np.degrees(np.angle(Hjw))), 2))
    return dict(f=[round(float(x), 5) for x in fr], mag=mag, phase=ph)


LASTREQ = [time.time()]     # updated on every request (idle watchdog for the
                            # desktop launcher; unused in plain browser mode)

_PREF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'psdat_ui.json')


def _load_pref():
    try:
        with open(_PREF_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def api_uipref(req):
    p = _load_pref()
    p.update({k: v for k, v in req.items()
              if k in ('scale', 'sb', 'layout', 'mmap', 'viz2', 'learn')})
    p.pop('viz', None)   # retire the v1 viz key (a test build shipped one with non-default styling)
    try:
        with open(_PREF_FILE, 'w') as f:
            json.dump(p, f)
    except Exception:
        pass
    return p


def _save_dir():
    """Where exports/reports are written on the user's machine. Prefer the
    Desktop, fall back to the home folder, then the app folder."""
    home = os.path.expanduser('~')
    for cand in (os.path.join(home, 'Desktop'), home,
                 os.path.dirname(os.path.abspath(__file__))):
        try:
            d = os.path.join(cand, 'PSDAT_output')
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            continue
    return os.getcwd()


def api_save(req):
    """Write an export/report to disk (browser <a download> and window.print()
    do not work inside the Qt desktop window, so files go through Python).
    Accepts {name, text} or {name, b64}; optional open=True opens it."""
    import base64
    import re as _re
    name = _re.sub(r'[^A-Za-z0-9._-]+', '_', str(req.get('name') or 'diagram'))
    d = _save_dir()
    path = os.path.join(d, name)
    try:
        if req.get('b64') is not None:
            with open(path, 'wb') as f:
                f.write(base64.b64decode(req['b64'].split(',')[-1]))
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(req.get('text', ''))
    except Exception as e:
        return {'error': f'could not save: {e}'}
    if req.get('open'):
        try:
            webbrowser.open('file://' + path)
        except Exception:
            pass
    return {'path': path, 'dir': d}



# ======================================================================
#  COURSE STUDIES — the classic curriculum, one click each
#  (P-V curves, N-1 screening, short-circuit levels, critical clearing
#   time, economic dispatch + DC-OPF with locational prices)
# ======================================================================
def _case_of(req):
    if req.get('net'):
        return net_to_case(req['net'])
    return make_case(req['system'])


def api_pv(req):
    """P-V (nose) curve by natural-parameter continuation: scale the chosen
    load(s), warm-start Newton from the previous point, halve the step on
    failure. Classic voltage-stability teaching [Kundur ch. 14; Taylor].
    PV-bus reactive limits are not enforced (stated simplification)."""
    from network import build_ybus, _pf_newton
    case = _case_of(req)
    n = case.n
    target = int(req.get('bus', 0))              # 0 = every load together
    Y = build_ybus(n, case.branch, tap=case.tap, gs=case.gs, bs=case.bs)
    pv = np.where(case.bus_type == 2)[0]
    pq = np.where(case.bus_type == 1)[0]
    pvpq = np.sort(np.concatenate([pv, pq]))
    Pg0 = np.zeros(n)
    for i, gb in enumerate(case.gen_bus):
        Pg0[int(gb) - 1] += case.Pg_sched[i]
    sel = np.zeros(n, bool)
    if target > 0:
        sel[target - 1] = True
        if case.Pd[target - 1] <= 0:
            raise ValueError(f'bus {target} carries no load — pick a load bus')
    else:
        sel = case.Pd > 0
    # distribute the extra load to the slack implicitly (slack picks it up)
    V = case.Vm0.copy().astype(float)
    th = np.zeros(n)
    for i, gb in enumerate(case.gen_bus):
        if case.bus_type[int(gb) - 1] == 2:
            V[int(gb) - 1] = case.Vg_sched[i]
    lam, step = 1.0, 0.05
    lam_hist, Vmon_hist, Pmw_hist = [], [], []
    mon = target - 1 if target > 0 else int(np.argmax(case.Pd))
    Vg, thg = V.copy(), th.copy()
    while step > 1e-4:
        lam_try = lam + step
        Pd = case.Pd * np.where(sel, lam_try, 1.0)
        Qd = case.Qd * np.where(sel, lam_try, 1.0)
        Psp = Pg0 - Pd
        Qsp = -Qd
        try:
            V2, th2, iters = _pf_newton(Y, Psp, Qsp, Vg.copy(), thg.copy(),
                                        pv, pq, pvpq, 1e-10, 25)
            ok = np.all(np.isfinite(V2)) and V2.min() > 0.3
        except Exception:
            ok = False
        if ok:
            lam, Vg, thg = lam_try, V2, th2
            lam_hist.append(float(lam))
            Vmon_hist.append(float(V2[mon]))
            Pmw_hist.append(float(np.sum(Pd[sel]) * case.baseMVA))
        else:
            step *= 0.5
    P0 = float(np.sum(case.Pd[sel]) * case.baseMVA)
    Pmax = Pmw_hist[-1] if Pmw_hist else P0
    return dict(bus=int(mon + 1), all_loads=bool(target == 0),
                P_mw=Pmw_hist, V_pu=[round(v, 5) for v in Vmon_hist],
                lam=[round(v, 5) for v in lam_hist],
                P0_mw=round(P0, 1), Pmax_mw=round(Pmax, 1),
                margin_pct=round(100 * (Pmax - P0) / max(P0, 1e-6), 1),
                note='flat losses to the slack; PV-bus Q-limits not enforced')


def api_n1(req):
    """N-1 line-outage screening: every in-service branch removed in turn,
    the power flow re-solved, and the worst voltage/loading recorded."""
    from network import build_ybus, power_flow
    case = _case_of(req)
    n = case.n
    br = case.branch
    tap = case.tap if case.tap is not None else np.zeros(br.shape[0])
    rates = None
    if req.get('net'):
        rates = [float(b2.get('rate', 0) or 0) for b2 in req['net']['branches']]
    rows = []
    for r in range(br.shape[0]):
        keep = [i for i in range(br.shape[0]) if i != r]
        # ---- islanding check (BFS over remaining branches) ----------------
        adj = [[] for _ in range(n)]
        for i in keep:
            f, t = int(br[i, 0]) - 1, int(br[i, 1]) - 1
            adj[f].append(t)
            adj[t].append(f)
        seen = [False] * n
        stack = [int(np.where(case.bus_type == 3)[0][0])]
        seen[stack[0]] = True
        while stack:
            u = stack.pop()
            for v2 in adj[u]:
                if not seen[v2]:
                    seen[v2] = True
                    stack.append(v2)
        name = f"{int(br[r,0])}-{int(br[r,1])}"
        if not all(seen):
            rows.append(dict(line=name, status='ISLANDS the network',
                             vmin=None, vmax=None, load_pct=None, sev=9e9))
            continue
        try:
            Y = build_ybus(n, br[keep], tap=tap[keep], gs=case.gs, bs=case.bs)
            V, th, Pg, Qg = power_flow(Y, case.bus_type, case.Pd, case.Qd,
                                       case.Vm0, case.gen_bus, case.Pg_sched,
                                       case.Vg_sched, tol=1e-10, itmax=40)
            if not np.all(np.isfinite(V)) or V.min() < 0.3:
                raise RuntimeError
        except Exception:
            rows.append(dict(line=name, status='DIVERGED (collapse risk)',
                             vmin=None, vmax=None, load_pct=None, sev=8e8))
            continue
        Vc = V * np.exp(1j * th)
        worst_ld, worst_line = 0.0, ''
        for j, i in enumerate(keep):
            f, t = int(br[i, 0]) - 1, int(br[i, 1]) - 1
            ys = 1.0 / (br[i, 2] + 1j * br[i, 3])
            Sf = Vc[f] * np.conj((Vc[f] - Vc[t]) * ys)
            rate = (rates[i] if rates else 0) or 0
            if rate > 0:
                ld = 100 * abs(Sf) * case.baseMVA / rate
                if ld > worst_ld:
                    worst_ld, worst_line = ld, f"{f+1}-{t+1}"
        nvio = int(np.sum(V < 0.95) + np.sum(V > 1.05)) + (1 if worst_ld > 100 else 0)
        sev = nvio * 100 + max(0, 0.95 - V.min()) * 1000 + max(0.0, worst_ld - 100)
        rows.append(dict(line=name, status='ok' if nvio == 0 else f'{nvio} violation(s)',
                         vmin=round(float(V.min()), 4), vmax=round(float(V.max()), 4),
                         load_pct=round(worst_ld, 1) if worst_ld else None,
                         worst_line=worst_line, sev=float(sev)))
    rows.sort(key=lambda z: -z['sev'])
    for z in rows:
        z.pop('sev')
    return dict(rows=rows, n_outages=len(rows),
                n_secure=sum(1 for z in rows if z['status'] == 'ok'))


def api_sc(req):
    """Balanced three-phase short-circuit levels from the Z-bus: machines as
    E'' behind X''d, loads as constant admittances [Anderson ch. 6;
    Sauer & Pai ch. 10].  I_f = V_pre / Z_ii (classical method)."""
    from network import build_ybus
    case = _case_of(req)
    n = case.n
    Y = build_ybus(n, case.branch, tap=case.tap, gs=case.gs, bs=case.bs)
    Vc = case.V0
    Yaug = Y + np.diag((case.Pd - 1j * case.Qd) / np.abs(Vc) ** 2)
    for k, gb in enumerate(case.gen_bus):
        b2 = int(gb) - 1
        xdpp = case.machine['Xdpp'][b2] if 'Xdpp' in case.machine else             case.machine['Xdp'][b2]
        Yaug[b2, b2] += 1.0 / (1j * max(xdpp, 1e-4))
    Z = np.linalg.inv(Yaug)
    rows = []
    for i in range(n):
        Zii = Z[i, i]
        If = abs(Vc[i]) / max(abs(Zii), 1e-9)          # pu on 100 MVA
        rows.append(dict(bus=i + 1, If_pu=round(float(If), 3),
                         sc_mva=round(float(If * abs(Vc[i]) * case.baseMVA), 1),
                         xr=round(float(abs(Zii.imag) / max(abs(Zii.real), 1e-9)), 1)))
    strong = max(rows, key=lambda z: z['sc_mva'])
    weak = min(rows, key=lambda z: z['sc_mva'])
    return dict(rows=rows, strong=strong['bus'], weak=weak['bus'],
                note='classical Z-bus method: machines as E&Prime; behind X&Prime;d, '
                     'loads as constant admittance, pre-fault voltages from the power flow')


def api_cct(req):
    """Critical clearing time by bisection on the full nonlinear engine:
    a bolted three-phase fault at the chosen bus applied at t=1 s, cleared
    after t_c; unstable when the machine-angle spread passes 180 deg."""
    from simulate import simulate
    r = dict(req)
    if r.get('net'):
        r.setdefault('mix', [g['tag'] for g in r['net']['gens']])
    sysm, case, mix = build_system(r)
    fb = int(req.get('fbus', 1)) - 1
    def fresh():                      # simulate() mutates the assembled system:
        s2, _c, _m = build_system(r)  # every trial integrates a pristine copy
        return s2
    if not (0 <= fb < case.n):
        raise ValueError('fault bus out of range')
    Xf = max(float(req.get('xf', 0.05)), 0.03)          # fault reactance (pu):
    Yf = 1.0 / (1j * Xf)                                # severe yet numerically
    #                                                     robust (V dips to ~0.2-0.4)
    dcols = []
    for k, un in enumerate(sysm.units):
        for nm2 in ('delta', 'dg'):
            if nm2 in un['names']:
                dcols.append(un['xsl'].start + un['names'].index(nm2))
                break
    if len(dcols) < 2:
        raise ValueError('the CCT study needs at least two machines with '
                         'rotor angles (SG family or GFM)')

    def spread_of(tc):
        s2 = fresh()
        T, X, Za = simulate(s2, tsim=1.0 + tc + 3.5, dt=4e-3,
                            fault=(fb, Yf, 1.0, 1.0 + tc))
        D = X[:, dcols]
        if not np.all(np.isfinite(D)):
            return T, None, True
        sp = np.rad2deg(D.max(axis=1) - D.min(axis=1))
        uns = bool(np.max(sp) > max(180.0, sp[0] + 120.0))
        return T, sp, uns

    lo, hi = 0.02, 0.10
    T, sp, uns = spread_of(lo)
    if uns:
        return dict(cct=None, verdict=f'unstable even at {lo*1000:.0f} ms',
                    tried=[[lo, False]])
    tried = [[lo, True]]
    while hi <= 1.6:
        T, sp, uns = spread_of(hi)
        tried.append([hi, not uns])
        if uns:
            break
        lo = hi
        hi *= 1.8
    if not uns:
        return dict(cct=None, verdict=f'stable beyond {lo:.2f} s for this fault',
                    tried=tried)
    for _ in range(5):
        mid = 0.5 * (lo + hi)
        T, sp, uns = spread_of(mid)
        tried.append([round(mid, 4), not uns])
        if uns:
            hi = mid
        else:
            lo = mid
    Ts, ss, _ = spread_of(lo)
    Tu, su, _ = spread_of(min(hi + 0.01, hi * 1.05))
    dec = max(1, len(Ts) // 400)
    return dict(cct=round(lo, 3), window=[round(lo, 3), round(hi, 3)],
                fbus=fb + 1, xf=Xf, tried=tried,
                t_s=[round(float(t), 4) for t in Ts[::dec]],
                spread_stable=[round(float(v2), 3) for v2 in ss[::dec]],
                t_u=[round(float(t), 4) for t in Tu[::dec]],
                spread_unstable=[round(float(v2), 3) for v2 in (su if su is not None else np.full(len(Tu), 360.0))[::dec]])


def api_ed(req):
    """Economic dispatch two ways [Wood, Wollenberg & Sheble ch. 3, 8]:
    (1) classic equal-lambda iteration with quadratic costs, and
    (2) a DC optimal power flow (piecewise-linear costs, line limits) whose
    nodal-balance duals ARE the locational marginal prices (LMPs)."""
    from scipy.optimize import linprog
    case = _case_of(req)
    n, m = case.n, len(case.gen_bus)
    S = np.array([case.Sbase_gen[k] if case.Sbase_gen is not None else 100.0
                  for k in range(m)], float)
    costs = req.get('costs') or []
    b = np.array([float(costs[k]['b']) if k < len(costs) else 14.0 + 9.0 * k
                  for k in range(m)])
    c = np.array([float(costs[k]['c']) if k < len(costs) else 12.0 / max(S[k], 1.0)
                  for k in range(m)])
    Pnow = np.array([case.Pg_sched[k] for k in range(m)]) * case.baseMVA
    Pv = case.V0 * np.exp(1j * case.TH0)         # solved complex bus voltages
    Sl = Pv * np.conj((__import__('network').build_ybus(
        n, case.branch, tap=case.tap, gs=case.gs, bs=case.bs) @ Pv))
    loss_mw = float(np.sum(Sl.real)) * case.baseMVA
    D = float(np.sum(case.Pd)) * case.baseMVA + loss_mw
    Pmin, Pmax = 0.05 * S, 1.0 * S
    # ---- (1) equal-lambda iteration ---------------------------------------
    lo_l, hi_l = 0.0, 500.0
    for _ in range(80):
        lam2 = 0.5 * (lo_l + hi_l)
        P = np.clip((lam2 - b) / (2 * c), Pmin, Pmax)
        if P.sum() > D:
            hi_l = lam2
        else:
            lo_l = lam2
    lam2 = 0.5 * (lo_l + hi_l)
    Popt = np.clip((lam2 - b) / (2 * c), Pmin, Pmax)
    cost = lambda P: float(np.sum(b * P + c * P * P))
    # slack absorbs the mismatch in the "now" dispatch for a fair comparison
    Pnow2 = Pnow.copy()
    Pnow2[0] += D - Pnow.sum()
    # ---- (2) DC-OPF with line limits (3-segment linearized costs) ---------
    br = case.branch
    nl = br.shape[0]
    rates = None
    if req.get('net'):
        rates = [float(z.get('rate', 0) or 0) for z in req['net']['branches']]
    NSEG = 3
    nv = m * NSEG + n                     # segment powers (MW) + angles (rad)
    cvec = np.zeros(nv)
    bounds = []
    for k in range(m):
        w = (Pmax[k] - Pmin[k]) / NSEG
        for s2 in range(NSEG):
            mid = Pmin[k] + (s2 + 0.5) * w
            cvec[k * NSEG + s2] = b[k] + 2 * c[k] * mid    # marginal cost of the segment
            bounds.append((0, w))
    for i in range(n):
        bounds.append((None, None))
    Aeq = np.zeros((n, nv))
    # nodal balance:  sum(segments at i) - baseMVA*(B_L theta)_i = Pd_i*base - Pmin_i
    beq2 = case.Pd * case.baseMVA
    for k, gb in enumerate(case.gen_bus):
        for s2 in range(NSEG):
            Aeq[int(gb) - 1, k * NSEG + s2] = 1.0
        beq2[int(gb) - 1] -= Pmin[k]
    Bl = np.zeros((n, n))
    fl = []
    for r2 in range(nl):
        f, t = int(br[r2, 0]) - 1, int(br[r2, 1]) - 1
        x = max(br[r2, 3], 1e-4)
        Bl[f, f] += 1 / x
        Bl[t, t] += 1 / x
        Bl[f, t] -= 1 / x
        Bl[t, f] -= 1 / x
        fl.append((f, t, x))
    for i in range(n):
        Aeq[i, m * NSEG:] = -Bl[i, :] * case.baseMVA
    slack = int(np.where(case.bus_type == 3)[0][0])
    Aeq_th = np.zeros((1, nv))
    Aeq_th[0, m * NSEG + slack] = 1.0
    Aeq2 = np.vstack([Aeq, Aeq_th])
    beq3 = np.concatenate([beq2, [0.0]])
    Aub, bub = [], []
    for r2, (f, t, x) in enumerate(fl):
        rate = (rates[r2] if rates else 0) or 0
        if rate <= 0:
            continue
        row = np.zeros(nv)
        row[m * NSEG + f] = case.baseMVA / x
        row[m * NSEG + t] = -case.baseMVA / x
        Aub.append(row.copy()); bub.append(rate)
        Aub.append(-row); bub.append(rate)
    res = linprog(cvec, A_ub=np.array(Aub) if Aub else None,
                  b_ub=np.array(bub) if bub else None,
                  A_eq=Aeq2, b_eq=beq3, bounds=bounds, method='highs')
    opf = None
    if res.success:
        Pg_opf = Pmin + res.x[:m * NSEG].reshape(m, NSEG).sum(axis=1)
        # dual of the nodal balance = d(cost)/d(demand at bus i) = the LMP
        lmp = [round(float(v2), 2) for v2 in res.eqlin.marginals[:n]]
        binding = []
        if Aub:
            sl2 = res.ineqlin.slack
            for j2 in range(0, len(bub), 2):
                if min(sl2[j2], sl2[j2 + 1]) < 1e-3:
                    f, t, x = fl[[r2 for r2, (f, t, x) in enumerate(fl)
                                  if ((rates[r2] if rates else 0) or 0) > 0][j2 // 2]]
                    binding.append(f"{f+1}-{t+1}")
        opf = dict(Pg_mw=[round(float(p), 1) for p in Pg_opf],
                   cost=round(cost(Pg_opf), 1), lmp=lmp, binding=binding,
                   spread=round(max(lmp) - min(lmp), 2))
    return dict(gens=[dict(g=f'G{k+1}', bus=int(case.gen_bus[k]),
                           b=round(float(b[k]), 2), c=round(float(c[k]), 4),
                           Pnow=round(float(Pnow2[k]), 1),
                           Popt=round(float(Popt[k]), 1),
                           Pmax=round(float(Pmax[k]), 1)) for k in range(m)],
                demand_mw=round(D, 1), loss_mw=round(loss_mw, 2),
                lam=round(float(lam2), 2),
                cost_now=round(cost(Pnow2), 1), cost_opt=round(cost(Popt), 1),
                saving=round(cost(Pnow2) - cost(Popt), 1), opf=opf,
                note='default textbook costs C_k(P)=b_k P + c_k P^2 (edit later '
                     'with the course text); losses held at the base-case value')



def api_opp(req):
    """Optimal PMU placement for full topological observability [Xu & Abur
    2004; Gou 2008]: a PMU at bus i observes i and every neighbor. Solved
    EXACTLY as a binary integer program (HiGHS branch-and-bound through
    scipy.optimize.milp): minimize sum(x) s.t. (I + Adjacency) x >= 1.
    Optional zero-injection reduction: a bus with no load and no generation
    can be merged into its neighbors (Kirchhoff at the null node) before the
    ILP, which lowers the PMU count further."""
    case = _case_of(req)
    n = case.n
    br = case.branch
    A = np.eye(n)
    for r2 in range(br.shape[0]):
        f, t = int(br[r2, 0]) - 1, int(br[r2, 1]) - 1
        A[f, t] = A[t, f] = 1.0
    hasg = np.zeros(n, bool)
    for gb in case.gen_bus:
        hasg[int(gb) - 1] = True
    zi = [i for i in range(n)
          if (abs(case.Pd[i]) < 1e-9 and abs(case.Qd[i]) < 1e-9
              and not hasg[i] and (getattr(case, 'bs', None) is None
                                   or abs(case.bs[i]) < 1e-9))]
    use_zi = bool(req.get('zero_inj', True)) and len(zi) > 0

    def solve_ilp(Acov, keep):
        from scipy.optimize import milp, LinearConstraint, Bounds
        k = Acov.shape[0]
        res = milp(c=np.ones(k),
                   constraints=LinearConstraint(Acov, lb=np.ones(k)),
                   integrality=np.ones(k), bounds=Bounds(0, 1))
        if not res.success:
            raise RuntimeError('ILP failed')
        x = np.round(res.x).astype(int)
        return [keep[i] for i in range(k) if x[i] == 1]

    pmus_plain = solve_ilp(A, list(range(n)))
    result = dict(pmus_plain=[p + 1 for p in sorted(pmus_plain)],
                  n_plain=len(pmus_plain))
    pmus = pmus_plain
    if use_zi:
        # merge each zero-injection bus into its neighbourhood (classic
        # topology transform), solve the reduced ILP, then verify by
        # propagation on the FULL graph.
        keep = [i for i in range(n) if i not in zi]
        idx = {b2: k for k, b2 in enumerate(keep)}
        Ar = np.eye(len(keep))
        nb = [set(np.where(A[i] > 0)[0]) - {i} for i in range(n)]
        for f in range(n):
            for t in nb[f]:
                paths = [(f, t)]
                if t in zi:
                    paths = [(f, u) for u in nb[t] if u != f]
                for (a2, b3) in paths:
                    if a2 in idx and b3 in idx:
                        Ar[idx[a2], idx[b3]] = Ar[idx[b3], idx[a2]] = 1
        try:
            pmus = solve_ilp(Ar, keep)
        except Exception:
            pmus = pmus_plain
    # ---- observability propagation (with ZI Kirchhoff rule) ---------------
    obs = np.zeros(n, int)                    # 0 unobserved 1 derived 2 direct
    for p in pmus:
        obs[p] = 2
        for t in np.where(A[p] > 0)[0]:
            if obs[t] == 0:
                obs[t] = 1
    def propagate(obs):
        changed = True
        while use_zi and changed:
            changed = False
            for j in zi:
                nbj = list(np.where(A[j] > 0)[0])
                nbj.remove(j)
                if obs[j] > 0:                         # KCL at an observed null bus:
                    unk = [u for u in nbj if obs[u] == 0]
                    if len(unk) == 1:                  # one unknown neighbor -> known
                        obs[unk[0]] = 1
                        changed = True
                elif all(obs[u] > 0 for u in nbj):     # all neighbors known -> the
                    obs[j] = 1                         # null bus itself is known
                    changed = True
        return obs
    obs = propagate(obs)
    if use_zi and np.any(obs == 0):                    # ZI reduction not sufficient
        pmus = pmus_plain                              # here: fall back to the exact
        obs = np.zeros(n, int)                         # plain optimum (always 100%)
        for p in pmus:
            obs[p] = 2
            for t in np.where(A[p] > 0)[0]:
                if obs[t] == 0:
                    obs[t] = 1
        obs = propagate(obs)
    depth = np.array([int(np.sum([A[p, i] > 0 for p in pmus])) for i in range(n)])
    return dict(pmus=[p + 1 for p in sorted(pmus)], n=len(pmus),
                zero_inj_used=use_zi, zi_buses=[z + 1 for z in zi],
                observed_pct=round(100.0 * float(np.mean(obs > 0)), 1),
                coverage=[dict(bus=i + 1,
                               how=('PMU' if obs[i] == 2 else
                                    'neighbor' if obs[i] == 1 else 'NOT observed'),
                               redundancy=int(depth[i])) for i in range(n)],
                **result)



def api_quiz(req):
    """Self-assessment questions generated from the student's OWN network:
    the numbers in every question come from the current model and its solved
    power flow, so no two networks give the same quiz. Seeded, so an
    instructor can reproduce a sheet."""
    import random
    case = _case_of(req)
    n = case.n
    rng = random.Random(int(req.get('seed', 1)))
    count = min(int(req.get('count', 6)), 12)
    from network import build_ybus
    Y = build_ybus(n, case.branch, tap=case.tap, gs=case.gs, bs=case.bs)
    Vc = case.V0 * np.exp(1j * case.TH0)         # solved operating point
    V = np.abs(Vc)
    th = np.angle(Vc)
    S = Vc * np.conj(Y @ Vc)
    Pgen = float(np.sum(S.real + case.Pd)) * case.baseMVA
    Pload = float(np.sum(case.Pd)) * case.baseMVA
    loss = Pgen - Pload
    br = case.branch
    qs = []

    def num(qtext, ans, unit, tol_pct, expl):
        qs.append(dict(kind='num', q=qtext, a=round(float(ans), 4), unit=unit,
                       tol=max(abs(ans) * tol_pct / 100.0, 1e-3), explain=expl))

    def mcq(qtext, correct, wrongs, expl):
        opts = [str(correct)] + [str(w) for w in wrongs]
        rng.shuffle(opts)
        qs.append(dict(kind='mcq', q=qtext, opts=opts, a=str(correct), explain=expl))

    makers = []
    makers.append(lambda: num(
        'Total real-power losses of the solved network (MW)?', loss, 'MW', 3,
        f'P_loss = ΣP_gen − ΣP_load = {Pgen:.1f} − {Pload:.1f} = {loss:.2f} MW.'))
    makers.append(lambda: mcq(
        'Which bus has the LOWEST voltage magnitude?', int(np.argmin(V) + 1),
        rng.sample([i + 1 for i in np.argsort(V)[1:6]], 3),
        f'|V| is lowest at bus {int(np.argmin(V)+1)} ({V.min():.4f} pu) — '
        'heavily loaded and electrically far from voltage support.'))
    def q_angle():
        r2 = rng.randrange(br.shape[0])
        f, t = int(br[r2, 0]), int(br[r2, 1])
        d = np.rad2deg(th[f - 1] - th[t - 1])
        num(f'Voltage-angle difference θ{f} − θ{t} across line {f}–{t} (degrees)?',
            d, 'deg', 5,
            f'θ{f} = {np.rad2deg(th[f-1]):.2f}°, θ{t} = {np.rad2deg(th[t-1]):.2f}° '
            f'→ difference {d:.2f}°. Real power flows from the leading to the lagging angle.')
    makers.append(q_angle)
    def q_pflow():
        r2 = rng.randrange(br.shape[0])
        f, t = int(br[r2, 0]), int(br[r2, 1])
        x = br[r2, 3]
        P = V[f-1] * V[t-1] * np.sin(th[f-1] - th[t-1]) / x * case.baseMVA
        num(f'Using P ≈ V{f}·V{t}·sin(θ{f}−θ{t})/X with X = {x:.4f} pu: '
            f'real power over line {f}–{t} (MW)?', P, 'MW', 5,
            f'P = {V[f-1]:.3f}·{V[t-1]:.3f}·sin({np.rad2deg(th[f-1]-th[t-1]):.2f}°)/{x:.4f} '
            f'× {case.baseMVA:.0f} = {P:.1f} MW (lossless line approximation).')
    makers.append(q_pflow)
    def q_dir():
        r2 = rng.randrange(br.shape[0])
        f, t = int(br[r2, 0]), int(br[r2, 1])
        fwd = (th[f-1] - th[t-1]) > 0
        mcq(f'In which direction does real power flow on line {f}–{t}?',
            f'{f} → {t}' if fwd else f'{t} → {f}',
            [f'{t} → {f}' if fwd else f'{f} → {t}',
             'no real-power flow', 'direction alternates at 60 Hz'],
            'Real power flows from the bus with the LEADING voltage angle to the '
            f'lagging one; θ{f} − θ{t} = {np.rad2deg(th[f-1]-th[t-1]):.2f}°.')
    makers.append(q_dir)
    makers.append(lambda: mcq(
        'Doubling every machine inertia constant H changes an electromechanical '
        'mode frequency f ≈ (1/2π)√(K/M) by a factor of…',
        '1/√2 (≈ 0.707×, slower swings)',
        ['√2 (≈ 1.41×, faster swings)', '1/2 (half)', 'no change'],
        'f ∝ 1/√M and M = 2H/ωs, so doubling H divides every swing frequency by √2 '
        '— the low-inertia problem in reverse.'))
    makers.append(lambda: mcq(
        'A grid-FOLLOWING converter differs from a grid-FORMING one because it…',
        'measures the grid angle with a PLL and injects current into an existing voltage',
        ['sets its own voltage magnitude and frequency like a synchronous machine',
         'only works when synchronous machines are absent',
         'cannot deliver reactive power'],
        'GFL: PLL + current source into a stiff grid. GFM: droop/VSM voltage source '
        'that can form the grid — the key modern-grid distinction.'))
    makers.append(lambda: num(
        'A 5.0-kW (STC) PV array runs at its maximum power point. Irradiance '
        'falls from 1000 to 600 W/m2 at unchanged cell temperature. '
        'New MPP power (kW)?', 3.0, 'kW', 4,
        'MPP power is nearly proportional to irradiance: 5.0 x 600/1000 = 3.0 kW. '
        'I_sc scales linearly with G while V_oc moves only logarithmically - the '
        'current axis does the work (PV Lab, panel 1).'))
    makers.append(lambda: mcq(
        'Partial shading of a PV string WITH bypass diodes produces...',
        'several local maxima in the P-V curve',
        ['a single lower maximum at the same voltage',
         'zero output until the shade clears',
         'a higher V_oc from the unshaded cells'],
        'Each bypass diode lets the unshaded substrings keep conducting, so the '
        'I-V curve becomes a staircase and the P-V curve grows multiple peaks - '
        'the global one is what a good tracker must find. Without the diodes the '
        'shaded cells are driven into reverse bias and become hot spots.'))
    makers.append(lambda: mcq(
        'To hold a 10% frequency-support reserve, a PV plant operates...',
        'above the MPP voltage, on the right branch of the P-V curve',
        ['below the MPP voltage, on the left branch',
         'exactly at the MPP, with the surplus stored in the DC link',
         'it cannot hold reserve without a battery'],
        'De-loading parks the operating point on the higher-voltage side of the '
        'MPP: the DC-link regulation is stable there, and stepping the voltage '
        'reference back toward V_mp releases the headroom within cycles '
        '(Freq-Watt support without storage).'))
    makers.append(lambda: num(
        'Reactive power a shunt capacitor of B = 0.5 pu injects at a bus held at '
        f'{V.max():.3f} pu (MVAr)?', 0.5 * V.max() ** 2 * case.baseMVA, 'MVAr', 3,
        f'Q = B·V² = 0.5 × {V.max():.3f}² × {case.baseMVA:.0f} = '
        f'{0.5*V.max()**2*case.baseMVA:.1f} MVAr — support falls with V², the classic '
        'weakness of passive compensation.'))
    rng.shuffle(makers)
    for mk in makers[:count]:
        mk()
    return dict(questions=qs, n=len(qs), seed=int(req.get('seed', 1)))


ROUTES = {'/api/meta': api_meta, '/api/uipref': api_uipref,
          '/api/linearize': api_linearize,
          '/api/simulate': api_simulate, '/api/scenario': api_scenario,
          '/api/params': api_params, '/api/paramsall': api_paramsall,
          '/api/sweep': api_sweep,
          '/api/pod': api_pod, '/api/bode': api_bode,
          '/api/netload': api_netload, '/api/pf': api_pf, '/api/states': api_states,
          '/api/save': api_save,
          '/api/pv': api_pv, '/api/n1': api_n1, '/api/sc': api_sc,
          '/api/cct': api_cct, '/api/ed': api_ed, '/api/opp': api_opp, '/api/quiz': api_quiz}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        LASTREQ[0] = time.time()
        if self.path == '/api/ping':
            return self._send(200, b'{}')
        if self.path == '/favicon.ico':          # the app window / taskbar icon
            ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PSDAT.ico')
            if os.path.isfile(ico):
                return self._send(200, open(ico, 'rb').read(), 'image/x-icon')
            return self._send(404, b'')
        if self.path in ('/', '/index.html'):
            self._send(200, PAGE.encode(), 'text/html; charset=utf-8')
        elif self.path == '/api/meta':
            self._send(200, json.dumps(api_meta(None), default=_jsonable).encode())
        else:
            self._send(404, b'{}')

    def do_POST(self):
        LASTREQ[0] = time.time()
        n = int(self.headers.get('Content-Length', 0))
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
            fn = ROUTES.get(self.path)
            if fn is None:
                return self._send(404, b'{"error":"unknown endpoint"}')
            out = fn(req)
            self._send(200, json.dumps(out, default=_jsonable).encode())
        except Exception as e:              # surface errors into the UI
            self._send(200, json.dumps({'error': f'{type(e).__name__}: {e}'}).encode())


def _jsonable(o):
    """numpy scalars -> plain JSON numbers/bools."""
    if isinstance(o, (np.floating, np.integer)):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSDAT — Power System Dynamics Analysis Toolbox</title>
<link rel="icon" href="favicon.ico" type="image/x-icon">
<link rel="shortcut icon" href="favicon.ico" type="image/x-icon">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%231f3b73'/%3E%3Ccircle cx='32' cy='20' r='10' fill='none' stroke='white' stroke-width='4.5'/%3E%3Cline x1='32' y1='30' x2='32' y2='40' stroke='white' stroke-width='4.5'/%3E%3Crect x='12' y='40' width='40' height='8' rx='2' fill='white'/%3E%3C/svg%3E">
<style>
:root{--navy:#1f3b73;--navy2:#16294f;--gfm:#1e8449;--gfl:#c0392b;--gold:#b7950b;
 --teal:#117a8b;--bess:#a04000;--bg:#e8ebf0;--card:#ffffff;--ink:#20242c;--mut:#6b7280;
 --line:#c9cfd9;--chrome:#f4f5f7;}
*{box-sizing:border-box;margin:0}
html,body{height:100%}
html{overflow:hidden}
/* whole interface rendered at 80% via a STANDARD CSS transform (NOT `zoom`):
   transforms are correctly accounted for by getScreenCTM, so the mouse→canvas
   mapping stays exact in every browser and the Qt window. */
body{font:14px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);
 overflow:hidden;display:flex;flex-direction:column;
 transform:scale(0.8);transform-origin:0 0;width:125%;height:125%;
 user-select:none;-webkit-user-select:none}
input,textarea,select{user-select:text;-webkit-user-select:text}
td,pre{user-select:text;-webkit-user-select:text}
header{flex:none}
header{background:var(--chrome);border-bottom:1px solid var(--line);color:var(--ink);
 padding:0 8px;display:flex;align-items:stretch;gap:2px;user-select:none}
.brand{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;color:var(--navy);
 padding:5px 10px 5px 4px;border-right:1px solid var(--line);margin-right:4px}
.brand svg{width:19px;height:19px}
.menubar{display:flex;align-items:stretch}
.menu{position:relative}
.menu>button{border:0;background:none;font:inherit;font-size:13px;padding:7px 11px;cursor:default;color:var(--ink)}
.menu.open>button,.menu>button:hover{background:#e2e6ec}
.menu .dd{display:none;position:absolute;top:100%;left:0;z-index:60;background:#fff;
 border:1px solid #aab2bf;box-shadow:0 5px 18px rgba(16,24,40,.22);min-width:228px;padding:4px 0;
 max-height:82vh;overflow-y:auto;overscroll-behavior:contain}
.menu.open .dd{display:block}
.dd a{display:flex;align-items:center;gap:0;padding:6px 16px 6px 12px;font-size:13px;
 color:var(--ink);cursor:default;white-space:nowrap;text-align:left}
.dd a span:last-child:not(.chk){margin-left:auto;padding-left:26px}
.dd a:hover{background:var(--navy);color:#fff}
.dd a:hover .chk{color:#fff}
.dd a span{color:var(--mut);font-size:12px}
.dd a:hover span{color:#dbe4f5}
.dd .chk{width:14px;display:inline-block;color:var(--navy)}
.dsep{border-top:1px solid #e3e7ef;margin:4px 0}
#statusbar{position:fixed;bottom:0;left:0;right:0;height:24px;background:var(--chrome);
 border-top:1px solid var(--line);display:flex;align-items:center;gap:0;font-size:12px;
 color:#374151;z-index:40;user-select:none}
#statusbar span{padding:0 12px;border-right:1px solid var(--line);white-space:nowrap;overflow:hidden}
#statusbar #stMsg{flex:1;color:var(--mut)}
#statusbar #stPos{min-width:110px;text-align:right}
.wrap{flex:1;min-height:0;width:100%;display:flex;gap:0;padding:0;max-width:none;margin:0}
.wrap>*{min-height:0}
#content{flex:1;overflow:hidden;display:flex;flex-direction:column;min-width:0;padding:6px 6px 30px}
.card.main{flex:1;overflow:auto}
body.fs .wrap{padding:0}
body.fs #content{padding:2px 2px 26px}
body.fs #rail{display:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:3px;box-shadow:none}
/* ---- left mode rail (single home for workspace switching) ---- */
#rail{flex:none;width:50px;background:var(--chrome);border-right:1px solid var(--line);
 display:flex;flex-direction:column;align-items:stretch;padding:5px 4px;gap:3px;user-select:none;z-index:20}
.railb{display:flex;flex-direction:column;align-items:center;gap:2px;padding:7px 2px 5px;
 border:1px solid transparent;border-radius:5px;background:none;font:inherit;font-size:9.5px;
 line-height:1.1;color:#4b5563;cursor:default;text-align:center}
.railb svg{width:21px;height:21px}
.railb:hover{background:#e2e8f2;border-color:#cdd7e6}
.railb.on{background:#fff;border-color:#9fb6da;color:var(--navy);font-weight:600;box-shadow:inset 3px 0 0 var(--navy)}
.railspring{flex:1}
.side h2{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);margin:12px 0 6px}
.side h2:first-child{margin-top:0}
select,input[type=number],input[type=text]{width:100%;padding:6px 8px;border:1px solid #cfd6e2;border-radius:3px;
 background:#fff;font:inherit;font-size:14px}
.unitrow{display:grid;grid-template-columns:38px 1fr 30px;gap:6px;align-items:center;margin:4px 0}
.unitrow label{font-size:13px;color:var(--mut)}
.gear{border:1px solid #cfd6e2;background:#fff;border-radius:3px;cursor:pointer;height:30px;
 font-size:14px;position:relative;color:#4b5563}
.gear:hover{border-color:var(--navy);color:var(--navy)}
.gear.mod::after{content:'';position:absolute;top:3px;right:3px;width:7px;height:7px;
 border-radius:50%;background:var(--gfl)}
.modalbg{position:fixed;inset:0;background:rgba(16,24,40,.45);display:flex;
 align-items:center;justify-content:center;z-index:50}
.modal{background:#fff;border-radius:5px;width:640px;max-width:94vw;max-height:86vh;
 display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(16,24,40,.3)}
.modal h3{font-family:Georgia,serif;color:var(--navy);padding:14px 18px 8px;font-size:17px}
.modal .sub2{padding:0 18px 8px;font-size:12.5px;color:var(--mut)}
.mbody{overflow:auto;padding:4px 18px;flex:1}
.prow{display:grid;grid-template-columns:88px 110px 1fr;gap:10px;align-items:center;
 padding:4px 0;border-bottom:1px solid #f0f2f7;font-size:13px}
.prow b{font-weight:600;color:#1f2937}
.prow input[type=text],.prow input[type=number]{padding:5px 7px}
.prow .d{color:var(--mut);font-size:12px}
.prow.chg b{color:var(--gfl)}
.mrow{display:flex;gap:10px;justify-content:flex-end;padding:12px 18px;border-top:1px solid #e9edf4}
.mrow .ghost{background:#fff;border:1px solid #cfd6e2;border-radius:3px;padding:9px 16px;cursor:pointer;font:inherit}
.presets{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 2px}
.presets button{font-size:12px;padding:4px 9px;border-radius:99px;border:1px solid #cfd6e2;background:#fff;cursor:pointer}
.presets button:hover{border-color:var(--navy);color:var(--navy)}
.badges{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.badge{background:#eef2fa;border:1px solid #d8e0f0;border-radius:3px;padding:6px 10px;font-size:12.5px}
.badge b{font-size:15px;display:block}
.hspring{flex:1}
.qtool{display:flex;align-items:center;gap:2px;margin-left:auto;padding:0 2px}
.qtool button{border:1px solid transparent;background:none;width:28px;height:26px;border-radius:3px;
 color:#4b5563;cursor:default;padding:0;display:flex;align-items:center;justify-content:center}
.qtool button svg{width:16px;height:16px}
.qtool button:hover{background:#e2e6ec;border-color:#c7cfdb;color:var(--navy)}
.main{padding:16px 18px}
.row{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end}
.f{display:flex;flex-direction:column;gap:4px;font-size:12.5px;color:var(--mut)}
.f input,.f select{width:130px}
.go{background:var(--navy);color:#fff;border:0;border-radius:3px;padding:8px 18px;font:inherit;
 font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(16,24,40,.2)}
.go:hover{background:#2c5aa0}.go:disabled{opacity:.55;cursor:wait}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
@media(max-width:1100px){.grid2{grid-template-columns:1fr}.wrap{grid-template-columns:236px 1fr}}
.panel{padding:12px 14px}
.panel h3{font-family:Georgia,serif;font-size:16px;color:var(--navy);margin-bottom:8px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);text-align:left;
 border-bottom:2px solid #e3e7ef;padding:5px 8px}
td{padding:5px 8px;border-bottom:1px solid #eef1f6}
tr.sel td{background:#eef4ff}
tbody tr{cursor:pointer}tbody tr:hover td{background:#f6f9ff}
.zbad{color:#b42318;font-weight:600}.zwarn{color:#b7791f;font-weight:600}.zok{color:#1e7a44}
.pbar{height:9px;background:linear-gradient(90deg,var(--navy),#2c5aa0);border-radius:5px}
.pl{display:grid;grid-template-columns:86px 1fr 42px;gap:8px;align-items:center;font-size:12.5px;margin:3px 0}
svg{display:block}
.note{font-size:12.5px;color:var(--mut);margin-top:6px}
.scgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:12px}
.sc{padding:13px;border:1px solid #e3e7ef;border-radius:3px;cursor:pointer;background:#fff}
.sc:hover{border-color:var(--navy);box-shadow:0 2px 8px rgba(31,59,115,.12)}
.sc b{color:var(--navy)}.sc p{font-size:12.5px;color:var(--mut);margin-top:4px}
pre{background:#101828;color:#d7e3f7;border-radius:3px;padding:12px;font-size:12.5px;overflow:auto;max-height:320px}
.imgs img{max-width:100%;border:1px solid #e3e7ef;border-radius:3px;margin-top:10px}
.spin{display:none;margin-left:10px;color:var(--mut);font-size:13px}
.err{background:#fef2f2;border:1px solid #f3c3c3;color:#b42318;border-radius:3px;padding:9px 12px;margin-top:10px;font-size:13.5px}
footer{color:var(--mut);font-size:12px;text-align:center;padding:12px}
.hint{font-size:12px;color:var(--mut);margin-top:3px;min-height:15px}
.tbar{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;align-items:center}
.tgrp{display:inline-flex;align-items:center;gap:4px;flex-wrap:nowrap;white-space:nowrap;
 padding:3px 7px;border:1px solid var(--line);border-radius:4px;background:#fbfcfd}
.tgrp .tblab{margin-right:3px}
.tbtn{font-size:12.5px;padding:5px 10px;border-radius:3px;border:1px solid #b9c1cd;background:linear-gradient(#fdfdfe,#eef0f4);cursor:default}
.tbtn:hover{border-color:var(--navy);color:var(--navy)}
.tbtn.tool.on{background:var(--navy);color:#fff;border-color:var(--navy)}
#vizBody .tbtn.on{background:var(--navy);color:#fff;border-color:var(--navy)}
#vizBody .pl b{font-variant-numeric:tabular-nums}
#vizBody input[type=range]{accent-color:var(--navy);cursor:pointer}
.tblab{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;align-self:center}
.tbsep{width:1px;background:#e3e7ef;align-self:stretch;margin:0 2px}
.pprow{display:grid;grid-template-columns:64px 1fr;gap:8px;align-items:center;margin:5px 0;font-size:13px}
.pprow span{color:var(--mut)}
.pprow input,.pprow select{padding:5px 7px;font-size:13px}
/* ============ ROW 2: quick-operations ribbon (fixed) ============ */
#ribbon{flex:none;display:flex;align-items:stretch;gap:1px;background:var(--chrome);
 border-bottom:1px solid var(--line);padding:2px 6px 1px;overflow-x:auto;overflow-y:hidden;
 user-select:none;scrollbar-width:none}
#ribbon::-webkit-scrollbar{display:none}
#ribbon.mopen{overflow:visible}   /* an open dropdown must never be clipped by the ribbon scroller */
.rgrp{display:flex;flex-direction:column;justify-content:space-between;padding:0 3px}
.rrow{display:flex;align-items:stretch;gap:1px;flex:1}
.rcap{font-size:9px;color:#8a93a3;text-align:center;letter-spacing:.09em;text-transform:uppercase;
 padding:0 2px;line-height:1.5;white-space:nowrap}
.rsep{width:1px;background:var(--line);margin:4px 1px;flex:none}
.rbig{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;
 min-width:46px;padding:2px 6px 1px;border:1px solid transparent;border-radius:3px;background:none;
 font:inherit;font-size:10.5px;line-height:1.15;color:#374151;cursor:default;white-space:nowrap}
.rbig svg{width:20px;height:20px}
.rbig:hover{border-color:#b9c9e2;background:#e8eef8}
.rsm{width:26px;height:25px;display:flex;align-items:center;justify-content:center;flex:none;
 border:1px solid transparent;border-radius:3px;background:none;color:#374151;cursor:default;padding:0;font:inherit}
.rsm svg{width:16px;height:16px}
.rsm:hover{border-color:#b9c9e2;background:#e8eef8}
.rsm.on,.rbig.on{background:#d8e4f6;border-color:#8fb0dd;color:var(--navy)}
.rgrid{display:grid;grid-template-rows:25px 25px;grid-auto-flow:column;gap:1px;align-content:center}
#ribbon .menu>button.rsm{width:32px}
#ribbon .menu .dd{min-width:190px}
/* ============ results explorer (right-hand tabbed attribute tables) ====== */
#pn_results .dbody{padding:0;display:flex;flex-direction:column;min-height:0}
#pn_results{min-width:250px}
.rexwrap{display:flex;flex-direction:column;min-height:0;flex:1}
.rextabs{display:flex;flex-wrap:wrap;gap:3px;padding:7px 8px 6px;border-bottom:1px solid var(--line)}
.rextabs button{font:600 11px/1 inherit;padding:4px 7px;border:1px solid var(--line);background:#f3f6fb;color:#41506a;border-radius:10px;cursor:pointer}
.rextabs button.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.rtabs{display:flex;gap:2px;padding:4px 4px 0;background:transparent}
.rtabs button{flex:1;font:700 12px/1.1 inherit;padding:7px 4px;border:1px solid var(--line);
 border-bottom:0;background:#eef2f9;color:#41506a;border-radius:8px 8px 0 0;cursor:pointer}
.rtabs button.on{background:#fff;color:var(--navy)}
.dpanel.intab>.dhead{display:none}   /* the tab itself names + controls the panel */
select.rextabs{display:block;width:calc(100% - 16px);margin:7px 8px 6px;padding:5px 6px;
 font:600 12px/1.2 inherit;color:var(--navy);border:1px solid var(--line);border-radius:6px;
 background:#f8fafd;cursor:pointer}
select.rexsort{flex:1;min-width:0;font:600 11px/1.2 inherit;color:#41506a;
 border:1px solid var(--line);border-radius:6px;background:#f3f6fb;padding:3px 5px;cursor:pointer}
.rextool{display:flex;align-items:center;gap:6px;padding:6px 8px}
.rextool input{flex:1;min-width:0;padding:4px 7px;border:1px solid #cfd6e2;border-radius:3px;font:inherit;font-size:12px}
.rexcount{font-size:11px;color:var(--mut);white-space:nowrap}
.rexexp{padding:3px 7px;font-size:11px;border:1px solid var(--line);background:#f3f6fb;color:#41506a;border-radius:3px;cursor:pointer}
.rexbody{overflow:auto;min-height:60px;flex:1}
table.rextab{border-collapse:separate;border-spacing:0;width:100%;font-size:11.5px;font-variant-numeric:tabular-nums}
table.rextab th{position:sticky;top:0;background:linear-gradient(#f4f7fc,#e9eef7);color:#243452;font-weight:700;
 text-align:right;padding:6px 9px;cursor:pointer;white-space:nowrap;border-bottom:1px solid #c8d2e2;
 border-right:1px solid rgba(200,210,226,.45);user-select:none;z-index:2;position:sticky}
table.rextab th.txt{text-align:left}
table.rextab th:hover{background:linear-gradient(#eef3fb,#dfe7f4)}
table.rextab th .rz{position:absolute;top:0;right:-3px;width:7px;height:100%;cursor:col-resize;z-index:3}
table.rextab tr.grp th{top:0;background:#e4ebf6;color:#3d4f70;font-size:10px;letter-spacing:.06em;text-transform:uppercase;
 text-align:center;padding:3px 6px;border-bottom:1px solid #d5dde9;cursor:default;z-index:2}
table.rextab.hasgrp thead tr:not(.grp) th{top:22px}
table.rextab td{padding:5px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid #edf1f7;color:#2f3a4d;line-height:1.35}
table.rextab td.txt{text-align:left}
table.rextab tbody tr:nth-child(even) td{background:#f7f9fc}
table.rextab tr[data-map]{cursor:pointer}
table.rextab tr[data-map]:hover td{background:#eaf3ff}
table.rextab tr.sev1 td{background:#fdf4e3}
table.rextab tr.sev2 td{background:#fdeae7}
table.rextab tr.sel td{background:#fdebd7;color:#8a4b12;font-weight:600}
table.rextab th .ar{font-size:9px;color:#5b6b86;margin-left:2px}
.rexsum{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;padding:6px 10px;border-top:1px solid var(--line);
 background:#f6f8fc;font-size:11px;color:#3a4a66;font-variant-numeric:tabular-nums}
.rexsum b{color:var(--navy);font-weight:700;margin-left:3px}
.rexsum .viol{color:#b42318;font-weight:700}.rexsum .ok{color:#1e7a44;font-weight:700}
#rexCtx{position:fixed;z-index:120;background:#fff;border:1px solid #c9d3e2;border-radius:6px;
 box-shadow:0 10px 28px rgba(20,35,70,.18);min-width:190px;padding:4px;display:none;font-size:12px}
#rexCtx a{display:block;padding:6px 11px;border-radius:4px;color:#243452;cursor:pointer;white-space:nowrap}
#rexCtx a:hover{background:#eef4fd}
#rexCtx .csep{height:1px;background:#e6ebf3;margin:4px 6px}
.rexlog{font-size:11.5px}
.rexlog div{padding:3px 9px;border-bottom:1px solid #eef1f6;color:#3a4658;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rexlog time{color:#94a3b8;margin-right:7px;font-variant-numeric:tabular-nums}
.rexkv{width:100%;border-collapse:collapse;font-size:12px}
.rexkv td{padding:5px 9px;border-bottom:1px solid #eef1f6}
.rexkv td:first-child{color:var(--mut);width:46%}
.rexkv tr.hd td{background:#eef2f8;color:#2b3a55;font-weight:700}
.rexempty{padding:18px 12px;color:var(--mut);font-size:12px;text-align:center;line-height:1.5}
#sldTip{position:absolute;z-index:40;pointer-events:none;max-width:250px;background:rgba(23,38,66,0.96);color:#eef2f8;font-size:11.5px;line-height:1.55;padding:7px 10px;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,0.25);border:1px solid #2b4066}
#sldTip b{color:#fff}#sldTip .k{color:#9db4d8;display:inline-block;min-width:52px}
/* ============ workspace: dockable panels around the canvas ============ */
#tab-net{flex:1;min-height:0;display:flex;flex-direction:column}
#ws{flex:1;min-height:0;display:flex;flex-direction:column}
#wsrow{flex:1;min-height:0;display:flex;position:relative}
.dockcol{flex:none;display:flex;flex-direction:column;gap:6px;min-height:0;overflow-y:auto;overflow-x:hidden}
#dockL{width:168px;margin-right:6px}
#dockR{width:254px;margin-left:6px}
#dockB{flex:none;display:flex;align-items:stretch;gap:6px;margin-top:6px;overflow-x:auto;overflow-y:hidden}
.dockcol:empty,#dockB:empty{display:none}
.dpanel{background:var(--card);border:1px solid var(--line);border-radius:3px;display:flex;
 flex-direction:column;min-height:0;flex:none}
.dockcol .dpanel.grow{flex:1;min-height:130px}
#dockB .dpanel{min-width:130px}
.dhead{display:flex;align-items:center;gap:2px;padding:2px 3px 2px 8px;background:#eef0f4;
 border-bottom:1px solid var(--line);font-size:10px;font-weight:600;letter-spacing:.09em;
 text-transform:uppercase;color:#4b5563;border-radius:3px 3px 0 0;flex:none}
.dhead>span{flex:1;white-space:nowrap;overflow:hidden;cursor:grab;padding:3px 0}
.dhb{border:0;background:none;width:19px;height:19px;border-radius:3px;color:#6b7280;
 display:flex;align-items:center;justify-content:center;padding:0;cursor:default;flex:none}
.dhb:hover{background:#dbe2ec;color:var(--navy)}
.dhb svg{width:12px;height:12px}
.dhb.on{color:var(--navy);background:#d8e4f6}
.dbody{padding:7px 8px;overflow:auto;min-height:0}
.dpanel.float{position:fixed;z-index:46;width:236px;max-height:72vh;
 box-shadow:0 10px 34px rgba(16,24,40,.28)}
.dpanel.flyout{position:absolute;z-index:45;width:238px;max-height:82%;
 box-shadow:0 10px 30px rgba(16,24,40,.26)}
.dpanel.dragging{opacity:.88;pointer-events:none}
.dhint{position:absolute;z-index:44;background:rgba(31,59,115,.13);border:2px dashed #2c5aa0;
 border-radius:4px;display:none;pointer-events:none}
#dhL{left:0;top:0;bottom:0;width:130px}
#dhR{right:0;top:0;bottom:0;width:130px}
#dhB{left:0;right:0;bottom:0;height:92px}
.ahstrip{flex:none;display:none;flex-direction:column;gap:4px;padding:4px 2px;background:var(--chrome);
 border:1px solid var(--line);border-radius:3px;z-index:33}
#ahL{margin-right:6px}#ahR{margin-left:6px}
#ahB{flex-direction:row;margin-top:6px;padding:2px 4px}
.ahtab{border:1px solid var(--line);background:#fbfcfd;font:inherit;font-size:10px;font-weight:600;
 letter-spacing:.08em;text-transform:uppercase;color:#4b5563;border-radius:3px;cursor:default;padding:8px 2px}
#ahL .ahtab,#ahR .ahtab{writing-mode:vertical-rl}
#ahB .ahtab{writing-mode:horizontal-tb;padding:2px 9px}
.ahtab:hover,.ahtab.on{color:var(--navy);border-color:#8fb0dd;background:#e8eef8}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:3px}
.pgrid .tbtn,.pflex .tbtn{display:flex;align-items:center;gap:5px;font-size:11.5px;padding:4px 6px;text-align:left}
.pgrid .tbtn svg,.pflex .tbtn svg{width:13px;height:13px;flex:none}
.pflex{display:flex;flex-wrap:wrap;gap:3px}
.psub{font-size:9.5px;color:#8a93a3;letter-spacing:.09em;text-transform:uppercase;margin:7px 0 3px}
.psub:first-child{margin-top:0}
/* single-column component palette (taller not wider) */
.pcol{display:flex;flex-direction:column;gap:2px}
.pcol .tbtn{display:flex;align-items:center;gap:8px;font-size:12px;padding:5px 8px;text-align:left;width:100%}
.pcol .tbtn svg{width:16px;height:16px;flex:none}
/* keep the pointer an ARROW everywhere in the editor (no hand/grab cursor) */
.pcol .tbtn.tool{cursor:default}
#sld,#cwrap{cursor:default!important}
body.dropping,body.dropping *{cursor:default!important}
.pcol .tbtn .kbd{margin-left:auto;font-size:10px;color:#9aa4b2}
.pcol .tbtn.tool.on .kbd{color:#cdddf5}
.pcol .psub{margin:8px 2px 2px}
/* collapse + width-resize */
.dpanel.collapsed>.dbody{display:none}
.dpanel.collapsed{flex:none!important;min-height:0!important}
.dhb.caret svg{transition:transform .12s}
.dpanel.collapsed .dhb.caret svg{transform:rotate(-90deg)}
.dsplit{flex:none;width:6px;cursor:col-resize;background:transparent;position:relative;z-index:18}
.dsplit::after{content:'';position:absolute;top:0;bottom:0;left:2px;width:2px;border-radius:2px;background:transparent}
.dsplit:hover::after,.dsplit.act::after{background:#9fb6da}
.dsplit.hidden{display:none}
/* ============ canvas + minimap ============ */
#cwrap{flex:1;min-width:0;position:relative;background:#fbfcfe;border:1px solid var(--line);
 border-radius:3px;overflow:hidden}
#sld{width:100%;height:100%;background:#fbfcfe;cursor:default;display:block}
#netErr{position:absolute;top:6px;left:8px;right:8px;z-index:30}
#netErr .err{box-shadow:0 3px 12px rgba(16,24,40,.15)}
#mmap{position:absolute;right:10px;bottom:10px;width:186px;height:126px;background:rgba(255,255,255,.95);
 border:1px solid #aab2bf;border-radius:3px;box-shadow:0 2px 10px rgba(16,24,40,.2);z-index:32;
 overflow:hidden;cursor:crosshair}
#mmap svg{width:100%;height:100%;display:block;background:#fbfcfe}
#mmap .mmv{fill:rgba(44,90,160,.15);stroke:#2c5aa0;stroke-width:1.4}
#mmap:hover{box-shadow:0 3px 14px rgba(16,24,40,.3)}
body.fs .dockcol,body.fs #dockB,body.fs .ahstrip{display:none!important}
body.fs #cwrap{border-radius:0}
/* ============ status bar zoom + lock ============ */
#stZoomBox{display:flex;align-items:center;padding:0 2px!important}
#stZoomBox button{border:0;background:none;width:23px;height:23px;font-size:13px;color:#4b5563;
 cursor:default;border-radius:3px;padding:0;font-family:inherit}
#stZoomBox button:hover{background:#e2e6ec;color:var(--navy)}
#stZoomBox #zpct{min-width:44px;text-align:center;font-size:11.5px;padding:0 2px}
#stLock:empty{display:none}
#kbd .mbody table{font-size:12.5px}
#kbd .mbody td:first-child{font-family:Consolas,monospace;color:var(--navy);white-space:nowrap;width:130px}
</style>
<style id="dark-css">
/* ============ Night theme (html.dark) — interface only ============
   Toggled from View ▸ "Night theme"; the SLD workspace and all charts keep
   their day appearance so the heat map and diagram colours read unchanged. */
html.dark{color-scheme:dark}
html.dark body{--bg:#0b1120;--card:#151d2f;--ink:#e2e8f5;--mut:#93a0b8;--line:#2b3650;
 --chrome:#10182b;--navy:#8fb3ef;--navy2:#a9c6f5;
 --gfm:#4fbf7a;--gfl:#e0705f;--gold:#d9b23a;--teal:#3fa7ba;--bess:#c9722e}
/* chrome: menus, ribbon, rail, docks, statusbar */
html.dark .menu.open>button,html.dark .menu>button:hover{background:#1d2a49}
html.dark .menu .dd{background:#151d2f;border-color:#33405f;box-shadow:0 5px 18px rgba(0,0,0,.5)}
html.dark .dd a{color:#dbe3f2}
html.dark .dd a:hover{background:#2c5aa0}
html.dark .dd .chk{color:#9db9f0}
html.dark .dsep{border-top-color:#232d45}
html.dark .rcap,html.dark .psub{color:#7f8ba3}
html.dark .rbig,html.dark .rsm{color:#c6d1e6}
html.dark .rbig:hover,html.dark .rsm:hover{border-color:#3a4a6e;background:#1d2a49}
html.dark .rsm.on,html.dark .rbig.on{background:#233252;border-color:#4a6394;color:#9db9f0}
html.dark .railb{color:#a9b6cf}
html.dark .railb:hover{background:#1d2a49;border-color:#33405f}
html.dark .railb.on{background:#151d2f;border-color:#4a6394;color:#9db9f0;box-shadow:inset 3px 0 0 #6f9ae0}
html.dark .dhead{background:#131b2d;color:#a9b6cf}
html.dark .dhb{color:#8b96ad}
html.dark .dhb:hover{background:#233252;color:#9db9f0}
html.dark .dhb.on{background:#233252;color:#9db9f0}
html.dark .ahtab{background:#131b2d;color:#a9b6cf}
html.dark .ahtab:hover,html.dark .ahtab.on{background:#1d2a49;border-color:#4a6394;color:#9db9f0}
html.dark #statusbar{color:#a9b6cf}
html.dark #statusbar #stMsg{color:#7f8ba3}
html.dark #stZoomBox button{color:#a9b6cf}
html.dark #stZoomBox button:hover{background:#1d2a49;color:#9db9f0}
html.dark .qtool button{color:#a9b6cf}
html.dark .qtool button:hover{background:#1d2a49;border-color:#33405f;color:#9db9f0}
html.dark .dsplit:hover::after,html.dark .dsplit.act::after{background:#4a6394}
html.dark .dhint{background:rgba(44,90,160,.2);border-color:#4a7ac2}
/* content, inputs, tables, chips, modals (shared with the mobile port) */
html.dark .go{background:#2c5aa0;box-shadow:0 1px 2px rgba(0,0,0,.4)}
html.dark .go:hover{background:#3568b5}
html.dark .tbtn{background:linear-gradient(#1c2539,#141c2e);border-color:#33405f;color:#c6d1e6}
html.dark .tbtn.tool.on{background:#2c5aa0;border-color:#2c5aa0;color:#fff}
html.dark #vizBody .tbtn.on{background:#2c5aa0;border-color:#2c5aa0;color:#fff}
html.dark .pbar{background:linear-gradient(90deg,#2c5aa0,#4a7ac2)}
html.dark .tgrp{background:#131b2d}
html.dark select,html.dark input[type=number],html.dark input[type=text],html.dark textarea
 {background:#0e1526;border-color:#33405f;color:#e2e8f5}
html.dark .gear{background:#151d2f;border-color:#33405f;color:#9fb0cc}
html.dark input[type=checkbox],html.dark input[type=range]{accent-color:#5b8ad4}
html.dark th{border-bottom-color:#33405f}
html.dark td{border-bottom-color:#232d45}
html.dark tr.sel td{background:#233252}
html.dark tbody tr:hover td{background:#1a2338}
html.dark .zbad{color:#ff9d90}html.dark .zwarn{color:#e8c27a}html.dark .zok{color:#58c07c}
html.dark .err{background:#2a1517;border-color:#5c2726;color:#f1a09b}
html.dark .sc{background:#151d2f;border-color:#2b3650}
html.dark .badge{background:#1a2338;border-color:#2e3b58}
html.dark .presets button{background:#151d2f;border-color:#33405f;color:#c6d1e6}
html.dark .imgs img{border-color:#2b3650;background:#fff}
html.dark .modal{background:#151d2f}
html.dark .mrow .ghost{background:#151d2f;border-color:#33405f;color:#c6d1e6}
html.dark .prow{border-bottom-color:#232d45}
html.dark .prow b{color:#dbe3f2}
html.dark .prow.chg b{color:#ff9d90}
html.dark .rextabs button{background:#131b2d;border-color:#2e3b58;color:#a9b6cf}
html.dark .rextabs button.on{background:#2c5aa0;border-color:#2c5aa0;color:#fff}
html.dark select.rextabs{background:#131b2d;border-color:#2e3b58;color:#9db9f0}
html.dark select.rexsort{background:#131b2d;border-color:#2e3b58;color:#a9b6cf}
html.dark .rextool input{background:#0e1526;border-color:#33405f;color:#e2e8f5}
html.dark .rexexp{background:#131b2d;border-color:#2e3b58;color:#a9b6cf}
html.dark .rtabs button{background:#131b2d;border-color:#2e3b58;color:#a9b6cf}
html.dark .rtabs button.on{background:#151d2f;color:#9db9f0}
html.dark table.rextab th{background:#1a2338;color:#c3d0e8;border-bottom-color:#33405f;border-right-color:rgba(51,64,95,.5)}
html.dark table.rextab th:hover{background:#20294a}
html.dark table.rextab tr.grp th{background:#161f36;color:#9fb0cc;border-bottom-color:#2b3650}
html.dark table.rextab td{border-bottom-color:#232d45;color:#c6d1e6}
html.dark table.rextab tbody tr:nth-child(even) td{background:#182036}
html.dark table.rextab tr[data-map]:hover td{background:#1d2a49}
html.dark table.rextab tr.sev1 td{background:#2b2211}
html.dark table.rextab tr.sev2 td{background:#2e1616}
html.dark table.rextab tr.sel td{background:#3a2a12;color:#f0c088}
html.dark .rexsum{background:#131b2d;color:#a9b6cf}
html.dark .rexsum .viol{color:#ff9d90}html.dark .rexsum .ok{color:#58c07c}
html.dark .rexkv td{border-bottom-color:#232d45}
html.dark .rexkv tr.hd td{background:#1a2338;color:#c3d0e8}
html.dark .rexlog div{border-bottom-color:#232d45;color:#a9b6cf}
html.dark #rexCtx{background:#151d2f;border-color:#33405f}
html.dark #rexCtx a{color:#dbe3f2}
html.dark #rexCtx a:hover{background:#1d2a49}
html.dark #rexCtx .csep{background:#232d45}
/* night: the canvas surround goes dark; the diagram itself sits on a light
   "paper" sheet drawn by the engine, so heat-map and diagram colours stay in
   their day appearance. Charts stay day. */
html.dark #cwrap{background:#0d1322;border-color:#26304a}
html.dark #sld{background:#0d1322}
html.dark #mmap{background:rgba(21,29,47,.95);border-color:#33405f}
html.dark #mmap svg{background:#0d1322}
</style></head><body>
<script>/* night-theme bootstrap: apply the saved choice before first paint */
try{if(localStorage.getItem('psdat_theme')==='dark'){document.documentElement.classList.add('dark');}}catch(_){}
</script>
<input type="file" id="fopen" accept=".json,.psdat,application/json,text/plain" style="display:none" onchange="openNetFile(this)">
<header>
 <div class="brand"><svg viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#1f3b73"/><circle cx="32" cy="20" r="10" fill="none" stroke="#fff" stroke-width="4.5"/><line x1="32" y1="30" x2="32" y2="40" stroke="#fff" stroke-width="4.5"/><rect x="12" y="40" width="40" height="8" rx="2" fill="#fff"/></svg>PSDAT</div>
 <nav class="menubar" id="menubar">
  <div class="menu"><button>File</button><div class="dd">
    <a onclick="newNet()"><span class="chk"></span>New network</a>
    <a onclick="$('fopen').click()"><span class="chk"></span>Open project / diagram…</a>
    <a onclick="saveNetFile()"><span class="chk"></span>Save diagram</a>
    <a onclick="saveProject()"><span class="chk"></span>Save project (diagram + results, .psdat)</a>
    <a onclick="resetNet()"><span class="chk"></span>Reset — reload a clean network</a>
    <div class="dsep"></div>
    <a onclick="exportPNG()"><span class="chk"></span>Export diagram as PNG</a>
    <a onclick="exportSVG()"><span class="chk"></span>Export diagram as SVG</a></div></div>
  <div class="menu"><button>Edit</button><div class="dd">
    <a onclick="undo()"><span class="chk"></span>Undo<span>Ctrl+Z</span></a>
    <a onclick="redo()"><span class="chk"></span>Redo<span>Ctrl+Y</span></a>
    <div class="dsep"></div>
    <a onclick="selectAll()"><span class="chk"></span>Select all<span>Ctrl+A</span></a>
    <a onclick="rotSel()"><span class="chk"></span>Rotate selection<span>R</span></a>
    <a onclick="flipSel()"><span class="chk"></span>Flip selection<span>F</span></a>
    <a onclick="delSel()"><span class="chk"></span>Delete selection<span>Del</span></a>
    <div class="dsep"></div>
    <a onclick="alignSel('l')"><span class="chk"></span>Align left</a>
    <a onclick="alignSel('c')"><span class="chk"></span>Align centre</a>
    <a onclick="alignSel('r')"><span class="chk"></span>Align right</a>
    <a onclick="alignSel('t')"><span class="chk"></span>Align top</a>
    <a onclick="alignSel('m')"><span class="chk"></span>Align middle</a>
    <a onclick="alignSel('b')"><span class="chk"></span>Align bottom</a>
    <div class="dsep"></div>
    <a onclick="distSel('h')"><span class="chk"></span>Distribute horizontally</a>
    <a onclick="distSel('v')"><span class="chk"></span>Distribute vertically</a></div></div>
  <div class="menu"><button>View</button><div class="dd">
    <a onclick="fitView()"><span class="chk"></span>Zoom to fit<span>A</span></a>
    <a onclick="zoomSel()"><span class="chk"></span>Zoom to selection<span>S</span></a>
    <a onclick="zoomBtn(1.25)"><span class="chk"></span>Zoom in<span>+</span></a>
    <a onclick="zoomBtn(0.8)"><span class="chk"></span>Zoom out<span>−</span></a>
    <a onclick="fsToggle()"><span class="chk" id="vFs" style="visibility:hidden">✓</span>Full-screen editing<span>F11</span></a>
    <div class="dsep"></div>
    <a onclick="tgl('grid')"><span class="chk" id="vGrid">✓</span>Grid &amp; snap</a>
    <a onclick="tgl('ortho')"><span class="chk" id="vOrtho" style="visibility:hidden">✓</span>Orthogonal routing<span>O</span></a>
    <a onclick="lblAll()"><span class="chk" id="vLbl">✓</span>Labels</a>
    <a onclick="tgl('anim')"><span class="chk" id="vAnim" style="visibility:hidden">✓</span>Flow arrows</a>
    <a onclick="tgl('critL')"><span class="chk" id="vCritL" style="visibility:hidden">✓</span>Critical lines</a>
    <a onclick="tgl('critB')"><span class="chk" id="vCritB" style="visibility:hidden">✓</span>Critical buses</a>
    <a onclick="tgl('cont')"><span class="chk" id="vCont" style="visibility:hidden">✓</span>Voltage contour</a>
    <a onclick="mmToggle()"><span class="chk" id="vMmap">✓</span>Mini-map (navigator)<span>M</span></a>
    <a onclick="openViz()"><span class="chk"></span>Visualization settings…</a>
    <a onclick="toggleNight()"><span class="chk" id="vNight" style="visibility:hidden">✓</span>Night theme (interface only)</a>
    <a onclick="setCMode(CMODE==='dynamic'?'fixed':'dynamic')"><span class="chk" id="vCmode" style="visibility:hidden">✓</span>Component colours by value (heat scale)</a>
    <div class="dsep"></div>
    <a onclick="pnToggle('model')"><span class="chk" id="vP_model">✓</span>Test system panel</a>
    <a onclick="pnToggle('draw')"><span class="chk" id="vP_draw">✓</span>Draw palette</a>
    <a onclick="pnToggle('fleet')"><span class="chk" id="vP_fleet">✓</span>Fleet panel</a>
    <a onclick="pnToggle('props')"><span class="chk" id="vP_props">✓</span>Properties panel</a>
    <a onclick="pnToggle('results')"><span class="chk" id="vP_results">✓</span>Results explorer</a>
    <a onclick="pnToggle('data')"><span class="chk" id="vP_data">✓</span>Data panel (parameters &amp; input)</a>
    <a onclick="restoreLayout()"><span class="chk"></span>Restore default layout</a>
    <div class="dsep"></div>
    <a onclick="applyUI(UIS+0.05,true)"><span class="chk"></span>Interface larger<span>Ctrl +</span></a>
    <a onclick="applyUI(UIS-0.05,true)"><span class="chk"></span>Interface smaller<span>Ctrl −</span></a>
    <a onclick="applyUI(1,true)"><span class="chk"></span>Interface size reset<span>Ctrl 0</span></a></div></div>
  <div class="menu"><button>Network</button><div class="dd">
    <a onclick="newNet()"><span class="chk"></span>New empty network</a>
    <div class="dsep"></div>
    <a onclick="goTab('net');setTool('select')"><span class="chk"></span>Select / move tool<span>V</span></a>
    <a onclick="goTab('net');setTool('addbus')"><span class="chk"></span>Add bus tool<span>B</span></a>
    <a onclick="goTab('net');setTool('addline')"><span class="chk"></span>Add line tool<span>L</span></a>
    <a onclick="goTab('net');setTool('addgen')"><span class="chk"></span>Add generator tool<span>G</span></a>
    <a onclick="goTab('net');setTool('delete')"><span class="chk"></span>Delete tool<span>X</span></a></div></div>
  <div class="menu"><button>Layout</button><div class="dd">
    <a onclick="layAuto()" title="picks the best algorithm for this graph's shape"><span class="chk"></span>Auto (smart)</a>
    <a onclick="autoArrange()"><span class="chk"></span>Force-directed</a>
    <a onclick="layHierV()"><span class="chk"></span>Hierarchical (Sugiyama)</a>
    <a onclick="layTree()"><span class="chk"></span>Tree</a>
    <a onclick="layRadial()"><span class="chk"></span>Radial</a>
    <a onclick="layCircular()"><span class="chk"></span>Circular</a>
    <a onclick="layGrid()"><span class="chk"></span>Grid</a>
    <a onclick="autoArrangeFull()" title="force-directed + orient + grid snap + right-angle routing"><span class="chk"></span>Orthogonal (grid-snapped)</a>
    <a onclick="layKK()"><span class="chk"></span>Kamada-Kawai</a>
    <a onclick="tidyLayout()" title="levels by electrical distance from the slack, crossings minimised"><span class="chk"></span>Electrical (levels from slack)<span>T</span></a>
    <a onclick="beautify()"><span class="chk"></span>Beautify (snap + route)</a>
    <div class="dsep"></div>
    <a onclick="cmdBarycenter()"><span class="chk"></span>Min. crossings</a>
    <a onclick="cmdEqual()"><span class="chk"></span>Equal spacing</a>
    <a onclick="cmdStraighten()"><span class="chk"></span>Straighten</a>
    <a onclick="layCompact()"><span class="chk"></span>Compact</a>
    <a onclick="layExpand()"><span class="chk"></span>Expand</a>
    <div class="dsep"></div>
    <a onclick="layRestore()"><span class="chk"></span>Restore default</a></div></div>
  <div class="menu"><button>Analysis</button><div class="dd">
    <a onclick="goTab('net');runPF()"><span class="chk"></span>Run power flow</a>
    <a onclick="useNet()"><span class="chk"></span>Use diagram in analysis</a>
    <div class="dsep"></div>
    <a onclick="goTab('ss')"><span class="chk"></span>Small-signal analysis…</a>
    <a onclick="goTab('ds')"><span class="chk"></span>Design &amp; sweeps…</a></div></div>
  <div class="menu"><button>Simulation</button><div class="dd">
    <a onclick="goTab('td')"><span class="chk"></span>Time-domain simulation…</a>
    <a onclick="goTab('td');runT()"><span class="chk"></span>Run with current settings</a>
    <div class="dsep"></div>
    <a onclick="goTab('sc')"><span class="chk"></span>Guided scenarios…</a></div></div>
  <div class="menu"><button>Reports</button><div class="dd">
    <a onclick="goTab('net');runPF()"><span class="chk"></span>Power-flow summary</a>
    <div class="dsep"></div>
    <a onclick="exportPNG()"><span class="chk"></span>Export diagram as PNG</a>
    <a onclick="exportSVG()"><span class="chk"></span>Export diagram as SVG</a>
    <a onclick="saveNetFile()"><span class="chk"></span>Save network data (.json)</a></div></div>
  <div class="menu"><button>Tools</button><div class="dd">
    <a onclick="resetNet()"><span class="chk"></span>Reset — reload a clean network</a>
    <div class="dsep"></div>
    <a onclick="setLock(true)"><span class="chk" id="vLock" style="visibility:hidden">✓</span>Lock layout<span>K</span></a>
    <a onclick="setLock(false)"><span class="chk"></span>Unlock layout</a>
    <div class="dsep"></div>
    <a onclick="tgl('grid')"><span class="chk" id="vGrid2">✓</span>Snap to grid</a>
    <a onclick="tgl('ortho')"><span class="chk" id="vOrtho2" style="visibility:hidden">✓</span>Orthogonal routing</a>
    <div class="dsep"></div>
    <a onclick="kbdShow()"><span class="chk"></span>Keyboard shortcuts…</a>
    <a onclick="restoreLayout()"><span class="chk"></span>Restore default layout</a>
    <div class="dsep"></div>
    <a onclick="scadaToggle()"><span class="chk" id="vScada" style="visibility:hidden">✓</span>SCADA operator mode</a>
    <a onclick="scadaOpen('alarms')"><span class="chk"></span>Alarms &amp; events…</a>
    <a onclick="scadaOpen('se')"><span class="chk"></span>State estimation…</a>
    <a onclick="scadaOpen('drill')"><span class="chk"></span>Disturbance drill…</a></div></div>
  <div class="menu"><button>Help</button><div class="dd">
    <a onclick="goTab('help')"><span class="chk"></span>About PSDAT</a>
    <a onclick="kbdShow()"><span class="chk"></span>Keyboard shortcuts…</a></div></div>
 </nav>
 <div class="hspring"></div>
</header>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg"><defs>
 <g id="icd" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></g>
 <symbol id="i-cursor" viewBox="0 0 24 24"><path d="M5.5 3.5 11.7 19.5 13.6 12.9 20.2 11z" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-bus" viewBox="0 0 24 24"><path d="M4 14h16" stroke="currentColor" stroke-width="3" stroke-linecap="round"/><path d="M9 14V7M15 14V7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></symbol>
 <symbol id="i-line" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="5" r="2.2"/><path d="M6.6 17.4 17.4 6.6"/></symbol>
 <symbol id="i-gen" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="7.6"/><path d="M8.6 12c1.1-2.6 2.3-2.6 3.4 0s2.3 2.6 3.4 0"/></symbol>
 <symbol id="i-del" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 7h14M10 7V4.5h4V7M7.5 7l1 13h7l1-13M10.3 10.5v6M13.7 10.5v6"/></symbol>
 <symbol id="i-undo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 5 4.5 9l4 4"/><path d="M4.5 9H14a5.5 5.5 0 0 1 5.5 5.5V17"/></symbol>
 <symbol id="i-redo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M15.5 5l4 4-4 4"/><path d="M19.5 9H10a5.5 5.5 0 0 0-5.5 5.5V17"/></symbol>
 <symbol id="i-rot" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M17.6 3.4v4.1h-4.1"/></symbol>
 <symbol id="i-flip" viewBox="0 0 24 24" stroke-linejoin="round"><path d="M12 3.5v17" stroke="currentColor" stroke-width="1.4" stroke-dasharray="2.5 2.5"/><path d="M9 8 4 12l5 4z" fill="currentColor" stroke="none"/><path d="M15 8l5 4-5 4z" fill="none" stroke="currentColor" stroke-width="1.6"/></symbol>
 <symbol id="i-arrange" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M7.4 7.2 16.6 8.9M16.9 10.3 8.3 16.6M7.2 8.5l1 6.6"/><circle cx="6.5" cy="6.5" r="2.1"/><circle cx="18" cy="9" r="2.1"/><circle cx="8.8" cy="18" r="2.1"/><path d="M17 15.5v5M14.5 18h5" stroke-width="1.9"/></symbol>
 <symbol id="i-autoarr" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4.5 19.5 13 11"/><path d="M15.5 3.5v5M13 6h5"/><path d="M19.5 11.5v3M18 13h3"/><path d="M9.5 4.5v3M8 6h3"/></symbol>
 <symbol id="i-tidy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 5.5h14M7.5 12h9M5 18.5h14"/><path d="M9.5 5.5V12M14.5 12v6.5" stroke-width="1.4"/></symbol>
 <symbol id="i-beauty" viewBox="0 0 24 24" stroke-linejoin="round"><path d="M11 5.5l1.5 4.2 4.2 1.5-4.2 1.5L11 17l-1.5-4.3-4.2-1.5 4.2-1.5z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M18.5 4v4M16.5 6h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M18 15.5v3.5M16.2 17.2h3.6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></symbol>
 <symbol id="i-contour" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><ellipse cx="12" cy="12" rx="8.5" ry="6.5"/><ellipse cx="12" cy="12" rx="4.7" ry="3.3"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-critl" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 19.5 9 15M16.5 9.5 21 6.5"/><path d="M14.2 5.5l-3.7 5h3.6l-2.6 5.5"/></symbol>
 <symbol id="i-critb" viewBox="0 0 24 24" stroke-linecap="round"><path d="M4.5 17.5h15" stroke="currentColor" stroke-width="2.8"/><path d="M12 4.5v7M12 14.2v.4" stroke="currentColor" stroke-width="2"/></symbol>
 <symbol id="i-flow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12H12"/><path d="M9.5 7.8l4.2 4.2-4.2 4.2M15.5 7.8l4.2 4.2-4.2 4.2"/></symbol>
 <symbol id="i-sliders" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9"/><circle cx="15" cy="7.5" r="2.1" fill="#fff"/><circle cx="9" cy="16.5" r="2.1" fill="#fff"/></symbol>
 <symbol id="i-lpf" viewBox="0 0 24 24"><rect x="2.6" y="7" width="18.8" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.4" font-size="7.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">MW</text></symbol>
 <symbol id="i-lv" viewBox="0 0 24 24"><rect x="3.5" y="7" width="17" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.6" font-size="8.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">V</text></symbol>
 <symbol id="i-lbus" viewBox="0 0 24 24"><rect x="3.5" y="7" width="17" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.8" font-size="9" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">#</text></symbol>
 <symbol id="i-lline" viewBox="0 0 24 24"><rect x="3.5" y="7" width="17" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.6" font-size="8.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">L</text></symbol>
 <symbol id="i-lgen" viewBox="0 0 24 24"><rect x="3.5" y="7" width="17" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.6" font-size="8.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">G</text></symbol>
 <symbol id="i-lload" viewBox="0 0 24 24"><rect x="2.6" y="7" width="18.8" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="15.4" font-size="7.6" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none" font-family="Segoe UI,sans-serif">PQ</text></symbol>
 <symbol id="i-showlab" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M2.5 12S6.5 5.8 12 5.8 21.5 12 21.5 12 17.5 18.2 12 18.2 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/></symbol>
 <symbol id="i-hidelab" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 12S6.5 5.8 12 5.8 21.5 12 21.5 12a17.6 17.6 0 0 1-3 3.3M9.5 17.7A11 11 0 0 1 2.5 12"/><path d="M4 4l16 16"/></symbol>
 <symbol id="i-zoomfit" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 8.5V4h4.5M15.5 4H20v4.5M20 15.5V20h-4.5M8.5 20H4v-4.5"/><rect x="9" y="9.2" width="6" height="5.6" rx="0.8" stroke-width="1.5"/></symbol>
 <symbol id="i-zoomsel" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="3.5" y="3.5" width="12" height="12" rx="1" stroke-dasharray="3 2.2"/><circle cx="15.7" cy="15.7" r="4.1"/><path d="M18.8 18.8 21.5 21.5"/></symbol>
 <symbol id="i-mmap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4.5" width="18" height="15" rx="1.6"/><rect x="12.5" y="12.5" width="5.6" height="4.4" fill="currentColor" opacity="0.4" stroke="none"/><path d="M6.5 8h5M6.5 11.5h3" stroke-width="1.3"/></symbol>
 <symbol id="i-fs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M9 4H4v5M4 4l6.2 6.2M15 20h5v-5M20 20l-6.2-6.2"/></symbol>
 <symbol id="i-snap" viewBox="0 0 24 24"><g fill="currentColor" stroke="none"><circle cx="5" cy="5" r="1.4"/><circle cx="12" cy="5" r="1.4"/><circle cx="19" cy="5" r="1.4"/><circle cx="5" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/><circle cx="5" cy="19" r="1.4"/><circle cx="12" cy="19" r="1.4"/><circle cx="19" cy="19" r="1.4"/></g><rect x="9.2" y="9.2" width="5.6" height="5.6" rx="1" fill="none" stroke="currentColor" stroke-width="1.6"/></symbol>
 <symbol id="i-ortho" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 4.5V15a3.5 3.5 0 0 0 3.5 3.5h9.5"/><path d="M15.5 15.5l3 3-3 3"/></symbol>
 <symbol id="i-align" viewBox="0 0 24 24" stroke-linecap="round"><path d="M4.5 3.5v17" stroke="currentColor" stroke-width="1.9"/><rect x="7.5" y="6" width="11.5" height="3.6" rx="0.8" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="7.5" y="14" width="7" height="3.6" rx="0.8" fill="none" stroke="currentColor" stroke-width="1.5"/></symbol>
 <symbol id="i-dist" viewBox="0 0 24 24"><rect x="3.5" y="7" width="3.4" height="10" rx="0.8" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="10.3" y="7" width="3.4" height="10" rx="0.8" fill="none" stroke="currentColor" stroke-width="1.5"/><rect x="17.1" y="7" width="3.4" height="10" rx="0.8" fill="none" stroke="currentColor" stroke-width="1.5"/></symbol>
 <symbol id="i-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><rect x="5.5" y="10.5" width="13" height="9" rx="1.6"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/><path d="M12 14v2.5" stroke-linecap="round"/></symbol>
 <symbol id="i-unlock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><rect x="5.5" y="10.5" width="13" height="9" rx="1.6"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 6.9-.8"/><path d="M12 14v2.5" stroke-linecap="round"/></symbol>
 <symbol id="i-new" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M7 3.5h6.5L18.5 8.5V20.5H7z"/><path d="M13.5 3.5v5h5"/><path d="M10.2 14.5h5.6M13 11.7v5.6" stroke-linecap="round"/></symbol>
 <symbol id="i-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.5 18V5.5h5.6l2 2h9.4V10"/><path d="M3.5 18l2.4-8h15.6l-2.3 8z"/></symbol>
 <symbol id="i-save" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5V14M8 10.5l4 4 4-4"/><path d="M4 19.5h16"/></symbol>
 <symbol id="i-png" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="4.5" width="18" height="15" rx="1.6"/><circle cx="8.4" cy="9.7" r="1.5"/><path d="M4.5 17.5l5-5 3.6 3.6 2.9-2.9 3.5 3.5"/></symbol>
 <symbol id="i-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M5 17.5C8.5 6 15.5 20.5 19.5 6.5"/><rect x="3" y="16" width="3.6" height="3.6" fill="currentColor" stroke="none"/><rect x="17.7" y="4.6" width="3.6" height="3.6" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-pf" viewBox="0 0 24 24"><path d="M13.2 3 5.5 13.5h5.2L9.5 21l8-11h-5.3z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></symbol>
 <symbol id="i-use" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.5l5.5 5.5L20 6.5"/></symbol>
 <symbol id="i-pin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M9.5 3.5h5l-.8 6 2.8 3v1.8H7.5V12.5l2.8-3z"/><path d="M12 14.5V20" stroke-linecap="round"/></symbol>
 <symbol id="i-close" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></symbol>
 <symbol id="i-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></symbol>
 <symbol id="i-float" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="8.5" y="4" width="12" height="9" rx="1.2"/><rect x="3.5" y="11" width="12" height="9" rx="1.2"/></symbol>
 <symbol id="i-reset" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 11a7.5 7.5 0 1 1 1.6 5.4"/><path d="M4.2 5.5v4.2h4.2"/></symbol>
 <symbol id="i-report" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5h8L18.5 8v12.5H6z"/><path d="M13.5 3.5V8h5"/><path d="M8.5 12.5h7M8.5 15.5h7M8.5 9.5h3"/></symbol>
 <symbol id="i-print" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M7 9V4h10v5"/><rect x="4.5" y="9" width="15" height="7" rx="1.4"/><path d="M7 14h10v5.5H7z"/><circle cx="16.4" cy="11.6" r="0.9" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-export" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4.5M8 8l4-3.5 4 3.5"/><path d="M5 14.5v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"/></symbol>
 <symbol id="i-run" viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-m-diagram" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 8h6M4 16h9" stroke-width="2.4"/><path d="M7 8v8M13 16V6" stroke-width="1.5"/><circle cx="18.5" cy="6" r="2.4"/></symbol>
 <symbol id="i-m-ss" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 5v14h16" /><path d="M6 15c2-6 3.5-6 5 0M11 12c1.3-8 2.6-4 3.5 1s1.8 2 3.5-4" stroke-width="1.5"/></symbol>
 <symbol id="i-m-td" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="8.2"/><path d="M12 7v5l3.4 2"/></symbol>
 <symbol id="i-m-ds" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M5 6h14M5 12h14M5 18h14"/><circle cx="9" cy="6" r="2" fill="#fff"/><circle cx="15" cy="12" r="2" fill="#fff"/><circle cx="8" cy="18" r="2" fill="#fff"/></symbol>
 <symbol id="i-m-sc" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3.5h6M10 3.5v6l-4.3 7.8A2 2 0 0 0 7.5 20.5h9a2 2 0 0 0 1.8-3.2L14 9.5v-6"/><path d="M8.4 14h7.2" stroke-width="1.3"/></symbol>
 <symbol id="i-m-help" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="8.4"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.6 1.3c0 1.7-2.2 2-2.2 3.5"/><path d="M12 17.2v.3"/></symbol>
 <symbol id="i-m-st" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3.5 4.5v15h16.5"/><path d="M6 7.5h8.5a3.6 3.6 0 0 1 0 7.2H8.5" stroke-width="1.6"/><circle cx="18.1" cy="11.1" r="1.4" fill="currentColor" stroke="none"/></symbol>
 <symbol id="i-m-ln" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.5 2.8 9l9.2 4.5L21.2 9z"/><path d="M6.5 11.6v4.3c0 1.3 2.5 2.6 5.5 2.6s5.5-1.3 5.5-2.6v-4.3"/><path d="M21.2 9v5.2"/></symbol>
 <symbol id="i-m-pv" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="17.6" cy="5.8" r="2.4"/><path d="M17.6 1.6v1M21.8 5.8h-1M20.6 2.8l-.7.7M20.6 8.8l-.7-.7"/><path d="M3 19.5h13.4L13.9 11.6H5.5z"/><path d="M6.6 11.6l-1.2 7.9M9.7 11.6v7.9M12.8 11.6l1.2 7.9M4.8 14.2h10M4.1 16.9h11.4"/></symbol>
 <symbol id="i-xfmr" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="9" cy="12" r="5.2"/><circle cx="15" cy="12" r="5.2"/></symbol>
 <symbol id="i-dbl" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M5.5 17.5 15 8M8 20l9.5-9.5"/><circle cx="4.4" cy="18.6" r="1.7"/><circle cx="18.6" cy="9.4" r="1.7"/></symbol>
 <symbol id="i-load" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5v10"/><path d="M7.5 10.5 12 15l4.5-4.5"/><path d="M6 19.5h12" stroke-width="2"/></symbol>
 <symbol id="i-cap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 3.5v6M12 14.5v6"/><path d="M5.5 9.5h13M5.5 14.5h13"/></symbol>
 <symbol id="i-react" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 3.5v3"/><path d="M6 7c0-2 3-2 3 0s-3 2-3 4 3 2 3 0M15 7c0-2 3-2 3 0s-3 2-3 4 3 2 3 0" transform="rotate(90 12 12)"/><path d="M12 17.5v3"/></symbol>
 <symbol id="i-note" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5.5h14v9l-4 4H5z"/><path d="M15 18.5v-4h4"/><path d="M8 9.5h8M8 12.5h5" stroke-width="1.3"/></symbol>
 <symbol id="i-collapse" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10l5 5 5-5"/></symbol>
</defs></svg>
<div id="ribbon">
 <div class="rgrp"><div class="rrow">
   <button class="rsm" onclick="undo()" title="Undo (Ctrl+Z)"><svg><use href="#i-undo"/></svg></button>
   <button class="rsm" onclick="redo()" title="Redo (Ctrl+Y)"><svg><use href="#i-redo"/></svg></button>
   <button class="rsm" onclick="saveNetFile()" title="Save diagram (.json)"><svg><use href="#i-save"/></svg></button>
   <button class="rsm" onclick="resetNet()" title="Reset — reload a clean, solvable network (recover from any error)"><svg><use href="#i-reset"/></svg></button>
  </div><div class="rcap">edit</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" onclick="rq(autoArrange)" title="Arrange — force-directed untangle: spread the buses apart, no overlaps"><svg><use href="#i-arrange"/></svg></button>
   <button class="rsm" onclick="rq(autoArrangeFull)" title="Auto Arrange — full pipeline: untangle, orient bars, re-seat machines, right-angle route, fit"><svg><use href="#i-autoarr"/></svg></button>
   <button class="rsm" onclick="rq(tidyLayout)" title="Tidy (T) — graph-theoretic levelled layout: minimised crossings, straight runs"><svg><use href="#i-tidy"/></svg></button>
   <button class="rsm" onclick="rq(beautify)" title="Beautify — snap to grid, orient bars, re-seat machines, right-angle route"><svg><use href="#i-beauty"/></svg></button>
   <button class="rsm" id="rbOrtho" onclick="rq(()=>tgl('ortho'))" title="Orthogonal (O) — right-angle substation routing that never crosses a bar"><svg><use href="#i-ortho"/></svg></button>
   <button class="rsm on" id="rbGrid" onclick="rq(()=>tgl('grid'))" title="Snap to Grid — grid dots + snap while drawing and moving"><svg><use href="#i-snap"/></svg></button>
   <div class="menu"><button class="rsm" title="Layout catalogue — ALL the arrangement methods (the MATLAB edition's list)"><svg style="width:8px;height:8px"><use href="#i-caret"/></svg></button>
    <div class="dd">
     <a onclick="rq(layAuto)"><span class="chk"></span>Auto (smart)</a>
     <a onclick="rq(autoArrange)"><span class="chk"></span>Force-directed</a>
     <a onclick="rq(layHierV)"><span class="chk"></span>Hierarchical (Sugiyama)</a>
     <a onclick="rq(layTree)"><span class="chk"></span>Tree</a>
     <a onclick="rq(layRadial)"><span class="chk"></span>Radial</a>
     <a onclick="rq(layCircular)"><span class="chk"></span>Circular</a>
     <a onclick="rq(layGrid)"><span class="chk"></span>Grid</a>
     <a onclick="rq(autoArrangeFull)"><span class="chk"></span>Orthogonal (grid-snapped)</a>
     <a onclick="rq(layKK)"><span class="chk"></span>Kamada-Kawai</a>
     <a onclick="rq(tidyLayout)"><span class="chk"></span>Electrical (levels from slack)</a>
     <a onclick="rq(beautify)"><span class="chk"></span>Beautify (snap + route)</a>
     <div class="dsep"></div>
     <a onclick="rq(cmdBarycenter)"><span class="chk"></span>Min. crossings</a>
     <a onclick="rq(cmdEqual)"><span class="chk"></span>Equal spacing</a>
     <a onclick="rq(cmdStraighten)"><span class="chk"></span>Straighten</a>
     <a onclick="rq(layCompact)"><span class="chk"></span>Compact</a>
     <a onclick="rq(layExpand)"><span class="chk"></span>Expand</a>
     <div class="dsep"></div>
     <a onclick="rq(layRestore)"><span class="chk"></span>Restore default</a></div></div>
  </div><div class="rcap">layout</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <div class="menu"><button class="rsm" title="Align — line up the box-selected buses"><svg><use href="#i-align"/></svg></button>
    <div class="dd">
     <a onclick="alignSel('l')"><span class="chk"></span>Align left</a>
     <a onclick="alignSel('c')"><span class="chk"></span>Align centre</a>
     <a onclick="alignSel('r')"><span class="chk"></span>Align right</a>
     <div class="dsep"></div>
     <a onclick="alignSel('t')"><span class="chk"></span>Align top</a>
     <a onclick="alignSel('m')"><span class="chk"></span>Align middle</a>
     <a onclick="alignSel('b')"><span class="chk"></span>Align bottom</a></div></div>
   <div class="menu"><button class="rsm" title="Distribute — space the box-selected buses evenly"><svg><use href="#i-dist"/></svg></button>
    <div class="dd">
     <a onclick="distSel('h')"><span class="chk"></span>Distribute horizontally</a>
     <a onclick="distSel('v')"><span class="chk"></span>Distribute vertically</a></div></div>
  </div><div class="rcap">align</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" id="rbLabels" onclick="lblAll()" title="Labels — show / hide ALL diagram labels (one click, like the MATLAB edition)"><svg><use href="#i-lpf"/></svg></button>
   <div class="menu"><button class="rsm" title="choose WHICH label classes show"><svg style="width:8px;height:8px"><use href="#i-caret"/></svg></button>
    <div class="dd">
     <a onclick="tglL('pf')"><span class="chk" id="ckPf">✓</span>Power-flow labels</a>
     <a onclick="tglL('volt')"><span class="chk" id="ckVolt">✓</span>Voltage labels</a>
     <a onclick="tglL('bus')"><span class="chk" id="ckBus">✓</span>Bus numbers</a>
     <a onclick="tglL('lname')"><span class="chk" id="ckLn">✓</span>Line names</a>
     <a onclick="tglL('gen')"><span class="chk" id="ckGen">✓</span>Generator labels</a>
     <a onclick="tglL('load')"><span class="chk" id="ckLoad">✓</span>Load labels</a>
     <div class="dsep"></div>
     <a onclick="lblAll(true)"><span class="chk"></span>Show all labels</a>
     <a onclick="lblAll(false)"><span class="chk"></span>Hide all labels</a></div></div>
   <button class="rsm" id="rbCont" onclick="rq(()=>tgl('cont'))" title="Contour — smooth voltage colour field (run a power flow first)"><svg><use href="#i-contour"/></svg></button>
   <button class="rsm" id="rbAnim" onclick="rq(()=>tgl('anim'))" title="Flow Arrows — animated arrowheads marching in the flow direction"><svg><use href="#i-flow"/></svg></button>
   <button class="rsm" onclick="flowSpeed(-1)" title="Flow arrows — slower" style="font:700 15px/1 Georgia,serif">−</button>
   <button class="rsm" onclick="flowSpeed(1)" title="Flow arrows — faster" style="font:700 14px/1 Georgia,serif">+</button>
   <button class="rsm" id="rbCritL" onclick="rq(()=>tgl('critL'))" title="Critical Lines — colour by loading: amber ≥80%, red ≥100%"><svg><use href="#i-critl"/></svg></button>
   <button class="rsm" id="rbCritB" onclick="rq(()=>tgl('critB'))" title="Critical Buses — colour by voltage violation (LOW red/amber · HIGH blue/violet)"><svg><use href="#i-critb"/></svg></button>
   <button class="rsm" onclick="openViz()" title="Visualization settings — arrow speed/size, heat-map density/transparency, contour smoothing, label size &amp; classes"><svg><use href="#i-sliders"/></svg></button>
  </div><div class="rcap">visualize</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" onclick="runActive()" title="Run — power flow on the diagram, or the current analysis"><svg><use href="#i-run"/></svg></button>
   <button class="rsm" onclick="resetActive()" title="Reset — clear the current results / disturbance back to defaults"><svg><use href="#i-reset"/></svg></button>
  </div><div class="rcap">run</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" onclick="reportPF()" title="Report — power-flow summary"><svg><use href="#i-report"/></svg></button>
   <div class="menu"><button class="rsm" title="Export — PNG / SVG / data"><svg><use href="#i-export"/></svg></button>
    <div class="dd">
     <a onclick="exportPNG()"><span class="chk"></span>Export PNG image</a>
     <a onclick="exportSVG()"><span class="chk"></span>Export SVG vector</a>
     <a onclick="saveNetFile()"><span class="chk"></span>Save network data (.json)</a></div></div>
   <button class="rsm" onclick="printDiagram()" title="Print — opens a printable report of the diagram + results in your browser"><svg><use href="#i-print"/></svg></button>
  </div><div class="rcap">results</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm tool on" id="rbSelect" data-tool="select" onclick="rq(()=>setTool('select'))" title="Select / move (V) — the default pointer tool"><svg><use href="#i-cursor"/></svg></button>
   <button class="rsm" onclick="rq(()=>fitView())" title="Zoom Fit (A) — bring the whole diagram into view"><svg><use href="#i-zoomfit"/></svg></button>
   <button class="rsm" onclick="rq(zoomSel)" title="Zoom to Selection (S) — fill the view with the selection"><svg><use href="#i-zoomsel"/></svg></button>
   <button class="rsm on" id="rbMmap" onclick="rq(mmToggle)" title="Mini-map / Navigator (M) — click to recentre · drag a box to zoom into that region"><svg><use href="#i-mmap"/></svg></button>
   <button class="rsm" id="rbFs" onclick="fsToggle()" title="Full-Screen Editing (F11) — canvas fills the screen; F11/Esc to leave"><svg><use href="#i-fs"/></svg></button>
  </div><div class="rcap">view</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" id="rbLock" onclick="rq(()=>setLock(true))" title="Lock Layout (K) — freeze the geometry"><svg><use href="#i-lock"/></svg></button>
   <button class="rsm on" id="rbUnlock" onclick="rq(()=>setLock(false))" title="Unlock Layout (K) — allow editing"><svg><use href="#i-unlock"/></svg></button>
  </div><div class="rcap">protect</div></div>
 <div class="rsep"></div>
 <div class="rgrp"><div class="rrow">
   <button class="rsm" onclick="rotSel()" title="Rotate the selection (R)"><svg><use href="#i-rot"/></svg></button>
   <button class="rsm" onclick="flipSel()" title="Flip the selection (F)"><svg><use href="#i-flip"/></svg></button>
   <button class="rsm tool" data-tool="delete" onclick="setTool('delete')" title="Delete — click an element to remove it (X)"><svg><use href="#i-del"/></svg></button>
  </div><div class="rcap">modify</div></div>
 <div class="hspring"></div>
</div>
<div id="scban" style="display:none"><span class="dot"></span><span class="txt"></span><span class="cnt"></span></div>
<div class="wrap">
 <nav id="rail">
  <button class="railb on" data-t="net" onclick="goTab('net')" title="Single-line diagram editor"><svg><use href="#i-m-diagram"/></svg>Diagram</button>
  <button class="railb" data-t="ss" onclick="goTab('ss')" title="Small-signal: exact linearization, modes, damping, participation"><svg><use href="#i-m-ss"/></svg>Signal</button>
  <button class="railb" data-t="td" onclick="goTab('td')" title="Time-domain nonlinear simulation"><svg><use href="#i-m-td"/></svg>Time</button>
  <button class="railb" data-t="ds" onclick="goTab('ds')" title="Design: sweeps, root loci, POD, Bode"><svg><use href="#i-m-ds"/></svg>Design</button>
  <button class="railb" data-t="sc" onclick="goTab('sc')" title="Guided scenarios from the manual"><svg><use href="#i-m-sc"/></svg>Scenar.</button>
  <button class="railb" data-t="st" onclick="goTab('st')" title="Course studies: P–V curves, N-1 screening, short-circuit levels, critical clearing time, dispatch &amp; LMP, PMU placement"><svg><use href="#i-m-st"/></svg>Studies</button>
  <button class="railb" data-t="ln" onclick="goTab('ln')" title="Learn: guided lessons, a quiz generated from your own network, the equal-area lab and a glossary"><svg><use href="#i-m-ln"/></svg>Learn</button>
  <button class="railb" data-t="pvl" onclick="goTab('pvl')" title="PV Lab — deep-dive photovoltaics: I-V curves, partial shading &amp; bypass diodes, MPPT algorithms, reserve &amp; capability, daily energy"><svg><use href="#i-m-pv"/></svg>PV Lab</button>
  <div class="railspring"></div>
  <button class="railb" data-t="help" onclick="goTab('help')" title="About PSDAT"><svg><use href="#i-m-help"/></svg>About</button>
 </nav>
 <div id="content">
  <div id="tab-net">
   <style>#sld [data-el="bus"],#sld [data-el="gen"]{cursor:move}#sld [data-el="br"]{cursor:grab}#sld [data-el="note"]{cursor:move}#sld [data-el]:hover{opacity:.82}
    .dhead .menu .dd{left:auto;right:0;min-width:172px}</style>
   <div id="ws">
    <div id="wsrow">
     <div class="ahstrip" id="ahL"></div>
     <div class="dockcol" id="dockL"></div>
     <div class="dsplit" id="splitL" data-side="left"></div>
     <div id="cwrap">
      <svg id="sld"></svg>
      <div id="netErr"></div>
      <div id="sldTip" style="display:none"></div>
      <div id="mmap" style="display:none" title="click to recentre · drag a box to zoom in"></div>
      <div class="dhint" id="dhL"></div><div class="dhint" id="dhR"></div><div class="dhint" id="dhB"></div>
     </div>
     <div class="dsplit" id="splitR" data-side="right"></div>
     <div class="dockcol" id="dockR"></div>
     <div class="ahstrip" id="ahR"></div>
    </div>
    <div id="dockB"></div>
    <div class="ahstrip" id="ahB"></div>
   </div>
   <div id="pnhold" style="display:none">
    <div class="dpanel" id="pn_model">
     <div class="dhead" data-pn="model">
      <button class="dhb caret" onclick="pnCollapse('model')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="model">Test system</span>
      <button class="dhb" data-pinbtn="model" onclick="pnPin('model')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('model','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('model','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('model','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('model','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('model')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody side">
      <select id="sys" title="import a benchmark into the editor — the diagram then becomes the model every analysis uses; every bundled system is in this list"></select>
     </div>
    </div>
    <div class="dpanel" id="pn_fleet">
     <div class="dhead" data-pn="fleet">
      <button class="dhb caret" onclick="pnCollapse('fleet')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="fleet">Fleet — technology presets</span>
      <button class="dhb" data-pinbtn="fleet" onclick="pnPin('fleet')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('fleet','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('fleet','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('fleet','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('fleet','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('fleet')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody side">
      <div class="presets" id="presets"></div>
      <div class="note" id="knote">each machine's technology is edited on the machine itself (click it on the canvas); effective inertia, IBR share and state count appear in Results &gt; Statistics after a run</div>
     </div>
    </div>
    <div class="dpanel" id="pn_draw">
     <div class="dhead" data-pn="draw">
      <button class="dhb caret" onclick="pnCollapse('draw')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="draw">Draw</span>
      <button class="dhb" data-pinbtn="draw" onclick="pnPin('draw')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('draw','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('draw','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('draw','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('draw','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('draw')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody">
      <div class="pcol">
       <div class="psub" style="margin-top:0">insert — drag onto the canvas</div>
       <button class="tbtn tool" data-tool="addbus" onclick="setTool('addbus')" title="Bus — drag onto the canvas to drop a bus bar (or click here, then click the canvas)"><svg><use href="#i-bus"/></svg>Bus<span class="kbd">B</span></button>
       <button class="tbtn tool" data-tool="addline" onclick="setTool('addline')" title="Transmission line — drag from one bus to another (or click the two buses)"><svg><use href="#i-line"/></svg>Line<span class="kbd">L</span></button>
       <button class="tbtn tool" data-tool="adddbl" onclick="setTool('adddbl')" title="Double-circuit line — drag bus→bus (adds two parallel branches)"><svg><use href="#i-dbl"/></svg>Double line</button>
       <button class="tbtn tool" data-tool="addxfmr" onclick="setTool('addxfmr')" title="Transformer — drag bus→bus; drawn with the two-winding symbol (edit tap in Properties)"><svg><use href="#i-xfmr"/></svg>Transformer</button>
       <button class="tbtn tool" data-tool="addgen" onclick="setTool('addgen')" title="Generator — drag onto a bus bar to attach a machine (set technology in Properties)"><svg><use href="#i-gen"/></svg>Generator<span class="kbd">G</span></button>
       <button class="tbtn tool" data-tool="addload" onclick="setTool('addload')" title="Load — drag onto a bus bar to add a P+jQ demand"><svg><use href="#i-load"/></svg>Load</button>
       <button class="tbtn tool" data-tool="addcap" onclick="setTool('addcap')" title="Shunt capacitor — drag onto a bus bar to add +MVAr support"><svg><use href="#i-cap"/></svg>Capacitor</button>
       <button class="tbtn tool" data-tool="addreact" onclick="setTool('addreact')" title="Shunt reactor — drag onto a bus bar to add −MVAr absorption"><svg><use href="#i-react"/></svg>Reactor</button>
       <div class="psub">FACTS — drop onto a bus</div>
       <button class="tbtn tool" data-tool="addsvc" onclick="setTool('addsvc')" title="SVC — Static VAR Compensator: thyristor-controlled variable shunt susceptance that regulates its bus voltage (Q = B·|V|²)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 2.5v3M6.5 5.5h11"/><path d="M9 8.5l3 5 3-5z"/><path d="M8 17h8M9.5 20h5"/></svg>SVC</button>
       <button class="tbtn tool" data-tool="addstatcom" onclick="setTool('addstatcom')" title="STATCOM — voltage-source-converter reactive compensator, current-limited (Q = |V|·I); holds voltage far better than an SVC at low V"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 2.5v3.5"/><circle cx="12" cy="13.5" r="6.5"/><path d="M8.6 13.5h1.6v-3h2.4v6h2.4v-3h1.4" stroke-width="1.4"/></svg>STATCOM</button>
       <div class="psub">FACTS series — click a line</div>
       <button class="tbtn tool" data-tool="addtcsc" onclick="setTool('addtcsc')" title="TCSC — Thyristor-Controlled Series Capacitor: continuously-variable series compensation that lowers the line reactance and boosts power transfer"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 12h5M16 12h5"/><path d="M10 7v10M13 7v10"/><path d="M6.5 16.5l3-3" stroke-width="1.3"/></svg>TCSC</button>
       <button class="tbtn tool" data-tool="addtssc" onclick="setTool('addtssc')" title="TSSC — Thyristor-Switched Series Capacitor: series compensation switched in discrete steps"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 12h6M15 12h6"/><path d="M11 7v10M13 7v10"/><path d="M9 12l4-3" stroke-width="1.3"/></svg>TSSC</button>
       <button class="tbtn tool" data-tool="addsssc" onclick="setTool('addsssc')" title="SSSC — Static Synchronous Series Compensator: VSC injecting a controllable series voltage (voltage-limited, works even at low line current)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2.5 12h4M17.5 12h4"/><rect x="7" y="7.5" width="10" height="9" rx="1.4"/><path d="M9 13c1-2 2-2 3 0s2 2 3 0" stroke-width="1.3"/></svg>SSSC</button>
       <div class="psub">FACTS combined — click a line</div>
       <button class="tbtn tool" data-tool="addupfc" onclick="setTool('addupfc')" title="UPFC — Unified Power Flow Controller: a shunt converter (holds the sending-bus voltage) plus a series converter (controls the line flow), coupled by a common DC link. Click a line: the shunt attaches at its sending bus, the series sits on the line."><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 16h4M17 16h4"/><rect x="7.5" y="11.5" width="9" height="9" rx="1.3"/><circle cx="7" cy="5" r="3.4"/><path d="M7 8.4v3.1" stroke-dasharray="1.6 1.6"/></svg>UPFC</button>
       <button class="tbtn tool" data-tool="addipfc" onclick="setTool('addipfc')" title="IPFC — Interline Power Flow Controller: two series converters on two lines, coupled by a common DC link, that trade real power between the corridors. Click line 1; set line 2 in Properties."><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2.5 7h3M11.5 7h3M2.5 17h3M11.5 17h3"/><rect x="6" y="3.5" width="5" height="7" rx="1.2"/><rect x="6" y="13.5" width="5" height="7" rx="1.2"/><path d="M17 7v10" stroke-dasharray="1.8 1.8"/><path d="M14.5 7h2.5M14.5 17h2.5"/></svg>IPFC</button>
       <button class="tbtn tool" data-tool="addnote" onclick="setTool('addnote')" title="Annotation — drag onto the canvas to drop a text note"><svg><use href="#i-note"/></svg>Annotation</button>
       <div class="note" style="margin-top:8px;font-size:11px">rotate · flip · delete are on the top ribbon (right end)</div>
      </div>
     </div>
    </div>
    <div class="dpanel grow" id="pn_props">
     <div class="dhead" data-pn="props">
      <button class="dhb caret" onclick="pnCollapse('props')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="props">Properties</span>
      <button class="dhb" data-pinbtn="props" onclick="pnPin('props')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('props','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('props','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('props','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('props','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('props')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody">
      <h3 id="ppTitle" style="font-family:Georgia,serif;font-size:15px;color:var(--navy);margin-bottom:6px">No selection</h3>
      <div id="pp" class="note">drag a component from the Draw palette onto the canvas — or click an element to edit it.</div>
      <div class="f" style="margin-top:10px" title="Power-flow solver. All three reach the same solution; the iteration count shows why Newton replaced Gauss-Seidel.">PF solver<select id="pfmeth" onchange="if(NET&&DPF)runPF()">
       <option value="nr">Newton-Raphson (quadratic)</option>
       <option value="fdlf">Fast-decoupled XB (Stott-Alsac)</option>
       <option value="gs">Gauss-Seidel (accelerated)</option></select></div>
      <div id="pfsum" class="note" style="margin-top:10px"></div>
     </div>
    </div>
    <div class="dpanel grow" id="pn_results">
     <div class="dhead" data-pn="results">
      <button class="dhb caret" onclick="pnCollapse('results')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="results">Results</span>
      <button class="dhb" data-pinbtn="results" onclick="pnPin('results')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('results','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('results','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('results','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('results','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('results')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody">
      <div class="rexwrap">
       <select class="rextabs" id="rexTabs" onchange="rexTab(this.value)"
        title="result table category — one compact list instead of a wall of chips"></select>
       <div class="rextool" style="padding-top:2px">
        <select id="rexSortSel" class="rexsort" onchange="rexSortSel(this.value)"
         title="sort the table by any column, ascending or descending — clicking a column header does the same"></select>
        <button class="rexexp" id="rexSortDir" onclick="rexSortFlip()" title="flip ascending / descending">▲ asc</button>
       </div>
       <div class="rexbody" id="rexBody" oncontextmenu="event.preventDefault();rexCtxOpen(event,null)"></div>
       <div id="rexCtx"></div>
      </div>
     </div>
    </div>
    <div class="dpanel grow" id="pn_data">
     <div class="dhead" data-pn="data">
      <button class="dhb caret" onclick="pnCollapse('data')" title="collapse / expand"><svg><use href="#i-collapse"/></svg></button>
      <span data-drag="data">Data</span>
      <button class="dhb" data-pinbtn="data" onclick="pnPin('data')" title="pin / auto-hide"><svg><use href="#i-pin"/></svg></button>
      <div class="menu"><button class="dhb" title="dock position"><svg><use href="#i-caret"/></svg></button>
       <div class="dd">
        <a onclick="pnDock('data','left')"><span class="chk"></span>Dock left</a>
        <a onclick="pnDock('data','right')"><span class="chk"></span>Dock right</a>
        <a onclick="pnDock('data','bottom')"><span class="chk"></span>Dock bottom</a>
        <a onclick="pnDock('data','float')"><span class="chk"></span>Floating window</a></div></div>
      <button class="dhb" onclick="pnClose('data')" title="hide — re-open from the View menu"><svg><use href="#i-close"/></svg></button>
     </div>
     <div class="dbody">
      <div class="rexwrap">
       <select class="rextabs" id="datTabs" onchange="datTab(this.value)"
        title="input-data category — the as-entered model (what goes IN), not results"></select>
       <div class="rexbody" id="datBody"></div>
      </div>
     </div>
    </div>
   </div>
  </div>
  <div class="card main" id="main" style="display:none">

   <div id="tab-ss" style="display:none">
    <div class="row"><button class="go" id="runL">Linearize &amp; analyse</button>
     <span class="spin" id="spL">computing exact Jacobians…</span></div>
    <div id="ssErr"></div>
    <div class="grid2">
     <div class="card panel"><h3>Eigenvalue map</h3><div id="eig"></div>
      <div class="note">crosses: system modes · dotted rays: 5% and 10% damping · red: unstable half-plane</div></div>
     <div class="card panel"><h3>Oscillatory modes <span style="color:var(--mut);font-size:12px">(click a row for participation)</span></h3>
      <div style="max-height:300px;overflow:auto"><table id="mtab"><thead>
       <tr><th>f (Hz)</th><th>damping</th><th>eigenvalue</th></tr></thead><tbody></tbody></table></div>
      <div class="grid2" style="grid-template-columns:1.2fr 1fr;gap:10px;margin-top:12px">
       <div><h3>Participation factors</h3><div id="part" class="note">select a mode above</div></div>
       <div><h3>Mode shape</h3><div id="shape" class="note">speed-phasor compass of the selected mode</div></div>
      </div></div>
    </div></div>

   <div id="tab-td" style="display:none">
    <div class="row">
     <div class="f">disturbance class<select id="dkind">
      <option value="load">network: load change</option>
      <option value="fault">network: 3-phase fault</option>
      <option value="trip">network: line outage</option>
      <option value="gen">generator: set-point pulse</option>
      <option value="cloud">source: cloud over PV</option>
      <option value="gust">source: wind gust</option></select></div>
     <div class="f" id="flocw"><span id="floclab">bus</span><input id="dloc" type="number" value="8" min="1"></div>
     <div class="f" id="floc2w" style="display:none">to bus<input id="dloc2" type="number" value="8" min="1"></div>
     <div class="f"><span id="fmaglab">size (pu)</span><input id="dmag" type="number" value="0.15" step="0.05"></div>
     <div class="f">applied at (s)<input id="dt1" type="number" value="1.0" step="0.5"></div>
     <div class="f">removed at (s)<input id="dt2" type="text" value="1.1" placeholder="blank = sustained"></div>
     <div class="f">simulate (s)<input id="dts" type="number" value="12" step="1"></div>
     <div class="f" title="Integration method. RK4 = built-in partitioned explicit (fast). Radau/BDF = SciPy implicit stiff solvers. RK45/LSODA = SciPy adaptive.">ODE solver<select id="dmeth">
      <option value="rk4">RK4 (built-in, partitioned)</option>
      <option value="Radau">Radau (SciPy, implicit)</option>
      <option value="BDF">BDF (SciPy, stiff)</option>
      <option value="RK45">RK45 (SciPy, adaptive)</option>
      <option value="LSODA">LSODA (SciPy, auto-stiff)</option></select></div>
     <button class="go" id="runT">Run simulation</button><span class="spin" id="spT">integrating…</span></div>
    <div class="hint" id="dhint"></div><div id="tdErr"></div>
    <div class="grid2">
     <div class="card panel"><h3>Centre-of-inertia frequency</h3><div id="cfrq"></div><div class="note" id="nad"></div></div>
     <div class="card panel"><h3>Unit frequencies</h3><div id="cspd"></div></div>
    </div>
    <div class="card panel" style="margin-top:16px"><h3>Watch states
      <button class="tbtn" style="margin-left:10px;padding:3px 10px" onclick="fillStates(true)" title="refresh the list from the current diagram + fleet">⟳ refresh list</button></h3>
     <select id="watch" multiple size="7" style="width:100%;margin:7px 0 4px;font-size:13px"
      onfocus="fillStates()" onmouseenter="fillStates()"
      title="every differential state of the CURRENT model — pick up to 4 (Ctrl-click); the chart draws on the next run"></select>
     <div id="cwatch"></div><div class="note">pick up to 4 states (Ctrl-click for several) — the list is generated from the model itself: delta·omega (SG), Efd·VR·RF (exciter), TM·PSV (governor), Vdc·xdc·vref (PV), SOC·Pf (battery), wt·wg·ttw·beta·Po (wind), slip (induction), each suffixed by its bus number; series-FACTS states read like k7_8. The chart updates on the next run.</div></div>
   </div>

   <div id="tab-ds" style="display:none">
    <div class="card panel"><h3>Parameter sweep &amp; root locus</h3>
     <div class="row">
      <div class="f">unit<select id="swU" onchange="loadSweepParams()"></select></div>
      <div class="f">parameter<select id="swP"></select></div>
      <div class="f">from<input id="swA" type="number" value="1" step="any"></div>
      <div class="f">to<input id="swB" type="number" value="10" step="any"></div>
      <div class="f">steps<input id="swN" type="number" value="9" min="3" max="15"></div>
      <div class="f">mode band (Hz)<div style="display:flex;gap:4px">
        <input id="swF1" type="number" value="0.2" step="0.1" style="width:62px">
        <input id="swF2" type="number" value="3" step="0.1" style="width:62px"></div></div>
      <button class="go" id="runSw">Sweep</button><span class="spin" id="spSw">sweeping…</span></div>
     <div id="swErr"></div>
     <div class="grid2"><div><h3 style="margin-top:10px">Root locus</h3><div id="swloc"></div>
       <div class="note">light → dark: increasing parameter value</div></div>
      <div><h3 style="margin-top:10px">Least damping in band</h3><div id="swcurve"></div></div></div></div>
    <div class="card panel" style="margin-top:14px"><h3>Damping-controller (POD) designer</h3>
     <div class="row">
      <div class="f">actuator (P* of)<select id="pdA"></select></div>
      <div class="f">measurement<select id="pdM"><option value="local">actuator speed</option>
        <option value="diff">speed difference</option></select></div>
      <div class="f" id="pdBw" style="display:none">minus unit<select id="pdB"></select></div>
      <div class="f">mode band (Hz)<div style="display:flex;gap:4px">
        <input id="pdF1" type="number" value="0.2" step="0.1" style="width:62px">
        <input id="pdF2" type="number" value="2" step="0.1" style="width:62px"></div></div>
      <div class="f">target damping (%)<input id="pdZ" type="number" value="15" step="1"></div>
      <button class="go" id="runPd">Design &amp; verify</button><span class="spin" id="spPd">designing…</span></div>
     <div id="pdErr"></div>
     <div class="grid2"><div id="pdout" class="note" style="margin-top:10px"></div>
      <div><div id="pdeig"></div></div></div></div>
    <div class="card panel" style="margin-top:14px"><h3>Frequency response (exact linearized model)</h3>
     <div class="row">
      <div class="f">input: P* of<select id="bdU"></select></div>
      <div class="f">output<select id="bdO"><option value="coi">COI frequency</option>
        <option value="unit">a unit's speed</option></select></div>
      <div class="f" id="bdAw" style="display:none">output unit<select id="bdA"></select></div>
      <button class="go" id="runBd">Compute</button><span class="spin" id="spBd">computing…</span></div>
     <div id="bdErr"></div>
     <div class="grid2"><div><div id="bdmag"></div></div><div><div id="bdph"></div></div></div></div>
   </div>

   <div id="tab-sc" style="display:none">
    <div class="note" style="margin-bottom:10px">Guided studies reproduce the manual's figures on the <b>bundled benchmark systems</b> (their narrative depends on those exact cases). Everything else — Power flow, Small-signal, Time domain, Design, Signals — runs on <b>your current diagram</b>; use those tabs to run the same experiments on an edited network.</div>
    <div class="scgrid" id="scen"></div>
    <div class="row" style="margin-top:12px"><span class="spin" id="spS">running scenario… (some take a couple of minutes)</span></div>
    <div id="scErr"></div><pre id="scout" style="display:none"></pre><div class="imgs" id="scimg"></div>
   </div>

   <div id="tab-st" style="display:none">
    <div class="note" style="margin-bottom:10px">Classroom studies — each solves <b>your current diagram</b> (or the selected benchmark) with the same open-equation engine as the analysis tabs, so every number can be reproduced by hand from the theory cards and the manual. Runs here tick off the <b>Learn</b> tab's lessons.</div>
    <div class="grid2" style="margin-top:0">
     <div class="card panel"><h3>Optimal PMU placement (WAMS design)</h3>
     <div class="row">
      <label class="note" style="align-self:center;cursor:pointer" title="a bus with no load and no generation obeys KCL exactly, so one of its neighbours can be inferred — the classic topology transform lowers the PMU count"><input type="checkbox" id="oppZI" checked> use zero-injection reduction</label>
      <button class="go" onclick="runOPP()" id="goOPP">Solve placement</button><span class="spin" id="spOPP">branch &amp; bound…</span>
      <button class="tbtn" onclick="oppShow()" id="oppShowB" style="display:none;padding:6px 14px">Show on diagram</button>
      <button class="tbtn" onclick="oppClear()" id="oppClearB" style="display:none;padding:6px 14px">Clear overlay</button></div>
     <div id="oppErr"></div>
     <div class="note" id="oppOut">the fewest PMUs that make <b>every bus observable</b> — a PMU measures its bus voltage phasor and every incident branch-current phasor, so it observes itself and all neighbours. Solved exactly as a binary integer program (HiGHS branch &amp; bound) [Xu &amp; Abur 2004]. Literature optima to check yourself: IEEE 14 → 3 · IEEE 30 → 7 · IEEE 39 → 13.</div>
     <div style="max-height:270px;overflow:auto;margin-top:8px" id="oppTab"></div></div>
   <div class="card panel"><h3>N−1 contingency screening</h3>
      <div class="row"><button class="go" onclick="runN1()" id="goN1">Screen all outages</button><span class="spin" id="spN1">re-solving every outage…</span></div>
      <div id="n1Err"></div>
      <div class="note" id="n1Out">every in-service branch is removed in turn and the power flow re-solved; outages are ranked worst-first (islanding · divergence · voltage/loading violations). This is the operating rule behind "the grid must survive any single failure". Set line <b>ratings</b> on branches to enable the loading check.</div>
      <div style="max-height:290px;overflow:auto;margin-top:8px" id="n1Tab"></div></div>
    </div>
    <div class="grid2" style="margin-top:14px">
     <div class="card panel"><h3>Short-circuit levels (three-phase, Z-bus)</h3>
      <div class="row"><button class="go" onclick="runSC()" id="goSC">Compute all buses</button><span class="spin" id="spSC">building the Z-bus…</span></div>
      <div id="stscErr"></div>
      <div class="note" id="stscOut">machines as E″ behind X″d, loads as constant admittance; I<sub>f</sub> = V<sub>pre</sub>/Z<sub>ii</sub> [Anderson ch. 6]. Strong buses (high MVA) hold their voltage through disturbances; weak buses are where converters struggle and protection needs care.</div>
      <div style="max-height:290px;overflow:auto;margin-top:8px" id="stscTab"></div></div>
     <div class="card panel"><h3>P–V (nose) curve — voltage stability</h3>
      <div class="row">
       <div class="f">load to scale<select id="pvBus"><option value="0">all loads together</option></select></div>
       <button class="go" onclick="runPV()" id="goPV">Trace curve</button><span class="spin" id="spPV">continuation running…</span></div>
      <div id="pvErr"></div><div id="pvChart"></div>
      <div class="note" id="pvOut">the chosen load(s) are scaled up with a warm-started Newton continuation until the power flow folds — the nose is the steady-state loadability limit, and the distance to it is the voltage-stability margin [Kundur ch. 14].</div></div>
     </div>
    <div class="card panel" style="margin-top:14px"><h3>Critical clearing time — transient stability</h3>
      <div class="row">
       <div class="f">fault at bus<select id="cctBus"></select></div>
       <div class="f" title="fault reactance to ground (pu on 100 MVA). 0.05 dips the bus to ~0.2-0.4 pu — severe yet numerically robust">fault X (pu)<input id="cctXf" type="number" value="0.05" step="0.01" min="0.03"></div>
       <button class="go" onclick="runCCT()" id="goCCT">Find CCT</button><span class="spin" id="spCCT">bisection on the nonlinear model… (1–3 min)</span></div>
      <div id="cctErr"></div>
      <div class="note" id="cctOut">a three-phase fault is applied at t = 1 s and cleared after t<sub>c</sub>; bisection on the <b>full nonlinear simulation</b> finds the largest t<sub>c</sub> the system survives — the margin your relays and breakers must beat. The equal-area lab (Learn tab) is the one-machine theory behind this.</div>
      <div id="cctChart"></div></div>
    
    <div class="card panel" style="margin-top:14px"><h3>Economic dispatch &amp; locational prices (DC-OPF)</h3>
     <div class="row"><button class="go" onclick="runED()" id="goED">Dispatch</button><span class="spin" id="spED">optimizing…</span>
      <span class="note" style="align-self:center">cost of each unit C<sub>k</sub>(P) = b<sub>k</sub>P + c<sub>k</sub>P² (textbook defaults) — classic equal-λ first, then a DC optimal power flow with line limits whose nodal duals <b>are</b> the LMPs [Wood &amp; Wollenberg ch. 3, 8]</span></div>
     <div id="edErr"></div>
     <div class="grid2" style="margin-top:8px"><div><div id="edTab" style="max-height:250px;overflow:auto"></div><div class="note" id="edOut"></div></div>
      <div><h3 style="margin-top:0">Locational marginal prices ($/MWh)</h3><div id="edLmp"></div><div class="note" id="edBind"></div></div></div></div>
    </div>

   <div id="tab-ln" style="display:none">
    <style>.easl{display:flex;align-items:center;gap:8px;font-size:12px;margin:3px 0}
     .easl span{width:150px;color:var(--mut);flex:none}.easl input{flex:1;min-width:60px}
     .easl b{width:46px;text-align:right;flex:none;font-variant-numeric:tabular-nums}</style>
    <div class="card panel"><h3>Learn power systems — on your own grid</h3>
     <p class="note" id="lnHead" style="margin-top:4px">loading progress…</p></div>
    <div class="grid2" style="margin-top:14px;align-items:start">
     <div id="lnLessons"></div>
     <div>
      <div class="card panel"><h3>Quiz — written from YOUR network</h3>
       <div class="note" style="margin:4px 0 8px">every number comes from the current diagram's solved power flow — change the network and the quiz changes with it. Same seed + same network = same sheet (instructors: that is reproducibility).</div>
       <div class="row">
        <div class="f">questions<select id="qzN"><option>4</option><option selected>6</option><option>8</option><option>12</option></select></div>
        <div class="f">seed<input id="qzSeed" type="number" value="1" min="1" style="width:74px"></div>
        <button class="go" onclick="qzNew()" id="qzGo">New quiz</button><span class="spin" id="spQZ">writing questions…</span></div>
       <div id="qzErr"></div><div id="qzBody" style="margin-top:8px"></div>
       <div class="row" style="margin-top:4px"><button class="go" id="qzGrade" onclick="qzGrade()" style="display:none">Grade my answers</button><span class="note" id="qzScore" style="align-self:center"></span></div></div>
      <div class="card panel" style="margin-top:14px"><h3>Equal-area criterion lab</h3>
       <div class="note" style="margin:4px 0 8px">one machine against an infinite bus: P<sub>e</sub> = EV/X · sin δ. Drag the sliders — the accelerating (A1) and decelerating (A2) areas update live; <b>A2 ≥ A1</b> is the stability test, and the fault-on swing equation (RK4) converts the critical angle into a clearing <i>time</i> [Kundur ch. 13].</div>
       <div id="eaSl"></div>
       <div id="eaChart" style="margin-top:6px"></div>
       <div class="note" id="eaOut"></div></div>
     </div>
    </div>
    <div class="card panel" style="margin-top:14px"><h3>Glossary — the language of the course</h3>
     <input id="glSearch" type="text" placeholder="search terms… (e.g. inertia, LMP, PLL)" oninput="glRender(this.value)"
      style="width:100%;margin:6px 0 4px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;font-size:12.5px">
     <div id="glBody" style="max-height:420px;overflow:auto"></div></div>
   </div>

   <div id="tab-pvl" style="display:none">
    <style>.pvsl{display:flex;align-items:center;gap:8px;font-size:12px;margin:3px 0}
     .pvsl span{width:170px;color:var(--mut);flex:none}.pvsl input[type=range]{flex:1;min-width:60px}
     .pvsl b{width:64px;text-align:right;flex:none;font-variant-numeric:tabular-nums}
     .pvbig{font-size:16px;color:var(--navy);font-weight:700}</style>
    <div class="note" style="margin-bottom:10px">Deep-dive photovoltaics, from the cell equation to grid support. Every curve below is computed from <b>the same explicit single-diode model the grid engine integrates</b> (<code>units.py</code>: I = G&thinsp;i<sub>sc</sub>[1 &minus; C&#8321;(e<sup>V/(C&#8322;v&#8338;&#8339;)</sup> &minus; 1)], normalised so the STC maximum-power point is V = 1, I = 1, P = 1). Multiply by your module's V<sub>mp</sub>, I<sub>mp</sub>, P<sub>mp</sub> to read volts, amperes and watts.</div>
    <div class="grid2" style="margin-top:0">
     <div class="card panel"><h3>1 &middot; The array characteristic — I&ndash;V and P&ndash;V</h3>
      <div id="pl1S"></div>
      <div class="grid2" style="gap:10px;margin-top:6px"><div id="pl1IV"></div><div id="pl1PV"></div></div>
      <div class="note" id="pl1Out"></div></div>
     <div class="card panel"><h3>2 &middot; Partial shading &amp; bypass diodes</h3>
      <div id="pl2S"></div>
      <label class="note" style="cursor:pointer;display:block;margin:2px 0"><input type="checkbox" id="pl2Byp" checked onchange="pvlP2()"> bypass diodes installed (one per substring)</label>
      <div class="grid2" style="gap:10px;margin-top:6px"><div id="pl2IV"></div><div id="pl2PV"></div></div>
      <div class="note" id="pl2Out"></div></div>
    </div>
    <div class="grid2" style="margin-top:14px">
     <div class="card panel"><h3>3 &middot; MPPT playground — watch the tracker think</h3>
      <div class="row">
       <div class="f">algorithm<select id="pl3Algo"><option value="po">Perturb &amp; Observe</option><option value="ic">Incremental conductance</option></select></div>
       <div class="f">step &Delta;V (pu)<input id="pl3Dv" type="number" value="0.01" step="0.005" min="0.002" max="0.06" style="width:74px"></div>
       <div class="f">scenario<select id="pl3Scen"><option value="steady">steady sun</option><option value="cloud">passing cloud</option></select></div>
       <label class="note" style="align-self:center;cursor:pointer"><input type="checkbox" id="pl3Shade" onchange="pvlP3Setup()"> use the shaded curve of panel 2</label>
       <button class="go" id="pl3Go" onclick="pvlP3Run()">Start</button>
       <button class="tbtn" style="padding:6px 12px" onclick="pvlP3Scan()" title="sweep the whole voltage range once and jump to the best point — the escape from a local peak">Global scan</button></div>
      <div id="pl3Chart" style="margin-top:6px"></div>
      <div id="pl3Strip"></div>
      <div class="note" id="pl3Out">press <b>Start</b> — the dot is the operating point the tracker moves; the strip chart compares harvested power with the true maximum. Small &Delta;V tracks slowly but rests close to the peak; large &Delta;V is fast and restless. On the shaded curve, watch P&amp;O settle on a <b>local</b> peak — then rescue it with Global scan.</div></div>
     <div class="card panel"><h3>4 &middot; Reserve, capability and grid support</h3>
      <div class="pvsl"><span>power reserve (deloading) %</span><input type="range" id="pl4R" min="0" max="40" value="10" step="1" oninput="pvlP4(1)"><b id="pl4Rv">10</b></div>
      <div id="pl4Curve" style="margin-top:4px"></div>
      <div class="grid2" style="gap:10px;margin-top:8px"><div id="pl4Cap"></div><div id="pl4GS"></div></div>
      <div class="note" id="pl4Out"></div></div>
    </div>
    <div class="grid2" style="margin-top:14px">
     <div class="card panel"><h3>5 &middot; A day of energy — irradiance to kWh</h3>
      <div class="pvsl"><span>cloudiness</span><input type="range" id="pl5C" min="0" max="100" value="35" step="5" oninput="pvlP5()"><b id="pl5Cv">35%</b></div>
      <div id="pl5Chart" style="margin-top:4px"></div>
      <div class="note" id="pl5Out"></div></div>
     <div class="card panel"><h3>6 &middot; From the laboratory to the grid</h3>
      <div class="note" style="line-height:1.6">Everything here has a live counterpart in the rest of the toolbox:
       the array model, DC link, MPPT and de-loading run inside every <b>PV-GFL / PV-GFM</b> unit on the diagram;
       cloud transients are a first-class disturbance; the IEEE&nbsp;1547 grid-support curves of panel&nbsp;4
       are the actual controllers on each PV and battery unit (off by default, enabled per unit).</div>
      <div class="row" style="margin-top:10px;flex-wrap:wrap">
       <button class="tbtn" style="padding:7px 13px" onclick="goTab('net');stat('click a machine and set its technology to PV-GFL or PV-GFM — or use the RES mix fleet preset')">Put PV on the diagram</button>
       <button class="tbtn" style="padding:7px 13px" onclick="pvlToTD()">Run a cloud transient (Time tab)</button>
       <button class="tbtn" style="padding:7px 13px" onclick="goTab('ln');LEARN.open='l9';try{lrnRender()}catch(_){}">Open Lesson 9 — Inside a PV plant</button>
       <button class="tbtn" style="padding:7px 13px" onclick="goTab('ln');const g=$('glSearch');if(g){g.value='MPPT';glRender('MPPT');}">Glossary: MPPT &amp; friends</button></div>
      <div class="note" style="margin-top:10px">Sources on the theory cards and in the manual: Masters; Femia et&nbsp;al.; Yazdani &amp; Iravani ch.&nbsp;8; Sangwongwanich et&nbsp;al. (reserve by operating above V<sub>mp</sub>); IEEE Std 1547-2018.</div></div>
    </div>
   </div>

   <div id="tab-help" style="display:none">
    <div class="card panel"><h3>What is this?</h3>
     <p>PSDAT is an education-first toolbox for power-system dynamics in the renewable era.
     Pick a test system and assign a technology to each machine position — synchronous generator,
     grid-forming or grid-following converter, PV plant, battery, or a wind turbine of Types 1–4.
     The <b>small-signal tab</b> linearizes the differential–algebraic model exactly and shows every
     oscillatory mode with its participation factors; the <b>time-domain tab</b> integrates the same
     nonlinear equations under the three PSDAT disturbance classes (network-side, generator-side and
     source-side); the <b>scenarios tab</b> reproduces the guided studies of the manual.
     The <b>Studies tab</b> adds the rest of a modern course &mdash; P&ndash;V nose curves, N&minus;1 screening,
     short-circuit levels, critical clearing time, economic dispatch with LMPs, and optimal PMU
     placement &mdash; all solved on your current diagram; the <b>Learn tab</b> turns it into a classroom:
     guided lessons that check themselves against the live app state, a quiz generated from your own
     network, an interactive equal-area lab and a course glossary.</p>
     <p style="margin-top:8px">Every equation in the engine is traceable to a textbook — see
     <i>docs/PSDAT_Manual</i> and <i>docs/PSDAT_Model_Sources</i>. The MATLAB twin
     (<code>PSDAT_App</code>, <code>PSDAT_Demo.m</code>) mirrors this lab equation-for-equation.</p></div>
    <div class="card panel" style="margin-top:14px"><h3>Developer</h3>
     <p><b>Dr. Ismael Khorshed Abdulrahman</b> — developer of PSDAT.</p>
     <p style="margin-top:6px;color:var(--mut);font-size:13px">Successor of PSDAT
     [Abdulrahman, <i>IEEE Open Access Journal of Power and Energy</i>, 2020]. Built as an
     education-first platform for power-system dynamics in the renewable era.</p></div>
   </div>
  </div>
  <div id="statusbar"><span id="stSys">no network</span><span id="stLock"></span><span id="stMsg">ready</span><span class="spin" id="spN" style="border-right:1px solid var(--line)">solving…</span><span id="stZoomBox"><button onclick="rq(()=>fitView())" title="Zoom Fit — whole diagram in view (A)">⤢</button><button onclick="rq(()=>zoomBtn(0.8))" title="zoom out (−)">−</button><span id="zpct">100%</span><button onclick="rq(()=>zoomBtn(1.25))" title="zoom in (+)">＋</button></span><span id="stPos">&nbsp;</span></div>
 </div>
</div>
<div class="modalbg" id="modal" style="display:none"><div class="modal">
 <h3 id="mTitle">Parameters</h3>
 <div class="sub2">Edit any value and Apply — the change is used by every analysis until Reset. Modified units show a red dot on the gear. Kundur converters start from the 900-MVA-scaled defaults.</div>
 <div class="mbody" id="mBody"></div>
 <div class="mrow"><button class="ghost" id="mReset">Reset to defaults</button>
  <button class="ghost" id="mClose">Cancel</button>
  <button class="go" id="mApply">Apply</button></div>
</div></div>
<div class="modalbg" id="kbd" style="display:none"><div class="modal" style="width:560px">
 <h3>Keyboard shortcuts</h3>
 <div class="mbody" style="padding-bottom:12px"><table>
  <tr><td>V · B · L · G · X</td><td>select · add bus · add line · add generator · delete tool</td></tr>
  <tr><td>R · F · Del</td><td>rotate · flip · delete the selection</td></tr>
  <tr><td>Ctrl+Z · Ctrl+Y</td><td>undo · redo</td></tr>
  <tr><td>Ctrl+A</td><td>select every bus and machine</td></tr>
  <tr><td>Shift+drag</td><td>box-select · arrow keys nudge the selection</td></tr>
  <tr><td>A · S · + · −</td><td>zoom fit · zoom to selection · zoom in · out</td></tr>
  <tr><td>wheel · middle-drag</td><td>zoom at the cursor · pan (dragging empty space also pans)</td></tr>
  <tr><td>T · O · M · K</td><td>tidy layout · orthogonal routing · mini-map · lock layout</td></tr>
  <tr><td>F11 · Esc</td><td>full-screen editing · leave full screen / cancel pending line</td></tr>
  <tr><td>Ctrl+ + · Ctrl+ − · Ctrl+0</td><td>interface larger · smaller · reset</td></tr>
 </table></div>
 <div class="mrow"><button class="go" onclick="$('kbd').style.display='none'">Close</button></div>
</div></div>
<div class="modalbg" id="viz" style="display:none"><div class="modal" style="width:480px">
 <h3>Visualization settings</h3>
 <div class="sub2">Fine-tune the single-line diagram — motion, heat map and labels. The defaults ARE the classic PSDAT heat map; these sliders only let you strengthen or soften it, and "Reset to defaults" always brings the original style back. Changes apply live and are remembered.</div>
 <div class="mbody" id="vizBody" style="padding-bottom:10px"></div>
 <div class="mrow"><button class="ghost" onclick="vizReset()">Reset to defaults</button>
  <button class="go" onclick="$('viz').style.display='none'">Done</button></div>
</div></div>
<script>
let META=null, LASTL=null, POV={}, MK=-1;
const $=id=>document.getElementById(id);
async function api(p,body){try{
  const r=await fetch(p,{method:body?'POST':'GET',body:body?JSON.stringify(body):null});
  return await r.json();
 }catch(e){return {error:'could not reach the engine: '+(e&&e.message||e)};}}
// turn raw backend errors into plain guidance (never leaves the app stuck)
function friendlyErr(m){m=String(m||'error');
 if(/singular/i.test(m))return 'Power flow could not be solved (singular matrix). Usually a bus with no path to the slack, an isolated section, a missing/duplicate slack, or a zero-impedance loop. Fix the connection — or press Reset to reload a clean network.';
 if(/did not converge/i.test(m))return m+' — try smaller loads, check impedances, or press Reset.';
 return m;}
function mix(){return NET?NET.gens.map(g=>g.tag):[];}   // the DIAGRAM is the model — the fleet is what is drawn
function setMix(m){if(!NET||!NET.gens.length)return;pushU();
 NET.gens.forEach((g,k)=>{const t=m[k%m.length];if(t&&g.tag!==t){g.tag=t;clearOv(k);}});
 edited();draw();fillDesign();syncSide();
 stat('fleet preset applied — '+NET.gens.map(g=>g.tag).join(' · '));}
function clearOv(k){if(POV[k]!==undefined){delete POV[k];}}
function buildSide(){
 // fleet presets act directly on the drawn network's machines.  Benchmark-specific
 // presets (from META) appear when the machine count matches; generic patterns always.
 const el=$('presets');if(!el)return;
 const ng=NET?NET.gens.length:0;
 const pat=(name,fn,tip)=>`<button onclick='setMix(${JSON.stringify(fn)})' title="${tip}">${name}</button>`;
 let h='';
 if(ng){
  const sys=$('sys').value;
  const mp=(META.presets&&META.presets[sys])||{};
  for(const [n,mm] of Object.entries(mp))if(mm.length===ng)h+=pat(n,mm,'benchmark preset ('+mm.join(', ')+')');
  const hadBench=!!h;
  h+=pat('All SG+FLC',Array.from({length:ng},()=>'SGF'),   // ALWAYS offered — the
    'every machine gets the FUZZY-LOGIC stabiliser (intelligent damping control)');   // intelligent-control preset
  if(!hadBench){
   h+=pat('All SG',Array.from({length:ng},()=>'SG'),'classical fleet — every unit a synchronous machine');
   h+=pat('All GFM',Array.from({length:ng},()=>'GFM'),'every unit a grid-forming converter');
   h+=pat('Mixed',Array.from({length:ng},(_,k)=>k%2?'GFL':'SG'),'alternating synchronous / grid-following');
   h+=pat('High IBR',Array.from({length:ng},(_,k)=>k?'GFL':'SG'),'one synchronous machine, the rest grid-following');
  }
 }else h='<span class="hint">draw or import a network first</span>';
 el.innerHTML=h;
 const _b=['bH','bP','bN'].map(i=>$(i));_b.forEach(e=>{if(e)e.textContent='–';});fillDesign();}
function fillDesign(){const m=mixActive();
 const opts=m.map((t,k)=>`<option value="${k}">G${k+1} (${t})</option>`).join('');
 for(const id of ['swU','pdA','pdB','bdU','bdA']){const el=$(id);if(!el)continue;
  const v=el.value; el.innerHTML=opts; if(v!==''&&+v<m.length)el.value=v;}
 loadSweepParams();}
// ---------- parameter editor ----------
let MPARAMS=[];
async function openPar(k){MK=k;
 const r=await api('/api/params',buildPayload({k}));
 if(r.error){alert(r.error);return;}
 MPARAMS=r.params;
 $('mTitle').textContent=`G${k+1} — ${r.tag} parameters`;
 const ov=POV[k]||{};
 $('mBody').innerHTML=r.params.map(p=>{
  const cur=(ov[p.name]!==undefined)?ov[p.name]:p.value;
  let inp;
  if(p.kind==='bool')inp=`<input type="checkbox" data-p="${p.name}" ${cur?'checked':''}>`;
  else if(p.kind==='text')inp=`<input type="text" data-p="${p.name}" value="${cur}">`;
  else inp=`<input type="number" step="any" data-p="${p.name}" value="${cur}">`;
  return `<div class="prow${ov[p.name]!==undefined?' chg':''}"><b>${p.name}</b><div>${inp}</div><span class="d">${p.desc}</span></div>`;}).join('');
 $('modal').style.display='flex';}
function closePar(){$('modal').style.display='none';}
function applyPar(){const ov={};
 for(const p of MPARAMS){const el=document.querySelector(`#mBody [data-p="${p.name}"]`);if(!el)continue;
  let v; if(p.kind==='bool')v=el.checked; else if(p.kind==='text')v=el.value; else v=parseFloat(el.value);
  const same = p.kind==='bool' ? (v===!!p.value) : (String(v)===String(p.value));
  if(!same && !(p.kind==='num'&&isNaN(v))) ov[p.name]=v;}
 if(Object.keys(ov).length)POV[MK]=ov; else delete POV[MK];
 closePar();try{PRMDIRTY=true;datRender();}catch(_){}}
function resetPar(){delete POV[MK];closePar();try{PRMDIRTY=true;datRender();}catch(_){}}
// ---------- SVG chart helpers ----------
function lin(a,b,c,d){return x=>c+(x-a)*(d-c)/(b-a||1);}
function axes(w,h,x0,x1,y0,y1,xl,yl){const L=52,B=30,T=10,R=12;
 const X=lin(x0,x1,L,w-R),Y=lin(y0,y1,h-B,T);let s='';
 const xt=ticks(x0,x1,6),yt=ticks(y0,y1,5);
 for(const v of yt){s+=`<line x1="${L}" y1="${Y(v)}" x2="${w-R}" y2="${Y(v)}" stroke="#eef1f6"/><text x="${L-6}" y="${Y(v)+4}" text-anchor="end" font-size="10.5" fill="#6b7280">${fmt(v)}</text>`;}
 for(const v of xt){s+=`<line x1="${X(v)}" y1="${T}" x2="${X(v)}" y2="${h-B}" stroke="#f2f4f8"/><text x="${X(v)}" y="${h-B+15}" text-anchor="middle" font-size="10.5" fill="#6b7280">${fmt(v)}</text>`;}
 s+=`<rect x="${L}" y="${T}" width="${w-R-L}" height="${h-B-T}" fill="none" stroke="#cfd6e2"/>`;
 s+=`<text x="${(L+w-R)/2}" y="${h-3}" text-anchor="middle" font-size="11" fill="#374151">${xl}</text>`;
 s+=`<text transform="translate(12 ${(T+h-B)/2}) rotate(-90)" text-anchor="middle" font-size="11" fill="#374151">${yl}</text>`;
 return {s,X,Y,L,T,R,B};}
function ticks(a,b,n){const sp=nice((b-a)/n);const t=[];for(let v=Math.ceil(a/sp)*sp;v<=b+1e-12;v+=sp)t.push(+v.toFixed(10));return t;}
function nice(x){const p=Math.pow(10,Math.floor(Math.log10(Math.abs(x)||1)));const f=x/p;return (f<1.5?1:f<3.5?2:f<7.5?5:10)*p;}
function fmt(v){return Math.abs(v)>=1000?v.toFixed(0):Math.abs(v)>=10?v.toFixed(1):v.toFixed(3).replace(/\.?0+$/,'');}
function lineChart(el,t,series,xl,yl){const w=el.clientWidth||560,h=300;
 let ys=[].concat(...Object.values(series).map(a=>a.filter(Number.isFinite)));
 if(!ys.length){el.innerHTML='<div class="note">no data</div>';return;}
 let y0=Math.min(...ys),y1=Math.max(...ys);if(y1-y0<1e-9){y0-=1;y1+=1}
 const pad=(y1-y0)*0.08;y0-=pad;y1+=pad;
 const A=axes(w,h,t[0],t[t.length-1],y0,y1,xl,yl);let s=A.s;
 const cols=['#1f3b73','#c0392b','#1e8449','#b7950b','#117a8b','#a04000','#8e44ad'];
 let ci=0,leg='';
 for(const[name,ys2]of Object.entries(series)){const c=cols[ci++%cols.length];
  let d='';for(let i=0;i<t.length;i++){if(!Number.isFinite(ys2[i]))continue;d+=(d?'L':'M')+A.X(t[i]).toFixed(1)+' '+A.Y(ys2[i]).toFixed(1);}
  s+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="1.9"/>`;
  leg+=`<tspan x="${A.L+10+((ci-1)%3)*170}" dy="${(ci-1)%3===0?14:0}" fill="${c}">— ${name}</tspan>`;}
 if(Object.keys(series).length>1)s+=`<text y="${A.T+8}" font-size="11">${leg}</text>`;
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s}</svg>`;}
// Interactive eigenvalue (s-plane) plot: drag a dashed box to ZOOM, double-click
// to reset, click a × to read its value (real, imag, f in Hz, damping ζ).
let EIGST=null;
function eigChart(el,ev){
 const re=ev.map(e=>e[0]),im=ev.map(e=>e[1]);
 const x0=Math.max(-12,Math.min(-1,...re.filter(v=>v>-40))),x1=Math.max(0.4,...re,1);
 const y1=Math.max(5,...im.map(Math.abs))*1.06;
 EIGST={ev,el,x0,x1,y0:-y1,y1,dx0:x0,dx1:x1,dy0:-y1,dy1:y1,drag:null,pick:null};
 eigRender();
}
function eigRender(){
 const E=EIGST; if(!E)return; const el=E.el;
 const w=el.clientWidth||560,h=320; E.w=w; E.h=h;
 const A=axes(w,h,E.x0,E.x1,E.y0,E.y1,'Real (1/s)','Imag (rad/s)'); let s=A.s;
 const clY=v=>Math.max(E.y0,Math.min(E.y1,v));
 for(const z of [0.05,0.10]){const th=Math.acos(z), dx=E.x0, dy=Math.abs(dx)*Math.tan(th);
  s+=`<line x1="${A.X(0)}" y1="${A.Y(0)}" x2="${A.X(dx)}" y2="${A.Y(clY(dy))}" stroke="#9aa4b2" stroke-dasharray="4 4" stroke-width="0.8"/>`;
  s+=`<line x1="${A.X(0)}" y1="${A.Y(0)}" x2="${A.X(dx)}" y2="${A.Y(clY(-dy))}" stroke="#9aa4b2" stroke-dasharray="4 4" stroke-width="0.8"/>`;}
 if(E.x1>0){s+=`<rect x="${A.X(0)}" y="${A.T}" width="${Math.max(0,A.X(E.x1)-A.X(0))}" height="${h-A.B-A.T}" fill="#fde8e8" opacity="0.55"/>`;
  s+=`<line x1="${A.X(0)}" y1="${A.T}" x2="${A.X(0)}" y2="${h-A.B}" stroke="#b42318" stroke-width="1"/>`;}
 E.ev.forEach((e,k)=>{
  if(e[0]<E.x0||e[0]>E.x1||e[1]<E.y0||e[1]>E.y1)return;
  const c=e[0]>1e-6?'#b42318':'#1f3b73', X=A.X(e[0]),Y=A.Y(e[1]);
  const f=Math.abs(e[1])/(2*Math.PI), zeta=-e[0]/(Math.hypot(e[0],e[1])||1)*100;
  const tip=`lambda=${e[0].toFixed(3)}${e[1]>=0?'+':''}${e[1].toFixed(3)}j · f=${f.toFixed(3)} Hz · zeta=${zeta.toFixed(1)}%`;
  s+=`<path d="M${X-4} ${Y-4} l8 8 M${X-4} ${Y+4} l8 -8" stroke="${c}" stroke-width="1.7" pointer-events="none"/>`;
  s+=`<circle cx="${X}" cy="${Y}" r="8" fill="transparent" style="cursor:pointer" onclick="eigPick(${k})"><title>${tip}</title></circle>`;
 });
 s+=`<rect id="eigband" x="0" y="0" width="0" height="0" fill="#1f3b73" fill-opacity="0.08" stroke="#1f3b73" stroke-dasharray="4 3" stroke-width="1" style="display:none" pointer-events="none"/>`;
 if(E.pick!=null&&E.ev[E.pick]){const e=E.ev[E.pick];const f=Math.abs(e[1])/(2*Math.PI),zeta=-e[0]/(Math.hypot(e[0],e[1])||1)*100;
  const txt=`λ = ${e[0].toFixed(3)} ${e[1]>=0?'+':'−'} ${Math.abs(e[1]).toFixed(3)}j     f = ${f.toFixed(3)} Hz     ζ = ${zeta.toFixed(1)} %`;
  s+=`<g pointer-events="none"><rect x="${A.L+6}" y="${A.T+5}" width="${Math.min(w-A.L-A.R,txt.length*6.6+18)}" height="20" rx="3" fill="#1f3b73"/><text x="${A.L+14}" y="${A.T+19}" font-size="11.5" fill="#fff">${txt}</text></g>`;}
 el.innerHTML=`<svg id="eigsvg" viewBox="0 0 ${w} ${h}" width="100%" style="cursor:crosshair" onmousedown="eigDown(event)" onmousemove="eigMove(event)" onmouseup="eigUp(event)" onmouseleave="eigUp(event)" ondblclick="eigReset()">${s}</svg>
  <div class="note" style="font-size:11px">drag a box to zoom · double-click to reset · click a × to read its value (or hover)</div>`;
}
function eigXY(ev){const svg=$('eigsvg');if(!svg)return[0,0];const r=svg.getBoundingClientRect();
 return [(ev.clientX-r.left)/r.width*EIGST.w,(ev.clientY-r.top)/r.height*EIGST.h];}
function eigDown(ev){if(!EIGST)return;const p=eigXY(ev);EIGST.drag={x:p[0],y:p[1],x2:p[0],y2:p[1]};}
function eigMove(ev){if(!EIGST||!EIGST.drag)return;const p=eigXY(ev),d=EIGST.drag;d.x2=p[0];d.y2=p[1];
 const b=$('eigband');if(b){b.setAttribute('x',Math.min(d.x,d.x2));b.setAttribute('y',Math.min(d.y,d.y2));
  b.setAttribute('width',Math.abs(d.x2-d.x));b.setAttribute('height',Math.abs(d.y2-d.y));b.style.display='';}}
function eigUp(ev){if(!EIGST||!EIGST.drag)return;const d=EIGST.drag;EIGST.drag=null;
 const b=$('eigband');if(b)b.style.display='none';
 if(Math.abs(d.x2-d.x)<8||Math.abs(d.y2-d.y)<8)return;          // too small -> click, not zoom
 const L=52,T=10,R=12,B=30,w=EIGST.w,h=EIGST.h;                 // axes() margins
 const invX=sx=>EIGST.x0+(sx-L)*(EIGST.x1-EIGST.x0)/((w-R)-L);
 const invY=sy=>EIGST.y0+(sy-(h-B))*(EIGST.y1-EIGST.y0)/(T-(h-B));
 const sx0=Math.min(d.x,d.x2),sx1=Math.max(d.x,d.x2),sy0=Math.min(d.y,d.y2),sy1=Math.max(d.y,d.y2);
 EIGST.x0=invX(sx0);EIGST.x1=invX(sx1);EIGST.y1=invY(sy0);EIGST.y0=invY(sy1);  // screen-top = higher imag
 eigRender();
}
function eigReset(){if(!EIGST)return;EIGST.x0=EIGST.dx0;EIGST.x1=EIGST.dx1;EIGST.y0=EIGST.dy0;EIGST.y1=EIGST.dy1;EIGST.pick=null;eigRender();}
function eigPick(k){if(!EIGST)return;EIGST.pick=(EIGST.pick===k?null:k);eigRender();}
// ---------- tabs ----------
function goTab(t){if(t===TAB){if(t==='net'&&NET)requestAnimationFrame(()=>draw());return;}
 TAB=t;
 document.querySelectorAll('#rail .railb').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
 for(const x of ['net','ss','td','ds','sc','st','ln','pvl','help'])$('tab-'+x).style.display=t===x?'':'none';
 $('main').style.display=t==='net'?'none':'';
 if(t==='st')try{stEnter();}catch(_){}
 if(t==='ln')try{lrnEnter();}catch(_){}
 if(t==='pvl')try{pvlEnter();}catch(_){}
 if(t==='net'&&NET)requestAnimationFrame(()=>draw());else mmDraw();}
function stat(m){const el=$('stMsg');if(el)el.textContent=m;}
function toggleSB(){pnToggle('model');}       // legacy View-menu entry -> Model panel
// interface renders at native 100%. CSS `zoom` is deliberately NOT used: it is a
// non-standard property that Qt WebEngine / older Chromium map inconsistently, which
// corrupted every mouse->canvas mapping (the "component drifts from the cursor" bug).
// UIS mirrors the body transform:scale (0.8) so manually-positioned overlays
// (floating panels, dock-drag) land correctly. The canvas mapping uses getScreenCTM.
function applyUI(sc,save){UIS=0.8;
 try{document.body.style.zoom='';}catch(_){}
 if(save)fetch('/api/uipref',{method:'POST',body:JSON.stringify({scale:0.8})}).catch(function(){});
 if(NET)draw();}
// ---------- active model: built-in vs drawn network ----------
let NET=null, ACTIVE='custom', HOMEXY=null;
let PMUV=null;                        // PMU-placement diagram overlay   // ONE model: the drawn network; HOMEXY = bus coords at import (Layout ▸ Restore)
let NU=40;   // adaptive network unit (median bus spacing) for flow-arrow sizing
let ASZ=8;   // adaptive flow-arrow size (world units), refreshed each draw
// ---------- diagram LAYOUT catalogue (the MATLAB edition's list) ----------
// Every algorithm is pure geometry on NET.buses; machines keep their own
// direction from their bus (re-anchored at a clean stand-off), the change is
// undoable, the view refits, and the auto power flow repaints the overlay.
function buildPayload(extra){const p=extra||{};
 // SINGLE SHARED MODEL: whenever a network is drawn/imported, EVERY analysis
 // (PF, small-signal, time-domain, sweep, POD design, Bode, signals) reads it.
 if(NET){p.net=NET;}else{p.system=$('sys').value;p.mix=mix();}
 p.prm=POV;return p;}
function mixActive(){return NET?NET.gens.map(g=>g.tag):mix();}
// ---------- extra chart types ----------
function compass(el,shape){const w=250,h=250,cx=w/2,cy=h/2,r=100;
 if(!shape||!shape.length){el.innerHTML='<div class="note">no inertial units in this mix</div>';return;}
 let s=`<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e3e7ef"/>`;
 s+=`<circle cx="${cx}" cy="${cy}" r="${r/2}" fill="none" stroke="#f0f2f7"/>`;
 s+=`<line x1="${cx-r}" y1="${cy}" x2="${cx+r}" y2="${cy}" stroke="#f0f2f7"/>`;
 s+=`<line x1="${cx}" y1="${cy-r}" x2="${cx}" y2="${cy+r}" stroke="#f0f2f7"/>`;
 const cols=['#1f3b73','#c0392b','#1e8449','#b7950b','#117a8b','#a04000','#8e44ad','#2c5aa0'];
 shape.forEach(([nm,re,im],i)=>{const mag=Math.hypot(re,im),x=cx+re*r*0.92,y=cy-im*r*0.92,c=cols[i%cols.length];
  s+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${c}" stroke-width="2"/>`;
  s+=`<circle cx="${x}" cy="${y}" r="3.4" fill="${c}"/>`;
  s+=`<text x="${cx+re*r*1.06-8}" y="${cy-im*r*1.06+4}" font-size="11" fill="${c}">${nm}</text>`;});
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="230">${s}</svg>
  <div class="note">arrows: speed-eigenvector phasors — opposite directions swing against each other</div>`;}
function locusChart(el,loci){const w=el.clientWidth||520,h=300;
 const all=[].concat(...loci);
 if(!all.length){el.innerHTML='<div class="note">no modes in range</div>';return;}
 let x0=Math.max(-12,Math.min(...all.map(e=>e[0]))-0.5),x1=Math.max(0.4,...all.map(e=>e[0]))+0.2;
 let y1=Math.max(5,...all.map(e=>Math.abs(e[1])))*1.06;
 const A=axes(w,h,x0,x1,0,y1,'Real (1/s)','Imag (rad/s)');let s=A.s;
 s+=`<rect x="${A.X(0)}" y="${A.T}" width="${Math.max(0,A.X(x1)-A.X(0))}" height="${h-A.B-A.T}" fill="#fde8e8" opacity="0.5"/>`;
 s+=`<line x1="${A.X(0)}" y1="${A.T}" x2="${A.X(0)}" y2="${h-A.B}" stroke="#b42318"/>`;
 const n=loci.length;
 loci.forEach((ev,i)=>{const f=0.25+0.75*i/Math.max(n-1,1);
  const c=`rgba(31,59,115,${f.toFixed(2)})`;
  for(const e of ev){if(e[1]<0||e[0]<x0)continue;
   s+=`<circle cx="${A.X(e[0])}" cy="${A.Y(e[1])}" r="${2+2*f}" fill="${c}"/>`;}});
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s}</svg>`;}
function overlayChart(el,ev0,ev1){const w=el.clientWidth||520,h=320;
 const all=ev0.concat(ev1);
 let x0=Math.max(-12,Math.min(-1,...all.map(e=>e[0]).filter(v=>v>-40))),x1=Math.max(0.4,...all.map(e=>e[0]));
 let y1=Math.max(5,...all.map(e=>Math.abs(e[1])))*1.06;
 const A=axes(w,h,x0,x1,-y1,y1,'Real (1/s)','Imag (rad/s)');let s=A.s;
 s+=`<line x1="${A.X(0)}" y1="${A.T}" x2="${A.X(0)}" y2="${h-A.B}" stroke="#b42318"/>`;
 for(const e of ev0){if(e[0]<x0)continue;
  s+=`<path d="M${A.X(e[0])-4} ${A.Y(e[1])-4} l8 8 M${A.X(e[0])-4} ${A.Y(e[1])+4} l8 -8" stroke="#1f3b73" stroke-width="1.6"/>`;}
 for(const e of ev1){if(e[0]<x0)continue;
  s+=`<circle cx="${A.X(e[0])}" cy="${A.Y(e[1])}" r="4.5" fill="none" stroke="#a04000" stroke-width="1.6"/>`;}
 s+=`<text x="${A.L+10}" y="${A.T+12}" font-size="11"><tspan fill="#1f3b73">× open loop</tspan><tspan dx="14" fill="#a04000">○ with POD</tspan></text>`;
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s}</svg>`;}
// ============================ SLD EDITOR ============================
let DTOOL='select', DSEL=null, DPEND=null, DPF=null, DDRAG=null, VB=[0,0,1040,620];
let MSEL=[], UST=[], URD=[], NUDGT=0, BRAX=[], UIS=1, LOCKED=false, ZANIM=0,
    TAB='net', MMAP=false, WHEELUNTIL=0, WHEELTO=0, DRAWRAF=0, FLOWSPD=1.0,
    ASZK=1.0, LBLK=1.0, HDLEVEL=1, HTRANS=0.5, HSMOOTH=1.0,
    HINTENS=1.0, HCONTR=1.0, HLEVELS=0, HRES=1.0,   // heat map: colour intensity · contrast · contour bands (0 = continuous) · resolution ×
    VOPT={grid:true,ortho:false,anim:false,critL:false,critB:false,cont:false},
    HVAR='vmag',       // heat-map variable: vmag|vang|p|q|i|ploss|qloss|loading|util
    LOPT={pf:true,volt:true,bus:true,lname:false,gen:true,load:true};
const GRID=10;
// heat-map (voltage-contour) density presets: cells across the field width + a
// hard cell-count cap for speed.  Low keeps big systems fast; Ultra is a fine,
// PowerWorld-smooth field for publication figures. Index by HDLEVEL (0..3).
const HDENS=[{n:70,cap:4200,l:'Low'},{n:120,cap:9500,l:'Medium'},
             {n:185,cap:24000,l:'High'},{n:270,cap:52000,l:'Ultra'}];
const _now=()=>(window.performance&&performance.now)?performance.now():+new Date();
// coalesce interactive redraws to one per animation frame
function qdraw(){if(!DRAWRAF)DRAWRAF=requestAnimationFrame(()=>{DRAWRAF=0;draw();});}
// true while the user is actively dragging / zooming — draw() runs a cheap fast path
function interacting(){return !!DDRAG||!!PNEW||!!ZANIM||_now()<WHEELUNTIL;}
const TAGC={'SG':'#1f3b73','SGP':'#5b21b6','SGF':'#5b21b6','SG6G':'#1f3b73','SG6':'#1f3b73','SG6P':'#5b21b6','SG4G':'#1f3b73','SG4':'#1f3b73','SG2':'#1f3b73',
 'GFM':'#1e8449','GFL':'#c0392b','PV-GFL':'#b7950b','PV-GFM':'#b7950b',
 'BESS-GFM':'#a04000','BESS-GFL':'#a04000','WT4-GFL':'#117a8b','WT4-GFM':'#117a8b',
 'WT3':'#117a8b','WT1':'#117a8b','WT2':'#117a8b'};
const TAGS={'SG':'SG','SGP':'SGp','SGF':'FLC','SG6G':'S6g','SG6':'SG6','SG6P':'S6p','SG4G':'S4g','SG4':'SG4','SG2':'SG2',
 'GFM':'GFM','GFL':'GFL','PV-GFL':'PV','PV-GFM':'PV','BESS-GFM':'BES',
 'BESS-GFL':'BES','WT4-GFL':'W4','WT4-GFM':'W4','WT3':'W3','WT1':'W1','WT2':'W2'};
// Flow indicator: a train of CHEVRON arrowheads sitting exactly on the line,
// pointing in the real-power direction, marching when Flow-Arrows is on.
// (Chevrons — not dashes: a short thick dash renders as a rectangle.  Motion is
//  animateTransform/translate, which — unlike animateMotion+mpath — is reliable
//  in the Qt WebEngine desktop window.)
// user flow-speed control (ribbon − / +): multiplies the marching speed
// adaptive network unit = 0.42 x median nearest-neighbour bus spacing, so the
// flow arrows auto-scale with network size / branch length (same rule as MATLAB)
function netunit(){
 const B=NET&&NET.buses?NET.buses:[]; const n=B.length; if(n<2)return 40;
 let d=[]; for(let i=0;i<n;i++){let m=1e18; for(let j=0;j<n;j++){if(i===j)continue;
  const dd=Math.hypot(B[i].x-B[j].x,B[i].y-B[j].y); if(dd<m)m=dd;} d.push(m);}
 d.sort((a,b)=>a-b); return Math.max(12, Math.min(120, 0.42*d[Math.floor(n/2)]));
}
function arrowsize(){
 // MATLAB-parity flow-arrow size: base 0.26*NU, shrunk on larger networks by
 // sqrt(9/nbus), clamped so arrows stay small & refined on big systems yet
 // clearly visible on small ones.
 const nb=(NET&&NET.buses)?NET.buses.length:9;
 const fN=Math.min(1,Math.max(0.45,Math.sqrt(9/nb)));
 return Math.max(2.5, Math.min(0.26*NU*fN, 16))*ASZK;   // ×ASZK: user arrow-size setting
}
function flowSpeed(d){
 const st=[0.33,0.48,0.69,1.0,1.44,2.07,3.0];   // default 0.33; three + taps -> 1.0 (normal)
 let i=0; for(let k=1;k<st.length;k++)if(Math.abs(st[k]-FLOWSPD)<Math.abs(st[i]-FLOWSPD))i=k;
 i=Math.max(0,Math.min(st.length-1,i+d)); FLOWSPD=st[i];
 stat('flow-arrow speed '+Math.round(FLOWSPD*100)+'%');
 if(VOPT.anim&&DPF)draw();
}
function flowGlide(idx,pts,fwd,col,wd,vpx){
 let P=pts.map(p=>[p[0],p[1]]); if(!fwd)P.reverse();
 const seg=[]; let tot=0;
 for(let k=1;k<P.length;k++){const ax=P[k][0]-P[k-1][0],ay=P[k][1]-P[k-1][1],L=Math.hypot(ax,ay)||1;
  seg.push({x0:P[k-1][0],y0:P[k-1][1],x1:P[k][0],y1:P[k][1],ux:ax/L,uy:ay/L,L}); tot+=L;}
 if(tot<10||!seg.length)return '';
 // split the polyline into ~straight RUNS at corners (>~40deg): each run marches
 // along ITS OWN direction, so orthogonal right-angle routes flow correctly (a
 // single translate vector can only follow a straight/gently-curved path).
 const runs=[]; let cur=[seg[0]];
 for(let k=1;k<seg.length;k++){
  if(seg[k].ux*seg[k-1].ux+seg[k].uy*seg[k-1].uy < 0.77){runs.push(cur);cur=[seg[k]];}
  else cur.push(seg[k]);
 }
 runs.push(cur);
 // MATLAB-style filled arrowheads, adaptive to the network unit NU
 const sz=ASZ, hw=0.60*sz, SP=Math.max(3.0*NU,4*sz), W=Math.max((wd+7)/2,hw+2);
 const dur=Math.max(SP/vpx,0.14).toFixed(2);   // one period; SP/vpx keeps px/s speed independent of density
 let out='';
 runs.forEach((rs,ri)=>{
  let rtot=0; rs.forEach(g=>rtot+=g.L); if(rtot<9)return;
  const dux=rs[0].ux,duy=rs[0].uy;            // this run's march direction
  let ch='';
  // tile chevrons ONE FULL PERIOD past BOTH ends (-SP .. rtot+SP): translating
  // by exactly SP then maps the clipped-visible set onto itself, so the loop
  // reset is pixel-identical — no snap-back (which the eye reads as reversing).
  for(let s=-SP; s<=rtot+SP+0.01; s+=SP){
   let ss=s,si=0; while(si<rs.length-1&&ss>rs[si].L){ss-=rs[si].L;si++;}
   const g=rs[si],ux=g.ux,uy=g.uy,nx=-uy,ny=ux;
   const px=g.x0+ux*ss,py=g.y0+uy*ss;         // ss<0 => lead-in arrow (clipped until it enters)
   const tx=px+ux*sz,ty=py+uy*sz;             // filled tapered arrowhead (MATLAB style)
   const axp=px-ux*sz*0.5+nx*hw,ayp=py-uy*sz*0.5+ny*hw, bxp=px-ux*sz*0.5-nx*hw,byp=py-uy*sz*0.5-ny*hw;
   ch+=`<path d="M${tx.toFixed(1)} ${ty.toFixed(1)}L${axp.toFixed(1)} ${ayp.toFixed(1)}L${bxp.toFixed(1)} ${byp.toFixed(1)}Z" fill="rgb(41,107,77)" stroke="none" opacity="0.92"/>`;
  }
  const rp=[[rs[0].x0,rs[0].y0]]; rs.forEach(g=>rp.push([g.x1,g.y1]));   // clip polygon for this run
  let up='',dn=[];
  for(let k=0;k<rp.length;k++){let nx,ny;
   if(k===0){nx=-rs[0].uy;ny=rs[0].ux;}
   else if(k===rp.length-1){nx=-rs[rs.length-1].uy;ny=rs[rs.length-1].ux;}
   else{nx=-(rs[k-1].uy+rs[k].uy);ny=rs[k-1].ux+rs[k].ux;const nl=Math.hypot(nx,ny)||1;nx/=nl;ny/=nl;}
   up+=`${(rp[k][0]+nx*W).toFixed(1)},${(rp[k][1]+ny*W).toFixed(1)} `;
   dn.unshift(`${(rp[k][0]-nx*W).toFixed(1)},${(rp[k][1]-ny*W).toFixed(1)}`);
  }
  out+=`<clipPath id="fclip${idx}_${ri}"><polygon points="${up}${dn.join(' ')}"/></clipPath>`+
   `<g class="fglide" clip-path="url(#fclip${idx}_${ri})" pointer-events="none"><g>${ch}`+
   `<animateTransform attributeName="transform" type="translate" values="0 0;${(dux*SP).toFixed(2)} ${(duy*SP).toFixed(2)}" dur="${dur}s" repeatCount="indefinite"/></g></g>`;
 });
 return out;
}
// One chevron at the arc-length midpoint of the drawn line (flow OFF): uses the
// SAME on-line geometry as the marching chevrons, so it is exactly aligned with
// the line (the old marker arrow used the bus-centre direction and drifted off
// diagonal lines).  Points in the real-power direction.
function midChevron(pts,fwd,col,sel){
 let P=pts.map(p=>[p[0],p[1]]); if(!fwd)P.reverse();
 const seg=[]; let tot=0;
 for(let k=1;k<P.length;k++){const ax=P[k][0]-P[k-1][0],ay=P[k][1]-P[k-1][1],L=Math.hypot(ax,ay)||1;
  seg.push({x:P[k-1][0],y:P[k-1][1],ux:ax/L,uy:ay/L,L}); tot+=L;}
 if(!seg.length||tot<1)return '';
 let s=tot/2,si=0; while(si<seg.length-1&&s>seg[si].L){s-=seg[si].L;si++;}
 const g=seg[si],ux=g.ux,uy=g.uy,nx=-uy,ny=ux,px=g.x+ux*s,py=g.y+uy*s;
 const sz=ASZ,hw=0.60*sz;      // filled arrowhead, adaptive (MATLAB parity)
 const tx=px+ux*sz,ty=py+uy*sz, a1x=px-ux*sz*0.5+nx*hw,a1y=py-uy*sz*0.5+ny*hw, a2x=px-ux*sz*0.5-nx*hw,a2y=py-uy*sz*0.5-ny*hw;
 return `<path d="M${tx.toFixed(1)} ${ty.toFixed(1)}L${a1x.toFixed(1)} ${a1y.toFixed(1)}L${a2x.toFixed(1)} ${a2y.toFixed(1)}Z" fill="${sel?'#e67e22':'rgb(41,107,77)'}" stroke="none"/>`;
}
function setTool(t){DTOOL=t;DPEND=null;
 document.querySelectorAll('.tool[data-tool]').forEach(b=>b.classList.toggle('on',b.dataset.tool===t));
 $('sld').style.cursor=t==='select'?'default':'crosshair';draw();}
async function loadNet(sysname){STDIRTY=true;
 // Import a benchmark into the editor.  From that moment the DIAGRAM is the one
 // shared model: every analysis (PF, small-signal, time-domain, design, signals)
 // reads the current drawing — there is no separate "built-in" model to drift.
 const sysSel=$('sys');            // keep the import picker in step (cosmetic)
 if(sysSel&&sysSel.value!==sysname&&
    [...sysSel.options].some(o=>o.value===sysname))sysSel.value=sysname;
 $('spN').style.display='inline';
 const keep=(NET&&$('sys').value===sysname)?mix():undefined;   // re-import: keep unit techs
 const r=await api('/api/netload',{system:sysname,mix:keep});
 $('spN').style.display='none';
 if(r.error){netErr(friendlyErr(r.error));return;}
 NET=r;DPF=null;DSEL=null;MSEL=[];UST=[];URD=[];POV={};
 ACTIVE='custom';HOMEXY=netHomeXY();PRMCACHE=null;PRMDIRTY=true;
 netErr('');fitView();prop();$('pfsum').textContent='';buildSide();fillDesign();try{datRender();}catch(_){}stat('loaded '+NET.name+' — the diagram is now the model for every analysis');
 try{rexLog('loaded '+NET.name+' — '+NET.buses.length+' buses, '+NET.branches.length+' branches, '+NET.gens.length+' machines');}catch(_){}}
function netHomeXY(){return NET?NET.buses.map(b=>[b.x,b.y]):null;}   // snapshot for Layout ▸ Restore
function newNet(){NET={name:'my system',buses:[],branches:[],gens:[],facts:[]};DPF=null;DSEL=null;MSEL=[];UST=[];URD=[];POV={};
 ACTIVE='custom';HOMEXY=null;PRMCACHE=null;PRMDIRTY=true;
 VB=[0,0,900,560];netErr('');draw();prop();buildSide();fillDesign();try{datRender();}catch(_){}}
function netErr(m){$('netErr').innerHTML=m?`<div class="err">${m}</div>`:'';if(m)stat(m);}
// Reset: recover from any error/stuck state and reload a clean, solvable network.
function resetNet(){
 DPF=null;DSEL=null;MSEL=[];DPEND=null;DDRAG=null;PNEW=null;WHEELUNTIL=0;
 try{document.body.classList.remove('dropping');}catch(_){}
 ['spN','spL','spT','spSw','spPd','spBd','spS'].forEach(id=>{const el=$(id);if(el)el.style.display='none';});
 ['runL','runT','runSw','runPd','runBd'].forEach(id=>{const el=$(id);if(el)el.disabled=false;});
 ['ssErr','tdErr','swErr','pdErr','bdErr','scErr'].forEach(id=>{const el=$(id);if(el)el.innerHTML='';});
 netErr('');const pf=$('pfsum');if(pf)pf.textContent='';
 const sys=($('sys')&&$('sys').value&&$('sys').value!=='__custom')?$('sys').value:'IEEE9';
 goTab('net');loadNet(sys);
 stat('reset — reloaded '+sys+' (a clean, solvable network)');}
function edited(){if(!NET)return;
 if(!NET.name.includes('(edited)'))NET.name+=' (edited)';
 ACTIVE='custom';                       // any edit -> the diagram stays the master model
 PMUV=null;                             // a model change makes a PMU placement stale
 DPF=null;$('pfsum').textContent='';STDIRTY=true;PRMDIRTY=true;
 try{datRender();}catch(_){}
 autoPF();}                             // ...and the consequence shows IMMEDIATELY
let APFT=null;
function autoPF(){
 // AUTO REFRESH (mirrors the MATLAB edition): any edit that changes the
 // model -- a new load, shunt, FACTS device, generator, a deleted line, an
 // applied parameter -- re-solves the power flow silently and repaints the
 // overlay, so the effect is visible without pressing Run.  Debounced so a
 // burst of edits (or a drag) solves once; networks over 120 buses keep
 // edits instant and ask for a manual run; half-built networks (no slack,
 // no generator yet) stay quiet until they are actually runnable.
 clearTimeout(APFT);
 APFT=setTimeout(async()=>{try{
  if(!NET||!NET.buses||!NET.buses.length||!NET.gens||!NET.gens.length)return;
  if(!NET.buses.some(b=>b.type==='slack'))return;
  if(NET.buses.length>120){stat('edited — run Power flow to refresh results');return;}
  const pm=($('pfmeth')||{}).value||'nr';
  const r=await api('/api/pf',{net:NET,pfmethod:pm});
  if(!r||r.error)return;                // quiet + honest: a half-wired net stays pending
  DPF=r;syncView();draw();
  try{rexRender();}catch(_){}
  const el=$('pfsum');
  if(el)el.innerHTML=`<b>Power flow (auto-refreshed).</b><br>generation ${r.Ptot} MW · load ${r.Pload} MW · losses ${(r.Ptot-r.Pload).toFixed(1)} MW`;
  stat('power flow refreshed automatically');
 }catch(_){}},350);}
// ---- undo / redo (full-diagram snapshots) ----
function pushU(keep){if(!NET)return;UST.push(JSON.stringify(NET));if(UST.length>80)UST.shift();if(!keep)URD=[];}
function undo(){if(!UST.length||!NET)return;URD.push(JSON.stringify(NET));NET=JSON.parse(UST.pop());
 DSEL=null;MSEL=[];DPEND=null;DPF=null;$('pfsum').textContent='';draw();prop();syncSide();autoPF();}
function redo(){if(!URD.length||!NET)return;UST.push(JSON.stringify(NET));NET=JSON.parse(URD.pop());
 DSEL=null;MSEL=[];DPEND=null;DPF=null;$('pfsum').textContent='';draw();prop();syncSide();autoPF();}
// ---- viewport: exact screen<->world map (letterbox-aware), fit, zoom ----
function svgScale(){const r=$('sld').getBoundingClientRect();return Math.min(r.width/VB[2],r.height/VB[3]);}
// screen -> world. Uses the SVG's own transform matrix (getScreenCTM) so it is
// exact under ANY page zoom / device-pixel-ratio / letterboxing — the mouse maps
// to the SAME point the diagram is drawn at, in every browser and the Qt window.
function s2w(e){const svg=$('sld');
 try{const m=svg.getScreenCTM&&svg.getScreenCTM();
  if(m&&(m.a||m.d)){const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;
   const w=pt.matrixTransform(m.inverse());
   if(isFinite(w.x)&&isFinite(w.y))return [w.x,w.y];}}catch(_){}
 const r=svg.getBoundingClientRect(),sc=Math.min(r.width/VB[2],r.height/VB[3])||1;   // fallback
 const ox=(r.width-VB[2]*sc)/2, oy=(r.height-VB[3]*sc)/2;
 return [VB[0]+(e.clientX-r.left-ox)/sc, VB[1]+(e.clientY-r.top-oy)/sc];}
function zPct(){const t=Math.round(svgScale()*100)+'%';
 const el=$('zpct');if(el)el.textContent=t;}
function fitView(anim){if(!NET||!NET.buses.length){VB=[0,0,900,560];draw();return;}
 const xs=[],ys=[];
 NET.buses.forEach(b=>{xs.push(b.x-75,b.x+75);ys.push(b.y-45,b.y+58);});
 NET.gens.forEach(g=>{xs.push(g.x-46,g.x+46);ys.push(g.y-40,g.y+40);});
 if(NET.notes)NET.notes.forEach(nt=>{xs.push(nt.x-10,nt.x+90);ys.push(nt.y-16,nt.y+16);});
 let x0=Math.min(...xs),y0=Math.min(...ys),w=Math.max(Math.max(...xs)-x0,140),h=Math.max(Math.max(...ys)-y0,140);
 const r=$('sld').getBoundingClientRect(),ar=(r.width||1040)/Math.max(r.height,1);
 if(w/h<ar){const w2=h*ar;x0-=(w2-w)/2;w=w2;}else{const h2=w/ar;y0-=(h2-h)/2;h=h2;}
 const tgt=[x0-15,y0-15,w+30,h+30];
 if(anim===false){VB=tgt;draw();}else animVB(tgt);}
function zoomBtn(f){const cx=VB[0]+VB[2]/2,cy=VB[1]+VB[3]/2;
 animVB([cx-VB[2]/(2*f),cy-VB[3]/(2*f),VB[2]/f,VB[3]/f],110);}
function tgl(k){VOPT[k]=!VOPT[k];syncView();
 if((k==='anim'||k==='critL'||k==='critB'||k==='cont')&&VOPT[k]&&!DPF)stat('run a power flow first — then this view comes alive');
 draw();}
function tglL(k){LOPT[k]=!LOPT[k];syncView();draw();}
function lblAll(on){if(on===undefined)on=!Object.values(LOPT).some(v=>v);
 for(const k in LOPT)LOPT[k]=!!on;
 syncView();draw();stat(on?'all label classes on':'labels hidden — geometry only');}
function syncView(){                     // one place: every toggle button + menu check
 const bt={grid:'rbGrid',ortho:'rbOrtho',anim:'rbAnim',critL:'rbCritL',critB:'rbCritB',cont:'rbCont'};
 for(const k in bt){const el=$(bt[k]);if(el)el.classList.toggle('on',!!VOPT[k]);}
 const anyLbl=Object.values(LOPT).some(v=>v),rbl=$('rbLabels');
 if(rbl)rbl.classList.toggle('on',anyLbl);
 const ck={pf:'ckPf',volt:'ckVolt',bus:'ckBus',lname:'ckLn',gen:'ckGen',load:'ckLoad'};
 for(const k in ck){const el=$(ck[k]);if(el)el.style.visibility=LOPT[k]?'visible':'hidden';}
 const fs=document.body.classList.contains('fs');
 const mk={vGrid:VOPT.grid,vGrid2:VOPT.grid,vOrtho:VOPT.ortho,vOrtho2:VOPT.ortho,vAnim:VOPT.anim,
  vCritL:VOPT.critL,vCritB:VOPT.critB,vCont:VOPT.cont,vMmap:MMAP,vFs:fs,
  vLbl:anyLbl,vLock:LOCKED};
 for(const id in mk){const el=$(id);if(el)el.style.visibility=mk[id]?'visible':'hidden';}
 const lk=$('rbLock'),ul=$('rbUnlock'),mb=$('rbMmap'),fb=$('rbFs'),sl=$('stLock');
 if(lk)lk.classList.toggle('on',LOCKED);
 if(ul)ul.classList.toggle('on',!LOCKED);
 if(mb)mb.classList.toggle('on',MMAP);
 if(fb)fb.classList.toggle('on',fs);
 if(sl)sl.textContent=LOCKED?'🔒 layout locked':'';}
// ---------------- Visualization settings panel (View ▸ Visualization settings) ----------------
// One place to tune the diagram: flow-arrow speed/size, heat-map density /
// transparency / contour smoothing, and label size + which label classes show.
function openViz(){vizBuild();$('viz').style.display='flex';}
function vizBuild(){
 const H='font-weight:700;color:var(--navy);margin:9px 0 3px;font-size:12.5px';
 const seg=HDENS.map((d,i)=>`<button class="tbtn${i===HDLEVEL?' on':''}" style="padding:3px 9px" onclick="setHeatDens(${i})">${d.l}</button>`).join(' ');
 const cls=[['pf','Power-flow'],['volt','Voltage'],['bus','Bus #'],['lname','Line names'],['gen','Generators'],['load','Loads']];
 const lc=cls.map(c=>`<label style="margin-right:13px;white-space:nowrap"><input type="checkbox" ${LOPT[c[0]]?'checked':''} onchange="vizLbl('${c[0]}')"> ${c[1]}</label>`).join('');
 const row=(lab,ctrl,id)=>`<div class="pl"><span>${lab}</span>${ctrl}<b id="${id}" style="text-align:right;color:var(--navy)"></b></div>`;
 const rng=(mn,mx,st,v,k)=>`<input type="range" min="${mn}" max="${mx}" step="${st}" value="${v}" oninput="vizSet('${k}',this.value)" style="width:100%">`;
 $('vizBody').innerHTML=
  `<div style="${H}">Motion</div>`+
  row('Arrow speed',rng(0.2,3,0.05,FLOWSPD,'FLOWSPD'),'vzSpd')+
  row('Arrow size',rng(0.5,2.5,0.05,ASZK,'ASZK'),'vzArr')+
  `<div class="pl" style="grid-template-columns:86px 1fr"><span>Flow arrows</span><label style="font-size:12.5px"><input type="checkbox" id="vzAnim" onchange="vizToggle('anim')"> animate marching arrows</label></div>`+
  `<div style="${H}">Heat map · voltage contour</div>`+
  `<div class="pl" style="grid-template-columns:86px 1fr"><span>Density</span><div>${seg}</div></div>`+
  row('Resolution',rng(0.5,2.5,0.05,HRES,'HRES'),'vzRes')+
  row('Opacity',rng(0.15,0.9,0.05,HTRANS,'HTRANS'),'vzTr')+
  row('Intensity',rng(0.3,1.8,0.05,HINTENS,'HINTENS'),'vzInt')+
  row('Contrast',rng(0.4,2.5,0.05,HCONTR,'HCONTR'),'vzCon')+
  row('Smoothing',rng(0.3,2.5,0.05,HSMOOTH,'HSMOOTH'),'vzSm')+
  row('Bands',rng(0,12,1,HLEVELS,'HLEVELS'),'vzLev')+
  `<div class="pl" style="grid-template-columns:86px 1fr"><span>Contour</span><label style="font-size:12.5px"><input type="checkbox" id="vzCont" onchange="vizToggle('cont')"> show smooth voltage field</label></div>`+
  `<div style="${H}">Labels</div>`+
  row('Label size',rng(0.6,1.8,0.05,LBLK,'LBLK'),'vzLb')+
  `<div class="pl" style="grid-template-columns:86px 1fr;align-items:start"><span>Show</span><div style="font-size:12.5px;line-height:2">${lc}</div></div>`;
 const a=$('vzAnim');if(a)a.checked=VOPT.anim;
 const c=$('vzCont');if(c)c.checked=VOPT.cont;
 vizVals();
}
function vizVals(){const set=(id,v)=>{const e=$(id);if(e)e.textContent=v;};
 set('vzSpd',Math.round(FLOWSPD*100)+'%');set('vzArr',ASZK.toFixed(2)+'×');
 set('vzTr',Math.round(HTRANS*100)+'%');set('vzSm',HSMOOTH.toFixed(2)+'×');
 set('vzRes',HRES.toFixed(2)+'×');set('vzInt',Math.round(HINTENS*100)+'%');
 set('vzCon',HCONTR.toFixed(2)+'×');set('vzLev',HLEVELS>=2?HLEVELS+' bands':'continuous');
 set('vzLb',LBLK.toFixed(2)+'×');}
function vizSet(k,v){v=parseFloat(v);
 if(k==='FLOWSPD')FLOWSPD=v;else if(k==='ASZK')ASZK=v;else if(k==='HTRANS')HTRANS=v;
 else if(k==='HSMOOTH')HSMOOTH=v;else if(k==='LBLK')LBLK=v;
 else if(k==='HINTENS')HINTENS=v;else if(k==='HCONTR')HCONTR=v;
 else if(k==='HLEVELS')HLEVELS=(v<2?0:Math.round(v));else if(k==='HRES')HRES=v;
 vizVals();vizSave();qdraw();}
let VIZSAVT=0;
function vizSave(){clearTimeout(VIZSAVT);            // persist the visual tuning (debounced)
 VIZSAVT=setTimeout(()=>{fetch('/api/uipref',{method:'POST',body:JSON.stringify({viz2:{
  sp:FLOWSPD,as:ASZK,lb:LBLK,dl:HDLEVEL,tr:HTRANS,sm:HSMOOTH,
  it:HINTENS,co:HCONTR,lv:HLEVELS,rs:HRES}})}).catch(()=>{});},400);}
function vizLoad(u){if(!u)return;
 const g=(k,d)=>(u[k]!==undefined&&isFinite(u[k]))?+u[k]:d;
 FLOWSPD=g('sp',1);ASZK=g('as',1);LBLK=g('lb',1);HDLEVEL=Math.max(0,Math.min(3,Math.round(g('dl',1))));
 HTRANS=g('tr',0.5);HSMOOTH=g('sm',1);HINTENS=g('it',1);HCONTR=g('co',1);
 HLEVELS=Math.max(0,Math.round(g('lv',0)));HRES=g('rs',1);}
function setHeatDens(i){HDLEVEL=i;
 document.querySelectorAll('#vizBody .tbtn').forEach((b,j)=>b.classList.toggle('on',j===i));
 stat('heat-map density: '+HDENS[i].l+(VOPT.cont?'':' — turn on the voltage contour to see it'));vizSave();qdraw();}
function vizToggle(k){tgl(k);const cb=$(k==='anim'?'vzAnim':'vzCont');if(cb)cb.checked=VOPT[k];}
function vizLbl(k){tglL(k);}
function vizReset(){FLOWSPD=1;ASZK=1;LBLK=1;HDLEVEL=1;HTRANS=0.5;HSMOOTH=1;
 HINTENS=1;HCONTR=1;HLEVELS=0;HRES=1;
 vizBuild();vizSave();qdraw();stat('visualization settings reset to defaults');}
// ---- ribbon Run / Reset / Report: act on the active workspace ----
function runActive(){
 if(TAB==='net'){runPF();return;}
 const fn={ss:()=>$('runL')&&$('runL').click(),td:runT,ds:()=>$('runSw')&&$('runSw').click()}[TAB];
 if(fn)fn();else stat('nothing to run in this view');}
function resetActive(){
 if(TAB==='net'){DPF=null;$('pfsum').textContent='';draw();stat('power-flow results cleared');return;}
 if(TAB==='td'){$('dkind').value='load';$('dkind').onchange();$('cfrq').innerHTML=$('cspd').innerHTML=$('cwatch').innerHTML='';$('nad').textContent='';stat('time-domain reset');return;}
 if(TAB==='ss'){const tb=document.querySelector('#mtab tbody');if(tb)tb.innerHTML='';$('eig').innerHTML=$('part').innerHTML=$('shape').innerHTML='';stat('small-signal cleared');return;}
 if(TAB==='pvl'){try{pvlReset();}catch(_){}stat('PV Lab reset to standard test conditions');return;}
 if(TAB==='st'){['pvChart','n1Tab','stscTab','cctChart','edTab','edLmp','oppTab','pvErr','n1Err','stscErr','cctErr','edErr','oppErr'].forEach(id=>{const e=$(id);if(e)e.innerHTML='';});
  ['pvOut','n1Out','stscOut','cctOut','edOut','edBind','oppOut'].forEach(id=>{const e=$(id);if(e&&e.dataset)e.textContent='';});oppClear();stat('studies cleared');return;}
 stat('reset');}
function reportPF(){if(TAB!=='net')goTab('net');
 if(!DPF){runPF();stat('running power flow for the report…');return;}
 pnShow('props');stat('power-flow summary shown in Properties');}
function rq(f){if(TAB!=='net')goTab('net');f();}   // quick-op: jump to the editor first
function setLock(v){LOCKED=!!v;syncView();
 stat(LOCKED?'layout locked — selection and viewing only (K unlocks)':'layout unlocked');}
function kbdShow(){$('kbd').style.display='flex';}
function selectAll(){if(!NET)return;MSEL=[];
 NET.buses.forEach((b,i)=>MSEL.push({t:'bus',i}));
 NET.gens.forEach((g,i)=>MSEL.push({t:'gen',i}));
 DSEL=null;prop();draw();stat(MSEL.length+' elements selected');}
// ---- align / distribute the box-selected buses ----
function movBus(i,dx,dy){const b=NET.buses[i];b.x+=dx;b.y+=dy;
 NET.gens.forEach(g=>{if(g.bus===i+1){g.x+=dx;g.y+=dy;}});}
function alignSel(m){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 const bi=MSEL.filter(x=>x.t==='bus').map(x=>x.i);
 if(bi.length<2){stat('Shift-drag a box around two or more buses first — then Align');return;}
 pushU();
 const xs=bi.map(i=>NET.buses[i].x),ys=bi.map(i=>NET.buses[i].y);
 let t;
 if(m==='l')t=Math.min(...xs);else if(m==='r')t=Math.max(...xs);
 else if(m==='c')t=(Math.min(...xs)+Math.max(...xs))/2;
 else if(m==='t')t=Math.min(...ys);else if(m==='b')t=Math.max(...ys);
 else t=(Math.min(...ys)+Math.max(...ys))/2;
 t=snapv(t);
 bi.forEach(i=>{const b=NET.buses[i];
  if(m==='l'||m==='c'||m==='r')movBus(i,t-b.x,0);else movBus(i,0,t-b.y);});
 draw();stat('aligned '+bi.length+' buses');}
function distSel(m){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 const bi=MSEL.filter(x=>x.t==='bus').map(x=>x.i);
 if(bi.length<3){stat('select three or more buses (Shift-drag) — then Distribute');return;}
 pushU();
 const key=m==='h'?'x':'y';
 const ord=[...bi].sort((a,b)=>NET.buses[a][key]-NET.buses[b][key]);
 const v0=NET.buses[ord[0]][key],v1=NET.buses[ord[ord.length-1]][key];
 ord.forEach((i,k)=>{const tv=snapv(v0+(v1-v0)*k/(ord.length-1)),b=NET.buses[i];
  if(m==='h')movBus(i,tv-b.x,0);else movBus(i,0,tv-b.y);});
 draw();stat('distributed '+bi.length+' buses evenly');}
// ---- beautify / full auto-arrange (polish passes over the existing geometry) ----
function orientBars(){const n=NET.buses.length,adj=Array.from({length:n},()=>[]);
 NET.branches.forEach(br=>{const a=br.f-1,b=br.t-1;
  if(a>=0&&b>=0&&a<n&&b<n&&a!==b){adj[a].push(b);adj[b].push(a);}});
 NET.buses.forEach((b,i)=>{let H=0,Vv=0;
  adj[i].forEach(v=>{const o=NET.buses[v];
   const dx=Math.abs(o.x-b.x),dy=Math.abs(o.y-b.y),dd=Math.hypot(dx,dy)||1;
   H+=dx/dd;Vv+=dy/dd;});
  b.rot=(adj[i].length&&H>Vv*1.2)?1:0;b.flip=0;});}
function beautify(){if(!NET||!NET.buses.length)return;
 if(LOCKED){stat('layout is locked');return;}
 pushU();
 NET.branches.forEach(b2=>{delete b2.co;});
 NET.buses.forEach(b=>{b.x=Math.round(b.x/GRID)*GRID;b.y=Math.round(b.y/GRID)*GRID;});
 orientBars();placeGens();
 if(!VOPT.ortho){VOPT.ortho=true;syncView();}
 fitView();prop();
 stat('beautified — grid-snapped, bars oriented, machines re-seated, right-angle routed');}
function autoArrangeFull(){if(!NET||NET.buses.length<2)return;
 if(LOCKED){stat('layout is locked');return;}
 autoArrange();orientBars();placeGens();
 if(!VOPT.ortho){VOPT.ortho=true;syncView();}
 fitView();stat('auto-arranged — untangled, oriented, routed, fitted');}
// ---- animated viewport (smooth zoom-to) ----
let VBRAF=0;
function animVB(tgt,ms){ms=ms||150;const f0=[...VB],t0=performance.now();
 if(VBRAF)cancelAnimationFrame(VBRAF);ZANIM=1;
 const stp=now=>{const k=Math.min(1,(now-t0)/ms),e=1-Math.pow(1-k,3);
  VB=f0.map((v,i)=>v+(tgt[i]-v)*e);
  if(k<1){draw();VBRAF=requestAnimationFrame(stp);}
  else{VBRAF=0;ZANIM=0;VB=[...tgt];draw();}};
 VBRAF=requestAnimationFrame(stp);}
function zoomSel(){if(!NET)return;
 const items=MSEL.length?MSEL:(DSEL?[DSEL]:[]);
 if(!items.length){stat('select something first — then Zoom to Selection (S)');return;}
 const xs=[],ys=[];
 for(const m of items){
  if(m.t==='bus'&&NET.buses[m.i]){const b=NET.buses[m.i];xs.push(b.x-75,b.x+75);ys.push(b.y-50,b.y+58);}
  else if(m.t==='gen'&&NET.gens[m.i]){const g=NET.gens[m.i];xs.push(g.x-46,g.x+46);ys.push(g.y-40,g.y+40);}
  else if(m.t==='br'&&NET.branches[m.i]){const br=NET.branches[m.i],A=NET.buses[br.f-1],B=NET.buses[br.t-1];
   if(A){xs.push(A.x-40,A.x+40);ys.push(A.y-40,A.y+40);}
   if(B){xs.push(B.x-40,B.x+40);ys.push(B.y-40,B.y+40);}}}
 if(!xs.length)return;
 let x0=Math.min(...xs),y0=Math.min(...ys),w=Math.max(Math.max(...xs)-x0,160),h=Math.max(Math.max(...ys)-y0,160);
 const r=$('sld').getBoundingClientRect(),ar=(r.width||1040)/Math.max(r.height,1);
 if(w/h<ar){const w2=h*ar;x0-=(w2-w)/2;w=w2;}else{const h2=w/ar;y0-=(h2-h)/2;h=h2;}
 animVB([x0-20,y0-20,w+40,h+40]);}
// ---- full-screen editing mode ----
// "Full-screen editing" = maximise the canvas INSIDE the window (hide the rail +
// side panels). It deliberately does NOT call the browser requestFullscreen API:
// that API is mishandled by the Qt desktop window and was closing the app.
function fsToggle(){const on=document.body.classList.contains('fs');
 document.body.classList.toggle('fs',!on);
 stat(on?'ready':'full-screen editing — press the button again, F11, or Esc to leave');
 syncView();if(NET)requestAnimationFrame(()=>draw());}
// ---- mini-map / navigator ----
let MMT=null,MMD=false,MMR=null;
function mmToggle(){MMAP=!MMAP;syncView();mmDraw();
 fetch('/api/uipref',{method:'POST',body:JSON.stringify({mmap:MMAP?1:0})}).catch(function(){});}
function mmDraw(){const mm=$('mmap');if(!mm)return;
 if(!MMAP||!NET||!NET.buses.length||TAB!=='net'){mm.style.display='none';return;}
 mm.style.display='';
 const xs=[],ys=[];NET.buses.forEach(b=>{xs.push(b.x);ys.push(b.y);});
 NET.gens.forEach(g=>{xs.push(g.x);ys.push(g.y);});
 let x0=Math.min(...xs)-60,x1=Math.max(...xs)+60,y0=Math.min(...ys)-60,y1=Math.max(...ys)+60;
 x0=Math.min(x0,VB[0]);y0=Math.min(y0,VB[1]);
 x1=Math.max(x1,VB[0]+VB[2]);y1=Math.max(y1,VB[1]+VB[3]);
 const W=186,H=126,sc=Math.min(W/(x1-x0||1),H/(y1-y0||1));
 const ox=(W-(x1-x0)*sc)/2-x0*sc,oy=(H-(y1-y0)*sc)/2-y0*sc;
 MMT={sc,ox,oy};
 let s='';
 NET.branches.forEach(br=>{const A=NET.buses[br.f-1],B=NET.buses[br.t-1];if(!A||!B)return;
  s+=`<line x1="${(A.x*sc+ox).toFixed(1)}" y1="${(A.y*sc+oy).toFixed(1)}" x2="${(B.x*sc+ox).toFixed(1)}" y2="${(B.y*sc+oy).toFixed(1)}" stroke="#9db0c8" stroke-width="1"/>`;});
 NET.buses.forEach(b=>{s+=`<rect x="${(b.x*sc+ox-1.6).toFixed(1)}" y="${(b.y*sc+oy-1.6).toFixed(1)}" width="3.2" height="3.2" fill="#1f3b73"/>`;});
 NET.gens.forEach(g=>{s+=`<circle cx="${(g.x*sc+ox).toFixed(1)}" cy="${(g.y*sc+oy).toFixed(1)}" r="1.7" fill="${TAGC[g.tag]||'#1f3b73'}"/>`;});
 s+=`<rect class="mmv" x="${(VB[0]*sc+ox).toFixed(1)}" y="${(VB[1]*sc+oy).toFixed(1)}" width="${(VB[2]*sc).toFixed(1)}" height="${(VB[3]*sc).toFixed(1)}"/>`;
 if(MMR&&MMR.moved){                         // rubber-band zoom rectangle
  const rx=Math.min(MMR.x0,MMR.x1),ry=Math.min(MMR.y0,MMR.y1),rw=Math.abs(MMR.x1-MMR.x0),rh=Math.abs(MMR.y1-MMR.y0);
  s+=`<rect x="${(rx*sc+ox).toFixed(1)}" y="${(ry*sc+oy).toFixed(1)}" width="${(rw*sc).toFixed(1)}" height="${(rh*sc).toFixed(1)}" fill="rgba(230,126,34,.16)" stroke="#e67e22" stroke-width="1.2" stroke-dasharray="3 2"/>`;}
 mm.innerHTML=`<svg viewBox="0 0 186 126">${s}</svg>`;}
function mm2w(e){if(!MMT)return null;const r=$('mmap').getBoundingClientRect();
 const mx=(e.clientX-r.left)*(186/(r.width||1)),my=(e.clientY-r.top)*(126/(r.height||1));
 return [(mx-MMT.ox)/MMT.sc,(my-MMT.oy)/MMT.sc];}
function mmJump(e){const w=mm2w(e);if(!w)return;
 VB[0]=w[0]-VB[2]/2;VB[1]=w[1]-VB[3]/2;draw();}
// zoom the main view to a world-space rectangle (aspect-fit), used by the minimap
function zoomWorldRect(x0,y0,x1,y1){
 let X0=Math.min(x0,x1),Y0=Math.min(y0,y1),w=Math.max(Math.abs(x1-x0),60),h=Math.max(Math.abs(y1-y0),60);
 const r=$('sld').getBoundingClientRect(),ar=(r.width||1040)/Math.max(r.height,1);
 if(w/h<ar){const w2=h*ar;X0-=(w2-w)/2;w=w2;}else{const h2=w/ar;Y0-=(h2-h)/2;h=h2;}
 animVB([X0-10,Y0-10,w+20,h+20]);}
// ---- dockable panels: left / right / bottom / floating + pin + auto-hide + resize + collapse ----
const PNS=['model','draw','fleet','props','results','data'];
const PNTITLE={model:'Test system',draw:'Draw',fleet:'Fleet — technology presets',props:'Properties',results:'Results',data:'Data'};
let LAY=null,FLYT=null,FLYID=null,DRAGP=null;
function defLayout(){return{v:12,wL:186,wR:300,rtab:'results',p:{
 model:{d:'left',o:0,pin:1,vis:1,col:0,x:90,y:170,ld:'left'},   // Test system on top
 draw:{d:'left',o:1,pin:1,vis:1,col:0,x:120,y:150,ld:'left'},   // Draw palette second
 fleet:{d:'left',o:2,pin:1,vis:1,col:0,x:110,y:230,ld:'left'},  // Fleet presets below
 props:{d:'right',o:0,pin:1,vis:1,col:0,x:200,y:250,ld:'right'},// Properties on the RIGHT (as the MATLAB edition)
 results:{d:'right',o:1,pin:1,vis:1,col:0,x:240,y:300,ld:'right'},// Results Explorer next to it
 data:{d:'right',o:2,pin:1,vis:1,col:0,x:260,y:340,ld:'right'}}};}  // Data — parameters & input data
function loadLayout(u){const d=defLayout();
 if(u&&u.v===12&&u.p){for(const k of PNS)if(u.p[k])Object.assign(d.p[k],u.p[k]);
  if(u.wL)d.wL=u.wL;if(u.wR)d.wR=u.wR;if(u.rtab)d.rtab=u.rtab;}
 return d;}   // older saved layouts (v<=11) are ignored once, so everyone
              // gets the new Properties | Results | Data tab row
function pnEl(id){return $('pn_'+id);}
function applyLayout(save){
 flyClose();
 const zones={left:$('dockL'),right:$('dockR'),bottom:$('dockB')};
 const strips={left:$('ahL'),right:$('ahR'),bottom:$('ahB')};
 for(const s2 of Object.values(strips))s2.innerHTML='';
 const hold=$('pnhold');
 const ids=[...PNS].sort((a,b)=>(LAY.p[a].o||0)-(LAY.p[b].o||0));
 for(const id of ids){const P=LAY.p[id],el=pnEl(id);
  el.classList.remove('float','flyout','dragging','intab');el.style.cssText='';
  el.classList.toggle('collapsed',!!P.col);
  if(!P.vis){hold.appendChild(el);continue;}
  if(P.d==='float'){document.body.appendChild(el);el.classList.add('float');
   el.style.left=(Math.max(4,Math.min(P.x||100,window.innerWidth-250))/UIS)+'px';
   el.style.top=(Math.max(40,Math.min(P.y||120,window.innerHeight-160))/UIS)+'px';continue;}
  if(!P.pin){hold.appendChild(el);
   const t=document.createElement('button');t.className='ahtab';t.textContent=PNTITLE[id];
   t.title='auto-hidden panel — click to peek; the 📌 pin docks it back';
   t.onclick=ev=>{ev.stopPropagation();flyOpen(id);};
   t.onmouseenter=()=>flyOpen(id);
   strips[P.d].appendChild(t);continue;}
  zones[P.d].appendChild(el);}
 for(const d in strips)strips[d].style.display=strips[d].children.length?'flex':'none';
 zones.left.style.width=(zones.left.children.length?LAY.wL:0)+'px';    // an empty dock
 zones.right.style.width=(zones.right.children.length?LAY.wR:0)+'px';  // takes no space
 const lEmpty=!zones.left.children.length,rEmpty=!zones.right.children.length;
 $('splitL').classList.toggle('hidden',lEmpty);
 $('splitR').classList.toggle('hidden',rEmpty);
 for(const id of PNS){const b=document.querySelector('[data-pinbtn="'+id+'"]');
  if(b)b.classList.toggle('on',!!LAY.p[id].pin&&LAY.p[id].d!=='float');
  const c=$('vP_'+id);if(c)c.style.visibility=LAY.p[id].vis?'visible':'hidden';}
 tabifyRight(zones.right);
 try{datRender();}catch(_){}                      // Data tab fills the moment it is shown
 if(NET)requestAnimationFrame(()=>draw());
 if(save!==false)saveLayout();}
function tabifyRight(col){
 // panels sharing the RIGHT dock present as side-by-side TABS (the MATLAB
 // idiom: Properties | Results next to each other), never stacked panels.
 let bar=$('rtabbar');if(bar)bar.remove();
 const els=[...col.querySelectorAll(':scope>.dpanel')];
 if(els.length<2){els.forEach(el=>el.style.display='');return;}
 let act=LAY.rtab||'props';
 if(!els.some(el=>el.id==='pn_'+act))act=els[0].id.slice(3);
 bar=document.createElement('div');bar.id='rtabbar';bar.className='rtabs';
 for(const el of els){const id=el.id.slice(3);
  el.classList.add('intab');                    // tab names + controls the panel:
  el.classList.remove('collapsed');             // its whole header strip is hidden,
  if(LAY.p[id])LAY.p[id].col=0;                 // so a collapsed tab must never happen
  const b=document.createElement('button');
  b.textContent=PNTITLE[id];
  if(id===act)b.className='on';
  b.onclick=e=>{e.stopPropagation();LAY.rtab=id;applyLayout(true);};
  bar.appendChild(b);
  el.style.display=(id===act)?'':'none';}
 col.insertBefore(bar,col.firstChild);}
function saveLayout(){fetch('/api/uipref',{method:'POST',body:JSON.stringify({layout:LAY})}).catch(function(){});}
function ordEnd(d){return 1+Math.max(-1,...PNS.filter(x=>LAY.p[x].d===d).map(x=>LAY.p[x].o||0));}
function pnDock(id,d){const P=LAY.p[id];P.vis=1;
 if(d==='float')P.d='float';
 else{P.d=d;P.ld=d;P.pin=1;P.o=ordEnd(d);}
 applyLayout();}
function pnPin(id){const P=LAY.p[id];
 if(P.d==='float'){P.d=P.ld||'left';P.pin=1;P.o=ordEnd(P.d);}
 else P.pin=P.pin?0:1;
 applyLayout();
 stat(P.pin?'panel pinned':'panel auto-hidden — its tab waits at the edge');}
function pnClose(id){LAY.p[id].vis=0;applyLayout();
 stat(PNTITLE[id]+' hidden — re-open it from the View menu');}
function pnToggle(id){const P=LAY.p[id];P.vis=P.vis?0:1;
 if(P.vis&&P.d!=='float')P.pin=1;
 applyLayout();}
function pnCollapse(id){const P=LAY.p[id];P.col=P.col?0:1;applyLayout();
 stat(P.col?PNTITLE[id]+' collapsed':PNTITLE[id]+' expanded');}
function pnShow(id){const P=LAY.p[id];P.vis=1;P.col=0;if(P.d!=='float')P.pin=1;
 applyLayout();const el=pnEl(id);if(el&&el.scrollIntoView)el.scrollIntoView({block:'nearest'});}
function restoreLayout(){LAY=defLayout();MMAP=false;applyLayout();syncView();
 stat('default layout restored');}
function flyOpen(id){if(FLYID===id)return;flyClose();
 const P=LAY.p[id],el=pnEl(id);FLYID=id;
 el.classList.remove('collapsed');
 el.classList.add('flyout');$('cwrap').appendChild(el);
 if(P.d==='left'){el.style.left='4px';el.style.top='4px';}
 else if(P.d==='right'){el.style.right='4px';el.style.top='4px';}
 else{el.style.left='4px';el.style.bottom='4px';}
 el.onmouseleave=()=>{FLYT=setTimeout(()=>flyClose(),450);};
 el.onmouseenter=()=>{if(FLYT){clearTimeout(FLYT);FLYT=null;}};}
function flyClose(){if(FLYT){clearTimeout(FLYT);FLYT=null;}
 if(!FLYID)return;const el=pnEl(FLYID);
 el.classList.remove('flyout');el.style.cssText='';
 if(LAY&&LAY.p[FLYID])el.classList.toggle('collapsed',!!LAY.p[FLYID].col);
 el.onmouseleave=el.onmouseenter=null;
 $('pnhold').appendChild(el);FLYID=null;}
function snapv(v){return VOPT.grid?Math.round(v/GRID)*GRID:Math.round(v);}
// ---- rotate / flip ----
function rotSel(){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 if(DSEL&&DSEL.t==='gen'){pushU();const g=NET.gens[DSEL.i],b=NET.buses[g.bus-1];
  const dx=g.x-b.x,dy=g.y-b.y;g.x=snapv(b.x-dy);g.y=snapv(b.y+dx);draw();return;}
 if(DSEL&&DSEL.t==='bus'){pushU();const b=NET.buses[DSEL.i];b.rot=b.rot?0:1;draw();return;}
 netErr('select a bus or a generator first, then rotate (R)');}
function flipSel(){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 if(DSEL&&DSEL.t==='gen'){pushU();const g=NET.gens[DSEL.i],b=NET.buses[g.bus-1];
  if(b.rot)g.x=2*b.x-g.x;else g.y=2*b.y-g.y;draw();return;}
 if(DSEL&&DSEL.t==='bus'){pushU();const b=NET.buses[DSEL.i];b.flip=b.flip?0:1;draw();return;}
 netErr('select a bus or a generator first, then flip (F)');}
// ---- multi-selection helpers ----
function inMsel(h){return MSEL.some(m=>m.t===h.t&&m.i===h.i);}
function isSeriesF(d){return ['TCSC','TSSC','SSSC'].includes(String(d.type).toUpperCase());}
function isCombF(d){return ['UPFC','IPFC'].includes(String(d.type).toUpperCase());}
function delOne(t,i){
 if(t==='br'){const br=NET.branches[i];                       // FACTS that reference this line
  if(br&&NET.facts){const same=(f,tt)=>((f===br.f&&tt===br.t)||(f===br.t&&tt===br.f));
   NET.facts=NET.facts.filter(d=>{
    if(isSeriesF(d))return !same(d.f,d.t);                    // series device sits on this line -> drop
    if(isCombF(d)){
     if(String(d.type).toUpperCase()==='UPFC')return !same(d.f,d.t);   // UPFC series line gone -> drop
     if(same(d.f,d.t))return false;                          // IPFC line 1 gone -> drop
     if(d.f2&&d.t2&&same(d.f2,d.t2)){d.f2=0;d.t2=0;}          // IPFC line 2 gone -> clear line 2
     return true;}
    return true;});}
  NET.branches.splice(i,1);}
 else if(t==='note'){if(NET.notes)NET.notes.splice(i,1);}
 else if(t==='gen')NET.gens.splice(i,1);
 else if(t==='facts'){if(NET.facts)NET.facts.splice(i,1);}
 else if(t==='bus'){const id=i+1;
  NET.branches=NET.branches.filter(br=>br.f!==id&&br.t!==id);
  NET.gens=NET.gens.filter(g=>g.bus!==id);
  if(NET.facts)NET.facts=NET.facts.filter(d=>{
   if(isSeriesF(d))return d.f!==id&&d.t!==id;
   if(isCombF(d)){
    if(String(d.type).toUpperCase()==='UPFC')return d.bus!==id&&d.f!==id&&d.t!==id;
    if(d.f===id||d.t===id)return false;                      // IPFC line 1 endpoint gone -> drop
    if(d.f2===id||d.t2===id){d.f2=0;d.t2=0;}                 // IPFC line 2 endpoint gone -> clear line 2
    return true;}
   return d.bus!==id;});                                     // shunt
  NET.branches.forEach(br=>{if(br.f>id)br.f--;if(br.t>id)br.t--;});
  NET.gens.forEach(g=>{if(g.bus>id)g.bus--;});
  if(NET.facts)NET.facts.forEach(d=>{
   if(isSeriesF(d)){if(d.f>id)d.f--;if(d.t>id)d.t--;}
   else if(isCombF(d)){if(d.bus>id)d.bus--;if(d.f>id)d.f--;if(d.t>id)d.t--;if(d.f2>id)d.f2--;if(d.t2>id)d.t2--;}
   else if(d.bus>id)d.bus--;});
  NET.buses.splice(i,1);}}
function delSel(){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 if(MSEL.length){pushU();
  MSEL.filter(m=>m.t==='gen').map(m=>m.i).sort((a,b)=>b-a).forEach(i=>NET.gens.splice(i,1));
  MSEL.filter(m=>m.t==='bus').map(m=>m.i).sort((a,b)=>b-a).forEach(i=>delOne('bus',i));
  MSEL=[];DSEL=null;edited();prop();draw();syncSide();return;}
 if(DSEL){pushU();delOne(DSEL.t,DSEL.i);DSEL=null;edited();prop();draw();syncSide();}}
function nudge(key){if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 const d={arrowleft:[-GRID,0],arrowright:[GRID,0],arrowup:[0,-GRID],arrowdown:[0,GRID]}[key];if(!d)return;
 const sel=MSEL.length?MSEL:(DSEL&&(DSEL.t==='bus'||DSEL.t==='gen')?[DSEL]:[]);
 if(!sel.length)return;
 const now=Date.now();if(now-NUDGT>900)pushU();NUDGT=now;   // real change: pushU clears redo
 const bset=new Set(sel.filter(m=>m.t==='bus').map(m=>m.i));
 bset.forEach(i=>{NET.buses[i].x+=d[0];NET.buses[i].y+=d[1];});
 NET.gens.forEach((g,i)=>{if(sel.some(m=>m.t==='gen'&&m.i===i)||bset.has(g.bus-1)){g.x+=d[0];g.y+=d[1];}});
 draw();}
// ---- auto-arrange: force layout + overlap removal, deterministic ----
function autoArrange(){if(!NET||NET.buses.length<2)return;
 if(LOCKED){stat('layout is locked');return;}
 pushU();
 NET.branches.forEach(b2=>{delete b2.co;});
 const n=NET.buses.length;
 const P=NET.buses.map((b,i)=>({x:b.x+(i%7-3)*0.013,y:b.y+(i%5-2)*0.017}));
 const adj=NET.branches.map(br=>[br.f-1,br.t-1]).filter(([a,b])=>a>=0&&b>=0&&a<n&&b<n&&a!==b);
 const L=135,K=9000;
 for(let it=0;it<260;it++){const fx=new Array(n).fill(0),fy=new Array(n).fill(0),cool=1-it/260;
  for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
   let dx=P[i].x-P[j].x,dy=P[i].y-P[j].y,d2=dx*dx+dy*dy;
   if(d2<1){dx=((i*7+j)%13-6)*0.1+0.05;dy=((i*3+j)%11-5)*0.1+0.05;d2=dx*dx+dy*dy;}
   if(d2>4*L*L*4)continue;
   const d=Math.sqrt(d2),f=K/d2;
   fx[i]+=f*dx/d;fy[i]+=f*dy/d;fx[j]-=f*dx/d;fy[j]-=f*dy/d;}
  for(const [a,b] of adj){const dx=P[b].x-P[a].x,dy=P[b].y-P[a].y,d=Math.hypot(dx,dy)||1,f=0.07*(d-L);
   fx[a]+=f*dx/d;fy[a]+=f*dy/d;fx[b]-=f*dx/d;fy[b]-=f*dy/d;}
  for(let i=0;i<n;i++){const m=Math.hypot(fx[i],fy[i])||1,mv=Math.min(m,13*cool+2);
   P[i].x+=fx[i]/m*mv;P[i].y+=fy[i]/m*mv;}}
 for(let r=0;r<50;r++){let done=true;
  for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
   const dx=P[j].x-P[i].x,dy=P[j].y-P[i].y,d=Math.hypot(dx,dy);
   if(d<82){done=false;const push=(82-d)/2+1,ux=d?dx/d:1,uy=d?dy/d:0;
    P[i].x-=ux*push;P[i].y-=uy*push;P[j].x+=ux*push;P[j].y+=uy*push;}}
  if(done)break;}
 NET.buses.forEach((b,i)=>{b.x=snapv(P[i].x);b.y=snapv(P[i].y);});
 placeGens();fitView();prop();}
// ---- tidy: graph-theoretic layout (Sugiyama-style) -------------------
// levels by electrical distance from the slack; crossing minimisation by
// median sweeps + adjacent transpositions; vertical alignment so branches
// run straight along the grid; automatic bar orientation from the incident
// branches; obstacle-aware right-angle routing (orthoRoute) finishes it.
// ---- MATLAB-parity layout algorithms.  (Force-directed = Arrange, levelled /
//      min-crossings = Tidy, orthogonal routing = the Ortho toggle; these add
//      the remaining named layouts so both platforms match.) -----------------
function layAdj(){const n=NET.buses.length,adj=Array.from({length:n},()=>[]);
 NET.branches.forEach(br=>{const a=br.f-1,b=br.t-1;
  if(a>=0&&b>=0&&a<n&&b<n&&a!==b){adj[a].push(b);adj[b].push(a);}});return adj;}
function layDo(fn,msg,orient){
 if(!NET||NET.buses.length<2)return; if(LOCKED){stat('layout is locked');return;}
 pushU(); const n=NET.buses.length, adj=layAdj(); const P=fn(n,adj);
 for(let i=0;i<n;i++){NET.buses[i].x=snapv(P[i].x);NET.buses[i].y=snapv(P[i].y);}
 NET.branches.forEach(b=>{delete b.co;});
 if(orient!==false)orientBars();
 placeGens();fitView();prop();draw();stat(msg);}
function layBFS(adj,n){                              // BFS levels from the slack bus
 let root=NET.buses.findIndex(b=>b.type==='slack');if(root<0)root=0;
 const lev=new Array(n).fill(-1);lev[root]=0;const q=[root];
 while(q.length){const u=q.shift();for(const v of adj[u])if(lev[v]<0){lev[v]=lev[u]+1;q.push(v);}}
 let lm=0;for(let i=0;i<n;i++)if(lev[i]>lm)lm=lev[i];
 for(let i=0;i<n;i++)if(lev[i]<0)lev[i]=++lm;
 return lev;}
function layCircular(){layDo((n)=>{
 const R=Math.max(180,55*n/Math.PI),cx=520,cy=380;
 return Array.from({length:n},(_,i)=>({x:cx+R*Math.cos(2*Math.PI*i/n-Math.PI/2),
   y:cy+R*Math.sin(2*Math.PI*i/n-Math.PI/2)}));},'circular layout');}
function layGrid(){layDo((n)=>{
 const c=Math.ceil(Math.sqrt(n)),s=160;
 return Array.from({length:n},(_,i)=>({x:160+(i%c)*s,y:120+Math.floor(i/c)*s}));},'grid layout');}
function layRadial(){layDo((n,adj)=>{
 const lev=layBFS(adj,n),byL={};for(let i=0;i<n;i++)(byL[lev[i]]=byL[lev[i]]||[]).push(i);
 const cx=520,cy=380,dr=140,P=new Array(n);
 Object.keys(byL).forEach(L=>{const arr=byL[L],R=(+L)*dr;
  arr.forEach((i,k)=>{P[i]=(+L===0)?{x:cx,y:cy}:
   {x:cx+R*Math.cos(2*Math.PI*k/arr.length+L*0.5),y:cy+R*Math.sin(2*Math.PI*k/arr.length+L*0.5)};});});
 return P;},'radial layout');}
function layTree(){layDo((n,adj)=>{
 const lev=layBFS(adj,n),byL={};for(let i=0;i<n;i++)(byL[lev[i]]=byL[lev[i]]||[]).push(i);
 const P=new Array(n);
 Object.keys(byL).sort((a,b)=>a-b).forEach(L=>{const arr=byL[L];
  arr.forEach((i,k)=>{P[i]={x:520+(k-(arr.length-1)/2)*150,y:110+(+L)*140};});});
 return P;},'tree layout');}
function layKK(){layDo((n,adj)=>{                     // Kamada-Kawai: spring by graph distance
 const INF=1e9,D=[];
 for(let s=0;s<n;s++){const d=new Array(n).fill(INF);d[s]=0;const q=[s];
  while(q.length){const u=q.shift();for(const v of adj[u])if(d[v]>d[u]+1){d[v]=d[u]+1;q.push(v);}}D.push(d);}
 const L0=110,P=Array.from({length:n},(_,i)=>({x:520+120*Math.cos(2*Math.PI*i/n),y:380+120*Math.sin(2*Math.PI*i/n)}));
 for(let it=0;it<300;it++){const F=Array.from({length:n},()=>({x:0,y:0}));
  for(let i=0;i<n;i++)for(let j=0;j<n;j++){if(i===j)continue;
   const dij=D[i][j]<INF?D[i][j]:n,l=L0*dij;
   let dx=P[i].x-P[j].x,dy=P[i].y-P[j].y,d=Math.hypot(dx,dy)||1;
   const f=(d-l)/d/Math.max(dij,1); F[i].x-=f*dx;F[i].y-=f*dy;}
  for(let i=0;i<n;i++){P[i].x+=F[i].x*0.1;P[i].y+=F[i].y*0.1;}}
 return P;},'Kamada-Kawai layout');}
function layScale(f,msg){if(!NET||NET.buses.length<2)return;if(LOCKED){stat('layout is locked');return;}
 pushU();const n=NET.buses.length;
 const cx=NET.buses.reduce((s,b)=>s+b.x,0)/n,cy=NET.buses.reduce((s,b)=>s+b.y,0)/n;
 NET.buses.forEach(b=>{b.x=snapv(cx+(b.x-cx)*f);b.y=snapv(cy+(b.y-cy)*f);});
 placeGens();fitView();prop();draw();stat(msg);}
function layCompact(){layScale(0.82,'compacted layout');}       // same factors as the MATLAB app
function layExpand(){layScale(1.20,'expanded layout');}
// ---- remaining MATLAB-parity commands: smart dispatch, vertical hierarchy,
//      in-place min-crossings / equal spacing / straighten, restore. --------
function layAuto(){                                   // Auto (smart): pick by graph shape (mirrors lay_auto)
 if(!NET||NET.buses.length<1)return;
 const n=NET.buses.length,e=NET.branches.length,adj=layAdj();
 let root=NET.buses.findIndex(b=>b.type==='slack');if(root<0)root=0;   // raw reachability (no patching)
 const seen=new Array(n).fill(false);seen[root]=true;const q=[root];
 while(q.length){const u=q.shift();for(const v of adj[u])if(!seen[v]){seen[v]=true;q.push(v);}}
 const connected=seen.every(s=>s);
 if(n<=2){layGrid();stat('auto layout → grid');return;}
 if(connected&&e===n-1){layTree();stat('auto layout → tree (radial feeder)');return;}
 if(n<=10){layCircular();stat('auto layout → circular');return;}
 if(2*e/Math.max(n,1)>=3.5){tidyLayout();stat('auto layout → levelled (dense mesh)');return;}
 autoArrange();stat('auto layout → force-directed');}
function layHierV(){                                  // Hierarchical: tidy engine, levels stacked VERTICALLY
 if(!NET||NET.buses.length<2)return;if(LOCKED){stat('layout is locked');return;}
 tidyLayout();
 const xs=NET.buses.map(b=>b.x),ys=NET.buses.map(b=>b.y);
 const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
 NET.buses.forEach(b=>{const dx=b.x-cx,dy=b.y-cy;b.x=snapv(cx+dy);b.y=snapv(cy+dx);});   // transpose about the centre
 orientBars();placeGens();fitView();prop();draw();stat('hierarchical layout (Sugiyama, vertical levels)');}
function layGroups(vals,tolK){                        // cluster a coordinate list (shared by the in-place commands)
 const n=vals.length,idx=vals.map((v,i)=>i).sort((a,b)=>vals[a]-vals[b]);
 const span=Math.max(Math.max(...vals)-Math.min(...vals),1),tol=tolK*span;
 const grp=new Array(n);let g=0;grp[idx[0]]=0;
 for(let p=1;p<n;p++){if(vals[idx[p]]-vals[idx[p-1]]>tol)g++;grp[idx[p]]=g;}
 return {grp,ng:g+1};}
function cmdBarycenter(){                             // minimize line crossings row-by-row (mirrors cmd_barycenter)
 if(!NET||NET.buses.length<3)return;if(LOCKED){stat('layout is locked');return;}
 pushU();const n=NET.buses.length,adj=layAdj();
 const ys=NET.buses.map(b=>b.y),{grp,ng}=layGroups(ys,0.06);
 for(let r=0;r<ng;r++){
  const idx=[];for(let i=0;i<n;i++)if(grp[i]===r)idx.push(i);
  if(idx.length<2)continue;
  const bc=idx.map(i=>adj[i].length?adj[i].reduce((s,v)=>s+NET.buses[v].x,0)/adj[i].length:NET.buses[i].x);
  const xs=idx.map(i=>NET.buses[i].x).sort((a,b)=>a-b);
  const ord=idx.map((_,k)=>k).sort((a,b)=>bc[a]-bc[b]);
  ord.forEach((k,p)=>{NET.buses[idx[k]].x=xs[p];});}
 NET.branches.forEach(b=>{delete b.co;});
 placeGens();prop();draw();stat('minimized line crossings (barycenter ordering per row)');}
function cmdEqual(){                                  // equalize bus spacing on both axes (mirrors cmd_equal)
 if(!NET||NET.buses.length<3)return;if(LOCKED){stat('layout is locked');return;}
 pushU();
 const eq=get=>{const vals=NET.buses.map(get),{grp,ng}=layGroups(vals,0.04);
  const lo=Math.min(...vals),hi=Math.max(...vals);if(hi-lo<1e-9)return null;
  return i=>lo+(hi-lo)*grp[i]/Math.max(ng-1,1);};
 const fx=eq(b=>b.x),fy=eq(b=>b.y);
 NET.buses.forEach((b,i)=>{if(fx)b.x=snapv(fx(i));if(fy)b.y=snapv(fy(i));});
 NET.branches.forEach(b=>{delete b.co;});
 placeGens();fitView();prop();draw();stat('equalized bus spacing');}
function cmdStraighten(){                             // snap near-collinear buses onto shared rows/columns (mirrors cmd_straighten)
 if(!NET||NET.buses.length<3)return;if(LOCKED){stat('layout is locked');return;}
 pushU();
 const snapc=get=>{const vals=NET.buses.map(get),{grp,ng}=layGroups(vals,0.05),m=new Array(ng).fill(0),c=new Array(ng).fill(0);
  vals.forEach((v,i)=>{m[grp[i]]+=v;c[grp[i]]++;});
  return i=>m[grp[i]]/c[grp[i]];};
 const fx=snapc(b=>b.x),fy=snapc(b=>b.y);
 NET.buses.forEach((b,i)=>{b.x=snapv(fx(i));b.y=snapv(fy(i));});
 NET.branches.forEach(b=>{delete b.co;});
 placeGens();prop();draw();stat('straightened transmission runs (aligned rows and columns)');}
function layRestore(){                                // back to the coordinates captured at import
 if(!NET)return;if(LOCKED){stat('layout is locked');return;}
 if(!HOMEXY||HOMEXY.length!==NET.buses.length){autoArrange();stat('no saved layout for this network — applied a clean force-directed arrange');return;}
 pushU();
 NET.buses.forEach((b,i)=>{b.x=HOMEXY[i][0];b.y=HOMEXY[i][1];});
 NET.branches.forEach(b=>{delete b.co;});
 orientBars();placeGens();fitView();prop();draw();stat('restored the imported layout');}
function tidyLayout(){if(!NET||NET.buses.length<2)return;
 if(LOCKED){stat('layout is locked');return;}
 pushU();
 NET.branches.forEach(b2=>{delete b2.co;});
 const n=NET.buses.length;
 const adj=Array.from({length:n},()=>[]);
 NET.branches.forEach(br=>{const a=br.f-1,b=br.t-1;
  if(a>=0&&b>=0&&a<n&&b<n&&a!==b){adj[a].push(b);adj[b].push(a);}});
 let root=NET.buses.findIndex(b=>b.type==='slack');if(root<0)root=0;
 const lev=new Array(n).fill(-1);lev[root]=0;
 const q=[root];
 while(q.length){const u=q.shift();for(const v of adj[u])if(lev[v]<0){lev[v]=lev[u]+1;q.push(v);}}
 let lmax=Math.max(...lev);
 for(let i=0;i<n;i++)if(lev[i]<0)lev[i]=++lmax;
 const nl=Math.max(...lev)+1;
 const cols=Array.from({length:nl},()=>[]);
 for(let i=0;i<n;i++)cols[lev[i]].push(i);
 const pos=new Array(n);
 cols.forEach(c=>c.forEach((b,r)=>pos[b]=r));
 const med=a=>{if(!a.length)return null;const t=[...a].sort((x,y)=>x-y);
  const m=t.length>>1;return t.length%2?t[m]:(t[m-1]+t[m])/2;};
 // 1) median sweeps, alternating direction (crossing minimisation)
 for(let it=0;it<10;it++){const fwd=it%2===0;
  for(let li=fwd?1:nl-2; fwd?li<nl:li>=0; li+=fwd?1:-1){
   const ref=fwd?li-1:li+1;if(ref<0||ref>=nl)continue;
   cols[li].sort((a,b)=>{
    const ma=med(adj[a].filter(v=>lev[v]===ref).map(v=>pos[v]));
    const mb=med(adj[b].filter(v=>lev[v]===ref).map(v=>pos[v]));
    return (ma==null?pos[a]:ma)-(mb==null?pos[b]:mb)||a-b;});
   cols[li].forEach((b,r)=>pos[b]=r);}}
 // 2) adjacent transpositions while they reduce crossings
 const crossAt=li=>{if(li<0||li+1>=nl)return 0;
  const E=[];
  cols[li].forEach(a=>adj[a].forEach(v=>{if(lev[v]===li+1)E.push([pos[a],pos[v]]);}));
  let c=0;
  for(let i=0;i<E.length;i++)for(let j=i+1;j<E.length;j++)
   if((E[i][0]-E[j][0])*(E[i][1]-E[j][1])<0)c++;
  return c;};
 for(let it=0;it<3;it++){let improved=false;
  for(let li=0;li<nl;li++)for(let r=0;r+1<cols[li].length;r++){
   const before=crossAt(li-1)+crossAt(li);
   const a=cols[li][r],b=cols[li][r+1];
   cols[li][r]=b;cols[li][r+1]=a;pos[a]=r+1;pos[b]=r;
   if(crossAt(li-1)+crossAt(li)<before)improved=true;
   else{cols[li][r]=a;cols[li][r+1]=b;pos[a]=r;pos[b]=r+1;}}
  if(!improved)break;}
 // 3) coordinates + vertical alignment so branches run straight
 const DX=190,DY=110;
 const Y=new Array(n);
 cols.forEach(c=>{const h=(c.length-1)*DY;c.forEach((b,r)=>{Y[b]=r*DY-h/2;});});
 for(let it=0;it<6;it++)
  cols.forEach(c=>{
   c.forEach(b=>{const nb=adj[b].filter(v=>lev[v]!==lev[b]);
    if(nb.length){const t=med(nb.map(v=>Y[v]));if(t!=null)Y[b]=t;}});
   const ord=[...c].sort((a,b)=>Y[a]-Y[b]||pos[a]-pos[b]);
   for(let r=1;r<ord.length;r++)
    if(Y[ord[r]]<Y[ord[r-1]]+DY)Y[ord[r]]=Y[ord[r-1]]+DY;});
 const miny=Math.min(...Y);
 for(let i=0;i<n;i++){NET.buses[i].x=60+lev[i]*DX;
  NET.buses[i].y=Math.round((Y[i]-miny)/20)*20+60;}
 // 4) bar orientation from the branches it must receive (perpendicular taps:
 //    mostly-horizontal branches -> vertical bar, and vice versa)
 NET.buses.forEach((b,i)=>{let H=0,Vv=0;
  adj[i].forEach(v=>{const o=NET.buses[v];
   const dx=Math.abs(o.x-b.x),dy=Math.abs(o.y-b.y),dd=Math.hypot(dx,dy)||1;
   H+=dx/dd;Vv+=dy/dd;});
  b.rot=(adj[i].length&&H>Vv*1.2)?1:0;b.flip=0;});
 placeGens();
 if(!VOPT.ortho)tgl('ortho');
 fitView();prop();}
function placeGens(){
 NET.gens.forEach(g=>{const b=NET.buses[g.bus-1];if(!b)return;
  let vx=0,vy=0;
  NET.branches.forEach(br=>{let o=null;
   if(br.f===g.bus)o=NET.buses[br.t-1];else if(br.t===g.bus)o=NET.buses[br.f-1];
   if(o){const d=Math.hypot(o.x-b.x,o.y-b.y)||1;vx+=(o.x-b.x)/d;vy+=(o.y-b.y)/d;}});
  if((b.Pd||0)!==0||(b.Qd||0)!==0){if(b.rot)vx+=0.8;else vy+=0.8;}
  // machines tap the bar PERPENDICULAR (SLD convention): a horizontal bar
  // takes its generator above/below, a vertical bar left/right
  if(b.rot){const ux=vx<-0.15?1:-1;g.x=snapv(b.x+ux*64);g.y=snapv(b.y);}
  else{const uy=vy<-0.15?1:-1;g.x=snapv(b.x);g.y=snapv(b.y+uy*64);}});
 const seen={};
 NET.gens.forEach(g=>{const b=NET.buses[g.bus-1],k=g.x+'_'+g.y;
  if(seen[k]!==undefined){seen[k]++;
   if(b&&b.rot)g.y+=seen[k]*42;else g.x+=seen[k]*42;}
  else seen[k]=0;});}
// ---- export / save / report / print (through the local Python engine, so it
//      works in the Qt desktop window where browser downloads/print are disabled) ----
function svgDoc(){const svg=$('sld');
 const inner=svg.innerHTML.replace(/<clipPath id="fclip[\d_]+">[\s\S]*?<\/clipPath>/g,'')
   .replace(/<g class="fglide"[\s\S]*?<\/g><\/g>/g,'').replace(/<path class="fglide"[\s\S]*?<\/path>/g,'');
 return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VB.join(' ')}" width="${Math.round(VB[2])}" height="${Math.round(VB[3])}"><rect x="${VB[0]}" y="${VB[1]}" width="${VB[2]}" height="${VB[3]}" fill="#fbfcfe"/>${inner.replace(/#sld /g,'')}</svg>`;}
function fname(ext){return ((NET&&NET.name)||'diagram').replace(/\W+/g,'_')+ext;}
async function saveOut(name,opts){stat('saving '+name+' …');
 const r=await api('/api/save',Object.assign({name},opts||{}));
 if(r&&r.path){stat('saved to '+r.path);}
 else{const m=(r&&r.error)||'unknown error';netErr('save failed: '+m);}
 return r;}
function exportSVG(){if(!NET)return;saveOut(fname('.svg'),{text:svgDoc()});}
function saveNetFile(){if(!NET)return;saveOut(fname('.json'),{text:JSON.stringify(NET,null,1)});}
function exportPNG(){if(!NET)return;const img=new Image(),sc=2;
 img.onload=()=>{try{const c=document.createElement('canvas');
   c.width=Math.max(1,Math.round(VB[2]*sc));c.height=Math.max(1,Math.round(VB[3]*sc));
   const g=c.getContext('2d');g.fillStyle='#ffffff';g.fillRect(0,0,c.width,c.height);
   g.drawImage(img,0,0,c.width,c.height);
   saveOut(fname('.png'),{b64:c.toDataURL('image/png')});}catch(e){netErr('PNG export failed: '+e.message);}};
 img.onerror=()=>netErr('PNG render failed');
 img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svgDoc());}
function reportHTML(forPrint){const title=(NET&&NET.name)||'diagram';
 let rows='';
 if(DPF&&DPF.V)rows=NET.buses.map((b,i)=>`<tr><td>${i+1}${b.name?' · '+b.name:''}</td><td>${DPF.V[i].toFixed(3)}</td><td>${DPF.th[i].toFixed(1)}°</td><td>${b.Pd||0}</td><td>${b.Qd||0}</td></tr>`).join('');
 const sum=DPF?`<p><b>Power flow:</b> generation ${DPF.Ptot} MW · load ${DPF.Pload} MW · losses ${(DPF.Ptot-DPF.Pload).toFixed(1)} MW</p>`:'<p><i>Run a power flow to include bus voltages in the report.</i></p>';
 const auto=forPrint?'<scr'+'ipt>window.onload=function(){setTimeout(function(){window.print();},350);};</scr'+'ipt>':'';
 return `<!doctype html><html><head><meta charset="utf-8"><title>PSDAT — ${title}</title>`+
  `<style>body{font:14px "Segoe UI",system-ui,sans-serif;color:#20242c;margin:26px}`+
  `h1{color:#1f3b73;font-family:Georgia,serif;margin:0 0 4px}h2{color:#1f3b73;font-size:15px;margin:16px 0 4px}`+
  `table{border-collapse:collapse;margin-top:6px}th,td{border:1px solid #cfd6e2;padding:4px 9px;font-size:12.5px;text-align:right}`+
  `th{background:#eef2fa}td:first-child,th:first-child{text-align:left}`+
  `.frame{border:1px solid #c9cfd9;border-radius:5px;margin:12px 0;max-width:960px}svg{width:100%;height:auto}`+
  `</style>${auto}</head><body>`+
  `<h1>PSDAT — ${title}</h1>`+
  `<p>${NET.buses.length} buses · ${NET.branches.length} lines · ${NET.gens.length} machines</p>`+
  `${sum}<div class="frame">${svgDoc()}</div>`+
  (rows?`<h2>Bus results</h2><table><tr><th>Bus</th><th>V (pu)</th><th>Angle</th><th>Pd (MW)</th><th>Qd (MVAr)</th></tr>${rows}</table>`:'')+
  `</body></html>`;}
function reportPF(){if(TAB!=='net')goTab('net');
 if(!NET){netErr('load or draw a network first');return;}
 if(!DPF){stat('running power flow for the report …');
  runPF().then(()=>saveOut(fname('_report.html'),{text:reportHTML(false),open:true}));return;}
 saveOut(fname('_report.html'),{text:reportHTML(false),open:true});}
function printDiagram(){if(!NET){netErr('load or draw a network first');return;}goTab('net');
 saveOut(fname('_print.html'),{text:reportHTML(true),open:true});}
const PROJ_RESULT_IDS=['pfsum','pvChart','pvOut','pvErr','n1Tab','n1Out','n1Err',
 'stscTab','stscOut','stscErr','cctChart','cctOut','cctErr',
 'edTab','edLmp','edOut','edBind','edErr','oppTab','oppOut','oppErr'];
function projData(){const res={};
 PROJ_RESULT_IDS.forEach(id=>{const e=$(id);if(e&&e.innerHTML&&e.innerHTML.trim())res[id]=e.innerHTML;});
 const sc=(window.SCADA&&window.SCADA.soe&&window.SCADA.soe.length)
  ?{soe:window.SCADA.soe.slice(0,300),alarms:window.SCADA.alarms.slice(0,100)}:undefined;
 return {app:'PSDAT',kind:'project',version:'2.4.1',saved:new Date().toISOString(),
  net:NET,pov:POV,dpf:(window.SCADA&&window.SCADA.on&&window.SCADA.trueDPF)?window.SCADA.trueDPF:DPF,
  hvar:HVAR,vopt:VOPT,cmode:CMODE,scada:sc,
  scenario:(window.SCADA&&window.SCADA.scenario)||undefined,results:res};}
function saveProject(){if(!NET){netErr('load or draw a network first');return;}
 saveOut(fname('.psdat'),{text:JSON.stringify(projData(),null,1)});}
function loadProjectText(txt,label){
 const p=JSON.parse(txt);
 const isProj=p&&p.net&&p.net.buses;
 const nt=isProj?p.net:p;
 if(!nt||!nt.buses||!nt.branches||!nt.gens)throw new Error('not a PSDAT project or network file');
 if(!nt.facts)nt.facts=[];
 NET=nt;UST=[];URD=[];DSEL=null;MSEL=[];DPEND=null;
 DPF=isProj&&p.dpf?p.dpf:null;
 if(isProj){POV=p.pov||{};if(p.hvar)HVAR=p.hvar;
  if(p.vopt&&typeof VOPT==='object')VOPT=Object.assign(VOPT,p.vopt);
  if(p.cmode)CMODE=(p.cmode==='dynamic')?'dynamic':'fixed';
  if(p.scada&&window.SCADA){try{window.SCADA.soe=p.scada.soe||[];
   window.SCADA.alarms=(p.scada.alarms||[]).map(a=>Object.assign({},a));}catch(_){}}
  if(p.scenario&&window.SCADA)window.SCADA.scenario=p.scenario;}
 netErr('');const ps=$('pfsum');if(ps)ps.textContent='';
 if(isProj&&p.results)Object.keys(p.results).forEach(id=>{
  if(PROJ_RESULT_IDS.indexOf(id)>=0){const e=$(id);if(e)e.innerHTML=p.results[id];}});
 try{syncView();}catch(_){}
 fitView();prop();
 try{buildSide();fillDesign();}catch(_){}
 try{datRender();}catch(_){}
 stat((isProj?'project':'network')+' loaded — '+((NET&&NET.name)||label||'untitled')
  +(DPF?' (with saved results)':''));}
function openNetFile(inp){const f=inp.files&&inp.files[0];if(!f)return;
 const rd=new FileReader();
 rd.onload=()=>{try{loadProjectText(String(rd.result),f.name);}
  catch(err){netErr('could not open: '+err.message);}
  inp.value='';};
 rd.readAsText(f);}
// ---- heat-map variable: any network quantity as the smooth colour field -----
const HVARS=[['vmag','Voltage magnitude','pu'],['vang','Voltage angle','°'],
 ['i','Current magnitude','pu'],['p','Active power flow','MW'],['q','Reactive power flow','MVAr'],
 ['ploss','Active power losses','MW'],['qloss','Reactive power losses','MVAr'],
 ['loading','Loading','%'],['util','Line utilisation','%']];
function hvarLabel(){const h=HVARS.find(x=>x[0]===HVAR)||HVARS[0];return h[1]+' ('+h[2]+')';}
function setHvar(v){HVAR=v;if(!VOPT.cont&&heatOnPref()){VOPT.cont=true;syncView();}
 try{stat('heat map: '+hvarLabel());}catch(_){}try{qdraw();}catch(_){try{draw();}catch(e){}}}
function hmapField(){                    // per-bus values + range for the current HVAR
 const n=NET.buses.length,v=new Array(n).fill(0);
 const h=HVARS.find(x=>x[0]===HVAR)||HVARS[0],unit=h[2],label=h[1];
 if(HVAR==='vmag'){for(let i=0;i<n;i++)v[i]=DPF?DPF.V[i]:1;return{v,lo:0.94,hi:1.06,unit,label};}
 if(HVAR==='vang'){for(let i=0;i<n;i++)v[i]=DPF?DPF.th[i]:0;
  return{v,lo:Math.min(...v),hi:Math.max(...v,Math.min(...v)+1e-6),unit,label};}
 const sum=(HVAR==='ploss'||HVAR==='qloss'),acc=new Array(n).fill(0);   // line var -> aggregate to buses
 // loading/utilisation need line ratings; if the network has none, fall back to
 // loading relative to the busiest line so the field is still meaningful.
 const anyRate=NET.branches.some(br=>br.rate>0);let maxS=1e-6;
 if(!anyRate&&DPF&&DPF.flows)DPF.flows.forEach((fl,i)=>{if(fl&&!(NET.branches[i]||{}).off)maxS=Math.max(maxS,Math.hypot(fl.Pf,fl.Qf));});
 if(DPF&&DPF.flows)NET.branches.forEach((br,i)=>{const fl=DPF.flows[i];if(!fl||br.off)return;
  const S=Math.hypot(fl.Pf,fl.Qf);let val=0;
  if(HVAR==='p')val=Math.abs(fl.Pf);else if(HVAR==='q')val=Math.abs(fl.Qf);
  else if(HVAR==='i'){val=S/100/Math.max(0.2,(DPF.V[br.f-1]||1));}
  else if(HVAR==='ploss')val=Math.abs(fl.loss||0);else if(HVAR==='qloss')val=Math.abs(fl.Qloss||0);
  else if(HVAR==='loading'||HVAR==='util')val=(br.rate>0)?S/br.rate*100:(anyRate?0:S/maxS*100);
  [br.f-1,br.t-1].forEach(bi=>{if(bi<0||bi>=n)return;acc[bi]=sum?acc[bi]+val:Math.max(acc[bi],val);});});
 for(let i=0;i<n;i++)v[i]=acc[i];
 return{v,lo:0,hi:Math.max(...v,1e-6),unit,label};}
function vband(v){                     // low = warm, high = cold (as contour)
 if(v<0.95)return '#b42318';           // undervoltage — critical (red)
 if(v<0.97)return '#b7791f';           // low (amber)
 if(v>1.07)return '#5b21b6';           // severe overvoltage (violet)
 if(v>1.05)return '#1d4ed8';           // overvoltage (blue)
 return '#1e7a44';}                    // normal (green)
// fcmap: the SAME heat colour scale as the MATLAB edition (low = blue ->
// cyan -> green -> yellow -> high = red), so both platforms look identical.
/* Heat-map colour scale + user preferences (ported from the mobile edition). */
const HEATCP=[[13,61,158],[0,158,235],[26,184,61],[250,204,26],[219,36,26]];
function uiDark(){return document.documentElement.classList.contains('dark');}
function heatPal(){return HEATCP;}
function heatOnPref(){try{return localStorage.getItem('psdat_heat')!=='off';}catch(_){return true;}}
function setHeatOn(v){try{localStorage.setItem('psdat_heat',v?'on':'off');}catch(_){}
 try{if(v&&!DPF&&typeof runActive==='function')runActive();}catch(_){}
 if(!!v!==!!VOPT.cont)tgl('cont');else qdraw();
 try{stat(v?'heat map on':'heat map off');}catch(_){}}
let CMODE='fixed';try{if(localStorage.getItem('psdat_cmode')==='dynamic')CMODE='dynamic';}catch(_){}
let DYNBUS=null;                     // per-bus colours for the current frame (dynamic mode)
function setCMode(m){CMODE=(m==='dynamic')?'dynamic':'fixed';
 try{localStorage.setItem('psdat_cmode',CMODE);}catch(_){}
 try{const c=document.getElementById('vCmode');if(c)c.style.visibility=(CMODE==='dynamic')?'visible':'hidden';}catch(_){}
 try{if(CMODE==='dynamic'&&!DPF&&typeof runActive==='function')runActive();}catch(_){}
 try{stat(CMODE==='dynamic'?('component colours follow '+hvarLabel()):'classic component colours');}catch(_){}
 qdraw();}
function heatT(val,HF,isV){let t=isV?(1.06-val)/0.12:(val-HF.lo)/((HF.hi-HF.lo)||1);
 return Math.max(0,Math.min(1,t));}
let HALOF=null;                       // heat-field sampler for adaptive label halos
function haloColor(x,y){
 if(!HALOF)return null;
 const H=HALOF;
 if(x<H.x0||x>H.x1||y<H.y0||y>H.y1)return null;
 let sw=0,sv=0;
 for(let q=0;q<H.bx.length;q++){
  const dx=H.bx[q]-x,dy=H.by[q]-y,dd=dx*dx+dy*dy+900,w=1/(dd*Math.sqrt(dd));
  sw+=w;sv+=w*H.v[q];}
 let t=H.isV?(1.06-sv/sw)/0.12:((sv/sw)-H.lo)/H.span;
 t=Math.max(0,Math.min(1,t));
 t=Math.max(0,Math.min(1,0.5+(t-0.5)*HCONTR));
 if(HLEVELS>=2)t=Math.round(t*(HLEVELS-1))/(HLEVELS-1);
 const cp=heatPal(),xx=t*4,i=Math.min(4,Math.max(1,Math.floor(xx)+1)),f=xx-(i-1),a=cp[i-1],b=cp[i];
 let r=a[0]*(1-f)+b[0]*f,g=a[1]*(1-f)+b[1]*f,bl=a[2]*(1-f)+b[2]*f;
 if(HINTENS!==1){const L=0.299*r+0.587*g+0.114*bl;
  r=L+(r-L)*HINTENS;g=L+(g-L)*HINTENS;bl=L+(bl-L)*HINTENS;}
 const A=HTRANS,mix=(cc,wc)=>Math.round(Math.max(0,Math.min(255,cc*A+wc*(1-A))));
 return `rgb(${mix(r,251)},${mix(g,252)},${mix(bl,254)})`;}
function brVals(HF){                 // per-branch colour position for dynamic mode
 const n=NET.branches.length,out=new Array(n).fill(null);
 if(!DPF)return out;
 const isV=(HVAR==='vmag');
 if(HVAR==='vmag'||HVAR==='vang'){
  NET.branches.forEach((br,i)=>{const a=HF.v[br.f-1],b2=HF.v[br.t-1];
   if(a!==undefined&&b2!==undefined&&!br.off)out[i]=heatT((a+b2)/2,HF,isV);});
  return out;}
 const anyRate=NET.branches.some(br=>br.rate>0);let maxS=1e-6;
 if(DPF.flows)DPF.flows.forEach((fl,i)=>{if(fl&&!(NET.branches[i]||{}).off)maxS=Math.max(maxS,Math.hypot(fl.Pf,fl.Qf));});
 if(DPF.flows)NET.branches.forEach((br,i)=>{const fl=DPF.flows[i];if(!fl||br.off)return;
  const S=Math.hypot(fl.Pf,fl.Qf);let val=0;
  if(HVAR==='p')val=Math.abs(fl.Pf);else if(HVAR==='q')val=Math.abs(fl.Qf);
  else if(HVAR==='i')val=S/100/Math.max(0.2,(DPF.V[br.f-1]||1));
  else if(HVAR==='ploss')val=Math.abs(fl.loss||0);else if(HVAR==='qloss')val=Math.abs(fl.Qloss||0);
  else if(HVAR==='loading'||HVAR==='util')val=(br.rate>0)?S/br.rate*100:(anyRate?0:S/maxS*100);
  out[i]=heatT(val,HF,false);});
 return out;}
function fcmap(t){t=Math.max(0,Math.min(1,t));
 const cp=heatPal();
 const x=t*4,i=Math.min(4,Math.max(1,Math.floor(x)+1)),f=x-(i-1),a=cp[i-1],b=cp[i];
 return `rgb(${Math.round(a[0]*(1-f)+b[0]*f)},${Math.round(a[1]*(1-f)+b[1]*f)},${Math.round(a[2]*(1-f)+b[2]*f)})`;}
function fcmapI(t){                                   // fcmap × user colour intensity
 t=Math.max(0,Math.min(1,t));
 const cp=heatPal();
 const x=t*4,i=Math.min(4,Math.max(1,Math.floor(x)+1)),f=x-(i-1),a=cp[i-1],b=cp[i];
 let r=a[0]*(1-f)+b[0]*f,g=a[1]*(1-f)+b[1]*f,bl=a[2]*(1-f)+b[2]*f;
 if(HINTENS!==1){const L=0.299*r+0.587*g+0.114*bl;
  r=L+(r-L)*HINTENS;g=L+(g-L)*HINTENS;bl=L+(bl-L)*HINTENS;}
 const c=v=>Math.round(Math.max(0,Math.min(255,v)));
 return `rgb(${c(r)},${c(g)},${c(bl)})`;}
const BARL=26;                                   // bus-bar half length
function busPt(b,tx,ty){const L=BARL-3;          // nearest attachment point on the bar
 if(b.rot)return{x:b.x,y:Math.max(b.y-L,Math.min(b.y+L,ty))};
 return{x:Math.max(b.x-L,Math.min(b.x+L,tx)),y:b.y};}
function segClearH(y,x0,x1,iA,iB){          // horizontal run avoids bars+machines
 const lo=Math.min(x0,x1)-4,hi=Math.max(x0,x1)+4;
 for(let i=0;i<NET.buses.length;i++){
  if(i===iA||i===iB)continue;const b=NET.buses[i];
  const hw=b.rot?13:BARL+9,hh=b.rot?BARL+9:13;
  if(Math.abs(b.y-y)<hh&&b.x+hw>lo&&b.x-hw<hi)return false;}
 for(const g of NET.gens)if(Math.abs(g.y-y)<19&&g.x+19>lo&&g.x-19<hi)return false;
 return true;}
function segClearV(x,y0,y1,iA,iB){          // vertical run avoids bars+machines
 const lo=Math.min(y0,y1)-4,hi=Math.max(y0,y1)+4;
 for(let i=0;i<NET.buses.length;i++){
  if(i===iA||i===iB)continue;const b=NET.buses[i];
  const hw=b.rot?13:BARL+9,hh=b.rot?BARL+9:13;
  if(Math.abs(b.x-x)<hw&&b.y+hh>lo&&b.y-hh<hi)return false;}
 for(const g of NET.gens)if(Math.abs(g.x-x)<19&&g.y+19>lo&&g.y-19<hi)return false;
 return true;}
function pathClear(pts,iA,iB){              // every segment of a candidate path
 for(let k=1;k<pts.length;k++){
  const [x0,y0]=pts[k-1],[x1,y1]=pts[k];
  if(Math.abs(x1-x0)<0.5&&Math.abs(y1-y0)<0.5)continue;
  if(Math.abs(y1-y0)<0.5){if(!segClearH(y0,x0,x1,iA,iB))return false;}
  else if(Math.abs(x1-x0)<0.5){if(!segClearV(x0,y0,y1,iA,iB))return false;}
  else return false;}                       // diagonal never allowed here
 return true;}
function ductDrop(bus,ib,other,hy){         // bar -> duct lane, perpendicular exit
 const S=26,L=BARL-3;
 if(!bus.rot){                              // horizontal bar: vertical riser
  const tx0=Math.max(bus.x-L,Math.min(bus.x+L,other.x));
  const cands=[tx0];
  for(const k of [10,-10,16,-16,23,-23,0])cands.push(bus.x+k);
  for(const c of cands){const cc=Math.max(bus.x-L,Math.min(bus.x+L,c));
   if(segClearV(cc,bus.y,hy,ib,-1))return {pts:[[cc,bus.y],[cc,hy]],lx:cc};}
  const sgy=Math.sign(hy-bus.y)||-1,jy=bus.y+sgy*24;   // sidestep escape
  for(const dxo of [38,-38,52,-52,66,-66,80,-80,96,-96,110,-110]){
   const ox=bus.x+dxo;
   if(segClearV(tx0,bus.y,jy,ib,-1)&&segClearH(jy,tx0,ox,ib,-1)&&segClearV(ox,jy,hy,ib,-1))
    return {pts:[[tx0,bus.y],[tx0,jy],[ox,jy],[ox,hy]],lx:ox};}
  return {pts:[[tx0,bus.y],[tx0,hy]],lx:tx0};}
 const sg=Math.sign(other.x-bus.x)||1;      // vertical bar: stub then riser
 let sx=bus.x+sg*(S+8);
 for(let j=1;j<9;j++){
  if(segClearH(bus.y,bus.x,sx,ib,-1)&&segClearV(sx,bus.y,hy,ib,-1))break;
  sx=bus.x+sg*(S+8+j*14);}
 return {pts:[[bus.x,bus.y],[sx,bus.y],[sx,hy]],lx:sx};}
function ductRoute(A,B,iA,iB){              // dedicated lane above the diagram
 const hy=Math.min(...NET.buses.map(b=>b.y))-56-(HWN++)*16;
 const da=ductDrop(A,iA,B,hy),db=ductDrop(B,iB,A,hy);
 const pts=da.pts.concat([[db.lx,hy]],[...db.pts].reverse());
 return {pts,mx:(da.lx+db.lx)/2,my:hy,mdx:Math.sign(db.lx-da.lx)||1,mdy:0};}
function ptsD(pts){const q=[pts[0]];
 for(let k=1;k<pts.length;k++){const l=q[q.length-1];
  if(Math.abs(pts[k][0]-l[0])>0.5||Math.abs(pts[k][1]-l[1])>0.5)q.push(pts[k]);}
 return 'M'+q.map(p=>`${p[0]} ${p[1]}`).join(' L');}
function orthoRoute(A,B,o,idx,co){          // right-angle, perpendicular taps,
 const S=26;                                // and NEVER through another bus
 const iA=NET.buses.indexOf(A),iB=NET.buses.indexOf(B);
 const p1=busPt(A,B.x,B.y),p2=busPt(B,A.x,A.y);
 let best=null;                             // {pts,mx,my,mdx,mdy}
 if(!A.rot&&!B.rot){                        // horizontal bars -> vertical exits
  if(Math.abs(p1.x-p2.x)<2&&Math.abs(o)<1&&!co){
   const pts=[[p1.x,p1.y],[p2.x,p2.y]];
   if(pathClear(pts,iA,iB))best={pts,mx:p1.x,my:(p1.y+p2.y)/2,mdx:0,mdy:Math.sign(p2.y-p1.y)||1};}
  if(!best&&Math.abs(p1.x-p2.x)>=24){
   const mid0=(p1.y+p2.y)/2+o,cs=[mid0];
   for(const d of [22,44,66,88,110,132,154,176])cs.push(mid0+d,mid0-d);
   cs.push(Math.max(p1.y,p2.y)+S+12+Math.abs(o));
   for(const c of cs){
    if(Math.abs(c-p1.y)<10||Math.abs(c-p2.y)<10)continue;
    const pts=[[p1.x,p1.y],[p1.x,c],[p2.x,c],[p2.x,p2.y]];
    if(pathClear(pts,iA,iB)){best={pts,mx:(p1.x+p2.x)/2,my:c,mdx:Math.sign(p2.x-p1.x)||1,mdy:0};break;}}}
  if(!best&&Math.abs(p1.x-p2.x)<24){          // same column: route BESIDE it
   const sgv=Math.sign(p2.y-p1.y)||1,y1=p1.y+sgv*20,y2=p2.y-sgv*20;
   const bx=(p1.x+p2.x)/2;
   for(const dxo of [38,-38,52,-52,66,-66,80,-80,96,-96]){
    const sx=bx+dxo+o;
    const pts=[[p1.x,p1.y],[p1.x,y1],[sx,y1],[sx,y2],[p2.x,y2],[p2.x,p2.y]];
    if(pathClear(pts,iA,iB)){best={pts,mx:sx,my:(y1+y2)/2,mdx:0,mdy:sgv};break;}}}
 }else if(A.rot&&B.rot){                    // vertical bars -> horizontal exits
  if(Math.abs(p1.y-p2.y)<2&&Math.abs(o)<1&&!co){
   const pts=[[p1.x,p1.y],[p2.x,p2.y]];
   if(pathClear(pts,iA,iB))best={pts,mx:(p1.x+p2.x)/2,my:p1.y,mdx:Math.sign(p2.x-p1.x)||1,mdy:0};}
  if(!best&&Math.abs(p1.y-p2.y)>=24){
   const mid0=(p1.x+p2.x)/2+o,cs=[mid0];
   for(const d of [22,44,66,88,110,132,154,176])cs.push(mid0+d,mid0-d);
   cs.push(Math.max(p1.x,p2.x)+S+12+Math.abs(o));
   for(const c of cs){
    if(Math.abs(c-p1.x)<10||Math.abs(c-p2.x)<10)continue;
    const pts=[[p1.x,p1.y],[c,p1.y],[c,p2.y],[p2.x,p2.y]];
    if(pathClear(pts,iA,iB)){best={pts,mx:c,my:(p1.y+p2.y)/2,mdx:0,mdy:Math.sign(p2.y-p1.y)||1};break;}}}
  if(!best&&Math.abs(p1.y-p2.y)<24){          // same row: route BESIDE it
   const sgh=Math.sign(p2.x-p1.x)||1,x1=p1.x+sgh*20,x2=p2.x-sgh*20;
   const by=(p1.y+p2.y)/2;
   for(const dyo of [38,-38,52,-52,66,-66,80,-80,96,-96]){
    const sy=by+dyo+o;
    const pts=[[p1.x,p1.y],[x1,p1.y],[x1,sy],[x2,sy],[x2,p2.y],[p2.x,p2.y]];
    if(pathClear(pts,iA,iB)){best={pts,mx:(x1+x2)/2,my:sy,mdx:sgh,mdy:0};break;}}}
 }else{                                     // mixed: L then Z candidates
  const rev=!!A.rot,Hb=rev?B:A,Vb=rev?A:B;
  const iH=rev?iB:iA,iV=rev?iA:iB;
  const ph=busPt(Hb,Vb.x+o,Vb.y),pv=busPt(Vb,Hb.x,Hb.y+o);
  const hx=ph.x,L=BARL-3;
  const cy=Math.max(Vb.y-L,Math.min(Vb.y+L,pv.y));
  const fin=(pts,mx,my,sgn)=>({pts,mx,my,mdx:rev?-sgn:sgn,mdy:0,fwd:!rev});
  if(Math.abs(cy-ph.y)>=S&&Math.abs(Vb.x-hx)>=S){
   const pts=[[hx,ph.y],[hx,cy],[Vb.x,cy]];
   if(pathClear(pts,iH,iV))best=fin(pts,(hx+Vb.x)/2,cy,Math.sign(Vb.x-hx)||1);}
  if(!best){
   const sy0=ph.y+(cy>=ph.y?1:-1)*S+Math.abs(o);
   const sx=Vb.x-(Math.sign(Vb.x-hx)||1)*(S+8),cs=[sy0];
   for(const dd of [22,44,66,88])cs.push(sy0+dd,sy0-dd);
   for(const c of cs){
    const pts=[[hx,ph.y],[hx,c],[sx,c],[sx,cy],[Vb.x,cy]];
    if(pathClear(pts,iH,iV)){best=fin(pts,(hx+sx)/2,c,Math.sign(sx-hx)||1);break;}}}
  if(!best&&Math.abs(Vb.x-Hb.x)<24){           // same column, mixed bars:
   const sgv=Math.sign(Hb.y-Vb.y)||1;          // route BESIDE the column
   const y2=Hb.y-sgv*24,L2=BARL-3;
   for(const dxo of [38,-38,52,-52,66,-66,80,-80,96,-96]){
    const sx2=Vb.x+dxo;
    const tx=Math.max(Hb.x-L2,Math.min(Hb.x+L2,sx2));
    const pts=[[Vb.x,pv.y],[sx2,pv.y],[sx2,y2],[tx,y2],[tx,Hb.y]];
    if(pathClear(pts,iV,iH)){
     best={pts,mx:sx2,my:(pv.y+y2)/2,mdx:0,mdy:(rev?1:-1)*(Math.sign(y2-pv.y)||1),fwd:rev};
     break;}}}
 }
 if(!best){const D=ductRoute(A,B,iA,iB);best=D;}
 // the user may have dragged this line: shift its main run by br.co
 const pts=best.pts;
 if(co&&pts.length>=3){
  if(pts.length===3){
   const vert=Math.abs(pts[1][0]-pts[0][0])<0.5;      // first leg vertical?
   if(vert){pts[1][1]+=co;pts[2][1]+=co;best.my=(pts[1][1]+pts[2][1])/2;}
   else{pts[1][0]+=co;pts[2][0]+=co;best.mx=(pts[1][0]+pts[2][0])/2;}}
  else{
   let bi=1,bl=-1;
   for(let q=1;q<pts.length-2;q++){
    const L2=Math.abs(pts[q+1][0]-pts[q][0])+Math.abs(pts[q+1][1]-pts[q][1]);
    if(L2>bl){bl=L2;bi=q;}}
   const horiz=Math.abs(pts[bi+1][1]-pts[bi][1])<0.5;
   if(horiz){pts[bi][1]+=co;pts[bi+1][1]+=co;}
   else{pts[bi][0]+=co;pts[bi+1][0]+=co;}
   best.mx=(pts[bi][0]+pts[bi+1][0])/2;best.my=(pts[bi][1]+pts[bi+1][1])/2;}}
 // which way a drag moves this route (for interactive re-routing)
 let axis;
 if(pts.length===2)axis=Math.abs(pts[1][0]-pts[0][0])<0.5?'x':'y';
 else if(pts.length===3)axis=Math.abs(pts[1][0]-pts[0][0])<0.5?'y':'x';
 else{let bi=1,bl=-1;
  for(let q=1;q<pts.length-2;q++){
   const L2=Math.abs(pts[q+1][0]-pts[q][0])+Math.abs(pts[q+1][1]-pts[q][1]);
   if(L2>bl){bl=L2;bi=q;}}
  axis=Math.abs(pts[bi+1][1]-pts[bi][1])<0.5?'y':'x';}
 return {d:ptsD(best.pts),pts:best.pts,mx:best.mx,my:best.my,mdx:best.mdx,mdy:best.mdy,axis,
         fwd:best.fwd!==false};}       // true when the path runs from->to
// ---- label engine: no label may overlap a component or another label ----
let LBS=null,HWN=0;
function lbReset(){LBS={obs:[],req:[]};}
function lbObs(x,y,w,h){LBS.obs.push([x,y,w,h]);}
function lbBox(x,y,txt,anchor,size){const w=txt.length*size*0.68+2,h=size+3;
 let bx=x;if(anchor==='middle')bx=x-w/2;else if(anchor==='end')bx=x-w;
 return[bx,y-h+2,w,h];}
function lbFree(b){for(const o of LBS.obs){
 if(b[0]<o[0]+o[2]+2&&b[0]+b[2]>o[0]-2&&b[1]<o[1]+o[3]+2&&b[1]+b[3]>o[1]-2)return false;}
 return true;}
function lbReq(p,x,y,txt,o){LBS.req.push({p,x,y,txt:String(txt),o:o||{}});}
function lbArea(b){let t=0;for(const o of LBS.obs){
 const w=Math.min(b[0]+b[2],o[0]+o[2])-Math.max(b[0],o[0]);
 const h=Math.min(b[1]+b[3],o[1]+o[3])-Math.max(b[1],o[1]);
 if(w>0&&h>0)t+=w*h;}return t;}
function lbPlace(){LBS.req.sort((a,b)=>a.p-b.p);let out='';
 for(const r of LBS.req){const o=r.o,size=(o.size||10.5)*LBLK,a0=o.anchor||'start';   // ×LBLK: user label-scale setting
  const cands=[[0,0,a0]].concat(o.cands||[]);
  let px=r.x,py=r.y,pa=a0,box=null,best=1e18;
  for(const c of cands){const a=c[2]||a0,bb=lbBox(r.x+c[0],r.y+c[1],r.txt,a,size);
   const ar=lbArea(bb);
   if(ar<best){best=ar;px=r.x+c[0];py=r.y+c[1];pa=a;box=bb;}
   if(ar===0)break;}                           // first collision-free candidate wins
  LBS.obs.push(box);                           // placed labels block later ones
  const hc=haloColor(px,py);                   // adaptive halo: the field colour underneath
  out+=`<text x="${px}" y="${py}" font-size="${size}" fill="${o.fill||'#374151'}"${o.weight?` font-weight="${o.weight}"`:''}${hc?` style="stroke:${hc}"`:''}${pa!=='start'?` text-anchor="${pa}"`:''}>${r.txt}</text>`;}
 return out;}
// COMBINED FACTS symbol (UPFC / IPFC): a UPFC is a series converter on its line
// f–t plus a shunt converter dropped onto bus f, tied by a dashed DC-link; an IPFC
// is two series converters (line f–t and, once set, f2–t2) tied by the DC-link.
// The whole device is one selectable object (every part carries data-i=i).
function factsCombinedGlyph(d,i){
 const T=String(d.type).toUpperCase();
 const sel=DSEL&&DSEL.t==='facts'&&DSEL.i===i,ms=inMsel({t:'facts',i});
 const col=T==='UPFC'?'#7c3aed':'#be185d',bxc=sel?'#e67e22':col,bw=sel?3:2;
 const sbox=(mx,my)=>{                            // series-converter box (VSC glyph)
  let r=`<rect x="${mx-15}" y="${my-9}" width="30" height="18" rx="3" fill="#fff" stroke="${bxc}" stroke-width="${bw}" data-el="facts" data-i="${i}"/>`;
  r+=`<path d="M${mx-7} ${my+2} h3 v-4 h3 v6 h2" fill="none" stroke="${col}" stroke-width="1.3" pointer-events="none"/>`;
  lbObs(mx-16,my-11,32,22);return r;};
 let s='';
 if(T==='UPFC'){
  const A=NET.buses[d.f-1],B=NET.buses[d.t-1],sb=NET.buses[d.bus-1];if(!A||!B)return '';
  const mx=Math.round((A.x+B.x)/2),my=Math.round((A.y+B.y)/2);   // series box on the line
  const sx=(d.x!=null?d.x:(sb?sb.x:mx)),sy=(d.y!=null?d.y:(sb?sb.y+64:my+64));   // shunt anchor
  if(sb){let cd;                                  // right-angle tap onto the sending busbar
   if(!sb.rot){const tx=Math.max(sb.x-(BARL-3),Math.min(sb.x+(BARL-3),sx));
    cd=(tx===sx)?`M${sx} ${sy} L${sx} ${sb.y}`:`M${sx} ${sy} L${tx} ${sy} L${tx} ${sb.y}`;}
   else{const ty=Math.max(sb.y-(BARL-3),Math.min(sb.y+(BARL-3),sy));
    cd=(ty===sy)?`M${sx} ${sy} L${sb.x} ${sy}`:`M${sx} ${sy} L${sx} ${ty} L${sb.x} ${ty}`;}
   s+=`<path d="${cd}" fill="none" stroke="${col}" stroke-width="1.6" data-el="facts" data-i="${i}"/>`;}
  s+=`<path d="M${mx} ${my} L${sx} ${sy}" fill="none" stroke="${col}" stroke-width="1.2" stroke-dasharray="3 3" pointer-events="none"/>`;   // DC link
  s+=sbox(mx,my);
  s+=`<circle cx="${sx}" cy="${sy}" r="13" fill="#fff" stroke="${bxc}" stroke-width="${bw}" data-el="facts" data-i="${i}"/>`;
  s+=`<path d="M${sx-6} ${sy+2} h3 v-5 h3 v8 h2" fill="none" stroke="${col}" stroke-width="1.3" pointer-events="none"/>`;
  lbObs(sx-14,sy-14,28,28);
  if(ms)s+=`<circle cx="${sx}" cy="${sy}" r="20" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`;
  if(LOPT.gen)lbReq(5,sx,sy+18,'UPFC',{size:9,fill:col,weight:600,anchor:'middle',cands:[[0,12],[0,-24],[26,4,'start'],[-26,4,'end']]});
  if(DPF&&DPF.facts&&LOPT.pf){const sh=DPF.facts.find(z=>z.kind==='shunt'&&z.ptype==='UPFC'&&z.bus===d.bus),
    se=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='UPFC'&&z.f===d.f&&z.t===d.t);
   if(sh)lbReq(6,sx,sy+30,`${sh.Q>=0?'+':''}${sh.Q} MVAr${sh.sat?' ⚠':''}`,{size:9,fill:sh.sat?'#b45309':'#1e7a44',anchor:'middle',cands:[[0,12],[0,-30]]});
   if(se)lbReq(7,mx,my+16,`${Math.round(se.kcomp*100)}%${se.sat?' ⚠':''}`,{size:9,fill:se.sat?'#b45309':'#1e7a44',anchor:'middle',cands:[[0,11],[0,-25]]});}
  return s;}
 // IPFC — two series converters, DC-coupled
 const A=NET.buses[d.f-1],B=NET.buses[d.t-1];if(!A||!B)return '';
 const m1x=Math.round((A.x+B.x)/2),m1y=Math.round((A.y+B.y)/2);
 let m2=null;
 if(d.f2&&d.t2&&NET.buses[d.f2-1]&&NET.buses[d.t2-1]){
  const C=NET.buses[d.f2-1],D=NET.buses[d.t2-1];m2={x:Math.round((C.x+D.x)/2),y:Math.round((C.y+D.y)/2)};}
 if(m2)s+=`<path d="M${m1x} ${m1y} L${m2.x} ${m2.y}" fill="none" stroke="${col}" stroke-width="1.2" stroke-dasharray="3 3" pointer-events="none"/>`;
 s+=sbox(m1x,m1y);
 if(m2)s+=sbox(m2.x,m2.y);
 if(ms)s+=`<circle cx="${m1x}" cy="${m1y}" r="20" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`;
 if(LOPT.gen)lbReq(5,m1x,m1y-14,'IPFC',{size:9,fill:col,weight:600,anchor:'middle',cands:[[0,-11],[0,25],[24,4,'start'],[-24,4,'end']]});
 if(DPF&&DPF.facts&&LOPT.pf){
  const s1=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='IPFC'&&z.f===d.f&&z.t===d.t);
  if(s1)lbReq(6,m1x,m1y+16,`${Math.round(s1.kcomp*100)}%${s1.sat?' ⚠':''}`,{size:9,fill:s1.sat?'#b45309':'#1e7a44',anchor:'middle',cands:[[0,11],[0,-25]]});
  if(m2){const s2=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='IPFC'&&z.f===d.f2&&z.t===d.t2);
   if(s2)lbReq(7,m2.x,m2.y+16,`${Math.round(s2.kcomp*100)}%${s2.sat?' ⚠':''}`,{size:9,fill:s2.sat?'#b45309':'#1e7a44',anchor:'middle',cands:[[0,11],[0,-25]]});}}
 return s;}
// SERIES FACTS symbol (TCSC / TSSC / SSSC): a box on the line's midpoint with a
// series-capacitor (TCSC/TSSC) or converter (SSSC) glyph + the compensation %.
function factsSeriesGlyph(d,i){
 const A=NET.buses[d.f-1],B=NET.buses[d.t-1];if(!A||!B)return '';
 const sel=DSEL&&DSEL.t==='facts'&&DSEL.i===i;
 const col=d.type==='SSSC'?'#0e7490':'#b45309';
 const x=(d.x!=null?d.x:Math.round((A.x+B.x)/2)),y=(d.y!=null?d.y:Math.round((A.y+B.y)/2));
 let s=`<rect x="${x-15}" y="${y-9}" width="30" height="18" rx="3" fill="#fff" stroke="${sel?'#e67e22':col}" stroke-width="${sel?3:2}" data-el="facts" data-i="${i}"/>`;
 if(d.type==='SSSC')
  s+=`<path d="M${x-7} ${y+2} h3 v-4 h3 v6 h2" fill="none" stroke="${col}" stroke-width="1.3" pointer-events="none"/>`;
 else if(d.type==='TCSC')   // continuously-variable: IEC "adjustable" arrow through the plates
  s+=`<path d="M${x-9} ${y} h5 M${x+4} ${y} h5 M${x-2} ${y-6} v12 M${x+2} ${y-6} v12" fill="none" stroke="${col}" stroke-width="1.5" pointer-events="none"/>`+
     `<path d="M${x-11} ${y+7} L${x+11} ${y-7} l-5 1.1 M${x+11} ${y-7} l-1.1 5" fill="none" stroke="${col}" stroke-width="1.2" pointer-events="none"/>`;
 else                        // TSSC step-switched: staircase mark under the plates
  s+=`<path d="M${x-9} ${y} h5 M${x+4} ${y} h5 M${x-2} ${y-6} v12 M${x+2} ${y-6} v12" fill="none" stroke="${col}" stroke-width="1.5" pointer-events="none"/>`+
     `<path d="M${x-10} ${y+8} h3.6 v-2.1 h3.6 v-2.1 h3.6" fill="none" stroke="${col}" stroke-width="1.2" pointer-events="none"/>`;
 lbObs(x-16,y-11,32,22);
 if(LOPT.gen)lbReq(5,x,y-14,d.type,{size:9,fill:col,weight:600,anchor:'middle',cands:[[0,-11],[0,25],[24,4,'start'],[-24,4,'end']]});
 if(DPF&&DPF.facts&&LOPT.pf){const fr=DPF.facts.find(z=>z.kind==='series'&&z.f===d.f&&z.t===d.t&&String(z.type).toUpperCase()===String(d.type).toUpperCase());
  if(fr)lbReq(6,x,y+16,`${Math.round(fr.kcomp*100)}% comp${fr.sat?' ⚠':''}`,{size:9,fill:fr.sat?'#b45309':'#1e7a44',anchor:'middle',cands:[[0,11],[0,-25]]});}
 return s;}
// FACTS device symbol (SVC / STATCOM): a bus-attached shunt compensator drawn
// like a machine — a right-angle connector to the bar and an IEEE-style symbol,
// with its regulated Vref and (after a power flow) reactive output labelled.
function factsGlyph(d,i){
 const T=String(d.type).toUpperCase();
 if(T==='TCSC'||T==='TSSC'||T==='SSSC')return factsSeriesGlyph(d,i);
 if(T==='UPFC'||T==='IPFC')return factsCombinedGlyph(d,i);
 const b=NET.buses[d.bus-1];if(!b)return '';
 const sel=DSEL&&DSEL.t==='facts'&&DSEL.i===i,ms=inMsel({t:'facts',i});
 const isSVC=String(d.type).toUpperCase()==='SVC',col=isSVC?'#7c3aed':'#0e7490';
 const x=d.x,y=d.y;
 let cd;                                        // right-angle tap onto the busbar
 if(!b.rot){const tx=Math.max(b.x-(BARL-3),Math.min(b.x+(BARL-3),x));
  cd=(tx===x)?`M${x} ${y} L${x} ${b.y}`:`M${x} ${y} L${tx} ${y} L${tx} ${b.y}`;}
 else{const ty=Math.max(b.y-(BARL-3),Math.min(b.y+(BARL-3),y));
  cd=(ty===y)?`M${x} ${y} L${b.x} ${y}`:`M${x} ${y} L${x} ${ty} L${b.x} ${ty}`;}
 let s=`<path d="${cd}" fill="none" stroke="${col}" stroke-width="1.6" data-el="facts" data-i="${i}"/>`;
 if(isSVC){   // SVC: antiparallel thyristor pair (the IEC "thyristor-controlled"
  // signature) over the capacitor bank -- matches the MATLAB SLD glyph exactly
  s+=`<rect x="${x-13}" y="${y-13}" width="26" height="26" rx="3" fill="#fff" stroke="${sel?'#e67e22':col}" stroke-width="${sel?3:2}" data-el="facts" data-i="${i}"/>`;
  s+=`<path d="M${x-11} ${y-9} h8 l-4 6 z M${x-11} ${y-3} h8 M${x+3} ${y-3} h8 l-4 -6 z M${x+3} ${y-9} h8 M${x-5} ${y+4} h10 M${x-5} ${y+7} h10" fill="none" stroke="${col}" stroke-width="1.3" pointer-events="none"/>`;
 }else{                                          // STATCOM: converter circle + square-wave
  s+=`<circle cx="${x}" cy="${y}" r="14" fill="#fff" stroke="${sel?'#e67e22':col}" stroke-width="${sel?3:2}" data-el="facts" data-i="${i}"/>`;
  s+=`<path d="M${x-7} ${y+2} h3 v-5 h3 v8 h3 v-5 h2" fill="none" stroke="${col}" stroke-width="1.4" pointer-events="none"/>`;
 }
 if(ms)s+=`<circle cx="${x}" cy="${y}" r="20" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`;
 lbObs(x-15,y-15,30,30);
 const abv=y<=b.y;
 if(LOPT.gen)lbReq(5,x,y+(abv?-20:27),d.type,{size:9.5,fill:col,weight:600,anchor:'middle',
  cands:[[0,abv?-12:12],[0,abv?-24:24],[26,4,'start'],[-26,4,'end']]});
 if(DPF&&DPF.facts&&LOPT.pf){const fr=DPF.facts.find(z=>z.bus===d.bus&&String(z.type).toUpperCase()===String(d.type).toUpperCase());
  if(fr)lbReq(6,x,y+(abv?29:-22),`${fr.Q>=0?'+':''}${fr.Q} MVAr${fr.sat?' ⚠lim':''}`,{size:9.5,fill:fr.sat?'#b45309':'#1e7a44',anchor:'middle',
   cands:[[0,abv?12:-12],[0,abv?24:-24],[28,4,'start'],[-28,4,'end']]});}
 return s;}
function loadGlyph(b,i){let s='';const LBL=LOPT.load,ld=(b.Pd||0)!==0||(b.Qd||0)!==0;
 if(ld){
  const lc=(DYNBUS&&DYNBUS[i])||'#4b5563';   // dynamic mode: load follows its bus colour
  if(b.rot){const sg=b.flip?-1:1,lx=b.x+sg*26,ay=b.y+14;
   s+=`<line x1="${b.x+sg*5}" y1="${ay}" x2="${lx}" y2="${ay}" stroke="${lc}" stroke-width="1.6" data-el="bus" data-i="${i}"/>`;
   s+=`<path d="M${lx} ${ay-6} l0 12 l${sg*11} -6 z" fill="${lc}" data-el="bus" data-i="${i}"/>`;
   lbObs(sg>0?b.x+5:b.x-37,ay-7,32,14);
   if(LBL)lbReq(3,lx+sg*15,ay+4,`${b.Pd}+j${b.Qd}`,{size:10,fill:'#6b7280',anchor:sg>0?'start':'end',
    cands:[[0,-13],[0,14],[0,27]]});}
  else{const sg=b.flip?-1:1,ly=b.y+sg*26,ax=b.x+14;
   s+=`<line x1="${ax}" y1="${b.y+sg*5}" x2="${ax}" y2="${ly}" stroke="${lc}" stroke-width="1.6" data-el="bus" data-i="${i}"/>`;
   s+=`<path d="M${ax-6} ${ly} l12 0 l-6 ${sg*11} z" fill="${lc}" data-el="bus" data-i="${i}"/>`;
   lbObs(ax-7,sg>0?b.y+5:b.y-37,14,32);
   if(LBL)lbReq(3,ax+10,ly+(sg>0?9:-3),`${b.Pd}+j${b.Qd}`,{size:10,fill:'#6b7280',
    cands:[[0,sg*12],[0,-sg*14],[0,sg*24],[8,0],[0,sg*36],[10,sg*24]]});}}
 if((b.Bs||0)!==0&&LBL){
  if(b.rot)lbReq(4,b.x,b.y+BARL+26,`⊥${b.Bs}MVAr`,{size:10,fill:'#117a8b',anchor:'middle',
   cands:[[0,13],[0,26],[0,-2*BARL-34],[0,39]]});
  else lbReq(4,b.x-BARL-5,b.y+(b.flip?-14:22),`⊥${b.Bs}MVAr`,{size:10,fill:'#117a8b',anchor:'end',
   cands:[[0,b.flip?-13:13],[0,b.flip?-26:26],[0,-35],[0,b.flip?-39:39],[0,48]]});}
 return s;}
// draw() is wrapped so a stray error NEVER blanks the canvas or wedges input —
// on failure the previous frame simply stays on screen.
function draw(){try{_draw();}catch(e){try{console.error('draw',e);stat('recovered from a draw error');}catch(_){}}try{rexTick();}catch(_){}}
function _draw(){const svg=$('sld');if(!svg)return;
 const st=$('stSys');
 if(st)st.textContent=NET?`${NET.name} — ${NET.buses.length} buses · ${NET.branches.length} lines · ${NET.gens.length} machines`:'no network';
 if(!NET){svg.innerHTML='<text x="30" y="40" font-size="15" fill="#8b93a3">load a benchmark system above, or start a new empty diagram</text>';zPct();return;}
 // FAST = mid-interaction: skip the expensive label engine, contour, minimap,
 // flow animation, and (on big networks) orthogonal routing — restored on release
 const FAST=interacting();
 const LBL=!FAST&&(LOPT.pf||LOPT.volt||LOPT.bus||LOPT.lname||LOPT.gen||LOPT.load);
 lbReset();HWN=0;BRAX=[];
 const CONT=VOPT.cont&&DPF&&!FAST&&NET.buses.length>0;
 const DYNC=(CMODE==='dynamic')&&DPF&&NET.buses.length>0;
 const DHF=(CONT||DYNC)?hmapField():null, DISV=(HVAR==='vmag');
 DYNBUS=(DYNC&&DHF)?NET.buses.map((b2,q)=>fcmap(heatT(DHF.v[q],DHF,DISV))):null;
 const DBR=(DYNC&&DHF)?brVals(DHF):null;
 HALOF=null;
 const ORTHO=VOPT.ortho&&!(FAST&&NET.buses.length>28);
 let defs=`<defs><marker id="arr" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 z" fill="#7c8aa5"/></marker><marker id="arrO" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 z" fill="#e67e22"/></marker>`;
 if(VOPT.grid)defs+=`<pattern id="gp" width="40" height="40" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1.1" fill="#d9dfeb"/></pattern>`;
 if(CONT){const xs3=NET.buses.map(b=>b.x);
  const bw3=Math.max(...xs3)-Math.min(...xs3)+200;
  const sd=Math.max(1.5,Math.min(60,Math.max(6,Math.min(26,bw3/120*0.9))*HSMOOTH*(HLEVELS>=2?0.5:1)));   // ×HSMOOTH: user contour smoothing (halved for crisp discrete bands)
  var cst2;
  cst2=k=>{const cpg=heatPal();return `rgb(${cpg[k][0]},${cpg[k][1]},${cpg[k][2]})`;};
  defs+=`<linearGradient id="cgrad">`+[4,3,2,1,0].map((k,j)=>`<stop offset="${(j*0.25).toFixed(2)}" stop-color="${cst2(k)}"/>`).join('')+`</linearGradient>`+
   `<linearGradient id="cgrad2">`+[0,1,2,3,4].map((k,j)=>`<stop offset="${(j*0.25).toFixed(2)}" stop-color="${cst2(k)}"/>`).join('')+`</linearGradient>`+
   `<filter id="cblur" x="-6%" y="-6%" width="112%" height="112%"><feGaussianBlur stdDeviation="${sd.toFixed(1)}"/></filter>`;}
 else if(DYNC){const cpg=heatPal(),cg=k=>`rgb(${cpg[k][0]},${cpg[k][1]},${cpg[k][2]})`;
  defs+=`<linearGradient id="cgrad">`+[4,3,2,1,0].map((k,j)=>`<stop offset="${(j*0.25).toFixed(2)}" stop-color="${cg(k)}"/>`).join('')+`</linearGradient>`+
   `<linearGradient id="cgrad2">`+[0,1,2,3,4].map((k,j)=>`<stop offset="${(j*0.25).toFixed(2)}" stop-color="${cg(k)}"/>`).join('')+`</linearGradient>`;}
 defs+=`</defs><style>#sld text{paint-order:stroke;stroke:#fbfcfe;stroke-width:2.4px;stroke-linejoin:round;pointer-events:none;user-select:none}</style>`;
 let s='';let sFlow='';        // flow arrows collected separately, painted ABOVE lines/buses/machines
 // Night mode: the workspace canvas is dark; the diagram sits on a light
 // "paper" sheet (network area + margin — the same extent as the heat field,
 // plus room for the legend), so the heat map and all diagram colours read
 // exactly as in day mode while the empty surroundings stay dark.
 if(uiDark()&&NET.buses.length){
  const xsP=NET.buses.map(b=>b.x),ysP=NET.buses.map(b=>b.y);
  const px0=Math.min(...xsP)-100,px1=Math.max(...xsP)+100;
  const py0=Math.min(...ysP)-100,py1=Math.max(...ysP)+100;
  const pw=Math.max(60,px1-px0),ph=Math.max(60,py1-py0);
  s+=`<clipPath id="pclip"><rect x="${px0}" y="${py0}" width="${pw}" height="${ph}" rx="14"/></clipPath>`+
     `<rect x="${px0}" y="${py0}" width="${pw}" height="${ph}" rx="14" fill="#fbfcfe" stroke="#26304a" stroke-width="1" pointer-events="none"/>`;
 }
 if(VOPT.grid&&!CONT)s+=`<rect x="${VB[0]}" y="${VB[1]}" width="${VB[2]}" height="${VB[3]}" fill="url(#gp)" pointer-events="none"/>`;   // never draw the reference grid over the heat map
 if(CONT){                                   // smooth colour field of the chosen heat-map variable
  const HF=DHF,isV=DISV;
  const xs2=NET.buses.map(b=>b.x),ys2=NET.buses.map(b=>b.y);
  const cx0=Math.min(...xs2)-100,cx1=Math.max(...xs2)+100;
  const cy0=Math.min(...ys2)-100,cy1=Math.max(...ys2)+100;
  const HD=HDENS[HDLEVEL]||HDENS[1];          // user density preset (Low/Medium/High/Ultra)
  let cw=Math.max(3,(cx1-cx0)/(HD.n*HRES));   // fine grid, × user interpolation-resolution
  const cap=Math.min(90000,HD.cap*HRES*HRES);
  while(((cx1-cx0)/cw)*((cy1-cy0)/cw)>cap)cw*=1.15;      // ... capped for speed
  const span=(HF.hi-HF.lo)||1;let cells='';
  for(let gy=cy0;gy<cy1;gy+=cw)for(let gx=cx0;gx<cx1;gx+=cw){
   const px=gx+cw/2,py=gy+cw/2;let sw=0,sv=0;
   for(let q=0;q<NET.buses.length;q++){const b2=NET.buses[q];
    const dd2=(b2.x-px)*(b2.x-px)+(b2.y-py)*(b2.y-py)+900,w2=1/(dd2*Math.sqrt(dd2));
    sw+=w2;sv+=w2*HF.v[q];}
   const val=sv/sw;
   let t=isV?(1.06-val)/0.12:(val-HF.lo)/span;   // voltage: low=red; others: high=red
   t=Math.max(0,Math.min(1,t));
   t=Math.max(0,Math.min(1,0.5+(t-0.5)*HCONTR));    // user contrast
   if(HLEVELS>=2)t=Math.round(t*(HLEVELS-1))/(HLEVELS-1);   // discrete contour bands
   cells+=`<rect x="${gx-0.4}" y="${gy-0.4}" width="${cw+0.8}" height="${cw+0.8}" fill="${fcmapI(t)}"/>`;}
  s+=(uiDark()?'<g clip-path="url(#pclip)">':'')+`<g filter="url(#cblur)" opacity="${HTRANS.toFixed(2)}" pointer-events="none">${cells}</g>`+(uiDark()?'</g>':'');
  HALOF={bx:NET.buses.map(b=>b.x),by:NET.buses.map(b=>b.y),v:HF.v,
         isV,lo:HF.lo,span:(HF.hi-HF.lo)||1,x0:cx0,x1:cx1,y0:cy0,y1:cy1};   // HTRANS: user heat transparency
  }
 // colour-scale legend — for the heat map AND for by-value component colours
 if((CONT||DYNC)&&DHF){
  const xsL=NET.buses.map(b=>b.x),ysL=NET.buses.map(b=>b.y);
  const lx0=Math.min(...xsL)-100,ly1=Math.max(...ysL)+100;
  if(DISV){
   s+=`<rect x="${lx0}" y="${ly1+16}" width="150" height="10" rx="3" fill="url(#cgrad)" pointer-events="none"/>`+
      `<text x="${lx0}" y="${ly1+40}" font-size="10">0.94 pu</text>`+
      `<text x="${lx0+58}" y="${ly1+40}" font-size="10">1.00</text>`+
      `<text x="${lx0+118}" y="${ly1+40}" font-size="10">1.06</text>`;
  }else{
   const fm=x=>{x=+x;return Math.abs(x)>=100?x.toFixed(0):Math.abs(x)>=10?x.toFixed(1):x.toFixed(2);};
   s+=`<rect x="${lx0}" y="${ly1+16}" width="150" height="10" rx="3" fill="url(#cgrad2)" pointer-events="none"/>`+
      `<text x="${lx0}" y="${ly1+40}" font-size="10">${fm(DHF.lo)}</text>`+
      `<text x="${lx0+150}" y="${ly1+40}" font-size="10" text-anchor="end">${fm(DHF.hi)} ${DHF.unit}</text>`+
      `<text x="${lx0}" y="${ly1+55}" font-size="10" fill="#5a6472">${DHF.label}</text>`;}}
 // ---- branches (parallel circuits offset; straight or orthogonal routing) ----
 NU=netunit(); ASZ=arrowsize();   // refresh the adaptive arrow unit + size for this draw
 let SfMax=1;
 if(VOPT.critL&&DPF)SfMax=Math.max(1e-6,...DPF.flows.map(f2=>f2?Math.hypot(f2.Pf,f2.Qf):0));
 const grp={};
 NET.branches.forEach((br,i)=>{const k=Math.min(br.f,br.t)+'-'+Math.max(br.f,br.t);(grp[k]=grp[k]||[]).push(i);});
 NET.branches.forEach((br,i)=>{const A=NET.buses[br.f-1],B=NET.buses[br.t-1];if(!A||!B)return;
  const k=Math.min(br.f,br.t)+'-'+Math.max(br.f,br.t),g=grp[k],o=(g.indexOf(i)-(g.length-1)/2)*16;
  const sel=DSEL&&DSEL.t==='br'&&DSEL.i===i,fl=DPF?DPF.flows[i]:null;
  let col=sel?'#e67e22':'#7c8aa5',wd=sel?3.2:2,pct=null;
  if(!sel&&DBR&&DBR[i]!=null){col=fcmap(DBR[i]);wd=2.5;}   // dynamic mode: line follows the selected variable
  if(VOPT.critL&&fl){const Sfm=Math.hypot(fl.Pf,fl.Qf);
   pct=(br.rate&&br.rate>0)?Sfm/br.rate:Sfm/SfMax;
   if(!sel){if(pct>=1){col='#c0392b';wd=3.6;}
    else if(pct>=0.8){col='#e67e22';wd=2.9;}}}
  if(br.off&&!sel){col='#cbd0da';wd=1.5;pct=null;}          // out of service -> pale, no flow
  const dx=B.x-A.x,dy=B.y-A.y,dd=Math.hypot(dx,dy)||1;
  const p1=busPt(A,B.x,B.y),p2=busPt(B,A.x,A.y);
  let path,mx,my,mdx,mdy;
  let blen,rdd,fdd;                          // drawn length + reversed + forward path string
  let bfwd=true;
  let flowPts=null;                          // polyline (from-bus -> to-bus) for flow chevrons
  if(ORTHO){
   const R=orthoRoute(A,B,o,i,br.co||0);
   BRAX[i]=R.axis;bfwd=R.fwd;fdd=R.d;
   mx=R.mx;my=R.my;mdx=R.mdx;mdy=R.mdy;
   blen=0;for(let q=1;q<R.pts.length;q++)blen+=Math.abs(R.pts[q][0]-R.pts[q-1][0])+Math.abs(R.pts[q][1]-R.pts[q-1][1]);
   rdd=ptsD([...R.pts].reverse());
   flowPts=bfwd?R.pts.map(p=>[p[0],p[1]]):[...R.pts].reverse().map(p=>[p[0],p[1]]);
   s+=`<path id="brv${i}" d="${R.d}" fill="none" stroke="${col}" stroke-width="${wd}" stroke-linejoin="round"/>`;
   s+=`<path d="${R.d}" fill="none" stroke="transparent" stroke-width="13" data-el="br" data-i="${i}"/>`;
  }else{
   BRAX[i]=null;
   mdx=dx/dd;mdy=dy/dd;blen=Math.hypot(p2.x-p1.x,p2.y-p1.y);
   if(g.length>1){const nx=-mdy,ny=mdx,cx=(p1.x+p2.x)/2+nx*o*1.9,cy=(p1.y+p2.y)/2+ny*o*1.9;
    path=`M${p1.x} ${p1.y} Q${cx} ${cy} ${p2.x} ${p2.y}`;fdd=path;
    rdd=`M${p2.x} ${p2.y} Q${cx} ${cy} ${p1.x} ${p1.y}`;
    s+=`<path id="brv${i}" d="${path}" fill="none" stroke="${col}" stroke-width="${wd}"/>`;
    s+=`<path d="${path}" fill="none" stroke="transparent" stroke-width="13" data-el="br" data-i="${i}"/>`;
    mx=(p1.x+p2.x)/2+nx*o*0.95;my=(p1.y+p2.y)/2+ny*o*0.95;
    flowPts=[];const NS=Math.max(3,Math.ceil(blen/10));
    for(let q=0;q<=NS;q++){const t=q/NS,it=1-t;
     flowPts.push([it*it*p1.x+2*it*t*cx+t*t*p2.x, it*it*p1.y+2*it*t*cy+t*t*p2.y]);}}
   else{const pd=`M${p1.x} ${p1.y} L${p2.x} ${p2.y}`;fdd=pd;
    rdd=`M${p2.x} ${p2.y} L${p1.x} ${p1.y}`;
    s+=`<path id="brv${i}" d="${pd}" fill="none" stroke="${col}" stroke-width="${wd}"/>`;
    s+=`<path d="${pd}" fill="none" stroke="transparent" stroke-width="13" data-el="br" data-i="${i}"/>`;
    mx=(p1.x+p2.x)/2;my=(p1.y+p2.y)/2;
    flowPts=[[p1.x,p1.y],[p2.x,p2.y]];}}
  if(br.xf||(br.tap&&br.tap!==0&&br.tap!==1)){    // two-winding transformer symbol
   s+=`<circle cx="${mx-mdx*5}" cy="${my-mdy*5}" r="7" fill="#fbfcfe" stroke="${col}" stroke-width="1.6" data-el="br" data-i="${i}"/><circle cx="${mx+mdx*5}" cy="${my+mdy*5}" r="7" fill="none" stroke="${col}" stroke-width="1.6" data-el="br" data-i="${i}"/>`;
   lbObs(mx-13,my-9,26,18);}
  if(LOPT.lname)lbReq(8,mx+7,my+16,br.name||('L'+br.f+'-'+br.t),{size:9.5,fill:'#8a6d3b',
   cands:[[0,-24],[-14,0,'end'],[0,13],[0,-37],[16,0],[0,26],[0,39],[-14,-24,'end']]});
  if(fl&&!br.off){const sgn=fl.Pf>=0?1:-1;
   const ax=mx+sgn*mdx*11,ay=my+sgn*mdy*11;
   // ONE flow indicator: chevron arrowheads sitting on the line, pointing in the
   // real-power direction — STATIC when Flow-Arrows is off, MARCHING when on.
   if(VOPT.anim&&!FAST&&flowPts&&flowPts.length>=2){   // FLOW ON — chevrons march along the line
    const PfMax=Math.max(1e-6,...DPF.flows.map(f2=>f2?Math.abs(f2.Pf):0));
    const vpx=(24+40*Math.min(1,Math.abs(fl.Pf)/PfMax))*FLOWSPD;   // chevron speed px/s (× user speed)
    sFlow+=flowGlide(i,flowPts,fl.Pf>=0,col,wd,vpx);      // marches on straight, curved AND ortho routes
   }else{                                    // FLOW OFF — one chevron at the midpoint, aligned to the line
    if(flowPts&&flowPts.length>=2)
     sFlow+=midChevron(flowPts,fl.Pf>=0,col,sel);
    else                                     // fallback (no polyline captured)
     sFlow+=`<circle cx="${mx}" cy="${my}" r="2.2" fill="${col}"/><line x1="${mx}" y1="${my}" x2="${ax}" y2="${ay}" stroke="${col}" stroke-width="2.2" marker-end="url(#${sel?'arrO':'arr'})"/>`;}
   lbObs(Math.min(mx,ax)-5,Math.min(my,ay)-5,Math.abs(ax-mx)+10,Math.abs(ay-my)+10);
   if(LOPT.pf)lbReq(7,mx+7,my-7,`${Math.abs(fl.Pf).toFixed(0)} MW`+(VOPT.critL&&br.rate>0?` · ${Math.round(pct*100)}%`:''),{cands:[[0,15],[-14,0,'end'],[-14,15,'end'],[0,-13],[8,4],[0,28],[0,-26],[16,15],[16,-13],[-14,-13,'end'],[0,41],[0,-39],[26,28],[26,-26],[-26,28,'end'],[-26,-26,'end'],[0,54],[0,-52]]});}});
 if(DPEND!=null&&NET.buses[DPEND]){const A=NET.buses[DPEND];
  s+=`<circle cx="${A.x}" cy="${A.y}" r="${BARL+8}" fill="none" stroke="#e67e22" stroke-dasharray="4 3" stroke-width="2"/>`;
  if(DDRAG&&DDRAG.t==='newline'&&DDRAG.moved){          // rubber-band to the cursor
   const to=busAt(DDRAG.cx,DDRAG.cy),tx=to>=0?NET.buses[to].x:DDRAG.cx,ty=to>=0?NET.buses[to].y:DDRAG.cy;
   s+=`<line x1="${A.x}" y1="${A.y}" x2="${tx}" y2="${ty}" stroke="#e67e22" stroke-width="2" stroke-dasharray="6 4"/>`;
   if(to>=0&&to!==DPEND)s+=`<circle cx="${tx}" cy="${ty}" r="${BARL+8}" fill="none" stroke="#1e8449" stroke-dasharray="4 3" stroke-width="2"/>`;}}
 // ---- buses ----
 NET.buses.forEach((b,i)=>{const sel=DSEL&&DSEL.t==='bus'&&DSEL.i===i,ms=inMsel({t:'bus',i});
  let barc=sel?'#e67e22':'#1f3b73';
  if(!sel&&DYNBUS)barc=DYNBUS[i];              // dynamic mode: bus follows the selected variable
  if(!sel&&VOPT.critB&&DPF){const v=DPF.V[i];
   if(v<0.95)barc='#b42318';               // undervoltage: red
   else if(v<0.97)barc='#b7791f';          // low: amber
   else if(v>1.07)barc='#5b21b6';          // severe over: violet
   else if(v>1.05)barc='#1d4ed8';}         // overvoltage: blue
  if(b.rot){s+=`<rect x="${b.x-9}" y="${b.y-BARL-4}" width="18" height="${2*BARL+8}" fill="transparent" data-el="bus" data-i="${i}"/>`;
   s+=`<rect x="${b.x-5}" y="${b.y-BARL}" width="10" height="${2*BARL}" rx="2" fill="${barc}" data-el="bus" data-i="${i}"/>`;
   lbObs(b.x-7,b.y-BARL-2,14,2*BARL+4);}
  else{s+=`<rect x="${b.x-BARL-4}" y="${b.y-9}" width="${2*BARL+8}" height="18" fill="transparent" data-el="bus" data-i="${i}"/>`;
   s+=`<rect x="${b.x-BARL}" y="${b.y-5}" width="${2*BARL}" height="10" rx="2" fill="${barc}" data-el="bus" data-i="${i}"/>`;
   lbObs(b.x-BARL-2,b.y-7,2*BARL+4,14);}
  if(ms)s+=b.rot?`<rect x="${b.x-13}" y="${b.y-BARL-8}" width="26" height="${2*BARL+16}" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`
              :`<rect x="${b.x-BARL-8}" y="${b.y-13}" width="${2*BARL+16}" height="26" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`;
  const nm=(b.name?b.name+' · ':'')+(i+1)+(b.type==='slack'?' ⚓':'');
  if(LOPT.bus){
   if(b.rot)lbReq(1,b.x,b.y-BARL-8,nm,{size:11,anchor:'middle',cands:[[0,2*BARL+22],[-13,BARL+12,'end'],[0,-13],[0,-26]]});
   else lbReq(1,b.x-BARL-5,b.y+4,nm,{size:11,anchor:'end',cands:[[0,-13],[0,17],[2*BARL+10,0,'start'],[2*BARL+10,-13,'start'],[0,-26],[0,-39],[2*BARL+10,17,'start']]});}
  if(DPF&&LOPT.volt){const v=DPF.V[i],vt=`${v.toFixed(3)}∠${DPF.th[i].toFixed(0)}°`;
   if(b.rot)lbReq(2,b.x,b.y+BARL+14,vt,{fill:vband(v),weight:600,anchor:'middle',cands:[[0,13],[0,-2*BARL-24],[0,26],[0,39]]});
   else lbReq(2,b.x+BARL+5,b.y+4,vt,{fill:vband(v),weight:600,cands:[[0,-13],[0,17],[-2*BARL-10,0,'end'],[-2*BARL-10,-13,'end'],[0,30],[0,-26],[-2*BARL-10,17,'end'],[0,43]]});}
  s+=loadGlyph(b,i);});
 // ---- generators ----
 NET.gens.forEach((g,i)=>{const b=NET.buses[g.bus-1];if(!b)return;
  const sel=DSEL&&DSEL.t==='gen'&&DSEL.i===i,ms=inMsel({t:'gen',i}),c=g.off?'#b6bcc8':(TAGC[g.tag]||'#1f3b73');
  const dc=(!g.off&&DYNBUS)?DYNBUS[g.bus-1]:null;   // dynamic mode: machine follows its bus colour
  let cd;                                       // connector taps the bar at a right angle
  if(!b.rot){const tx=Math.max(b.x-(BARL-3),Math.min(b.x+(BARL-3),g.x));
   cd=(tx===g.x)?`M${g.x} ${g.y} L${g.x} ${b.y}`:`M${g.x} ${g.y} L${tx} ${g.y} L${tx} ${b.y}`;}
  else{const ty=Math.max(b.y-(BARL-3),Math.min(b.y+(BARL-3),g.y));
   cd=(ty===g.y)?`M${g.x} ${g.y} L${b.x} ${g.y}`:`M${g.x} ${g.y} L${g.x} ${ty} L${b.x} ${ty}`;}
  s+=`<path d="${cd}" fill="none" stroke="${dc||c}" stroke-width="1.6" data-el="gen" data-i="${i}"/>`;
  s+=`<circle cx="${g.x}" cy="${g.y}" r="15" fill="#fff" stroke="${sel?'#e67e22':(dc||c)}" stroke-width="${sel?3:2.2}" data-el="gen" data-i="${i}"/>`;
  if(ms)s+=`<circle cx="${g.x}" cy="${g.y}" r="20" fill="none" stroke="#e67e22" stroke-dasharray="4 3"/>`;
  s+=`<text x="${g.x}" y="${g.y+4}" font-size="10" font-weight="700" fill="${c}" text-anchor="middle" style="pointer-events:none">${TAGS[g.tag]||'?'}</text>`;
  lbObs(g.x-17,g.y-17,34,34);
  const abv=g.y<=b.y;
  if(LOPT.gen)lbReq(5,g.x,g.y+(abv?-21:28),`${g.Pg} MW`,{size:10,fill:'#6b7280',anchor:'middle',
   cands:[[0,abv?-13:13],[27,4,'start'],[-27,4,'end'],[0,abv?-26:26],[0,abv?-39:39],[27,abv?-13:13,'start'],[-27,abv?-13:13,'end'],[42,4,'start'],[-42,4,'end']]});
  if(DPF&&DPF.Pg[i]!==undefined&&LOPT.pf)lbReq(6,g.x,g.y+(abv?31:-24),`${DPF.Pg[i]}+j${DPF.Qg[i]}`,{size:10,fill:'#1e7a44',anchor:'middle',
   cands:[[0,abv?13:-13],[27,4,'start'],[-27,4,'end'],[0,abv?26:-26],[0,abv?39:-39]]});});
 // ---- FACTS devices (SVC / STATCOM): bus-attached shunt compensators ----
 if(NET.facts)NET.facts.forEach((d,i)=>{s+=factsGlyph(d,i);});
 s+=sFlow;              // power-flow arrows on top: above lines, buses and machines (always visible)
 if(REXHL&&REXHL.size){ // filter/search highlight: ring the matching components (GIS-style)
  REXHL.forEach(k=>{const p=k.split(':'),t=p[0],i=+p[1];
   if(t==='bus'&&NET.buses[i]){const b=NET.buses[i];
    s+=`<circle cx="${b.x}" cy="${b.y}" r="${BARL+12}" fill="none" stroke="#7c3aed" stroke-width="2.5" stroke-dasharray="3 3" pointer-events="none"/>`;}
   else if(t==='gen'&&NET.gens[i]){const g=NET.gens[i];
    s+=`<circle cx="${g.x}" cy="${g.y}" r="22" fill="none" stroke="#7c3aed" stroke-width="2.5" stroke-dasharray="3 3" pointer-events="none"/>`;}
   else if(t==='br'&&NET.branches[i]){const br=NET.branches[i],A=NET.buses[br.f-1],B=NET.buses[br.t-1];
    if(A&&B)s+=`<line x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}" stroke="#7c3aed" stroke-width="6" stroke-opacity="0.35" pointer-events="none"/>`;}});}
 // ---- annotations (decorative text; ignored by the solver) ----
 if(NET.notes)NET.notes.forEach((nt,i)=>{const sel=DSEL&&DSEL.t==='note'&&DSEL.i===i;
  const sz=nt.size||14,lines=String(nt.text||'').split('\n');
  const w=Math.max(...lines.map(t=>t.length))*sz*0.58+10,h=lines.length*sz*1.25+6;
  const rot=nt.rot?` transform="rotate(${nt.rot} ${nt.x} ${nt.y})"`:'';
  s+=`<g${rot}>`;
  s+=`<rect x="${nt.x-4}" y="${nt.y-sz}" width="${w}" height="${h}" rx="3" fill="${sel?'rgba(230,126,34,0.10)':'transparent'}" stroke="${sel?'#e67e22':'transparent'}" stroke-dasharray="4 3" data-el="note" data-i="${i}"/>`;
  s+=`<text x="${nt.x}" y="${nt.y}" font-size="${sz}" fill="#1f2937" style="pointer-events:none">`+
     lines.map((t,k)=>`<tspan x="${nt.x}" dy="${k?sz*1.25:0}">${(t||' ').replace(/&/g,'&amp;').replace(/</g,'&lt;')}</tspan>`).join('')+`</text></g>`;});
 // ---- marquee ----
 if(DDRAG&&DDRAG.t==='marq'){
  const x=Math.min(DDRAG.x0,DDRAG.x1),y=Math.min(DDRAG.y0,DDRAG.y1);
  s+=`<rect x="${x}" y="${y}" width="${Math.abs(DDRAG.x1-DDRAG.x0)}" height="${Math.abs(DDRAG.y1-DDRAG.y0)}" fill="rgba(230,126,34,0.07)" stroke="#e67e22" stroke-dasharray="5 3"/>`;}
 // ---- palette drag-drop preview: the component itself, translucent, AT the cursor ----
 if(PNEW&&PNEW.active&&PNEW.over&&isFinite(PNEW.wx)&&isFinite(PNEW.wy)){
  const t=PNEW.tool,px=snapv(PNEW.wx),py=snapv(PNEW.wy);
  s+=`<g opacity="0.62" pointer-events="none">`;
  if(t==='addbus'){s+=`<rect x="${px-BARL}" y="${py-5}" width="${2*BARL}" height="10" rx="2" fill="#1f3b73"/>`;}
  else if(t==='addnote'){s+=`<text x="${px}" y="${py+5}" font-size="14" fill="#1f2937">text</text>`;}
  else{const bi=busAt(PNEW.wx,PNEW.wy);           // machine/load/shunt attach to a bus
   if(bi>=0){const b=NET.buses[bi];
    s+=`<circle cx="${b.x}" cy="${b.y}" r="${BARL+9}" fill="none" stroke="#1e8449" stroke-width="2" stroke-dasharray="4 3"/>`;}
   if(t==='addgen'){s+=`<circle cx="${px}" cy="${py}" r="15" fill="#fff" stroke="#1f3b73" stroke-width="2.2"/><path d="M${px-8} ${py} c2.7-6 5.3-6 8 0" fill="none" stroke="#1f3b73" stroke-width="1.6"/>`;}
   else if(t==='addload'){s+=`<path d="M${px} ${py-9} L${px} ${py+5} M${px-6} ${py-1} L${px} ${py+7} L${px+6} ${py-1}" fill="none" stroke="#4b5563" stroke-width="2"/>`;}
   else if(t==='addcap'){s+=`<path d="M${px-9} ${py-4} h18 M${px-9} ${py+4} h18 M${px} ${py-10} v6 M${px} ${py+4} v6" stroke="#117a8b" stroke-width="2" fill="none"/>`;}
   else if(t==='addreact'){s+=`<path d="M${px-8} ${py+4} a8 8 0 0 1 16 0" fill="none" stroke="#a04000" stroke-width="2"/><path d="M${px} ${py-8} v4 M${px} ${py+4} v6" stroke="#a04000" stroke-width="2"/>`;}}
  s+=`<circle cx="${px}" cy="${py}" r="2.4" fill="#e67e22"/></g>`;}   // exact drop point
 if(typeof PMUV!=='undefined'&&PMUV&&PMUV.p){
  // PMU placement overlay: a compact synchrophasor beacon (dot + three signal
  // arcs) hugging the bus bar -- no enclosing rings, no filled badge.  The
  // "PMU" caption is dark, white-haloed, and placed by the collision-free
  // label engine so it stays legible on dense diagrams and heat maps.
  for(const p of PMUV.p){const b=NET.buses[p-1];if(!b)continue;
   const px=b.rot?b.x:(b.x-BARL+5), py=b.rot?(b.y-BARL-7):(b.y-10);
   const arc=r=>`M${(px-r*0.72).toFixed(1)} ${(py-3-r*0.72).toFixed(1)} a${r} ${r} 0 0 1 ${(r*1.44).toFixed(1)} 0 `;
   const arcs=arc(6)+arc(10.5)+arc(15);
   s+=`<g pointer-events="none">`+
      `<path d="${arcs}" fill="none" stroke="#fff" stroke-width="4.6" stroke-linecap="round" opacity=".9"/>`+
      `<path d="${arcs}" fill="none" stroke="#d92d20" stroke-width="2.1" stroke-linecap="round"/>`+
      `<circle cx="${px}" cy="${py}" r="4.2" fill="#fff" stroke="#d92d20" stroke-width="1.2"/>`+
      `<circle cx="${px}" cy="${py}" r="2.7" fill="#d92d20" stroke="#fff" stroke-width="1"/></g>`;
   if(LBL)lbReq(2,px,py-20,'PMU',{size:9.5,fill:'#d92d20',weight:700,anchor:'middle',halo:1,
     cands:[[0,-9],[16,26,'start'],[-16,26,'end'],[0,36]]});
   else s+=`<text x="${px}" y="${py-20}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d92d20" stroke="#fff" stroke-width="3" paint-order="stroke" stroke-linejoin="round">PMU</text>`;}}
 svg.setAttribute('viewBox',VB.join(' '));
 svg.innerHTML=defs+s+(LBL?lbPlace():'');zPct();if(!FAST)mmDraw();}
function hitEl(e){const el=e.target.closest('[data-el]');return el?{t:el.dataset.el,i:+el.dataset.i}:null;}
// Touch long-press entry point: select a component and open its editor directly.
// A machine opens its full parameter modal; every other element selects and
// reveals the Properties panel so its values/options can be edited on a phone.
function mobileEdit(t,i){
 if(!NET)return;
 DSEL={t,i};MSEL=[];try{prop();draw();}catch(_){}
 if(t==='gen'){try{openPar(i);}catch(_){}}
 else{try{pnShow('props');}catch(_){}}
 try{stat('long-press — editing '+(t==='br'?'branch':t==='facts'?'FACTS device':t)+' '+(i+1));}catch(_){}}
function sldTipHTML(hit){if(!NET)return '';const kv=(k,v)=>`<span class="k">${k}</span> ${v}<br>`;
 if(hit.t==='bus'&&NET.buses[hit.i]){const b=NET.buses[hit.i],i=hit.i;
  let s=`<b>Bus ${i+1}${b.name?' · '+rexEsc(b.name):''}</b><br>`+kv('type',b.type.toUpperCase());
  if(DPF&&DPF.V)s+=kv('|V|',DPF.V[i].toFixed(4)+' pu ∠ '+DPF.th[i].toFixed(1)+'°');
  if(b.Pd||b.Qd)s+=kv('load',b.Pd+' + j'+b.Qd+' MVA');
  if(b.Bs)s+=kv('shunt',b.Bs+' MVAr');return s;}
 if(hit.t==='gen'&&NET.gens[hit.i]){const g=NET.gens[hit.i],i=hit.i;
  let s=`<b>${/^SG/.test(g.tag)?'Generator':'IBR'} @ bus ${g.bus}</b><br>`+kv('tech',g.tag)+kv('P set',g.Pg+' MW');
  if(DPF&&DPF.Pg&&DPF.Pg[i]!==undefined)s+=kv('solved',DPF.Pg[i]+' + j'+DPF.Qg[i]+' MVA');
  return s+kv('rating',g.S+' MVA');}
 if(hit.t==='facts'&&NET.facts&&NET.facts[hit.i]){const d=NET.facts[hit.i],T=String(d.type).toUpperCase();
  if(T==='TCSC'||T==='TSSC'||T==='SSSC'){
   let s=`<b>${d.type} · line ${d.f}→${d.t}</b><br>`+kv('compensation',Math.round((d.kcomp||0)*100)+'%');
   if(DPF&&DPF.facts){const fr=DPF.facts.find(z=>z.kind==='series'&&z.f===d.f&&z.t===d.t&&String(z.type).toUpperCase()===T);
    if(fr){s+=kv('Xc',fr.Xc+' pu');s+=kv('Vse',fr.Vse+' pu'+(fr.sat?' (limit)':''));s+=kv('line P',fr.Pline+' MW');}}
   return s+kv('effect','x_eff = x·(1−kcomp)');}
  if(T==='UPFC'){
   let s=`<b>UPFC · bus ${d.bus} + line ${d.f}→${d.t}</b><br>`+kv('shunt','holds V='+d.Vref+' pu')+kv('series',Math.round((d.kcomp||0)*100)+'% comp');
   if(DPF&&DPF.facts){const sh=DPF.facts.find(z=>z.kind==='shunt'&&z.ptype==='UPFC'&&z.bus===d.bus),
     se=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='UPFC'&&z.f===d.f&&z.t===d.t);
    if(sh)s+=kv('shunt Q',(sh.Q>=0?'+':'')+sh.Q+' MVAr'+(sh.sat?' (limit)':''));
    if(se)s+=kv('line P',se.Pline+' MW'+(se.sat?' (Vse limit)':''));}
   return s+kv('note','shunt (V) + series (flow), DC-coupled');}
  if(T==='IPFC'){
   let s=`<b>IPFC · line ${d.f}→${d.t}${d.f2&&d.t2?' & '+d.f2+'→'+d.t2:''}</b><br>`+kv('conv 1',Math.round((d.kcomp||0)*100)+'% comp');
   if(d.f2&&d.t2)s+=kv('conv 2',Math.round((d.kcomp2||0)*100)+'% comp'); else s+=kv('conv 2','— set line 2 in Properties');
   if(DPF&&DPF.facts){const s1=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='IPFC'&&z.f===d.f&&z.t===d.t);
    if(s1)s+=kv('line 1 P',s1.Pline+' MW');
    if(d.f2&&d.t2){const s2=DPF.facts.find(z=>z.kind==='series'&&z.ptype==='IPFC'&&z.f===d.f2&&z.t===d.t2);if(s2)s+=kv('line 2 P',s2.Pline+' MW');}}
   return s+kv('note','two series converters, DC-coupled');}
  const isS=T==='SVC';
  let s=`<b>${d.type} @ bus ${d.bus}</b><br>`+kv('regulates',d.Vref+' pu');
  s+=isS?kv('range','B ['+d.Bmin+', '+d.Bmax+'] pu'):kv('range','I ['+d.Imin+', '+d.Imax+'] pu');
  if(DPF&&DPF.facts){const fr=DPF.facts.find(z=>z.bus===d.bus&&String(z.type).toUpperCase()===String(d.type).toUpperCase());
   if(fr){s+=kv('output',(fr.Q>=0?'+':'')+fr.Q+' MVAr'+(fr.sat?' (at limit)':''));s+=kv('bus |V|',fr.V+' pu');}}
  return s+kv('signal',d.signal==='Q'?'reactive power':'local bus |V|');}
 if(hit.t==='br'&&NET.branches[hit.i]){const br=NET.branches[hit.i],i=hit.i;
  let s=`<b>${rexIsXfmr(br)?'Transformer':'Line'} ${br.f} → ${br.t}</b><br>`+kv('R+jX',br.r+' + j'+br.x+' pu');
  if(br.b)s+=kv('B',br.b+' pu'); if(br.tap)s+=kv('tap',br.tap);
  const fl=(DPF&&DPF.flows)?DPF.flows[i]:null;
  if(fl){s+=kv('flow',Math.abs(fl.Pf).toFixed(1)+' MW · '+fl.Qf+' MVAr')+kv('loss',fl.loss+' MW');
   if(br.rate>0)s+=kv('loading',(100*Math.hypot(fl.Pf,fl.Qf)/br.rate).toFixed(0)+'%');}
  return s;}
 return '';}
function sldTip(e){const tp=$('sldTip');if(!tp)return;
 if(DDRAG||PNEW||LOCKED){tp.style.display='none';return;}
 const hit=hitEl(e); const html=hit?sldTipHTML(hit):''; if(!html){tp.style.display='none';return;}
 tp.innerHTML=html; tp.style.display='block';
 const sc=UIS||1, r=$('cwrap').getBoundingClientRect();
 let x=(e.clientX-r.left)/sc+15, y=(e.clientY-r.top)/sc+16, W=r.width/sc, H=r.height/sc;
 if(x+tp.offsetWidth>W)x=(e.clientX-r.left)/sc-tp.offsetWidth-15;
 if(y+tp.offsetHeight>H)y=(e.clientY-r.top)/sc-tp.offsetHeight-16;
 tp.style.left=Math.max(2,x)+'px'; tp.style.top=Math.max(2,y)+'px';}
function sldDown(e){
 e.preventDefault();                        // no text selection / native drags
 flyClose();                                // clicking the canvas closes fly-out panels
 if(e.button===1){DDRAG={t:'pan',x:e.clientX,y:e.clientY,vb:[...VB]};
  $('sld').style.cursor='grabbing';return;} // middle mouse button = pan
 if(e.button!==0)return;
 if(!NET&&DTOOL!=='addbus')return;
 if(LOCKED&&DTOOL!=='select'){stat('layout is locked — Unlock Layout (K) to edit');return;}
 const [wx,wy]=s2w(e),hit=NET?hitEl(e):null;
 if(DTOOL==='select'){
  if(LOCKED){                               // locked: click-select, box-select, pan
   if(hit){DSEL=hit;MSEL=[];prop();draw();}
   else{DSEL=null;prop();
    if(e.shiftKey)DDRAG={t:'marq',x0:wx,y0:wy,x1:wx,y1:wy};
    else{MSEL=[];DDRAG={t:'pan',x:e.clientX,y:e.clientY,vb:[...VB]};$('sld').style.cursor='grabbing';}
    draw();}
   return;}
  if(hit&&(hit.t==='bus'||hit.t==='gen')&&inMsel(hit)){          // drag the whole selection
   DSEL=hit;prop();pushU(true);
   const bset=new Set(MSEL.filter(m=>m.t==='bus').map(m=>m.i));
   DDRAG={t:'group',sx:wx,sy:wy,moved:false,
    bpos:[...bset].map(i=>({i,x:NET.buses[i].x,y:NET.buses[i].y})),
    gpos:NET.gens.map((g,i)=>({i,x:g.x,y:g.y,go:bset.has(g.bus-1)||MSEL.some(m=>m.t==='gen'&&m.i===i)}))};
   draw();}
  else if(hit){DSEL=hit;MSEL=[];prop();
   if(hit.t==='bus'){pushU(true);const b=NET.buses[hit.i];DDRAG={t:'bus',i:hit.i,dx:b.x-wx,dy:b.y-wy,moved:false};}
   else if(hit.t==='gen'){pushU(true);const g=NET.gens[hit.i];DDRAG={t:'gen',i:hit.i,dx:g.x-wx,dy:g.y-wy,moved:false};}
   else if(hit.t==='facts'){pushU(true);const d=NET.facts[hit.i];DDRAG={t:'facts',i:hit.i,dx:d.x-wx,dy:d.y-wy,moved:false};}
   else if(hit.t==='note'){pushU(true);const nt=NET.notes[hit.i];DDRAG={t:'note',i:hit.i,dx:nt.x-wx,dy:nt.y-wy,moved:false};}
   else if(hit.t==='br'&&VOPT.ortho&&BRAX[hit.i]){pushU(true);
    DDRAG={t:'brc',i:hit.i,wx,wy,co0:NET.branches[hit.i].co||0,axis:BRAX[hit.i],moved:false};}
   draw();}
  else{DSEL=null;prop();
   if(e.shiftKey)DDRAG={t:'marq',x0:wx,y0:wy,x1:wx,y1:wy};
   else{MSEL=[];DDRAG={t:'pan',x:e.clientX,y:e.clientY,vb:[...VB]};$('sld').style.cursor='grabbing';}
   draw();}
 }else if(DTOOL==='addline'||DTOOL==='adddbl'||DTOOL==='addxfmr'){
   const bi=hit&&hit.t==='bus'?hit.i:busAt(wx,wy);
   if(bi>=0){
    if(DPEND==null){DPEND=bi;DDRAG={t:'newline',from:bi,cx:wx,cy:wy,moved:false};
     stat('drag to the second bus — or click it');}
    else if(DPEND!==bi){addBranchTool(DPEND,bi);}
    draw();}
 }else if(DNODE.includes(DTOOL)){
   placeNode(DTOOL,wx,wy);
 }else if(DTOOL==='addtcsc'||DTOOL==='addtssc'||DTOOL==='addsssc'){
   const bi=hit&&hit.t==='br'?hit.i:-1;
   if(bi>=0)placeSeries(DTOOL,bi); else stat('click on a line to place the series FACTS device');
 }else if(DTOOL==='addupfc'||DTOOL==='addipfc'){
   const bi=hit&&hit.t==='br'?hit.i:-1;
   if(bi>=0)placeCombined(DTOOL,bi); else stat('click on a line to place the '+(DTOOL==='addupfc'?'UPFC (shunt + series)':'IPFC (set line 2 in Properties)'));
 }else if(DTOOL==='delete'&&hit){
  pushU();delOne(hit.t,hit.i);
  DSEL=null;MSEL=[];edited();prop();draw();syncSide();}}
// nearest bus bar to a world point (for drop-on-bus + bus-to-bus line drawing)
function busAt(wx,wy,tol){if(!NET||!NET.buses)return -1;tol=tol||30;
 let best=-1,bd=tol*tol;
 for(let i=0;i<NET.buses.length;i++){const b=NET.buses[i];let dx,dy;
  if(b.rot){dx=wx-b.x;dy=Math.max(0,Math.abs(wy-b.y)-BARL);}
  else{dx=Math.max(0,Math.abs(wx-b.x)-BARL);dy=wy-b.y;}
  const d2=dx*dx+dy*dy;if(d2<bd){bd=d2;best=i;}}
 return best;}
function addBranchTool(fromI,toI){pushU();
 if(DTOOL==='addxfmr')NET.branches.push({f:fromI+1,t:toI+1,r:0.002,x:0.06,b:0,tap:1.0,xf:1});
 else{NET.branches.push({f:fromI+1,t:toI+1,r:0.005,x:0.05,b:0.02,tap:0});
  if(DTOOL==='adddbl')NET.branches.push({f:fromI+1,t:toI+1,r:0.005,x:0.05,b:0.02,tap:0});}
 DSEL={t:'br',i:NET.branches.length-1};DPEND=null;edited();prop();draw();
 stat(DTOOL==='addxfmr'?'transformer added':DTOOL==='adddbl'?'double-circuit line added':'line added');}
// ---- drag-and-drop a component straight from the palette onto the canvas ----
let PNEW=null;
const DNODE=['addbus','addgen','addload','addcap','addreact','addsvc','addstatcom','addnote'];   // drop at a point / on a bus
const DEDGE=['addline','adddbl','addxfmr'];                                 // connect two buses
const NEWICO={addbus:'i-bus',addgen:'i-gen',addload:'i-load',addcap:'i-cap',addreact:'i-react',addnote:'i-note'};
const NEWLBL={addbus:'Bus',addgen:'Generator',addload:'Load',addcap:'Capacitor',addreact:'Reactor',
 addsvc:'SVC',addstatcom:'STATCOM',addnote:'Annotation',
 addline:'Line',adddbl:'Double line',addxfmr:'Transformer'};
function overCanvas(e){const r=$('sld').getBoundingClientRect();
 return e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom;}
// place a node-type component at a world point (used by click AND drag-drop)
function placeNode(tool,wx,wy){if(!NET)newNet();
 if(tool==='addbus'){pushU();
  NET.buses.push({x:snapv(wx),y:snapv(wy),type:NET.buses.length===0?'slack':'pq',Vset:1.0,Pd:0,Qd:0,Bs:0});
  edited();DSEL={t:'bus',i:NET.buses.length-1};MSEL=[];prop();draw();stat('bus added');return true;}
 if(tool==='addnote'){pushU();if(!NET.notes)NET.notes=[];
  NET.notes.push({x:snapv(wx),y:snapv(wy),text:'text',size:14});
  edited();DSEL={t:'note',i:NET.notes.length-1};MSEL=[];prop();draw();stat('annotation added — type your text in Properties');return true;}
 const bi=busAt(wx,wy);
 if(bi<0){stat('drop '+tool.replace('add','')+' onto a bus bar');return false;}
 const b=NET.buses[bi];pushU();
 if(tool==='addgen'){NET.gens.push({bus:bi+1,tag:'SG',Pg:100,Vset:b.Vset||1.0,S:120,md:null,
   x:b.rot?b.x-64:b.x,y:b.rot?b.y:b.y-64});
  if(b.type==='pq')b.type='pv';DSEL={t:'gen',i:NET.gens.length-1};stat('generator added at bus '+(bi+1));}
 else if(tool==='addload'){if((b.Pd||0)===0&&(b.Qd||0)===0){b.Pd=50;b.Qd=20;}
  if(b.type!=='slack'&&!NET.gens.some(g=>g.bus===bi+1))b.type='pq';DSEL={t:'bus',i:bi};stat('load added at bus '+(bi+1));}
 else if(tool==='addcap'){b.Bs=(+b.Bs||0)+30;DSEL={t:'bus',i:bi};stat('shunt capacitor +30 MVAr at bus '+(bi+1));}
 else if(tool==='addreact'){b.Bs=(+b.Bs||0)-30;DSEL={t:'bus',i:bi};stat('shunt reactor −30 MVAr at bus '+(bi+1));}
 else if(tool==='addsvc'||tool==='addstatcom'){if(!NET.facts)NET.facts=[];
  const typ=tool==='addsvc'?'SVC':'STATCOM';
  NET.facts.push({type:typ,bus:bi+1,Vref:(+b.Vset||1.0),Bmax:2,Bmin:-2,Imax:2,Imin:-2,
   Kr:20,Tr:0.05,droop:0,signal:'V',rbus:0,x:b.rot?b.x-64:b.x,y:b.rot?b.y:b.y+64});
  DSEL={t:'facts',i:NET.facts.length-1};stat(typ+' added at bus '+(bi+1)+' — regulates V='+(+b.Vset||1.0)+' pu');}
 MSEL=[];edited();prop();draw();syncSide();return true;}
// place a SERIES FACTS device (TCSC/TSSC/SSSC) on a line, at its midpoint
function placeSeries(tool,bi){if(!NET||!NET.branches[bi])return;
 const br=NET.branches[bi],A=NET.buses[br.f-1],B=NET.buses[br.t-1];if(!A||!B)return;
 if(!NET.facts)NET.facts=[];pushU();
 const typ={addtcsc:'TCSC',addtssc:'TSSC',addsssc:'SSSC'}[tool];
 NET.facts.push({type:typ,f:br.f,t:br.t,kcomp:0.4,kmin:-0.2,kmax:0.7,Tc:0.02,Vsemax:0.2,
  mode:'const',x:Math.round((A.x+B.x)/2),y:Math.round((A.y+B.y)/2)});
 DSEL={t:'facts',i:NET.facts.length-1};MSEL=[];edited();prop();draw();
 stat(typ+' added on line '+br.f+'-'+br.t+' — 40% series compensation');}
// place a COMBINED FACTS device (UPFC / IPFC) by clicking a line.  A UPFC drops a
// shunt converter at the line's sending bus and a series converter on the line;
// an IPFC drops the first series converter here (the second line is set in the
// editor).  Both are single NET.facts entries that expand_combined() unfolds into
// the verified STATCOM/SSSC primitives for the engine.
function placeCombined(tool,bi){if(!NET||!NET.branches[bi])return;
 const br=NET.branches[bi],A=NET.buses[br.f-1],B=NET.buses[br.t-1];if(!A||!B)return;
 if(!NET.facts)NET.facts=[];pushU();
 const mx=Math.round((A.x+B.x)/2),my=Math.round((A.y+B.y)/2);
 if(tool==='addupfc'){const sb=NET.buses[br.f-1];
  NET.facts.push({type:'UPFC',bus:br.f,f:br.f,t:br.t,Vref:(+sb.Vset||1.0),Imax:2,Imin:-2,
   kcomp:0.3,kmin:-0.2,kmax:0.7,Vsemax:0.2,Kr:20,Tr:0.05,Kaw:150,droop:0,
   x:(sb.rot?sb.x-64:sb.x),y:(sb.rot?sb.y:sb.y+64)});
  stat('UPFC added — shunt at bus '+br.f+' (holds V='+(+sb.Vset||1.0)+' pu) + series on line '+br.f+'-'+br.t);}
 else{                                            // IPFC — line 1 here, line 2 in Properties
  NET.facts.push({type:'IPFC',f:br.f,t:br.t,f2:0,t2:0,kcomp:0.3,kcomp2:0.2,
   kmin:-0.2,kmax:0.7,Vsemax:0.2,x:mx,y:my});
  stat('IPFC added on line '+br.f+'-'+br.t+' — pick the second line in Properties');}
 DSEL={t:'facts',i:NET.facts.length-1};MSEL=[];edited();prop();draw();}
function sldMove(e){if(!DDRAG)return;
 if(DDRAG.t==='pan'){const sc=svgScale();
  VB[0]=DDRAG.vb[0]-(e.clientX-DDRAG.x)/sc;
  VB[1]=DDRAG.vb[1]-(e.clientY-DDRAG.y)/sc;qdraw();return;}
 const [wx,wy]=s2w(e);
 if(DDRAG.t==='marq'){DDRAG.x1=wx;DDRAG.y1=wy;qdraw();return;}
 if(DDRAG.t==='newline'){DDRAG.cx=wx;DDRAG.cy=wy;
  if(!DDRAG.moved&&Math.hypot(wx-NET.buses[DDRAG.from].x,wy-NET.buses[DDRAG.from].y)>14)DDRAG.moved=true;
  qdraw();return;}
 if(DDRAG.t==='brc'){const br=NET.branches[DDRAG.i];
  const d=DDRAG.axis==='y'?wy-DDRAG.wy:wx-DDRAG.wx;
  if(Math.abs(d)>2&&!DDRAG.moved){DDRAG.moved=true;URD=[];}
  br.co=Math.round(DDRAG.co0+d);
  if(Math.abs(br.co)<3)delete br.co;
  qdraw();return;}
 if(DDRAG.t==='group'){
  const dx=snapv(wx-DDRAG.sx),dy=snapv(wy-DDRAG.sy);
  if((dx||dy)&&!DDRAG.moved){DDRAG.moved=true;URD=[];}
  DDRAG.bpos.forEach(p=>{NET.buses[p.i].x=p.x+dx;NET.buses[p.i].y=p.y+dy;});
  DDRAG.gpos.forEach(p=>{if(p.go){NET.gens[p.i].x=p.x+dx;NET.gens[p.i].y=p.y+dy;}});
  qdraw();return;}
 if(DDRAG.t==='bus'){const b=NET.buses[DDRAG.i],nx=snapv(wx+DDRAG.dx),ny=snapv(wy+DDRAG.dy);
  if((nx!==b.x||ny!==b.y)&&!DDRAG.moved){DDRAG.moved=true;URD=[];}
  const odx=nx-b.x,ody=ny-b.y;b.x=nx;b.y=ny;
  NET.gens.forEach(g=>{if(g.bus===DDRAG.i+1){g.x+=odx;g.y+=ody;}});
  if(NET.facts)NET.facts.forEach(d=>{if(d.bus===DDRAG.i+1){d.x+=odx;d.y+=ody;}});}
 if(DDRAG.t==='gen'){const g=NET.gens[DDRAG.i],nx=snapv(wx+DDRAG.dx),ny=snapv(wy+DDRAG.dy);
  if((nx!==g.x||ny!==g.y)&&!DDRAG.moved){DDRAG.moved=true;URD=[];}g.x=nx;g.y=ny;}
 if(DDRAG.t==='facts'&&NET.facts){const d=NET.facts[DDRAG.i],nx=snapv(wx+DDRAG.dx),ny=snapv(wy+DDRAG.dy);
  if((nx!==d.x||ny!==d.y)&&!DDRAG.moved){DDRAG.moved=true;URD=[];}d.x=nx;d.y=ny;}
 if(DDRAG.t==='note'){const nt=NET.notes[DDRAG.i],nx=snapv(wx+DDRAG.dx),ny=snapv(wy+DDRAG.dy);
  if((nx!==nt.x||ny!==nt.y)&&!DDRAG.moved){DDRAG.moved=true;URD=[];}nt.x=nx;nt.y=ny;}
 qdraw();}
function sldUp(){if(!DDRAG)return;
 if(DDRAG.t==='marq'){
  const x0=Math.min(DDRAG.x0,DDRAG.x1),x1=Math.max(DDRAG.x0,DDRAG.x1);
  const y0=Math.min(DDRAG.y0,DDRAG.y1),y1=Math.max(DDRAG.y0,DDRAG.y1);
  MSEL=[];
  NET.buses.forEach((b,i)=>{if(b.x>=x0&&b.x<=x1&&b.y>=y0&&b.y<=y1)MSEL.push({t:'bus',i});});
  NET.gens.forEach((g,i)=>{if(g.x>=x0&&g.x<=x1&&g.y>=y0&&g.y<=y1)MSEL.push({t:'gen',i});});
  if(MSEL.length===1){DSEL=MSEL[0];prop();}
  DDRAG=null;draw();return;}
 if(DDRAG.t==='newline'){                  // bus-to-bus drag: complete on release
  if(DDRAG.moved){const to=busAt(DDRAG.cx,DDRAG.cy);
   if(to>=0&&to!==DDRAG.from)addBranchTool(DDRAG.from,to);
   else{DPEND=null;stat('line cancelled — release on a different bus');}}
  DDRAG=null;draw();return;}   // not moved: leave DPEND set for click-click
 if((DDRAG.t==='bus'||DDRAG.t==='gen'||DDRAG.t==='note'||DDRAG.t==='group'||DDRAG.t==='brc')&&!DDRAG.moved)UST.pop();
 if(DDRAG.t==='pan')$('sld').style.cursor=DTOOL==='select'?'default':'crosshair';
 DDRAG=null;draw();}
function sldKey(e){
 if(e.key==='F11'){e.preventDefault();fsToggle();return;}
 if(e.ctrlKey||e.metaKey){
  if(e.key==='='||e.key==='+'){e.preventDefault();applyUI(UIS+0.05,true);return;}
  if(e.key==='-'){e.preventDefault();applyUI(UIS-0.05,true);return;}
  if(e.key==='0'){e.preventDefault();applyUI(1,true);return;}}
 if(e.key==='Escape'){
  const kb=$('kbd');
  if(kb&&kb.style.display!=='none'){kb.style.display='none';return;}
  if(document.body.classList.contains('fs')){fsToggle();return;}
  if(DPEND!=null){DPEND=null;draw();return;}
  if(DDRAG&&DDRAG.t==='marq'){DDRAG=null;draw();return;}
  return;}
 const tabnet=$('tab-net');if(!tabnet||tabnet.style.display==='none')return;
 const tg=e.target.tagName;if(tg==='INPUT'||tg==='SELECT'||tg==='TEXTAREA')return;
 if($('modal')&&$('modal').style.display==='flex')return;
 const k=e.key.toLowerCase();
 if(e.ctrlKey||e.metaKey){
  if(k==='z'&&e.shiftKey){e.preventDefault();redo();}
  else if(k==='z'){e.preventDefault();undo();}
  else if(k==='y'){e.preventDefault();redo();}
  else if(k==='a'){e.preventDefault();selectAll();}
  return;}
 if(k==='v')setTool('select');else if(k==='b')setTool('addbus');
 else if(k==='l')setTool('addline');else if(k==='g')setTool('addgen');
 else if(k==='x')setTool('delete');
 else if(k==='r')rotSel();else if(k==='f')flipSel();else if(k==='a')fitView();
 else if(k==='s')zoomSel();else if(k==='t')tidyLayout();
 else if(k==='o')tgl('ortho');else if(k==='m')mmToggle();
 else if(k==='k')setLock(!LOCKED);
 else if(k==='+'||k==='=')zoomBtn(1.25);else if(k==='-')zoomBtn(0.8);
 else if(k==='delete'||k==='backspace'){e.preventDefault();delSel();}
 else if(k.startsWith('arrow')){e.preventDefault();nudge(k);}}
let WACC=1,WCX=0,WCY=0,WRAF=0;
function sldWheel(e){e.preventDefault();          // smooth: coalesce wheel ticks
 WACC*=e.deltaY>0?1.11:1/1.11;WCX=e.clientX;WCY=e.clientY;
 WHEELUNTIL=_now()+140;                           // fast path while spinning
 if(!WRAF)WRAF=requestAnimationFrame(()=>{WRAF=0;
  const [wx,wy]=s2w({clientX:WCX,clientY:WCY}),f=WACC;WACC=1;
  VB=[wx-(wx-VB[0])*f, wy-(wy-VB[1])*f, VB[2]*f, VB[3]*f];draw();});
 clearTimeout(WHEELTO);                            // one full-quality redraw when it stops
 WHEELTO=setTimeout(()=>{WHEELUNTIL=0;draw();},150);}
const PBTNS=`<div style="display:flex;gap:5px;margin-top:8px">
   <button class="tbtn" style="flex:1" onclick="rotSel()" title="rotate (R)">↻ rotate</button>
   <button class="tbtn" style="flex:1" onclick="flipSel()" title="flip (F)">⇋ flip</button>
   <button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>`;
// ---- supplementary controller (POD / wide-area damping) editor, shared by the
// shunt (SVC/STATCOM) and UPFC editors.  A washout + lead-lag + gain damping loop
// on a selectable LOCAL or REMOTE (WAMS) feedback signal, modulating the device
// reference.  Same block the small-signal POD-design tool tunes.
const POD_DEF={on:false,sig:'Vbus',rbus:0,f:0,t:0,i:0,j:0,tau:0,Tw:10,T1:0.30,T2:0.05,nc:2,K:0,lo:-0.10,hi:0.10};
function podEditorHTML(d){
 const p=Object.assign({},POD_DEF,d.pod||{});
 const sig=p.sig||'Vbus';
 const opts=[['Vbus','bus |V| (local / remote)'],['Pline','line P (tie-line power)'],['Qline','line Q (reactive flow)'],
   ['Iline','line current'],['adiff','bus-angle difference'],['wgen','rotor speed / frequency'],['angle','bus angle (PMU phase)']]
   .map(o=>`<option value="${o[0]}"${sig===o[0]?' selected':''}>${o[1]}</option>`).join('');
 let tgt;
 if(sig==='Pline'||sig==='Qline'||sig==='Iline')
  tgt=`<div class="pprow"><span>line f → t</span><div style="display:flex;gap:5px"><input id="pp_pod_f" type="number" step="1" value="${p.f||0}" title="from bus"><input id="pp_pod_t" type="number" step="1" value="${p.t||0}" title="to bus"></div></div>`;
 else if(sig==='adiff')
  tgt=`<div class="pprow"><span>buses i, j</span><div style="display:flex;gap:5px"><input id="pp_pod_i" type="number" step="1" value="${p.i||0}" title="θi − θj"><input id="pp_pod_j" type="number" step="1" value="${p.j||0}"></div></div>`;
 else
  tgt=`<div class="pprow"><span>measured bus</span><input id="pp_pod_rbus" type="number" step="1" value="${p.rbus||0}" title="remote/local bus (0 = the device's own bus)"></div>`;
 return `<div class="psub" style="margin:8px 0 2px">supplementary controller — POD / wide-area damping</div>
  <div class="pprow"><span>enable</span><input id="pp_pod_on" type="checkbox" ${p.on?'checked':''} onchange="applyProp()" style="width:auto;justify-self:start" title="add a washout + lead-lag damping loop that modulates the reference"></div>
  <div class="pprow"><span>input signal</span><select id="pp_pod_sig" onchange="applyProp()"${p.on?'':' disabled'}>${opts}</select></div>`
  + (p.on?`${tgt}
  <div class="pprow"><span>delay τ (s)</span><input id="pp_pod_tau" type="number" step="0.01" value="${p.tau||0}" title="WAMS/PMU measurement latency (0 = none)"></div>
  <div class="pprow"><span>washout Tw</span><input id="pp_pod_tw" type="number" step="0.5" value="${p.Tw}" title="washout time constant (removes the DC component)"></div>
  <div class="pprow"><span>lead T1 / lag T2</span><div style="display:flex;gap:5px"><input id="pp_pod_t1" type="number" step="0.01" value="${p.T1}"><input id="pp_pod_t2" type="number" step="0.01" value="${p.T2}"></div></div>
  <div class="pprow"><span>stages nc</span><input id="pp_pod_nc" type="number" step="1" min="0" max="4" value="${p.nc}" title="identical lead-lag stages"></div>
  <div class="pprow"><span>gain K</span><input id="pp_pod_k" type="number" step="0.1" value="${p.K}" title="damping-loop gain — sign sets the phase; tune with Analysis ▸ POD design"></div>
  <div class="pprow"><span>output ± limit</span><div style="display:flex;gap:5px"><input id="pp_pod_lo" type="number" step="0.01" value="${p.lo}"><input id="pp_pod_hi" type="number" step="0.01" value="${p.hi}"></div></div>
  <div class="note" style="margin-top:4px">Adds washout + ${p.nc}× lead-lag states; acts on the ${sig==='Vbus'?'measured bus voltage':sig==='Pline'?'line active power':sig==='Qline'?'line reactive power':sig==='Iline'?'line current':sig==='adiff'?'bus-angle difference':sig==='wgen'?'rotor speed (local frequency)':'bus angle'} and enters small-signal &amp; time-domain. A remote bus/line plus the delay τ is the WAMS/PMU channel.</div>`:'');}
function podApply(d){
 if(!$('pp_pod_on'))return;
 const p=Object.assign({},POD_DEF,d.pod||{});
 p.on=$('pp_pod_on').checked;
 if($('pp_pod_sig'))p.sig=$('pp_pod_sig').value;
 if($('pp_pod_rbus'))p.rbus=Math.round(+$('pp_pod_rbus').value)||0;
 if($('pp_pod_f'))p.f=Math.round(+$('pp_pod_f').value)||0;
 if($('pp_pod_t'))p.t=Math.round(+$('pp_pod_t').value)||0;
 if($('pp_pod_i'))p.i=Math.round(+$('pp_pod_i').value)||0;
 if($('pp_pod_j'))p.j=Math.round(+$('pp_pod_j').value)||0;
 if($('pp_pod_tau'))p.tau=Math.max(0,+$('pp_pod_tau').value||0);
 if($('pp_pod_tw'))p.Tw=+$('pp_pod_tw').value||10;
 if($('pp_pod_t1'))p.T1=+$('pp_pod_t1').value||0.30;
 if($('pp_pod_t2'))p.T2=+$('pp_pod_t2').value||0.05;
 if($('pp_pod_nc'))p.nc=Math.max(0,Math.min(4,Math.round(+$('pp_pod_nc').value)));
 if($('pp_pod_k'))p.K=+$('pp_pod_k').value||0;
 if($('pp_pod_lo'))p.lo=+$('pp_pod_lo').value;
 if($('pp_pod_hi'))p.hi=+$('pp_pod_hi').value;
 d.pod=p;}
function prop(){const pp=$('pp');
 if(MSEL.length>1&&NET){$('ppTitle').textContent='Selection';
  pp.innerHTML=`<b>${MSEL.filter(m=>m.t==='bus').length}</b> buses and <b>${MSEL.filter(m=>m.t==='gen').length}</b> generators selected.<br><br>
   drag any of them to move the group · arrow keys nudge · <b>Del</b> deletes all.
   <div style="display:flex;gap:5px;margin-top:8px">
   <button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()">✕ delete selection</button></div>`;return;}
 if(!DSEL||!NET){$('ppTitle').textContent='No selection';
  pp.innerHTML='<b>Drag</b> a component from the Draw palette onto the canvas — bus/generator/load/shunt/annotation. For a line, <b>drag from one bus to another</b>.<br><br>Then click any element to edit it here. Middle-drag (or drag empty space) to pan · wheel to zoom · <b>A</b> fit · <b>S</b> zoom to selection.<br>Shift-drag a box to select many; arrow keys nudge · <b>R</b> rotate · <b>F</b> flip · <b>Del</b> delete · Ctrl+Z undo.';return;}
 if(DSEL.t==='bus'){const b=NET.buses[DSEL.i];$('ppTitle').textContent=`Bus ${DSEL.i+1}`;
  pp.innerHTML=`<div class="pprow"><span>name</span><input id="pp_nm" type="text" value="${b.name||''}" placeholder="optional label"></div>
   <div class="pprow"><span>type</span><select id="pp_type">
    <option value="pq"${b.type==='pq'?' selected':''}>PQ (load)</option>
    <option value="pv"${b.type==='pv'?' selected':''}>PV (gen)</option>
    <option value="slack"${b.type==='slack'?' selected':''}>slack ⚓</option></select></div>
   <div class="pprow"><span>V set (pu)</span><input id="pp_vs" type="number" step="0.005" value="${b.Vset}"></div>
   <div class="pprow"><span>load P (MW)</span><input id="pp_pd" type="number" step="5" value="${b.Pd}"></div>
   <div class="pprow"><span>load Q (MVAr)</span><input id="pp_qd" type="number" step="5" value="${b.Qd}"></div>
   <div class="pprow"><span>shunt (MVAr)</span><input id="pp_bs" type="number" step="10" value="${b.Bs}"></div>
   <div class="psub" style="margin:8px 0 2px">layout</div>
   <div class="pprow"><span>orientation</span><select id="pp_or"><option value="0"${!b.rot?' selected':''}>horizontal ▬</option><option value="1"${b.rot?' selected':''}>vertical ▮</option></select></div>
   <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_bx" type="number" step="10" value="${Math.round(b.x)}" title="X"><input id="pp_by" type="number" step="10" value="${Math.round(b.y)}" title="Y"></div></div>
   <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>${PBTNS}`;}
 if(DSEL.t==='br'){const br=NET.branches[DSEL.i];$('ppTitle').textContent=`Line ${br.f} – ${br.t}`;
  pp.innerHTML=`<div class="pprow"><span>name</span><input id="pp_ln" type="text" value="${br.name||''}" placeholder="optional — for Line Names"></div>
   <div class="pprow"><span>r (pu)</span><input id="pp_r" type="number" step="0.001" value="${br.r}"></div>
   <div class="pprow"><span>x (pu)</span><input id="pp_x" type="number" step="0.005" value="${br.x}"></div>
   <div class="pprow"><span>b (pu)</span><input id="pp_b" type="number" step="0.01" value="${br.b}"></div>
   <div class="pprow"><span>tap</span><input id="pp_tap" type="number" step="0.01" value="${br.tap||0}" title="0 or 1 = no off-nominal ratio"></div>
   <div class="pprow"><span>transformer</span><input id="pp_xf" type="checkbox" ${br.xf?'checked':''} style="width:auto;justify-self:start" title="draw the two-winding transformer symbol"></div>
   <div class="pprow"><span>rating (MVA)</span><input id="pp_rt" type="number" step="10" value="${br.rate||0}" title="thermal rating for the ⚠ critical view; 0 = unrated"></div>
   <div class="pprow"><span>flow (solved)</span><input type="text" disabled value="${(DPF&&DPF.flows&&DPF.flows[DSEL.i])?(Math.abs(DPF.flows[DSEL.i].Pf).toFixed(0)+' MW · '+Math.abs(DPF.flows[DSEL.i].Qf).toFixed(0)+' MVAr'+(br.rate>0?' · '+Math.round(Math.hypot(DPF.flows[DSEL.i].Pf,DPF.flows[DSEL.i].Qf)/br.rate*100)+'%':'')):'run a power flow'}" title="active / reactive flow and loading from the last power flow"></div>
   <div class="pprow"><span>status</span><select id="pp_boff"><option value="0"${br.off?'':' selected'}>In service</option><option value="1"${br.off?' selected':''}>Out of service</option></select></div>
   <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
   <div style="display:flex;gap:5px;margin-top:8px">
   <button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
   <div class="note" style="margin-top:6px">drag the line itself to re-route its corridor where you want it (right-angle mode); parallel circuits draw side-by-side automatically.</div>`;}
 if(DSEL.t==='note'){const nt=NET.notes[DSEL.i];$('ppTitle').textContent='Annotation';
  pp.innerHTML=`<div class="pprow" style="grid-template-columns:1fr"><textarea id="pp_nt" rows="3" style="width:100%;padding:6px 8px;border:1px solid #cfd6e2;border-radius:3px;font:inherit;resize:vertical" placeholder="note text">${(nt.text||'').replace(/</g,'&lt;')}</textarea></div>
   <div class="pprow"><span>size</span><input id="pp_ns" type="number" step="1" min="7" max="48" value="${nt.size||14}"></div>
   <div class="pprow"><span>angle °</span><input id="pp_nr" type="number" step="15" value="${nt.rot||0}"></div>
   <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_nx" type="number" step="10" value="${Math.round(nt.x)}" title="X"><input id="pp_ny" type="number" step="10" value="${Math.round(nt.y)}" title="Y"></div></div>
   <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
   <div style="display:flex;gap:5px;margin-top:8px">
   <button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
   <div class="note" style="margin-top:6px">annotations are drawing decorations — they don't affect the power flow or any analysis.</div>`;}
 if(DSEL.t==='facts'&&NET.facts&&NET.facts[DSEL.i]){const d=NET.facts[DSEL.i],T=String(d.type).toUpperCase(),isS=T==='SVC';
  if(T==='TCSC'||T==='TSSC'||T==='SSSC'){
   $('ppTitle').textContent=`${d.type} · line ${d.f}–${d.t}`;
   pp.innerHTML=`<div class="note" style="margin-bottom:6px">${T==='SSSC'?'Static Synchronous Series Compensator — a VSC injecting a controllable series voltage (voltage-limited; effective even at low line current).':(T==='TCSC'?'Thyristor-Controlled Series Capacitor — continuously-variable series compensation.':'Thyristor-Switched Series Capacitor — series compensation switched in steps.')} Lowers the line reactance (x_eff = x·(1−kcomp)) to boost power transfer.</div>
    <div class="pprow"><span>comp kcomp</span><input id="pp_fkc" type="number" step="0.05" value="${d.kcomp}" title="series-compensation fraction (>0 = capacitive)"></div>
    <div class="pprow"><span>kmin</span><input id="pp_fkmn" type="number" step="0.05" value="${d.kmin!=null?d.kmin:-0.2}"></div>
    <div class="pprow"><span>kmax</span><input id="pp_fkmx" type="number" step="0.05" value="${d.kmax!=null?d.kmax:0.7}"></div>
    ${T==='SSSC'?`<div class="pprow"><span>Vse max (pu)</span><input id="pp_fvm" type="number" step="0.02" value="${d.Vsemax!=null?d.Vsemax:0.2}" title="max injected series voltage"></div>`:''}
    ${T!=='TSSC'?`<div class="pprow"><span>Tc (s)</span><input id="pp_ftc" type="number" step="0.01" value="${d.Tc!=null?d.Tc:0.05}" title="compensation response time (dynamic model, used when the POD is enabled)"></div>`:''}
    ${T!=='TSSC'?podEditorHTML(d):''}
    <div class="psub" style="margin:8px 0 2px">layout</div>
    <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_fx" type="number" step="10" value="${Math.round(d.x)}" title="X"><input id="pp_fy" type="number" step="10" value="${Math.round(d.y)}" title="Y"></div></div>
    <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
    <div style="display:flex;gap:5px;margin-top:8px"><button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
    <div class="note" style="margin-top:6px">Compensation reshapes the load flow and every analysis.${T!=='TSSC'?' Enabling the supplementary controller gives the compensation a dynamic state the POD modulates for damping — tune the gain/phase with Analysis ▸ POD design so no other mode is destabilized.':''}</div>`;
  }else if(T==='UPFC'){
   const pqm=String(d.mode||'').toLowerCase()==='pq';
   $('ppTitle').textContent=`UPFC · bus ${d.bus} + line ${d.f}–${d.t}`;
   pp.innerHTML=`<div class="note" style="margin-bottom:6px">Unified Power Flow Controller — a shunt converter at bus ${d.bus} (holds the voltage) + a series converter on line ${d.f}–${d.t}, DC-coupled so the series real power is supplied by the shunt.</div>
    <div class="pprow"><span>control mode</span><select id="pp_cmode" onchange="applyProp()" title="composition = STATCOM+SSSC (V + reactance); P-Q flow = independent line P and Q via the DC-coupled series source"><option value="comp"${pqm?'':' selected'}>composition (V + reactance)</option><option value="pq"${pqm?' selected':''}>P-Q flow control (DC-coupled)</option></select></div>
    <div class="psub" style="margin:8px 0 2px">shunt converter</div>
    <div class="pprow"><span>shunt bus</span><input id="pp_cbus" type="number" step="1" value="${d.bus}" title="bus the shunt converter regulates (defaults to the line's sending bus)"></div>
    <div class="pprow"><span>V ref (pu)</span><input id="pp_fvr" type="number" step="0.005" value="${d.Vref}" title="regulated voltage set-point"></div>
    <div class="pprow"><span>Imax (pu)</span><input id="pp_fhi" type="number" step="0.1" value="${d.Imax!=null?d.Imax:2}" title="max capacitive reactive current"></div>
    <div class="pprow"><span>Imin (pu)</span><input id="pp_flo" type="number" step="0.1" value="${d.Imin!=null?d.Imin:-2}" title="max inductive reactive current"></div>
    <div class="pprow"><span>gain Kr</span><input id="pp_fkr" type="number" step="1" value="${d.Kr!=null?d.Kr:20}"></div>
    <div class="pprow"><span>Tr (s)</span><input id="pp_ftr" type="number" step="0.01" value="${d.Tr!=null?d.Tr:0.05}"></div>
    <div class="pprow"><span>droop (pu)</span><input id="pp_fdr" type="number" step="0.005" value="${d.droop||0}"></div>
    <div class="psub" style="margin:8px 0 2px">series converter · line ${d.f}–${d.t}</div>
    ${pqm?`<div class="pprow"><span>P set (MW)</span><input id="pp_cps" type="number" step="5" value="${d.Pset!=null?d.Pset:50}" title="target active power delivered along the corridor"></div>
    <div class="pprow"><span>Q set (MVAr)</span><input id="pp_cqs" type="number" step="5" value="${d.Qset!=null?d.Qset:0}" title="target reactive power on the corridor (set independently of P)"></div>`
    :`<div class="pprow"><span>comp kcomp</span><input id="pp_fkc" type="number" step="0.05" value="${d.kcomp}" title="series-compensation fraction (>0 = capacitive, boosts transfer)"></div>
    <div class="pprow"><span>Vse max (pu)</span><input id="pp_fvm" type="number" step="0.02" value="${d.Vsemax!=null?d.Vsemax:0.2}" title="max injected series voltage"></div>`}
    ${podEditorHTML(d)}
    <div class="psub" style="margin:8px 0 2px">layout</div>
    <div class="pprow"><span>shunt pos</span><div style="display:flex;gap:5px"><input id="pp_fx" type="number" step="10" value="${Math.round(d.x)}" title="X"><input id="pp_fy" type="number" step="10" value="${Math.round(d.y)}" title="Y"></div></div>
    <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
    <div style="display:flex;gap:5px;margin-top:8px"><button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
    <div class="note" style="margin-top:6px">Composed from the verified STATCOM + SSSC primitives, so it enters power flow, small-signal and time-domain. Common-DC-link real-power coupling (independent P–Q control) is the next combined-device refinement.</div>`;
  }else if(T==='IPFC'){
   const pqm=String(d.mode||'').toLowerCase()==='pq';
   $('ppTitle').textContent=`IPFC · line ${d.f}–${d.t}${d.f2&&d.t2?` & ${d.f2}–${d.t2}`:''}`;
   const l2opts=`<option value="-1">— none —</option>`+(NET.branches||[]).map((b,bi)=>`<option value="${bi}"${(d.f2===b.f&&d.t2===b.t)?' selected':''}${(b.f===d.f&&b.t===d.t)?' disabled':''}>line ${b.f}–${b.t}</option>`).join('');
   pp.innerHTML=`<div class="note" style="margin-bottom:6px">Interline Power Flow Controller — two DC-coupled series converters. Line 1 is ${d.f}–${d.t}; choose line 2 below.</div>
    <div class="pprow"><span>control mode</span><select id="pp_imode" onchange="applyProp()" title="composition = two independent SSSCs; P-Q flow = master line sets P and Q, the slave sets Q and supplies the balancing real power via the DC link"><option value="comp"${pqm?'':' selected'}>composition (two SSSC)</option><option value="pq"${pqm?' selected':''}>P-Q flow control (DC-coupled)</option></select></div>
    <div class="pprow"><span>line 2</span><select id="pp_cl2" title="second (slave) line">${l2opts}</select></div>
    ${pqm?`<div class="psub" style="margin:8px 0 2px">master · line ${d.f}–${d.t}</div>
    <div class="pprow"><span>P1 set (MW)</span><input id="pp_ip1" type="number" step="5" value="${d.P1set!=null?d.P1set:60}" title="line-1 active power delivered (controlled)"></div>
    <div class="pprow"><span>Q1 set (MVAr)</span><input id="pp_iq1" type="number" step="5" value="${d.Q1set!=null?d.Q1set:10}" title="line-1 reactive power (controlled)"></div>
    <div class="psub" style="margin:8px 0 2px">slave · line ${d.f2||'?'}–${d.t2||'?'} (real power DC-set)</div>
    <div class="pprow"><span>Q2 set (MVAr)</span><input id="pp_iq2" type="number" step="5" value="${d.Q2set!=null?d.Q2set:5}" title="line-2 reactive power (controlled); its real power balances the DC link"></div>
    <div class="pprow"><span>Vse max (pu)</span><input id="pp_fvm" type="number" step="0.02" value="${d.Vsemax!=null?d.Vsemax:0.3}" title="max injected series voltage per converter"></div>`
    :`<div class="psub" style="margin:8px 0 2px">converter 1 · line ${d.f}–${d.t}</div>
    <div class="pprow"><span>comp kcomp</span><input id="pp_fkc" type="number" step="0.05" value="${d.kcomp}" title="series compensation on line 1"></div>
    <div class="pprow"><span>comp kcomp2</span><input id="pp_fkc2" type="number" step="0.05" value="${d.kcomp2!=null?d.kcomp2:0.2}" title="series compensation on line 2"></div>
    <div class="pprow"><span>Vse max (pu)</span><input id="pp_fvm" type="number" step="0.02" value="${d.Vsemax!=null?d.Vsemax:0.2}" title="max injected series voltage per converter"></div>`}
    <div class="psub" style="margin:8px 0 2px">layout</div>
    <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_fx" type="number" step="10" value="${Math.round(d.x)}" title="X"><input id="pp_fy" type="number" step="10" value="${Math.round(d.y)}" title="Y"></div></div>
    <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
    <div style="display:flex;gap:5px;margin-top:8px"><button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
    <div class="note" style="margin-top:6px">${pqm?'Master line holds P1 and Q1; the slave holds Q2 and supplies the balancing real power through the DC link (P_se1 + P_se2 = 0). Needs line 2 set and a well-connected common bus.':'Each converter is a verified SSSC. Switch to P-Q flow control for the DC-coupled independent-P-Q model.'}</div>`;
  }else{
  $('ppTitle').textContent=`${d.type} @ bus ${d.bus}`;
  const lim=isS?`<div class="pprow"><span>Bmax (pu)</span><input id="pp_fhi" type="number" step="0.1" value="${d.Bmax}" title="max capacitive susceptance (Q=B·|V|²)"></div>
   <div class="pprow"><span>Bmin (pu)</span><input id="pp_flo" type="number" step="0.1" value="${d.Bmin}" title="max inductive susceptance"></div>`
   :`<div class="pprow"><span>Imax (pu)</span><input id="pp_fhi" type="number" step="0.1" value="${d.Imax}" title="max capacitive reactive current (Q=|V|·I)"></div>
   <div class="pprow"><span>Imin (pu)</span><input id="pp_flo" type="number" step="0.1" value="${d.Imin}" title="max inductive reactive current"></div>`;
  pp.innerHTML=`<div class="note" style="margin-bottom:6px">${isS?'Static VAR Compensator — variable shunt susceptance, Q=B·|V|² (constant-impedance limit).':'STATCOM — VSC reactive source, Q=|V|·I (constant-current limit; holds voltage far better at low V).'}</div>
   <div class="pprow"><span>V ref (pu)</span><input id="pp_fvr" type="number" step="0.005" value="${d.Vref}" title="regulated voltage set-point"></div>
   ${lim}
   <div class="psub" style="margin:8px 0 2px">controller</div>
   <div class="pprow"><span>input signal</span><select id="pp_fsig" title="feedback signal the regulator acts on (local bus by default)"><option value="V"${d.signal==='V'?' selected':''}>bus |V| (local)</option><option value="Q"${d.signal==='Q'?' selected':''}>reactive power Q</option></select></div>
   <div class="pprow"><span>gain Kr</span><input id="pp_fkr" type="number" step="1" value="${d.Kr}" title="regulator gain"></div>
   <div class="pprow"><span>Tr (s)</span><input id="pp_ftr" type="number" step="0.01" value="${d.Tr}" title="regulator time constant"></div>
   <div class="pprow"><span>droop (pu)</span><input id="pp_fdr" type="number" step="0.005" value="${d.droop||0}" title="V–Q slope / slope reactance"></div>
   ${podEditorHTML(d)}
   <div class="psub" style="margin:8px 0 2px">layout</div>
   <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_fx" type="number" step="10" value="${Math.round(d.x)}" title="X"><input id="pp_fy" type="number" step="10" value="${Math.round(d.y)}" title="Y"></div></div>
   <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
   <div style="display:flex;gap:5px;margin-top:8px"><button class="tbtn" style="flex:1;color:#b42318" onclick="delSel()" title="delete (Del)">✕ delete</button></div>
   <div class="note" style="margin-top:6px">Included in power flow, small-signal and time-domain. The supplementary controller reads a local or remote (WAMS) signal to damp oscillations — tune its gain with Analysis ▸ POD design.</div>`;}
  }
 if(DSEL.t==='gen'){const g=NET.gens[DSEL.i],hb=NET.buses[g.bus-1]||{};
  const bq=(DPF&&DPF.Qg&&DPF.Qg[DSEL.i]!=null)?DPF.Qg[DSEL.i]:null;
  const gov=POV[DSEL.i]||{},gmd=g.md||{};
  const qmx=(gov.Qmax!=null)?gov.Qmax:((gmd.Qmax!=null)?gmd.Qmax:'');
  const qmn=(gov.Qmin!=null)?gov.Qmin:((gmd.Qmin!=null)?gmd.Qmin:'');
  const pmx=(gov.Pmax!=null)?gov.Pmax:((gmd.Pmax!=null)?gmd.Pmax:'');
  $('ppTitle').textContent=`Generator @ bus ${g.bus}`;
  pp.innerHTML=`<div class="pprow"><span>technology</span><select id="pp_tag" onchange="applyProp()" title="changing the type applies immediately, so ⚙ full parameters show the new model">${META.unit_types.map(u=>`<option${u===g.tag?' selected':''}>${u}</option>`).join('')}</select></div>
   <div class="pprow"><span>bus role</span><select id="pp_grole" title="how the power flow treats this unit's bus">
     <option value="slack"${hb.type==='slack'?' selected':''}>Slack — reference ⚓</option>
     <option value="pv"${(hb.type==='pv'||!hb.type)?' selected':''}>PV — P &amp; V fixed</option>
     <option value="pq"${hb.type==='pq'?' selected':''}>PQ — P &amp; Q fixed</option></select></div>
   <div class="pprow"><span>active power P (MW)</span><input id="pp_pg" type="number" step="10" value="${g.Pg}"></div>
   <div class="pprow"><span>reactive Q (MVAr)</span><input type="text" disabled value="${bq!=null?(bq.toFixed(1)+'  (solved)'):'run a power flow'}" title="reactive output — computed by the power flow for a PV / slack unit"></div>
   <div class="pprow"><span>voltage setpoint (pu)</span><input id="pp_gv" type="number" step="0.005" value="${g.Vset}"></div>
   <div class="pprow"><span>rating (MVA)</span><input id="pp_gs" type="number" step="10" value="${g.S}"></div>
   <div class="psub" style="margin:8px 0 2px">reactive &amp; operating limits</div>
   <div class="pprow"><span>reactive Qmax (pu)</span><input id="pp_gqmx" type="number" step="0.02" value="${qmx}" placeholder="pu of rating" title="upper reactive-power capability limit, per unit of the machine rating"></div>
   <div class="pprow"><span>reactive Qmin (pu)</span><input id="pp_gqmn" type="number" step="0.02" value="${qmn}" placeholder="− Qmax if blank" title="lower reactive-power limit (absorbing), per unit of the machine rating"></div>
   <div class="pprow"><span>active Pmax (pu)</span><input id="pp_gpmx" type="number" step="0.05" value="${pmx}" placeholder="1.5× dispatch" title="active-power / MW output limit, per unit of the machine rating (used by dispatch &amp; the dynamic model)"></div>
   <div class="pprow"><span>status</span><select id="pp_goff"><option value="0"${g.off?'':' selected'}>In service</option><option value="1"${g.off?' selected':''}>Out of service</option></select></div>
   <div class="psub" style="margin:8px 0 2px">layout</div>
   <div class="pprow"><span>position</span><div style="display:flex;gap:5px"><input id="pp_gx" type="number" step="10" value="${Math.round(g.x)}" title="X"><input id="pp_gy" type="number" step="10" value="${Math.round(g.y)}" title="Y"></div></div>
   <button class="go" style="margin-top:8px;width:100%" onclick="applyProp()">Apply</button>
   <button class="tbtn" style="margin-top:6px;width:100%" onclick="genPar(${DSEL.i})">⚙ full model parameters</button>${PBTNS}
   <div class="note" style="margin-top:6px">${META.unit_info[g.tag]||''}</div>`;}}
function applyProp(){if(!DSEL)return;pushU();
 if(DSEL.t==='bus'){const b=NET.buses[DSEL.i];
  b.name=$('pp_nm').value.trim();if(!b.name)delete b.name;
  b.type=$('pp_type').value;b.Vset=+$('pp_vs').value;b.Pd=+$('pp_pd').value;b.Qd=+$('pp_qd').value;b.Bs=+$('pp_bs').value;
  if($('pp_or'))b.rot=+$('pp_or').value?1:0;                    // orientation (angle)
  const nx=+$('pp_bx').value,ny=+$('pp_by').value;              // position (moves attached machines too)
  if(isFinite(nx)&&isFinite(ny)){const odx=nx-b.x,ody=ny-b.y;
   NET.gens.forEach(g=>{if(g.bus===DSEL.i+1){g.x+=odx;g.y+=ody;}});b.x=nx;b.y=ny;}}
 if(DSEL.t==='br'){const br=NET.branches[DSEL.i];
  const ln=$('pp_ln').value.trim();if(ln)br.name=ln;else delete br.name;
  br.r=+$('pp_r').value;br.x=+$('pp_x').value;br.b=+$('pp_b').value;br.tap=+$('pp_tap').value;
  if($('pp_xf').checked)br.xf=1;else delete br.xf;
  br.rate=+$('pp_rt').value||0;
  if($('pp_boff')&&$('pp_boff').value==='1')br.off=true;else delete br.off;}
 if(DSEL.t==='note'){const nt=NET.notes[DSEL.i];
  nt.text=$('pp_nt').value;nt.size=Math.max(7,Math.min(48,+$('pp_ns').value||14));
  nt.rot=((+$('pp_nr').value||0)%360+360)%360;if(!nt.rot)delete nt.rot;
  const nx=+$('pp_nx').value,ny=+$('pp_ny').value;if(isFinite(nx))nt.x=nx;if(isFinite(ny))nt.y=ny;}
 if(DSEL.t==='gen'){const g=NET.gens[DSEL.i];
  const old=g.tag;g.tag=$('pp_tag').value;g.Pg=+$('pp_pg').value;g.Vset=+$('pp_gv').value;g.S=+$('pp_gs').value;
  if($('pp_grole')&&NET.buses[g.bus-1])NET.buses[g.bus-1].type=$('pp_grole').value;   // bus role
  if($('pp_goff')&&$('pp_goff').value==='1')g.off=true;else delete g.off;             // in/out of service
  const nx=+$('pp_gx').value,ny=+$('pp_gy').value;if(isFinite(nx))g.x=nx;if(isFinite(ny))g.y=ny;
  if(old!==g.tag)clearOv(DSEL.i);
  // reactive & operating limit overrides (pu of rating) — set when given, cleared when blank
  [['pp_gqmx','Qmax'],['pp_gqmn','Qmin'],['pp_gpmx','Pmax']].forEach(([id,key])=>{
   const el=$(id),val=el?el.value:'';
   if(val!==''&&isFinite(+val)){POV[DSEL.i]=Object.assign({},POV[DSEL.i]||{},{[key]:+val});}
   else if(POV[DSEL.i]&&POV[DSEL.i][key]!=null){const o=Object.assign({},POV[DSEL.i]);delete o[key];
    if(Object.keys(o).length)POV[DSEL.i]=o;else delete POV[DSEL.i];}});}
 if(DSEL.t==='facts'&&NET.facts&&NET.facts[DSEL.i]){const d=NET.facts[DSEL.i],T=String(d.type).toUpperCase();
  if(T==='TCSC'||T==='TSSC'||T==='SSSC'){
   d.kcomp=+$('pp_fkc').value;d.kmin=+$('pp_fkmn').value;d.kmax=+$('pp_fkmx').value;
   if(T==='SSSC'&&$('pp_fvm'))d.Vsemax=+$('pp_fvm').value;
   if($('pp_ftc'))d.Tc=+$('pp_ftc').value||0.05;
   const nx=+$('pp_fx').value,ny=+$('pp_fy').value;if(isFinite(nx))d.x=nx;if(isFinite(ny))d.y=ny;
   if(T!=='TSSC')podApply(d);
  }else if(T==='UPFC'){
   const nb=Math.round(+$('pp_cbus').value);if(nb>=1&&nb<=NET.buses.length)d.bus=nb;
   d.Vref=+$('pp_fvr').value||1.0;d.Imax=+$('pp_fhi').value;d.Imin=+$('pp_flo').value;
   d.Kr=+$('pp_fkr').value;d.Tr=+$('pp_ftr').value;d.droop=+$('pp_fdr').value||0;
   if($('pp_cmode'))d.mode=$('pp_cmode').value;
   if(d.mode==='pq'){d.Pset=$('pp_cps')?+$('pp_cps').value:(d.Pset!=null?d.Pset:50);
    d.Qset=$('pp_cqs')?+$('pp_cqs').value:(d.Qset!=null?d.Qset:0);}
   else{delete d.Pset;delete d.Qset;}
   if($('pp_fkc'))d.kcomp=+$('pp_fkc').value;if($('pp_fvm'))d.Vsemax=+$('pp_fvm').value;
   const nx=+$('pp_fx').value,ny=+$('pp_fy').value;if(isFinite(nx))d.x=nx;if(isFinite(ny))d.y=ny;
   podApply(d);
  }else if(T==='IPFC'){
   if($('pp_imode'))d.mode=$('pp_imode').value;
   if($('pp_fvm'))d.Vsemax=+$('pp_fvm').value;
   const sel=$('pp_cl2');if(sel){const bi=+sel.value;
    if(bi>=0&&NET.branches[bi]&&!(NET.branches[bi].f===d.f&&NET.branches[bi].t===d.t)){d.f2=NET.branches[bi].f;d.t2=NET.branches[bi].t;}
    else{d.f2=0;d.t2=0;}}
   if(d.mode==='pq'){
    d.P1set=$('pp_ip1')?+$('pp_ip1').value:(d.P1set!=null?d.P1set:60);
    d.Q1set=$('pp_iq1')?+$('pp_iq1').value:(d.Q1set!=null?d.Q1set:10);
    d.Q2set=$('pp_iq2')?+$('pp_iq2').value:(d.Q2set!=null?d.Q2set:5);
   }else{
    if($('pp_fkc'))d.kcomp=+$('pp_fkc').value;if($('pp_fkc2'))d.kcomp2=+$('pp_fkc2').value;
    delete d.P1set;delete d.Q1set;delete d.Q2set;
   }
   const nx=+$('pp_fx').value,ny=+$('pp_fy').value;if(isFinite(nx))d.x=nx;if(isFinite(ny))d.y=ny;
  }else{const isS=T==='SVC';
   d.Vref=+$('pp_fvr').value||1.0;
   if(isS){d.Bmax=+$('pp_fhi').value;d.Bmin=+$('pp_flo').value;}else{d.Imax=+$('pp_fhi').value;d.Imin=+$('pp_flo').value;}
   d.signal=$('pp_fsig').value;d.Kr=+$('pp_fkr').value;d.Tr=+$('pp_ftr').value;d.droop=+$('pp_fdr').value||0;
   const nx=+$('pp_fx').value,ny=+$('pp_fy').value;if(isFinite(nx))d.x=nx;if(isFinite(ny))d.y=ny;
   podApply(d);}}
 try{rexLog('edited '+(DSEL?DSEL.t:'')+' '+((DSEL?DSEL.i:0)+1));}catch(_){}
 edited();draw();prop();syncSide();}
function genPar(i){openPar(i);}   // per-machine full model parameters (single shared model)
// ============ Results Explorer: tabbed attribute tables, fully SLD-synced ===
// A GIS-style attribute table: one tab per component class, sortable columns,
// a live filter box, CSV export, and full two-way linkage with the diagram —
// click a row to select+highlight its glyph, double-click to zoom to it, and
// any selection made on the canvas jumps this panel to the matching tab/row.
const REXTABS=[['bus','Bus'],['line','Line'],['gen','Generator'],['load','Load'],
 ['xfmr','Transformer'],['shunt','Shunt'],['renew','Renewable'],['dyn','Dynamic'],
 ['ss','Small-Signal'],['log','Event Log'],['warn','Warnings'],['msg','Messages'],
 ['stat','Statistics'],['props','Properties']];
let REXTAB='bus',REXQ='',REXSORT={},REXDS='',REXSS='',REXLOG=[],REXMSG=[],REXCOLS=[],REXHL=new Set(),
    REXW={},REXORD={},REXRZ=null,REXDRAG=null;   // per-tab column widths + order; live resize/reorder state
function rexMsg(m){var d=new Date();
 var t=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)+':'+('0'+d.getSeconds()).slice(-2);
 REXMSG.unshift({t:t,m:m}); if(REXMSG.length>300)REXMSG.pop();
 if(REXTAB==='msg')rexRender();}
// conditional-formatting colours (toolbox risk convention: red = worst)
const CFV=v=>{if(v===''||v==null)return '';v=+v;return v<0.95?'#b42318':v<0.97?'#b7791f':v>1.07?'#6d28d9':v>1.05?'#1d4ed8':'';};
const CFLOAD=v=>{if(v===''||v==null)return '';v=+v;return v>=100?'#b42318':v>=80?'#b7791f':'';};
const CFZ=v=>{if(v===''||v==null)return '';v=+v;return v<0?'#b42318':v<5?'#b7791f':'#1e7a44';};
function rexEsc(s){return (''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function rexIsXfmr(br){return !!(br&&(br.xf||(br.tap&&br.tap!==0&&br.tap!==1)));}
function rexNum(v){if(v===''||v==null||!isFinite(v))return '—';
 v=+v;const a=Math.abs(v);const d=a>=100?0:a>=10?1:a>=1?2:3;return v.toFixed(d).replace(/\.?0+$/,'');}
function rexV(i){return (DPF&&DPF.V&&DPF.V[i]!=null)?DPF.V[i]:'';}
function rexTh(i){return (DPF&&DPF.th&&DPF.th[i]!=null)?DPF.th[i]:'';}
function rexSfMax(){let m=1e-6;if(DPF&&DPF.flows)for(const f of DPF.flows)if(f)m=Math.max(m,Math.hypot(f.Pf,f.Qf));return m;}
function rexLog(m){const d=new Date();
 const t=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)+':'+('0'+d.getSeconds()).slice(-2);
 REXLOG.unshift({t,m});if(REXLOG.length>300)REXLOG.pop();
 if(REXTAB==='log')rexRender();}
function rexData(tab){const N=NET;let cols=[],rows=[];if(!N)return {cols,rows};
 const V4={num:1,f:v=>v===''?'—':(+v).toFixed(4),cf:CFV},A2={num:1,f:v=>v===''?'—':(+v).toFixed(2)};
 if(tab==='bus'){
  cols=[{l:'#',num:1,g:'identity'},{l:'name',txt:1,g:'identity'},{l:'type',txt:1,g:'identity'},
   Object.assign({l:'|V| pu',g:'solution'},V4),Object.assign({l:'∠ °',g:'solution'},A2),
   {l:'Pd MW',num:1,g:'load & shunt'},{l:'Qd MVAr',num:1,g:'load & shunt'},{l:'Bs MVAr',num:1,g:'load & shunt'}];
  N.buses.forEach((b,i)=>rows.push({v:[i+1,b.name||'',b.type.toUpperCase(),rexV(i),rexTh(i),b.Pd,b.Qd,b.Bs],map:{t:'bus',i}}));
 }else if(tab==='line'){const sf=rexSfMax();
  cols=[{l:'#',num:1,g:'identity'},{l:'from→to',txt:1,g:'identity'},
   {l:'R pu',num:1,f:v=>(+v).toFixed(4),g:'parameters'},{l:'X pu',num:1,f:v=>(+v).toFixed(4),g:'parameters'},
   {l:'B pu',num:1,f:v=>(+v).toFixed(3),g:'parameters'},{l:'P MW',num:1,g:'solution'},{l:'Q MVAr',num:1,g:'solution'},
   {l:'loss MW',num:1,f:v=>v===''?'—':(+v).toFixed(2),g:'solution'},{l:'load %',num:1,f:v=>v===''?'—':(+v).toFixed(0),cf:CFLOAD,g:'solution'}];
  N.branches.forEach((br,i)=>{if(rexIsXfmr(br))return;const fl=(DPF&&DPF.flows)?DPF.flows[i]:null;
   let ld='';if(fl){const s=Math.hypot(fl.Pf,fl.Qf);ld=(br.rate&&br.rate>0)?100*s/br.rate:100*s/sf;}
   rows.push({v:[i+1,br.f+'→'+br.t,br.r,br.x,br.b,fl?fl.Pf:'',fl?fl.Qf:'',fl?fl.loss:'',ld],map:{t:'br',i}});});
 }else if(tab==='xfmr'){const sf=rexSfMax();
  cols=[{l:'#',num:1,g:'identity'},{l:'from→to',txt:1,g:'identity'},
   {l:'R pu',num:1,f:v=>(+v).toFixed(4),g:'parameters'},{l:'X pu',num:1,f:v=>(+v).toFixed(4),g:'parameters'},
   {l:'tap',num:1,f:v=>(+v).toFixed(3),g:'parameters'},{l:'P MW',num:1,g:'solution'},
   {l:'loss MW',num:1,f:v=>v===''?'—':(+v).toFixed(2),g:'solution'},
   {l:'load %',num:1,f:v=>v===''?'—':(+v).toFixed(0),cf:CFLOAD,g:'solution'}];
  N.branches.forEach((br,i)=>{if(!rexIsXfmr(br))return;const fl=(DPF&&DPF.flows)?DPF.flows[i]:null;
   let ld='';if(fl){const s=Math.hypot(fl.Pf,fl.Qf);ld=(br.rate&&br.rate>0)?100*s/br.rate:100*s/sf;}
   rows.push({v:[i+1,br.f+'→'+br.t,br.r,br.x,(br.tap||1),fl?fl.Pf:'',fl?fl.loss:'',ld],map:{t:'br',i}});});
 }else if(tab==='gen'){
  cols=[{l:'#',num:1,g:'identity'},{l:'bus',num:1,g:'identity'},{l:'type',txt:1,g:'identity'},
   {l:'Pg MW',num:1,g:'solution'},{l:'Qg MVAr',num:1,g:'solution'},
   {l:'Vset pu',num:1,f:v=>(+v).toFixed(4),g:'setpoints'},Object.assign({l:'|V| pu',g:'solution'},V4),{l:'MVA',num:1,g:'setpoints'}];
  N.gens.forEach((g,i)=>{const pg=(DPF&&DPF.Pg)?DPF.Pg[i]:g.Pg,qg=(DPF&&DPF.Qg)?DPF.Qg[i]:'';
   rows.push({v:[i+1,g.bus,g.tag,pg,qg,g.Vset,rexV(g.bus-1),g.S],map:{t:'gen',i}});});
 }else if(tab==='load'){
  cols=[{l:'bus',num:1},{l:'name',txt:1},{l:'Pd MW',num:1},{l:'Qd MVAr',num:1},Object.assign({l:'|V| pu'},V4),
   Object.assign({l:'∠ °'},A2),{l:'I pu',num:1,f:v=>v===''?'—':(+v).toFixed(3)},
   {l:'pf',num:1,f:v=>v===''?'—':(+v).toFixed(3)},{l:'status',txt:1}];
  N.buses.forEach((b,i)=>{if(!(b.Pd||b.Qd))return;const s=Math.hypot(b.Pd,b.Qd),vv=rexV(i);
   const Ipu=(vv!==''&&vv)?s/100/vv:'',pf=s>1e-9?b.Pd/s:'';
   rows.push({v:[i+1,b.name||('Load-'+(i+1)),b.Pd,b.Qd,vv,rexTh(i),Ipu,pf,(s>1e-9?'in service':'off')],map:{t:'bus',i}});});
 }else if(tab==='shunt'){
  cols=[{l:'bus',num:1},{l:'B MVAr',num:1},{l:'kind',txt:1},Object.assign({l:'|V| pu'},V4),
   {l:'Q inj MVAr',num:1,f:v=>v===''?'—':(+v).toFixed(1)}];
  N.buses.forEach((b,i)=>{if(!b.Bs)return;const vv=rexV(i),q=(vv!==''&&vv)?b.Bs*vv*vv:'';
   rows.push({v:[i+1,b.Bs,(b.Bs>=0?'capacitor':'reactor'),vv,q],map:{t:'bus',i}});});
 }else if(tab==='dyn'){
  cols=[{l:'#',num:1},{l:'bus',num:1},{l:'type',txt:1},{l:'H s',num:1,f:v=>v===''?'—':(+v).toFixed(2)},
   {l:'MVA',num:1},Object.assign({l:'|V| pu'},V4)];
  N.gens.forEach((g,i)=>{const H=(g.md&&g.md.H!==undefined)?g.md.H:'';
   rows.push({v:[i+1,g.bus,g.tag,H,g.S,rexV(g.bus-1)],map:{t:'gen',i}});});
 }else if(tab==='renew'){
  cols=[{l:'#',num:1},{l:'bus',num:1},{l:'tech',txt:1},{l:'Pg MW',num:1},{l:'Qg MVAr',num:1},
   {l:'Vset pu',num:1,f:v=>(+v).toFixed(4)},Object.assign({l:'|V| pu'},V4),{l:'MVA',num:1}];
  N.gens.forEach((g,i)=>{if(/^SG/.test(g.tag))return;
   const pg=(DPF&&DPF.Pg)?DPF.Pg[i]:g.Pg,qg=(DPF&&DPF.Qg)?DPF.Qg[i]:'';
   rows.push({v:[i+1,g.bus,g.tag,pg,qg,g.Vset,rexV(g.bus-1),g.S],map:{t:'gen',i}});});
 }else if(tab==='ss'){
  cols=[{l:'#',num:1},{l:'f Hz',num:1,f:v=>(+v).toFixed(3)},{l:'damping %',num:1,f:v=>(+v).toFixed(2),cf:CFZ},
   {l:'real 1/s',num:1,f:v=>(+v).toFixed(3)},{l:'imag rad/s',num:1,f:v=>(+v).toFixed(3)}];
  if(typeof LASTL!=='undefined'&&LASTL&&LASTL.modes)
   LASTL.modes.forEach((m,i)=>rows.push({v:[i+1,m.f,m.z,m.re,m.im],map:null}));
 }else if(tab==='warn'){
  cols=[{l:'severity',txt:1,cf:v=>v==='HIGH'?'#b42318':(v==='med'?'#b7791f':'')},
   {l:'issue',txt:1},{l:'component',txt:1},{l:'value',txt:1}];
  const pw=(sev,iss,comp,val,map)=>rows.push({v:[sev,iss,comp,val],map:map});
  if(DPF&&DPF.V)N.buses.forEach((b,i)=>{const v=DPF.V[i];
   if(v<0.95)pw('HIGH','undervoltage','bus '+(i+1),v.toFixed(3)+' pu',{t:'bus',i});
   else if(v<0.97)pw('med','low voltage','bus '+(i+1),v.toFixed(3)+' pu',{t:'bus',i});
   else if(v>1.07)pw('HIGH','severe overvoltage','bus '+(i+1),v.toFixed(3)+' pu',{t:'bus',i});
   else if(v>1.05)pw('med','overvoltage','bus '+(i+1),v.toFixed(3)+' pu',{t:'bus',i});});
  if(DPF&&DPF.flows){const sf=rexSfMax();N.branches.forEach((br,i)=>{const fl=DPF.flows[i];if(!fl)return;
   const s=Math.hypot(fl.Pf,fl.Qf),ld=(br.rate&&br.rate>0)?100*s/br.rate:100*s/sf;
   if(ld>=100)pw('HIGH','overloaded '+(rexIsXfmr(br)?'transformer':'line'),br.f+'→'+br.t,ld.toFixed(0)+'%',{t:'br',i});
   else if(ld>=80)pw('med','heavy loading',br.f+'→'+br.t,ld.toFixed(0)+'%',{t:'br',i});});}
  const deg={};N.branches.forEach(br=>{deg[br.f]=1;deg[br.t]=1;});
  N.buses.forEach((b,i)=>{if(!deg[i+1])pw('HIGH','islanded bus','bus '+(i+1),'no branch',{t:'bus',i});});
  if(typeof LASTL!=='undefined'&&LASTL&&LASTL.modes)LASTL.modes.forEach(m=>{
   if(m.z<0)pw('HIGH','unstable mode',m.f.toFixed(2)+' Hz',m.z.toFixed(1)+'% damping',null);
   else if(m.z<5)pw('med','poorly damped',m.f.toFixed(2)+' Hz',m.z.toFixed(1)+'% damping',null);});
 }
 return {cols,rows};}
function rexCell(col,v){if(v==='')return col.num?'—':'';if(col.f)return col.f(v);if(col.num)return rexNum(v);return ''+v;}
function rexTabsUI(){const t=$('rexTabs');if(!t)return;
 // one compact dropdown instead of fourteen chips: the categories no longer
 // eat panel height, and the current one reads directly off the control
 t.innerHTML=REXTABS.map(kv=>`<option value="${kv[0]}"${kv[0]===REXTAB?' selected':''}>${kv[1]}</option>`).join('');}
function rexTab(k){REXTAB=k;rexRender();if(NET)draw();}
function rexFilter(v){REXQ=(v||'').toLowerCase();rexRender();if(NET)draw();}
function rexSortBy(ci){const so=REXSORT[REXTAB];
 if(so&&so.c===ci)so.d=-so.d;else REXSORT[REXTAB]={c:ci,d:1};rexRender();}
// explicit sort controls (mirrors the MATLAB edition): a "Sort: column"
// picker + an ascending/descending button, kept in lockstep with the
// click-on-header sorting that the arrows in the header already show.
function rexSortUI(D){const s=$('rexSortSel'),b=$('rexSortDir');if(!s)return;
 const on=!!(D&&D.cols&&D.cols.length);
 s.style.display=on?'':'none';if(b)b.style.display=on?'':'none';
 if(!on)return;
 const so=REXSORT[REXTAB];
 s.innerHTML='<option value="-1">Sort: table order</option>'+
  D.cols.map((c,i)=>`<option value="${i}"${so&&so.c===i?' selected':''}>Sort: ${rexEsc(c.l)}</option>`).join('');
 if(b)b.textContent=(so&&so.d<0)?'▼ desc':'▲ asc';}
function rexSortSel(v){v=+v;
 if(v<0)delete REXSORT[REXTAB];
 else{const so=REXSORT[REXTAB];REXSORT[REXTAB]={c:v,d:(so&&so.c===v)?so.d:1};}
 rexRender();}
function rexSortFlip(){const so=REXSORT[REXTAB];
 if(so)so.d=-so.d;else if(REXCOLS&&REXCOLS.length)REXSORT[REXTAB]={c:0,d:-1};
 rexRender();}
// ---- advanced filter: space-separated AND terms; each is either plain text
//      (matches any column) or  column<op>value  with op in < <= > >= = ------
function rexNormCol(s){return (''+s).toLowerCase().replace(/[^a-z0-9|∠→%]/g,'');}
function rexParseQ(q,cols){const terms=[];
 for(const tok of (q||'').trim().split(/\s+/)){if(!tok)continue;
  const m=tok.match(/^(.+?)(<=|>=|=|<|>)(.+)$/);
  if(m){const cn=rexNormCol(m[1]);
   let ci=-1;cols.forEach((c,k)=>{if(ci<0&&rexNormCol(c.l).startsWith(cn))ci=k;});
   if(ci>=0){terms.push({ci,op:m[2],v:m[3].toLowerCase(),num:isFinite(parseFloat(m[3]))?parseFloat(m[3]):null});continue;}}
  terms.push({text:tok.toLowerCase()});}
 return terms;}
function rexRowPass(r,terms,cols){
 for(const t of terms){
  if(t.text!==undefined){
   if(!r.v.some((c,ci)=>rexCell(cols[ci],c).toLowerCase().includes(t.text)))return false;continue;}
  const raw=r.v[t.ci];
  if(t.op==='='){if(!(''+rexCell(cols[t.ci],raw)).toLowerCase().includes(t.v))return false;continue;}
  const x=parseFloat(raw);if(raw===''||!isFinite(x))return false;
  if(t.op==='<' &&!(x< t.num))return false;
  if(t.op==='<='&&!(x<=t.num))return false;
  if(t.op==='>' &&!(x> t.num))return false;
  if(t.op==='>='&&!(x>=t.num))return false;}
 return true;}
function rexOrd(nc){const o=REXORD[REXTAB];
 return (o&&o.length===nc)?o:Array.from({length:nc},(_,i)=>i);}
function rexColReset(){delete REXW[REXTAB];delete REXORD[REXTAB];delete REXSORT[REXTAB];
 rexRender();stat('columns reset for the '+REXTAB+' table');}
function rexPick(ms,zoom){if(!ms||!NET)return;const p=ms.split(':'),t=p[0],i=+p[1];
 MSEL=[];DSEL={t,i};REXSS=rexSelSig();      // pin the sig so rexTick keeps THIS tab
 prop();draw();if(zoom)zoomSel();rexRender();}
function rexPropsHTML(){if(!NET||!DSEL)return '<div class="rexempty">select a component on the canvas or in any table to see its full properties here.</div>';
 const rows=[],add=(k,v)=>rows.push([k,v]);
 if(DSEL.t==='bus'){const b=NET.buses[DSEL.i],i=DSEL.i;
  add('kind','Bus');add('number',i+1);if(b.name)add('name',b.name);
  add('type',b.type.toUpperCase());add('V set',b.Vset+' pu');
  add('load P',b.Pd+' MW');add('load Q',b.Qd+' MVAr');add('shunt B',b.Bs+' MVAr');
  if(DPF&&DPF.V){add('|V| solved',DPF.V[i].toFixed(4)+' pu');add('angle',DPF.th[i].toFixed(2)+' °');}
 }else if(DSEL.t==='gen'){const g=NET.gens[DSEL.i],i=DSEL.i;
  add('kind','Generator');add('at bus',g.bus);add('technology',g.tag);
  add('P set',g.Pg+' MW');add('V set',g.Vset+' pu');add('rating',g.S+' MVA');
  if(DPF&&DPF.Pg){add('Pg solved',DPF.Pg[i]+' MW');add('Qg solved',DPF.Qg[i]+' MVAr');add('|V|',DPF.V[g.bus-1].toFixed(4)+' pu');}
  if(g.md&&g.md.H!==undefined)add('inertia H',g.md.H+' s');
 }else if(DSEL.t==='br'){const br=NET.branches[DSEL.i],i=DSEL.i;
  add('kind',rexIsXfmr(br)?'Transformer':'Line');add('from bus',br.f);add('to bus',br.t);
  add('R',br.r+' pu');add('X',br.x+' pu');add('B',br.b+' pu');add('tap',(br.tap||0));
  if(br.rate)add('rating',br.rate+' MVA');
  const fl=(DPF&&DPF.flows)?DPF.flows[i]:null;
  if(fl){add('P from',fl.Pf+' MW');add('Q from',fl.Qf+' MVAr');add('loss',fl.loss+' MW');}
 }else if(DSEL.t==='note'){add('kind','Annotation');add('text',(NET.notes[DSEL.i].text||''));}
 if(!rows.length)return '<div class="rexempty">no detail for this selection.</div>';
 let h='<table class="rexkv"><tr class="hd"><td colspan="2">'+rexEsc(rows[0][1])+' &mdash; full properties</td></tr>';
 rows.forEach(r=>{h+=`<tr><td>${rexEsc(r[0])}</td><td>${rexEsc(r[1])}</td></tr>`;});
 return h+'</table>';}
function rexStatHTML(){if(!NET)return '<div class="rexempty">load a network to see statistics.</div>';
 const rows=[],add=(k,v)=>rows.push([k,v]);
 const nb=NET.buses.length,nl=NET.branches.filter(b=>!rexIsXfmr(b)).length,nx=NET.branches.filter(rexIsXfmr).length;
 const ng=NET.gens.length,nibr=NET.gens.filter(g=>!/^SG/.test(g.tag)).length;
 const nld=NET.buses.filter(b=>b.Pd||b.Qd).length,nsh=NET.buses.filter(b=>b.Bs).length;
 add('buses',nb);add('lines',nl);add('transformers',nx);add('generators',ng+'  ('+nibr+' IBR)');
 add('loads',nld);add('shunts',nsh);
 if(DPF){add('total generation',DPF.Ptot+' MW');add('total load',DPF.Pload+' MW');
  add('losses',(DPF.Ptot-DPF.Pload).toFixed(1)+' MW');
  let mn=1e9,mx=-1e9,imn=0,imx=0;DPF.V.forEach((v,i)=>{if(v<mn){mn=v;imn=i;}if(v>mx){mx=v;imx=i;}});
  add('min |V|',mn.toFixed(4)+' pu (bus '+(imn+1)+')');add('max |V|',mx.toFixed(4)+' pu (bus '+(imx+1)+')');
  if(DPF.flows){const sf=rexSfMax();let wl=0,wi=-1;NET.branches.forEach((br,i)=>{const fl=DPF.flows[i];if(!fl)return;
    const s=Math.hypot(fl.Pf,fl.Qf),ld=(br.rate&&br.rate>0)?100*s/br.rate:100*s/sf;if(ld>wl){wl=ld;wi=i;}});
   if(wi>=0)add('worst line loading',wl.toFixed(0)+'% ('+NET.branches[wi].f+'→'+NET.branches[wi].t+')');}
 }else add('power flow','not solved — run it for live totals');
 if(typeof LASTL!=='undefined'&&LASTL&&LASTL.nstates!==undefined){add('dynamic states',LASTL.nstates);
  add('effective inertia',LASTL.Heff+' s');add('IBR share',LASTL.pen+' %');if(LASTL.unstable)add('unstable modes',LASTL.unstable);}
 let h='<table class="rexkv"><tr class="hd"><td colspan="2">'+rexEsc(NET.name)+' — network statistics</td></tr>';
 rows.forEach(r=>{h+=`<tr><td>${rexEsc(r[0])}</td><td>${rexEsc(r[1])}</td></tr>`;});
 return h+'</table>';}
function rexRender(){const body=$('rexBody');if(!body)return;rexTabsUI();const cnt=$('rexCount');
 const sum=$('rexSum');if(sum)sum.style.display='none';
 REXHL=new Set();                               // filter/search -> highlight set (repopulated below)
 const q=$('rexQ');if(q&&q.value.toLowerCase()!==REXQ)q.value=REXQ;
 if(REXTAB==='log'||REXTAB==='msg'){rexSortUI(null);const src=REXTAB==='log'?REXLOG:REXMSG;
  const L=src.filter(e=>!REXQ||e.m.toLowerCase().includes(REXQ)||e.t.includes(REXQ));
  if(cnt)cnt.textContent=L.length+(REXTAB==='log'?' events':' messages');
  body.innerHTML=L.length?('<div class="rexlog">'+L.map(e=>`<div><time>${e.t}</time>${rexEsc(e.m)}</div>`).join('')+'</div>')
   :('<div class="rexempty">'+(REXTAB==='log'?'actions and solver results are logged here as you work.':'simulation and solver messages appear here after you run an analysis.')+'</div>');return;}
 if(REXTAB==='props'){rexSortUI(null);if(cnt)cnt.textContent='';body.innerHTML=rexPropsHTML();return;}
 if(REXTAB==='stat'){rexSortUI(null);if(cnt)cnt.textContent='';body.innerHTML=rexStatHTML();return;}
 if(!NET){rexSortUI(null);if(cnt)cnt.textContent='';body.innerHTML='<div class="rexempty">load a benchmark or draw a network to populate the tables.</div>';return;}
 const D=rexData(REXTAB);REXCOLS=D.cols;rexSortUI(D);let rows=D.rows;
 const terms=REXQ?rexParseQ(REXQ,D.cols):[];
 if(terms.length)rows=rows.filter(r=>rexRowPass(r,terms,D.cols));
 if(terms.length)rows.forEach(r=>{if(r.map)REXHL.add(r.map.t+':'+r.map.i);});   // highlight matches on the SLD
 const so=REXSORT[REXTAB];
 if(so){const ci=so.c,dir=so.d;rows=rows.slice().sort((a,b)=>{let x=a.v[ci],y=b.v[ci];
   const xn=(x!==''&&isFinite(x)),yn=(y!==''&&isFinite(y));
   if(D.cols[ci].num&&xn&&yn)return dir*((+x)-(+y));
   if(xn&&!yn)return dir;if(!xn&&yn)return -dir;
   x=(''+x).toLowerCase();y=(''+y).toLowerCase();return dir*(x<y?-1:x>y?1:0);});}
 if(cnt)cnt.textContent=rows.length+(rows.length===1?' row':' rows')+(terms.length?' (filtered)':'');
 rexSummary(rows,D);                            // no-op since the totals strip was removed (kept for compat)
 if(!rows.length){let hint;
  if(REXTAB==='ss')hint=' — run the Small-signal (Linearize) analysis';
  else if(REXTAB==='warn')hint=DPF?' — all voltages and loadings are within limits':' — run a power flow to scan for issues';
  else if(REXTAB==='renew')hint=' — no converter-interfaced units in this fleet (all SG)';
  else hint=(DPF?'':' — run a power flow for live values');
  body.innerHTML='<div class="rexempty">'+(REXTAB==='warn'&&DPF?'No warnings':'no '+REXTAB+' rows')+(REXQ?' match “'+rexEsc(REXQ)+'”':'')+hint+'.</div>';return;}
 const selKey=DSEL?DSEL.t+DSEL.i:'';
 const ord=rexOrd(D.cols.length),W=REXW[REXTAB]||{};
 const defOrder=ord.every((v,i)=>v===i);
 const hasGrp=defOrder&&D.cols.some(c=>c.g);
 let h='<table class="rextab'+(hasGrp?' hasgrp':'')+'"><thead>';
 if(hasGrp){h+='<tr class="grp">';                       // grouped column bands (default order only)
  let i=0;while(i<D.cols.length){const g=D.cols[i].g||'';let sp=1;
   while(i+sp<D.cols.length&&(D.cols[i+sp].g||'')===g)sp++;
   h+=`<th colspan="${sp}">${rexEsc(g)}</th>`;i+=sp;}
  h+='</tr>';}
 h+='<tr>';
 ord.forEach((ci,vi)=>{const c=D.cols[ci];const ar=(so&&so.c===ci)?(so.d>0?'▲':'▼'):'';
  const w=W[c.l]?` style="width:${W[c.l]}px;min-width:${W[c.l]}px;max-width:${W[c.l]}px"`:'';
  h+=`<th class="${c.txt?'txt':''}" draggable="true" data-ci="${ci}" data-vi="${vi}"${w}>${rexEsc(c.l)}<span class="ar">${ar}</span><span class="rz" data-rz="${ci}"></span></th>`;});
 h+='</tr></thead><tbody>';
 rows.forEach(r=>{const mk=r.map?r.map.t+r.map.i:'';const isSel=(mk&&mk===selKey);
  const dm=r.map?` data-map="${r.map.t}:${r.map.i}"`:'';
  let sev=0;                                    // 0 none · 1 amber · 2 red (conditional formatting)
  const tds=ord.map(ci=>{const col=D.cols[ci],c=r.v[ci];let st='';
   if(col.cf){const cc=col.cf(c); if(cc){st=` style="color:${cc};font-weight:600"`;
    if(cc==='#b42318')sev=Math.max(sev,2); else if(cc==='#b7791f')sev=Math.max(sev,1);}}
   return `<td class="${col.txt?'txt':''}"${st}>${rexEsc(rexCell(col,c))}</td>`;}).join('');
  const cls=isSel?'sel':(sev===2?'sev2':(sev===1?'sev1':''));
  h+=`<tr${cls?` class="${cls}"`:''}${dm}>${tds}</tr>`;});
 body.innerHTML=h+'</tbody></table>';
 body.querySelectorAll('tr[data-map]').forEach(tr=>{
  tr.onclick=()=>rexPick(tr.dataset.map,false);tr.ondblclick=()=>rexPick(tr.dataset.map,true);
  tr.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();rexCtxOpen(e,tr.dataset.map);};});
 rexWireCols(body);
 const s=body.querySelector('tr.sel');if(s&&s.scrollIntoView)s.scrollIntoView({block:'nearest'});}
// ---- professional-table plumbing: summary strip, resize, reorder, context ----
function rexSummary(rows,D){const el=$('rexSum');if(!el)return;
 const parts=[];const num=v=>rexNum(v);
 const colv=lab=>{let ci=-1;D.cols.forEach((c,k)=>{if(ci<0&&c.l===lab)ci=k;});
  return ci<0?[]:rows.map(r=>parseFloat(r.v[ci])).filter(isFinite);};
 const sumOf=a=>a.reduce((s,x)=>s+x,0);
 if(REXTAB==='bus'){const V=colv('|V| pu');
  parts.push('buses<b>'+rows.length+'</b>','ΣPd<b>'+num(sumOf(colv('Pd MW')))+' MW</b>','ΣQd<b>'+num(sumOf(colv('Qd MVAr')))+' MVAr</b>');
  if(V.length)parts.push('|V|<b>'+Math.min(...V).toFixed(3)+' – '+Math.max(...V).toFixed(3)+' pu</b>');
 }else if(REXTAB==='line'||REXTAB==='xfmr'){const ls=colv('loss MW'),ld=colv('load %');
  parts.push((REXTAB==='line'?'lines':'transformers')+'<b>'+rows.length+'</b>');
  if(ls.length)parts.push('Σloss<b>'+num(sumOf(ls))+' MW</b>');
  if(ld.length)parts.push('worst load<b>'+Math.max(...ld).toFixed(0)+' %</b>');
 }else if(REXTAB==='gen'||REXTAB==='renew'){
  parts.push('units<b>'+rows.length+'</b>','ΣPg<b>'+num(sumOf(colv('Pg MW')))+' MW</b>','ΣQg<b>'+num(sumOf(colv('Qg MVAr')))+' MVAr</b>');
 }else if(REXTAB==='load'){
  parts.push('loads<b>'+rows.length+'</b>','ΣPd<b>'+num(sumOf(colv('Pd MW')))+' MW</b>','ΣQd<b>'+num(sumOf(colv('Qd MVAr')))+' MVAr</b>');
 }else if(REXTAB==='shunt'){
  parts.push('shunts<b>'+rows.length+'</b>','ΣQ inj<b>'+num(sumOf(colv('Q inj MVAr')))+' MVAr</b>');
 }else if(REXTAB==='ss'){const z=colv('damping %');
  parts.push('modes<b>'+rows.length+'</b>');
  if(z.length)parts.push('worst ζ<b>'+Math.min(...z).toFixed(2)+' %</b>',
   z.some(x=>x<0)?'<span class="viol">UNSTABLE</span>':(z.some(x=>x<5)?'<span class="viol">poorly damped</span>':'<span class="ok">all ζ ≥ 5%</span>'));
 }else if(REXTAB==='warn'){
  const hi=rows.filter(r=>r.v[0]==='HIGH').length,md=rows.length-hi;
  parts.push('violations<b>'+rows.length+'</b>',hi?'<span class="viol">'+hi+' HIGH</span>':'<span class="ok">0 high</span>',md+' medium');
 }else if(REXTAB==='dyn'){const H=colv('H s');
  parts.push('machines<b>'+rows.length+'</b>');if(H.length)parts.push('ΣH·S<b>'+num(sumOf(H))+' s·pu</b>');}
 if(DPF&&['bus','line','xfmr','gen','load','shunt'].includes(REXTAB))
  parts.push('system: gen<b>'+DPF.Ptot+' MW</b>','load<b>'+DPF.Pload+' MW</b>','losses<b>'+(DPF.Ptot-DPF.Pload).toFixed(1)+' MW</b>');
 if(!parts.length){el.style.display='none';return;}
 el.innerHTML=parts.map(p=>'<span>'+p+'</span>').join('');el.style.display='flex';}
function rexWireCols(body){
 body.querySelectorAll('th .rz').forEach(rz=>{
  rz.onmousedown=e=>{e.preventDefault();e.stopPropagation();
   const th=rz.parentElement,ci=+rz.dataset.rz;
   REXRZ={ci,lab:REXCOLS[ci].l,x0:e.clientX,w0:th.getBoundingClientRect().width};};
  rz.onclick=e=>e.stopPropagation();});
 body.querySelectorAll('th[data-ci]').forEach(th=>{
  th.onclick=e=>{if(REXRZ)return;rexSortBy(+th.dataset.ci);};
  th.ondragstart=e=>{REXDRAG={from:+th.dataset.vi};e.dataTransfer.effectAllowed='move';try{e.dataTransfer.setData('text/plain','');}catch(_){}};
  th.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='move';};
  th.ondrop=e=>{e.preventDefault();if(!REXDRAG)return;
   const to=+th.dataset.vi,from=REXDRAG.from;REXDRAG=null;if(to===from)return;
   const ord=rexOrd(REXCOLS.length).slice();const [mv]=ord.splice(from,1);ord.splice(to,0,mv);
   REXORD[REXTAB]=ord;rexRender();stat('column moved — ⟲ cols restores the default order');};
  th.ondragend=()=>{REXDRAG=null;};});}
window.addEventListener('mousemove',e=>{if(!REXRZ)return;
 const w=Math.max(44,REXRZ.w0+(e.clientX-REXRZ.x0));
 (REXW[REXTAB]=REXW[REXTAB]||{})[REXRZ.lab]=Math.round(w);
 const th=document.querySelector(`#rexBody th[data-ci="${REXRZ.ci}"]`);
 if(th){th.style.width=th.style.minWidth=th.style.maxWidth=w+'px';}});
window.addEventListener('mouseup',()=>{if(REXRZ){REXRZ=null;rexRender();}});
function rexCtxOpen(e,ms){const m=$('rexCtx');if(!m)return;
 const items=[];
 if(ms){items.push(['Select on canvas',`rexPick('${ms}',false)`],
   ['Zoom to component',`rexPick('${ms}',true)`],
   ['Full properties',`rexPick('${ms}',false);rexTab('props')`],['—','']);}
 items.push(['Copy row (TSV)',ms?`rexCopyRow('${ms}')`:'rexCopy()'],
  ['Copy table (TSV)','rexCopy()'],['Export CSV','rexExport()'],['Print table','rexPrint()'],
  ['—',''],['Reset columns &amp; sort','rexColReset()']);
 m.innerHTML=items.map(([l,fn])=>l==='—'?'<div class="csep"></div>':`<a onclick="rexCtxClose();${fn}">${l}</a>`).join('');
 m.style.display='block';
 const W=m.offsetWidth,H=m.offsetHeight;
 m.style.left=Math.min(e.clientX,window.innerWidth-W-8)+'px';
 m.style.top=Math.min(e.clientY,window.innerHeight-H-8)+'px';}
function rexCtxClose(){const m=$('rexCtx');if(m)m.style.display='none';}
window.addEventListener('click',rexCtxClose);
window.addEventListener('blur',rexCtxClose);
function rexCopyRow(ms){const D=rexData(REXTAB);
 const r=D.rows.find(x=>x.map&&(x.map.t+':'+x.map.i)===ms);if(!r)return;
 const ord=rexOrd(D.cols.length);
 const tsv=ord.map(ci=>D.cols[ci].l).join('\t')+'\n'+ord.map(ci=>rexCell(D.cols[ci],r.v[ci])).join('\t');
 const ok=()=>stat('row copied');
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(tsv).then(ok,()=>rexCopyFB(tsv,ok));
 else rexCopyFB(tsv,ok);}
function rexTabFor(sel){if(!sel||!NET)return null;
 if(sel.t==='gen')return 'gen';
 if(sel.t==='br')return rexIsXfmr(NET.branches[sel.i])?'xfmr':'line';
 if(sel.t==='bus'){const b=NET.buses[sel.i];
  if(REXTAB==='load'&&(b.Pd||b.Qd))return 'load';
  if(REXTAB==='shunt'&&b.Bs)return 'shunt';
  return 'bus';}
 return null;}
function rexDataSig(){return NET?(NET.name+'|'+NET.buses.length+'|'+NET.branches.length+'|'+NET.gens.length+'|'+(DPF?('D'+DPF.Ptot+'_'+DPF.Pload):'-')):'';}
function rexSelSig(){return DSEL?(DSEL.t+DSEL.i):(MSEL.length?'m'+MSEL.length:'');}
function rexTick(){if(!$('rexBody'))return;let need=false;
 const ds=rexDataSig();if(ds!==REXDS){REXDS=ds;need=true;}
 const ss=rexSelSig();if(ss!==REXSS){REXSS=ss;const tb=rexTabFor(DSEL);if(tb&&tb!==REXTAB)REXTAB=tb;need=true;}
 if(need)rexRender();}
function rexCsvq(s){s=''+s;return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
function rexDownload(fn,txt){const a=document.createElement('a');
 a.href='data:text/csv;charset=utf-8,'+encodeURIComponent(txt);a.download=fn;
 document.body.appendChild(a);a.click();document.body.removeChild(a);}
function rexExport(){
 if(REXTAB==='log'){if(!REXLOG.length){stat('event log is empty');return;}
  rexDownload('psdat_log.csv','time,event\n'+REXLOG.map(e=>e.t+','+rexCsvq(e.m)).join('\n'));stat('event log exported');return;}
 if(REXTAB==='props'){stat('switch to a table tab to export');return;}
 if(!NET)return;const D=rexData(REXTAB);if(!D.rows.length){stat('no rows to export');return;}
 const head=D.cols.map(c=>rexCsvq(c.l)).join(',');
 const bod=D.rows.map(r=>r.v.map((c,ci)=>rexCsvq(rexCell(D.cols[ci],c))).join(',')).join('\n');
 rexDownload('psdat_'+REXTAB+'.csv',head+'\n'+bod);stat(REXTAB+' table exported to CSV');}
function rexTableHB(){                          // {head:[...],body:[[...]]} — WYSIWYG: current filter, sort and column order
 if(REXTAB==='log')return {head:['time','event'],body:REXLOG.map(e=>[e.t,e.m])};
 if(REXTAB==='msg')return {head:['time','message'],body:REXMSG.map(e=>[e.t,e.m])};
 if(REXTAB==='props'||!NET)return null;
 const D=rexData(REXTAB);let rows=D.rows;
 const terms=REXQ?rexParseQ(REXQ,D.cols):[];
 if(terms.length)rows=rows.filter(r=>rexRowPass(r,terms,D.cols));
 const so=REXSORT[REXTAB];
 if(so){const ci=so.c,dir=so.d;rows=rows.slice().sort((a,b)=>{let x=a.v[ci],y=b.v[ci];
   const xn=(x!==''&&isFinite(x)),yn=(y!==''&&isFinite(y));
   if(D.cols[ci].num&&xn&&yn)return dir*((+x)-(+y));
   if(xn&&!yn)return dir;if(!xn&&yn)return -dir;
   x=(''+x).toLowerCase();y=(''+y).toLowerCase();return dir*(x<y?-1:x>y?1:0);});}
 const ord=rexOrd(D.cols.length);
 return {head:ord.map(ci=>D.cols[ci].l),body:rows.map(r=>ord.map(ci=>rexCell(D.cols[ci],r.v[ci])))};}
function rexCopy(){const t=rexTableHB();if(!t||!t.body.length){stat('nothing to copy on this tab');return;}
 const tsv=[t.head.join('\t')].concat(t.body.map(r=>r.join('\t'))).join('\n');
 const ok=()=>stat(REXTAB+' table copied to clipboard');
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(tsv).then(ok,()=>rexCopyFB(tsv,ok));
 else rexCopyFB(tsv,ok);}
function rexCopyFB(txt,ok){const ta=document.createElement('textarea');ta.value=txt;
 ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();
 try{document.execCommand('copy');ok();}catch(e){stat('copy is not permitted in this window');}document.body.removeChild(ta);}
function rexPrint(){const t=rexTableHB();if(!t||!t.body.length){stat('nothing to print on this tab');return;}
 const ttl='PSDAT — '+REXTAB.toUpperCase()+' results'+(NET?' — '+NET.name:'');
 const tbl='<table><thead><tr>'+t.head.map(x=>`<th>${rexEsc(x)}</th>`).join('')+'</tr></thead><tbody>'+
  t.body.map(r=>'<tr>'+r.map(x=>`<td>${rexEsc(x)}</td>`).join('')+'</tr>').join('')+'</tbody></table>';
 const doc='<html><head><title>'+rexEsc(ttl)+'</title><style>body{font:12px system-ui,Arial;padding:18px;color:#1f2937}'+
  'h2{font-family:Georgia,serif;color:#16305c}table{border-collapse:collapse;width:100%;font-size:12px}'+
  'th,td{border:1px solid #cbd5e1;padding:4px 8px;text-align:right}th{background:#eef2f8;color:#20304d}</style></head>'+
  '<body><h2>'+rexEsc(ttl)+'</h2>'+tbl+'</body></html>';
 const f=document.createElement('iframe');f.style.position='fixed';f.style.right='0';f.style.bottom='0';
 f.style.width='0';f.style.height='0';f.style.border='0';document.body.appendChild(f);
 const d=f.contentWindow.document;d.open();d.write(doc);d.close();
 setTimeout(()=>{try{f.contentWindow.focus();f.contentWindow.print();}catch(e){stat('printing is not available in this window');}
  setTimeout(()=>{try{document.body.removeChild(f);}catch(_){}} ,600);},220);}
async function runPF(){if(!NET){netErr('load or draw a network first');return;}
 netErr('');$('spN').style.display='inline';
 const pm=($('pfmeth')||{}).value||'nr';
 const r=await api('/api/pf',{net:NET,pfmethod:pm});
 $('spN').style.display='none';
 if(r.error){netErr(friendlyErr(r.error));return;}
 DPF=r;
 VOPT.cont=heatOnPref(); VOPT.anim=true;   // auto-show the two flagship results on every successful run: voltage heat map + animated flow arrows (user can still toggle them off)
 syncView(); draw();
 const pfl={nr:'Newton-Raphson',fdlf:'fast-decoupled XB',gs:'Gauss-Seidel'};
 const pi=r.pf?`<br>solver: <b>${pfl[r.pf.method]||r.pf.method}</b> — ${r.pf.iters} iterations, residual ${r.pf.mismatch.toExponential(1)} pu`:'';
 $('pfsum').innerHTML=`<b>Power flow converged.</b><br>generation ${r.Ptot} MW · load ${r.Pload} MW · losses ${(r.Ptot-r.Pload).toFixed(1)} MW${pi}<br>voltages: <span style="color:#1e7a44">green</span> normal · <span style="color:#b7791f">amber</span>/<span style="color:#b42318">red</span> LOW · <span style="color:#1d4ed8">blue</span>/<span style="color:#5b21b6">violet</span> HIGH (0.95–1.05 pu band)`;
 try{rexLog('power flow ('+((r.pf&&r.pf.method)||pm)+'): gen '+r.Ptot+' MW, load '+r.Pload+' MW, losses '+(r.Ptot-r.Pload).toFixed(1)+' MW'+(r.pf?', '+r.pf.iters+' iters':''));
  rexMsg('Power flow converged — '+((r.pf&&r.pf.method)||pm).toUpperCase()+(r.pf?(', '+r.pf.iters+' iterations, mismatch '+r.pf.mismatch.toExponential(1)+' pu'):'')+', losses '+(r.Ptot-r.Pload).toFixed(1)+' MW');}catch(_){}}
function useNet(quiet){if(!NET){netErr('load or draw a network first');return;}
 ACTIVE='custom';syncSide();
 $('knote').textContent=`analysis tabs use: ${NET.name} (${NET.buses.length} buses, ${NET.gens.length} units)`;}
function syncSide(){
 // the diagram is always the model — just refresh the fleet strip + design pickers
 if(!NET)return;
 buildSide();fillDesign();}
// ---------- design & sweeps ----------
async function loadSweepParams(){const el=$('swU');if(!el||el.value==='')return;
 const r=await api('/api/params',buildPayload({k:+el.value}));
 if(r.error)return;
 $('swP').innerHTML=r.params.filter(p=>p.kind==='num').map(p=>`<option value="${p.name}" title="${p.desc}">${p.name}</option>`).join('');}
async function runSw(){$('runSw').disabled=true;$('spSw').style.display='inline';$('swErr').innerHTML='';
 const r=await api('/api/sweep',buildPayload({unit:+$('swU').value,
  param:$('swP').value,vfrom:+$('swA').value,vto:+$('swB').value,n:+$('swN').value,
  band:[+$('swF1').value,+$('swF2').value]}));
 $('runSw').disabled=false;$('spSw').style.display='none';
 if(r.error){$('swErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 locusChart($('swloc'),r.loci);
 const zs=r.curve.map(c=>c[1]);
 lineChart($('swcurve'),r.curve.map(c=>c[0]),{'ζ (%)':zs},$('swP').value,'least damping (%)');}
async function runPd(){$('runPd').disabled=true;$('spPd').style.display='inline';$('pdErr').innerHTML='';
 const meas=$('pdM').value==='diff'?{type:'diff',a:+$('pdA').value,b:+$('pdB').value}:{type:'local',a:+$('pdA').value};
 const r=await api('/api/pod',buildPayload({act:+$('pdA').value,
  meas,band:[+$('pdF1').value,+$('pdF2').value],zt:$('pdZ').value/100}));
 $('runPd').disabled=false;$('spPd').style.display='none';
 if(r.error){$('pdErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 try{lrnMark('pd');}catch(_){}
 const mR=Math.max(...r.ranking.map(x=>x[1]));
 $('pdout').innerHTML=
  `<p>target mode <b>${r.target.f} Hz</b> at <b>${r.target.z} %</b> damping → achieved <b>${r.achieved.z} %</b>`+
  ` (${r.unstable?'<span class="zbad">'+r.unstable+' unstable!</span>':'all modes stable'})</p>`+
  `<p style="margin-top:6px">POD on the actuator: K = ${r.pod.K}, washout ${r.pod.Tw} s, ${r.pod.nc} lead-lag(s) T1 = ${r.pod.T1}, T2 = ${r.pod.T2}</p>`+
  `<h3 style="margin-top:10px">Residue ranking (best actuator location)</h3>`+
  r.ranking.map(x=>`<div class="pl"><span>${x[0]}</span><div><div class="pbar" style="width:${(100*x[1]/mR).toFixed(0)}%"></div></div><span>${x[1].toExponential(1)}</span></div>`).join('');
 overlayChart($('pdeig'),r.ev_open,r.ev_closed);}
async function runBd(){$('runBd').disabled=true;$('spBd').style.display='inline';$('bdErr').innerHTML='';
 const out=$('bdO').value==='unit'?{type:'unit',a:+$('bdA').value}:{type:'coi'};
 const r=await api('/api/bode',buildPayload({inp:+$('bdU').value,out}));
 $('runBd').disabled=false;$('spBd').style.display='none';
 if(r.error){$('bdErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 const lx=r.f.map(Math.log10);
 lineChart($('bdmag'),lx,{'|H| (dB)':r.mag},'log10 f (Hz)','magnitude (dB)');
 lineChart($('bdph'),lx,{'∠H (deg)':r.phase},'log10 f (Hz)','phase (deg)');}
// ---------- small-signal ----------

async function runL(){$('runL').disabled=true;$('spL').style.display='inline';$('ssErr').innerHTML='';
 const r=await api('/api/linearize',buildPayload());
 $('runL').disabled=false;$('spL').style.display='none';
 if(r.error){$('ssErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 LASTL=r;try{lrnMark('ss');}catch(_){}
 const _bh=$('bH'),_bp=$('bP'),_bn=$('bN');if(_bh)_bh.textContent=r.Heff+' s';if(_bp)_bp.textContent=r.pen+' %';if(_bn)_bn.textContent=r.nstates;
 try{let cm=r.modes&&r.modes.length?r.modes.reduce((a,b)=>b.z<a.z?b:a):null;
  rexMsg('Small-signal: '+r.nstates+' states, '+(r.unstable||0)+' unstable'+(cm?(', least-damped '+cm.f.toFixed(3)+' Hz @ '+cm.z.toFixed(2)+'%'):''));
  if(REXTAB==='ss')rexRender();}catch(_){}
 eigChart($('eig'),r.ev);
 const tb=document.querySelector('#mtab tbody');
 tb.innerHTML=r.modes.map((m,i)=>{const cls=m.z<0?'zbad':m.z<5?'zwarn':'zok';
  return `<tr data-i="${i}"><td>${m.f.toFixed(3)}</td><td class="${cls}">${m.z.toFixed(2)} %</td><td>${m.re.toFixed(3)} ± ${m.im.toFixed(3)}j</td></tr>`;}).join('');
 if(r.unstable)$('ssErr').innerHTML=`<div class="err">⚠ ${r.unstable} unstable mode(s) — this operating condition is small-signal unstable.</div>`;
 tb.onclick=e=>{const tr=e.target.closest('tr');if(!tr)return;
  tb.querySelectorAll('tr').forEach(x=>x.classList.remove('sel'));tr.classList.add('sel');
  const m=LASTL.modes[+tr.dataset.i];
  $('part').innerHTML=m.part.map(([n,v])=>`<div class="pl"><span>${n}</span><div><div class="pbar" style="width:${(v*100).toFixed(0)}%"></div></div><span>${v.toFixed(2)}</span></div>`).join('');
  compass($('shape'),m.shape);};}
// ---------- time domain ----------
const DH={load:'positive size = load increase at the chosen bus (0.15 pu = 15 MW)',
 fault:'size = fault reactance Xf (pu) at the bus; removed-at = clearing time',
 trip:'outage of the line between the two buses; removed-at = reclosure time',
 gen:'pulse on the set-point / mechanical power of the chosen UNIT (G number)',
 cloud:'size = irradiance dip depth (0.6 = lose 60% of the sun) over the chosen PV UNIT',
 gust:'size = gust amplitude in pu of rated wind at the chosen wind UNIT (IEC shape)'};
$('dkind').onchange=()=>{const k=$('dkind').value;$('dhint').textContent=DH[k];
 $('floc2w').style.display=k==='trip'?'':'none';
 $('floclab').textContent=(k==='gen'||k==='cloud'||k==='gust')?'unit (G#)':'bus';
 $('fmaglab').textContent=k==='fault'?'Xf (pu)':k==='cloud'?'dip depth':k==='gust'?'gust (pu)':'size (pu)';
 const t1=+$('dt1').value||1.0;                     // removed-at defaults to applied-at + 0.1 s
 $('dt2').value=(k==='cloud'||k==='gust'||k==='trip')?'':(t1+0.1).toFixed(1);};
$('dt1').oninput=()=>{const k=$('dkind').value;
 if(!(k==='cloud'||k==='gust'||k==='trip'))$('dt2').value=(+$('dt1').value+0.1).toFixed(1);};
let STDIRTY=true;
function stFill(names){const sel=$('watch');if(!sel||!names)return;
 const keep=new Set([...sel.selectedOptions].map(o=>o.value));
 sel.innerHTML=names.map(n=>`<option value="${n}"${keep.has(n)?' selected':''}>${n}</option>`).join('');
 STDIRTY=false;}
async function fillStates(force){if(!force&&!STDIRTY)return;
 try{const r=await api('/api/states',buildPayload({}));if(r&&r.names)stFill(r.names);}catch(_){}}
async function runT(){$('runT').disabled=true;$('spT').style.display='inline';$('tdErr').innerHTML='';
 const watch=[...(($('watch')||{}).selectedOptions||[])].map(o=>o.value).slice(0,4);
 const r=await api('/api/simulate',buildPayload({watch,
  dist:{kind:$('dkind').value,loc:+$('dloc').value,loc2:+$('dloc2').value,mag:+$('dmag').value,
        t1:+$('dt1').value,t2:$('dt2').value,tsim:+$('dts').value,method:$('dmeth').value}}));
 $('runT').disabled=false;$('spT').style.display='none';
 if(r.error){$('tdErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 try{const dk=$('dkind').value;if(dk==='fault')lrnMark('td');if(dk==='cloud')lrnMark('cloud');}catch(_){}
 if(r.fCOI)lineChart($('cfrq'),r.t,{'f_COI':r.fCOI},'time (s)','frequency (Hz)');
 $('nad').innerHTML=r.metrics?`nadir ${r.metrics.nadir} Hz · initial RoCoF ${r.metrics.rocof==null?'–':r.metrics.rocof} Hz/s · final ${r.metrics.fend} Hz · solver ${r.method||'rk4'} (${r.nsteps||0} pts)`+(r.solver_note?`<br><span style="color:#b7791f">${r.solver_note}</span>`:''):'';
 lineChart($('cspd'),r.t,r.speeds,'time (s)','unit frequency (Hz)');
 if(Object.keys(r.watch).length)lineChart($('cwatch'),r.t,r.watch,'time (s)','value (pu / deg)');
 else $('cwatch').innerHTML='';
 if(r.names)stFill(r.names);}                     // the run knows the exact state set
// ---------- DATA tab: the as-entered model — input data & parameters ----------
let DATTAB='busin',PRMCACHE=null,PRMDIRTY=true;
const DATTABS=[['busin','Bus & load input'],['brin','Branch input'],['unitin','Units & dispatch'],
               ['prm','Unit parameters'],['factsin','FACTS input']];
function datTab(v){DATTAB=v;datRender();}
function datTable(cols,rows,empty){
 if(!rows.length)return '<div class="rexempty">'+empty+'</div>';
 let h='<table class="rextab"><thead><tr>'+cols.map(c=>`<th class="${c.txt?'txt':''}" style="cursor:default">${rexEsc(c.l)}</th>`).join('')+'</tr></thead><tbody>';
 rows.forEach(r=>{h+=`<tr${r.map?` data-map="${r.map}"`:''}>`+
  r.v.map((v,ci)=>`<td class="${cols[ci].txt?'txt':''}">${rexEsc(v===undefined||v===null?'':v)}</td>`).join('')+'</tr>';});
 return h+'</tbody></table>';}
function datRender(){const body=$('datBody');if(!body)return;
 const s=$('datTabs');
 if(s&&!s.options.length)s.innerHTML=DATTABS.map(t=>`<option value="${t[0]}">${t[1]}</option>`).join('');
 if(s)s.value=DATTAB;
 if(!body.offsetParent)return;                    // panel hidden: skip the DOM work
 if(!NET){body.innerHTML='<div class="rexempty">load a benchmark or draw a network to see its input data.</div>';return;}
 const T=(c,r,e)=>{body.innerHTML=datTable(c,r,e);
  body.querySelectorAll('tr[data-map]').forEach(tr=>{
   tr.onclick=()=>rexPick(tr.dataset.map,false);tr.ondblclick=()=>rexPick(tr.dataset.map,true);});};
 if(DATTAB==='busin'){
  T([{l:'bus'},{l:'name',txt:1},{l:'type',txt:1},{l:'V set pu'},{l:'Pd MW'},{l:'Qd MVAr'},{l:'shunt B MVAr'}],
    NET.buses.map((b,i)=>({v:[i+1,b.name||'',b.type.toUpperCase(),b.Vset,b.Pd,b.Qd,b.Bs],map:'bus:'+i})),
    'no buses yet — draw or import a network.');}
 else if(DATTAB==='brin'){
  T([{l:'#'},{l:'from→to',txt:1},{l:'kind',txt:1},{l:'R pu'},{l:'X pu'},{l:'B pu'},{l:'tap'},{l:'rating MVA'}],
    NET.branches.map((br,i)=>({v:[i+1,br.f+'→'+br.t,rexIsXfmr(br)?'transformer':'line',br.r,br.x,br.b,br.tap||'',br.rate||''],map:'br:'+i})),
    'no branches yet.');}
 else if(DATTAB==='unitin'){
  T([{l:'unit',txt:1},{l:'bus'},{l:'technology',txt:1},{l:'P set MW'},{l:'V set pu'},{l:'rating MVA'},{l:'edited',txt:1}],
    NET.gens.map((g,k)=>({v:['G'+(k+1),g.bus,g.tag,g.Pg,g.Vset,g.S,
     ((POV[k]&&Object.keys(POV[k]).length)||g.md)?'✓':''],map:'gen:'+k})),
    'no machines yet.');}
 else if(DATTAB==='factsin'){
  const rows=(NET.facts||[]).map((d,i)=>{
   const loc=d.bus?('bus '+d.bus):(d.f?(d.f+'→'+d.t+(d.f2?'  &  '+d.f2+'→'+d.t2:'')):'');
   const set=['Vref','Xset','Pset','Qset','kpct','Qmax','Qmin'].filter(k2=>d[k2]!==undefined&&d[k2]!=='')
     .map(k2=>k2+' = '+d[k2]).join('   ');
   return {v:[i+1,d.type,loc,set],map:'facts:'+i};});
  T([{l:'#'},{l:'device',txt:1},{l:'location',txt:1},{l:'settings',txt:1}],rows,
    'no FACTS devices on the diagram — drag one from the Draw palette.');}
 else if(DATTAB==='prm'){body.innerHTML='<div class="rexempty">reading the parameter catalogue…</div>';datPrm(body);}}
async function datPrm(body){
 try{
  if(PRMDIRTY||!PRMCACHE){const r=await api('/api/paramsall',buildPayload({}));
   if(r&&r.units){PRMCACHE=r.units;PRMDIRTY=false;}
   else{body.innerHTML='<div class="rexempty">'+rexEsc((r&&r.error)?friendlyErr(r.error):'parameters unavailable')+'</div>';return;}}
  if(DATTAB!=='prm')return;                       // the user moved on while we fetched
  const rows=[];
  PRMCACHE.forEach((u,k)=>{const ov=POV[k]||{};
   u.params.forEach(p=>{const has=ov[p.name]!==undefined;
    rows.push({v:['G'+(k+1)+' ('+u.tag+')',p.name,String(p.value),
      (has?String(ov[p.name]):''),p.desc||''],map:'gen:'+k});});});
  body.innerHTML=datTable([{l:'unit',txt:1},{l:'parameter',txt:1},{l:'default'},{l:'edited'},{l:'description',txt:1}],
    rows,'no units on the diagram.')+
   '<div class="rexempty" style="text-align:left;padding:8px 12px">double-click a row to edit that unit\'s parameters — the <b>edited</b> column shows your overrides.</div>';
  body.querySelectorAll('tr[data-map]').forEach(tr=>{
   tr.onclick=()=>rexPick(tr.dataset.map,false);
   tr.ondblclick=()=>{openPar(+tr.dataset.map.split(':')[1]);};});
 }catch(e){body.innerHTML='<div class="rexempty">could not read the parameter catalogue.</div>';}}
// ---------- scenarios ----------
async function runS(name){$('spS').style.display='inline';$('scErr').innerHTML='';$('scout').style.display='none';$('scimg').innerHTML='';
 const r=await api('/api/scenario',{name});
 $('spS').style.display='none';
 if(r.error){$('scErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 $('scout').textContent=r.text;$('scout').style.display='';
 $('scimg').innerHTML=r.images.map(u=>`<img src="${u}">`).join('');}
// ================== STUDIES — course-grade static analyses ==================
function stTable(cols,rows,empty){
 if(!rows.length)return '<div class="rexempty">'+(empty||'no rows')+'</div>';
 let h='<table class="rextab"><thead><tr>'+cols.map(c=>`<th class="${c.txt?'txt':''}" style="cursor:default">${c.l}</th>`).join('')+'</tr></thead><tbody>';
 rows.forEach(r=>{h+='<tr>'+r.v.map((v,ci)=>`<td class="${cols[ci].txt?'txt':''}">${v===undefined||v===null?'':v}</td>`).join('')+'</tr>';});
 return h+'</tbody></table>';}
function stBars(el,labels,vals,yl){const w=el.clientWidth||480,h=250,L=52,B=34,T=12,R=10;
 if(!vals||!vals.length){el.innerHTML='<div class="note">no data</div>';return;}
 let y0=Math.min(0,...vals),y1=Math.max(...vals);if(y1-y0<1e-9)y1=y0+1;
 y1+=(y1-y0)*0.1;
 const Y=v=>h-B-(v-y0)*(h-B-T)/(y1-y0||1);let s='';
 for(const tv of ticks(y0,y1,5))s+=`<line x1="${L}" y1="${Y(tv)}" x2="${w-R}" y2="${Y(tv)}" stroke="#eef1f6"/><text x="${L-6}" y="${Y(tv)+4}" text-anchor="end" font-size="10.5" fill="#6b7280">${fmt(tv)}</text>`;
 const n=labels.length,bw=(w-L-R)/n,Y0=Y(Math.max(0,y0));
 vals.forEach((v,i)=>{const x=L+bw*(i+0.5),hw=Math.min(bw*0.34,26);
  s+=`<rect x="${(x-hw).toFixed(1)}" y="${Math.min(Y(v),Y0).toFixed(1)}" width="${(2*hw).toFixed(1)}" height="${Math.max(1,Math.abs(Y0-Y(v))).toFixed(1)}" fill="#1f3b73" opacity=".85"><title>bus ${labels[i]}: ${v}</title></rect>`;
  if(n<=24)s+=`<text x="${x.toFixed(1)}" y="${h-B+14}" text-anchor="middle" font-size="10" fill="#6b7280">${labels[i]}</text>`;});
 s+=`<rect x="${L}" y="${T}" width="${w-R-L}" height="${h-B-T}" fill="none" stroke="#cfd6e2"/>`;
 s+=`<text transform="translate(12 ${(T+h-B)/2}) rotate(-90)" text-anchor="middle" font-size="11" fill="#374151">${yl}</text>`;
 s+=`<text x="${(L+w-R)/2}" y="${h-3}" text-anchor="middle" font-size="11" fill="#374151">bus</text>`;
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s}</svg>`;}
function stEnter(){const pb=$('pvBus'),cb=$('cctBus');if(!pb||!cb)return;
 let lop='<option value="0">all loads together</option>',cop='';
 if(NET)NET.buses.forEach((b,i)=>{const nm=b.name?' · '+rexEsc(b.name):'';
  if(+b.Pd>0)lop+=`<option value="${i+1}">bus ${i+1}${nm} (${b.Pd} MW)</option>`;
  cop+=`<option value="${i+1}">bus ${i+1}${nm}</option>`;});
 const kp=pb.value,kc=cb.value;
 pb.innerHTML=lop;cb.innerHTML=cop||'<option value="1">bus 1</option>';
 if([...pb.options].some(o=>o.value===kp))pb.value=kp;
 if([...cb.options].some(o=>o.value===kc))cb.value=kc;}
async function runPV(){const b=$('goPV');b.disabled=true;$('spPV').style.display='inline';$('pvErr').innerHTML='';
 const r=await api('/api/pv',buildPayload({bus:+$('pvBus').value}));
 b.disabled=false;$('spPV').style.display='none';
 if(r.error){$('pvErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 lineChart($('pvChart'),r.P_mw,{[`V at bus ${r.bus} (pu)`]:r.V_pu},
  r.all_loads?'total scaled load P (MW)':`load at bus ${r.bus} (MW)`,'V (pu)');
 const mc=r.margin_pct>50?'#1e7a44':r.margin_pct>20?'#b7791f':'#b42318';
 $('pvOut').innerHTML=`base load <b>${r.P0_mw} MW</b> → nose at <b>${r.Pmax_mw} MW</b> — loading margin <b style="color:${mc}">${r.margin_pct}%</b>. Monitored voltage at the nose: ${r.V_pu[r.V_pu.length-1]} pu (${r.V_pu.length} continuation points). <span style="color:var(--mut)">${r.note}. Utilities plan for &gt;20–30% margin; a capacitor or SVC at the weak bus pushes the nose right — try it.</span>`;
 lrnMark('pv');}
async function runN1(){const b=$('goN1');b.disabled=true;$('spN1').style.display='inline';$('n1Err').innerHTML='';
 const r=await api('/api/n1',buildPayload({}));
 b.disabled=false;$('spN1').style.display='none';
 if(r.error){$('n1Err').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 const sev=st2=>/ISLAND|DIVERG/.test(st2)?'#b42318':/violation/.test(st2)?'#b7791f':'#1e7a44';
 $('n1Tab').innerHTML=stTable(
  [{l:'outage',txt:1},{l:'result',txt:1},{l:'V min (pu)'},{l:'V max (pu)'},{l:'worst loading',txt:1}],
  r.rows.map(z=>({v:['line '+z.line,`<b style="color:${sev(z.status)}">${z.status}</b>`,
   z.vmin==null?'—':z.vmin,z.vmax==null?'—':z.vmax,
   z.load_pct==null?'—':z.load_pct+'%'+(z.worst_line?' on '+z.worst_line:'')]})),'no branches');
 $('n1Out').innerHTML=`<b>${r.n_secure} of ${r.n_outages}</b> single-line outages leave the system secure (ranked worst-first). Islanding and divergence outrank voltage violations; the 0.95–1.05 pu band is the screening criterion. <span style="color:var(--mut)">set line ratings on branches to enable the loading check.</span>`;
 lrnMark('n1');}
async function runSC(){const b=$('goSC');b.disabled=true;$('spSC').style.display='inline';$('stscErr').innerHTML='';
 const r=await api('/api/sc',buildPayload({}));
 b.disabled=false;$('spSC').style.display='none';
 if(r.error){$('stscErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 const mx=Math.max(...r.rows.map(z=>z.sc_mva));
 $('stscTab').innerHTML=stTable(
  [{l:'bus',txt:1},{l:'I_f (pu)'},{l:'S_sc (MVA)'},{l:'X/R'},{l:'relative strength',txt:1}],
  r.rows.map(z=>({v:[String(z.bus)+(z.bus===r.strong?' <b style="color:#1e7a44">● strongest</b>':z.bus===r.weak?' <b style="color:#b42318">● weakest</b>':''),
   z.If_pu,z.sc_mva,z.xr,
   `<div style="height:9px;border-radius:5px;background:linear-gradient(90deg,var(--navy),#2c5aa0);width:${Math.max(2,100*z.sc_mva/mx).toFixed(0)}%"></div>`]})),'no buses');
 $('stscOut').innerHTML=`strongest bus <b style="color:#1e7a44">${r.strong}</b> · weakest bus <b style="color:#b42318">${r.weak}</b> — ${r.note}. <span style="color:var(--mut)">short-circuit MVA is the "grid strength" converters see (SCR = S_sc / S_converter).</span>`;
 lrnMark('sc');}
async function runCCT(){const b=$('goCCT');b.disabled=true;$('spCCT').style.display='inline';$('cctErr').innerHTML='';
 const r=await api('/api/cct',buildPayload({fbus:+$('cctBus').value,xf:+$('cctXf').value}));
 b.disabled=false;$('spCCT').style.display='none';
 if(r.error){$('cctErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 const chip=x=>`<span style="display:inline-block;margin:2px 4px 2px 0;padding:2px 8px;border-radius:10px;font-size:11px;background:${x[1]?'#f0fdf4':'#fef2f2'};color:${x[1]?'#1e7a44':'#b42318'};border:1px solid ${x[1]?'#bbf7d0':'#fecaca'}">${(x[0]*1000).toFixed(0)} ms ${x[1]?'✓':'✗'}</span>`;
 const chips=(r.tried||[]).map(chip).join('');
 if(r.cct==null){$('cctOut').innerHTML=`<b>${r.verdict}</b><br>${chips}`;$('cctChart').innerHTML='';return;}
 $('cctOut').innerHTML=`CCT ≈ <b style="font-size:17px;color:var(--navy)">${(r.cct*1000).toFixed(0)} ms</b> <span style="color:var(--mut)">(bracket ${(r.window[0]*1000).toFixed(0)}–${(r.window[1]*1000).toFixed(0)} ms)</span> for a fault at bus ${r.fbus}, X<sub>f</sub> = ${r.xf} pu.<br>bisection trail: ${chips}<br><span style="color:var(--mut)">a typical relay + breaker clears in 60–120 ms — is this fault clearable in time? More inertia (H) buys milliseconds; faster excitation and stabilizers buy damping after the swing.</span>`;
 const t=(r.t_s.length>=r.t_u.length?r.t_s:r.t_u);
 lineChart($('cctChart'),t,{[`cleared at ${(r.cct*1000).toFixed(0)} ms — stable`]:r.spread_stable,
  [`cleared at ${(r.window[1]*1000).toFixed(0)}+ ms — unstable`]:r.spread_unstable},'time (s)','max rotor-angle spread (deg)');
 lrnMark('cct');}
async function runED(){const b=$('goED');b.disabled=true;$('spED').style.display='inline';$('edErr').innerHTML='';
 const r=await api('/api/ed',buildPayload({}));
 b.disabled=false;$('spED').style.display='none';
 if(r.error){$('edErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 $('edTab').innerHTML=stTable(
  [{l:'unit',txt:1},{l:'b ($/MWh)'},{l:'c ($/MWh²)'},{l:'P now (MW)'},{l:'equal-λ (MW)'},{l:'DC-OPF (MW)'},{l:'P max (MW)'}],
  r.gens.map((g,k)=>({v:[g.g+' · bus '+g.bus,g.b,g.c,g.Pnow,g.Popt,r.opf?r.opf.Pg_mw[k]:'—',g.Pmax]})),'no generators');
 $('edOut').innerHTML=`demand <b>${r.demand_mw} MW</b> (incl. ${r.loss_mw} MW losses) · system marginal price λ = <b>${r.lam} $/MWh</b> · production cost ${r.cost_now} → <b>${r.cost_opt} $/h</b>, saving <b style="color:#1e7a44">${r.saving} $/h</b> just by re-dispatching${r.opf?` · DC-OPF cost ${r.opf.cost} $/h with line limits respected`:''}. <span style="color:var(--mut)">${r.note}.</span>`;
 if(r.opf){stBars($('edLmp'),r.opf.lmp.map((_,i)=>String(i+1)),r.opf.lmp,'LMP ($/MWh)');
  $('edBind').innerHTML=r.opf.binding.length?
   `congested line(s): <b style="color:#b42318">${r.opf.binding.join(', ')}</b> — LMP spread ${r.opf.spread} $/MWh. Buses behind the congestion pay more: that price difference is exactly the congestion rent.`:
   `no line limit binds, so every bus pays the same λ (${r.opf.lmp[0]} $/MWh). Set a line's <b>rating</b> below its flow and re-run — congestion makes the prices separate by location.`;}
 else{$('edLmp').innerHTML='<div class="note">DC-OPF unavailable (SciPy linprog failed)</div>';$('edBind').textContent='';}
 lrnMark('ed');}
let OPPRES=null;
async function runOPP(){const b=$('goOPP');b.disabled=true;$('spOPP').style.display='inline';$('oppErr').innerHTML='';
 const r=await api('/api/opp',buildPayload({zero_inj:$('oppZI').checked}));
 b.disabled=false;$('spOPP').style.display='none';
 if(r.error){$('oppErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 OPPRES=r;
 $('oppTab').innerHTML=stTable([{l:'bus',txt:1},{l:'observed by',txt:1},{l:'redundancy (PMUs seeing it)'}],
  r.coverage.map(z=>({v:[String(z.bus),z.how==='PMU'?'<b style="color:#1f3b73">■ PMU here</b>':z.how==='neighbor'?'a neighbouring PMU':'<b style="color:#b42318">NOT observed</b>',z.redundancy]})),'no buses');
 $('oppOut').innerHTML=`<b>${r.n} PMU${r.n>1?'s':''}</b> make all ${r.coverage.length} buses observable (${r.observed_pct}%): buses <b>${r.pmus.join(', ')}</b>.`+
  (r.zero_inj_used?` Zero-injection buses (${r.zi_buses.join(', ')}) let KCL fill the gaps — without that credit the exact optimum is ${r.n_plain} PMUs (${r.pmus_plain.join(', ')}).`:'')+
  ` <span style="color:var(--mut)">each PMU streams synchro-phasors (V and every incident branch current) to the control centre — the WAMS backbone.</span>`;
 $('oppShowB').style.display='';$('oppClearB').style.display=PMUV?'':'none';
 lrnMark('opp');}
function oppShow(){if(!OPPRES)return;PMUV={p:OPPRES.pmus,cov:OPPRES.coverage};
 $('oppClearB').style.display='';goTab('net');
 stat('PMU placement on the diagram — a signal beacon marks each PMU bus (coverage detail in Studies ▸ PMU table)');}
function oppClear(){PMUV=null;const b=$('oppClearB');if(b)b.style.display='none';
 if(TAB==='net'&&NET)draw();stat('PMU overlay cleared');}
// ================== LEARN — lessons, quiz, equal-area lab, glossary =========
let LEARN={t:{},done:{},qb:0},LNBOOT=0,LNSAVET=null;
function lrnSave(){clearTimeout(LNSAVET);LNSAVET=setTimeout(()=>{api('/api/uipref',{learn:LEARN});},800);}
function lrnMark(k){if(!LEARN.done[k]){LEARN.done[k]=1;lrnSave();if(TAB==='ln')try{lrnRender();}catch(_){}}}
function lrnTick(key){LEARN.t[key]=LEARN.t[key]?0:1;lrnSave();lrnRender();}
const LESSONS=[
 {id:'l1',title:'1 · Meet the grid',icon:'⚡',goal:'Import a benchmark, read its power flow, learn to move around the diagram.',steps:[
  {t:'Import a benchmark from <b>Test system</b> on the Diagram tab — IEEE 9 is the classic starter',c:()=>!!NET&&NET.buses.length>=3},
  {t:'The power flow solves by itself: voltages colour the buses, arrows animate the flows',c:()=>!!DPF},
  {t:'Hover a line to read its P + jQ, and a bus to read its voltage',m:1},
  {t:'Click a bus and rename it in Properties — your first model edit',m:1}]},
 {id:'l2',title:'2 · Power flow, three solvers',icon:'🧮',goal:'One nonlinear problem — Newton-Raphson, fast-decoupled and Gauss-Seidel all land on the same answer at very different speeds.',steps:[
  {t:'In Properties (Diagram tab) switch <b>PF solver</b> to fast-decoupled — note the iteration count in the summary',c:()=>!!DPF&&($('pfmeth')||{}).value==='fdlf'},
  {t:'Try <b>Gauss-Seidel</b>: hundreds of sweeps for the same answer — why Newton won [Tinney &amp; Hart 1967]',c:()=>!!DPF&&($('pfmeth')||{}).value==='gs'},
  {t:'Read the losses (generation − load) in the power-flow summary',m:1},
  {t:'Open the <b>Data</b> panel (right dock) — the exact input tables every solver reads',m:1}]},
 {id:'l3',title:'3 · Small-signal stability',icon:'〰️',goal:'Linearize the whole differential-algebraic model exactly and meet the electromechanical modes.',steps:[
  {t:'Run <b>Signal ▸ Linearize &amp; analyse</b>',c:()=>LEARN.done.ss===1||!!LASTL},
  {t:'Click the least-damped oscillatory mode in the table — participation factors show WHICH machines swing against which',m:1},
  {t:'Apply the <b>40% GFM</b> fleet preset (left dock) and re-linearize: what happened to frequencies and damping?',c:()=>LEARN.done.ss===1&&!!NET&&NET.gens.some(g=>g.tag==='GFM')},
  {t:'Restore <b>All SG</b> and re-run — the A/B habit is how engineers reason',m:1}]},
 {id:'l4',title:'4 · Time domain & inertia',icon:'⏱️',goal:'The same equations, integrated nonlinearly through a disturbance — nadir, RoCoF and the low-inertia problem.',steps:[
  {t:'Run a <b>3-phase fault</b> simulation on the Time tab',c:()=>LEARN.done.td===1},
  {t:'Read the frequency nadir and initial RoCoF under the COI chart',m:1},
  {t:'Pick two machine angles (delta) in Watch states and re-run — see them swing against each other',m:1},
  {t:'Halve a machine\'s H (click it ▸ parameters) and re-run: faster RoCoF, deeper nadir — the renewable-grid challenge in one experiment',m:1}]},
 {id:'l5',title:'5 · Voltage stability',icon:'📉',goal:'How much more load fits before the power flow folds? The nose curve knows.',steps:[
  {t:'Trace a <b>P–V curve</b> (Studies tab) for the heaviest load bus',c:()=>LEARN.done.pv===1},
  {t:'Read the loading margin — planners keep &gt;20–30%',m:1},
  {t:'Drop a <b>capacitor</b> on the weakest bus and re-trace: the nose moves right',m:1},
  {t:'Swap it for an <b>SVC</b> (FACTS palette): dynamic support also survives the low-voltage region where fixed banks fade (Q = BV²)',m:1}]},
 {id:'l6',title:'6 · Operating the grid',icon:'🕹️',goal:'Security first, economics second — a system operator\'s day in two studies.',steps:[
  {t:'Run the <b>N−1 screening</b> (Studies): the grid must survive any single outage',c:()=>LEARN.done.n1===1},
  {t:'Run <b>Economic dispatch</b>: equal-λ loads the cheap units harder',c:()=>LEARN.done.ed===1},
  {t:'Are all LMPs equal? Set one line\'s rating below its flow and re-dispatch — congestion splits the prices by location',m:1},
  {t:'Close the loop: does the cheapest dispatch stay N−1 secure?',m:1}]},
 {id:'l7',title:'7 · Faults & protection',icon:'🛡️',goal:'Short-circuit strength, the critical clearing time, and the race relays must win.',steps:[
  {t:'Compute <b>short-circuit levels</b> (Studies): strong vs weak buses',c:()=>LEARN.done.sc===1},
  {t:'Find the <b>critical clearing time</b> for a fault near a generator',c:()=>LEARN.done.cct===1},
  {t:'A relay + breaker typically clears in 60–120 ms — compare with your CCT',m:1},
  {t:'Play the <b>equal-area lab</b> (this tab): watch A2 shrink as clearing is delayed',c:()=>LEARN.done.ea===1}]},
 {id:'l8',title:'8 · The modern grid',icon:'🛰️',goal:'FACTS devices, intelligent control and wide-area measurement — where the field is going.',steps:[
  {t:'Drop a FACTS device (SVC, TCSC, UPFC…) and watch the power flow react instantly',c:()=>!!NET&&(NET.facts||[]).length>0},
  {t:'Give the machines the fuzzy stabilizer — fleet preset <b>All SG+FLC</b> — and re-linearize: damping jumps',c:()=>!!NET&&NET.gens.some(g=>g.tag==='SGF')},
  {t:'Design a <b>POD</b> (Design tab) for the worst inter-area mode',c:()=>LEARN.done.pd===1},
  {t:'Place PMUs (Studies ▸ PMU placement) and show them on the diagram — the WAMS backbone',c:()=>LEARN.done.opp===1}]},
 {id:'l9',title:'9 · Inside a PV plant',icon:'☀️',goal:'From photons to grid support: the PV Lab, then the same physics on the grid.',steps:[
  {t:'In <b>PV Lab</b>, pull irradiance down to ~400 W/m² and heat the cells to 60&deg;C — watch WHICH axis each knob moves',c:()=>LEARN.done.pvcurve===1},
  {t:'Shade one substring to ~30% (bypass diodes ON) and find the GLOBAL peak among the local ones',c:()=>LEARN.done.pvshade===1},
  {t:'Start the MPPT on the shaded curve — watch it trap on a local peak, then rescue it with <b>Global scan</b>',c:()=>LEARN.done.pvmppt===1},
  {t:'On the grid: give a machine the PV technology (RES mix preset works) and run a <b>cloud transient</b> on the Time tab',c:()=>LEARN.done.cloud===1}]}];
function lrnStepOK(le,i){const st2=le.steps[i],key=le.id+'.'+i;
 if(LEARN.t[key])return true;
 if(st2.c){try{if(st2.c()){LEARN.t[key]=1;lrnSave();return true;}}catch(_){}}
 return false;}
function lrnRender(){const box=$('lnLessons');if(!box)return;
 let ndone=0,h='';
 for(const le of LESSONS){
  const oks=le.steps.map((_,i)=>lrnStepOK(le,i)),all=oks.every(Boolean);if(all)ndone++;
  const open=LEARN.open===le.id;
  h+=`<div class="card panel" style="margin-bottom:12px${all?';border-color:#86efac':''}">`+
   `<h3 style="cursor:pointer;display:flex;align-items:center;gap:8px;margin:0" onclick="LEARN.open=LEARN.open==='${le.id}'?null:'${le.id}';lrnSave();lrnRender()">`+
   `<span style="width:22px;text-align:center;flex:none">${all?'✅':le.icon}</span><span>${le.title}</span>`+
   `<span style="margin-left:auto;font-size:11.5px;color:${all?'#1e7a44':'var(--mut)'};font-weight:400;flex:none">${oks.filter(Boolean).length}/${le.steps.length}${all?' · complete':''}</span></h3>`;
  if(open){h+=`<div class="note" style="margin:6px 0 8px">${le.goal}</div>`;
   le.steps.forEach((st2,i)=>{const ok=oks[i];
    h+=`<div style="display:flex;gap:9px;align-items:flex-start;padding:6px 2px;border-top:1px solid var(--line)">`+
     `<span onclick="${st2.m?`lrnTick('${le.id}.${i}')`:'void 0'}" title="${st2.m?'click to mark done':'checked automatically from the live app state'}" style="cursor:${st2.m?'pointer':'default'};flex:none;width:19px;height:19px;border-radius:50%;border:2px solid ${ok?'#1e8449':'#cbd5e1'};background:${ok?'#1e8449':'#fff'};color:#fff;font-size:12px;line-height:15px;text-align:center">${ok?'✓':''}</span>`+
     `<span style="font-size:12.5px;line-height:1.45;${ok?'color:var(--mut)':''}">${st2.t}${st2.m?' <i style="color:#94a3b8;font-size:10.5px">(tick when done)</i>':''}</span></div>`;});}
  h+='</div>';}
 box.innerHTML=h;
 const qb=LEARN.qb||0,hd=$('lnHead');
 if(hd)hd.innerHTML=`<b>${ndone} of ${LESSONS.length}</b> lessons complete · quiz personal best: <b>${qb?qb+'%':'—'}</b>. The checks read the <b>live app state</b> — import, solve, design, and the steps tick themselves (grey circles are manual ticks). Progress is saved with the app; the quiz below is written from your own network.`;}
function lrnEnter(){if(LEARN.open===undefined)LEARN.open='l1';
 lrnRender();
 if(!LNBOOT){LNBOOT=1;
  $('eaSl').innerHTML=EASL.map(s2=>`<div class="easl"><span>${s2[1]}</span><input type="range" id="${s2[0]}" min="${s2[2]}" max="${s2[3]}" value="${s2[4]}" step="${s2[5]}" oninput="eaDraw(1)"><b id="${s2[0]}v">${s2[4]}</b></div>`).join('');
  try{eaDraw();}catch(_){}
  try{glRender('');}catch(_){}}}
// ---------- quiz ----------
let QZ=null;
async function qzNew(){const b=$('qzGo');b.disabled=true;$('spQZ').style.display='inline';$('qzErr').innerHTML='';
 const r=await api('/api/quiz',buildPayload({count:+$('qzN').value,seed:+$('qzSeed').value}));
 b.disabled=false;$('spQZ').style.display='none';
 if(r.error){$('qzErr').innerHTML=`<div class="err">${friendlyErr(r.error)}</div>`;return;}
 QZ=r;$('qzScore').textContent='';
 $('qzBody').innerHTML=r.questions.map((q,i)=>{
  let inp;
  if(q.kind==='num')inp=`<div class="row" style="margin-top:6px"><input type="number" step="any" id="qz_${i}" style="width:150px" placeholder="your answer"> <span class="note" style="align-self:center">${q.unit}</span></div>`;
  else inp='<div style="margin-top:6px">'+q.opts.map((o,j)=>`<label style="display:block;padding:3px 0;font-size:12.5px;cursor:pointer"><input type="radio" name="qz_${i}" value="${j}"> ${rexEsc(o)}</label>`).join('')+'</div>';
  return `<div class="card" style="padding:10px 12px;margin-bottom:10px">`+
   `<div style="font-size:13px;line-height:1.5"><b>Q${i+1}.</b> ${q.q}</div>${inp}`+
   `<div id="qze_${i}" style="display:none;margin-top:7px;padding:8px 10px;border-radius:6px;font-size:12px;line-height:1.5"></div></div>`;}).join('');
 $('qzGrade').style.display='';}
function qzGrade(){if(!QZ)return;let sc2=0;
 QZ.questions.forEach((q,i)=>{let ok=false,blank=false;
  if(q.kind==='num'){const v=parseFloat(($('qz_'+i)||{}).value);blank=!isFinite(v);ok=!blank&&Math.abs(v-q.a)<=q.tol;}
  else{const s2=document.querySelector(`input[name="qz_${i}"]:checked`);blank=!s2;ok=!!s2&&q.opts[+s2.value]===q.a;}
  if(ok)sc2++;
  const e=$('qze_'+i);if(e){e.style.display='';e.style.background=ok?'#f0fdf4':'#fef2f2';e.style.border='1px solid '+(ok?'#bbf7d0':'#fecaca');
   e.innerHTML=(ok?'<b style="color:#1e7a44">✓ correct</b>':`<b style="color:#b42318">✗ ${blank?'no answer':'not quite'}</b> — answer: <b>${rexEsc(String(q.a))}${q.kind==='num'?' '+q.unit:''}</b>`)+`<br>${q.explain}`;}});
 const pct=Math.round(100*sc2/QZ.questions.length);
 $('qzScore').innerHTML=`score: <b style="font-size:15px;color:${pct>=80?'#1e7a44':pct>=50?'#b7791f':'#b42318'}">${sc2}/${QZ.questions.length} (${pct}%)</b>${pct>(LEARN.qb||0)?' — new personal best!':''}`;
 if(pct>(LEARN.qb||0)){LEARN.qb=pct;lrnSave();}
 lrnMark('quiz');try{lrnRender();}catch(_){}}
// ---------- equal-area criterion lab (pure client-side physics) ----------
const EASL=[['eaPm','P_m — mechanical power (pu)',0.2,1.4,0.8,0.05],
 ['eaE','E — internal EMF (pu)',0.8,1.5,1.2,0.05],
 ['eaV','V — infinite bus (pu)',0.9,1.15,1.0,0.05],
 ['eaXr','X pre-fault (pu)',0.25,1.2,0.5,0.05],
 ['eaXf','X during fault (pu)',0.6,6,2.0,0.1],
 ['eaXp','X post-fault (pu)',0.25,2,0.7,0.05],
 ['eaDc','clearing angle δ_c (deg)',5,175,75,1],
 ['eaH','inertia H (s)',1,10,4,0.5]];
function eaDraw(user){const g=id=>+($(id)||{value:0}).value;
 const Pm=g('eaPm'),E=g('eaE'),V=g('eaV'),Xr=g('eaXr'),Xf=g('eaXf'),Xp=g('eaXp'),H=g('eaH');
 let dc=g('eaDc')*Math.PI/180;
 EASL.forEach(s2=>{const b=$(s2[0]+'v');if(b)b.textContent=$(s2[0]).value;});
 const Pr=E*V/Xr,Pf=E*V/Xf,Pp=E*V/Xp,out=$('eaOut'),el=$('eaChart');
 if(!out||!el)return;
 if(Pm>=Pr){out.innerHTML='<b style="color:#b42318">P_m exceeds the pre-fault maximum EV/X — no equilibrium exists even before the fault. Lower P_m or X pre-fault.</b>';el.innerHTML='';return;}
 if(Pm>=Pp){out.innerHTML='<b style="color:#b42318">P_m exceeds the POST-fault maximum EV/X_post — unstable for ANY clearing time: the weakened network cannot carry the load. Lower X post-fault.</b>';el.innerHTML='';return;}
 const d0=Math.asin(Pm/Pr),dmax=Math.PI-Math.asin(Pm/Pp);
 dc=Math.max(d0,Math.min(dc,dmax));
 const A1=Pm*(dc-d0)+Pf*(Math.cos(dc)-Math.cos(d0));
 const A2=Pp*(Math.cos(dc)-Math.cos(dmax))-Pm*(dmax-dc);
 const ccr=(Pm*(dmax-d0)-Pf*Math.cos(d0)+Pp*Math.cos(dmax))/(Pp-Pf);
 const dcr=(ccr>=-1&&ccr<=1)?Math.acos(ccr):null;
 let cct=null;
 if(dcr!=null&&dcr>d0){const M=2*H/(2*Math.PI*60);let d=d0,w2=0,t2=0;const dt=2e-4;
  while(t2<3){const k1w=(Pm-Pf*Math.sin(d))/M,k1d=w2,
   k2w=(Pm-Pf*Math.sin(d+0.5*dt*k1d))/M,k2d=w2+0.5*dt*k1w,
   k3w=(Pm-Pf*Math.sin(d+0.5*dt*k2d))/M,k3d=w2+0.5*dt*k2w,
   k4w=(Pm-Pf*Math.sin(d+dt*k3d))/M,k4d=w2+dt*k3w;
   d+=dt*(k1d+2*k2d+2*k3d+k4d)/6;w2+=dt*(k1w+2*k2w+2*k3w+k4w)/6;t2+=dt;
   if(d>=dcr){cct=t2;break;}
   if(w2<0&&t2>0.02)break;}}
 const w0=el.clientWidth||520,h0=300,ymax=Math.max(Pr,Pp,Pm)*1.12;
 const A=axes(w0,h0,0,180,0,ymax,'rotor angle δ (deg)','electrical power P_e (pu)');let s2=A.s;
 const seg=(a,b,P1,fill)=>{let pts='';
  for(let k=0;k<=24;k++){const dd=a+(b-a)*k/24;pts+=`${A.X(dd*180/Math.PI).toFixed(1)},${A.Y(Pm).toFixed(1)} `;}
  for(let k=24;k>=0;k--){const dd=a+(b-a)*k/24;pts+=`${A.X(dd*180/Math.PI).toFixed(1)},${A.Y(P1*Math.sin(dd)).toFixed(1)} `;}
  return `<polygon points="${pts}" fill="${fill}" stroke="none"/>`;};
 s2+=seg(d0,dc,Pf,'rgba(180,35,24,0.26)');
 s2+=seg(dc,dmax,Pp,'rgba(30,132,73,0.22)');
 const curve=(Pmx,col,wd,dash)=>{let d2='';for(let k=0;k<=180;k+=2){d2+=(d2?'L':'M')+A.X(k).toFixed(1)+' '+A.Y(Pmx*Math.sin(k*Math.PI/180)).toFixed(1);}
  return `<path d="${d2}" fill="none" stroke="${col}" stroke-width="${wd}"${dash?` stroke-dasharray="${dash}"`:''}/>`;};
 s2+=curve(Pr,'#94a3b8',1.3,'5 4')+curve(Pf,'#b42318',1.9)+curve(Pp,'#1e8449',1.9);
 s2+=`<line x1="${A.X(0)}" y1="${A.Y(Pm)}" x2="${A.X(180)}" y2="${A.Y(Pm)}" stroke="#1f3b73" stroke-width="1.8"/>`;
 const vl=(dd,lab,col)=>`<line x1="${A.X(dd*180/Math.PI).toFixed(1)}" y1="${A.T}" x2="${A.X(dd*180/Math.PI).toFixed(1)}" y2="${h0-A.B}" stroke="${col}" stroke-dasharray="3 3" stroke-width="1"/><text x="${A.X(dd*180/Math.PI).toFixed(1)}" y="${A.T+11}" text-anchor="middle" font-size="10.5" fill="${col}">${lab}</text>`;
 s2+=vl(d0,'δ0','#475569')+vl(dc,'δc','#b45309')+vl(dmax,'δmax','#1e8449');
 if(dcr!=null)s2+=vl(dcr,'δcr','#b42318');
 el.innerHTML=`<svg viewBox="0 0 ${w0} ${h0}" width="100%">${s2}</svg>`+
  `<div style="display:flex;gap:12px;font-size:11px;color:var(--mut);flex-wrap:wrap;margin-top:2px">`+
  `<span style="color:#94a3b8">— pre-fault</span><span style="color:#b42318">— during fault</span><span style="color:#1e8449">— post-fault</span><span style="color:#1f3b73">— P_m</span>`+
  `<span><span style="display:inline-block;width:10px;height:10px;background:rgba(180,35,24,.26)"></span> A1 accelerating</span>`+
  `<span><span style="display:inline-block;width:10px;height:10px;background:rgba(30,132,73,.22)"></span> A2 decelerating (available)</span></div>`;
 const stab=A2>=A1;
 out.innerHTML=`A1 (kinetic energy gained) = <b>${A1.toFixed(3)}</b> · A2 (available to shed) = <b>${A2.toFixed(3)}</b> → `+
  (stab?`<b style="color:#1e7a44">STABLE</b> — margin ${(100*(A2-A1)/Math.max(A1,1e-9)).toFixed(0)}%`
       :`<b style="color:#b42318">UNSTABLE</b> — the rotor passes δmax with kinetic energy to spare`)+
  (dcr!=null?` · critical angle δ_cr = <b>${(dcr*180/Math.PI).toFixed(1)}°</b>`+
   (cct!=null?` · CCT ≈ <b>${(cct*1000).toFixed(0)} ms</b> for H = ${H} s (RK4 on the fault-on swing equation, 60 Hz)`:'')
   :' · no critical angle for these curves (stable for any clearing angle)');
 if(user)lrnMark('ea');}
// ---------- glossary ----------
const GLOSS=[
 ['AVR (automatic voltage regulator)','The exciter control that holds a machine\'s terminal voltage at its set-point. Fast, high-gain AVRs rescue voltage but erode oscillation damping — the reason stabilizers exist.','ss'],
 ['Base MVA / per-unit','All PSDAT equations run on a 100 MVA system base: quantity ÷ base = per-unit. Impedances of machines are converted from their own rating, which is why a small machine looks "far away" electrically.',''],
 ['Bus','A network node (a substation busbar). Solver types: PQ (load — P and Q fixed), PV (generator — P and |V| fixed), slack (angle reference; absorbs the loss mismatch).','net'],
 ['CCT (critical clearing time)','The longest a fault can stay on before the machines lose synchronism. Found here by bisection on the full nonlinear simulation; the equal-area criterion is its one-machine theory.','st'],
 ['COI (centre of inertia)','The inertia-weighted average of all machine angles/speeds — the "average clock" of the grid. Frequency plots use it so local swings do not masquerade as system frequency.','td'],
 ['Contingency (N−1)','Loss of any single element. A secure operating point survives every one of them — the fundamental planning and operating criterion.','st'],
 ['Damping ratio ζ','For an eigenvalue σ ± jω: ζ = −σ/√(σ²+ω²). Under 3% is trouble, 5–10% is the usual planning floor; the amplitude of each swing shrinks by e^(−2πζ/√(1−ζ²)) per cycle.','ss'],
 ['DC power flow','Linearized power flow: flat voltages, small angles, losses ignored → P = B′θ. One matrix solve, no iteration — the workhorse of markets (DC-OPF) and fast screening.','st'],
 ['Droop','Proportional frequency (or voltage) control: a 5% droop governor gives 100% power change for a 5% frequency change. It is what lets many units share load without fighting.',''],
 ['Economic dispatch','Minimize total generation cost subject to meeting demand: run every unit at equal marginal cost λ — the "equal-λ" rule — unless a limit binds.','st'],
 ['Eigenvalue / mode','λ = σ ± jω of the linearized system: ω/2π is the oscillation frequency, σ the decay rate. Electromechanical modes live at 0.1–3 Hz.','ss'],
 ['Equal-area criterion','Graphical transient-stability test for one machine vs an infinite bus: stable iff the decelerating area A2 can absorb the accelerating area A1. Interactive lab on the Learn tab.','ln'],
 ['Exciter','The DC/static system feeding the rotor field winding. Its speed and ceiling decide how hard the machine can push reactive power during a fault.',''],
 ['FACTS','Flexible AC Transmission Systems — power-electronic devices (SVC, STATCOM, TCSC, SSSC, UPFC, IPFC) that control voltage, reactance or line flow within cycles. All six are in the Draw palette.','net'],
 ['Fast-decoupled power flow','Stott–Alsac 1974: exploit the P–θ / Q–V decoupling of high-X/R grids to iterate two constant matrices. Linear convergence, tiny cost per iteration.',''],
 ['Fault (three-phase)','All three phases shorted — the most severe balanced fault and the standard stability test. Studies ▸ short-circuit gives the current; Studies ▸ CCT the survivable duration.','st'],
 ['Frequency nadir','The lowest COI frequency after losing generation. Set by inertia (first seconds), governor speed (next seconds) and load damping.','td'],
 ['Gauss-Seidel','The 1950s power-flow method: sweep bus by bus updating voltages. Simple, memory-light, and slow — hundreds of sweeps where Newton needs four iterations.',''],
 ['GFL (grid-following converter)','Measures the grid angle with a PLL and injects current into an existing voltage. Plentiful today, but it needs a grid to follow — it cannot start or hold one.',''],
 ['GFM (grid-forming converter)','Sets its own voltage magnitude and frequency (droop/VSM), behaving like a fast synchronous machine. The key technology for very-high-renewable grids.',''],
 ['Governor','The turbine controller that moves mechanical power against frequency error (droop). It sets the frequency recovery after the inertial response.',''],
 ['H (inertia constant)','Stored kinetic energy at rated speed ÷ machine MVA, in seconds (2–9 s typical). The 2H/ωs term is what resists RoCoF in the first instants.',''],
 ['Infinite bus','An idealized node of fixed voltage and frequency — the "rest of the grid" in one-machine studies like the equal-area lab.','ln'],
 ['Inter-area mode','A low-frequency (0.1–0.8 Hz) oscillation of one GROUP of machines against another, spanning long corridors. The classic WAMS/POD target; Kundur two-area is its textbook home.','ss'],
 ['Islanding','An outage that splits the network into disconnected parts. The N−1 screen flags these outright — power flow is not even attempted.','st'],
 ['Jacobian','The matrix of first derivatives of the power-balance equations. Newton-Raphson solves J·Δx = −mismatch each iteration; its singularity IS the nose of the P–V curve.',''],
 ['LMP (locational marginal price)','The cost of serving one more MW at a bus = the dual variable of that bus\'s balance constraint in the OPF. Congestion and losses make it differ by location.','st'],
 ['Loadability / nose point','The maximum load the network can steadily supply — the fold of the P–V curve, where the power-flow Jacobian goes singular.','st'],
 ['Low-inertia grid','A system where converters displace synchronous machines: less stored kinetic energy, faster RoCoF, deeper nadirs — and new controls (GFM, fast reserves) to compensate.',''],
 ['Modal analysis / participation factor','Eigenvectors weighted to show HOW MUCH each state participates in each mode — the map from "a 0.6 Hz mode exists" to "areas 1 and 2 swing against each other".','ss'],
 ['Newton-Raphson','Quadratic-convergence root finding on the mismatch equations (Tinney &amp; Hart 1967). The default PSDAT solver: 3–5 iterations to 1e-13.',''],
 ['Observability (WAMS)','A bus is observable if its voltage phasor can be measured or derived. The PMU placement study finds the cheapest fully-observable sensor set.','st'],
 ['OPF (optimal power flow)','Dispatch that minimizes cost subject to the NETWORK constraints (balance, line limits). PSDAT\'s DC-OPF returns dispatch, binding lines and LMPs.','st'],
 ['PLL (phase-locked loop)','The synchronizer a GFL converter uses to track the grid angle. In weak (low short-circuit) grids the PLL itself can destabilize — a very modern failure mode.',''],
 ['PMU (phasor measurement unit)','A GPS-synchronized sensor streaming voltage/current phasors 30–60 times a second — the eyes of the wide-area measurement system.','st'],
 ['POD (power oscillation damper)','A washout + lead-lag controller on a FACTS device or converter that phases its output against an oscillation — designed on the Design tab from residues.','ds'],
 ['Power flow (load flow)','THE steady-state calculation: given loads and dispatch, find every bus voltage magnitude and angle. Everything else in the course starts from its solution.','net'],
 ['PSS (power system stabilizer)','A supplementary exciter input (from speed/power) that adds damping torque. PSDAT also ships a fuzzy-logic version — the SGF machine — that needs no linear model.','ss'],
 ['Reactive power Q','The oscillating power of fields, in MVAr. It does no average work but sets every voltage magnitude in the grid; it travels badly, so support must be local.',''],
 ['RoCoF','Rate of change of frequency (Hz/s) right after an imbalance: RoCoF = Δp·f0/(2H_sys). The first casualty of low inertia; relays trip on it.','td'],
 ['Rotor angle δ','The electrical angle of a machine\'s rotor EMF vs the synchronous reference. Its second-order dynamics ARE the swing equation; losing synchronism = δ running away.',''],
 ['Short-circuit MVA','√3·V·I_f at a bus — the "strength" of the grid there. High = stiff voltage, happy converters; low = weak grid, careful tuning. SCR = S_sc/S_converter.','st'],
 ['Slack bus','The angle reference of the power flow; its generator absorbs the loss mismatch no other unit scheduled. Exactly one per island.',''],
 ['Small-signal stability','Stability of the linearization around the operating point: all eigenvalues in the left half-plane, with enough damping ratio on the oscillatory ones.','ss'],
 ['SSSC','Static Synchronous Series Compensator — a series VSC injecting a controllable quadrature voltage; unlike a TCSC it works at low line current.','net'],
 ['STATCOM','A shunt VSC holding bus voltage by injecting reactive current, |I| limited — so its support survives low voltage far better than an SVC\'s Q = BV².','net'],
 ['SVC','Static VAR Compensator — thyristor-switched/controlled shunt susceptance regulating bus voltage; output falls with V², its classic weakness.','net'],
 ['Swing equation','(2H/ωs)·d²δ/dt² = P_m − P_e: Newton\'s law for the rotor. Every transient-stability idea in the course is a statement about this equation.','ln'],
 ['Synchronous generator','The rotating machine behind ~still-most of the world\'s MWh: EMF from a DC-excited rotor, inertia for free, fault current for protection — the reference every converter is compared to.',''],
 ['TCSC','Thyristor-Controlled Series Capacitor — continuously variable series compensation that shortens a line electrically, boosting transfer and (with a POD) damping oscillations.','net'],
 ['Transient stability','Surviving the LARGE disturbance — fault, line loss — where linearization no longer applies and the full nonlinear swing dynamics decide. CCT is its currency.','st'],
 ['UPFC','Unified Power Flow Controller — shunt + series VSCs on one DC link: simultaneous control of bus voltage AND line P, Q. The most capable (and expensive) FACTS device.','net'],
 ['WAMS','Wide-Area Measurement System: PMUs + communications + analytics watching the whole interconnection in real time — inter-area modes, angle separations, oscillation alarms.','st'],
 ['Zero-injection bus','A bus with no load and no generation: KCL there is exact, so one unmeasured neighbour can be deduced — free observability in PMU placement.','st'],
 ['ZIP / voltage-dependent load','Load as constant-Z + constant-I + constant-P mix. The mix decides how demand relieves (or not) as voltage sags — and it moves the nose of the P–V curve.',''],
 ['Bypass diode','A diode across each substring of a PV module that conducts when the substring is shaded, letting the rest of the string keep its current — the reason a shaded P–V curve has several peaks instead of a dead string (and no hot spots).','pvl'],
 ['Capacity factor','Energy actually produced over a period divided by rated-power-times-hours. Typical PV: 15–25% — the day/night and weather arithmetic of panel 5 in the PV Lab.','pvl'],
 ['Fill factor','FF = P_mp/(V_oc·I_sc): how "square" the I–V curve is. Crystalline silicon sits near 0.7–0.85; it drops as cells heat or degrade.','pvl'],
 ['Incremental conductance','MPPT rule that compares dI/dV with −I/V (equivalently watches dP/dV): quieter at the peak than P&O, equally blind to OTHER peaks under partial shading.','pvl'],
 ['Irradiance / STC','Solar power density on the array plane (W/m²). Standard Test Conditions: 1000 W/m², 25 °C cell temperature, AM1.5 — the datasheet operating point every rating refers to.','pvl'],
 ['MPPT','Maximum-power-point tracking: the control that keeps a PV array at the knee of its P–V curve as sun and temperature move it. P&O and incremental conductance are the classroom pair — race them in the PV Lab.','pvl'],
 ['Partial shading','Unequal irradiance across a string. With bypass diodes it carves the P–V curve into multiple local maxima; a hill-climbing MPPT can settle on the wrong one, which is why trackers add periodic global scans.','pvl'],
 ['Perturb & Observe (P&O)','The workhorse MPPT: step the voltage, watch the power, keep going if it rose, turn around if it fell. It must oscillate around the peak to know the peak is there.','pvl'],
 ['Performance ratio','Harvested energy divided by what the incident irradiance offered a lossless STC array — the honest single number for a plant, discounting temperature, mismatch and conversion losses.','pvl'],
 ['Power reserve (de-loading)','Running a PV plant below its available maximum — PSDAT parks the operating point ABOVE V_mp on the stable right branch — so headroom exists for frequency support without a battery.','pvl'],
 ['Single-diode model','The standard PV cell circuit: photocurrent, diode, series/shunt resistance. PSDAT uses its classical explicit approximation I = G·i_sc[1 − C₁(e^{V/(C₂v_oc)} − 1)], anchored at V_oc and the STC MPP.','pvl'],
 ['Temperature coefficient','How ratings drift with cell temperature: V_oc ≈ −0.3%/°C, I_sc ≈ +0.05%/°C for silicon — hot panels lose voltage, and with it power, even in perfect sun.','pvl']];
function glRender(q){const el=$('glBody');if(!el)return;q=(q||'').toLowerCase();
 const rows=GLOSS.slice().sort((a,b)=>a[0].localeCompare(b[0]))
  .filter(g=>!q||g[0].toLowerCase().includes(q)||g[1].toLowerCase().includes(q));
 el.innerHTML=rows.map(g=>`<div style="padding:8px 2px;border-top:1px solid var(--line)">`+
  `<b style="font-size:12.5px">${g[0]}</b>${g[2]?` <a style="font-size:11px;color:#1d4ed8;cursor:pointer" onclick="goTab('${g[2]}')" title="open the tab where this lives">open ▸</a>`:''}`+
  `<div style="font-size:12px;color:#475569;margin-top:2px;line-height:1.5">${g[1]}</div></div>`).join('')
  ||'<div class="rexempty">no term matches — try a shorter search</div>';}
// ================== PV LAB — deep-dive photovoltaics ======================
// The SAME explicit single-diode model as the engine (units.py, normalised to
// the STC maximum-power point: V=1, I=1, P=1; voc=Voc/Vmp, isc=Isc/Imp).
// The laboratory adds the classical first-order temperature coefficients
// (about -0.29%/K on Voc, +0.05%/K on Isc) so their effect can be SEEN; the
// grid engine itself runs at STC cell temperature.
const PVLM={voc:1.25,isc:1.08};
PVLM.C2=(1/PVLM.voc-1)/Math.log(1-1/PVLM.isc);
PVLM.C1=(1-1/PVLM.isc)*Math.exp(-1/(PVLM.C2*PVLM.voc));
function pvlCv(G,T){const vocT=PVLM.voc*(1-0.0029*(T-25)),iscT=G*PVLM.isc*(1+0.0005*(T-25));
 return {vocT,iscT,I:V=>Math.max(0,iscT*(1-PVLM.C1*(Math.exp(V/(PVLM.C2*vocT))-1)))};}
function pvlMPP(cv){let bv=0,bp=0;
 for(let k=1;k<300;k++){const V=cv.vocT*k/300,P=V*cv.I(V);if(P>bp){bp=P;bv=V;}}
 let a=Math.max(0.01,bv-cv.vocT/300),b=Math.min(cv.vocT,bv+cv.vocT/300);
 for(let i=0;i<36;i++){const c=a+(b-a)*0.382,d=a+(b-a)*0.618;
  if(c*cv.I(c)>d*cv.I(d))b=d;else a=c;}
 const V=(a+b)/2;return [V,V*cv.I(V)];}
function pvlAxes(el,x1,y1,xl,yl,h){const w=el.clientWidth||330;h=h||205;
 return {A:axes(w,h,0,x1,0,y1*1.06,xl,yl),w,h};}
let PVLB=0;
function pvlEnter(){if(!PVLB){PVLB=1;
  $('pl1S').innerHTML=
   '<div class="pvsl"><span>irradiance G (W/m&sup2;)</span><input type="range" id="pl1G" min="100" max="1200" value="1000" step="20" oninput="pvlP1(1)"><b id="pl1Gv">1000</b></div>'+
   '<div class="pvsl"><span>cell temperature (&deg;C)</span><input type="range" id="pl1T" min="-10" max="75" value="25" step="1" oninput="pvlP1(1)"><b id="pl1Tv">25</b></div>';
  $('pl2S').innerHTML=[1,2,3].map(k=>
   `<div class="pvsl"><span>substring ${k} irradiance %</span><input type="range" id="pl2G${k}" min="5" max="100" value="${k===2?30:100}" step="5" oninput="pvlP2(1)"><b id="pl2G${k}v">${k===2?30:100}%</b></div>`).join('');
  pvlP1();pvlP2();pvlP3Setup();pvlP4();pvlP5();pvlGS();}
 else{pvlP1();pvlP2();}}
function pvlReset(){pvlP3Stop();
 if(!PVLB)return;
 $('pl1G').value=1000;$('pl1T').value=25;
 [1,2,3].forEach(k=>{$('pl2G'+k).value=(k===2?30:100);});
 $('pl2Byp').checked=true;$('pl4R').value=10;$('pl5C').value=35;
 $('pl3Shade').checked=false;$('pl3Scen').value='steady';
 pvlP1();pvlP2();pvlP3Setup();pvlP4();pvlP5();}
// ---- panel 1: I-V / P-V ---------------------------------------------------
function pvlP1(user){const G=+$('pl1G').value/1000,T=+$('pl1T').value;
 $('pl1Gv').textContent=$('pl1G').value;$('pl1Tv').textContent=T;
 const cv=pvlCv(G,T),[Vm,Pm]=pvlMPP(cv),Im=Pm/Vm;
 const {A,w,h}=pvlAxes($('pl1IV'),PVLM.voc*1.06,PVLM.isc*1.25,'V (pu of Vmp@STC)','I (pu)');
 let sI=A.s,d='';
 for(let k=0;k<=200;k++){const V=cv.vocT*k/200;d+=(d?'L':'M')+A.X(V).toFixed(1)+' '+A.Y(cv.I(V)).toFixed(1);}
 sI+=`<path d="${d}" fill="none" stroke="#b45309" stroke-width="2"/>`;
 sI+=`<circle cx="${A.X(Vm)}" cy="${A.Y(Im)}" r="4" fill="#1f3b73"/>`;
 sI+=`<text x="${A.X(Vm)+6}" y="${A.Y(Im)-7}" font-size="10" fill="#1f3b73" font-weight="700">MPP</text>`;
 sI+=`<text x="${A.X(0)+5}" y="${A.Y(cv.iscT)-5}" font-size="10" fill="#b45309">I_sc = ${cv.iscT.toFixed(3)}</text>`;
 sI+=`<text x="${A.X(cv.vocT)-4}" y="${A.Y(0)-6}" font-size="10" fill="#b45309" text-anchor="end">V_oc = ${cv.vocT.toFixed(3)}</text>`;
 $('pl1IV').innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${sI}</svg>`;
 const B=pvlAxes($('pl1PV'),PVLM.voc*1.06,1.15,'V (pu)','P (pu of Pmp@STC)');
 let sP=B.A.s,d2='';
 for(let k=0;k<=200;k++){const V=cv.vocT*k/200;d2+=(d2?'L':'M')+B.A.X(V).toFixed(1)+' '+B.A.Y(V*cv.I(V)).toFixed(1);}
 sP+=`<path d="${d2}" fill="none" stroke="#1e8449" stroke-width="2"/>`;
 sP+=`<circle cx="${B.A.X(Vm)}" cy="${B.A.Y(Pm)}" r="4" fill="#1f3b73"/>`;
 sP+=`<line x1="${B.A.X(Vm)}" y1="${B.A.Y(Pm)}" x2="${B.A.X(Vm)}" y2="${B.A.Y(0)}" stroke="#1f3b73" stroke-dasharray="3 3" stroke-width="1"/>`;
 $('pl1PV').innerHTML=`<svg viewBox="0 0 ${B.w} ${B.h}" width="100%">${sP}</svg>`;
 const FF=Pm/(cv.vocT*cv.iscT);
 $('pl1Out').innerHTML=`MPP: <span class="pvbig">${Pm.toFixed(3)} pu</span> at V = ${Vm.toFixed(3)}, I = ${Im.toFixed(3)} &middot; fill factor FF = P<sub>mp</sub>/(V<sub>oc</sub>I<sub>sc</sub>) = <b>${FF.toFixed(3)}</b>.
  Irradiance scales the CURRENT almost linearly; temperature moves the VOLTAGE (&asymp;&minus;0.29%/K) — hot panels lose power even in bright sun. <span style="color:var(--mut)">Two stated properties of the explicit fit, shared with the grid engine: V<sub>oc</sub> does not move with G (good above &asymp;200 W/m&sup2;), and the curve&rsquo;s true maximum sits &asymp;1.5% above the V&nbsp;=&nbsp;1 anchor.</span>`;
 if(user)lrnMark('pvcurve');
 if(user&&$('pl3Scen'))pvlP3Setup();}
// ---- panel 2: partial shading ----------------------------------------------
let PVL2=null;
function pvlP2(user){if(!$('pl2G1'))return;
 const T=+$('pl1T').value,byp=$('pl2Byp').checked;
 const Gs=[1,2,3].map(k=>{const v=+$('pl2G'+k).value;$('pl2G'+k+'v').textContent=v+'%';return v/100;});
 const base=pvlCv(1,T),voc3=base.vocT/3;
 const sub=Gs.map(g=>({isc:g*base.iscT}));
 const Vk=(ss,I)=>{if(I>=ss.isc*0.99995)return byp?-0.018:-(I-ss.isc)*1.4;
  return Math.max(-0.02,PVLM.C2*voc3*Math.log(1+(1-I/ss.isc)/PVLM.C1));};
 const Imax=Math.max(...sub.map(z=>z.isc)),N=460,Vs=[],Is=[],Ps=[];let hot=false;
 for(let k=0;k<=N;k++){const I=Imax*k/N;
  let V=0;for(const ss of sub){const v=Vk(ss,I);V+=v;if(v<-0.25)hot=true;}
  if(V<=0&&k>0)break;
  Vs.push(Math.max(0,V));Is.push(I);Ps.push(Math.max(0,V)*I);}
 // local maxima of P over V (parametrised by I; V is decreasing in I)
 const peaks=[];
 for(let k=1;k<Ps.length-1;k++)if(Ps[k]>Ps[k-1]&&Ps[k]>=Ps[k+1]&&Ps[k]>0.02)peaks.push(k);
 let gk=0;Ps.forEach((p,k)=>{if(p>Ps[gk])gk=k;});
 const ideal=Gs.reduce((a,g)=>a+pvlMPP(pvlCv(g,T))[1]/3,0);
 const {A,w,h}=pvlAxes($('pl2IV'),PVLM.voc*1.06,PVLM.isc*1.25,'string V (pu)','I (pu)');
 let sI=A.s,d='';
 for(let k=0;k<Vs.length;k++)d+=(d?'L':'M')+A.X(Vs[k]).toFixed(1)+' '+A.Y(Is[k]).toFixed(1);
 sI+=`<path d="${d}" fill="none" stroke="#b45309" stroke-width="2"/>`;
 $('pl2IV').innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${sI}</svg>`;
 const B=pvlAxes($('pl2PV'),PVLM.voc*1.06,1.15,'string V (pu)','P (pu)');
 let sP=B.A.s,d2='';
 for(let k=0;k<Vs.length;k++)d2+=(d2?'L':'M')+B.A.X(Vs[k]).toFixed(1)+' '+B.A.Y(Ps[k]).toFixed(1);
 sP+=`<path d="${d2}" fill="none" stroke="#1e8449" stroke-width="2"/>`;
 for(const k of peaks)if(k!==gk)sP+=`<circle cx="${B.A.X(Vs[k])}" cy="${B.A.Y(Ps[k])}" r="4" fill="#fff" stroke="#b42318" stroke-width="1.8"/>`;
 sP+=`<circle cx="${B.A.X(Vs[gk])}" cy="${B.A.Y(Ps[gk])}" r="4.6" fill="#1f3b73"/><text x="${B.A.X(Vs[gk])+6}" y="${B.A.Y(Ps[gk])-7}" font-size="10" font-weight="700" fill="#1f3b73">global</text>`;
 $('pl2PV').innerHTML=`<svg viewBox="0 0 ${B.w} ${B.h}" width="100%">${sP}</svg>`;
 PVL2={Vs,Ps};
 const mm=100*(ideal-Ps[gk])/Math.max(ideal,1e-9);
 $('pl2Out').innerHTML=(byp?`<b>${peaks.length}</b> peak${peaks.length>1?'s':''} — bypass diodes let the unshaded substrings keep conducting, so the I&ndash;V curve becomes a staircase and the P&ndash;V curve grows <b>local maxima</b> (hollow red). Global MPP <b>${Ps[gk].toFixed(3)} pu</b> at V = ${Vs[gk].toFixed(2)}; ideal (no mismatch) ${ideal.toFixed(3)} pu &rarr; mismatch loss <b>${mm.toFixed(1)}%</b>. A tracker that climbs the nearest hill can lose the difference between the tallest peaks — panel 3 shows it happening.`
  :`<b style="color:#b42318">No bypass diodes:</b> the whole string is throttled to the weakest substring's current${hot?' and the shaded cells are driven into <b>reverse bias — hot-spot damage territory</b>':''}. Output ${Ps[gk].toFixed(3)} pu vs ${ideal.toFixed(3)} pu ideal (${mm.toFixed(1)}% lost). Re-enable the diodes and compare.`);
 if(user&&byp&&peaks.length>1)lrnMark('pvshade');
 if(user)pvlP3Setup();}
// ---- panel 3: MPPT playground ----------------------------------------------
let PVT={run:0,timer:null,V:0.8,dir:1,Pp:-1,Vp:0.79,t:0,hist:[],scan:-1,best:[0,0]};
function pvlP3Pfun(){ // returns {P(V),vmax,Pmp} for the current scenario state
 const shade=$('pl3Shade').checked&&PVL2&&PVL2.Vs.length>5;
 const cf=($('pl3Scen').value==='cloud')?pvlCloud(PVT.t):1;
 if(shade){const Vs=PVL2.Vs,Ps=PVL2.Ps;
  const P=V=>{ // linear interpolation on the panel-2 curve (V descending in index)
   if(V<=0||V>=Vs[0])return 0;
   let lo=0,hi=Vs.length-1;
   while(hi-lo>1){const md=(lo+hi)>>1;(Vs[md]>V)?lo=md:hi=md;}
   const f=(Vs[lo]-V)/Math.max(Vs[lo]-Vs[hi],1e-9);
   return Math.max(0,(Ps[lo]+f*(Ps[hi]-Ps[lo]))*cf);};
  let pm=0;for(let k=0;k<Ps.length;k++)if(Ps[k]*cf>pm)pm=Ps[k]*cf;
  return {P,vmax:Vs[0],Pmp:pm};}
 const cv=pvlCv((+$('pl1G').value/1000)*cf,+$('pl1T').value);
 const [_,Pm]=pvlMPP(cv);
 return {P:V=>Math.max(0,V*cv.I(V)),vmax:cv.vocT,Pmp:Pm};}
function pvlCloud(t){const x=(t%260)/260;      // deterministic passing cloud
 if(x<0.25)return 1;if(x<0.4)return 1-0.6*(x-0.25)/0.15;
 if(x<0.6)return 0.4;if(x<0.75)return 0.4+0.6*(x-0.6)/0.15;return 1;}
function pvlP3Setup(){pvlP3Stop();PVT.V=0.8;PVT.dir=1;PVT.Pp=-1;PVT.Vp=0.79;PVT.t=0;PVT.hist=[];PVT.scan=-1;
 pvlP3Draw();}
function pvlP3Run(){if(PVT.run){pvlP3Stop();return;}
 PVT.run=1;$('pl3Go').textContent='Pause';
 PVT.timer=setInterval(pvlP3Tick,90);}
function pvlP3Stop(){PVT.run=0;if(PVT.timer){clearInterval(PVT.timer);PVT.timer=null;}
 const b=$('pl3Go');if(b)b.textContent='Start';}
function pvlP3Scan(){if(PVT.scan<0){PVT.scan=0;PVT.best=[PVT.V,0];if(!PVT.run)pvlP3Run();}}
function pvlP3Tick(){const F=pvlP3Pfun(),dv=Math.max(0.002,Math.min(0.06,+$('pl3Dv').value||0.01));
 PVT.t++;
 if(PVT.scan>=0){ // global sweep: 46 frames across the range, then jump to best
  const V=0.04+(F.vmax-0.06)*PVT.scan/45,P=F.P(V);
  if(P>PVT.best[1])PVT.best=[V,P];
  PVT.V=V;PVT.scan++;
  if(PVT.scan>45){PVT.V=PVT.best[0];PVT.scan=-1;PVT.Pp=-1;lrnMark('pvmppt');}}
 else{const P=F.P(PVT.V);
  if($('pl3Algo').value==='ic'){const dP=P-PVT.Pp,dV=PVT.V-PVT.Vp;PVT.Vp=PVT.V;
   const g=Math.abs(dV)>1e-9?dP/dV:0;
   PVT.V+=(g>0.004?dv:g<-0.004?-dv:0)*(PVT.Pp<0?1:1);}
  else{if(PVT.Pp>=0&&P<PVT.Pp)PVT.dir=-PVT.dir;PVT.V+=PVT.dir*dv;}
  PVT.Pp=P;
  PVT.V=Math.max(0.04,Math.min(F.vmax-0.01,PVT.V));}
 PVT.hist.push([F.P(PVT.V),F.Pmp]);if(PVT.hist.length>240)PVT.hist.shift();
 if(PVT.t>130)lrnMark('pvmppt');
 if(PVT.t%2===0)pvlP3Draw(F);}
function pvlP3Draw(F){F=F||pvlP3Pfun();
 const el=$('pl3Chart'),{A,w,h}=pvlAxes(el,PVLM.voc*1.06,1.15,'operating voltage V (pu)','P (pu)');
 let s2=A.s,d='';
 for(let k=0;k<=240;k++){const V=F.vmax*k/240;d+=(d?'L':'M')+A.X(V).toFixed(1)+' '+A.Y(F.P(V)).toFixed(1);}
 s2+=`<path d="${d}" fill="none" stroke="#1e8449" stroke-width="2"/>`;
 s2+=`<line x1="${A.X(PVT.V)}" y1="${A.Y(0)}" x2="${A.X(PVT.V)}" y2="${A.Y(F.P(PVT.V))}" stroke="#b45309" stroke-width="1.2" stroke-dasharray="3 3"/>`;
 s2+=`<circle cx="${A.X(PVT.V)}" cy="${A.Y(F.P(PVT.V))}" r="6" fill="#b45309" stroke="#fff" stroke-width="1.6"/>`;
 $('pl3Chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s2}</svg>`;
 if(PVT.hist.length>4&&PVT.t%4===0){
  const t2=PVT.hist.map((_,i)=>i),got=PVT.hist.map(z=>z[0]),avail=PVT.hist.map(z=>z[1]);
  lineChart($('pl3Strip'),t2,{'harvested P':got,'available P_mp':avail},'ticks','P (pu)');
  const eff=100*got.reduce((a,b)=>a+b,0)/Math.max(1e-9,avail.reduce((a,b)=>a+b,0));
  $('pl3Out').innerHTML=`tracking efficiency over the window: <span class="pvbig">${eff.toFixed(1)}%</span> &middot; ${$('pl3Algo').value==='po'?'P&amp;O reverses direction whenever power falls — it must oscillate around the peak to know it is there.':'Incremental conductance holds still when dP/dV &asymp; 0 — quieter at the peak, same hill-climbing blindness on multi-peak curves.'} ${$('pl3Shade').checked?'<b>Shaded curve:</b> if the dot settled on a hollow-red peak of panel 2, press <b>Global scan</b>.':''}`;}}
// ---- panel 4: reserve + capability + IEEE 1547 ------------------------------
function pvlP4(user){if(!$('pl4R'))return;
 const r=+$('pl4R').value;$('pl4Rv').textContent=r;
 const G=+($('pl1G')?$('pl1G').value:1000)/1000,T=+($('pl1T')?$('pl1T').value:25);
 const cv=pvlCv(G,T),[Vm,Pm]=pvlMPP(cv),Pt=(1-r/100)*Pm;
 let lo=Vm,hi=cv.vocT*0.999;               // upper-branch bisection (engine method)
 for(let i=0;i<40;i++){const md=(lo+hi)/2;(md*cv.I(md)>Pt)?lo=md:hi=md;}
 const Vop=(lo+hi)/2,Pop=Vop*cv.I(Vop);
 const {A,w,h}=pvlAxes($('pl4Curve'),PVLM.voc*1.06,1.15,'V (pu)','P (pu)',195);
 let s2=A.s,d='';
 for(let k=0;k<=200;k++){const V=cv.vocT*k/200;d+=(d?'L':'M')+A.X(V).toFixed(1)+' '+A.Y(V*cv.I(V)).toFixed(1);}
 s2+=`<path d="${d}" fill="none" stroke="#1e8449" stroke-width="2"/>`;
 s2+=`<circle cx="${A.X(Vm)}" cy="${A.Y(Pm)}" r="4" fill="#94a3b8"/><text x="${A.X(Vm)}" y="${A.Y(Pm)-8}" font-size="10" text-anchor="middle" fill="#64748b">MPP</text>`;
 s2+=`<circle cx="${A.X(Vop)}" cy="${A.Y(Pop)}" r="5" fill="#1f3b73"/><text x="${A.X(Vop)+7}" y="${A.Y(Pop)-6}" font-size="10" font-weight="700" fill="#1f3b73">operating</text>`;
 s2+=`<path d="M${A.X(Vm)} ${A.Y(Pm)+10} L${A.X(Vop)} ${A.Y(Pop)+10}" stroke="#b45309" stroke-width="1.4" marker-end="" stroke-dasharray="4 3"/>`;
 $('pl4Curve').innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s2}</svg>`;
 // capability half-circle (inverter rated at the STC MPP power)
 const el2=$('pl4Cap'),w2=el2.clientWidth||300,h2=180,cx=w2/2,cy=h2-24,R=Math.min(w2*0.42,h2-40);
 let c='<path d="M'+(cx-R)+' '+cy+' A'+R+' '+R+' 0 0 1 '+(cx+R)+' '+cy+'" fill="#eef2ff" stroke="#cfd6e2"/>';
 c+=`<line x1="${cx-R-6}" y1="${cy}" x2="${cx+R+6}" y2="${cy}" stroke="#9aa4b2"/>`;
 const Pp=Math.min(1,Pop),Qa=Math.sqrt(Math.max(0,1-Pp*Pp));
 c+=`<line x1="${cx-Qa*R}" y1="${cy-Pp*R}" x2="${cx+Qa*R}" y2="${cy-Pp*R}" stroke="#1e8449" stroke-width="2.4"/>`;
 c+=`<circle cx="${cx}" cy="${cy-Pp*R}" r="4.4" fill="#1f3b73"/>`;
 c+=`<text x="${cx}" y="${cy-R-6}" font-size="10.5" text-anchor="middle" fill="#374151">P (up) vs Q (right/left), S = 1 pu</text>`;
 c+=`<text x="${cx+Qa*R}" y="${cy-Pp*R-7}" font-size="10" fill="#1e8449" text-anchor="end">&plusmn;Q available = ${Qa.toFixed(2)} pu</text>`;
 el2.innerHTML=`<svg viewBox="0 0 ${w2} ${h2}" width="100%">${c}</svg>`;
 $('pl4Out').innerHTML=`Holding <b>${r}%</b> reserve parks the array at V = <b>${Vop.toFixed(3)}</b> pu — on the <b>right (high-voltage) branch</b>, exactly as the engine's de-loading routine does: the DC-link regulator is stable there, and stepping the voltage reference back toward V<sub>mp</sub> releases <b>${(Pm-Pop).toFixed(3)} pu</b> of headroom within cycles for Freq&ndash;Watt support. The green chord on the half-circle is the reactive range the inverter can offer at this real-power output — the room Volt&ndash;VAR works in.`;
 if(user)lrnMark('pvreserve');}
function pvlGS(){ // IEEE-1547-style default curves, drawn once
 const el=$('pl4GS'),w=el.clientWidth||300,h=180;
 const mini=(x0,x1,pts,xl,col,ox,oy,ww,hh)=>{
  const X=v=>ox+ (v-x0)/(x1-x0)*ww, Y=v=>oy+hh-(v+1)/2*hh;
  let m=`<rect x="${ox}" y="${oy}" width="${ww}" height="${hh}" fill="none" stroke="#e2e8f0"/>`;
  m+=`<line x1="${ox}" y1="${Y(0)}" x2="${ox+ww}" y2="${Y(0)}" stroke="#eef1f6"/>`;
  let d='';for(const [x,y] of pts)d+=(d?'L':'M')+X(x).toFixed(1)+' '+Y(y).toFixed(1);
  m+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="1.8"/>`;
  m+=`<text x="${ox+ww/2}" y="${oy+hh+11}" font-size="9.5" text-anchor="middle" fill="#64748b">${xl}</text>`;
  return m;};
 let s2='<text x="4" y="11" font-size="10.5" fill="#374151" font-weight="700">IEEE 1547-style grid-support curves (the units’ own controllers)</text>';
 s2+=mini(0.9,1.1,[[0.9,1],[0.92,1],[0.98,0],[1.02,0],[1.08,-1],[1.1,-1]],'Volt-VAR: Q vs V','#1d4ed8',8,22,w*0.29,h-58);
 s2+=mini(1.0,1.12,[[1.0,1],[1.06,1],[1.10,-0.0],[1.12,0]],'Volt-Watt: P vs V','#b45309',8+w*0.345,22,w*0.29,h-58);
 s2+=mini(59.2,60.8,[[59.2,1],[59.964,1],[60.036,0.4],[60.8,-0.6]],'Freq-Watt: P vs f','#1e8449',8+2*w*0.345,22,w*0.29,h-58);
 el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%">${s2}</svg>`;}
// ---- panel 5: a day of energy ------------------------------------------------
function pvlP5(){if(!$('pl5C'))return;
 const c=+$('pl5C').value/100;$('pl5Cv').textContent=$('pl5C').value+'%';
 const dip=t=>{let v=0;for(const [m,w2,a] of [[10.6,0.5,0.8],[13.1,0.8,0.95],[15.3,0.45,0.7],[16.6,0.35,0.5]])
  v+=a*Math.exp(-((t-m)*(t-m))/(2*w2*w2));return Math.min(0.92,v);};
 const ts=[],Gs=[],Psr=[];let E=0,H=0;
 for(let t=5;t<=21;t+=1/12){const clear=Math.max(0,Math.sin(Math.PI*(t-5.6)/13.2));
  const G=Math.max(0,clear*(1-c*dip(t)));
  const Tamb=14+16*Math.max(0,Math.sin(Math.PI*(t-7.6)/13));
  const T=Tamb+28*G;                       // NOCT rule: cells run ~28 K above ambient at full sun
  const P=G>0.02?pvlMPP(pvlCv(G,T))[1]:0;
  ts.push(t);Gs.push(100*G);Psr.push(100*P);E+=P/12;H+=G/12;}
 lineChart($('pl5Chart'),ts,{'irradiance (% of STC)':Gs,'MPP power (% of rated)':Psr},'hour of day','%');
 const CF=100*E/24,PR=100*E/Math.max(H,1e-9);
 $('pl5Out').innerHTML=`Energy: <span class="pvbig">${E.toFixed(2)} kWh per kW<sub>p</sub></span> today &middot; capacity factor ${CF.toFixed(1)}% &middot; performance ratio ${PR.toFixed(1)}% <span style="color:var(--mut)">(energy harvested &divide; energy the irradiance offered to a lossless STC array; cell temperature follows the NOCT rule T<sub>cell</sub> = T<sub>ambient</sub> + 28&thinsp;K&middot;G, so the gap IS the heat — clear the clouds and watch PR fall as the panels cook in peak sun)</span>. Rooftop reality check: 4&ndash;5 kWh/kW<sub>p</sub> is a good sunny day; a 5-kW<sub>p</sub> roof at today's profile earns ${(5*E).toFixed(1)} kWh.`;}
function pvlToTD(){goTab('td');
 try{$('dkind').value='cloud';$('dkind').onchange();}catch(_){}
 stat('cloud transient preset — set a machine to PV-GFL/PV-GFM first (RES mix preset does it), then Run simulation');}
// ---------- init ----------
// global safety net: an uncaught error must never take the whole app down
window.addEventListener('error',ev=>{try{
  if(PNEW){PNEW=null;document.body.classList.remove('dropping');}
  if(DDRAG){DDRAG=null;}
  const el=$('stMsg');if(el)el.textContent='recovered from an error — still running';}catch(_){}});
window.addEventListener('unhandledrejection',()=>{});
(async()=>{try{META=await api('/api/meta');
 applyUI((META.ui&&META.ui.scale)||0.7,false);
 LAY=loadLayout(META.ui&&META.ui.layout);
 if(META.ui&&typeof META.ui.mmap!=='undefined')MMAP=!!META.ui.mmap;  // off by default; honour a saved choice
 try{if(META.ui&&META.ui.viz2)vizLoad(META.ui.viz2);}catch(_){}                     // saved heat-map / motion / label tuning (v2 key; the v1 key is retired)
 try{const L0=META.ui&&META.ui.learn;if(L0&&typeof L0==='object')LEARN=Object.assign({t:{},done:{},qb:0},L0);}catch(_){}   // course progress
 applyLayout(false);syncView();
 const updClip=()=>{const r=$('ribbon');            // ribbon scroller clips its
  if(r)r.classList.toggle('mopen',!!r.querySelector('.menu.open'));};  // dropdowns unless told not to
 document.querySelectorAll('.menu>button').forEach(b=>{
  b.onclick=e=>{e.stopPropagation();const m=b.parentElement,was=m.classList.contains('open');
   document.querySelectorAll('.menu').forEach(x=>x.classList.remove('open'));
   if(!was)m.classList.add('open');updClip();};
  b.onmouseenter=()=>{if(document.querySelector('.menu.open')){
   document.querySelectorAll('.menu').forEach(x=>x.classList.remove('open'));
   b.parentElement.classList.add('open');updClip();}};});
 window.addEventListener('click',()=>{document.querySelectorAll('.menu').forEach(x=>x.classList.remove('open'));updClip();});
 $('sys').innerHTML=Object.entries(META.systems).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
 $('sys').onchange=()=>{if($('sys').value!=='__custom')loadNet($('sys').value);};   // import -> the diagram becomes the model
 try{buildSide();}catch(_){}
 $('scen').innerHTML=Object.entries(META.scenarios).map(([k,v])=>`<div class="sc" onclick="runS('${k}')"><b>${k}</b><p>${v}</p></div>`).join('');
 $('runL').onclick=runL;$('runT').onclick=runT;try{$('dkind').onchange();}catch(_){}
 $('runSw').onclick=runSw;$('runPd').onclick=runPd;$('runBd').onclick=runBd;
 $('mApply').onclick=applyPar;$('mReset').onclick=resetPar;$('mClose').onclick=closePar;
 $('modal').onclick=e=>{if(e.target.id==='modal')closePar();};
 $('pdM').onchange=()=>{$('pdBw').style.display=$('pdM').value==='diff'?'':'none';};
 $('bdO').onchange=()=>{$('bdAw').style.display=$('bdO').value==='unit'?'':'none';};
 $('kbd').onclick=e=>{if(e.target.id==='kbd')e.target.style.display='none';};
 $('sld').addEventListener('mousemove',e=>{const el=$('stPos');if(el&&NET){const[wx,wy]=s2w(e);el.textContent=`${Math.round(wx)}, ${Math.round(wy)}`;} sldTip(e);});
 $('sld').addEventListener('mouseleave',()=>{const tp=$('sldTip');if(tp)tp.style.display='none';});
 const _ping=()=>{fetch('/api/ping').catch(()=>{});};
 setInterval(_ping,15000);
 setInterval(()=>{if(TAB==='ln'&&!document.hidden)try{lrnRender();}catch(_){}},2500);   // lessons re-check the live state
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)_ping();});
 window.addEventListener('focus',_ping);          // wake the heartbeat when refocused
 $('sld').addEventListener('mousedown',sldDown);
 $('sld').addEventListener('wheel',sldWheel,{passive:false});
 $('sld').addEventListener('contextmenu',e=>e.preventDefault());
 window.addEventListener('mousemove',sldMove);
 window.addEventListener('mouseup',sldUp);
 window.addEventListener('keydown',sldKey);
 window.addEventListener('resize',()=>{if(NET)draw();});
 // dock-panel dragging: grab a panel title to float it; drop near an edge to dock
 document.addEventListener('mousedown',e=>{const sp=e.target.closest('.dhead [data-drag]');
  if(!sp)return;e.preventDefault();
  const id=sp.dataset.drag,el=pnEl(id),r=el.getBoundingClientRect();
  DRAGP={id,dx:e.clientX-r.left,dy:e.clientY-r.top,moved:false,zone:null};});
 window.addEventListener('mousemove',e=>{if(!DRAGP)return;
  const P=LAY.p[DRAGP.id];
  if(!DRAGP.moved){DRAGP.moved=true;
   if(P.d!=='float'){P.d='float';applyLayout(false);}
   pnEl(DRAGP.id).classList.add('dragging');}
  const el=pnEl(DRAGP.id);
  P.x=e.clientX-DRAGP.dx;P.y=e.clientY-DRAGP.dy;
  el.style.left=(P.x/UIS)+'px';el.style.top=(P.y/UIS)+'px';
  const c=$('cwrap').getBoundingClientRect();
  DRAGP.zone=null;
  if(e.clientX>c.left-10&&e.clientX<c.right+10&&e.clientY>c.top-10&&e.clientY<c.bottom+10){
   if(e.clientX<c.left+70)DRAGP.zone='left';
   else if(e.clientX>c.right-70)DRAGP.zone='right';
   else if(e.clientY>c.bottom-70)DRAGP.zone='bottom';}
  $('dhL').style.display=DRAGP.zone==='left'?'block':'none';
  $('dhR').style.display=DRAGP.zone==='right'?'block':'none';
  $('dhB').style.display=DRAGP.zone==='bottom'?'block':'none';});
 window.addEventListener('mouseup',()=>{if(!DRAGP)return;
  const dp=DRAGP;DRAGP=null;
  $('dhL').style.display=$('dhR').style.display=$('dhB').style.display='none';
  const el=pnEl(dp.id);if(el)el.classList.remove('dragging');
  if(!dp.moved)return;
  if(dp.zone)pnDock(dp.id,dp.zone);else applyLayout();});
 // minimap: click to recentre · drag a box to zoom into that region
 $('mmap').addEventListener('mousedown',e=>{e.preventDefault();e.stopPropagation();
  const w=mm2w(e);if(!w)return;MMD=true;MMR={x0:w[0],y0:w[1],x1:w[0],y1:w[1],moved:false,cx:e.clientX,cy:e.clientY};});
 window.addEventListener('mousemove',e=>{if(!MMD||!MMR)return;const w=mm2w(e);if(!w)return;
  MMR.x1=w[0];MMR.y1=w[1];
  if(!MMR.moved&&Math.hypot(e.clientX-MMR.cx,e.clientY-MMR.cy)>5)MMR.moved=true;
  mmDraw();});
 window.addEventListener('mouseup',()=>{if(!MMD)return;MMD=false;
  if(MMR&&MMR.moved)zoomWorldRect(MMR.x0,MMR.y0,MMR.x1,MMR.y1);
  else if(MMR){VB[0]=MMR.x0-VB[2]/2;VB[1]=MMR.y0-VB[3]/2;draw();}   // click = recentre
  MMR=null;});
 // palette drag-and-drop: press a component in the Draw palette, drag onto the canvas, release.
 // The moving preview is drawn INSIDE the SVG at s2w(cursor) — so it sits exactly under the
 // pointer and lands exactly where shown, at any zoom (no floating HTML chip to drift).
 document.addEventListener('mousedown',e=>{const btn=e.target.closest('.pcol .tbtn.tool');
  if(!btn)return;const t=btn.dataset.tool;
  if(!DNODE.includes(t)&&!DEDGE.includes(t))return;
  PNEW={tool:t,edge:DEDGE.includes(t),x0:e.clientX,y0:e.clientY,active:false,over:false};});
 window.addEventListener('mousemove',e=>{try{if(!PNEW)return;
  if(!PNEW.active){if(Math.hypot(e.clientX-PNEW.x0,e.clientY-PNEW.y0)<6)return;
   PNEW.active=true;document.body.classList.add('dropping');
   if(TAB!=='net')goTab('net');
   if(PNEW.edge){setTool(PNEW.tool);
    stat('drop on the FIRST bus — then click (or drag to) the second to finish the '+NEWLBL[PNEW.tool].toLowerCase());}
   else{const need=['addbus','addnote'].includes(PNEW.tool)?'the canvas':'a bus bar';
    stat('drop the '+NEWLBL[PNEW.tool].toLowerCase()+' on '+need+' — it follows your cursor');}}
  const ov=overCanvas(e)&&!LOCKED;PNEW.over=ov;
  if(ov){const w=s2w(e);PNEW.wx=w[0];PNEW.wy=w[1];}
  qdraw();}catch(err){PNEW=null;document.body.classList.remove('dropping');}});
 window.addEventListener('mouseup',e=>{if(!PNEW)return;const p=PNEW;PNEW=null;
  document.body.classList.remove('dropping');
  if(!p.active)return;                          // no drag: the button's click set the tool
  try{
   if(LOCKED||!overCanvas(e)){draw();return;}
   const w=s2w(e);if(!isFinite(w[0])||!isFinite(w[1])){draw();return;}
   if(p.edge){                                  // Line / Double / Transformer: arm the tool,
    setTool(p.tool);const bi=busAt(w[0],w[1]);  // and pick the first bus if dropped on one
    if(bi>=0){DPEND=bi;stat('now click (or drag to) the second bus to finish the '+NEWLBL[p.tool].toLowerCase());}
    else stat(NEWLBL[p.tool]+' tool ready — click the first bus, then the second');
    draw();
   }else placeNode(p.tool,w[0],w[1]);
  }catch(err){draw();}});
 // dock-column width resize: drag the splitter between a dock column and the canvas
 let RSZ=null;
 for(const sid of ['splitL','splitR']){$(sid).addEventListener('mousedown',e=>{
   e.preventDefault();const side=$(sid).dataset.side;
   RSZ={side,x0:e.clientX,w0:side==='left'?LAY.wL:LAY.wR};$(sid).classList.add('act');});}
 window.addEventListener('mousemove',e=>{if(!RSZ)return;
  const d=(e.clientX-RSZ.x0)/UIS,w=Math.max(120,Math.min(460,RSZ.w0+(RSZ.side==='left'?d:-d)));
  if(RSZ.side==='left'){LAY.wL=w;$('dockL').style.width=w+'px';}
  else{LAY.wR=w;$('dockR').style.width=w+'px';}
  if(NET)draw();});
 window.addEventListener('mouseup',()=>{if(!RSZ)return;
  $('splitL').classList.remove('act');$('splitR').classList.remove('act');RSZ=null;saveLayout();});
 if(window.ResizeObserver){let rz=0;
  new ResizeObserver(()=>{if(NET&&!rz)rz=requestAnimationFrame(()=>{rz=0;draw();});}).observe($('cwrap'));}
 loadNet('IEEE9');
 }catch(e){try{console.error('init',e);const el=$('stMsg');if(el)el.textContent='startup error: '+e.message;}catch(_){}}
})();
</script>
<style id="scada-css">
/* ============ SCADA / Operator mode (desktop) ============ */
#scban{flex:none;display:none;align-items:center;gap:10px;height:34px;box-sizing:border-box;
 padding:0 14px;font:600 12.5px system-ui;cursor:pointer;box-shadow:0 2px 8px rgba(16,24,40,.10)}
#scban .dot{width:9px;height:9px;border-radius:5px;flex:none}
#scban .txt{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#scban .cnt{flex:none;font-weight:700;font-size:11px;padding:2px 9px;border-radius:99px;background:rgba(255,255,255,.6)}
#scban.ok{background:#eefaf1;color:#1c7a43;border-bottom:1px solid #c7ead2}#scban.ok .dot{background:#1e7a44}
#scban.warn{background:#fff7ed;color:#8a5a00;border-bottom:1px solid #f6ddb0}#scban.warn .dot{background:#b7791f}
#scban.crit{background:#fef2f2;color:#b42318;border-bottom:1px solid #f3c3c3}#scban.crit .dot{background:#d92d20}
#scban.flash .dot{animation:scfl 1s steps(2) infinite}
@keyframes scfl{50%{opacity:.15}}
.scrow{display:flex;gap:10px;align-items:flex-start;padding:9px 4px;border-top:1px solid #eef1f6;font-size:13px;color:#1a2230}
.scrow:first-of-type{border-top:0}
.scrow .sdot{width:10px;height:10px;border-radius:5px;flex:none;margin-top:3px}
.scrow .stime{flex:none;color:#8b93a3;font:600 11px system-ui;margin-top:1px;font-variant-numeric:tabular-nums}
.scrow .stxt{flex:1;min-width:0;line-height:1.45;overflow-wrap:anywhere}
.scrow.ack{opacity:.55}
.scrow .sack{flex:none;border:1px solid #d6ddea;background:#fff;color:#1f3b73;border-radius:6px;padding:4px 10px;font:600 11.5px system-ui;cursor:pointer}
.scact{display:block;width:100%;margin-top:10px;padding:11px;border:0;border-radius:8px;background:#1f3b73;color:#fff;font:600 13.5px system-ui;cursor:pointer}
.scact.warn{background:#b7791f}.scact.danger{background:#d92d20}.scact.gray{background:#5b6270}.scact.teal{background:#117a8b}
.scstat{margin-left:auto;flex:none;display:inline-block;padding:3px 10px;border-radius:99px;font:700 10.5px system-ui;letter-spacing:.03em}
.scstat.closed{background:#eefaf1;color:#1c7a43}.scstat.open{background:#fef2f2;color:#b42318}
.scseg{display:flex;gap:6px;margin:0 0 8px}
.scseg button{flex:1;border:1px solid #cfd6e2;background:#f3f6fb;color:#41506a;border-radius:8px;padding:7px;font:600 12.5px system-ui;cursor:pointer}
.scseg button.on{background:#1f3b73;border-color:#1f3b73;color:#fff}
.scinfo{display:flex;justify-content:space-between;gap:14px;padding:8px 2px;border-top:1px solid #eef1f6;font-size:13px}
.scinfo:first-of-type{border-top:0}
.scinfo .k{color:#68707e}.scinfo .v{color:#1a2230;font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.schd{display:flex;align-items:center;gap:10px;margin:2px 0 6px}
.schd .ic{width:30px;height:30px;flex:none;display:flex;align-items:center;justify-content:center;
 border-radius:8px;background:#eef3ff;color:#1f3b73;font:700 13px system-ui}
.schd .tt{font:600 15px Georgia,serif;color:#1f3b73}
html.dark #scban.ok{background:#0f2418;color:#58c07c;border-bottom-color:#1f4a2e}
html.dark #scban.warn{background:#251d0e;color:#e0b25f;border-bottom-color:#4a3a17}
html.dark #scban.crit{background:#2a1517;color:#f1a09b;border-bottom-color:#5c2726}
html.dark #scban .cnt{background:rgba(0,0,0,.3)}
html.dark .scrow{color:#dbe3f2;border-top-color:#232d45}
html.dark .scrow .sack{background:#151d2f;border-color:#33405f;color:#9db9f0}
html.dark .scact{background:#2c5aa0}
html.dark .scact.warn{background:#a06a12}html.dark .scact.danger{background:#c03024}
html.dark .scstat.closed{background:#0f2418;color:#58c07c}html.dark .scstat.open{background:#2a1517;color:#f1a09b}
html.dark .scseg button{background:#131b2d;border-color:#2e3b58;color:#a9b6cf}
html.dark .scseg button.on{background:#2c5aa0;border-color:#2c5aa0;color:#fff}
html.dark .scinfo{border-top-color:#232d45}
html.dark .scinfo .k{color:#7f8ba3}html.dark .scinfo .v{color:#dbe3f2}
html.dark .schd .ic{background:#1d2a49;color:#9db9f0}
html.dark .schd .tt{color:#9db9f0}
</style>
<script>
/* ================= PSDAT desktop: night toggle + SCADA operator mode =========
   Ported from the PSDAT Mobile edition: emulated telemetry on a fixed scan
   cycle, select-before-operate switching, alarm annunciator + SOE log, per-tag
   trends, WLS state estimation with bad-data detection, disturbance drills. */
function toggleNight(){
 var dark=!document.documentElement.classList.contains('dark');
 document.documentElement.classList.toggle('dark',dark);
 try{localStorage.setItem('psdat_theme',dark?'dark':'light');}catch(_){}
 var c=document.getElementById('vNight');if(c)c.style.visibility=dark?'visible':'hidden';
 try{qdraw();}catch(_){}
 try{stat(dark?'night theme on — the diagram keeps its day appearance':'day theme on');}catch(_){}}
(function(){
'use strict';
var SCADA=window.SCADA={on:false,iv:0,scanMs:2000,t0:0,trueDPF:null,telem:null,
 alarms:[],soe:[],trend:{},sel:null,armed:null,aseg:'alarms',prevLock:false,
 badInj:null,scenario:null,pending:null,drill:null,_asig:''};
var _nsp=null;function nrand(){if(_nsp!==null){var v=_nsp;_nsp=null;return v;}
 var u,w,s2;do{u=Math.random()*2-1;w=Math.random()*2-1;s2=u*u+w*w;}while(s2>=1||s2===0);
 var m=Math.sqrt(-2*Math.log(s2)/s2);_nsp=w*m;return u*m;}
function ts(t){var d=new Date(t);return d.toTimeString().slice(0,8)+'.'+('00'+d.getMilliseconds()).slice(-3);}
function soe(txt,kind){SCADA.soe.unshift({t:Date.now(),txt:txt,kind:kind||'op'});
 if(SCADA.soe.length>400)SCADA.soe.length=400;}
function trendPush(k,t,v){var a=SCADA.trend[k]||(SCADA.trend[k]=[]);a.push([t,v]);if(a.length>150)a.shift();}
function captureTruth(){if(typeof DPF!=='undefined'&&DPF)SCADA.trueDPF=DPF;}
/* ---- modals ---------------------------------------------------------------*/
var MODALS={};
function scModal(id,title,w){if(MODALS[id])return MODALS[id];
 var bg=document.createElement('div');bg.className='modalbg';bg.id='scm_'+id;bg.style.display='none';
 bg.innerHTML='<div class="modal" style="width:'+(w||620)+'px"><h3>'+title+'</h3>'
  +'<div class="mbody" style="max-height:62vh;padding-bottom:12px"></div>'
  +'<div class="mrow"><button class="ghost" data-x>Close</button></div></div>';
 bg.addEventListener('click',function(e){if(e.target===bg)bg.style.display='none';});
 bg.querySelector('[data-x]').onclick=function(){bg.style.display='none';};
 document.body.appendChild(bg);
 MODALS[id]={bg:bg,body:bg.querySelector('.mbody')};return MODALS[id];}
function scShow(id){var m=MODALS[id];if(m)m.bg.style.display='flex';}
function isOpen(id){var m=MODALS[id];return m&&m.bg.style.display!=='none';}
window.scadaOpen=function(id){
 if(!SCADA.on){try{stat('tip: start the SCADA operator mode (Tools menu) for live telemetry');}catch(_){}}
 if(id==='alarms'){scModal('alarms','Alarms & events',640);alarmsRender(true);scShow('alarms');}
 else if(id==='se'){scModal('se','State estimation (WLS)',700);seRender();scShow('se');}
 else if(id==='drill'){scModal('drill','Disturbance drill',600);drillRender();scShow('drill');}};
/* ---- mode enter / exit ----------------------------------------------------*/
window.scadaToggle=function(){SCADA.on?scadaExit():scadaEnter();};
function scadaEnter(){
 if(typeof NET==='undefined'||!NET||!NET.buses.length){try{stat('load a network before starting a SCADA session');}catch(_){}return;}
 SCADA.on=true;SCADA.t0=Date.now();SCADA.trend={};SCADA.armed=null;SCADA.sel=null;
 try{SCADA.prevLock=(typeof LOCKED!=='undefined')&&LOCKED;setLock(true);}catch(_){}
 try{setTool('select');}catch(_){}
 captureTruth();
 if(!SCADA.trueDPF){try{if(typeof runActive==='function')runActive();}catch(_){}}
 SCADA.scanMs=NET.buses.length<=60?2000:5000;
 if(SCADA.iv)clearInterval(SCADA.iv);
 SCADA.iv=setInterval(scadaScan,SCADA.scanMs);
 soe('operator session started — '+(NET.name||'network')+' ('+NET.buses.length+' buses, scan '+(SCADA.scanMs/1000)+' s)','sys');
 var c=document.getElementById('vScada');if(c)c.style.visibility='visible';
 bannerSync();
 try{stat('SCADA operator mode — click any component to control it (layout locked)');}catch(_){}}
function scadaExit(){
 SCADA.on=false;if(SCADA.iv){clearInterval(SCADA.iv);SCADA.iv=0;}
 if(SCADA.trueDPF)DPF=SCADA.trueDPF;
 soe('operator session ended','sys');
 try{setLock(!!SCADA.prevLock);}catch(_){}
 var c=document.getElementById('vScada');if(c)c.style.visibility='hidden';
 if(SCADA.drill&&SCADA.drill.active){SCADA.drill.active=false;SCADA.drill.done=true;SCADA.drill.debrief=drillDebrief();}
 SCADA.badInj=null;
 Object.keys(MODALS).forEach(function(k){MODALS[k].bg.style.display='none';});
 bannerSync();try{qdraw();}catch(_){}
 try{stat('SCADA session ended — edit mode restored');}catch(_){}}
/* ---- click-to-control on the diagram (mouseup + hit-test: the canvas
        re-renders on mousedown, so a native click never fires on the SVG) ----*/
var _scDown=null;
document.addEventListener('mousedown',function(e){
 if(SCADA.on)_scDown={x:e.clientX,y:e.clientY};},true);
document.addEventListener('mouseup',function(e){
 if(!SCADA.on)return;
 if(typeof TAB!=='undefined'&&TAB!=='net')return;
 if(!_scDown||Math.hypot(e.clientX-_scDown.x,e.clientY-_scDown.y)>6)return;
 var sld=document.getElementById('sld');if(!sld)return;
 var tgt=document.elementFromPoint(e.clientX,e.clientY);
 if(!tgt||!sld.contains(tgt))return;
 var el=tgt.closest('[data-el]');if(!el)return;
 var t=el.getAttribute('data-el');if(t==='note'||t==='facts')return;
 SCADA.sel={t:t,i:+el.getAttribute('data-i')};SCADA.armed=null;
 scModal('ctl','Control & telemetry',560);scadaCtlRefresh();scShow('ctl');
},true);
/* ---- scan cycle -----------------------------------------------------------*/
function scadaScan(){
 if(!SCADA.on)return;
 if(document.hidden)return;
 if(!SCADA.trueDPF){captureTruth();if(!SCADA.trueDPF)return;}
 var T=SCADA.trueDPF,n=NET.buses.length,t=(Date.now()-SCADA.t0)/1000;
 var D=Object.assign({},T);
 D.V=T.V?T.V.map(function(v){return v*(1+nrand()*0.0012);}):T.V;
 D.th=T.th?T.th.map(function(a){return a+nrand()*0.03;}):T.th;
 if(T.flows)D.flows=T.flows.map(function(f){if(!f)return f;
  return Object.assign({},f,{Pf:f.Pf*(1+nrand()*0.004)+nrand()*0.05,
                             Qf:f.Qf*(1+nrand()*0.004)+nrand()*0.05});});
 if(SCADA.badInj){var bi=SCADA.badInj;
  if(bi.k==='V'&&D.V&&D.V[bi.i]!==undefined)D.V=D.V.map(function(v,q){return q===bi.i?v+bi.bias:v;});
  else if(D.flows&&D.flows[bi.i]){var f2=Object.assign({},D.flows[bi.i]);
   if(bi.k==='Pf')f2.Pf+=bi.bias*100;else if(bi.k==='Qf')f2.Qf+=bi.bias*100;
   D.flows=D.flows.slice();D.flows[bi.i]=f2;}}
 DPF=D;SCADA.telem=D;
 drillTick();
 NET.buses.forEach(function(b,q){if(D.V&&D.V[q]!==undefined)trendPush('V'+q,t,D.V[q]);});
 if(D.flows)NET.branches.forEach(function(br,q){var f=D.flows[q];
  if(f&&!br.off)trendPush('S'+q,t,Math.hypot(f.Pf,f.Qf));});
 alarmEval();bannerSync();
 if((typeof TAB==='undefined'||TAB==='net')&&n<=150){try{qdraw();}catch(_){}}
 if(isOpen('ctl'))scadaCtlRefresh();
 if(isOpen('alarms'))alarmsRender();
 if(isOpen('drill')&&SCADA.drill&&SCADA.drill.active)drillRender();
}
/* ---- alarm engine ---------------------------------------------------------*/
function raiseAl(key,sev,txt,act){act[key]=1;
 var ex=null;for(var k=0;k<SCADA.alarms.length;k++){var a=SCADA.alarms[k];
  if(a.key===key&&a.active){ex=a;break;}}
 if(ex){if(sev>ex.sev){ex.sev=sev;ex.txt=txt;ex.ack=false;ex.t=Date.now();
   soe('ALARM (escalated) '+txt,'alarm');}
  else ex.txt=txt;
  return;}
 SCADA.alarms.unshift({key:key,sev:sev,txt:txt,t:Date.now(),ack:false,active:true});
 if(SCADA.alarms.length>120)SCADA.alarms.length=120;
 soe((sev===2?'ALARM ':'warning ')+txt,'alarm');}
function alarmEval(){if(!SCADA.on)return;var act={},T=SCADA.trueDPF;
 if(T&&T.V)NET.buses.forEach(function(b,i){var v=T.V[i];if(v===undefined)return;
  var nm='bus '+(i+1)+(b.name?' ('+b.name+')':'');
  if(v<0.90)raiseAl('uv'+i,2,'UNDERVOLTAGE '+nm+' — '+v.toFixed(3)+' pu',act);
  else if(v<0.95)raiseAl('uv'+i,1,'low voltage '+nm+' — '+v.toFixed(3)+' pu',act);
  if(v>1.10)raiseAl('ov'+i,2,'OVERVOLTAGE '+nm+' — '+v.toFixed(3)+' pu',act);
  else if(v>1.05)raiseAl('ov'+i,1,'high voltage '+nm+' — '+v.toFixed(3)+' pu',act);});
 if(T&&T.flows)NET.branches.forEach(function(br,i){
  if(br.off||!(br.rate>0))return;var f=T.flows[i];if(!f)return;
  var pct=Math.hypot(f.Pf,f.Qf)/br.rate*100;
  if(pct>=100)raiseAl('ol'+i,2,'OVERLOAD line '+br.f+'–'+br.t+' — '+pct.toFixed(0)+'% of rating',act);
  else if(pct>=90)raiseAl('ol'+i,1,'high loading line '+br.f+'–'+br.t+' — '+pct.toFixed(0)+'%',act);});
 var ne=document.getElementById('netErr');
 if(ne&&ne.textContent.trim())raiseAl('pf',2,'SOLVE FAILED — system state unknown. '+ne.textContent.trim().slice(0,90),act);
 SCADA.alarms.forEach(function(a){if(a.active&&!act[a.key]){a.active=false;
  soe('returned to normal — '+a.txt,'alarm');}});
 SCADA.alarms=SCADA.alarms.filter(function(a){return a.active||!a.ack;});
}
function bannerSync(){var ban=document.getElementById('scban');if(!ban)return;
 ban.style.display=SCADA.on?'flex':'none';if(!SCADA.on)return;
 var actA=SCADA.alarms.filter(function(a){return a.active;});
 var un=SCADA.alarms.filter(function(a){return !a.ack;});
 var crit=un.some(function(a){return a.sev===2;});
 ban.className=(actA.length?(actA.some(function(a){return a.sev===2;})?'crit':'warn'):'ok')+(crit?' flash':'');
 var top=(un.length?un:actA).slice().sort(function(a,b2){return (b2.sev-a.sev)||(b2.t-a.t);})[0];
 ban.querySelector('.txt').textContent='SCADA — '+(actA.length?top.txt
  :('system normal · supervisory scan '+(SCADA.scanMs/1000)+' s · click a component to control it'));
 ban.querySelector('.cnt').textContent=actA.length?(un.length?un.length+' unack':'all ack'):'OK';}
/* ---- alarms & events modal ------------------------------------------------*/
function alarmsRender(force){var M=MODALS.alarms;if(!M)return;var b=M.body;
 var sig=SCADA.aseg+'|'+SCADA.alarms.length+'|'+SCADA.alarms.filter(function(a){return !a.ack;}).length
  +'|'+SCADA.alarms.filter(function(a){return a.active;}).length+'|'+SCADA.soe.length
  +'|'+(SCADA.alarms[0]?SCADA.alarms[0].txt:'');
 if(!force&&sig===SCADA._asig)return;SCADA._asig=sig;
 var h='<div class="scseg"><button data-s="alarms"'+(SCADA.aseg==='alarms'?' class="on"':'')+'>Alarms</button>'
  +'<button data-s="soe"'+(SCADA.aseg==='soe'?' class="on"':'')+'>Events (SOE)</button></div>';
 if(SCADA.aseg==='alarms'){
  h+='<button class="sack" data-ackall style="border:1px solid #d6ddea;background:none;border-radius:8px;padding:6px 13px;font:600 12px system-ui;color:#1f3b73;cursor:pointer">Acknowledge all</button>';
  if(!SCADA.alarms.length)h+='<div class="note" style="padding:14px 2px">No alarms. Limit checks run on every scan — undervoltage/overvoltage on all buses'+(NET&&NET.branches.some(function(x){return x.rate>0;})?' and line overload versus ratings.':'; set line ratings to enable overload alarms.')+'</div>';
  else SCADA.alarms.forEach(function(a,k){
   h+='<div class="scrow'+(a.ack?' ack':'')+'"><span class="sdot" style="background:'+(a.active?(a.sev===2?'#d92d20':'#b7791f'):'#1e7a44')+'"></span>'
    +'<span class="stime">'+ts(a.t).slice(0,8)+'</span><span class="stxt">'+a.txt+(a.active?'':' <i>(cleared)</i>')+'</span>'
    +(a.ack?'':'<button class="sack" data-k="'+k+'">ACK</button>')+'</div>';});
 }else{
  h+='<button class="sack" data-csv style="border:1px solid #d6ddea;background:none;border-radius:8px;padding:6px 13px;font:600 12px system-ui;color:#1f3b73;cursor:pointer">Export CSV</button>';
  if(!SCADA.soe.length)h+='<div class="note" style="padding:14px 2px">No events yet.</div>';
  else SCADA.soe.forEach(function(e){
   h+='<div class="scrow"><span class="sdot" style="background:'+(e.kind==='alarm'?'#b7791f':e.kind==='sys'?'#8b93a3':'#2c5aa0')+'"></span>'
    +'<span class="stime">'+ts(e.t)+'</span><span class="stxt">'+e.txt+'</span></div>';});}
 b.innerHTML=h;
 b.querySelectorAll('.scseg button').forEach(function(x){x.onclick=function(){SCADA.aseg=x.dataset.s;alarmsRender(true);};});
 var aa=b.querySelector('[data-ackall]');if(aa)aa.onclick=function(){
  SCADA.alarms.forEach(function(a){a.ack=true;});
  soe('operator acknowledged all alarms');alarmEval();alarmsRender(true);bannerSync();};
 b.querySelectorAll('.sack[data-k]').forEach(function(x){x.onclick=function(){
  var a=SCADA.alarms[+x.dataset.k];if(a){a.ack=true;soe('operator acknowledged: '+a.txt);}
  alarmEval();alarmsRender(true);bannerSync();};});
 var cs=b.querySelector('[data-csv]');if(cs)cs.onclick=function(){
  try{saveOut('psdat_soe.csv',{text:'time,kind,event\n'+SCADA.soe.slice().reverse().map(function(e){
   return ts(e.t)+','+e.kind+',"'+String(e.txt).replace(/"/g,'""')+'"';}).join('\n')});}catch(_){}};}
/* ---- component control & telemetry ---------------------------------------*/
function armBtn(id,label,cls,hint){
 var A=SCADA.armed;
 if(A&&A.id===id&&Date.now()<A.until)
  return '<button class="scact danger" data-arm-go="'+id+'">CONFIRM — '+label+'</button><div class="note" style="text-align:center;margin-top:4px">select-before-operate: confirm within 6 s</div>';
 return '<button class="scact '+cls+'" data-arm="'+id+'">'+label+'…</button>'+(hint?'<div class="note" style="margin-top:4px">'+hint+'</div>':'');}
function fmtN(x,d){var n=Number(x);return isFinite(n)?n.toFixed(d===undefined?1:d):'—';}
function scadaCtlRefresh(){
 var M=MODALS.ctl;if(!M||!SCADA.sel||!isOpen('ctl'))return;
 var b=M.body,st=SCADA.sel,t=st.t,i=st.i,D=(typeof DPF!=='undefined')?DPF:null;
 function row(k,v){return '<div class="scinfo"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>';}
 var h='',trendKey=null,trendLabel='',unit='';
 if(t==='br'){var br=NET.branches[i];if(!br)return;
  var open=!!br.off,f=(!open&&D&&D.flows)?D.flows[i]:null;
  h+='<div class="schd"><span class="ic">L</span><span class="tt">Line '+br.f+'–'+br.t+'</span>'
   +'<span class="scstat '+(open?'open':'closed')+'">'+(open?'BREAKER OPEN':'IN SERVICE')+'</span></div>';
  if(f){var S=Math.hypot(f.Pf,f.Qf);
   h+=row('Active power P',fmtN(f.Pf)+' MW')+row('Reactive power Q',fmtN(f.Qf)+' MVAr')+row('Apparent power S',fmtN(S)+' MVA');
   if(br.rate>0)h+=row('Loading',fmtN(S/br.rate*100,0)+' % of '+br.rate+' MVA');}
  else if(open)h+=row('Telemetry','no flow — breaker open');
  h+=armBtn('br'+i,open?'CLOSE breaker  line '+br.f+'–'+br.t:'OPEN breaker  line '+br.f+'–'+br.t,open?'':'danger',
   open?'closing re-solves the power flow immediately':'opening removes the line and re-solves the power flow');
  trendKey='S'+i;trendLabel='apparent power';unit='MVA';}
 else if(t==='gen'){var g=NET.gens[i];if(!g)return;
  var bb=NET.buses[g.bus-1],slack=bb&&bb.type==='slack';
  var offG=!!g.off,inSvc=NET.gens.filter(function(x){return !x.off;}).length;
  h+='<div class="schd"><span class="ic">G</span><span class="tt">Machine '+(i+1)+' · bus '+g.bus+' ('+(g.tag||'SG')+')</span>'
   +'<span class="scstat '+(offG?'open':'closed')+'">'+(offG?'TRIPPED':'IN SERVICE')+'</span></div>';
  h+=row('Scheduled output',fmtN(g.Pg)+' MW');
  if(D&&D.V&&bb)h+=row('Bus voltage',fmtN(D.V[g.bus-1],3)+' pu');
  if(g.Vset)h+=row('AVR setpoint',fmtN(g.Vset,3)+' pu');
  if(slack)h+='<div class="note" style="margin-top:8px">reference (slack) machine — it balances the system and cannot be tripped here.</div>';
  else if(!offG&&inSvc<=1)h+='<div class="note" style="margin-top:8px">last in-service machine — tripping it would black out the island.</div>';
  else h+=armBtn('g'+i,offG?'RECONNECT machine '+(i+1):'TRIP machine '+(i+1),offG?'':'danger',
   offG?'reconnecting restores its scheduled output':'the remaining machines and the slack pick up its output');
  trendKey='V'+(g.bus-1);trendLabel='bus voltage';unit='pu';}
 else if(t==='bus'){var b2=NET.buses[i];if(!b2)return;
  var hasLoad=(+b2.Pd||0)!==0||(+b2.Qd||0)!==0||b2.Pd0!==undefined;
  h+='<div class="schd"><span class="ic">B</span><span class="tt">Bus '+(i+1)+(b2.name?' · '+b2.name:'')+'</span>'
   +(b2.type==='slack'?'<span class="scstat closed">REFERENCE</span>':'')+'</div>';
  if(D&&D.V)h+=row('Voltage',fmtN(D.V[i],3)+' pu')+row('Angle',fmtN(D.th?D.th[i]:NaN,1)+'°');
  if(hasLoad)h+=row('Load',fmtN(b2.Pd)+' + j'+fmtN(b2.Qd)+' MVA'+(b2.Pd0!==undefined?'  (of '+fmtN(b2.Pd0)+')':''));
  if(hasLoad){
   h+=armBtn('sh'+i,'SHED 25% of the load at bus '+(i+1),'warn','emergency load shedding — re-solves immediately');
   if(b2.Pd0!==undefined&&(b2.Pd<b2.Pd0))h+=armBtn('rs'+i,'RESTORE full load at bus '+(i+1),'','returns to '+fmtN(b2.Pd0)+' MW');}
  trendKey='V'+i;trendLabel='voltage';unit='pu';}
 else return;
 h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:14px 4px 4px">Trend — '+trendLabel+' ('+unit+')</div><div id="sc-trend" style="margin:2px 0 6px"></div>';
 h+='<div class="note">telemetry refreshes every '+(SCADA.scanMs/1000)+' s · all operations are recorded in the event log</div>';
 b.innerHTML=h;
 var tr=SCADA.trend[trendKey];var te=b.querySelector('#sc-trend');
 if(te){if(tr&&tr.length>2){var xs=tr.map(function(p){return p[0];}),ys=tr.map(function(p){return p[1];});
   var ser={};ser[trendLabel]=ys;
   try{lineChart(te,xs,ser,'time since session start (s)',unit);}catch(_){te.innerHTML='<div class="note">collecting…</div>';}}
  else te.innerHTML='<div class="note">collecting telemetry…</div>';}
 b.querySelectorAll('[data-arm]').forEach(function(bn){bn.onclick=function(){
  SCADA.armed={id:bn.dataset.arm,until:Date.now()+6000};
  setTimeout(function(){if(SCADA.armed&&Date.now()>=SCADA.armed.until){SCADA.armed=null;scadaCtlRefresh();}},6200);
  scadaCtlRefresh();};});
 b.querySelectorAll('[data-arm-go]').forEach(function(bn){bn.onclick=function(){
  var id=bn.dataset.armGo;SCADA.armed=null;execOp(id);};});
}
function execOp(id){
 var m;
 if(m=id.match(/^br(\d+)$/)){var i=+m[1],br=NET.branches[i];if(!br)return;
  br.off=br.off?0:1;
  soe('OPERATOR '+(br.off?'OPENED':'CLOSED')+' breaker — line '+br.f+'–'+br.t);}
 else if(m=id.match(/^g(\d+)$/)){var gi=+m[1],g=NET.gens[gi];if(!g)return;
  g.off=g.off?0:1;
  soe('OPERATOR '+(g.off?'TRIPPED':'RECONNECTED')+' machine '+(gi+1)+' (bus '+g.bus+')');}
 else if(m=id.match(/^sh(\d+)$/)){var bi=+m[1],b=NET.buses[bi];if(!b)return;
  if(b.Pd0===undefined){b.Pd0=+b.Pd||0;b.Qd0=+b.Qd||0;}
  b.Pd=Math.round((+b.Pd||0)*0.75*10)/10;b.Qd=Math.round((+b.Qd||0)*0.75*10)/10;
  soe('OPERATOR SHED load at bus '+(bi+1)+' → '+b.Pd+' MW');}
 else if(m=id.match(/^rs(\d+)$/)){var ri=+m[1],rb=NET.buses[ri];if(!rb)return;
  if(rb.Pd0!==undefined){rb.Pd=rb.Pd0;rb.Qd=rb.Qd0;}
  soe('OPERATOR RESTORED load at bus '+(ri+1)+' → '+rb.Pd+' MW');}
 else return;
 try{if(typeof runActive==='function')runActive();}catch(_){}
 setTimeout(function(){captureTruth();alarmEval();bannerSync();scadaCtlRefresh();
  if(isOpen('alarms'))alarmsRender();try{qdraw();}catch(_){}},900);
}
/* ---- state estimation (WLS + bad data) ------------------------------------*/
function solveLin(A,b){var n=b.length,i,j,k;
 var M=new Array(n);for(i=0;i<n;i++){M[i]=A[i].slice();M[i].push(b[i]);}
 for(k=0;k<n;k++){var p=k,mx=Math.abs(M[k][k]);
  for(i=k+1;i<n;i++){var v=Math.abs(M[i][k]);if(v>mx){mx=v;p=i;}}
  if(mx<1e-11)return null;
  if(p!==k){var t=M[p];M[p]=M[k];M[k]=t;}
  for(i=k+1;i<n;i++){var f=M[i][k]/M[k][k];if(!f)continue;
   for(j=k;j<=n;j++)M[i][j]-=f*M[k][j];}}
 var x=new Array(n);
 for(i=n-1;i>=0;i--){var s2=M[i][n];for(j=i+1;j<n;j++)s2-=M[i][j]*x[j];x[i]=s2/M[i][i];}
 return x;}
function chi2inv99(k){if(k<1)k=1;var z=2.326348,h=2/(9*k);
 return k*Math.pow(1-h+z*Math.sqrt(h),3);}
function seRefBus(){var r=-1;
 for(var i=0;i<NET.buses.length;i++)if(NET.buses[i].type==='slack'){r=i;break;}
 if(r<0&&NET.gens.length)r=NET.gens[0].bus-1;
 return Math.max(0,r);}
function seBranchY(br){var r=+br.r||0,x=(+br.x||0.05),b=+br.b||0,a=(+br.tap||0)||1;
 var d=r*r+x*x,g=r/d,bb=-x/d,bc=b/2;
 return {Gff:(g)/(a*a),Bff:(bb+bc)/(a*a),Gft:-g/a,Bft:-bb/a};}
function seMeasure(){
 var D=SCADA.telem||DPF,T=[],z=[],sg=[];
 if(!D||!D.V)return null;
 var n=NET.buses.length;
 for(var i=0;i<n;i++){T.push({k:'V',i:i,lbl:'V  bus '+(i+1)});z.push(D.V[i]);sg.push(0.004);}
 if(D.flows)NET.branches.forEach(function(br,k){var f=D.flows[k];
  if(!f||br.off||f.upfc)return;
  T.push({k:'Pf',i:k,lbl:'P  line '+br.f+'–'+br.t});z.push(f.Pf/100);sg.push(0.008);
  T.push({k:'Qf',i:k,lbl:'Q  line '+br.f+'–'+br.t});z.push(f.Qf/100);sg.push(0.008);});
 if(SCADA.badInj){var bi=SCADA.badInj;
  for(var m2=0;m2<T.length;m2++)if(T[m2].k===bi.k&&T[m2].i===bi.i){z[m2]+=bi.bias;break;}}
 return {T:T,z:z,sg:sg};}
function runSE(){
 if(typeof NET==='undefined'||!NET||!NET.buses.length)return {ok:false,msg:'no network'};
 var M=seMeasure();if(!M)return {ok:false,msg:'no telemetry yet — start SCADA mode and wait for a scan'};
 var n=NET.buses.length,ref=seRefBus(),ns=2*n-1,m=M.z.length;
 if(m<ns)return {ok:false,msg:'not enough measurements ('+m+') for '+ns+' states'};
 var th=new Array(n).fill(0),V=new Array(n).fill(1);
 function sx(i){return i<ref?i:i-1;}
 var it,conv=false;
 var H=null,r=null,W=M.sg.map(function(s2){return 1/(s2*s2);});
 for(it=0;it<15;it++){
  H=[];r=[];
  for(var q=0;q<m;q++){var t=M.T[q],row=new Array(ns).fill(0),h;
   if(t.k==='V'){h=V[t.i];row[(n-1)+t.i]=1;}
   else{var br=NET.branches[t.i],fb=br.f-1,tb=br.t-1,Y=seBranchY(br);
    var d=th[fb]-th[tb],cd=Math.cos(d),sd=Math.sin(d),Vf=V[fb],Vt=V[tb];
    if(t.k==='Pf'){
     h=Vf*Vf*Y.Gff+Vf*Vt*(Y.Gft*cd+Y.Bft*sd);
     var dth=Vf*Vt*(-Y.Gft*sd+Y.Bft*cd);
     if(fb!==ref)row[sx(fb)]=dth; if(tb!==ref)row[sx(tb)]=-dth;
     row[(n-1)+fb]=2*Vf*Y.Gff+Vt*(Y.Gft*cd+Y.Bft*sd);
     row[(n-1)+tb]=Vf*(Y.Gft*cd+Y.Bft*sd);
    }else{
     h=-Vf*Vf*Y.Bff+Vf*Vt*(Y.Gft*sd-Y.Bft*cd);
     var dth2=Vf*Vt*(Y.Gft*cd+Y.Bft*sd);
     if(fb!==ref)row[sx(fb)]=dth2; if(tb!==ref)row[sx(tb)]=-dth2;
     row[(n-1)+fb]=-2*Vf*Y.Bff+Vt*(Y.Gft*sd-Y.Bft*cd);
     row[(n-1)+tb]=Vf*(Y.Gft*sd-Y.Bft*cd);
    }}
   H.push(row);r.push(M.z[q]-h);}
  var G=new Array(ns),rhs=new Array(ns).fill(0),a2,b2,q2;
  for(a2=0;a2<ns;a2++)G[a2]=new Array(ns).fill(0);
  for(q2=0;q2<m;q2++){var Hq=H[q2],wq=W[q2];
   for(a2=0;a2<ns;a2++){var ha=Hq[a2];if(!ha)continue;
    rhs[a2]+=ha*wq*r[q2];
    for(b2=a2;b2<ns;b2++){var hb=Hq[b2];if(hb)G[a2][b2]+=ha*wq*hb;}}}
  for(a2=0;a2<ns;a2++)for(b2=0;b2<a2;b2++)G[a2][b2]=G[b2][a2];
  var dx=solveLin(G,rhs);
  if(!dx)return {ok:false,msg:'gain matrix is singular — part of the network is unobservable (islanded?)'};
  var mx=0;
  for(var s3=0;s3<ns;s3++)mx=Math.max(mx,Math.abs(dx[s3]));
  for(var i3=0;i3<n;i3++){if(i3!==ref)th[i3]+=dx[sx(i3)];V[i3]+=dx[(n-1)+i3];}
  if(mx<1e-6){conv=true;break;}}
 var J=0;for(var q3=0;q3<m;q3++)J+=r[q3]*r[q3]*W[q3];
 var dof=m-ns,thr=chi2inv99(dof);
 var lnr=null;
 if(conv&&ns<=240){
  var G2=new Array(ns);for(var a4=0;a4<ns;a4++)G2[a4]=new Array(ns).fill(0);
  for(var q4=0;q4<m;q4++){var Hq2=H[q4],w4=W[q4];
   for(var a5=0;a5<ns;a5++){var h5=Hq2[a5];if(!h5)continue;
    for(var b5=a5;b5<ns;b5++){var h6=Hq2[b5];if(h6)G2[a5][b5]+=h5*w4*h6;}}}
  for(var a6=0;a6<ns;a6++)for(var b6=0;b6<a6;b6++)G2[a6][b6]=G2[b6][a6];
  var Gi=[],ok=true,e;
  for(e=0;e<ns;e++){var ei=new Array(ns).fill(0);ei[e]=1;
   var col=solveLin(G2,ei);if(!col){ok=false;break;}Gi.push(col);}
  if(ok){var best=-1,bi2=-1;
   for(var q5=0;q5<m;q5++){var Hq3=H[q5],s5=0;
    for(var a7=0;a7<ns;a7++){var h7=Hq3[a7];if(!h7)continue;
     for(var b7=0;b7<ns;b7++){var h8=Hq3[b7];if(h8)s5+=h7*Gi[b7][a7]*h8;}}
    var om=(M.sg[q5]*M.sg[q5])-s5;
    var rn=Math.abs(r[q5])/Math.sqrt(Math.max(om,1e-10));
    if(rn>best){best=rn;bi2=q5;}}
   if(bi2>=0)lnr={rn:best,lbl:M.T[bi2].lbl};}}
 return {ok:true,conv:conv,iters:it+1,J:J,dof:dof,thr:thr,bad:J>thr,lnr:lnr,
         V:V,th:th.map(function(a){return a*180/Math.PI;}),ref:ref,m:m,ns:ns};}
function seRender(res){var M=scModal('se','State estimation (WLS)',700);var b=M.body;
 var h='<div class="note" style="margin:2px 0 8px">Fuses the latest noisy scan — every bus voltage plus P/Q at the sending end of every in-service line — into one best state by <b>weighted least squares</b>, then checks the measurements against each other (χ² test, largest normalized residual). Start the SCADA mode for live telemetry.</div>';
 h+='<button class="scact" data-se-run>Run state estimation</button>';
 h+=SCADA.badInj
  ?'<button class="scact warn" data-se-clear>Clear the injected gross error</button><div class="note" style="margin-top:4px">a gross error is riding on one measurement — run the estimator to hunt it down</div>'
  :'<button class="scact gray" data-se-inj>Inject a gross error into one measurement…</button><div class="note" style="margin-top:4px">classroom experiment: corrupt one telemetry point, then let the χ²/residual test find it</div>';
 if(res){
  if(!res.ok)h+='<div class="err" style="margin-top:12px">'+res.msg+'</div>';
  else{
   h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:14px 4px 4px">Result</div>';
   h+='<div class="scinfo"><span class="k">Convergence</span><span class="v">'+(res.conv?(res.iters+' iterations'):'NOT converged')+'</span></div>';
   h+='<div class="scinfo"><span class="k">Measurements / states</span><span class="v">'+res.m+' / '+res.ns+' (redundancy '+(res.m/res.ns).toFixed(2)+')</span></div>';
   h+='<div class="scinfo"><span class="k">Objective J(x̂)</span><span class="v">'+res.J.toFixed(1)+'</span></div>';
   h+='<div class="scinfo"><span class="k">χ²₀.₉₉ threshold (dof '+res.dof+')</span><span class="v">'+res.thr.toFixed(1)+'</span></div>';
   h+=res.bad
    ?'<div class="err" style="margin-top:10px"><b>BAD DATA detected</b> — J exceeds the χ² threshold.'+(res.lnr?('<br>largest normalized residual: <b>'+res.lnr.lbl+'</b> (r<sub>N</sub> = '+res.lnr.rn.toFixed(1)+') — prime suspect.'):'')+'</div>'
    :'<div class="note" style="margin-top:10px;color:#1c7a43"><b>Measurements are consistent</b> — J is under the χ² threshold'+(res.lnr?(' (largest r<sub>N</sub> = '+res.lnr.rn.toFixed(1)+', '+res.lnr.lbl+')'):'')+'.</div>';
   if(res.conv){
    var n=NET.buses.length,rows=Math.min(n,40),T=SCADA.trueDPF,D=SCADA.telem||DPF;
    h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:14px 4px 4px">Estimated bus voltages (pu)</div>';
    h+='<div style="max-height:250px;overflow:auto"><table><tr><th>bus</th><th>telemetry</th><th>estimate</th><th>true</th><th>est−true</th></tr>';
    for(var i=0;i<rows;i++){var e=res.V[i],tv=T&&T.V?T.V[i]:NaN,dv=D&&D.V?D.V[i]:NaN;
     h+='<tr><td>'+(i+1)+'</td><td>'+(isFinite(dv)?dv.toFixed(4):'—')+'</td><td>'+e.toFixed(4)+'</td><td>'+(isFinite(tv)?tv.toFixed(4):'—')+'</td><td>'+(isFinite(tv)?((e-tv)>=0?'+':'')+(e-tv).toFixed(4):'—')+'</td></tr>';}
    h+='</table></div>';
    if(n>rows)h+='<div class="note">first '+rows+' of '+n+' buses shown</div>';}}
 }
 b.innerHTML=h;
 var rb=b.querySelector('[data-se-run]');if(rb)rb.onclick=function(){
  var res2=runSE();
  soe('state estimation run — '+(res2.ok?('J='+res2.J.toFixed(1)+' vs χ²='+res2.thr.toFixed(1)+(res2.bad?' → BAD DATA'+(res2.lnr?(' ('+res2.lnr.lbl+')'):''):' → consistent')):res2.msg),'sys');
  seRender(res2);};
 var ib=b.querySelector('[data-se-inj]');if(ib)ib.onclick=function(){
  var Mm=seMeasure();if(!Mm||!Mm.T.length){try{stat('no telemetry yet — start the SCADA mode first');}catch(_){}return;}
  var pi=Math.floor(Math.random()*Mm.T.length),pick=Mm.T[pi];
  var bias=pick.k==='V'?0.08:(Math.max(0.3,Math.abs(Mm.z[pi])*0.5)*(Math.random()<0.5?-1:1));
  SCADA.badInj={k:pick.k,i:pick.i,bias:bias,lbl:pick.lbl};
  soe('gross error injected into one telemetry point (sealed)','sys');
  seRender();};
 var cb=b.querySelector('[data-se-clear]');if(cb)cb.onclick=function(){
  soe('injected gross error cleared — it was on '+(SCADA.badInj?SCADA.badInj.lbl:'?'),'sys');
  SCADA.badInj=null;seRender();};}
/* ---- disturbance drills ---------------------------------------------------*/
function drillCandidates(){var c=[];
 NET.branches.forEach(function(br,i){if(!br.off)c.push({action:'openLine',i:i,lbl:'line '+br.f+'–'+br.t+' trips'});});
 var ins=NET.gens.filter(function(g){return !g.off;}).length;
 NET.gens.forEach(function(g,i){var b=NET.buses[g.bus-1];
  if(!g.off&&ins>1&&(!b||b.type!=='slack'))c.push({action:'tripGen',i:i,lbl:'machine '+(i+1)+' trips'});});
 NET.buses.forEach(function(b,i){if((+b.Pd||0)>0)c.push({action:'loadScale',i:i,mag:1.35,lbl:'load surge at bus '+(i+1)});});
 return c;}
function genDrill(){var c=drillCandidates();if(!c.length)return null;
 var k=2+(Math.random()<0.4?1:0),ev=[],used={};
 while(ev.length<k&&c.length){var p=Math.floor(Math.random()*c.length),cd=c[p];
  var key=cd.action+cd.i;if(used[key]){c.splice(p,1);continue;}used[key]=1;
  ev.push({at:0,action:cd.action,i:cd.i,mag:cd.mag,lbl:cd.lbl,fired:false});}
 var t=15+Math.random()*20;
 ev.forEach(function(e){e.at=Math.round(t);t+=20+Math.random()*35;});
 ev.sort(function(a,b){return a.at-b.at;});
 return {name:'random drill — '+(NET.name||'network'),events:ev};}
function drillFire(e){
 if(e.action==='openLine'){var br=NET.branches[e.i];if(br&&!br.off){br.off=1;
   soe('SYSTEM EVENT — '+e.lbl,'sys');}}
 else if(e.action==='closeLine'){var b2=NET.branches[e.i];if(b2&&b2.off){b2.off=0;
   soe('SYSTEM EVENT — line '+b2.f+'–'+b2.t+' reclosed','sys');}}
 else if(e.action==='tripGen'){var g=NET.gens[e.i];if(g&&!g.off){g.off=1;
   soe('SYSTEM EVENT — '+e.lbl,'sys');}}
 else if(e.action==='recGen'){var g2=NET.gens[e.i];if(g2&&g2.off){g2.off=0;
   soe('SYSTEM EVENT — machine '+(e.i+1)+' reconnected','sys');}}
 else if(e.action==='loadScale'){var b3=NET.buses[e.i];if(b3){
   if(b3.Pd0===undefined){b3.Pd0=+b3.Pd||0;b3.Qd0=+b3.Qd||0;}
   b3.Pd=Math.round((+b3.Pd||0)*(e.mag||1.35)*10)/10;
   b3.Qd=Math.round((+b3.Qd||0)*(e.mag||1.35)*10)/10;
   soe('SYSTEM EVENT — '+(e.lbl||('load change at bus '+(e.i+1)))+' → '+b3.Pd+' MW','sys');}}
 else return;
 try{if(typeof runActive==='function')runActive();}catch(_){}
 setTimeout(function(){captureTruth();alarmEval();bannerSync();
  if(isOpen('ctl'))scadaCtlRefresh();if(isOpen('alarms'))alarmsRender();try{qdraw();}catch(_){}},900);}
function drillTick(){var D=SCADA.drill;if(!D||!D.active)return;
 var elapsed=(Date.now()-D.t0)/1000;
 D.events.forEach(function(e){if(!e.fired&&elapsed>=e.at){e.fired=true;drillFire(e);}});}
function drillDebrief(){var D=SCADA.drill;if(!D)return null;
 var t0=D.t0,als=SCADA.soe.filter(function(e){return e.t>=t0&&e.kind==='alarm'&&/^ALARM|^warning/.test(e.txt);});
 var crit=als.filter(function(e){return /^ALARM/.test(e.txt);}).length;
 var ops=SCADA.soe.filter(function(e){return e.t>=t0&&e.kind==='op'&&/^OPERATOR/i.test(e.txt);}).length;
 var firstAl=null,firstAck=null;
 SCADA.soe.slice().reverse().forEach(function(e){
  if(e.t<t0)return;
  if(firstAl===null&&e.kind==='alarm'&&/^ALARM|^warning/.test(e.txt))firstAl=e.t;
  if(firstAl!==null&&firstAck===null&&/acknowledged/.test(e.txt))firstAck=e.t;});
 var act=SCADA.alarms.filter(function(a){return a.active;}).length;
 return {dur:Math.round((Date.now()-t0)/1000),fired:D.events.filter(function(e){return e.fired;}).length,
  total:D.events.length,alarms:als.length,crit:crit,ops:ops,
  ackLat:(firstAl!==null&&firstAck!==null)?Math.round((firstAck-firstAl)/1000):null,
  normal:act===0};}
function drillRender(){var M=scModal('drill','Disturbance drill',600);var b=M.body;
 var D=SCADA.drill,h='';
 h+='<div class="note" style="margin:2px 0 8px">Timed, sealed system events fire while you operate — respond: read the alarms, switch, shed, restore. Attach a drill to the project (File ▸ Save project) to give a whole class the same scenario. Requires the SCADA mode to be running.</div>';
 if(!D||(!D.active&&!D.done)){
  h+='<button class="scact" data-dr-new>New random drill (events stay sealed)</button>';
  if(SCADA.scenario)h+='<button class="scact teal" data-dr-scen>Run the project scenario — '+SCADA.scenario.name+'</button>';
  if(SCADA.pending){h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:12px 4px 4px">Armed</div>'
   +'<div class="note">'+SCADA.pending.events.length+' sealed events over ~'+(SCADA.pending.events[SCADA.pending.events.length-1].at)+' s</div>'
   +'<button class="scact danger" data-dr-start>Start the drill</button>'
   +'<button class="scact gray" data-dr-attach>Attach to project (saved in .psdat)</button>';}
 }else if(D.active){
  var el2=Math.round((Date.now()-D.t0)/1000);
  h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:2px 4px 4px">Drill running — '+D.name+'</div>';
  h+='<div class="scinfo"><span class="k">Elapsed</span><span class="v">'+el2+' s</span></div>';
  h+='<div class="scinfo"><span class="k">Events fired</span><span class="v">'+D.events.filter(function(e){return e.fired;}).length+' of '+D.events.length+'</span></div>';
  h+='<button class="scact danger" data-dr-end>End drill &amp; debrief</button>';
 }else if(D.done){var R=D.debrief;
  h+='<div style="font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase;color:#8b93a3;margin:2px 4px 4px">Debrief — '+D.name+'</div>';
  h+='<div class="scinfo"><span class="k">Duration</span><span class="v">'+R.dur+' s</span></div>';
  h+='<div class="scinfo"><span class="k">Events fired</span><span class="v">'+R.fired+' of '+R.total+'</span></div>';
  h+='<div class="scinfo"><span class="k">Alarms raised</span><span class="v">'+R.alarms+' ('+R.crit+' critical)</span></div>';
  h+='<div class="scinfo"><span class="k">First acknowledge after</span><span class="v">'+(R.ackLat===null?'—':R.ackLat+' s')+'</span></div>';
  h+='<div class="scinfo"><span class="k">Operator actions</span><span class="v">'+R.ops+'</span></div>';
  h+='<div class="scinfo"><span class="k">System normal at end</span><span class="v">'+(R.normal?'YES':'NO — alarms still active')+'</span></div>';
  h+='<button class="scact" data-dr-clear>Close debrief</button>';}
 b.innerHTML=h;
 var nb=b.querySelector('[data-dr-new]');if(nb)nb.onclick=function(){
  var d=genDrill();if(!d){try{stat('nothing to disturb in this network');}catch(_){}return;}
  SCADA.pending=d;drillRender();};
 var sb2=b.querySelector('[data-dr-scen]');if(sb2)sb2.onclick=function(){
  SCADA.pending={name:SCADA.scenario.name,events:SCADA.scenario.events.map(function(e){
   return {at:+e.at||+e.t||10,action:e.action,i:+e.i||0,mag:e.mag,lbl:e.lbl||e.action,fired:false};})};
  drillRender();};
 var st2=b.querySelector('[data-dr-start]');if(st2)st2.onclick=function(){
  if(!SCADA.on){try{stat('start the SCADA operator mode first (Tools menu)');}catch(_){}return;}
  SCADA.drill={name:SCADA.pending.name,events:SCADA.pending.events,t0:Date.now(),active:true,done:false};
  SCADA.pending=null;
  soe('DRILL started — '+SCADA.drill.events.length+' sealed events pending','sys');
  drillRender();};
 var ab2=b.querySelector('[data-dr-attach]');if(ab2)ab2.onclick=function(){
  SCADA.scenario={name:SCADA.pending.name,
   events:SCADA.pending.events.map(function(e){return {at:e.at,action:e.action,i:e.i,mag:e.mag,lbl:e.lbl};})};
  soe('drill attached to the project — save the project to distribute it','sys');
  try{stat('drill attached — use File › Save project to write it into the .psdat file');}catch(_){}
  drillRender();};
 var eb2=b.querySelector('[data-dr-end]');if(eb2)eb2.onclick=function(){
  var R=drillDebrief();SCADA.drill.active=false;SCADA.drill.done=true;SCADA.drill.debrief=R;
  soe('DRILL debrief — '+R.fired+'/'+R.total+' events, '+R.alarms+' alarms ('+R.crit+' critical), '
   +(R.ackLat===null?'no acknowledge':'first ACK after '+R.ackLat+' s')+', '+R.ops+' operator actions, '
   +(R.normal?'system NORMAL':'alarms still active'),'sys');
  drillRender();};
 var cb2=b.querySelector('[data-dr-clear]');if(cb2)cb2.onclick=function(){
  SCADA.drill=null;drillRender();};}
/* ---- keep truth/alarms in step with every real solve ----------------------*/
try{var _rpf=runPF;runPF=async function(){var r=await _rpf.apply(this,arguments);
 if(SCADA.on){captureTruth();alarmEval();bannerSync();if(isOpen('ctl'))scadaCtlRefresh();}
 return r;};}catch(e){}
/* persist the heat-map On/Off choice whenever the user toggles the contour */
try{var _tgl=tgl;tgl=function(k){_tgl(k);
 if(k==='cont'){try{localStorage.setItem('psdat_heat',VOPT.cont?'on':'off');}catch(_){}}};}catch(e){}
/* banner click + menu checkmark init */
function scInit(){
 var ban=document.getElementById('scban');if(ban)ban.onclick=function(){window.scadaOpen('alarms');};
 var c=document.getElementById('vNight');
 if(c)c.style.visibility=document.documentElement.classList.contains('dark')?'visible':'hidden';
 var c2=document.getElementById('vCmode');
 if(c2&&typeof CMODE!=='undefined')c2.style.visibility=(CMODE==='dynamic')?'visible':'hidden';}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scInit);else scInit();
})();
</script>
</body></html>"""


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8642
    srv = ThreadingHTTPServer(('127.0.0.1', port), H)
    url = f'http://localhost:{port}'
    print(f'PSDAT Interactive Lab -> {url}   (Ctrl+C to stop)')
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
