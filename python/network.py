"""
network.py — admittance matrix and Newton–Raphson power flow.

Polar power-balance network model at the quasi-static-phasor timescale
[Sauer & Pai, Power System Dynamics and Stability, ch. 7].  Handles
off-nominal transformer taps and bus shunts the same way MATPOWER does
[Zimmerman et al., IEEE Trans. Power Syst., 2011]:
    Yff = (ys + j*bc/2)/tap^2 ,  Yft = -ys/conj(tap),
    Ytf = -ys/tap ,             Ytt =  ys + j*bc/2 .

numpy only.
"""
import numpy as np


def build_ybus(n, branch, tap=None, gs=None, bs=None):
    """Bus admittance matrix.
    branch rows: [from, to, r, x, b_line_charging]  (1-based bus numbers)
    tap: per-branch off-nominal ratio (0 or 1 = none); gs, bs: bus shunts (pu).
    """
    Y = np.zeros((n, n), complex)
    for k in range(branch.shape[0]):
        f = int(branch[k, 0]) - 1
        t = int(branch[k, 1]) - 1
        r, x, b = branch[k, 2], branch[k, 3], branch[k, 4]
        a = 1.0
        if tap is not None and tap[k] != 0:
            a = tap[k]
        y = 1.0 / (r + 1j * x)
        bc = 1j * b / 2
        Y[f, f] += (y + bc) / (a * a)
        Y[t, t] += y + bc
        Y[f, t] -= y / np.conj(a)
        Y[t, f] -= y / a
    if gs is not None or bs is not None:
        # gs and bs stamp independently: a call that passes only bs (e.g. the
        # saturated-FACTS re-solve on a case with no conductive shunts) must
        # never have its susceptances silently dropped.
        g = np.zeros(n) if gs is None else np.asarray(gs, float)
        b = np.zeros(n) if bs is None else np.asarray(bs, float)
        for i in range(n):
            Y[i, i] += g[i] + 1j * b[i]
    return Y


def line_admittance_stamp(n, branch_row, tap=1.0):
    """Y-matrix stamp of ONE branch (for line-outage disturbances: Ybus - stamp
    removes the line; add it back to reclose)."""
    Y = np.zeros((n, n), complex)
    f = int(branch_row[0]) - 1
    t = int(branch_row[1]) - 1
    r, x, b = branch_row[2], branch_row[3], branch_row[4]
    a = 1.0 if (tap == 0) else tap
    y = 1.0 / (r + 1j * x)
    bc = 1j * b / 2
    Y[f, f] += (y + bc) / (a * a)
    Y[t, t] += y + bc
    Y[f, t] -= y / np.conj(a)
    Y[t, f] -= y / a
    return Y


def power_flow(Ybus, bus_type, Pd, Qd, Vm0, gen_bus, Pg_sched, Vg_sched,
               tol=1e-13, itmax=60, method='nr', branch=None, tap=None,
               report=False):
    """Power flow in polar form [Sauer & Pai, ch. 7].
    Returns V, theta (rad), and the NET generator injections Pg, Qg (pu) at
    every bus (load added back so Pg is what the generating unit produces).
    With `report=True` a fifth dict {method, iters, mismatch} is appended.

    `method` selects the iterative solver — all three converge to the *same*
    solution (they drive the identical nonlinear power-balance mismatch to
    zero); only the path and rate differ, which is exactly the teaching point:
      'nr'   full Newton-Raphson, polar  [Tinney & Hart 1967]  (quadratic)
      'fdlf' fast-decoupled, XB          [Stott & Alsac 1974]   (linear, cheap)
      'gs'   Gauss-Seidel on bus voltages [Ward & Hale 1956]    (linear, simple)
    `branch`/`tap` (optional) let the fast-decoupled B' use the proper
    series-reactance network; without them it falls back to -Im(Ybus).
    """
    n = len(bus_type)
    V = Vm0.copy().astype(float)
    th = np.zeros(n)
    pv = np.where(bus_type == 2)[0]
    pq = np.where(bus_type == 1)[0]
    Psp = np.zeros(n)
    for i, gb in enumerate(gen_bus):
        Psp[gb - 1] += Pg_sched[i]
        if bus_type[gb - 1] == 2:
            V[gb - 1] = Vg_sched[i]
    Psp = Psp - Pd
    Qsp = -Qd
    pvpq = np.sort(np.concatenate([pv, pq]))
    m = str(method or 'nr').lower()
    if m in ('fdlf', 'fd', 'fast', 'fastdecoupled'):
        V, th, iters = _pf_fdlf(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol,
                                max(itmax, 200), branch, tap, n)
        mname = 'fdlf'
    elif m in ('gs', 'gauss', 'gauss-seidel', 'gaussseidel'):
        V, th, iters = _pf_gauss(Ybus, Psp, Qsp, V, th, bus_type, gen_bus,
                                 Vg_sched, pq, pvpq, tol, max(itmax, 20000))
        mname = 'gs'
    else:
        V, th, iters = _pf_newton(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol, itmax)
        mname = 'nr'
    Vc = V * np.exp(1j * th)
    S = Vc * np.conj(Ybus @ Vc)
    if report:
        mis = np.concatenate([(Psp - S.real)[pvpq], (Qsp - S.imag)[pq]]) \
            if (len(pvpq) or len(pq)) else np.zeros(1)
        info = dict(method=mname, iters=int(iters),
                    mismatch=float(np.max(np.abs(mis))))
        return V, th, S.real + Pd, S.imag + Qd, info
    return V, th, S.real + Pd, S.imag + Qd


