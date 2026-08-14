"""Design-tool regression test: POD on a Kundur GFM battery must reach its
damping target on the exact closed loop without destabilising other modes.
Run:  python3 tests/test_design.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cases
from system import System
from linearize import linearize
import design as D

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("  PASS" if cond else "  FAIL"), name, detail)


ck = cases.kundur2a()
BESS_K = dict(cases.GFM_K, Eh=1.0, SOC0=0.6)
s = System(ck, ['SG', 'BESS-GFM', 'SG', 'SG'], [None, BESS_K, None, None])
R = linearize(s)
ia = sorted([l for l in R['ev'] if 0.3 < l.imag / 2 / np.pi < 0.9],
            key=lambda l: -l.real / abs(l))
lam0 = ia[0]
z0 = -lam0.real / abs(lam0) * 100
check("open-loop inter-area found", 0.55 < lam0.imag / 2 / np.pi < 0.70,
      f"{lam0.imag/2/np.pi:.3f} Hz {z0:.2f}%")

B = D.input_matrix(R, units=[1])
C = D.output_matrix(R, D.speed_output(s, 1))
res, lam, i = D.residues(R, B, C, lam0)
check("residue nonzero", abs(res[0]) > 1e-6)

pod = D.pod_design(res[0], lam, zeta_target=0.15)
ev = np.linalg.eig(D.closed_loop(R, B[:, 0], C, pod))[0]
z1, lam1 = D.damping_of(ev, lam)
check("target damping reached", abs(z1 - 15.0) < 2.0, f"achieved {z1:.2f}%")
check("closed loop stable", int(np.sum(ev.real > 1e-6)) == 0)
worst = min(-l.real / abs(l) * 100 for l in ev if l.imag > 2 * np.pi * 0.05)
check("no collateral damage", worst > 5.0, f"worst osc {worst:.1f}%")

print("\nALL PASS" if ok else "\nFAILURES — see above")
sys.exit(0 if ok else 1)
