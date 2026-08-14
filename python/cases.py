"""
cases.py — bundled test systems.

Each loader returns a `Case` (plain data object) with the network, the
load-flow solution, and the synchronous-machine dynamic data:

  ieee9()    — IEEE 9-bus, 3 machines  [Sauer & Pai; PSDAT (OAJPE 2020)]
  kundur2a() — Kundur two-area, 4 machines, 11 buses
               [Kundur, Power System Stability and Control, Example 12.6]
  ne68()     — 16-machine 68-bus NETS–NYPS  [Rogers, Power System Oscillations;
               Pal & Chaudhuri, Robust Control in Power Systems]

Machine data are per-unit on the 100-MVA system base throughout; `Sbase_gen`
(machine MVA ratings) is used for inertia weighting and penetration measures.
"""
import os
import re
import sys
import numpy as np
from network import build_ybus, power_flow

# folder holding the bundled case files — inside the PyInstaller bundle when
# running as the standalone PSDAT.exe, next to this file otherwise
_HERE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


class Case:
    """Container for one test system (network + machine dynamic data)."""

    def __init__(self, name, m, n, ws, bus_type, Pd, Qd, Vm0, gen_bus,
                 Pg_sched, Vg_sched, branch, tap=None, gs=None, bs=None,
                 machine=None, Sbase_gen=None, baseMVA=100.0, facts=None):
        self.name, self.m, self.n, self.ws = name, m, n, ws
        self.baseMVA = baseMVA
        self.bus_type = bus_type
        self.Pd, self.Qd, self.Vm0 = Pd, Qd, Vm0
        self.gen_bus, self.Pg_sched, self.Vg_sched = gen_bus, Pg_sched, Vg_sched
        self.tap, self.gs, self.bs = tap, gs, bs
        self.machine = machine            # dict of arrays H, Xd, ..., exciter, governor
        self.Sbase_gen = Sbase_gen
        self.facts = list(facts) if facts else []   # FACTS devices (SVC/STATCOM/TCSC/...)
        import facts as _F
        # DC-coupled UPFC in P-Q control mode: realize the corridor P/Q injection
        # + sending-bus V regulation as a network edit (line removed, loads shifted,
        # a shunt regulator added), so the rest of the pipeline sees a plain case.
        self._upfc_pq = [d for d in self.facts if _F.upfc_pq(d)]
        if self._upfc_pq:
            stamps, Pd, Qd, statcoms = _F.upfc_pq_prepare(self.facts, branch, tap, n, Pd, Qd)
            self.facts = [d for d in self.facts if not _F.upfc_pq(d)] + statcoms
            self._upfc_stamps = stamps
            self.Pd, self.Qd = Pd, Qd                # injections carry into the dynamics too
        else:
            self._upfc_stamps = []
        # DC-coupled IPFC in P-Q mode: solved separately (series-voltage-source
        # fixed point) after the Ybus is built; realized as constant ΔS injections.
        self._ipfc_pq = [d for d in self.facts if _F.ipfc_pq(d)]
        self.facts = [d for d in self.facts if not _F.ipfc_pq(d)]
        # series FACTS (TCSC/TSSC/SSSC) compensate their line BEFORE the Ybus:
        self.branch = _F.apply_series(branch, self.facts) if self.facts else branch
        self.Ybus = build_ybus(n, self.branch, tap, gs, bs)
        for st in self._upfc_stamps:                 # remove each P-Q-UPFC's own line
            self.Ybus = self.Ybus - st
        for dev in self._ipfc_pq:                     # master P/Q + slave Q with DC balance
            dPd, dQd, rep = _F.ipfc_pq_solve(dev, self.Ybus, bus_type, Pd, Qd,
                Vm0, gen_bus, Pg_sched, Vg_sched, self.branch, tap, power_flow)
            Pd = Pd + dPd; Qd = Qd + dQd; dev['_rep'] = rep
        if self._ipfc_pq:
            self.Pd, self.Qd = Pd, Qd                # injections carry into the dynamics
        self.V0, self.TH0, self.Pg, self.Qg = self._facts_power_flow(
            bus_type, Pd, Qd, Vm0, gen_bus, Pg_sched, Vg_sched, tap, gs, bs)
        if self.facts:
            _F.series_oppoint(self.facts, self.V0, self.TH0, self.branch, tap)
        # voltage-dependent (ZIP-exponent) load coefficients, per bus; 0 = the
        # constant-power default used by every bundled benchmark (see system.dae)
        self.load_a = np.zeros(n)
        self.load_b = np.zeros(n)

    def _facts_power_flow(self, bus_type, Pd, Qd, Vm0, gen_bus, Pg_sched,
                          Vg_sched, tap, gs, bs):
        """Power flow with shunt-FACTS voltage regulation.  Each SVC/STATCOM on a
        PQ bus holds that bus at its Vref (reusing the PV machinery); a device
        that would exceed its limit is fixed as its equivalent shunt and the
        case re-solved, so the reported voltages are physically achievable."""
        if not self.facts:
            return power_flow(self.Ybus, bus_type, Pd, Qd, Vm0, gen_bus,
                              Pg_sched, Vg_sched)
        import facts as _F
        bt, vm = _F.facts_pf_setup(bus_type, Vm0, self.facts)
        V, TH, Pg, Qg = power_flow(self.Ybus, bt, Pd, Qd, vm, gen_bus,
                                   Pg_sched, Vg_sched)
        shunts = _F.facts_operating_point(self.facts, V, Qg)
        if shunts:                       # one re-solve with saturated devices fixed
            bs2 = (np.zeros(self.n) if bs is None else np.array(bs, float)).copy()
            bt2 = bt.copy()
            for i, B in shunts.items():
                bs2[i] += B              # saturated device becomes a fixed shunt
                if bus_type[i] == 1:
                    bt2[i] = 1            # ... and its bus floats again (PQ)
            # PF-ONLY admittance matrix: self.Ybus (used by the dynamics) stays
            # clean, because each saturated device's Q is produced by its own
            # regulator state at the limit -- baking the shunt in as well would
            # count the injection twice in the DAE.
            Ypf = build_ybus(self.n, self.branch, tap, gs, bs2)
            for st in self._upfc_stamps:               # keep P-Q-UPFC lines removed
                Ypf = Ypf - st
            V, TH, Pg, Qg = power_flow(Ypf, bt2, Pd, Qd, vm, gen_bus,
                                       Pg_sched, Vg_sched)
            # refresh the UNSATURATED devices only: at a saturated bus the Q now
            # flows through the bs2 shunt (Qg there reads 0), so recomputing
            # would wrongly zero the device output.  The limit values stand, and
            # B_lim*V0^2 (resp. I_lim*V0) reproduces the shunt's Q at the solved
            # V0, keeping the start an exact equilibrium of the DAE.
            _F.facts_operating_point(self.facts, V, Qg, skip=set(shunts))
        return V, TH, Pg, Qg

    def line(self, fbus, tbus):
        """Return (row, tap) of the first branch fbus-tbus (1-based)."""
        for k in range(self.branch.shape[0]):
            if int(self.branch[k, 0]) == fbus and int(self.branch[k, 1]) == tbus:
                return self.branch[k], (1.0 if self.tap is None else self.tap[k])
        raise ValueError(f"no branch {fbus}-{tbus} in {self.name}")