def _bprime(branch, n, pvpq):
    """B' for fast-decoupled load flow: the series-susceptance network built
    from reactance only (r, line charging, off-nominal taps and shunts all
    dropped — the Stott-Alsac XB approximation) restricted to the non-slack
    buses.  Returns None if branch data was not supplied."""
    if branch is None:
        return None
    Bp = np.zeros((n, n))
    for k in range(branch.shape[0]):
        f = int(branch[k, 0]) - 1
        t = int(branch[k, 1]) - 1
        x = branch[k, 3]
        if x == 0:
            continue
        b = 1.0 / x
        Bp[f, f] += b; Bp[t, t] += b
        Bp[f, t] -= b; Bp[t, f] -= b
    return Bp[np.ix_(pvpq, pvpq)]


def _pf_fdlf(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol, itmax, branch, tap, n):
    """Fast-decoupled load flow [Stott & Alsac, IEEE T-PAS 1974].  Constant,
    pre-factored decoupling matrices B' (angle, series-reactance network) and
    B'' (magnitude, full -Im Ybus) replace the Jacobian; each iteration is two
    cheap back-substitutions.  The true nonlinear mismatch is re-evaluated
    every half-step, so it lands on the same root as Newton — just linearly."""
    B = Ybus.imag
    Bp = _bprime(branch, n, pvpq)
    if Bp is None:                     # no branch data: -Im(Ybus) fallback
        Bp = -B[np.ix_(pvpq, pvpq)]
    Bpp = -B[np.ix_(pq, pq)]           # B'' : magnitude sub-problem (Q-V)
    have_pq = len(pq) > 0
    have_pvpq = len(pvpq) > 0
    it = 0
    for it in range(itmax):
        Vc = V * np.exp(1j * th)
        S = Vc * np.conj(Ybus @ Vc)
        P, Q = S.real, S.imag
        dP, dQ = (Psp - P), (Qsp - Q)
        if max(np.max(np.abs(dP[pvpq])) if have_pvpq else 0.0,
               np.max(np.abs(dQ[pq])) if have_pq else 0.0) < tol:
            break
        if have_pvpq:                  # P-theta half-iteration
            dth = np.linalg.solve(Bp, dP[pvpq] / V[pvpq])
            th[pvpq] += dth
        if have_pq:                    # recompute, then Q-V half-iteration
            Vc = V * np.exp(1j * th)
            Q = (Vc * np.conj(Ybus @ Vc)).imag
            dV = np.linalg.solve(Bpp, (Qsp - Q)[pq] / V[pq])
            V[pq] += dV
    return V, th, it


