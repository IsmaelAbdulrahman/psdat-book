"""
simulate.py — nonlinear time-domain simulation of the DAE.

Integrator: explicit RK4 on the differential states with a damped-Newton
solve of the algebraic network equations at every stage (the classical
partitioned-explicit approach [Kundur sec. 13.3]); the algebraic Jacobian
factor is refreshed periodically and at disturbance events.  This mirrors
the validated PSDAT-IBR reference implementation; the MATLAB twin uses
ode15s on the singular-mass-matrix DAE (simultaneous-implicit method).

THREE disturbance classes:
  network-side    — load change `dPload`, three-phase fault `fault`,
                    line outage/reclosure `line_trip`
  generator-side  — power set-point / mechanical-power pulse `gen_dist`
  source-side     — irradiance profile `G_prof` (cloud transient), wind
                    profile `vw_prof` (gust/ramp), NEW in PSDAT: the
                    renewable resource itself is the disturbance.

Pulse protocol: `gen_dist`/`dPload` are applied at t_dist and (if t_off is
given) removed at t_off, so the free ring-down after removal reveals the
mode damping (the apply-then-remove protocol of the original PSDAT study).
"""
import time
import numpy as np
from linearize import num_jac
from network import line_admittance_stamp


# ---------------------------------------------------------------- profiles
def step_profile(t0, val, base=1.0):
    """base -> base+val at t0 (smooth 50 ms ramp)."""
    def f(t):
        u = min(max((t - t0) / 0.05, 0.0), 1.0)
        return base + val * 0.5 * (1 - np.cos(np.pi * u))
    return f


def ramp_profile(t0, t1, val, base=1.0):
    """base -> base+val linearly over [t0, t1] (cloud passage, wind ramp)."""
    def f(t):
        u = min(max((t - t0) / (t1 - t0), 0.0), 1.0)
        return base + val * u
    return f


def cloud_profile(t0, depth, tdown=2.0, tlow=5.0, tup=5.0, base=1.0):
    """Cloud transient: irradiance dips by `depth` over tdown, stays low for
    tlow, recovers over tup — the standard PV cloud-shadow test."""
    def f(t):
        if t < t0:
            return base
        if t < t0 + tdown:
            return base - depth * 0.5 * (1 - np.cos(np.pi * (t - t0) / tdown))
        if t < t0 + tdown + tlow:
            return base - depth
        if t < t0 + tdown + tlow + tup:
            return base - depth * 0.5 * (1 + np.cos(np.pi * (t - t0 - tdown - tlow) / tup))
        return base
    return f


def gust_profile(t0, A, T=10.5, base=1.0):
    """IEC 61400-1 extreme-operating-gust ('Mexican hat'):
    v = base - 0.37*A*sin(3 pi tau/T)*(1 - cos(2 pi tau/T)), tau in [0,T]."""
    def f(t):
        tau = t - t0
        if tau < 0 or tau > T:
            return base
        return base - 0.37 * A * np.sin(3 * np.pi * tau / T) * (1 - np.cos(2 * np.pi * tau / T))
    return f