# ---------------------------------------------------------------- IEEE 9-bus
def ieee9():
    ws = 2 * np.pi * 60
    m, n = 3, 9
    bus_type = np.array([3, 2, 2, 1, 1, 1, 1, 1, 1])
    Pd = np.array([0, 0, 0, 0, 125, 90, 0, 100, 0], float) / 100
    Qd = np.array([0, 0, 0, 0, 50, 30, 0, 35, 0], float) / 100
    Vm0 = np.array([1.04, 1.025, 1.025, 1, 1, 1, 1, 1, 1], float)
    gen_bus = np.array([1, 2, 3])
    Pg_sched = np.array([0, 163, 85], float) / 100
    Vg_sched = np.array([1.04, 1.025, 1.025])
    branch = np.array([[1, 4, 0, 0.0576, 0], [4, 6, 0.017, 0.092, 0.158],
                       [6, 9, 0.039, 0.17, 0.358], [3, 9, 0, 0.0586, 0],
                       [8, 9, 0.0119, 0.1008, 0.209], [7, 8, 0.0085, 0.072, 0.149],
                       [2, 7, 0, 0.0625, 0], [5, 7, 0.032, 0.161, 0.306],
                       [4, 5, 0.01, 0.085, 0.176]], float)
    # 2-axis sub-transient machines + IEEE Type-I exciters + turbine-governors
    # (identical to PSDAT Main_File.m / the OAJPE 2020 paper)
    o = np.ones(m)
    machine = dict(
        H=np.array([23.64, 6.40, 3.01]),
        Xd=np.array([0.146, 0.8958, 1.3125]), Xdp=np.array([0.0608, 0.1198, 0.1813]),
        Xdpp=np.array([0.0489, 0.0881, 0.1133]), Xq=np.array([0.0969, 0.8645, 1.2578]),
        Xqp=np.array([0.0969, 0.1969, 0.25]), Xqpp=np.array([0.0396, 0.0887, 0.0833]),
        Td0p=np.array([8.96, 6.0, 5.89]), Td0pp=np.array([0.115, 0.0337, 0.042]),
        Tq0p=np.array([0.31, 0.535, 0.60]), Tq0pp=np.array([0.033, 0.078, 0.1875]),
        Rs=np.array([0.0041, 0.0026, 0.0035]), Xls=np.array([0.12, 0.102, 0.075]),
        Dm=np.array([0.1 * (2 * 23.64) / ws, 0.2 * (2 * 6.4) / ws, 0.3 * (2 * 3.01) / ws]),
        KA=20 * o, TA=0.2 * o, KE=1.0 * o, TE=0.314 * o, KF=0.063 * o, TF=0.35 * o,
        Ax=0.0039 * o, Bx=1.555 * o, TCH=0.10 * o, TSV=0.05 * o, RD=0.05 * o)
    return Case('IEEE9', m, n, ws, bus_type, Pd, Qd, Vm0, gen_bus, Pg_sched,
                Vg_sched, branch, machine=machine,
                Sbase_gen=np.array([100., 300., 270.]))


