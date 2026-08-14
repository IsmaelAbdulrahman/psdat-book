"""
facts.py — FACTS (Flexible AC Transmission Systems) device models.

This first increment covers the two SHUNT devices, which are the foundation
the series (TCSC/TSSC/SSSC) and combined (UPFC/IPFC) devices build on:

  SVC     — Static VAR Compensator.  A thyristor-controlled variable shunt
            SUSCEPTANCE B (pu on the 100-MVA base). Reactive injection into
            its bus is  Q = B*|V|^2, so its capability is a constant-impedance
            band  Q in [Bmin, Bmax]*|V|^2  (Q collapses as V^2 when V sags).
  STATCOM — Static Synchronous Compensator.  A voltage-source converter modelled
            as a controllable reactive CURRENT source, Q = |V|*I, with a
            constant-CURRENT limit  I in [-Imax, Imax]  (Q holds up far better
            than an SVC at low voltage — the key teaching contrast).

Both share ONE modular voltage-regulator: an integral (optionally proportional)
controller acting on a selectable measured signal (local bus |V| by default;
the `signal`/`rbus` fields are the hooks the WAMS/remote-signal phase extends),
with anti-windup at the device limits.  Steady state: the device holds its bus
at Vref within its limits; dynamics: one state (B or I) plus the regulator, added
to the same differential-algebraic system the machines use, so power flow,
small-signal and time-domain pick the device up automatically.

References: Hingorani & Gyugyi, *Understanding FACTS* (IEEE Press);
Acha et al., *FACTS: Modelling and Simulation in Power Networks* (Wiley);
Canizares, IEEE T-PWRS 2000 (SVC/STATCOM steady-state & stability models).
"""
import numpy as np

# shunt devices sit at a bus; series devices sit ON a line (branch);
# combined devices couple a shunt + series (UPFC) or two series (IPFC).
SHUNT = ('SVC', 'STATCOM')
SERIES = ('TCSC', 'TSSC', 'SSSC')
COMBINED = ('UPFC', 'IPFC')


# ===================================================================== POD / WADC
# Modular supplementary (Power-Oscillation-Damping / Wide-Area-Damping) controller
# that can be attached to any FACTS device.  It reads ONE measured feedback signal
# — local OR remote (WAMS/PMU): a bus |V|, a line power/current, a bus-angle
# difference, or a remote generator speed — passes it through an optional
# measurement lag (WAMS latency), a washout, nc identical lead-lag stages and a
# gain, hard-limits the result, and adds it to the device reference (ΔVref for a
# shunt regulator, Δkcomp for a series compensator).  The block realization is
# byte-for-byte the one design.pod_ss() designs and closed_loop() verifies, so a
# controller tuned by the residue-based POD-design tool can be typed straight in
# here and the persistent closed-loop model reproduces the predicted damping.
#
# Signal is fed as a DEVIATION (s - s0) about the operating point (s0 measured by
# System after init), so every controller state is 0 at equilibrium and the device
# operating point, power flow and all published results are unchanged when K=0 or
# the loop is disabled.  States (in order): [lag?] washout, LL1..LLnc.
POD_SIGNALS = ('Vbus', 'Pline', 'Qline', 'Iline', 'adiff', 'wgen', 'angle')
# Feedback-signal menu of the POD/WADC controller (each local OR remote):
#   Vbus  — |V| of the device bus, or of any remote bus (rbus)     [local / remote voltage]
#   Pline — active-power flow of any line f-t (tie-line power)     [P, tie-line MW]
#   Qline — reactive-power flow of any line f-t                    [Q]
#   Iline — current magnitude of any line f-t                      [line current]
#   adiff — bus-voltage-angle difference th_i - th_j               [angle spread]
#   wgen  — rotor speed of the machine at any bus (≈ local freq)   [rotor speed / frequency]
#   angle — bus voltage angle at any bus                           [PMU phase]
# A remote choice (rbus / f,t / i,j away from the device) plus the measurement
# delay tau IS the WAMS/PMU channel: the signal travels through the wide-area
# network and arrives lagged by tau seconds (modelled as a first-order lag).

def _pod_defaults():
    """Default supplementary-controller block (disabled -> zero extra states)."""
    return dict(on=False, sig='Vbus', rbus=0, f=0, t=0, i=0, j=0,
                tau=0.0, Tw=10.0, T1=0.30, T2=0.05, nc=2, K=0.0,
                lo=-0.10, hi=0.10, ctype='leadlag', Ki=0.5, Kd=0.05, Tf=0.02)

def pod_cfg(d):
    """Merge a device's `pod` sub-dict onto the defaults (None -> disabled)."""
    p = dict(_pod_defaults())
    src = d.get('pod') if isinstance(d, dict) else None
    if isinstance(src, dict):
        p.update({k: src[k] for k in src if k in p})
    return p

def pod_nstate(pod):
    """Number of controller states this POD block adds (0 when disabled)."""
    if not pod or not pod.get('on'):
        return 0
    nlag = 1 if float(pod.get('tau', 0.0) or 0.0) > 1e-9 else 0
    ct = str(pod.get('ctype', 'leadlag') or 'leadlag').lower()
    if ct == 'pi':                                           # lag? + integrator
        return nlag + 1
    if ct == 'pid':                                          # lag? + integrator + D filter
        return nlag + 2
    return nlag + 1 + max(0, int(pod.get('nc', 2)))          # lag? + washout + nc LL

