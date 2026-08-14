"""
design.py — small-signal control design: B/C matrices, residues, and
residue-based damping-controller (POD/PSS) tuning.

Revives Program 3 of the original PSDAT for the converter-dominated grid.
Theory: [Kundur ch. 12; Pal & Chaudhuri, Robust Control in Power Systems,
ch. 5-6; Rogers, Power System Oscillations].

Workflow (all exact, from the linearized DAE):
  1. B matrix  — input = the power set-point of a chosen unit (where a
     damping signal can be injected: GFM/GFL/BESS P*, SG governor).
  2. C matrix  — output = a measurable signal (unit speed, COI frequency,
     speed difference between two areas).
  3. residue   R_i = C v_i w_i^T B  of mode i for every candidate unit:
     |R| ranks the best location; angle(R) gives the phase compensation.
  4. lead-lag POD  K * (s Tw/(1+s Tw)) * ((1+s T1)/(1+s T2))^nc  tuned so
     the compensated residue points into the left half plane; the gain is
     set by the first-order mode sensitivity  d(lambda) = -R * K * H(lambda)
     and verified on the exact closed-loop eigenvalues.
"""
import numpy as np
from linearize import num_jac, linearize


# ---------------------------------------------------------------- B and C
def input_matrix(R, units=None):
    """B for inputs = dP set-points of the chosen units (default: all).
    Columns follow the `units` list."""
    sys = R['sys']
    units = list(range(len(sys.units))) if units is None else units
    x0, z0 = sys.x0, sys.z0
    f0, g0 = sys.dae(x0, z0)
    cols_f = []
    cols_g = []
    eps = 1e-7
    for k in units:
        f1, g1 = sys.dae(x0, z0, uin={k: {'dP': eps}})
        cols_f.append((f1 - f0) / eps)
        cols_g.append((g1 - g0) / eps)
    fu = np.column_stack(cols_f)
    gu = np.column_stack(cols_g)
    B = fu - R['fz'] @ np.linalg.solve(R['gz'], gu)
    return B


def output_matrix(R, h):
    """C for output y = h(x, z) (returns a 1 x NX row).  h must be smooth."""
    sys = R['sys']
    x0, z0 = sys.x0, sys.z0
    hx = num_jac(lambda x: np.atleast_1d(h(x, z0)), x0)
    hz = num_jac(lambda z: np.atleast_1d(h(x0, z)), z0)
    return hx - hz @ np.linalg.solve(R['gz'], R['gx'])


def speed_output(sys, k):
    """y = speed deviation (pu) of unit k — the classic damping-loop input."""
    un = sys.units[k]
    tag = un['tag']
    ws = sys.case.ws
    if tag == 'SG':
        col = un['xsl'].start + 5
    elif tag == 'GFM' or tag.endswith('-GFM'):
        col = un['xsl'].start + 1
    else:
        raise ValueError('speed output needs an SG or GFM-type unit')
    return lambda x, z: (x[col] - ws) / ws


def diff_speed_output(sys, ka, kb):
    """y = speed(ka) - speed(kb) in pu — inter-area signal."""
    fa = speed_output(sys, ka)
    fb = speed_output(sys, kb)
    return lambda x, z: fa(x, z) - fb(x, z)


# ---------------------------------------------------------------- residues
def residues(R, B, C, lam_target):
    """Residue of the mode nearest lam_target for every input column of B:
    R_i = (C v_i)(w_i^T b_j).  Returns list of complex residues."""
    ev, VV = R['ev'], R['evec']
    W = np.linalg.inv(VV)
    i = int(np.argmin(np.abs(ev - lam_target)))
    lam = ev[i]
    Cv = (C @ VV[:, i]).item()
    out = [Cv * (W[i, :] @ B[:, j]) for j in range(B.shape[1])]
    return np.array(out), lam, i