# ---------------------------------------------------------------- simulate
def simulate(sys, tsim=15.0, dt=2e-3, t_dist=1.0, t_off=None,
             dPload=None, gen_dist=None, fault=None, line_trip=None,
             G_prof=None, vw_prof=None, store=True, progress=False, method='rk4'):
    """Run the simulation.  Arguments:
      dPload    {bus0: dP}   network-side load change (pulse t_dist..t_off)
      gen_dist  {unit_k: dP} generator-side set-point pulse (t_dist..t_off)
      fault     (bus0, Yf_complex, ton, toff) three-phase fault via shunt
      line_trip (fbus, tbus, ton, toff)       outage of case line f-t (1-based)
      G_prof    {unit_k: fn(t)->G_multiplier}  PV irradiance (absolute, pu STC)
      vw_prof   {unit_k: fn(t)->vw_pu}         wind speed (absolute, pu rated)
    Returns T, X, Z."""
    case = sys.case
    x = sys.x0.copy()
    z = sys.z0.copy()

    Ytrip = None
    if line_trip is not None:
        fb, tb, ton_l, toff_l = line_trip
        row, tap = case.line(fb, tb)
        Ytrip = -line_admittance_stamp(case.n, row, tap)   # subtract the line
    Yf = None
    if fault is not None:
        fb, Yfv, ton_f, toff_f = fault
        Yf = np.zeros((case.n, case.n), complex)
        Yf[fb, fb] = Yfv

    # Smooth 50-ms event ramps, exactly as the MATLAB twin (PSDAT_TimeDomain):
    # an instantaneous admittance jump can throw the per-step algebraic Newton
    # from the physical network root onto the spurious low-voltage branch at
    # fault clearing; the raised-cosine ramp keeps the root a continuous
    # function of time, so the warm-started solve tracks it exactly.
    tr = 0.05
    def sramp(t, t0):
        if t0 is None:
            return 0.0
        return 0.5 * (1.0 - np.cos(np.pi * min(max((t - t0) / tr, 0.0), 1.0)))

    def inputs_at(t):
        """Assemble (uin, dl, Ye) at time t."""
        w = sramp(t, t_dist) - sramp(t, t_off)     # pulse weight (0..1, ramped)
        uin = {}
        if gen_dist and w > 0.0:
            for k, dp in gen_dist.items():
                uin.setdefault(k, {})['dP'] = dp * w
        if G_prof:
            for k, fn in G_prof.items():
                uin.setdefault(k, {})['G'] = fn(t)
        if vw_prof:
            for k, fn in vw_prof.items():
                uin.setdefault(k, {})['vw'] = fn(t)
        dl = None
        if dPload and w > 0.0:
            dl = {b: dp * w for b, dp in dPload.items()}
        Ye = None
        if Yf is not None:
            wf = sramp(t, ton_f) - sramp(t, toff_f)
            if wf > 0.0:
                Ye = Yf * wf
        if Ytrip is not None:
            wl = sramp(t, ton_l) - sramp(t, toff_l)
            if wl > 0.0:
                Ye = Ytrip * wl if Ye is None else Ye + Ytrip * wl
        return uin, dl, Ye

    def gz_at(xx, zz, uin, dl, Ye):
        return num_jac(lambda q: sys.dae(xx, q, uin, dl, Ye)[1], zz)

    def _inv(J):
        try:
            return np.linalg.inv(J)
        except np.linalg.LinAlgError:
            return np.linalg.pinv(J)

    # Newton iteration matrix: refreshed ADAPTIVELY — only near disturbance
    # events or when the iteration is struggling (>3 corrections).  A stale
    # iteration matrix still converges to the exact same algebraic solution
    # (it only affects the path, not the root), so results are unchanged
    # while steady stretches skip the expensive Jacobian entirely.
    state = {'fac': _inv(gz_at(x, z, {}, None, None)), 'hot': 0}

    _n = sys.case.n
    _Vsl = slice(sys.NZ - 2 * _n, sys.NZ - _n)     # bus |V| block inside z

    def _newton(zz, uin, dl, Ye, cap, iters, refreshes, xx):
        f = None
        fresh = 0
        for it in range(iters):
            f, g = sys.dae(xx, zz, uin, dl, Ye)
            if np.max(np.abs(g)) < 1e-9:
                break
            if fresh < refreshes and (fresh > 0 or it >= 3):
                state['fac'] = _inv(gz_at(xx, zz, uin, dl, Ye))
                fresh += 1
            dz = state['fac'] @ g
            s = 1.0
            mx = np.max(np.abs(dz))
            if mx > cap:                  # damp large algebraic jumps (faults)
                s = cap / mx
            zz = zz - s * dz
        return f, zz, it

    def deriv(xx, zz, uin, dl, Ye, robust=False):
        # Robust mode (inside a disturbance window): SMALL Newton caps and
        # fresh iteration matrices.  A hard-capped warm-started Newton cannot
        # leap across the solution valley onto the spurious low-voltage branch
        # of the network equations -- the classical collapse mode of partitioned
        # DAE integration during deep faults [Kundur sec. 13.3].
        z_in = zz
        if robust:
            f, zz, it = _newton(zz, uin, dl, Ye, 0.06, 30, 2, xx)
            # branch guard: a converged answer whose voltages DROPPED far below
            # the incoming point is retried with a tiny cap from the same start;
            # if the collapse is real (a genuinely unstable case) it recurs.
            if np.min(zz[_Vsl]) < np.min(z_in[_Vsl]) - 0.25:
                state['fac'] = _inv(gz_at(xx, z_in, uin, dl, Ye))
                f2, z2, it2 = _newton(z_in, uin, dl, Ye, 0.02, 60, 2, xx)
                g2 = np.max(np.abs(sys.dae(xx, z2, uin, dl, Ye)[1]))
                if g2 < 1e-8:
                    f, zz = f2, z2
        else:
            f, zz, it = _newton(zz, uin, dl, Ye, 0.25, 12, 1, xx)
        if it >= 3:
            state['hot'] = 3              # keep refreshing for the next steps
        return f, zz

    events = [t_dist] + ([t_off] if t_off else [])
    if fault is not None:
        events += [ton_f, toff_f]
    if line_trip is not None:
        events += [ton_l, toff_l]
    # robust-Newton SPANS: for a FAULT the whole window (not just its edges)
    # plus the trailing ramp -- with the big fault shunt in, the algebraic root
    # sits close to the solvability nose for the full duration, so the guarded
    # solver stays engaged from switch-on until a settling margin after clear.
    # Trips and pulses only stress the solve at their switching edges.
    spans = []
    if fault is not None:
        spans.append((ton_f, toff_f + tr + 0.06))
    for e in events:
        spans.append((e, e + tr + 0.06))

    # ---- alternative integrators: SciPy stiff/adaptive ODE solvers -----------
    # The DAE is integrated as an ODE — at every RHS evaluation the algebraic
    # network equations g(x,z)=0 are Newton-solved for z, then dx/dt = f(x,z).
    # This exposes SciPy's RK45 / Radau (implicit) / BDF (stiff, multistep) /
    # LSODA (auto stiff-switch) beside the built-in partitioned RK4.
    if method and str(method).lower() not in ('rk4', 'psdat', ''):
        try:
            from scipy.integrate import solve_ivp
            # cache the algebraic-Jacobian factor across RHS evaluations; warm-
            # started from the previous z it usually converges in 1-2 matvecs,
            # so the expensive finite-difference Jacobian is only refreshed when
            # the Newton loop actually struggles (near a disturbance) — this
            # keeps the implicit solvers within a small factor of built-in RK4.
            zc = {'z': z.copy(), 'fac': _inv(gz_at(x, z, {}, None, None))}
            t_wall = time.time()
            wall_cap = 10.0                # bail to RK4 if a stiff event grinds

            def _solvez(xx, zz, uin, dl, Ye):
                f = None
                fresh = False
                for it in range(40):
                    f, g = sys.dae(xx, zz, uin, dl, Ye)
                    if not np.all(np.isfinite(g)):     # diverged — bail fast
                        break
                    if np.max(np.abs(g)) < 1e-10:
                        break
                    if it >= 2 and not fresh:      # struggling: refresh once
                        zc['fac'] = _inv(gz_at(xx, zz, uin, dl, Ye))
                        fresh = True
                    dz = zc['fac'] @ g
                    mx = np.max(np.abs(dz))
                    if mx > 0.25:
                        dz = dz * (0.25 / mx)
                    zz = zz - dz
                return f, zz

            def rhs(t, xx):
                # a non-finite state means the solver has diverged on a stiff
                # event; raise so solve_ivp stops immediately (instead of
                # shrinking its step forever) and we fall back to RK4.  The
                # wall-clock cap bounds the time if it instead grinds with
                # ever-smaller steps around a discontinuity.
                if not np.all(np.isfinite(xx)) or time.time() - t_wall > wall_cap:
                    raise RuntimeError('state diverged / over time budget')
                uin, dl, Ye = inputs_at(t)
                f, zz = _solvez(xx, zc['z'].copy(), uin, dl, Ye)
                if not np.all(np.isfinite(f)):
                    raise RuntimeError('rhs diverged')
                zc['z'] = zz
                return f

            # Integrate PIECEWISE between the disturbance instants: within each
            # segment the RHS is smooth, so the adaptive solver never steps
            # across a fault/switch edge (which would wreck its order estimate)
            # — it restarts cleanly at every event.  x is continuous across the
            # events (only the algebraic z jumps), so the pieces join exactly.
            teval = np.linspace(0.0, tsim, int(round(tsim / dt)) + 1)
            bpts = sorted(set([0.0, tsim] + [e for e in events if 0.0 < e < tsim]))
            xseg = x.copy()
            Tacc, Xacc = [], []
            for a, b in zip(bpts[:-1], bpts[1:]):
                te = teval[(teval >= a - 1e-12) & (teval <= b + 1e-12)]
                if te.size == 0 or te[0] > a + 1e-12:
                    te = np.concatenate([[a], te])
                if te[-1] < b - 1e-12:
                    te = np.concatenate([te, [b]])
                sol = solve_ivp(rhs, (a, b), xseg, method=method, t_eval=te,
                                max_step=max(dt * 8, 0.05), rtol=1e-6, atol=1e-8)
                if not sol.success or not np.all(np.isfinite(sol.y)):
                    raise RuntimeError('scipy solver diverged on this case')
                i0 = 0 if not Tacc else 1           # drop duplicated segment start
                Tacc.append(sol.t[i0:])
                Xacc.append(sol.y.T[i0:])
                xseg = sol.y.T[-1]
            T = np.concatenate(Tacc)
            Xs = np.concatenate(Xacc)
            if not np.all(np.isfinite(Xs)):
                raise RuntimeError('non-finite trajectory')
            if not store:
                uin, dl, Ye = inputs_at(T[-1])
                _, zf = _solvez(Xs[-1], zc['z'].copy(), uin, dl, Ye)
                return T, Xs[-1], zf
            Zs = np.zeros((len(T), sys.NZ))
            zz = z.copy()
            for kk, tt in enumerate(T):
                uin, dl, Ye = inputs_at(tt)
                _, zz = _solvez(Xs[kk], zz, uin, dl, Ye)
                Zs[kk] = zz
            return T, Xs, Zs
        except Exception:
            # SciPy missing, or the adaptive solver failed on a stiff event:
            # never crash the app over a solver choice — fall through to the
            # built-in partitioned RK4, which truncates gracefully on divergence.
            pass

    nsteps = int(round(tsim / dt))
    T = np.zeros(nsteps + 1)
    if store:
        X = np.zeros((nsteps + 1, sys.NX))
        Z = np.zeros((nsteps + 1, sys.NZ))
        X[0] = x
        Z[0] = z
    for k in range(nsteps):
        t = k * dt
        tn = t + dt
        uin, dl, Ye = inputs_at(tn)
        near = any(a - 2 * dt <= tn <= b for a, b in spans)
        if near or state['hot'] > 0:      # events / recent struggle: refresh
            state['fac'] = _inv(gz_at(x, z, uin, dl, Ye))
            state['hot'] = max(state['hot'] - 1, 0)
        k1, z1 = deriv(x, z, uin, dl, Ye, near)
        k2, z2 = deriv(x + 0.5 * dt * k1, z1, uin, dl, Ye, near)
        k3, z3 = deriv(x + 0.5 * dt * k2, z2, uin, dl, Ye, near)
        k4, z4 = deriv(x + dt * k3, z3, uin, dl, Ye, near)
        x = x + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        if not np.all(np.isfinite(x)):    # diverged (unstable case): truncate
            T = T[:k + 1]
            if store:
                X = X[:k + 1]
                Z = Z[:k + 1]
            break
        _, z = deriv(x, z4, uin, dl, Ye, near)
        T[k + 1] = tn
        if store:
            X[k + 1] = x
            Z[k + 1] = z
        if progress and k % max(int(1.0 / dt), 1) == 0:
            print(f"    t = {t:.1f} s")
    if not store:
        return T, x, z
    return T, X, Z
