"""Parity tests: PSDAT must reproduce the validated PSDAT-IBR reference
numbers (and the published PSDAT/OAJPE-2020 base modes) exactly.
Run:  python3 tests/test_parity.py   (from the v2/python folder)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cases
from system import System
from linearize import linearize, modes
from simulate import simulate

ok = True


def check(name, got, want, tol):
    global ok
    good = abs(got - want) <= tol
    ok &= good
    print(("  PASS" if good else "  FAIL"), f"{name}: {got:.4f} (want {want:.4f})")


print("[1] IEEE 9-bus all-SG published modes (OAJPE 2020)")
c9 = cases.ieee9()
R = linearize(System(c9, ['SG', 'SG', 'SG']))
lam = R['ev']
ia = lam[np.argmin(np.abs(lam - (-0.6512 + 9.0749j)))]
lo = lam[np.argmin(np.abs(lam - (-1.1563 + 14.9046j)))]
check("inter-area re", ia.real, -0.65117, 1e-3)
check("inter-area im", ia.imag, 9.0749, 1e-3)
check("local re", lo.real, -1.15629, 1e-3)
check("local im", lo.imag, 14.9046, 1e-3)

print("[2] 9-bus mixes (reference implementation values)")
R = linearize(System(c9, ['SG', 'GFM', 'GFM']))
gm = sorted([(z, f) for f, z, l in modes(R['ev']) if 1.3 < f < 1.6])[0]
check("78% GFM mode damping", gm[0], 10.23, 0.1)
R = linearize(System(c9, ['SG', 'GFL', 'GFL']))
check("78% GFL unstable count", float(np.sum(R['ev'].real > 1e-6)), 0.0, 0.5)

print("[3] Kundur two-area (reference values)")
ck = cases.kundur2a()


def inter(ev):
    return sorted([(-l.real / abs(l) * 100, l.imag / 2 / np.pi)
                   for l in ev if 0.3 < l.imag / 2 / np.pi < 0.9])[0]


R = linearize(System(ck, ['SG'] * 4))
z, f = inter(R['ev'])
check("SG inter-area f", f, 0.631, 0.005)
check("SG inter-area zeta", z, 3.53, 0.1)
R = linearize(System(ck, ['SG', 'GFM', 'SG', 'GFM'],
                     [None, cases.GFM_K, None, cases.GFM_K]))
z, f = inter(R['ev'])
check("GFM inter-area zeta", z, 10.22, 0.1)
R = linearize(System(ck, ['SG', 'GFL', 'SG', 'GFL'],
                     [None, cases.GFL_K, None, cases.GFL_K]))
check("GFL unstable count", float(np.sum(R['ev'].real > 1e-6)), 3.0, 0.5)

print("[4] 68-bus NETS-NYPS (reference values)")
c68 = cases.ne68()
R = linearize(System(c68, ['SG'] * 16))
o = sorted([(-l.real / abs(l) * 100, l.imag / 2 / np.pi)
            for l in R['ev'] if 0.1 < l.imag / 2 / np.pi < 1.4])
check("critical mode f", o[0][1], 1.270, 0.005)
check("critical mode zeta", o[0][0], 6.98, 0.1)
check("state count", float(R['A'].shape[0]), 176.0, 0.1)

print("[5] 9-bus time domain: sustained 15 MW load step")
s = System(c9, ['SG', 'SG', 'SG'])
T, X, Z = simulate(s, tsim=15.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
fc = s.coi_freq(X)
check("all-SG nadir (Hz)", fc[T >= 1.0].min(), 59.869, 0.002)

print("\nALL PASS" if ok else "\nFAILURES — see above")
sys.exit(0 if ok else 1)