def _pf_gauss(Ybus, Psp, Qsp, V, th, bus_type, gen_bus, Vg_sched,
              pq, pvpq, tol, itmax, accel=1.6):
    """Gauss-Seidel on the complex bus voltages — the historically first
    digital power-flow method [Ward & Hale 1956].  Simple and memory-light but
    only linearly convergent; a fixed acceleration factor (SOR, alpha=1.6) is
    applied, the standard remedy that keeps it practical on larger nets."""
    Vc = (V * np.exp(1j * th)).astype(complex)
    Ssp = Psp + 1j * Qsp
    Vset = {}
    for i, gb in enumerate(gen_bus):
        if bus_type[gb - 1] == 2:
            Vset[gb - 1] = Vg_sched[i]
    pvset = set(np.where(bus_type == 2)[0].tolist())
    have_pq = len(pq) > 0
    have_pvpq = len(pvpq) > 0
    it = 0
    for it in range(itmax):
        for i in range(len(bus_type)):
            if bus_type[i] == 3:                      # slack fixed
                continue
            ksum = Ybus[i, :] @ Vc - Ybus[i, i] * Vc[i]
            if i in pvset:                            # PV: match Q, hold |V|
                Qi = -np.imag(np.conj(Vc[i]) * (ksum + Ybus[i, i] * Vc[i]))
                Si = Psp[i] + 1j * Qi
                Vnew = (np.conj(Si / Vc[i]) - ksum) / Ybus[i, i]
                Vacc = Vc[i] + accel * (Vnew - Vc[i])
                Vc[i] = Vset[i] * Vacc / abs(Vacc)    # re-impose scheduled |V|
            else:                                     # PQ: full update
                Vnew = (np.conj(Ssp[i] / Vc[i]) - ksum) / Ybus[i, i]
                Vc[i] = Vc[i] + accel * (Vnew - Vc[i])
        S = Vc * np.conj(Ybus @ Vc)
        dP, dQ = (Psp - S.real), (Qsp - S.imag)
        if max(np.max(np.abs(dP[pvpq])) if have_pvpq else 0.0,
               np.max(np.abs(dQ[pq])) if have_pq else 0.0) < tol:
            break
    return np.abs(Vc), np.angle(Vc), it


def _pf_newton(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol, itmax):
    """Full Newton-Raphson in polar form (the analytic-Jacobian workhorse)."""
    G = Ybus.real
    B = Ybus.imag
    it = 0
    for it in range(itmax):
        Vc = V * np.exp(1j * th)
        S = Vc * np.conj(Ybus @ Vc)
        P, Q = S.real, S.imag
        mism = np.concatenate([(Psp - P)[pvpq], (Qsp - Q)[pq]])
        if np.max(np.abs(mism)) < tol:
            break
        npv, npq = len(pvpq), len(pq)
        J11 = np.zeros((npv, npv)); J12 = np.zeros((npv, npq))
        J21 = np.zeros((npq, npv)); J22 = np.zeros((npq, npq))
        for a, i in enumerate(pvpq):
            for b_, k in enumerate(pvpq):
                J11[a, b_] = (-Q[i] - B[i, i] * V[i] ** 2) if i == k else \
                    V[i] * V[k] * (G[i, k] * np.sin(th[i] - th[k]) - B[i, k] * np.cos(th[i] - th[k]))
            for b_, k in enumerate(pq):
                J12[a, b_] = (P[i] / V[i] + G[i, i] * V[i]) if i == k else \
                    V[i] * (G[i, k] * np.cos(th[i] - th[k]) + B[i, k] * np.sin(th[i] - th[k]))
        for a, i in enumerate(pq):
            for b_, k in enumerate(pvpq):
                J21[a, b_] = (P[i] - G[i, i] * V[i] ** 2) if i == k else \
                    -V[i] * V[k] * (G[i, k] * np.cos(th[i] - th[k]) + B[i, k] * np.sin(th[i] - th[k]))
            for b_, k in enumerate(pq):
                J22[a, b_] = (Q[i] / V[i] - B[i, i] * V[i]) if i == k else \
                    V[i] * (G[i, k] * np.sin(th[i] - th[k]) - B[i, k] * np.cos(th[i] - th[k]))
        dx = np.linalg.solve(np.block([[J11, J12], [J21, J22]]), mism)
        th[pvpq] += dx[:npv]
        V[pq] += dx[npv:]
    return V, th, it
