"""Unit-model regression tests: every unit type must (a) initialise to a
machine-precision equilibrium (SOC drift excluded), (b) be small-signal
stable on the IEEE 9-bus, and (c) show its signature physics.
Run:  python3 tests/test_units.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import cases
from system import System
from linearize import linearize, modes, dominant_mode
from simulate import simulate, cloud_profile, gust_profile

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("  PASS" if cond else "  FAIL"), name, detail)


c9 = cases.ieee9()
ALL = ['GFM', 'GFL', 'PV-GFL', 'PV-GFM', 'BESS-GFM', 'BESS-GFL',
       'WT4-GFL', 'WT4-GFM', 'WT3', 'WT1', 'WT2']

print("[1] equilibrium + small-signal stability, each unit at bus 3")
for tag in ALL:
    s = System(c9, ['SG', 'SG', tag])
    res = s.equilibrium_residual()
    R = linearize(s)
    nun = int(np.sum(R['ev'].real > 1e-6))
    check(f"{tag:9s}", res < 1e-9 and nun == 0,
          f"res={res:.0e} unstable={nun}")

print("[2] mixed renewable system (BESS-GFM + WT4 + PV)")
s = System(c9, ['BESS-GFM', 'WT4-GFL', 'PV-GFL'])
check("mixed equilibrium", s.equilibrium_residual() < 1e-9)
R = linearize(s)
check("mixed stable", int(np.sum(R['ev'].real > 1e-6)) == 0)

print("[3] signature physics")
# PV: DC-link mode exists and is damped
s = System(c9, ['SG', 'SG', 'PV-GFL'])
R = linearize(s)
nm = s.state_names()
dm = dominant_mode(R, [j for j, x in enumerate(nm) if x in ('Vdc3', 'xdc3')],
                   fband=(0.05, 20))
check("PV DC-link mode damped", dm is not None and dm['zeta'] > 20,
      f"f={dm['f']:.2f} Hz zeta={dm['zeta']:.0f}%")
# WT4: lightly-damped shaft torsional mode near 1-2 Hz
s = System(c9, ['SG', 'SG', 'WT4-GFL'])
R = linearize(s)
nm = s.state_names()
dm = dominant_mode(R, [j for j, x in enumerate(nm) if x in ('wt3', 'wg3', 'ttw3')],
                   fband=(0.5, 4))
check("WT4 torsional mode", dm is not None and 0.8 < dm['f'] < 2.5,
      f"f={dm['f']:.2f} Hz zeta={dm['zeta']:.1f}%")
# WT1: machine absorbs reactive power (cap compensates), slip negative
s = System(c9, ['SG', 'SG', 'WT1'])
u = s.units[2]['aux']
slip0 = s.x0[s.units[2]['xsl']][2]
check("WT1 generating slip < 0", slip0 < 0, f"s0={slip0:.4f}")
check("WT1 absorbs Q (Bcap > 0)", u['Bcap'] > 0, f"Bcap={u['Bcap']:.3f}")
# WT3: subsynchronous at below-rated wind (slip = 1 - vw0 > 0)
s = System(c9, ['SG', 'SG', 'WT3'])
slip0 = s.x0[s.units[2]['xsl']][2]
check("WT3 subsync slip ~ 0.1", abs(slip0 - 0.1) < 1e-6, f"s0={slip0:.4f}")

print("[4] source-side disturbances (short runs)")
s = System(c9, ['SG', 'SG', 'PV-GFL'])
T, X, Z = simulate(s, tsim=11.0, dt=2e-3,
                   G_prof={2: cloud_profile(1.0, depth=0.5, tdown=1.5, tlow=2, tup=1.5)})
fc = s.coi_freq(X)
check("cloud dips frequency", 59.3 < fc.min() < 59.95, f"min={fc.min():.3f} Hz")
check("cloud recovers", abs(fc[-1] - 60) < 0.05, f"end={fc[-1]:.3f} Hz")
s = System(c9, ['SG', 'SG', 'WT3'])
T, X, Z = simulate(s, tsim=6.0, dt=2e-3,
                   vw_prof={2: gust_profile(1.0, A=0.12, base=0.9)})
wt = s.unit_state(X, 2, 'wt')
check("gust accelerates turbine", wt.max() > 0.905, f"wt_max={wt.max():.3f}")

print("[5] BESS fast-frequency response improves the nadir")
s = System(c9, ['SG', 'GFL', 'GFL'])
T, X, Z = simulate(s, tsim=8.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
nad0 = s.coi_freq(X)[T >= 1.0].min()
s = System(c9, ['SG', 'BESS-GFL', 'GFL'])
T, X, Z = simulate(s, tsim=8.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
nad1 = s.coi_freq(X)[T >= 1.0].min()
check("FFR raises nadir", nad1 > nad0 + 0.05, f"{nad0:.3f} -> {nad1:.3f} Hz")

print("\nALL PASS" if ok else "\nFAILURES — see above")
sys.exit(0 if ok else 1)