# ------------------------------------------------------------- Kundur 2-area
def kundur2a():
    """Kundur Example 12.6 / Klein–Rogers–Kundur two-area system.  Machine
    dynamic data converted from the 900-MVA machine base to the 100-MVA
    system base (X -> X/9, H -> H*9)."""
    ws = 2 * np.pi * 60
    m, n = 4, 11
    bus_type = np.array([3, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1])
    Pd = np.zeros(n); Qd = np.zeros(n); Bsh = np.zeros(n)
    Pd[6] = 9.67; Qd[6] = 1.0; Bsh[6] = 2.00     # bus 7 load + 200 MVAr cap
    Pd[8] = 17.67; Qd[8] = 1.0; Bsh[8] = 3.50    # bus 9 load + 350 MVAr cap
    Vm0 = np.ones(n); Vm0[0] = 1.03; Vm0[1] = 1.01; Vm0[2] = 1.03; Vm0[3] = 1.01
    gen_bus = np.array([1, 2, 3, 4])
    Pg_sched = np.array([7.0, 7.0, 7.19, 7.0])
    Vg_sched = np.array([1.03, 1.01, 1.03, 1.01])

    def ln(L):   # 230-kV line constants per km on 100 MVA [Kundur ex. 12.6]
        return (0.0001 * L, 0.001 * L, 0.00175 * L)

    def ln2(L):  # double-circuit
        r, x, b = ln(L)
        return (r / 2, x / 2, b * 2)
    br = [[1, 5, 0, 0.0167, 0], [2, 6, 0, 0.0167, 0],
          [3, 11, 0, 0.0167, 0], [4, 10, 0, 0.0167, 0],
          [5, 6, *ln(25)], [6, 7, *ln(10)],
          [7, 8, *ln2(110)], [8, 9, *ln2(110)],
          [9, 10, *ln(10)], [10, 11, *ln(25)]]
    branch = np.array(br, float)
    o = np.ones(m)
    machine = dict(
        H=np.array([58.5, 58.5, 55.575, 55.575]),         # = H(900 MVA) * 9
        Xd=0.2 * o, Xdp=0.0333 * o, Xdpp=0.02778 * o,
        Xq=0.18889 * o, Xqp=0.06111 * o, Xqpp=0.02778 * o,
        Xls=0.02222 * o, Rs=0.000278 * o,
        Td0p=8.0 * o, Td0pp=0.03 * o, Tq0p=0.4 * o, Tq0pp=0.05 * o,
        Dm=0.10 * o,      # small uniform damping -> lightly-damped stable base
        KA=200 * o, TA=0.01 * o, KE=1 * o, TE=0.05 * o,
        KF=0.001 * o, TF=0.1 * o, Ax=0.0 * o, Bx=0.0 * o,
        TCH=0.10 * o, TSV=0.05 * o, RD=0.05 * o)
    return Case('Kundur2A', m, n, ws, bus_type, Pd, Qd, Vm0, gen_bus, Pg_sched,
                Vg_sched, branch, gs=np.zeros(n), bs=Bsh, machine=machine,
                Sbase_gen=np.array([900., 900., 900., 900.]))


# Converter parameters referred to the Kundur 900-MVA machine size
# (impedances /9, inertia *9) — use for units replacing Kundur machines.
GFM_K = dict(Hv=45.0, Dp=180.0, wc=31.4, mq=0.0056, Rc=0.0006, Xc=0.0056)
GFL_K = dict(Kp=50.0, Ki=900.0, Ti=0.01)