def pod_names(pod):
    if not pod or not pod.get('on'):
        return []
    names = ['podLag'] if float(pod.get('tau', 0.0) or 0.0) > 1e-9 else []
    ct = str(pod.get('ctype', 'leadlag') or 'leadlag').lower()
    if ct == 'pi':
        return names + ['podInt']
    if ct == 'pid':
        return names + ['podInt', 'podDf']
    return names + ['podWo'] + [f'podLL{j + 1}' for j in range(max(0, int(pod.get('nc', 2))))]

def pod_output(xc, s_dev, pod):
    """Advance the POD block: controller sub-states `xc` (len pod_nstate) and the
    deviation input `s_dev` -> (state derivatives dxc, limited output Vpod).
    washout sTw/(1+sTw) -> (1+sT1)/(1+sT2) x nc -> gain K -> clamp[lo,hi].
    Same state-space as design.pod_ss (washout x'=-x/Tw+u, y=u-x/Tw; lead-lag
    x'=(u-x)/T2, y=(1-T1/T2)x+(T1/T2)u)."""
    Tw = max(float(pod.get('Tw', 10.0)), 1e-3)
    T1 = max(float(pod.get('T1', 0.30)), 1e-4)
    T2 = max(float(pod.get('T2', 0.05)), 1e-4)
    nc = max(0, int(pod.get('nc', 2)))
    K = float(pod.get('K', 0.0))
    lo, hi = float(pod.get('lo', -0.10)), float(pod.get('hi', 0.10))
    tau = float(pod.get('tau', 0.0) or 0.0)
    dx = np.empty(len(xc))
    idx = 0
    u = s_dev
    if tau > 1e-9:                                    # measurement lag 1/(1+s tau)
        xl = xc[idx]; dx[idx] = (s_dev - xl) / max(tau, 1e-3); u = xl; idx += 1
    ct = str(pod.get('ctype', 'leadlag') or 'leadlag').lower()
    if ct in ('pi', 'pid'):
        # PI / PID on the deviation input [Astrom & Hagglund]: y = Kp e + Ki xI
        # (+ Kd * filtered de/dt).  Anti-windup by CONDITIONAL INTEGRATION: the
        # integrator freezes while the output is clamped AND the error keeps
        # pushing further into the limit.
        Ki = float(pod.get('Ki', 0.5)); Kd = float(pod.get('Kd', 0.05))
        Tf = max(float(pod.get('Tf', 0.02)), 1e-3)
        ii = idx; xi_ = xc[ii]; idx += 1
        y = K * u + Ki * xi_
        if ct == 'pid':
            xd = xc[idx]; yd = (u - xd) / Tf
            dx[idx] = yd; y = y + Kd * yd; idx += 1
        Vpod = min(max(y, lo), hi)
        dx[ii] = 0.0 if ((y > hi and u > 0.0) or (y < lo and u < 0.0)) else u
        return dx, Vpod
    xw = xc[idx]; dx[idx] = -xw / Tw + u; y = u - xw / Tw; idx += 1      # washout
    for _ in range(nc):                                                 # lead-lag x nc
        xj = xc[idx]; dx[idx] = (y - xj) / T2; y = (1.0 - T1 / T2) * xj + (T1 / T2) * y
        idx += 1
    Vpod = min(max(K * y, lo), hi)                                       # gain + limiter
    return dx, Vpod


def default_facts(kind, Vref=1.0):
    """Reasonable default parameters for a newly-dropped FACTS device (pu on the
    100-MVA system base).  Editable in the parameter editor."""
    kind = str(kind).upper()
    if kind == 'UPFC':
        # Unified Power Flow Controller: a shunt converter (STATCOM at bus, holds
        # V) + a series converter (SSSC on line f-t, controls the flow), coupled
        # by a common DC link.  v1 composes the two verified primitives.
        return dict(type='UPFC', bus=0, f=0, t=0, Vref=float(Vref), Imax=2.0,
                    Imin=-2.0, kcomp=0.3, kmin=-0.2, kmax=0.7, Vsemax=0.20,
                    Kr=20.0, Tr=0.05, Kaw=150.0, droop=0.0)
    if kind == 'IPFC':
        # Interline Power Flow Controller: two series converters on two lines,
        # coupled by a common DC link.  v1 composes two series compensators.
        return dict(type='IPFC', f=0, t=0, f2=0, t2=0, kcomp=0.3, kcomp2=0.2,
                    kmin=-0.2, kmax=0.7, Vsemax=0.20)
    if kind in SERIES:
        # series compensation: the device inserts a reactance in the line, set as
        # a compensation fraction kcomp of the line reactance (kcomp>0 = capacitive,
        # x_eff = x_line*(1-kcomp), which BOOSTS the transferable power).
        base = dict(type=kind, f=0, t=0, kcomp=0.4, kmin=-0.2, kmax=0.7,
                    Tc=0.02, mode='const')
        if kind == 'SSSC':
            base.update(Vsemax=0.20)              # max injected series voltage (pu)
        if kind in ('TCSC', 'SSSC'):             # continuously controllable -> POD-capable
            base['pod'] = _pod_defaults()
        return base
    base = dict(type=kind, Vref=float(Vref), Kr=20.0, Tr=0.05, Kaw=150.0,
                droop=0.0, signal='V', rbus=0, tdelay=0.0, pod=_pod_defaults())
    if kind == 'SVC':
        base.update(Bmax=2.0, Bmin=-2.0)          # +/-200 MVAr at 1 pu
    else:  # STATCOM
        base.update(Imax=2.0, Imin=-2.0)          # +/-2 pu reactive current
    return base