# ---------------------------------------------------------------- POD design
def pod_design(res, lam, zeta_target=0.15, Tw=10.0, nc_max=3):
    """Residue-angle phase-compensation design [Pal & Chaudhuri sec. 6.3]:
    the mode moves along -angle(R*H(lam)); choose lead-lag stages so the
    compensated residue points at 180 deg (straight left), then set the
    gain from the first-order sensitivity to reach zeta_target.
    Returns dict(K, Tw, T1, T2, nc)."""
    w = abs(lam.imag)
    # required compensation: make angle(R * H) = 180 deg at the mode
    def H_wash(s):
        return (s * Tw) / (1 + s * Tw)
    phi_needed = np.pi - np.angle(res * H_wash(lam))
    phi_needed = (phi_needed + np.pi) % (2 * np.pi) - np.pi
    # if more than 90 deg is needed, flip the loop sign instead and
    # compensate only the remainder (keeps the lead-lags mild)
    if abs(phi_needed) > np.pi / 2:
        phi_needed = phi_needed - np.sign(phi_needed) * np.pi
    nc = min(nc_max, max(1, int(np.ceil(abs(phi_needed) / (np.deg2rad(65))))))
    phi_c = phi_needed / nc
    # lead-lag with maximum phase phi_c at frequency w:
    a = (1 + np.sin(phi_c)) / (1 - np.sin(phi_c))
    T2 = 1 / (w * np.sqrt(a))
    T1 = a * T2

    def H(s):
        return H_wash(s) * ((1 + s * T1) / (1 + s * T2)) ** nc
    # gain from the first-order mode sensitivity with the u = +F(s)y loop
    # convention of closed_loop():  dlam = K * res * H(lam)
    dlam_needed = (-zeta_target * abs(lam) - lam.real)   # move Re(lam) left
    sens = (res * H(lam)).real
    K = dlam_needed / sens if abs(sens) > 1e-12 else 0.0
    return dict(K=float(K), Tw=Tw, T1=float(T1), T2=float(T2), nc=int(nc),
                H=H, phi_deg=float(np.rad2deg(phi_needed)))


def pod_ss(pod):
    """State-space (Ac, Bc, Cc, Dc) of  K * washout * leadlag^nc  (SISO)."""
    K, Tw, T1, T2, nc = pod['K'], pod['Tw'], pod['T1'], pod['T2'], pod['nc']
    # washout: x' = -x/Tw + u ; y = -x/Tw + u   (y = sTw/(1+sTw) u)
    A = np.array([[-1 / Tw]])
    B = np.array([[1.0]])
    C = np.array([[-1 / Tw]])
    D = np.array([[1.0]])
    for _ in range(nc):
        # lead-lag (1+sT1)/(1+sT2):  x' = (u - x)/T2 ; y = (1-T1/T2)x + (T1/T2)u
        Al = np.array([[-1 / T2]])
        Bl = np.array([[1 / T2]])
        Cl = np.array([[1 - T1 / T2]])
        Dl = np.array([[T1 / T2]])
        A = np.block([[A, np.zeros((A.shape[0], 1))], [Bl @ C, Al]])
        B = np.vstack([B, Bl @ D])
        C = np.hstack([Dl @ C, Cl])
        D = Dl @ D
    return A, B, K * C, K * D


def closed_loop(R, B, C, pod, sign=+1.0):
    """Exact closed-loop state matrix with u = sign * POD(s) * y appended."""
    Ac, Bc, Cc, Dc = pod_ss(pod)
    A = R['A']
    b = B.reshape(-1, 1)
    c = C.reshape(1, -1)
    Acl = np.block([[A + sign * Dc.item() * b @ c, sign * b @ Cc],
                    [Bc @ c, Ac]])
    return Acl


def damping_of(ev, lam_ref):
    lam = ev[np.argmin(np.abs(ev - lam_ref))]
    return -lam.real / abs(lam) * 100, lam


# ---------------------------------------------------------------- sweeps
def param_sweep(case, mix, prm_key, values, unit_k, base_prm=None,
                mode_band=(0.2, 2.0)):
    """Eigenvalue sweep of one unit parameter (e.g. GFM Hv, Dp, PLL Kp):
    returns list of (value, least-damped mode in band)."""
    from system import System
    out = []
    for v in values:
        prm = [dict(base_prm[k]) if base_prm and base_prm[k] else {}
               for k in range(len(mix))]
        prm[unit_k][prm_key] = v
        R = linearize(System(case, mix, prm))
        cand = [(z, f, lam) for f, z, lam in
                [(l.imag / 2 / np.pi, -l.real / abs(l) * 100, l)
                 for l in R['ev'] if mode_band[0] < l.imag / 2 / np.pi < mode_band[1]]]
        out.append((v, min(cand) if cand else None))
    return out