# ------------------------------------------------------- 68-bus NETS–NYPS
def _mat(txt, key):
    mm = re.search(key + r'\s*=\s*\[(.*?)\];', txt, re.S)
    rows = []
    for ln_ in mm.group(1).strip().splitlines():
        ln_ = ln_.split('%')[0].strip().rstrip(';')
        if ln_:
            rows.append([float(v) for v in ln_.replace(',', ' ').split()])
    return np.array(rows)


def ne68():
    """16-machine, 68-bus NETS–NYPS reduced New England / New York system.
    Network parsed from the bundled MATPOWER case file case68_16m.m."""
    ws = 2 * np.pi * 60
    txt = open(os.path.join(_HERE, 'case68_16m.m')).read()
    bus = _mat(txt, r'mpc\.bus'); gen = _mat(txt, r'mpc\.gen'); br = _mat(txt, r'mpc\.branch')
    n = bus.shape[0]; m = 16
    bus_type = bus[:, 1].astype(int)
    if not np.any(bus_type == 3):
        bus_type[0] = 3
    machine = dict(
        H=np.array([42, 30.2, 35.8, 28.6, 26, 34.8, 26.4, 24.3, 34.5, 31, 28.2, 92.3, 248, 300, 300, 225], float),
        Xd=np.array([0.1, 0.295, 0.2495, 0.262, 0.33, 0.254, 0.295, 0.29, 0.2106, 0.169, 0.128, 0.101, 0.0296, 0.018, 0.018, 0.0356]),
        Xdp=np.array([0.031, 0.0697, 0.0531, 0.0436, 0.066, 0.05, 0.049, 0.057, 0.057, 0.0457, 0.018, 0.031, 0.0055, 0.0029, 0.0029, 0.0071]),
        Xdpp=np.array([0.025, 0.05, 0.045, 0.035, 0.05, 0.04, 0.04, 0.045, 0.045, 0.04, 0.012, 0.025, 0.004, 0.0023, 0.0023, 0.0055]),
        Xq=np.array([0.069, 0.282, 0.237, 0.258, 0.31, 0.241, 0.292, 0.28, 0.205, 0.115, 0.123, 0.095, 0.0286, 0.0173, 0.0173, 0.0334]),
        Xqp=np.array([0.0417, 0.0933, 0.0714, 0.0586, 0.0883, 0.0675, 0.0667, 0.0767, 0.0767, 0.0615, 0.0241, 0.042, 0.0074, 0.0038, 0.0038, 0.0095]),
        Xqpp=np.array([0.025, 0.05, 0.045, 0.035, 0.05, 0.04, 0.04, 0.045, 0.045, 0.04, 0.012, 0.025, 0.004, 0.0023, 0.0023, 0.0055]),
        Td0p=np.array([10.2, 6.56, 5.7, 5.69, 5.4, 7.3, 5.66, 6.7, 4.79, 9.37, 4.1, 7.4, 5.9, 4.1, 4.1, 7.8]),
        Td0pp=0.05 * np.ones(m),
        Tq0p=np.array([1.5, 1.5, 1.5, 1.5, 0.44, 0.4, 1.5, 0.41, 1.96, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5]),
        Tq0pp=0.035 * np.ones(m),
        Rs=np.zeros(m),
        Xls=np.array([0.0125, 0.035, 0.0304, 0.0295, 0.027, 0.0224, 0.0322, 0.028, 0.0298, 0.0199, 0.0103, 0.022, 0.003, 0.0017, 0.0017, 0.0041]),
        Dm=0.01 * np.array([4, 9.75, 10, 10, 3, 10, 8, 9, 14, 5.56, 13.6, 13.5, 33, 100, 100, 50], float),
        KA=40. * np.ones(m), TA=0.02 * np.ones(m), KE=1. * np.ones(m), TE=0.785 * np.ones(m),
        KF=0.063 * np.ones(m), TF=0.35 * np.ones(m), Ax=0.07 * np.ones(m), Bx=0.91 * np.ones(m),
        TCH=0.10 * np.ones(m), TSV=0.05 * np.ones(m), RD=0.05 * np.ones(m))
    return Case('NE68', m, n, ws, bus_type, bus[:, 2] / 100, bus[:, 3] / 100,
                bus[:, 7].copy(), gen[:, 0].astype(int), gen[:, 1] / 100,
                gen[:, 5].copy(), br[:, [0, 1, 2, 3, 4]].astype(float),
                tap=br[:, 8].copy(), gs=bus[:, 4] / 100, bs=bus[:, 5] / 100,
                machine=machine, Sbase_gen=100. * np.ones(m))