# --------------------------------------------------------- series compensation
def _find_branch(branch, f, t):
    """Row of the first branch between buses f and t (either orientation)."""
    for k in range(branch.shape[0]):
        bf, bt = int(branch[k, 0]), int(branch[k, 1])
        if (bf == f and bt == t) or (bf == t and bt == f):
            return k
    return None


def apply_series(branch, facts):
    """Insert each series device's compensation into its line BEFORE the Ybus is
    built: x_eff = x_line*(1-kcomp), clamped to [kmin,kmax].  Records the branch
    row and base reactance on the device so the operating point can be reported.
    Returns a modified copy of `branch` (the originals are left untouched)."""
    br = branch.copy().astype(float)
    for d in facts or []:
        if str(d.get('type', '')).upper() not in SERIES:
            continue
        k = _find_branch(br, int(d.get('f', 0)), int(d.get('t', 0)))
        if k is None:
            d['_br'] = -1
            continue
        kc = min(max(float(d.get('kcomp', 0.4)),
                     float(d.get('kmin', -0.2))), float(d.get('kmax', 0.7)))
        xl = float(branch[k, 3])
        d['_br'] = k
        d['_kc'] = kc
        d['_xline'] = xl
        d['_Xc'] = -kc * xl                       # inserted reactance (cap<0)
        br[k, 3] = xl * (1.0 - kc)                # x_eff
    return br


def series_oppoint(facts, V0, TH0, branch, tap=None):
    """After the load flow, record each series device's operating point on the
    device dict: line current, injected series voltage Vse=|Xc*I|, and the line
    active-power flow.  For an SSSC also flag if Vse hit its voltage rating."""
    Vc = V0 * np.exp(1j * TH0)
    for d in facts or []:
        if str(d.get('type', '')).upper() not in SERIES:
            continue
        k = d.get('_br', -1)
        if k is None or k < 0:
            continue
        f = int(branch[k, 0]) - 1
        t = int(branch[k, 1]) - 1
        r = float(branch[k, 2]); xeff = float(branch[k, 3]); b = float(branch[k, 4])
        a = 1.0
        if tap is not None and tap[k] != 0:
            a = tap[k]
        y = 1.0 / (r + 1j * xeff)
        Ise = (Vc[f] / a - Vc[t]) * y             # series current through the line
        Imag = abs(Ise)
        Xc = float(d.get('_Xc', 0.0))
        Sf = (Vc[f] / a) * np.conj(Ise + Vc[f] / a * (1j * b / 2))
        d['_I'] = round(Imag, 3)
        d['_Vse'] = round(abs(Xc) * Imag, 4)      # injected series-voltage magnitude
        d['_Pline'] = round(float(Sf.real) * 100, 1)
        d['_satV'] = bool(str(d['type']).upper() == 'SSSC'
                          and abs(Xc) * Imag > float(d.get('Vsemax', 0.20)) + 1e-9)


# --------------------------------------------- dynamic series (POD-modulated)
# A continuously-controllable series device (TCSC / SSSC) with its POD enabled
# carries a first-order compensation state k(t): dk/dt = (k_cmd - k)/Tc, where
# k_cmd = clip(k0 + Vpod, kmin, kmax) and Vpod is the supplementary-controller
# output.  The base compensation k0 is already in Ybus (apply_series); the DYNAMIC
# deviation from k0 enters the DAE as an admittance-stamp perturbation ΔY(k) on the
# device's line (system.dae), so the operating point is reproduced exactly at k=k0
# and small-signal / time-domain pick up the modulation with no extra machinery.
def series_dynamic(d):
    """True if this series device carries a dynamic (POD-modulated) state."""
    return (str(d.get('type', '')).upper() in ('TCSC', 'SSSC')
            and isinstance(d.get('pod'), dict) and bool(d['pod'].get('on')))

def series_dy(r, xline, a, k, k0):
    """Δ(series admittance) of the compensation deviation k-k0 for the ΔY stamp:
    Δy = 1/(r + j x(1-k)) − 1/(r + j x(1-k0)).  (charging b and tap are unchanged
    by compensation, so only the series branch admittance moves.)"""
    y = 1.0 / (r + 1j * xline * (1.0 - k))
    y0 = 1.0 / (r + 1j * xline * (1.0 - k0))
    return y - y0


