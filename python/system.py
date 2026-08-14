"""
system.py — assemble the multi-unit DAE  dx/dt = f(x,z,u), 0 = g(x,z,u).

x stacks the differential states of all units (in gen-bus order);
z stacks each unit's own algebraic variables (stator currents, if any)
followed by the bus voltage magnitudes V(1:n) and angles TH(1:n).
g stacks the unit algebraic residuals, then the polar power-balance
equations of every bus [Sauer & Pai ch. 7]:

    Pinj_i - PL_i - Re{ V_i * conj( (Y V)_i ) } = 0
    Qinj_i - QL_i - Im{ V_i * conj( (Y V)_i ) } = 0
"""
import numpy as np
import units as U

_EMPTY_U = {}          # shared read-only default for "no unit inputs"


class System:
    """A case + a unit mix.  `unit_types` is a list of m tags (one per
    machine position, in `case.gen_bus` order); `unit_prm` an optional list
    of per-unit parameter overrides (dicts or None)."""

    def __init__(self, case, unit_types, unit_prm=None):
        assert len(unit_types) == case.m, "one unit tag per machine position"
        self.case = case
        self.types = list(unit_types)
        self.prm = list(unit_prm) if unit_prm else [None] * case.m
        self.units = []
        pos = 0
        zpos = 0
        x0 = []
        z0 = []
        for k, tag in enumerate(self.types):
            ns, na, init_fn, f_fn, names = U.REGISTRY[tag]
            gb = int(case.gen_bus[k]) - 1          # terminal bus (0-based)
            st, alg, aux = init_fn(case, gb, self.prm[k])
            self.units.append(dict(tag=tag, bus=gb, xsl=slice(pos, pos + ns),
                                   zsl=slice(zpos, zpos + na), f=f_fn,
                                   aux=aux, names=names))
            x0.append(st)
            z0.append(alg)
            pos += ns
            zpos += na
        # ---- FACTS devices: each shunt device (SVC/STATCOM) adds a small state
        # block and injects reactive power at its bus.  Modelled as extra "units"
        # so power balance, small-signal and time-domain handle them with no
        # special-casing (their f returns Pk=0, Qk = the device reactive). ----
        import facts as FA
        self._FA = FA
        self.nfacts = 0
        for d in (getattr(case, 'facts', None) or []):
            tag = str(d.get('type', '')).upper()
            if tag not in FA.REGISTRY:
                continue
            _ns, _na, init_fn, f_fn, names = FA.REGISTRY[tag]
            gb = int(d['bus']) - 1
            st, alg, aux = init_fn(case, gb, d)
            ns, na = len(st), len(alg)             # actual counts (POD adds states)
            self.units.append(dict(tag=tag, bus=gb, xsl=slice(pos, pos + ns),
                                   zsl=slice(zpos, zpos + na), f=f_fn,
                                   aux=aux, names=aux.get('names', names), facts=True,
                                   podcfg=aux.get('pod')))
            x0.append(st)
            z0.append(alg)
            pos += ns
            zpos += na
            self.prm.append(None)          # FACTS carry their config in aux, not prm
            self.nfacts += 1
        # ---- dynamic series FACTS (POD-modulated TCSC/SSSC): a first-order
        # compensation state k(t) (+ POD states).  The network coupling is a
        # state-dependent admittance stamp ΔY(k) applied in dae() — NOT a bus
        # injection — so k=k0 reproduces the static operating point exactly.
        self.sfacts = []
        for d in (getattr(case, 'facts', None) or []):
            if not FA.series_dynamic(d):
                continue
            row = d.get('_br', -1)
            if row is None or row < 0:
                continue
            k0 = float(d.get('_kc', min(max(float(d.get('kcomp', 0.4)),
                       float(d.get('kmin', -0.2))), float(d.get('kmax', 0.7)))))
            xline = float(d.get('_xline', case.branch[row, 3]))
            r = float(case.branch[row, 2])
            f = int(case.branch[row, 0]) - 1
            t = int(case.branch[row, 1]) - 1
            a = 1.0
            if case.tap is not None and case.tap[row] != 0:
                a = case.tap[row]
            pod = FA.pod_cfg(d)
            npod = FA.pod_nstate(pod)
            names = ['kcomp'] + FA.pod_names(pod)
            st = np.concatenate([[k0], np.zeros(npod)])
            aux = dict(f=f, t=t, r=r, xline=xline, a=a, k0=k0,
                       kmin=float(d.get('kmin', -0.2)), kmax=float(d.get('kmax', 0.7)),
                       Tc=max(float(d.get('Tc', 0.02)), 1e-3), pod=pod, npod=npod)
            self.sfacts.append(dict(bus=f, xsl=slice(pos, pos + len(st)),
                                    aux=aux, names=names, podcfg=pod))
            x0.append(st)
            pos += len(st)
        self.NX = pos
        self.NU = zpos                              # unit algebraic vars
        n = case.n
        self.Vsl = slice(zpos, zpos + n)
        self.THsl = slice(zpos + n, zpos + 2 * n)
        self.NZ = zpos + 2 * n
        self.x0 = np.concatenate(x0) if x0 else np.zeros(0)
        self.z0 = np.concatenate([np.concatenate(z0) if z0 else np.zeros(0),
                                  case.V0, case.TH0])
        # ---- POD/WADC supplementary controllers: measure each enabled device's
        # feedback signal at the operating point, so the loop acts on a zero-mean
        # deviation (s - s0) and every controller state is 0 at equilibrium. ----
        self._build_pod_context()
        for un in self.units:
            pc = un.get('podcfg')
            if pc and pc.get('on'):
                pc['s0'] = self._pod_measure(un, self.x0, self.z0)
        for sf in self.sfacts:
            pc = sf.get('podcfg')
            if pc and pc.get('on'):
                pc['s0'] = self._pod_measure(sf, self.x0, self.z0)

    # ------------------------------------------------------------------ DAE
    def dae(self, x, z, uin=None, dPload=None, Yextra=None):
        """Residuals (f, g).  uin: {unit_index: u-dict} unit inputs;
        dPload: {bus0: dP} network-side load changes; Yextra: admittance
        perturbation (fault shunt / line outage)."""
        case = self.case
        n = case.n
        V = z[self.Vsl]
        TH = z[self.THsl]
        Yb = case.Ybus if Yextra is None else case.Ybus + Yextra
        # dynamic series FACTS: stamp the compensation deviation ΔY(k) onto Ybus
        # (state-dependent admittance) BEFORE the network power — reproduces the
        # base-compensated Ybus at k=k0 (ΔY=0), and modulates it as k moves.
        if self.sfacts:
            if Yextra is None:
                Yb = Yb.copy()                 # never mutate the shared case.Ybus
            for sf in self.sfacts:
                a = sf['aux']
                dy = self._FA.series_dy(a['r'], a['xline'], a['a'],
                                        x[sf['xsl']][0], a['k0'])
                fb, tb, tp = a['f'], a['t'], a['a']
                Yb[fb, fb] += dy / (tp * tp)
                Yb[tb, tb] += dy
                Yb[fb, tb] -= dy / np.conj(tp)
                Yb[tb, fb] -= dy / tp
        Vc = V * np.exp(1j * TH)
        Snet = Vc * np.conj(Yb @ Vc)
        # Voltage-dependent (ZIP-exponent) load model [Sauer & Pai; Kundur]:
        #   PL = Pd*(V/V0)^a,  QL = Qd*(V/V0)^b,  a,b in {0,1,2}
        #   (constant power / current / impedance).  Default a=b=0 -> constant
        #   power, so the operating point and every published result are
        #   unchanged; a,b are exact multipliers of 1 at V=V0 (equilibrium).
        la = getattr(case, 'load_a', None)
        lb = getattr(case, 'load_b', None)
        if la is not None and (np.any(la) or np.any(lb)):
            vr = V / case.V0
            PL = case.Pd * vr ** la
            QL = case.Qd * vr ** lb
        else:
            PL = case.Pd.copy() if dPload else case.Pd
            QL = case.Qd
        if dPload:                          # network-side load change (pulse)
            for b_, dp in dPload.items():
                PL[b_] += dp
        f = np.empty(self.NX)               # write unit blocks straight into
        gu = np.empty(self.NU)              # the output arrays (no re-concat)
        Pinj = np.zeros(n)
        Qinj = np.zeros(n)
        prm = self.prm
        for k, un in enumerate(self.units):
            u = uin.get(k, _EMPTY_U) if uin else _EMPTY_U
            pc = un.get('podcfg')
            if pc is not None and pc.get('on'):        # feed the measured deviation
                s_dev = self._pod_measure(un, x, z) - pc.get('s0', 0.0)
                u = {'pod_sig': s_dev} if u is _EMPTY_U else {**u, 'pod_sig': s_dev}
            fk, Pk, Qk, gk = un['f'](x[un['xsl']], z[un['zsl']],
                                     V[un['bus']], TH[un['bus']],
                                     un['aux'], prm[k], u)
            f[un['xsl']] = fk
            gu[un['zsl']] = gk
            b = un['bus']
            Pinj[b] += Pk
            Qinj[b] += Qk
        # dynamic series FACTS state derivatives: k tracks its (POD-modulated,
        # limited) reference through a first-order lag; the network coupling was
        # already applied as the ΔY stamp above.
        for sf in self.sfacts:
            a = sf['aux']
            xs = x[sf['xsl']]
            Vpod = 0.0
            dxc = np.zeros(0)
            pc = sf['podcfg']
            if pc is not None and pc.get('on') and a['npod']:
                s_dev = self._pod_measure(sf, x, z) - pc.get('s0', 0.0)
                dxc, Vpod = self._FA.pod_output(xs[1:1 + a['npod']], s_dev, pc)
            k_cmd = min(max(a['k0'] + Vpod, a['kmin']), a['kmax'])
            f[sf['xsl']] = np.concatenate([[(k_cmd - xs[0]) / a['Tc']], dxc])
        g = np.concatenate([gu, Pinj - PL - Snet.real, Qinj - QL - Snet.imag])
        return f, g

    # --------------------------------------------------- POD signal measurement
    def _build_pod_context(self):
        """Look-ups used to measure remote POD feedback signals: bus -> rotor-
        speed state column (for 'wgen'), and an unordered bus-pair -> branch row
        (for line power / current)."""
        self._spdcol = {}
        for k, col, M, kind in self.speed_states():
            self._spdcol[self.units[k]['bus']] = col       # 0-based bus -> speed col
        self._brow = {}
        br = self.case.branch
        for r in range(br.shape[0]):
            a, b = int(br[r, 0]) - 1, int(br[r, 1]) - 1
            self._brow.setdefault((min(a, b), max(a, b)), r)

    def _line_quantity(self, f, t, V, TH, want):
        """Line-quantity feedback at the branch's stored 'from' end: active power
        ('Pline'), reactive power ('Qline') or current magnitude ('Iline') on the
        branch between buses f,t (1-based)."""
        r = self._brow.get((min(f - 1, t - 1), max(f - 1, t - 1)))
        if r is None:
            return 0.0
        br = self.case.branch[r]
        fa, ta = int(br[0]) - 1, int(br[1]) - 1
        y = 1.0 / (br[2] + 1j * br[3]); bc = 1j * br[4] / 2.0
        a = 1.0
        if self.case.tap is not None and self.case.tap[r] != 0:
            a = self.case.tap[r]
        Vf = V[fa] * np.exp(1j * TH[fa]); Vt = V[ta] * np.exp(1j * TH[ta])
        If = (y + bc) / (a * a) * Vf - y / np.conj(a) * Vt      # current leaving 'from'
        if want == 'Iline':
            return float(abs(If))
        S = Vf * np.conj(If)                                    # complex power leaving 'from'
        return float(S.imag) if want == 'Qline' else float(S.real)

    def _pod_measure(self, un, x, z):
        """The device's raw feedback signal — local or remote (WAMS)."""
        pc = un['podcfg']; n = self.case.n
        V = z[self.Vsl]; TH = z[self.THsl]
        sig = pc.get('sig', 'Vbus')
        try:
            if sig == 'Vbus':
                i = int(pc.get('rbus', 0)) or (un['bus'] + 1)
                if 1 <= i <= n:
                    return float(V[i - 1])
            elif sig == 'angle':
                i = int(pc.get('rbus', 0)) or (un['bus'] + 1)
                if 1 <= i <= n:
                    return float(TH[i - 1])
            elif sig == 'adiff':
                i, j = int(pc.get('i', 0)), int(pc.get('j', 0))
                if 1 <= i <= n and 1 <= j <= n:
                    return float(TH[i - 1] - TH[j - 1])
            elif sig == 'wgen':
                i = int(pc.get('rbus', 0)) or (un['bus'] + 1)
                col = self._spdcol.get(i - 1)
                if col is not None:
                    return float(x[col])
            elif sig in ('Pline', 'Qline', 'Iline'):
                f, t = int(pc.get('f', 0)), int(pc.get('t', 0))
                if 1 <= f <= n and 1 <= t <= n and f != t:
                    return self._line_quantity(f, t, V, TH, sig)
        except Exception:
            pass
        return float(V[un['bus']])            # robust fallback: local bus |V|

    # ------------------------------------------------------------ utilities
    def equilibrium_residual(self):
        """Max |f;g| at the initial point, EXCLUDING known drift states
        (battery SOC is a pure integrator of power: it legitimately drifts
        while the unit dis/charges, so its derivative is not zero at the
        quasi-static operating point)."""
        f0, g0 = self.dae(self.x0, self.z0)
        names = self.state_names()
        keep = np.array([not names[j].startswith('SOC') for j in range(self.NX)])
        return max(np.max(np.abs(f0[keep])) if keep.any() else 0.0,
                   np.max(np.abs(g0)) if len(g0) else 0.0)

    def state_names(self):
        out = []
        for k, un in enumerate(self.units):
            out += [f"{s}{un['bus'] + 1}" for s in un['names']]
        for sf in self.sfacts:
            out += [f"{s}{sf['aux']['f'] + 1}_{sf['aux']['t'] + 1}" for s in sf['names']]
        return out

    def unit_state(self, X, k, name):
        """Time history of one named state of unit k (X: NT x NX array)."""
        un = self.units[k]
        j = un['names'].index(name)
        return X[:, un['xsl']][:, j] if X.ndim == 2 else X[un['xsl']][j]

    def speed_states(self):
        """(k, column, M_i) of every unit whose speed state defines the
        centre-of-inertia frequency: SG rotor speed and the GFM family's
        virtual-swing speed.  Converter-interfaced turbines (WT4) and the
        induction machines (WT1-WT3) are deliberately excluded: their rotor
        speed is not an angle-forming grid frequency."""
        out = []
        for k, un in enumerate(self.units):
            if un.get('facts'):
                continue                               # FACTS carry no rotor speed
            i = un['bus']
            tag = un['tag']
            Sb = self.case.Sbase_gen[k]
            if tag == 'SG' or tag.startswith('SG'):    # SG, SG6, SG4, SG2
                col = un['xsl'].start + un['names'].index('omega')
                out.append((k, col, 2 * self.case.machine['H'][i] * Sb, 'abs'))
            elif tag.endswith('GFM') or tag == 'GFM':
                out.append((k, un['xsl'].start + 1, 2 * un['aux']['p']['Hv'] * Sb, 'abs'))
        return out

    def coi_freq(self, X):
        """Centre-of-inertia frequency (Hz) from SG + GFM speed states."""
        ws = self.case.ws
        num = 0.0
        den = 0.0
        for k, col, M, kind in self.speed_states():
            num = num + M * X[..., col]
            den += M
        if den == 0:
            return None
        return (num / den) / ws * (ws / (2 * np.pi))   # rad/s -> Hz

    def eff_inertia(self):
        """Effective system inertia H_sys incl. GFM virtual inertia
        [Fang et al. 2019]: H_sys = sum(2 H S) / sum(S) over SG + GFM."""
        num = 0.0
        for k, un in enumerate(self.units):
            if un.get('facts'):
                continue
            i = un['bus']
            Sb = self.case.Sbase_gen[k]
            if un['tag'] == 'SG' or un['tag'].startswith('SG'):
                num += 2 * self.case.machine['H'][i] * Sb
            elif un['tag'] == 'GFM' or un['tag'].endswith('-GFM'):
                num += 2 * un['aux']['p']['Hv'] * Sb
        return num / np.sum(self.case.Sbase_gen)

    def penetration(self):
        """IBR share of total generation (%)."""
        Pgen = np.array([self.case.Pg[u['bus']] for u in self.units])
        ibr = sum(Pgen[k] for k, u in enumerate(self.units)
                  if not u.get('facts') and not u['tag'].startswith('SG'))
        den = sum(Pgen[k] for k, u in enumerate(self.units) if not u.get('facts'))
        return 100.0 * ibr / den if den else 0.0
