"""
linearize.py — small-signal state matrix and modal analysis.

The DAE  dx/dt = f(x,z), 0 = g(x,z)  is linearised about the operating
point by eliminating the algebraic variables [Kundur ch. 12; Sauer & Pai
ch. 7; PSDAT (OAJPE 2020)]:

    A = fx - fz * gz^-1 * gx

The Jacobians are exact numerical derivatives (finite differences with
step 1e-7, ~7-digit accuracy); the companion MATLAB script
PSDAT_Symbolic.m obtains the SAME matrix by exact symbolic
differentiation on the smaller systems.
"""
import numpy as np


def num_jac(fun, v0, eps=1e-7):
    base = fun(v0)
    J = np.empty((len(base), len(v0)))
    v = np.array(v0, dtype=float)           # perturb in place: one vector,
    for i in range(len(v)):                 # not one copy per column
        vi = v[i]
        v[i] = vi + eps
        J[:, i] = fun(v)
        v[i] = vi
    J -= base[:, None]
    J /= eps
    return J


def dae_jacobians(sys, x0, z0, eps=1e-7):
    """All four Jacobian blocks in ONE sweep per variable: each perturbed
    point is evaluated once and yields its fx AND gx (fz AND gz) column
    together — half the DAE evaluations of computing the blocks separately.
    Same finite-difference mathematics, same numbers."""
    f0, g0 = sys.dae(x0, z0)
    nf, ng = len(f0), len(g0)
    fx = np.empty((nf, len(x0)))
    gx = np.empty((ng, len(x0)))
    xp = np.array(x0, dtype=float)
    for i in range(len(x0)):
        xi = xp[i]
        xp[i] = xi + eps
        fi, gi = sys.dae(xp, z0)
        fx[:, i] = fi
        gx[:, i] = gi
        xp[i] = xi
    fx -= f0[:, None]; fx /= eps
    gx -= g0[:, None]; gx /= eps
    fz = np.empty((nf, len(z0)))
    gz = np.empty((ng, len(z0)))
    zp = np.array(z0, dtype=float)
    for i in range(len(z0)):
        zi = zp[i]
        zp[i] = zi + eps
        fi, gi = sys.dae(x0, zp)
        fz[:, i] = fi
        gz[:, i] = gi
        zp[i] = zi
    fz -= f0[:, None]; fz /= eps
    gz -= g0[:, None]; gz /= eps
    return f0, g0, fx, fz, gx, gz


def linearize(sys, verbose=False):
    """Returns dict with A, eigenvalues ev, right eigenvectors evec, and the
    four Jacobian blocks (reused by design.py for B and C matrices)."""
    x0, z0 = sys.x0, sys.z0
    f0, g0, fx, fz, gx, gz = dae_jacobians(sys, x0, z0)
    res = max(np.max(np.abs(f0)), np.max(np.abs(g0)))
    if verbose:
        print(f"  operating-point residual max|f;g| = {res:.2e}")
    A = fx - fz @ np.linalg.solve(gz, gx)
    ev, evec = np.linalg.eig(A)
    return dict(A=A, ev=ev, evec=evec, fx=fx, fz=fz, gx=gx, gz=gz,
                res=res, sys=sys)


def modes(ev, fmin=0.05, fmax=np.inf):
    """Oscillatory modes as sorted (freq_Hz, damping_%, lambda)."""
    out = []
    for lam in ev:
        fr = lam.imag / (2 * np.pi)
        if fmin <= fr <= fmax:
            out.append((fr, -lam.real / abs(lam) * 100, lam))
    return sorted(out)


def participation(R, k=None, lam=None):
    """Participation factors [Kundur sec. 12.2.5]: p_ij = |v_ij * w_ij|,
    normalised per mode.  Select the mode by index k or nearest to lam."""
    ev, VV = R['ev'], R['evec']
    W = np.linalg.inv(VV)
    if k is None:
        k = int(np.argmin(np.abs(ev - lam)))
    p = np.abs(VV[:, k] * W[k, :])
    return p / p.max(), ev[k]


def dominant_mode(R, states, fband=(0.05, 6.0)):
    """Least-damped oscillatory mode whose participation is dominated by the
    given state columns (used to identify PLL / power-sync / torsional /
    DC-link modes)."""
    ev, VV = R['ev'], R['evec']
    W = np.linalg.inv(VV)
    best = None
    for k in range(len(ev)):
        fr = ev[k].imag / (2 * np.pi)
        if not (fband[0] < fr < fband[1]):
            continue
        p = np.abs(VV[:, k] * W[k, :])
        if p.sum() == 0:
            continue
        score = p[states].sum() / p.sum()
        if best is None or score > best[0]:
            best = (score, k)
    if best is None:
        return None
    p, lam = participation(R, k=best[1])
    return dict(k=best[1], lam=lam, p=p, score=best[0],
                f=lam.imag / 2 / np.pi, zeta=-lam.real / abs(lam) * 100)


def print_modes(R, fmax=6.0, label=""):
    ev = R['ev']
    nunst = int(np.sum(ev.real > 1e-6))
    print(f"{label}  ({R['A'].shape[0]} states, {nunst} unstable)")
    print("   %9s %11s   %s" % ("freq(Hz)", "damping(%)", "eigenvalue"))
    for fr, z, lam in modes(ev, fmax=fmax):
        print("   %9.4f %11.2f   %9.4f%+9.4fj" % (fr, z, lam.real, lam.imag))