# ------------------------------------------------------- combined devices
def upfc_pq(d):
    """A UPFC in DC-coupled independent-P-Q control mode carries numeric line-flow
    targets Pset (MW) and Qset (MVAr); otherwise it runs in the composed
    voltage/reactance mode (STATCOM shunt + SSSC series)."""
    return (str(d.get('type', '')).upper() == 'UPFC'
            and d.get('Pset') is not None and d.get('Qset') is not None
            and str(d.get('mode', '')).lower() in ('', 'pq', 'p-q', 'pqctrl'))


def ipfc_pq(d):
    """An IPFC in DC-coupled P-Q control mode: the master converter (line f-t)
    holds P1set + jQ1set, the slave (line f2-t2) holds Q2set and supplies the
    balancing real power through the common DC link (P_se1 + P_se2 = 0)."""
    return (str(d.get('type', '')).upper() == 'IPFC'
            and d.get('P1set') is not None and d.get('Q1set') is not None
            and d.get('Q2set') is not None
            and int(d.get('f2', 0)) and int(d.get('t2', 0))
            and str(d.get('mode', '')).lower() in ('pq', 'p-q', 'pqctrl'))


# ------- DC-coupled IPFC: series-voltage-source model (relaxed fixed point) ----
def _line_yb(branch, row):
    r, x, b = float(branch[row, 2]), float(branch[row, 3]), float(branch[row, 4])
    return 1.0 / (r + 1j * x), 1j * b / 2.0


def _ipfc_deliv(Vf, Vt, Vse, y, bc):
    """Complex power delivered TO the receiving bus by a line with series source."""
    Ef = Vf + Vse
    return Vt * np.conj(y * Ef - (y + bc) * Vt)


def _ipfc_pse(Vf, Vt, Vse, y, bc):
    Ef = Vf + Vse
    return float((Vse * np.conj((y + bc) * Ef - y * Vt)).real)


def _ipfc_vse_master(Vf, Vt, S1, y, bc):
    """Algebraic series voltage that delivers S1 at the receiving bus."""
    Ic = np.conj(S1 / Vt)
    return (Ic + (y + bc) * Vt) / y - Vf


def _ipfc_vse_slave(Vf, Vt, Q2, Pse_tgt, y, bc, x0=0j):
    """2-D Newton for the slave series voltage: Im(delivered)=Q2, Re(S_se)=Pse_tgt."""
    v = np.array([x0.real, x0.imag], float)
    for _ in range(40):
        Vse = v[0] + 1j * v[1]
        F = np.array([_ipfc_deliv(Vf, Vt, Vse, y, bc).imag - Q2,
                      _ipfc_pse(Vf, Vt, Vse, y, bc) - Pse_tgt])
        if np.max(np.abs(F)) < 1e-13:
            break
        J = np.empty((2, 2)); eps = 1e-7
        for j in range(2):
            vp = v.copy(); vp[j] += eps; Vp = vp[0] + 1j * vp[1]
            J[:, j] = (np.array([_ipfc_deliv(Vf, Vt, Vp, y, bc).imag - Q2,
                                 _ipfc_pse(Vf, Vt, Vp, y, bc) - Pse_tgt]) - F) / eps
        try:
            v = v - np.linalg.solve(J, F)
        except np.linalg.LinAlgError:
            break
    return v[0] + 1j * v[1]


def _ipfc_clamp(Vse, vmax):
    m = abs(Vse)
    return Vse * (vmax / m) if m > vmax else Vse


def _ipfc_inj(Vf, Vt, Vse, y, bc):
    """ΔS added as extra load at the two terminals (vs. the plain line in Ybus)."""
    return Vf * np.conj((y + bc) * Vse), Vt * np.conj(-y * Vse)