# ------------------------------------ IEEE 14 / 30 / 57 (MATPOWER, generic MD)
def _md_one(S):
    """Generic round-rotor synchronous machine (rating S MVA) on the 100-MVA
    base — for the standard IEEE cases, which ship no published dynamic data."""
    k = S / 100.0
    return dict(H=5.0 * k, Xd=1.8 / k, Xdp=0.30 / k, Xdpp=0.25 / k, Xq=1.7 / k,
                Xqp=0.55 / k, Xqpp=0.25 / k, Td0p=8.0, Td0pp=0.03, Tq0p=0.4,
                Tq0pp=0.05, Rs=0.0025 / k, Xls=0.2 / k, Dm=0.0, KA=20.0, TA=0.2,
                KE=1.0, TE=0.314, KF=0.063, TF=0.35, Ax=0.0039, Bx=1.555,
                TCH=0.1, TSV=0.05, RD=0.05)


def _machine_by_bus(n, gen_bus, Sbase):
    """Per-BUS machine arrays (length n) with each unit's generic data placed at
    its terminal bus.  This is the indexing System/units expect (they read
    machine data at case.gen_bus[k]-1), so generators may sit at ANY bus — not
    only buses 1..m.  This is why 14/30/57 (gens at scattered buses) now run."""
    ref = _md_one(100.0)
    machine = {key: np.full(n, ref[key], float) for key in ref}
    for k in range(len(gen_bus)):
        md = _md_one(float(Sbase[k])); i = int(gen_bus[k]) - 1
        for key, v in md.items():
            machine[key][i] = v
    return machine


def _matpower(name, casefile):
    """Build a Case straight from a bundled MATPOWER case .m file (same parser
    as ne68).  Handles the big IEEE imports too: out-of-service branches and
    offline units are dropped (MATPOWER status columns), non-consecutive bus
    ids are renumbered to 1..n (case300's numbering reaches 9533), and a PV
    bus left without an in-service unit is demoted to PQ so the power flow
    stays well-posed."""
    ws = 2 * np.pi * 60
    txt = open(os.path.join(_HERE, casefile)).read()
    bus = _mat(txt, r'mpc\.bus'); gen = _mat(txt, r'mpc\.gen'); br = _mat(txt, r'mpc\.branch')
    n = bus.shape[0]
    if br.shape[1] >= 11:
        br = br[br[:, 10] != 0]              # drop out-of-service branches
    if gen.shape[1] >= 8:
        gen = gen[gen[:, 7] > 0]             # drop offline units
    m = gen.shape[0]
    ids = bus[:, 0].astype(int)
    if not np.array_equal(ids, np.arange(1, n + 1)):
        idmap = np.zeros(ids.max() + 1, dtype=int)
        idmap[ids] = np.arange(1, n + 1)     # external id -> row index
        br = br.copy(); gen = gen.copy()
        br[:, 0] = idmap[br[:, 0].astype(int)]
        br[:, 1] = idmap[br[:, 1].astype(int)]
        gen[:, 0] = idmap[gen[:, 0].astype(int)]
    bus_type = bus[:, 1].astype(int)
    if not np.any(bus_type == 3):
        bus_type[0] = 3
    hasg = np.zeros(n + 1, dtype=bool)
    hasg[gen[:, 0].astype(int)] = True
    bus_type[(bus_type == 2) & ~hasg[1:]] = 1   # PV without a unit -> PQ
    Sbase = gen[:, 6].copy() if gen.shape[1] > 6 else 100.0 * np.ones(m)
    Sbase[~(Sbase > 0)] = 100.0
    tap = br[:, 8].copy() if br.shape[1] > 8 else None
    gb = gen[:, 0].astype(int)
    return Case(name, m, n, ws, bus_type, bus[:, 2] / 100, bus[:, 3] / 100,
                bus[:, 7].copy(), gb, gen[:, 1] / 100,
                gen[:, 5].copy(), br[:, [0, 1, 2, 3, 4]].astype(float),
                tap=tap, gs=bus[:, 4] / 100, bs=bus[:, 5] / 100,
                machine=_machine_by_bus(n, gb, Sbase), Sbase_gen=Sbase)


def ieee14():
    return _matpower('IEEE14', 'case14.m')


def ieee30():
    return _matpower('IEEE30', 'case30.m')


def ieee57():
    return _matpower('IEEE57', 'case57.m')


def ieee39():
    return _matpower('IEEE39', 'case39.m')


def ieee118():
    return _matpower('IEEE118', 'case118.m')


def ieee300():
    return _matpower('IEEE300', 'case300.m')