def ipfc_pq_solve(dev, Ybus, bus_type, Pd, Qd, Vm0, gen_bus, Pg, Vg, branch, tap,
                  power_flow, vmax=None, cap=90):
    """Solve one DC-coupled IPFC for its constant ΔS injections (pu) at the target
    operating point, plus a report dict.  Returns (dPd, dQd, rep).

    Model: each converter is a series voltage source Vse inserted on its line; both
    lines stay in Ybus (robust, never islands the common bus) and the sources' effect
    is added as ΔS load offsets at the four terminals.  The master (line 1) holds the
    delivered S1 = P1set + jQ1set; the slave (line 2) holds the delivered Q2set and
    supplies the DC-balancing real power P_se2 = -P_se1.

    Method — augmented Newton with continuation.  The unknowns are the bus voltage
    angles/magnitudes *and* the two complex series voltages; the equations are the
    network power balance (with the ΔS injections) plus four controls: Re S1 = P1,
    Im S1 = Q1, Im S2 = Q2, and P_se1 + P_se2 = 0.  Solving all of them together gives
    quadratic convergence independent of the network coupling.  The delivered-power
    constraint has a low- and a high-effort branch; to land on the physical (low-effort)
    one we ramp the targets from the natural flows (Vse = 0) to the setpoints and
    Newton-solve each step warm-started from the last.  Feasible setpoints are hit to
    machine precision in a couple of steps; a setpoint past the corridor's transfer
    limit (a fold) or the |Vse| ≤ Vsemax rating stops at the boundary and is flagged."""
    n = len(Pd)

    def row_of(f, t):
        for k in range(branch.shape[0]):
            bf, bt = int(branch[k, 0]), int(branch[k, 1])
            if (bf == f and bt == t) or (bf == t and bt == f):
                return k
        return -1

    f1, t1 = int(dev['f']), int(dev['t'])
    f2, t2 = int(dev['f2']), int(dev['t2'])
    r1, r2 = row_of(f1, t1), row_of(f2, t2)
    if r1 < 0 or r2 < 0:
        return np.zeros(n), np.zeros(n), dict(ok=False)
    y1, bc1 = _line_yb(branch, r1)
    y2, bc2 = _line_yb(branch, r2)
    P1 = float(dev['P1set']) / 100.0
    Q1 = float(dev['Q1set']) / 100.0
    Q2 = float(dev['Q2set']) / 100.0
    if vmax is None:
        vmax = float(dev.get('Vsemax', 0.30) or 0.30)

    # index sets and fixed schedules for the augmented power-flow residual
    slack = int(np.where(np.asarray(bus_type) == 3)[0][0])
    pq = [i for i in range(n) if bus_type[i] == 1]
    nonslack = [i for i in range(n) if i != slack]
    Pgb = np.zeros(n)
    for k, b in enumerate(gen_bus):
        Pgb[int(b) - 1] = Pg[k]
    Psch = Pgb - Pd                       # scheduled real injection (slack free)
    Qsch = -Qd                            # scheduled reactive injection (gen Q free)
    Vfix = np.array(Vm0, float).copy()
    for k, b in enumerate(gen_bus):
        Vfix[int(b) - 1] = Vg[k]          # |V| held at the generator setpoints
    nx = len(nonslack) + len(pq) + 4
    nfev = [0]

    def unpack(x):
        th = np.zeros(n); Vm = Vfix.copy()
        for j, i in enumerate(nonslack):
            th[i] = x[j]
        off = len(nonslack)
        for j, i in enumerate(pq):
            Vm[i] = x[off + j]
        off += len(pq)
        return th, Vm, x[off] + 1j * x[off + 1], x[off + 2] + 1j * x[off + 3]

    def pack(th, Vm, V1, V2):
        return np.array([th[i] for i in nonslack] + [Vm[i] for i in pq]
                        + [V1.real, V1.imag, V2.real, V2.imag])

    def inj(V, V1, V2):
        dS = np.zeros(n, complex)
        s1f, s1t = _ipfc_inj(V[f1 - 1], V[t1 - 1], V1, y1, bc1)
        s2f, s2t = _ipfc_inj(V[f2 - 1], V[t2 - 1], V2, y2, bc2)
        for bus, ds in [(f1, s1f), (t1, s1t), (f2, s2f), (t2, s2t)]:
            dS[bus - 1] += ds
        return dS

    def resid(x, S1t, Q2t):
        th, Vm, V1, V2 = unpack(x)
        V = Vm * np.exp(1j * th)
        Sm = V * np.conj(Ybus @ V) + inj(V, V1, V2) - (Psch + 1j * Qsch)
        S1 = _ipfc_deliv(V[f1 - 1], V[t1 - 1], V1, y1, bc1)
        S2 = _ipfc_deliv(V[f2 - 1], V[t2 - 1], V2, y2, bc2)
        Pse1 = _ipfc_pse(V[f1 - 1], V[t1 - 1], V1, y1, bc1)
        Pse2 = _ipfc_pse(V[f2 - 1], V[t2 - 1], V2, y2, bc2)
        return np.array([Sm[i].real for i in nonslack] + [Sm[i].imag for i in pq]
                        + [S1.real - S1t.real, S1.imag - S1t.imag, S2.imag - Q2t, Pse1 + Pse2])

    def newton(x0, S1t, Q2t, tol=1e-11, itmax=25):
        x = x0.copy()
        for _ in range(itmax):
            r = resid(x, S1t, Q2t)
            nr = float(np.max(np.abs(r)))
            if nr < tol:
                return x, True, nr
            J = np.empty((nx, nx))
            for j in range(nx):
                xp = x.copy(); xp[j] += 1e-7
                J[:, j] = (resid(xp, S1t, Q2t) - r) / 1e-7
            nfev[0] += 1
            try:
                dx = np.linalg.solve(J, -r)
            except np.linalg.LinAlgError:
                return x, False, nr
            step = 1.0                         # backtracking line search
            for _ in range(20):
                if float(np.max(np.abs(resid(x + step * dx, S1t, Q2t)))) < nr:
                    break
                step *= 0.5
            x = x + step * dx
        nr = float(np.max(np.abs(resid(x, S1t, Q2t))))
        return x, nr < 1e-8, nr

    def maxvse(x):
        _, _, V1, V2 = unpack(x)
        return max(abs(V1), abs(V2))

    # natural corridor flows (Vse = 0) — the continuation anchor
    V0, TH0, _, _ = power_flow(Ybus, bus_type, Pd, Qd, Vm0, gen_bus, Pg, Vg)
    Vc0 = V0 * np.exp(1j * TH0)
    S1n = _ipfc_deliv(Vc0[f1 - 1], Vc0[t1 - 1], 0j, y1, bc1)
    S2n = _ipfc_deliv(Vc0[f2 - 1], Vc0[t2 - 1], 0j, y2, bc2)

    def interp(lam):
        return ((S1n.real + lam * (P1 - S1n.real)) + 1j * (S1n.imag + lam * (Q1 - S1n.imag)),
                S2n.imag + lam * (Q2 - S2n.imag))

    x = pack(TH0, V0, 1e-3 + 1e-3j, 1e-3 + 1e-3j)
    lam = 0.0; dlam = 0.5
    while lam < 1 - 1e-9 and nfev[0] < cap:
        trial = min(lam + dlam, 1.0)
        S1t, Q2t = interp(trial)
        xn, ok, _ = newton(x, S1t, Q2t)
        if ok and maxvse(xn) <= vmax + 1e-9:
            lam = trial; x = xn
            dlam = min(dlam * 1.5, 0.5)
        else:
            dlam *= 0.5
            if dlam < 1e-3:                    # boundary — bisect to the last feasible point
                lo, hi = lam, min(lam + 2 * dlam, 1.0)
                for _ in range(30):
                    mid = 0.5 * (lo + hi)
                    S1t, Q2t = interp(mid)
                    xm, okm, _ = newton(x, S1t, Q2t)
                    if okm and maxvse(xm) <= vmax + 1e-9:
                        lo = mid; x = xm
                    else:
                        hi = mid
                lam = lo
                break

    th, Vm, V1, V2 = unpack(x)
    V = Vm * np.exp(1j * th)
    dS = inj(V, V1, V2)
    S1 = _ipfc_deliv(V[f1 - 1], V[t1 - 1], V1, y1, bc1) * 100
    S2 = _ipfc_deliv(V[f2 - 1], V[t2 - 1], V2, y2, bc2) * 100
    limited = lam < 1 - 1e-6
    sat = (abs(V1) >= vmax - 1e-4) or (abs(V2) >= vmax - 1e-4)
    rep = dict(ok=True, iters=nfev[0], lam=lam, limited=bool(limited), saturated=bool(sat),
               S1=S1, S2=S2,
               Pse1=_ipfc_pse(V[f1 - 1], V[t1 - 1], V1, y1, bc1) * 100,
               Pse2=_ipfc_pse(V[f2 - 1], V[t2 - 1], V2, y2, bc2) * 100,
               Vse1=abs(V1), Vse2=abs(V2))
    return dS.real.copy(), dS.imag.copy(), rep


def upfc_pq_prepare(facts, branch, tap, n, Pd, Qd):
    """DC-coupled UPFC (P-Q mode) steady-state model: the series converter forces
    the corridor to deliver Pset+jQset at the receiving bus while the shunt holds
    the sending bus at Vref and supplies the series real power through the DC link
    (so the device is real-power-neutral to the grid and P,Q are set
    independently).  Realized as the decoupled-injection model — remove the line
    f-t, draw Pset at f, inject Pset+jQset at t — plus a shunt regulator at f.
    Returns (line_stamps_to_subtract, Pd, Qd, statcoms_to_add); Pd,Qd are copies."""
    Pd = np.array(Pd, float).copy()
    Qd = np.array(Qd, float).copy()
    stamps = []
    statcoms = []
    from network import line_admittance_stamp
    for idx, d in enumerate(facts or []):
        if not upfc_pq(d):
            continue
        f, t = int(d.get('f', 0)), int(d.get('t', 0))
        if not (1 <= f <= n and 1 <= t <= n and f != t):
            continue
        row = _find_branch(branch, f, t)
        if row is None:
            continue
        tp = 1.0 if (tap is None or tap[row] == 0) else tap[row]
        stamps.append(line_admittance_stamp(n, branch[row], tp))
        P = float(d.get('Pset', 0.0)) / 100.0
        Q = float(d.get('Qset', 0.0)) / 100.0
        Pd[f - 1] += P                                # sending bus pushes P into the corridor
        Pd[t - 1] -= P                                # receiving bus gets P + jQ (negative load)
        Qd[t - 1] -= Q
        statcoms.append(dict(type='STATCOM', bus=f, Vref=float(d.get('Vref', 1.0)),
                             Imax=float(d.get('Imax', 2.0)), Imin=float(d.get('Imin', -2.0)),
                             Kr=float(d.get('Kr', 20.0)), Tr=float(d.get('Tr', 0.05)),
                             Kaw=float(d.get('Kaw', 150.0)), droop=0.0, signal='V',
                             pod=(d.get('pod') if isinstance(d.get('pod'), dict) else None),
                             _parent=idx, _ptype='UPFC', _pqf=f, _pqt=t,
                             _Pset=float(d.get('Pset', 0.0)), _Qset=float(d.get('Qset', 0.0))))
    return stamps, Pd, Qd, statcoms


def expand_combined(facts):
    """Expand each UPFC / IPFC into the primitive shunt + series devices the
    engine already understands, tagging every part with `_parent` (index of the
    combined device) and `_ptype` so results can be grouped back in the UI.
    Shunt and series devices pass through unchanged.  A UPFC in P-Q control mode
    is handled by cases.Case (upfc_pq_prepare) — its shunt regulator is injected
    there — so here it collapses to nothing (its line/injection edits are applied
    to the network, not modelled as an extra series primitive)."""
    out = []
    for idx, d in enumerate(facts or []):
        t = str(d.get('type', '')).upper()
        if t == 'UPFC' and upfc_pq(d):
            out.append(d)                             # P-Q UPFC: kept for cases.Case to realize
            continue
        if t == 'IPFC' and ipfc_pq(d):
            out.append(d)                             # P-Q IPFC: kept for cases.Case to realize
            continue
        if t == 'UPFC':
            out.append(dict(type='STATCOM', bus=int(d.get('bus', 0)),
                            Vref=float(d.get('Vref', 1.0)), Imax=float(d.get('Imax', 2.0)),
                            Imin=float(d.get('Imin', -2.0)), Kr=float(d.get('Kr', 20.0)),
                            Tr=float(d.get('Tr', 0.05)), Kaw=float(d.get('Kaw', 150.0)),
                            droop=float(d.get('droop', 0.0)), signal='V',
                            pod=(d.get('pod') if isinstance(d.get('pod'), dict) else None),
                            _parent=idx, _ptype='UPFC'))
            out.append(dict(type='SSSC', f=int(d.get('f', 0)), t=int(d.get('t', 0)),
                            kcomp=float(d.get('kcomp', 0.3)), kmin=float(d.get('kmin', -0.2)),
                            kmax=float(d.get('kmax', 0.7)), Vsemax=float(d.get('Vsemax', 0.20)),
                            _parent=idx, _ptype='UPFC'))
        elif t == 'IPFC':
            out.append(dict(type='SSSC', f=int(d.get('f', 0)), t=int(d.get('t', 0)),
                            kcomp=float(d.get('kcomp', 0.3)), kmin=float(d.get('kmin', -0.2)),
                            kmax=float(d.get('kmax', 0.7)), Vsemax=float(d.get('Vsemax', 0.20)),
                            _parent=idx, _ptype='IPFC'))
            f2, t2 = int(d.get('f2', 0)), int(d.get('t2', 0))
            if f2 and t2 and f2 != t2:            # second converter only once line 2 is set
                out.append(dict(type='SSSC', f=f2, t=t2,
                                kcomp=float(d.get('kcomp2', 0.2)), kmin=float(d.get('kmin', -0.2)),
                                kmax=float(d.get('kmax', 0.7)), Vsemax=float(d.get('Vsemax', 0.20)),
                                _parent=idx, _ptype='IPFC'))
        else:
            out.append(d)
    return out


# ----------------------------------------------------------------- steady state
def facts_pf_setup(bus_type, Vm0, facts):
    """Before the power flow: turn each shunt-FACTS PQ bus into a voltage-
    regulated (PV) bus at the device's Vref.  Returns modified copies."""
    bt = bus_type.copy()
    vm = Vm0.copy()
    for d in facts or []:
        if str(d.get('type', '')).upper() not in SHUNT:
            continue
        i = int(d['bus']) - 1
        if bt[i] == 1:                 # PQ -> PV (the device now holds V here)
            bt[i] = 2
        vm[i] = float(d.get('Vref', vm[i]) or 1.0)
    return bt, vm


def facts_operating_point(facts, V0, Qg, skip=()):
    """After a PV-regulated solve, record each shunt device's operating point
    (susceptance B / reactive current I / reactive output Q) on the device dict
    and flag saturation.  Returns a {bus_index: shunt_B} map of EQUIVALENT shunt
    susceptances for the saturated devices — a saturated SVC is exactly a fixed
    shunt B=Blim; a current-limited STATCOM is approximated by the shunt Ilim/V
    at the present voltage (refined on the re-solve).  Empty map => nothing
    saturated => the PV-regulated solution stands.  `skip` lists 0-based buses
    whose devices were already fixed at their limit in the re-solve: their
    operating point is final and must not be recomputed (the bus Qg no longer
    carries their output)."""
    shunts = {}
    for d in facts or []:
        k = str(d.get('type', '')).upper()
        if k not in SHUNT:
            continue
        i = int(d['bus']) - 1
        if i in skip:
            continue
        V = max(float(V0[i]), 1e-6)
        Q = float(Qg[i])               # reactive injected at the device bus
        if k == 'SVC':
            lo, hi = float(d.get('Bmin', -2.0)), float(d.get('Bmax', 2.0))
            B = Q / (V * V)
            Bs = min(max(B, lo), hi)
            d['_B'], d['_Q'] = Bs, Bs * V * V
            d['_sat'] = (B > hi + 1e-9) or (B < lo - 1e-9)
            if d['_sat']:
                shunts[i] = Bs
        else:  # STATCOM
            lo, hi = float(d.get('Imin', -2.0)), float(d.get('Imax', 2.0))
            I = Q / V
            Is = min(max(I, lo), hi)
            d['_I'], d['_Q'] = Is, Is * V
            d['_sat'] = (I > hi + 1e-9) or (I < lo - 1e-9)
            if d['_sat']:
                shunts[i] = Is / V
    return shunts


# ------------------------------------------------------------------- dynamics
def _shunt_aux(case, gb, d, base_names, lo, hi):
    """Common regulator + optional POD-controller aux for a shunt device."""
    V0 = float(case.V0[gb])
    pod = pod_cfg(d)
    npod = pod_nstate(pod)
    aux = dict(Vref=float(d.get('Vref', V0) or V0), Kr=float(d.get('Kr', 20.0)),
               Tr=max(float(d.get('Tr', 0.05)), 1e-3), Kaw=float(d.get('Kaw', 150.0)),
               lo=lo, hi=hi, droop=float(d.get('droop', 0.0)),
               pod=pod, npod=npod, names=base_names + pod_names(pod))
    return aux, npod


def _svc_init(case, gb, d):
    """SVC dynamic init: susceptance state B0 (+ any POD controller states=0)."""
    V0 = float(case.V0[gb])
    B0 = float(d.get('_B', case.Qg[gb] / max(V0 * V0, 1e-6)))
    aux, npod = _shunt_aux(case, gb, d, ['Bsvc'],
                           float(d.get('Bmin', -2.0)), float(d.get('Bmax', 2.0)))
    st0 = _reg_state0(B0, V0, d, aux)
    return np.concatenate([[st0], np.zeros(npod)]), np.zeros(0), aux


def _statcom_init(case, gb, d):
    """STATCOM dynamic init: reactive-current state I0 (+ any POD states=0)."""
    V0 = float(case.V0[gb])
    I0 = float(d.get('_I', case.Qg[gb] / max(V0, 1e-6)))
    aux, npod = _shunt_aux(case, gb, d, ['Istatcom'],
                           float(d.get('Imin', -2.0)), float(d.get('Imax', 2.0)))
    st0 = _reg_state0(I0, V0, d, aux)
    return np.concatenate([[st0], np.zeros(npod)]), np.zeros(0), aux


def _reg_state0(s0, V0, d, aux):
    """Equilibrium value of the integral-regulator STATE.  Unsaturated: the
    output itself (err=0, the PF held V at Vref).  Saturated: the wound-up
    anti-windup equilibrium st = sat + (Kr/(Tr*Kaw))*err, which makes
    rate = (Kr/Tr)*err + Kaw*(sat - st) = 0 EXACTLY while the OUTPUT stays
    clamped at the limit -- the device starts at its ceiling with no drift."""
    sat0 = min(max(s0, aux['lo']), aux['hi'])
    if d.get('_sat') and aux['Kaw'] > 0:
        err0 = aux['Vref'] - V0 - aux['droop'] * sat0
        return sat0 + (aux['Kr'] / (aux['Tr'] * aux['Kaw'])) * err0
    return sat0


def _reg_rate(state, V, aux, u):
    """Shared integral voltage-regulator with droop, an OUTPUT limiter, and
    back-calculation anti-windup.  Returns (state_rate, limited_output).  The
    output (B for an SVC, I for a STATCOM) is hard-clamped to [lo, hi]; the
    back-calc term Kaw*(clamped - state) drives the integrator state back to the
    limit whenever it saturates, so it never winds up or overshoots the rating.
    `u` may carry 'dVref' (a reference step) and 'dsig' (an injected signal —
    the hook for external / WAMS wide-area inputs)."""
    Vref = aux['Vref'] + u.get('dVref', 0.0)
    sat = min(max(state, aux['lo']), aux['hi'])          # output limiter
    err = Vref - V - aux['droop'] * sat + u.get('dsig', 0.0)
    rate = (aux['Kr'] / aux['Tr']) * err + aux['Kaw'] * (sat - state)
    return rate, sat


def _pod_apply(x, aux, u):
    """Run the POD block (if any) on this device's controller sub-states and the
    measured deviation signal `u['pod_sig']`; return (dxc, u2) where u2 carries
    the POD output folded into dVref for the regulator."""
    npod = aux.get('npod', 0)
    if not npod:
        return np.zeros(0), u
    dxc, Vpod = pod_output(x[1:1 + npod], u.get('pod_sig', 0.0), aux['pod'])
    u2 = dict(u); u2['dVref'] = u.get('dVref', 0.0) + Vpod
    return dxc, u2


def _svc_f(x, z, V, TH, aux, prm, u):
    dxc, u2 = _pod_apply(x, aux, u)
    dB, B = _reg_rate(x[0], V, aux, u2)
    return np.concatenate([[dB], dxc]), 0.0, B * V * V, np.zeros(0)  # Q = B*|V|^2


def _statcom_f(x, z, V, TH, aux, prm, u):
    dxc, u2 = _pod_apply(x, aux, u)
    dI, I = _reg_rate(x[0], V, aux, u2)
    return np.concatenate([[dI], dxc]), 0.0, I * V, np.zeros(0)      # Q = |V|*I


# tag -> (n_states, n_alg, init_fn, f_fn, state_names) — same shape as units.REGISTRY
REGISTRY = {
    'SVC':     (1, 0, _svc_init,     _svc_f,     ['Bsvc']),
    'STATCOM': (1, 0, _statcom_init, _statcom_f, ['Istatcom']),
}
