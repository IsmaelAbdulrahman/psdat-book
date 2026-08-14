"""
units.py — the unit equation library.

Every generating unit lives here as a pair of plain functions
    <tag>_init(case, i, prm)                 -> x0, alg0, aux
    <tag>_f(xi, za, Vg, Thg, aux, prm, u)    -> f, Pinj, Qinj, galg
written with every equation visible and cited, in the educational style of
PSDAT [Abdulrahman, IEEE OAJPE 2020].  `xi` are the unit's differential
states, `za` its own algebraic variables (stator currents, if any), (Vg,Thg)
its terminal bus voltage, `aux` the constants frozen at the operating point,
`prm` the parameter dict, and `u` the unit inputs at time t:

    u = dict(dP =  power set-point / mechanical-power offset (pu),
             G  =  PV irradiance (pu of STC, absolute; None -> initial),
             vw =  wind speed (pu of rated, absolute; None -> initial))

Sign convention: Pinj, Qinj are the powers INJECTED into the bus (generation
positive), matching the polar power-balance equations of the network.

Unit catalogue (tag -> differential states):
  SG        11  two-axis sub-transient machine + IEEE-T1 exciter + governor
                 [Sauer & Pai ch. 3-4; Anderson & Fouad]
  GFM        3  grid-forming droop/VSM converter, ideal DC source
                 [Zhong & Weiss 2011; D'Arco & Suul 2014]
  GFL        4  grid-following PLL + current-control converter, ideal source
                 [Kaura & Blasko 1997; Chung 2000; Yazdani & Iravani ch. 8]
  PV-GFL     7  PV array + DC link + MPPT behind a GFL converter
                 [Villalva et al. 2009 (array); Yazdani & Iravani ch. 8]
  PV-GFM     4  curtailed PV (headroom) behind a GFM converter
  BESS-GFM   4  battery (state of charge) behind a GFM converter
  BESS-GFL   7  battery behind GFL with fast-frequency response (droop+RoCoF)
                 [Kundur ch. 11 (droop); IEEE 2800-2022 (FFR functions)]
  WT4-GFL   12  Type-4 wind turbine: Cp(lambda,beta) aerodynamics, two-mass
                 drivetrain, pitch control, MPPT, behind GFL
                 [Heier 1998 (Cp); Slootweg et al. 2003; Ackermann ch. 24]
  WT4-GFM    9  same turbine behind a GFM converter (rotor provides inertia)
  WT3       10  Type-3 DFIG: 3rd-order induction machine + rotor-converter
                 current control + drivetrain + pitch  [Ekanayake et al. 2003;
                 Holdsworth et al. 2003; Sauer & Pai ch. 5 (IM model)]
  WT1        5  Type-1 fixed-speed squirrel-cage induction generator,
                 two-mass shaft, direct grid connection [Ackermann ch. 24]
  WT2        6  Type-2: WT1 + variable external rotor resistance control
"""
import numpy as np

# ============================ DEFAULT PARAMETERS ============================
# (system per-unit on 100 MVA unless stated; overridable per unit instance)
# IEEE Std 1547-2018 autonomous grid-support functions, shared by every grid-
# following inverter (PV / battery / ideal GFL).  ALL OFF by default (gains 0,
# qmode 0 = constant reactive power), so a unit reduces to constant-P/Q and its
# dispatched operating point is untouched.  Turn one on per unit in the gear
# dialog.  See q_support()/p_support() for the equations and clause references.
GS_DEF = dict(qmode=0,        # reactive mode: 0 const-Q, 1 Volt-VAR, 2 const-PF
              Kqv=0.0,        # Volt-VAR Q-V droop gain (pu Q / pu V)   [1547 Tbl.8]
              Vdb=0.0,        # Volt-VAR voltage deadband half-width (pu)
              Qmax=0.44,      # reactive capability limit (pu of unit rating)
              Kvw=0.0,        # Volt-Watt P-V droop gain (pu P / pu V)  [1547 5.14.6]
              Vvw=1.06,       # Volt-Watt voltage threshold (pu; curtail above)
              Kfw=0.0,        # Freq-Watt P-f droop gain (pu P / pu f)  [1547 6.4]
              fdb=0.0)        # Freq-Watt frequency deadband half-width (pu)
GFM_DEF = dict(Hv=5.0, Dp=20.0, wc=31.4, mq=0.05, Rc=0.005, Xc=0.05)
GFL_DEF = dict(Kp=50.0, Ki=900.0, Ti=0.01)   # GS_DEF merged in only at the GFL/PV/BESS
PV_DEF = dict(voc=1.25, isc=1.08,      # units that implement it (not wind / PV-GFM)
                                        # array open-circuit V / short-circuit I (STC MPP)
              Cdc=0.20,                 # DC-link 'inertia' constant (pu-s)
              Kpdc=5.0, Kidc=50.0,      # DC-voltage regulator PI
              Tm=0.5,                   # MPPT tracking lag (s)
              G0=1.0,                   # initial irradiance (pu of 1000 W/m2)
              curt=0.10, Tav=0.2)       # PV-GFM: headroom fraction, meas. lag
BESS_DEF = dict(Eh=1.0,                 # storage duration at rated power (h)
                eta=0.95,               # one-way efficiency (smooth loss model)
                SOC0=0.60, SOCmin=0.10, SOCmax=0.90, dSOC=0.05,  # limit width
                Pmax=None,              # power rating (pu); None -> 1.5*|Pg0|
                Kf=15.0, db=3e-4,       # FFR droop gain, deadband (pu freq) — native Freq-Watt
                Tf=0.15, Tw=0.5, Kr=0.0,  # FFR lag, RoCoF washout, RoCoF gain
                # IEEE 1547-2018 reactive support + Volt-Watt (frequency handled
                # by the native FFR above, so no separate Freq-Watt here):
                qmode=0, Kqv=0.0, Vdb=0.0, Qmax=0.44, Kvw=0.0, Vvw=1.06)
WT4_DEF = dict(Ht=4.0, Hg=0.9,          # turbine / generator inertia (s, on WT base)
               Ksh=0.3, Dsh=1.0,        # shaft stiffness (pu T/el.rad), damping
               lam_r=8.1, Cpmax=0.48,   # optimal tip-speed ratio, max Cp
               c=(0.5176, 116, 0.4, 5, 21, 0.0068),  # Heier Cp coefficients
               Kpp=150.0, Kip=25.0,     # pitch PI (deg per pu speed)
               Tp=0.3, bmax=27.0,       # pitch actuator lag (s), max angle (deg)
               TPo=5.0,                 # MPPT power-order lag (s)
               vw0=0.9,                 # initial wind speed (pu of rated)
               kopt=1.0,                # MPPT constant: Popt = kopt*wg^3
               syn_in=False, Ksi=10.0, Tsi=1.0)  # synthetic-inertia option
WT3_DEF = dict(Rs=0.00706, Xls=0.171, Xm=2.9, Rr=0.005, Xlr=0.156,  # GE 3.6 MW-class
               Ht=4.29, Hg=0.9, Ksh=0.3, Dsh=1.0,   # two-mass drivetrain
               lam_r=8.1, Cpmax=0.48, c=(0.5176, 116, 0.4, 5, 21, 0.0068),
               Kpp=150.0, Kip=25.0, Tp=0.3, bmax=27.0, TPo=5.0,
               KpT=0.3, KiT=8.0,        # rotor q-axis (torque) current PI
               KpV=0.3, KiV=8.0,        # rotor d-axis (Q) current PI
               vw0=0.9, kopt=1.0)
WT1_DEF = dict(Rs=0.0064, Xls=0.0929, Xm=3.8, Rr=0.0088, Xlr=0.0999,  # SCIG
               Ht=4.0, Hg=0.6, Ksh=0.3, Dsh=1.0,
               lam_r=6.3, Cpmax=0.44, c=(0.5176, 116, 0.4, 5, 21, 0.0068),
               vw0=0.9)
WT2_DEF = dict(WT1_DEF, Rext_max=0.05, KpR=0.5, KiR=5.0)  # + rotor-R control


def _p(defaults, prm):
    q = dict(defaults)
    if prm:
        q.update(prm)
    return q


# ============================ SYNCHRONOUS GENERATOR =========================
# Two-axis sub-transient model + IEEE Type-I exciter + turbine-governor,
# exactly as in PSDAT [Sauer & Pai (2017) ch. 3-4; eqns 3.148-3.159 etc.].
# States: Eqp Si1d Edp Si2q Delta w Efd RF VR TM PSV ; algebraic: Id Iq.
def sg_init(case, i, prm=None):
    md = case.machine
    ws = case.ws
    Vb = case.V0[i] * np.exp(1j * case.TH0[i])
    S = case.Pg[i] + 1j * case.Qg[i]
    Rs, Xq, Xqp, Xd, Xdp, Xdpp, Xls = (md['Rs'][i], md['Xq'][i], md['Xqp'][i],
                                       md['Xd'][i], md['Xdp'][i], md['Xdpp'][i], md['Xls'][i])
    Xqpp = md['Xqpp'][i]
    Iph = np.conj(S / Vb)
    E0 = Vb + (Rs + 1j * Xq) * Iph
    D0 = np.angle(E0)
    Id0 = np.real(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Iq0 = np.imag(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Edp0 = (Xq - Xqp) * Iq0
    Si2q0 = (Xls - Xq) * Iq0
    Eqp0 = Rs * Iq0 + Xdp * Id0 + case.V0[i] * np.cos(D0 - case.TH0[i])
    Si1d0 = Eqp0 - (Xdp - Xls) * Id0
    Efd0 = Eqp0 + (Xd - Xdp) * Id0
    TM0 = (((Xdpp - Xls) / (Xdp - Xls)) * Eqp0 * Iq0
           + ((Xdp - Xdpp) / (Xdp - Xls)) * Si1d0 * Iq0
           + ((Xqpp - Xls) / (Xqp - Xls)) * Edp0 * Id0
           - ((Xqp - Xqpp) / (Xqp - Xls)) * Si2q0 * Id0
           + (Xqpp - Xdpp) * Id0 * Iq0)
    VR0 = (md['KE'][i] + md['Ax'][i] * np.exp(md['Bx'][i] * Efd0)) * Efd0
    RF0 = (md['KF'][i] / md['TF'][i]) * Efd0
    x0 = np.array([Eqp0, Si1d0, Edp0, Si2q0, D0, ws, Efd0, RF0, VR0, TM0, TM0])
    aux = dict(i=i, Vref=case.V0[i] + VR0 / md['KA'][i], PC=TM0, md=md, ws=ws)
    return x0, np.array([Id0, Iq0]), aux


def sg_f(xi, za, Vg, Thg, aux, prm, u):
    md = aux['md']; i = aux['i']; ws = aux['ws']
    Eqp, Si1d, Edp, Si2q, Delta, w, Efd, RF, VR, TM, PSV = xi
    Id, Iq = za
    H, Xd, Xdp, Xdpp = md['H'][i], md['Xd'][i], md['Xdp'][i], md['Xdpp'][i]
    Xq, Xqp, Xqpp, Xls = md['Xq'][i], md['Xqp'][i], md['Xqpp'][i], md['Xls'][i]
    Rs, Dm = md['Rs'][i], md['Dm'][i]
    ad = Delta - Thg
    PC = aux['PC'] + u.get('dP', 0.0)          # governor set-point (+ gen-side dist.)
    # flux-decay + damper-winding dynamics [Sauer & Pai eq. 3.148-3.151]
    f1 = (1 / md['Td0p'][i]) * (-Eqp - (Xd - Xdp) * (Id - ((Xdp - Xdpp) / (Xdp - Xls) ** 2)
                                                     * (Si1d + (Xdp - Xls) * Id - Eqp)) + Efd)
    f2 = (1 / md['Td0pp'][i]) * (-Si1d + Eqp - (Xdp - Xls) * Id)
    f3 = (1 / md['Tq0p'][i]) * (-Edp + (Xq - Xqp) * (Iq - ((Xqp - Xqpp) / (Xqp - Xls) ** 2)
                                                     * (Si2q + (Xqp - Xls) * Iq + Edp)))
    f4 = (1 / md['Tq0pp'][i]) * (-Si2q - Edp - (Xqp - Xls) * Iq)
    # swing equation [Kundur eq. 3.18]; TE = sub-transient air-gap torque
    f5 = w - ws
    TE = (((Xdpp - Xls) / (Xdp - Xls)) * Eqp * Iq + ((Xdp - Xdpp) / (Xdp - Xls)) * Si1d * Iq
          + ((Xqpp - Xls) / (Xqp - Xls)) * Edp * Id - ((Xqp - Xqpp) / (Xqp - Xls)) * Si2q * Id
          + (Xqpp - Xdpp) * Id * Iq)
    f6 = (ws / (2 * H)) * (TM - TE - Dm * (w - ws))
    # IEEE Type-I exciter [Sauer & Pai fig. 4.5]
    f7 = (1 / md['TE'][i]) * ((-(md['KE'][i] + md['Ax'][i] * np.exp(md['Bx'][i] * Efd))) * Efd + VR)
    f8 = (1 / md['TF'][i]) * (-RF + (md['KF'][i] / md['TF'][i]) * Efd)
    f9 = (1 / md['TA'][i]) * (-VR + md['KA'][i] * RF - ((md['KA'][i] * md['KF'][i]) / md['TF'][i]) * Efd
                              + md['KA'][i] * (aux['Vref'] - Vg + aux.get('Vpss', 0.0)))
    # turbine-governor with droop RD [Sauer & Pai fig. 4.8]
    f10 = (1 / md['TCH'][i]) * (-TM + PSV)
    f11 = (1 / md['TSV'][i]) * (-PSV + PC - (1 / md['RD'][i]) * (w / ws - 1))
    # stator algebraic equations [Sauer & Pai eq. 3.152-3.153]
    SE1 = (Rs * Id - Xqpp * Iq - ((Xqpp - Xls) / (Xqp - Xls)) * Edp
           + ((Xqp - Xqpp) / (Xqp - Xls)) * Si2q + Vg * np.sin(ad))
    SE2 = (Rs * Iq + Xdpp * Id - ((Xdpp - Xls) / (Xdp - Xls)) * Eqp
           - ((Xdp - Xdpp) / (Xdp - Xls)) * Si1d + Vg * np.cos(ad))
    Pinj = Id * Vg * np.sin(ad) + Iq * Vg * np.cos(ad)
    Qinj = Id * Vg * np.cos(ad) - Iq * Vg * np.sin(ad)
    return (np.array([f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11]),
            Pinj, Qinj, np.array([SE1, SE2]))


# -------------------- REDUCED-ORDER SG MODELS (Sauer & Pai) -----------------
# Teaching-oriented lower-order representations of the same machine, selectable
# per generator.  Each is an exact limiting case of the full model above, so it
# equilibrates to machine precision at the same operating point:
#   SG2  classical  (2 states: delta, omega)                  [Sauer&Pai 6.4]
#   SG4  two-axis   (4 states: Eqp, Edp, delta, omega)        [Sauer&Pai 6.3]
#   SG6  one-axis flux-decay + IEEE-T1 exciter (6 states:
#            Eqp, delta, omega, Efd, RF, VR)                  [Sauer&Pai 6.2 + 4.5]
# The 11-state 'SG' remains the full sub-transient + exciter + governor model.
def _dq0(case, i):
    """Common terminal / current initialisation in the machine dq frame."""
    Vb = case.V0[i] * np.exp(1j * case.TH0[i])
    Iph = np.conj((case.Pg[i] + 1j * case.Qg[i]) / Vb)
    return Vb, Iph


def sg2_init(case, i, prm=None):                       # classical (2-state)
    md = case.machine; ws = case.ws
    Vb, Iph = _dq0(case, i)
    Rs, Xdp = md['Rs'][i], md['Xdp'][i]
    E = Vb + (Rs + 1j * Xdp) * Iph                     # emf behind transient reactance
    D0 = np.angle(E); Ep = np.abs(E)
    Id0 = np.real(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Iq0 = np.imag(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    x0 = np.array([D0, ws])
    aux = dict(i=i, md=md, ws=ws, Ep=Ep, Pm=Ep * Iq0)  # Pm = internal power at t0
    return x0, np.array([Id0, Iq0]), aux


def sg2_f(xi, za, Vg, Thg, aux, prm, u):
    md = aux['md']; i = aux['i']; ws = aux['ws']; Ep = aux['Ep']
    Delta, w = xi; Id, Iq = za
    H, Dm, Rs, Xdp = md['H'][i], md['Dm'][i], md['Rs'][i], md['Xdp'][i]
    ad = Delta - Thg
    Pm = aux['Pm'] + u.get('dP', 0.0)
    TE = Ep * Iq                                       # air-gap power, E'd=0
    f1 = w - ws
    f2 = (ws / (2 * H)) * (Pm - TE - Dm * (w - ws))
    SE1 = Rs * Id - Xdp * Iq + Vg * np.sin(ad)         # E'd=0, X'q=X'd=Xdp
    SE2 = Rs * Iq + Xdp * Id - Ep + Vg * np.cos(ad)    # E'q=Ep (constant)
    Pinj = Id * Vg * np.sin(ad) + Iq * Vg * np.cos(ad)
    Qinj = Id * Vg * np.cos(ad) - Iq * Vg * np.sin(ad)
    return np.array([f1, f2]), Pinj, Qinj, np.array([SE1, SE2])


def sg4_init(case, i, prm=None):                       # two-axis (4-state)
    md = case.machine; ws = case.ws
    Vb, Iph = _dq0(case, i)
    Rs, Xq, Xqp = md['Rs'][i], md['Xq'][i], md['Xqp'][i]
    Xd, Xdp = md['Xd'][i], md['Xdp'][i]
    E0 = Vb + (Rs + 1j * Xq) * Iph; D0 = np.angle(E0)
    Id0 = np.real(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Iq0 = np.imag(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Edp0 = (Xq - Xqp) * Iq0
    Eqp0 = Rs * Iq0 + Xdp * Id0 + case.V0[i] * np.cos(D0 - case.TH0[i])
    Efd0 = Eqp0 + (Xd - Xdp) * Id0
    Pe0 = Edp0 * Id0 + Eqp0 * Iq0 + (Xqp - Xdp) * Id0 * Iq0
    x0 = np.array([Eqp0, Edp0, D0, ws])
    aux = dict(i=i, md=md, ws=ws, Efd=Efd0, Pm=Pe0)    # Efd, Pm held constant
    return x0, np.array([Id0, Iq0]), aux


def sg4_f(xi, za, Vg, Thg, aux, prm, u):
    md = aux['md']; i = aux['i']; ws = aux['ws']
    Eqp, Edp, Delta, w = xi; Id, Iq = za
    H, Dm, Rs = md['H'][i], md['Dm'][i], md['Rs'][i]
    Xd, Xdp, Xq, Xqp = md['Xd'][i], md['Xdp'][i], md['Xq'][i], md['Xqp'][i]
    Td0p, Tq0p = md['Td0p'][i], md['Tq0p'][i]
    ad = Delta - Thg
    Pm = aux['Pm'] + u.get('dP', 0.0); Efd = aux['Efd']
    f1 = (1 / Td0p) * (-Eqp - (Xd - Xdp) * Id + Efd)
    f2 = (1 / Tq0p) * (-Edp + (Xq - Xqp) * Iq)
    f3 = w - ws
    TE = Edp * Id + Eqp * Iq + (Xqp - Xdp) * Id * Iq
    f4 = (ws / (2 * H)) * (Pm - TE - Dm * (w - ws))
    SE1 = Rs * Id - Xqp * Iq - Edp + Vg * np.sin(ad)
    SE2 = Rs * Iq + Xdp * Id - Eqp + Vg * np.cos(ad)
    Pinj = Id * Vg * np.sin(ad) + Iq * Vg * np.cos(ad)
    Qinj = Id * Vg * np.cos(ad) - Iq * Vg * np.sin(ad)
    return np.array([f1, f2, f3, f4]), Pinj, Qinj, np.array([SE1, SE2])


def sg6_init(case, i, prm=None):                       # one-axis flux-decay + IEEE-T1 AVR
    md = case.machine; ws = case.ws
    Vb, Iph = _dq0(case, i)
    Rs, Xq, Xd, Xdp = md['Rs'][i], md['Xq'][i], md['Xd'][i], md['Xdp'][i]
    E0 = Vb + (Rs + 1j * Xq) * Iph; D0 = np.angle(E0)
    Id0 = np.real(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Iq0 = np.imag(Iph * np.exp(-1j * (D0 - np.pi / 2)))
    Eqp0 = Rs * Iq0 + Xdp * Id0 + case.V0[i] * np.cos(D0 - case.TH0[i])
    Efd0 = Eqp0 + (Xd - Xdp) * Id0
    Pe0 = Eqp0 * Iq0 + (Xq - Xdp) * Id0 * Iq0
    VR0 = (md['KE'][i] + md['Ax'][i] * np.exp(md['Bx'][i] * Efd0)) * Efd0
    RF0 = (md['KF'][i] / md['TF'][i]) * Efd0
    x0 = np.array([Eqp0, D0, ws, Efd0, RF0, VR0])
    aux = dict(i=i, md=md, ws=ws, Pm=Pe0, Vref=case.V0[i] + VR0 / md['KA'][i])
    return x0, np.array([Id0, Iq0]), aux


def sg6_f(xi, za, Vg, Thg, aux, prm, u):
    md = aux['md']; i = aux['i']; ws = aux['ws']
    Eqp, Delta, w, Efd, RF, VR = xi; Id, Iq = za
    H, Dm, Rs = md['H'][i], md['Dm'][i], md['Rs'][i]
    Xd, Xdp, Xq, Td0p = md['Xd'][i], md['Xdp'][i], md['Xq'][i], md['Td0p'][i]
    ad = Delta - Thg
    Pm = aux['Pm'] + u.get('dP', 0.0)
    f1 = (1 / Td0p) * (-Eqp - (Xd - Xdp) * Id + Efd)   # flux decay (E'd=0)
    f2 = w - ws
    TE = Eqp * Iq + (Xq - Xdp) * Id * Iq
    f3 = (ws / (2 * H)) * (Pm - TE - Dm * (w - ws))
    f4 = (1 / md['TE'][i]) * ((-(md['KE'][i] + md['Ax'][i] * np.exp(md['Bx'][i] * Efd))) * Efd + VR)
    f5 = (1 / md['TF'][i]) * (-RF + (md['KF'][i] / md['TF'][i]) * Efd)
    f6 = (1 / md['TA'][i]) * (-VR + md['KA'][i] * RF - ((md['KA'][i] * md['KF'][i]) / md['TF'][i]) * Efd
                              + md['KA'][i] * (aux['Vref'] - Vg + aux.get('Vpss', 0.0)))
    SE1 = Rs * Id - Xq * Iq + Vg * np.sin(ad)          # d-axis, E'd=0, salient Xq
    SE2 = Rs * Iq + Xdp * Id - Eqp + Vg * np.cos(ad)
    Pinj = Id * Vg * np.sin(ad) + Iq * Vg * np.cos(ad)
    Qinj = Id * Vg * np.cos(ad) - Iq * Vg * np.sin(ad)
    return np.array([f1, f2, f3, f4, f5, f6]), Pinj, Qinj, np.array([SE1, SE2])


# --- governed reduced variants: add the turbine-governor to the swing so the
#     model shows primary frequency response (Pm = TM, droop RD) ---
def _gov_f(TM, PSV, w, ws, md, i, PC):
    fTM = (1 / md['TCH'][i]) * (-TM + PSV)
    fPSV = (1 / md['TSV'][i]) * (-PSV + PC - (1 / md['RD'][i]) * (w / ws - 1))
    return fTM, fPSV


def sg4g_init(case, i, prm=None):                      # two-axis + governor (6 states)
    x0, z0, aux = sg4_init(case, i, prm)
    Pm = aux['Pm']
    aux['PC'] = Pm                                      # governor set-point
    return np.concatenate([x0, [Pm, Pm]]), z0, aux     # + TM, PSV


def sg4g_f(xi, za, Vg, Thg, aux, prm, u):
    Eqp, Edp, Delta, w, TM, PSV = xi
    md = aux['md']; i = aux['i']; ws = aux['ws']
    sub = np.array([Eqp, Edp, Delta, w])
    aux2 = dict(aux); aux2['Pm'] = TM                  # swing sees governed torque
    fsub, Pinj, Qinj, SE = sg4_f(sub, za, Vg, Thg, aux2, prm, {})
    fTM, fPSV = _gov_f(TM, PSV, w, ws, md, i, aux['PC'] + u.get('dP', 0.0))
    return np.array([fsub[0], fsub[1], fsub[2], fsub[3], fTM, fPSV]), Pinj, Qinj, SE


def sg6g_init(case, i, prm=None):                      # one-axis + AVR + governor (8)
    x0, z0, aux = sg6_init(case, i, prm)
    Pm = aux['Pm']
    aux['PC'] = Pm
    return np.concatenate([x0, [Pm, Pm]]), z0, aux


def sg6g_f(xi, za, Vg, Thg, aux, prm, u):
    Eqp, Delta, w, Efd, RF, VR, TM, PSV = xi
    md = aux['md']; i = aux['i']; ws = aux['ws']
    sub = np.array([Eqp, Delta, w, Efd, RF, VR])
    aux2 = dict(aux); aux2['Pm'] = TM
    fsub, Pinj, Qinj, SE = sg6_f(sub, za, Vg, Thg, aux2, prm, {})
    fTM, fPSV = _gov_f(TM, PSV, w, ws, md, i, aux['PC'] + u.get('dP', 0.0))
    return (np.array([fsub[0], fsub[1], fsub[2], fsub[3], fsub[4], fsub[5], fTM, fPSV]),
            Pinj, Qinj, SE)


# ------------- POWER-SYSTEM STABILISER (supplementary excitation control) ---
# Classic Δω-input stabiliser [Sauer & Pai ch. 8; Kundur ch. 12; IEEE PSS1A]:
# a washout sTw/(1+sTw) (blocks steady-state bias) followed by TWO lead-lag
# stages [(1+sT1)/(1+sT2)]^2 (phase lead to cancel the exciter+field lag
# GEP(s)) and gain Kpss.  The output Vpss is summed into the AVR reference,
# adding electrical damping torque in phase with Δω.  A single stage gives
# ~30 deg lead at 1.4 Hz — not enough to cancel the ~70 deg GEP lag, so two
# identical stages are used (the industry-standard structure).  Three states
# (Vw washout, V1/V2 lead-lag); all zero at the operating point (Δω=0) so the
# equilibrium is untouched.  This is the "bridge to industry" controller — the
# same block shipped in real AVR/PSS packages, here in transparent state form.
PSS_DEF = dict(Kpss=10.0, Tw=10.0, T1=0.25, T2=0.02)


def _pss_params(prm):
    p = dict(PSS_DEF)
    if prm:
        for k in ('Kpss', 'Tw', 'T1', 'T2'):
            if k in prm and prm[k] not in (None, ''):
                p[k] = float(prm[k])
    return p


def _pss_f(Vw, V1, V2, dw, p):
    """PSS block.  dw = per-unit speed deviation (w-ws)/ws.
    washout -> two lead-lag stages.  Returns (fVw, fV1, fV2, Vpss)."""
    r = p['T1'] / p['T2']
    u = p['Kpss'] * dw                                  # gain on speed deviation
    fVw = (1.0 / p['Tw']) * (u - Vw)                    # washout state
    yw = u - Vw                                         # sTw/(1+sTw) output
    fV1 = (1.0 / p['T2']) * (yw - V1)                   # lead-lag stage 1
    y1 = r * yw + (1.0 - r) * V1
    fV2 = (1.0 / p['T2']) * (y1 - V2)                   # lead-lag stage 2
    Vpss = r * y1 + (1.0 - r) * V2
    return fVw, fV1, fV2, Vpss


def sgp_init(case, i, prm=None):                       # full SG + PSS (14 states)
    x0, z0, aux = sg_init(case, i, prm)
    aux['pss'] = _pss_params(prm)
    return np.concatenate([x0, [0.0, 0.0, 0.0]]), z0, aux   # + Vw,V1,V2 (0 at eq.)


def sgp_f(xi, za, Vg, Thg, aux, prm, u):
    ws = aux['ws']
    sub = xi[:11]; Vw, V1, V2 = xi[11], xi[12], xi[13]
    w = sub[5]                                          # omega index in full SG
    fVw, fV1, fV2, Vpss = _pss_f(Vw, V1, V2, (w - ws) / ws, aux['pss'])
    aux2 = dict(aux); aux2['Vpss'] = Vpss              # inject into AVR summing pt
    fsub, Pinj, Qinj, SE = sg_f(sub, za, Vg, Thg, aux2, prm, u)
    return np.concatenate([fsub, [fVw, fV1, fV2]]), Pinj, Qinj, SE


def sg6p_init(case, i, prm=None):                      # one-axis+AVR + PSS (9 states)
    x0, z0, aux = sg6_init(case, i, prm)
    aux['pss'] = _pss_params(prm)
    return np.concatenate([x0, [0.0, 0.0, 0.0]]), z0, aux


def sg6p_f(xi, za, Vg, Thg, aux, prm, u):
    ws = aux['ws']
    sub = xi[:6]; Vw, V1, V2 = xi[6], xi[7], xi[8]
    w = sub[2]                                          # omega index in SG6
    fVw, fV1, fV2, Vpss = _pss_f(Vw, V1, V2, (w - ws) / ws, aux['pss'])
    aux2 = dict(aux); aux2['Vpss'] = Vpss
    fsub, Pinj, Qinj, SE = sg6_f(sub, za, Vg, Thg, aux2, prm, u)
    return np.concatenate([fsub, [fVw, fV1, fV2]]), Pinj, Qinj, SE


# ------------- FUZZY-LOGIC STABILISER (intelligent supplementary control) ---
# Mamdani/Sugeno fuzzy PSS [Hsu & Cheng 1990; El-Metwally & Malik, IEE Proc.
# 1995; Kundur ch. 12 discussion of nonlinear stabilisers]: instead of a fixed
# lead-lag transfer function, the stabilising signal is produced by FUZZY
# INFERENCE over the washed-out speed deviation e and its (realizable)
# derivative de — a nonlinear, gain-scheduled PD surface:
#     e  -> 5 triangular fuzzy sets  NB NS ZE PS PB  on [-1, 1]
#     de -> 5 triangular fuzzy sets  NB NS ZE PS PB  on [-1, 1]
#     25 rules, the standard skew-symmetric (anti-diagonal) rule table
#         U(i,j) = sat(i + j)   (a large positive e AND rising -> push hard)
#     product inference + centre-average (zero-order Sugeno) defuzzification.
# Near the operating point the surface is exactly linear (equivalent to a
# washout PD stabiliser with gains Ku*Ke and Ku*Kde) so small-signal analysis
# sees a well-defined damping controller; for LARGE swings the saturating
# rule table gives the bang-bang-like extra push that made fuzzy PSS popular
# for multi-machine transient damping.  Two states (washout Vw, derivative
# filter Xd), both zero at the operating point, so the equilibrium is exact.
# The same structure is the front half of an ANFIS stabiliser: an adaptive
# pass (least squares on the rule consequents) can be layered on later
# without changing the state form used here.
FZ_DEF = dict(Ke=60.0, Kde=4.0, Ku=0.10, Tw=10.0, Td=0.05)
# defaults picked by eigen-scan on Kundur two-area: the 0.63 Hz inter-area
# mode moves from zeta = 3.5% (plain SG) to 10.5% with every local mode kept
# above 5.8% — comparable to the linear PSS while staying saturating-safe.
FZ_C = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])       # MF / consequent centres


def _fz_params(prm):
    p = dict(FZ_DEF)
    if prm:
        for k in FZ_DEF:
            if k in prm and prm[k] not in (None, ''):
                p[k] = float(prm[k])
    return p


def _fz_mu(x):
    """Memberships of scalar x on the 5-set triangular partition (half-width
    0.5, clipped to [-1,1]); normalized so the strengths sum to one."""
    x = min(1.0, max(-1.0, float(x)))
    mu = np.maximum(0.0, 1.0 - np.abs(x - FZ_C) / 0.5)
    s = mu.sum()
    return mu / (s if s > 0 else 1.0)


def _fz_pss(Vw, Xd, dw, p):
    """Fuzzy stabiliser block.  dw = per-unit speed deviation (w-ws)/ws.
    States: Vw (washout), Xd (derivative-filter).  Returns (fVw, fXd, Vs)."""
    fVw = (dw - Vw) / p['Tw']
    e = dw - Vw                                     # sTw/(1+sTw): washed Δω
    fXd = (e - Xd) / p['Td']
    de = fXd                                        # s/(1+sTd): realizable d/dt
    me = _fz_mu(p['Ke'] * e)
    md = _fz_mu(p['Kde'] * de)
    u = 0.0                                         # 25-rule Sugeno inference
    for i in range(5):
        wi = me[i]
        if wi == 0.0:
            continue
        for j in range(5):
            wj = md[j]
            if wj == 0.0:
                continue
            u += wi * wj * FZ_C[min(4, max(0, i + j - 2))]
    Vs = p['Ku'] * u
    return fVw, fXd, min(0.12, max(-0.12, Vs))      # PSS-style output limit


def sgf_init(case, i, prm=None):                   # full SG + FUZZY stabiliser
    x0, z0, aux = sg_init(case, i, prm)
    aux['fz'] = _fz_params(prm)
    return np.concatenate([x0, [0.0, 0.0]]), z0, aux   # + Vw, Xd (0 at eq.)


def sgf_f(xi, za, Vg, Thg, aux, prm, u):
    ws = aux['ws']
    sub = xi[:11]; Vw, Xd = xi[11], xi[12]
    w = sub[5]                                      # omega index in full SG
    fVw, fXd, Vpss = _fz_pss(Vw, Xd, (w - ws) / ws, aux['fz'])
    aux2 = dict(aux); aux2['Vpss'] = Vpss           # inject at the AVR summing pt
    fsub, Pinj, Qinj, SE = sg_f(sub, za, Vg, Thg, aux2, prm, u)
    return np.concatenate([fsub, [fVw, fXd]]), Pinj, Qinj, SE


# ============================ CONVERTER CORES ===============================
# Shared by the ideal-source units and by every PV / battery / wind unit that
# uses the same interface — the equations appear ONCE, here.

def gfm_core(dg, wg, Qf, Vg, Thg, Pref, Qset, Eset, p, ws):
    """Grid-forming droop/VSM core [Zhong & Weiss 2011; D'Arco & Suul 2014].
        ddg/dt = wg - ws
        2Hv/ws * dwg/dt = Pref - Pe - Dp*(wg/ws - 1)      (instantaneous Pe)
        dQf/dt = wc*(Qe - Qf),  Eg = Eset + mq*(Qset - Qf)
    Returns (f3, Pe, Qe)."""
    Zc = p['Rc'] + 1j * p['Xc']
    Vb = Vg * np.exp(1j * Thg)
    Egm = Eset + p['mq'] * (Qset - Qf)
    Eg = Egm * np.exp(1j * dg)
    Ic = (Eg - Vb) / Zc
    Sc = Vb * np.conj(Ic)
    Pe, Qe = Sc.real, Sc.imag
    fdg = wg - ws
    fwg = (ws / (2 * p['Hv'])) * (Pref - Pe - p['Dp'] * (wg / ws - 1))
    fQf = p['wc'] * (Qe - Qf)
    return np.array([fdg, fwg, fQf]), Pe, Qe


def gfl_core(thp, xpll, idc, iqc, Vg, Thg, idr, iqr, p):
    """Grid-following core: SRF-PLL [Kaura & Blasko 1997; Chung 2000] plus
    first-order current-control loops [Yazdani & Iravani ch. 8].
        dthp/dt = xpll + Kp*vq ,   dxpll/dt = Ki*vq     (vq = V sin(th-thp))
        Ti*did/dt = id* - id ,     Ti*diq/dt = iq* - iq
    Returns (f4, Pinj, Qinj, fpll) where fpll = PLL frequency estimate (rad/s
    deviation form: dthp/dt)."""
    phi = Thg - thp
    vq = Vg * np.sin(phi)
    fthp = xpll + p['Kp'] * vq
    fxpll = p['Ki'] * vq
    fid = (1 / p['Ti']) * (idr - idc)
    fiq = (1 / p['Ti']) * (iqr - iqc)
    Pinj = Vg * (idc * np.cos(phi) + iqc * np.sin(phi))
    Qinj = Vg * (idc * np.sin(phi) - iqc * np.cos(phi))
    return np.array([fthp, fxpll, fid, fiq]), Pinj, Qinj, fthp


def _ilim(idr, iqr, Ilim):
    """Converter current limit (fault ride-through): scale the reference
    vector down to the unit's current rating if exceeded [IEEE 2800-2022].
    Ilim is in SYSTEM pu — 1.2 x the unit's rated current (computed at init
    from its MVA size), NOT a fixed 1.2: a fixed system-pu limit silently
    clips any converter dispatched above 1.2 pu-system (this was a latent
    bug in the PSDAT-IBR reference for the 78%-GFL scenario)."""
    Iref = np.hypot(idr, iqr)
    if Iref > Ilim:
        idr *= Ilim / Iref
        iqr *= Ilim / Iref
    return idr, iqr


def _irate(case, i, p):
    """Unit current limit (system pu): Imax (pu of unit rating, default 1.2)
    x rated current, the rating defaulting to the dispatched |S0| (with a
    0.3-pu floor so lightly-dispatched units keep fault headroom)."""
    S0 = abs(case.Pg[i] + 1j * case.Qg[i])
    Sconv = p.get('Sconv') or max(S0, 0.3)
    return p.get('Imax', 1.2) * Sconv / max(case.V0[i], 0.5)


# ============================ IDEAL-SOURCE CONVERTERS =======================
def gfm_init(case, i, prm=None):
    p = _p(GFM_DEF, prm)
    Vb = case.V0[i] * np.exp(1j * case.TH0[i])
    S = case.Pg[i] + 1j * case.Qg[i]
    Ic = np.conj(S / Vb)
    Eg = Vb + (p['Rc'] + 1j * p['Xc']) * Ic       # internal voltage phasor
    x0 = np.array([np.angle(Eg), case.ws, case.Qg[i]])
    aux = dict(Pset=case.Pg[i], Qset=case.Qg[i], Eset=np.abs(Eg), p=p, ws=case.ws)
    return x0, np.array([]), aux


def gfm_f(xi, za, Vg, Thg, aux, prm, u):
    dg, wg, Qf = xi
    Pref = aux['Pset'] + u.get('dP', 0.0)
    f, Pe, Qe = gfm_core(dg, wg, Qf, Vg, Thg, Pref, aux['Qset'], aux['Eset'],
                         aux['p'], aux['ws'])
    return f, Pe, Qe, np.array([])


def gfl_init(case, i, prm=None):
    p = _p({**GFL_DEF, **GS_DEF}, prm)
    x0 = np.array([case.TH0[i], 0.0, case.Pg[i] / case.V0[i], -case.Qg[i] / case.V0[i]])
    aux = dict(Pset=case.Pg[i], Qset=case.Qg[i], p=p, ws=case.ws, V0=case.V0[i],
               Ilim=_irate(case, i, p))
    return x0, np.array([]), aux


def gfl_f(xi, za, Vg, Thg, aux, prm, u):
    thp, xpll, idc, iqc = xi
    p = aux['p']; ws = aux['ws']
    Pset = aux['Pset'] + u.get('dP', 0.0)
    dw = xpll / ws                               # PLL frequency-deviation estimate (pu)
    Pref = p_support(Pset, Vg, dw, aux['V0'], p)              # Volt-Watt + Freq-Watt
    Qref = q_support(Pref, Pset, aux['Qset'], Vg, aux['V0'], p)  # Volt-VAR / const-PF
    vd = max(Vg * np.cos(Thg - thp), 0.1)        # voltage floor (fault ride-through)
    idr, iqr = _ilim(Pref / vd, -Qref / vd, aux['Ilim'])
    f, Pinj, Qinj, _ = gfl_core(thp, xpll, idc, iqc, Vg, Thg, idr, iqr, p)
    return f, Pinj, Qinj, np.array([])


# ============================ SMOOTH HELPERS ================================
# Limits are implemented with SMOOTH functions so the model stays continuously
# differentiable (exact linearization remains valid; limits are inactive at
# the operating point and engage smoothly during large disturbances).

def s_relu(x, eps=0.01):
    """Smooth max(x, 0)."""
    return 0.5 * (x + np.sqrt(x * x + eps * eps))


def s_min(a, b, eps=0.01):
    """Smooth min(a, b)."""
    return a - s_relu(a - b, eps)


def s_clamp(x, lo, hi, eps=0.01):
    """Smooth clamp of x into [lo, hi]."""
    return x - s_relu(x - hi, eps) + s_relu(lo - x, eps)


def s_dead(y, db):
    """Smooth deadband: ~0 inside |y|<db, ~y-db*sign(y) outside
    (slope exactly 0 at the origin -> inactive in the linearization).
    db<=0 means no deadband (pass-through)."""
    if db <= 0:
        return y
    return y - db * np.tanh(y / db)


def s_sig(x):
    """Smooth 0..1 saturation (capability fade near SOC limits)."""
    return 0.5 * (1 + np.tanh(x))


# =================== IEEE 1547-2018 GRID-SUPPORT FUNCTIONS ==================
# Autonomous inverter functions that make a grid-following converter respond to
# local voltage and frequency — the "bridge to industry": the same controls a
# real PV/battery inverter must implement per IEEE Std 1547-2018 (and IEEE 2800-
# 2022 for bulk plants).  Written as explicit droops so they reduce EXACTLY to
# constant-P/Q at the dispatched operating point (gains 0 or signals at their
# reference), leaving the initial equilibrium untouched.
#
#   q_support (reactive, one mode active):
#     0 constant reactive power  Q* = Qset
#     1 Volt-VAR   Q* = Qset - Kqv * db(V - V0)                 [1547-2018 §5.14.4, Table 8]
#     2 constant power factor    Q* = (Qset/Pset) * P           [1547-2018 §5.14.2]
#   p_support (active, both may be active):
#     Volt-Watt    P* = Pset - Kvw * [ru(V - Vvw) - ru(V0 - Vvw)]   [1547-2018 §5.14.6]
#     Freq-Watt    P* = P* - Kfw * db(dw)  (droop 1/R = Kfw)        [1547-2018 §6.4;
#                                            governor-style droop, Kundur §11.1]
#   db()=smooth deadband (s_dead), ru()=smooth ramp/relu (s_relu); the -ru(V0-Vvw)
#   term is the exact-equilibrium correction (Volt-Watt off at V=V0).

def q_support(Pref, Pset, Qset, Vg, V0, p):
    """Reactive-power reference of a grid-following inverter (IEEE 1547-2018
    clause 5.14).  Returns Q* clamped to +/-Qmax, exact-equilibrium preserving
    (Q*=Qset at V=V0, P=Pset)."""
    mode = int(p.get('qmode', 0))
    if mode == 1 and p.get('Kqv', 0.0) > 0.0:                 # Volt-VAR
        dv = s_dead(Vg - V0, p['Vdb']) if p.get('Vdb', 0.0) > 0 else (Vg - V0)
        Qr = Qset - p['Kqv'] * dv
    elif mode == 2 and abs(Pset) > 1e-6:                      # constant power factor
        Qr = (Qset / Pset) * Pref                             # holds the dispatched pf
    else:
        return Qset                                          # constant reactive power
    qm = p.get('Qmax', 0.44)
    c0 = Qset - s_clamp(Qset, -qm, qm)
    return s_clamp(Qr, -qm, qm) + c0


def p_support(Pset, Vg, dw, V0, p):
    """Active-power reference of a grid-following inverter with the IEEE 1547-
    2018 Volt-Watt (over-voltage curtailment) and Freq-Watt (frequency droop)
    functions.  dw = per-unit frequency deviation.  Both inactive at V=V0, dw=0,
    so P*=Pset there (exact equilibrium)."""
    Pr = Pset
    if p.get('Kvw', 0.0) > 0.0:                              # Volt-Watt (over-voltage)
        Pr = Pr - p['Kvw'] * (s_relu(Vg - p.get('Vvw', 1.06))
                              - s_relu(V0 - p.get('Vvw', 1.06)))
    if p.get('Kfw', 0.0) > 0.0:                              # Freq-Watt (droop)
        Pr = Pr - p['Kfw'] * s_dead(dw, p.get('fdb', 0.0))
    return Pr


# ============================ PV ARRAY ======================================
# Simplified explicit single-diode array model (normalised so that the STC
# maximum-power point is V=1, I=1; voc=Voc/Vmp, isc=Isc/Imp):
#     I(V,G) = G*isc*[1 - C1*(exp(V/(C2*voc)) - 1)]
#     C2 = (1/voc - 1)/ln(1 - 1/isc),  C1 = (1 - 1/isc)*exp(-1/(C2*voc))
# — the classical explicit PV-array approximation used throughout the PV
# literature and textbooks [Masters, Renewable & Efficient Electric Power
# Systems; Femia et al., Power Electronics and Control Techniques for Maximum
# Energy Harvesting in PV Systems].  Irradiance G in pu of 1000 W/m2.

def pv_curve(p):
    voc, isc = p['voc'], p['isc']
    C2 = (1 / voc - 1) / np.log(1 - 1 / isc)
    C1 = (1 - 1 / isc) * np.exp(-1 / (C2 * voc))
    def I(V, G):
        return G * isc * (1 - C1 * (np.exp(V / (C2 * voc)) - 1))
    return I


def pv_mpp(p, G):
    """Numerical maximum-power point (Vmp, Pmp) of the array at irradiance G
    (golden-section search on the smooth P(V) curve)."""
    I = pv_curve(p)
    a, b = 0.5, p['voc'] * 0.999
    gr = (np.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    for _ in range(60):
        if c * I(c, G) > d * I(d, G):
            b = d
        else:
            a = c
        c, d = b - gr * (b - a), a + gr * (b - a)
    V = 0.5 * (a + b)
    return V, V * I(V, G)


def pv_vpower(p, G, Ptgt, Vmp, Pmp):
    """DC-side voltage on the UPPER (deloading) branch of the P-V curve that
    delivers array power Ptgt (<= Pmp).  Raising V above Vmp curtails the array
    — this is how a PV plant provides active-power grid support (Volt-Watt /
    Freq-Watt) without a battery [Sangwongwanich et al., IEEE T-PE 2017,
    'flexible active-power control of PV'; Femia et al.].  Returns Vmp when no
    curtailment is requested (Ptgt >= Pmp)."""
    if Ptgt >= Pmp * 0.999:
        return Vmp
    I = pv_curve(p)
    lo, hi = Vmp, p['voc'] * 0.999
    for _ in range(40):                 # bisection: on V>Vmp, power falls as V rises
        mid = 0.5 * (lo + hi)
        if mid * I(mid, G) > Ptgt:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------- PV-GFL ---
# PV plant behind a grid-following converter [Yazdani & Iravani ch. 8]:
# the DC-link voltage is regulated by the d-axis current reference (energy
# balance), the MPPT sets the DC-voltage reference.
# States: thpll xpll id iq | Vdc xdc vref
#     Cdc*Vdc*dVdc/dt = Ppv(Vdc,G) - Pe          (DC-link power balance)
#     id* = Kpdc*(Vdc - vref) + xdc,  dxdc/dt = Kidc*(Vdc - vref)
#     dvref/dt = (Vmp(G) - vref)/Tm              (MPPT tracking lag)
def pvgfl_init(case, i, prm=None):
    p = _p({**GFL_DEF, **PV_DEF, **GS_DEF}, prm)
    vmp0, pmp0 = pv_mpp(p, p['G0'])
    Spl = case.Pg[i]                        # plant rating scale (system pu):
    # the DC side is normalised PER PLANT (powers /Spl), so the DC-link time
    # constant Cdc and the PI gains are size-invariant, as physics requires
    x0 = np.array([case.TH0[i], 0.0, case.Pg[i] / case.V0[i], -case.Qg[i] / case.V0[i],
                   vmp0, 1.0 / case.V0[i], vmp0])
    aux = dict(Pset=case.Pg[i], Qset=case.Qg[i], p=p, ws=case.ws, V0=case.V0[i],
               Spl=Spl, pmp0=pmp0, Icurve=pv_curve(p), Ilim=_irate(case, i, p))
    return x0, np.array([]), aux


def pvgfl_f(xi, za, Vg, Thg, aux, prm, u):
    thp, xpll, idc, iqc, Vdc, xdc, vref = xi
    p = aux['p']; ws = aux['ws']
    G = u.get('G', None)
    G = p['G0'] if G is None else G
    # --- PV array + DC link (plant per-unit: 1.0 = plant MPP at G0) ---
    Ppv_p = Vdc * aux['Icurve'](Vdc, G) / aux['pmp0']
    phi = Thg - thp
    Pe = Vg * (idc * np.cos(phi) + iqc * np.sin(phi))    # AC power (system pu)
    fVdc = (Ppv_p - Pe / aux['Spl']) / (p['Cdc'] * Vdc)
    fxdc = p['Kidc'] * (Vdc - vref)
    # --- MPPT reference: tracks Vmp, OR a curtailed (higher) voltage when the
    #     active-power grid-support functions ask the array to de-load ---
    vmpG, pmpG = pv_mpp(p, G)
    if p.get('Kvw', 0.0) > 0.0 or p.get('Kfw', 0.0) > 0.0:
        dw = xpll / ws                                   # PLL frequency deviation (pu)
        Pav = aux['Pset'] * (pmpG / aux['pmp0'])         # available power (system pu) at G
        Pdem = p_support(Pav, Vg, dw, aux['V0'], p)      # Volt-Watt / Freq-Watt curtailment
        frac = min(max(Pdem / max(Pav, 1e-6), 0.1), 1.0)
        vtarget = pv_vpower(p, G, frac * pmpG, vmpG, pmpG)
    else:
        vtarget = vmpG
    fvref = (vtarget - vref) / p['Tm']
    # --- GFL interface (current reference scaled back to system pu) ---
    vd = max(Vg * np.cos(phi), 0.1)
    idr = aux['Spl'] * (p['Kpdc'] * (Vdc - vref) + xdc)  # DC-voltage regulator
    Qref = q_support(Pe, aux['Pset'], aux['Qset'], Vg, aux['V0'], p)   # Volt-VAR / const-PF
    iqr = -Qref / vd
    idr, iqr = _ilim(idr, iqr, aux['Ilim'])
    f4, Pinj, Qinj, _ = gfl_core(thp, xpll, idc, iqc, Vg, Thg, idr, iqr, p)
    return (np.concatenate([f4, [fVdc, fxdc, fvref]]), Pinj, Qinj, np.array([]))


# ---------------------------------------------------------------- PV-GFM ---
# Curtailed PV behind a grid-forming converter: the plant holds `curt`
# headroom (deloaded operation) so it can respond like a GFM source until the
# available power Pav(G) is reached; the DC side is assumed regulated by
# curtailment.  States: dg wg Qf | Pav
def pvgfm_init(case, i, prm=None):
    p = _p({**GFM_DEF, **PV_DEF}, prm)
    st, _, auxg = gfm_init(case, i, {k: p[k] for k in GFM_DEF})
    Pav0 = case.Pg[i] / (1 - p['curt'])     # headroom above the operating point
    _, pmp0 = pv_mpp(p, p['G0'])
    kS = Pav0 / pmp0
    x0 = np.concatenate([st, [Pav0]])
    # c0 makes the smooth limit EXACTLY inactive at the operating point, so
    # the initial state is a machine-precision equilibrium
    c0 = case.Pg[i] - s_min(case.Pg[i], Pav0)
    aux = dict(auxg, pv=p, kS=kS, c0=c0)
    return x0, np.array([]), aux


def pvgfm_f(xi, za, Vg, Thg, aux, prm, u):
    dg, wg, Qf, Pav = xi
    p = aux['pv']
    G = u.get('G', None)
    G = p['G0'] if G is None else G
    _, pmpG = pv_mpp(p, G)
    fPav = (aux['kS'] * pmpG - Pav) / p['Tav']          # available-power tracking
    Pref = aux['Pset'] + u.get('dP', 0.0)
    Pref = s_min(Pref, Pav) + aux['c0']                  # cannot exceed the sun
    f3, Pe, Qe = gfm_core(dg, wg, Qf, Vg, Thg, Pref, aux['Qset'], aux['Eset'],
                          aux['p'], aux['ws'])
    return np.concatenate([f3, [fPav]]), Pe, Qe, np.array([])


# ============================ BATTERY STORAGE ===============================
# State of charge integrates the DC-side power with a smooth efficiency loss
# [Plett, Battery Management Systems vol. I (SOC definition)]:
#     dSOC/dt = -Pb / (3600*Eh*Pmax),   Pb = Pe + (1/eta-1)*max(Pe,0)
#                                            + (1-eta)*max(-Pe,0)
# The power capability fades smoothly to zero at the SOC limits, which
# reproduces the loss-of-support behaviour of a depleted battery.

def _bess_soc(Pe, SOC, p):
    Pb = Pe + (1 / p['eta'] - 1) * s_relu(Pe) + (1 - p['eta']) * s_relu(-Pe)
    fSOC = -Pb / (3600.0 * p['Eh'] * p['Pmax'])
    Pdis = p['Pmax'] * s_sig((SOC - p['SOCmin']) / p['dSOC'])   # discharge cap
    Pchg = p['Pmax'] * s_sig((p['SOCmax'] - SOC) / p['dSOC'])   # charge cap
    return fSOC, Pdis, Pchg


# -------------------------------------------------------------- BESS-GFM ---
# Grid-forming battery: THE virtual-inertia / primary-response asset of a
# low-inertia grid [Lasseter et al. 2020; NERC grid-forming guideline 2021].
# States: dg wg Qf | SOC
def bessgfm_init(case, i, prm=None):
    p = _p({**GFM_DEF, **BESS_DEF}, prm)
    if p['Pmax'] is None:
        p['Pmax'] = 1.5 * max(abs(case.Pg[i]), 0.1)
    st, _, auxg = gfm_init(case, i, {k: p[k] for k in GFM_DEF})
    x0 = np.concatenate([st, [p['SOC0']]])
    _, Pdis0, Pchg0 = _bess_soc(case.Pg[i], p['SOC0'], p)
    c0 = case.Pg[i] - s_clamp(case.Pg[i], -Pchg0, Pdis0)   # exact equilibrium
    fade0 = s_sig((p['SOC0'] - p['SOCmin']) / p['dSOC']) * \
        s_sig((p['SOCmax'] - p['SOC0']) / p['dSOC'])       # normalisation
    aux = dict(auxg, bess=p, c0=c0, fade0=fade0)
    return x0, np.array([]), aux


def bessgfm_f(xi, za, Vg, Thg, aux, prm, u):
    dg, wg, Qf, SOC = xi
    p = aux['bess']
    Pref = aux['Pset'] + u.get('dP', 0.0)
    f3, Pe, Qe = gfm_core(dg, wg, Qf, Vg, Thg, Pref, aux['Qset'], aux['Eset'],
                          aux['p'], aux['ws'])
    fSOC, Pdis, Pchg = _bess_soc(Pe, SOC, p)
    # capability limit acts on the swing power balance: BOTH the reference
    # and the droop authority fade as the SOC window closes, so a depleted
    # battery glides to zero ACTIVE power (it keeps regulating voltage — a
    # converter needs no energy to supply reactive power)
    fade = s_sig((SOC - p['SOCmin']) / p['dSOC']) * \
        s_sig((p['SOCmax'] - SOC) / p['dSOC']) / aux['fade0']
    Pref_lim = s_clamp(Pref, -Pchg, Pdis) + aux['c0']
    f3[1] = (aux['ws'] / (2 * aux['p']['Hv'])) * (
        fade * Pref_lim - Pe - fade * aux['p']['Dp'] * (wg / aux['ws'] - 1))
    return np.concatenate([f3, [fSOC]]), Pe, Qe, np.array([])


# -------------------------------------------------------------- BESS-GFL ---
# Grid-following battery with FAST FREQUENCY RESPONSE: droop on the PLL
# frequency estimate (with deadband) plus an optional RoCoF term, as required
# of storage IBRs by modern interconnection rules [IEEE Std 2800-2022;
# Kundur ch. 11 for the droop concept].
# States: thpll xpll id iq | SOC xw Pf
#     dxw/dt  = (dw_pll - xw)/Tw           (washout -> RoCoF estimate)
#     Pf* = -Kf*dead(dw_pll) - Kr*(dw_pll - xw)/Tw ,  dPf/dt = (Pf*-Pf)/Tf
def bessgfl_init(case, i, prm=None):
    p = _p({**GFL_DEF, **BESS_DEF}, prm)
    if p['Pmax'] is None:
        p['Pmax'] = 1.5 * max(abs(case.Pg[i]), 0.1)
    x0 = np.array([case.TH0[i], 0.0, case.Pg[i] / case.V0[i], -case.Qg[i] / case.V0[i],
                   p['SOC0'], 0.0, 0.0])
    _, Pdis0, Pchg0 = _bess_soc(case.Pg[i], p['SOC0'], p)
    c0 = case.Pg[i] - s_clamp(case.Pg[i], -Pchg0, Pdis0)   # exact equilibrium
    aux = dict(Pset=case.Pg[i], Qset=case.Qg[i], p=p, ws=case.ws, c0=c0,
               V0=case.V0[i], Ilim=_irate(case, i, p))
    return x0, np.array([]), aux


def bessgfl_f(xi, za, Vg, Thg, aux, prm, u):
    thp, xpll, idc, iqc, SOC, xw, Pf = xi
    p = aux['p']
    ws = aux['ws']
    phi = Thg - thp
    vq = Vg * np.sin(phi)
    dw = (xpll + p['Kp'] * vq) / ws          # PLL frequency deviation (pu)
    fxw = (dw - xw) / p['Tw']
    rocof = (dw - xw) / p['Tw']
    Pfr = -p['Kf'] * s_dead(dw, p['db']) - p['Kr'] * rocof
    fPf = (Pfr - Pf) / p['Tf']
    Pe = Vg * (idc * np.cos(phi) + iqc * np.sin(phi))
    fSOC, Pdis, Pchg = _bess_soc(Pe, SOC, p)
    Pbase = aux['Pset'] + u.get('dP', 0.0) + Pf          # dispatch + native FFR
    Pbase = p_support(Pbase, Vg, dw, aux['V0'], p)       # + Volt-Watt (Freq-Watt off by default)
    Pcmd = s_clamp(Pbase, -Pchg, Pdis) + aux['c0']
    Qref = q_support(Pcmd, aux['Pset'], aux['Qset'], Vg, aux['V0'], p)  # Volt-VAR / const-PF
    vd = max(Vg * np.cos(phi), 0.1)
    idr, iqr = _ilim(Pcmd / vd, -Qref / vd, aux['Ilim'])
    f4, Pinj, Qinj, _ = gfl_core(thp, xpll, idc, iqc, Vg, Thg, idr, iqr, p)
    return (np.concatenate([f4, [fSOC, fxw, fPf]]), Pinj, Qinj, np.array([]))


# ============================ WIND: SHARED BLOCKS ===========================
# Aerodynamics [Heier, Grid Integration of Wind Energy Conversion Systems]:
#     Cp(lambda, beta) = c1*(c2/li - c3*beta - c4)*exp(-c5/li) + c6*lambda
#     1/li = 1/(lambda + 0.08*beta) - 0.035/(beta^3 + 1)
# with the classical coefficients c = (0.5176, 116, 0.4, 5, 21, 0.0068)
# (Cpmax = 0.48 at lambda = 8.1, beta = 0).  Speeds and wind in pu of rated;
# lambda = lam_r * wt/vw so that lambda = lam_r at the MPPT locus.
# Turbine-pu mechanical power:  Pm = (Cp/Cpmax) * vw^3   (=1 at rated).

def wt_cp(lam, be, p):
    c1, c2, c3, c4, c5, c6 = p['c']
    li = 1.0 / (1.0 / (lam + 0.08 * be) - 0.035 / (be ** 3 + 1))
    return c1 * (c2 / li - c3 * be - c4) * np.exp(-c5 / li) + c6 * lam


def wt_pm(wt, vw, be, p):
    """Turbine-pu mechanical power at speed wt, wind vw, pitch be (deg)."""
    lam = p['lam_r'] * wt / vw
    return (wt_cp(lam, be, p) / p['Cpmax']) * vw ** 3


def _pitch_init(e0, p, Kaw=1.0):
    """Pitch PI + anti-windup equilibrium (fixed point of the smooth
    saturation): returns (be0, xp0, be_raw0) such that d(beta)/dt and
    d(xp)/dt are EXACTLY zero at speed error e0."""
    be_raw = (p['Kip'] / Kaw) * e0
    for _ in range(80):
        be = s_clamp(be_raw, 0.0, p['bmax'])
        be_raw = (p['Kip'] * e0 + Kaw * be) / Kaw
    be = s_clamp(be_raw, 0.0, p['bmax'])
    xp0 = be_raw - p['Kpp'] * e0
    return be, xp0, be_raw


def _wt_source_init(case, i, p):
    """Common Type-3/4 source-side initialisation at wind vw0 (MPPT below
    rated: wg = vw, lambda = lam_r, Pm_turbine = vw^3; pitch solves the
    aero balance above rated).  Returns dict of initial source states and
    scaling kS (system-pu per turbine-pu)."""
    vw0 = p['vw0']
    if vw0 <= 1.0:                       # below rated: on the MPPT locus
        wg0 = vw0
        Pn = vw0 ** 3
        e0 = wg0 - 1.0
        be0, xp0, _ = _pitch_init(e0, p)
    else:                                # above rated: pitch holds wg = 1
        wg0 = 1.0
        Pn = 1.0
        lo, hi = 0.0, p['bmax']
        for _ in range(80):              # bisection: Cp(lam_r/vw0, be) = Cpmax/vw0^3
            mid = 0.5 * (lo + hi)
            if wt_pm(1.0, vw0, mid, p) > 1.0:
                lo = mid
            else:
                hi = mid
        be0 = 0.5 * (lo + hi)
        xp0 = be0                        # PI unsaturated, e0 = 0
    Pn = wt_pm(wg0, vw0, be0, p)         # actual aero power at (wg0, be0)
    kS = case.Pg[i] / Pn                 # plant scale (system pu / turbine pu)
    Te0 = Pn / wg0
    ttw0 = Te0 / p['Ksh']
    # MPPT power-order lag with exact-equilibrium correction c0
    Pcl0 = s_min(p['kopt'] * wg0 ** 3, 1.0)
    cPo = Pn - Pcl0
    return dict(vw0=vw0, wg0=wg0, wt0=wg0, ttw0=ttw0, be0=be0, xp0=xp0,
                Po0=Pn, kS=kS, cPo=cPo)


def _wt_source_f(wt, wg, ttw, be, xp, Po, Te, vw, u_dP, p, src, ws, Kaw=1.0):
    """Common Type-3/4 source derivatives given generator-side torque Te
    (turbine pu).  Two-mass drivetrain [Ackermann, Wind Power in Power
    Systems, ch. 24; Kundur ch. 15 (torsional)]:
        2Ht dwt/dt = Tm - Tsh ,  dttw/dt = ws(wt - wg),
        Tsh = Ksh*ttw + Dsh*(wt - wg)          (2Hg dwg/dt = Tsh - Te
                                                handled by the caller).
    MPPT power order [Ackermann ch. 25]: Popt = kopt*wg^3 -> lag TPo.
    Pitch PI with anti-windup [Slootweg et al. 2003]."""
    Tm = wt_pm(wt, vw, be, p) / wt
    Tsh = p['Ksh'] * ttw + p['Dsh'] * (wt - wg)
    fwt = (Tm - Tsh) / (2 * p['Ht'])
    fttw = ws * (wt - wg)
    fwg = (Tsh - Te) / (2 * p['Hg'])
    e = wg - 1.0
    be_raw = p['Kpp'] * e + xp
    be_sat = s_clamp(be_raw, 0.0, p['bmax'])
    fbe = (be_sat - be) / p['Tp']
    fxp = p['Kip'] * e - Kaw * (be_raw - be)
    Pcl = s_min(p['kopt'] * wg ** 3, 1.0) + src['cPo']
    fPo = (Pcl - Po) / p['TPo']
    return Tm, Tsh, fwt, fwg, fttw, fbe, fxp, fPo


# ---------------------------------------------------------------- WT4-GFL --
# Type-4 (full-converter) wind turbine behind a grid-following converter
# [Ackermann ch. 25; Anaya-Lara et al., Wind Energy Generation: Modelling
# and Control].  The machine-side converter executes the MPPT power order
# (fast torque control), the grid-side converter exports it via GFL current
# control; the rotor is therefore DECOUPLED from grid frequency — unless the
# optional synthetic-inertia loop (washout on the PLL frequency) is enabled
# [Morren et al. 2006; ENTSO-E/Hydro-Quebec practice].
# States: thpll xpll id iq | wt wg ttw | be xp | Po | xw Psi
def wt4gfl_init(case, i, prm=None):
    p = _p({**GFL_DEF, **WT4_DEF}, prm)
    src = _wt_source_init(case, i, p)
    x0 = np.array([case.TH0[i], 0.0, case.Pg[i] / case.V0[i], -case.Qg[i] / case.V0[i],
                   src['wt0'], src['wg0'], src['ttw0'], src['be0'], src['xp0'],
                   src['Po0'], 0.0, 0.0])
    aux = dict(Pset=case.Pg[i], Qset=case.Qg[i], p=p, ws=case.ws, src=src,
               Ilim=_irate(case, i, p))
    return x0, np.array([]), aux


def wt4gfl_f(xi, za, Vg, Thg, aux, prm, u):
    thp, xpll, idc, iqc, wt, wg, ttw, be, xp, Po, xw, Psi = xi
    p = aux['p']
    ws = aux['ws']
    src = aux['src']
    vw = u.get('vw', None)
    vw = src['vw0'] if vw is None else vw
    # synthetic inertia: extra power ordered from rotor kinetic energy in
    # proportion to the measured RoCoF (0 when disabled: Ksi = 0)
    phi = Thg - thp
    dw = (xpll + p['Kp'] * Vg * np.sin(phi)) / ws
    fxw = (dw - xw) / p['Tsi']
    rocof = (dw - xw) / p['Tsi']
    Psi_ref = -p['Ksi'] * rocof if p['syn_in'] else 0.0
    fPsi = (Psi_ref - Psi) / 0.2
    Te = (Po + Psi) / wg                       # machine-side torque execution
    Tm, Tsh, fwt, fwg, fttw, fbe, fxp, fPo = _wt_source_f(
        wt, wg, ttw, be, xp, Po, Te, vw, 0.0, p, src, ws)
    # grid side exports the ordered power (+ any set-point disturbance)
    Pcmd = src['kS'] * (Po + Psi) + u.get('dP', 0.0)
    vd = max(Vg * np.cos(phi), 0.1)
    idr, iqr = _ilim(Pcmd / vd, -aux['Qset'] / vd, aux['Ilim'])
    f4, Pinj, Qinj, _ = gfl_core(thp, xpll, idc, iqc, Vg, Thg, idr, iqr, p)
    return (np.concatenate([f4, [fwt, fwg, fttw, fbe, fxp, fPo, fxw, fPsi]]),
            Pinj, Qinj, np.array([]))


# ---------------------------------------------------------------- WT4-GFM --
# Same turbine behind a GRID-FORMING converter: the converter swing draws its
# power imbalance from the rotor, so the wind turbine's stored kinetic energy
# provides REAL inertia to the grid (at the cost of a speed excursion and an
# MPPT recovery) [Anaya-Lara; NREL grid-forming roadmap 2020].
# States: dg wgc Qf | wt wg ttw | be xp | Po
def wt4gfm_init(case, i, prm=None):
    p = _p({**GFM_DEF, **WT4_DEF}, prm)
    src = _wt_source_init(case, i, p)
    st, _, auxg = gfm_init(case, i, {k: p[k] for k in GFM_DEF})
    x0 = np.concatenate([st, [src['wt0'], src['wg0'], src['ttw0'],
                              src['be0'], src['xp0'], src['Po0']]])
    aux = dict(auxg, wt=p, src=src)
    return x0, np.array([]), aux


def wt4gfm_f(xi, za, Vg, Thg, aux, prm, u):
    dg, wgc, Qf, wt, wg, ttw, be, xp, Po = xi
    p = aux['wt']
    ws = aux['ws']
    src = aux['src']
    vw = u.get('vw', None)
    vw = src['vw0'] if vw is None else vw
    Pref = src['kS'] * Po + u.get('dP', 0.0)   # droop reference follows MPPT
    f3, Pe, Qe = gfm_core(dg, wgc, Qf, Vg, Thg, Pref, aux['Qset'], aux['Eset'],
                          aux['p'], ws)
    Te = (Pe / src['kS']) / wg                 # grid power drawn from the rotor
    Tm, Tsh, fwt, fwg, fttw, fbe, fxp, fPo = _wt_source_f(
        wt, wg, ttw, be, xp, Po, Te, vw, 0.0, p, src, ws)
    return (np.concatenate([f3, [fwt, fwg, fttw, fbe, fxp, fPo]]),
            Pe, Qe, np.array([]))


# ============================ INDUCTION-MACHINE WIND ========================
# Third-order (transient, 'voltage behind transient reactance') induction-
# machine model in the synchronously-rotating network frame, stator
# transients neglected [Krause; Kundur sec. 7.4 (induction machines);
# Anaya-Lara et al. ch. 2; Holdsworth et al. 2003]:
#     X   = Xls + Xm                 (open-circuit reactance)
#     X'  = Xls + Xm*Xlr/(Xm + Xlr)  (transient reactance)
#     T0' = (Xlr + Xm)/(ws*Rr)       (rotor open-circuit time constant)
# Generator convention (Ids, Iqs delivered to the network):
#     stator:  Vd = Ed' - Rs*Ids + X'*Iqs
#              Vq = Eq' - Rs*Iqs - X'*Ids
#     rotor:   dEd'/dt =  s*ws*Eq' - (Ed' - (X - X')*Iqs)/T0' - ws*(Xm/Xrr)*vqr
#              dEq'/dt = -s*ws*Ed' - (Eq' + (X - X')*Ids)/T0' + ws*(Xm/Xrr)*vdr
#     (derived from the space-phasor rotor equation
#      dE'/dt = -js*ws*E' - (E' - j(X-X')*i_s,motor)/T0' + jws*(Xm/Xrr)*vr
#      with the GENERATOR current I = -i_s,motor)
#     torque:  Te = Ed'*Ids + Eq'*Iqs      (air-gap power, pu, ws = 1 pu)
# For the squirrel-cage machine (Types 1-2) vdr = vqr = 0; the DFIG (Type 3)
# rotor-side converter imposes (vdr, vqr).

def _im_derived(p, scale):
    """Electrical machine constants converted from the machine MVA base to
    the system base (impedances / scale, scale = machine MVA in system pu),
    plus derived reactances.  The DRIVETRAIN stays in turbine per-unit
    (`Ht, Hg, Ksh, Dsh` used as given); torques are converted with the
    mechanical scale kSm at the interface."""
    q = dict(p)
    for k in ('Rs', 'Xls', 'Xm', 'Rr', 'Xlr'):
        q[k] = p[k] / scale
    q['X'] = q['Xls'] + q['Xm']
    q['Xp'] = q['Xls'] + q['Xm'] * q['Xlr'] / (q['Xm'] + q['Xlr'])
    q['Xrr'] = q['Xm'] + q['Xlr']
    return q


def _im_stator(Ed, Eq, Ids, Iqs, Vg, Thg, q):
    """Stator algebraic residuals and terminal P, Q (generator convention),
    with the network voltage resolved in the synchronous frame:
    Vd = V*cos(theta), Vq = V*sin(theta)."""
    Vd = Vg * np.cos(Thg)
    Vq = Vg * np.sin(Thg)
    g1 = Ed - q['Rs'] * Ids + q['Xp'] * Iqs - Vd
    g2 = Eq - q['Rs'] * Iqs - q['Xp'] * Ids - Vq
    P = Vd * Ids + Vq * Iqs
    Q = Vq * Ids - Vd * Iqs
    return g1, g2, P, Q


def _im_ss_solve(case, i, q, Pg_target, smin=-0.2, smax=-1e-5):
    """Steady-state slip and currents of the squirrel-cage machine from the
    classical equivalent circuit [Kundur sec. 7.2], such that the machine
    DELIVERS Pg_target at the bus voltage.  Returns (s0, im) with im the
    stator current phasor in generator convention."""
    Vb = case.V0[i] * np.exp(1j * case.TH0[i])
    Zs = q['Rs'] + 1j * q['Xls']
    Zm = 1j * q['Xm']

    def Pdel(s):
        Zr = q['Rr'] / s + 1j * q['Xlr']
        Zin = Zs + Zm * Zr / (Zm + Zr)
        imot = Vb / Zin                       # motor-convention stator current
        return -np.real(Vb * np.conj(imot))   # delivered = -absorbed

    lo, hi = smin, smax
    for _ in range(90):                       # bisection (Pdel monotone in s here)
        mid = 0.5 * (lo + hi)
        if Pdel(mid) > Pg_target:
            lo = mid
        else:
            hi = mid
    s0 = 0.5 * (lo + hi)
    Zr = q['Rr'] / s0 + 1j * q['Xlr']
    Zin = Zs + Zm * Zr / (Zm + Zr)
    imot = Vb / Zin
    return s0, -imot                          # generator convention


def _im_E_from_alg(Ids, Iqs, Vg, Thg, q):
    """E' that satisfies the stator equations for given currents/voltage."""
    Vd = Vg * np.cos(Thg)
    Vq = Vg * np.sin(Thg)
    Ed = Vd + q['Rs'] * Ids - q['Xp'] * Iqs
    Eq = Vq + q['Rs'] * Iqs + q['Xp'] * Ids
    return Ed, Eq


# ------------------------------------------------------------------- WT1 ---
# Type-1 fixed-speed wind turbine: squirrel-cage induction generator directly
# coupled to the grid, two-mass shaft, fixed pitch, PLUS the shunt
# compensation capacitor that such wind farms carry for their reactive
# consumption [Ackermann ch. 24; Holdsworth et al. 2003].
# States: Edp Eqp s | wt ttw     Algebraic: Ids Iqs
def wt1_init(case, i, prm=None):
    p = _p(WT1_DEF, prm)
    scale = p.get('Smach') or max(abs(case.Pg[i]) / 0.9, 0.1)  # plant MVA (system pu)
    q = _im_derived(p, scale)
    s0, iph = _im_ss_solve(case, i, q, case.Pg[i])
    Ids0, Iqs0 = iph.real, iph.imag
    Ed0, Eq0 = _im_E_from_alg(Ids0, Iqs0, case.V0[i], case.TH0[i], q)
    Te0 = Ed0 * Ids0 + Eq0 * Iqs0            # system-pu air-gap torque
    wr0 = 1.0 - s0
    wt0 = wr0
    # aero: mechanical scale kSm makes the turbine torque balance EXACT at
    # the operating point (fixed speed, beta = 0, wind vw0)
    lam0 = p['lam_r'] * wt0 / p['vw0']
    Pm_t = (wt_cp(lam0, 0.0, p) / p['Cpmax']) * p['vw0'] ** 3
    kSm = (Te0 * wt0) / Pm_t                 # system-pu-mech per turbine-pu
    ttw0 = (Te0 / kSm) / p['Ksh']            # turbine-pu shaft twist
    # reactive compensation: capacitor supplies the machine's Q consumption
    # plus whatever net Q the load flow assigned to this bus
    _, _, P0, Q0 = _im_stator(Ed0, Eq0, Ids0, Iqs0, case.V0[i], case.TH0[i], q)
    Bcap = (case.Qg[i] - Q0) / case.V0[i] ** 2
    x0 = np.array([Ed0, Eq0, s0, wt0, ttw0])
    aux = dict(q=q, p=p, ws=case.ws, Bcap=Bcap, kSm=kSm, vw0=p['vw0'],
               V0=case.V0[i])
    return x0, np.array([Ids0, Iqs0]), aux


def _wt1_body(Ed, Eq, s, wt, ttw, Ids, Iqs, Vg, Thg, aux, vw, vdr=0.0, vqr=0.0,
              Rr_eff=None):
    """Shared Type-1/2 dynamics; Rr_eff allows the Type-2 external rotor
    resistance.  Returns (f5, galg2, P, Q)."""
    q = dict(aux['q'])
    ws = aux['ws']
    if Rr_eff is not None:
        q['Rr'] = Rr_eff
    T0p = q['Xrr'] / (ws * q['Rr'])
    g1, g2, P, Q = _im_stator(Ed, Eq, Ids, Iqs, Vg, Thg, q)
    fEd = s * ws * Eq - (Ed - (q['X'] - q['Xp']) * Iqs) / T0p - ws * (q['Xm'] / q['Xrr']) * vqr
    fEq = -s * ws * Ed - (Eq + (q['X'] - q['Xp']) * Ids) / T0p + ws * (q['Xm'] / q['Xrr']) * vdr
    Te_t = (Ed * Ids + Eq * Iqs) / aux['kSm']  # air-gap torque, turbine pu
    wr = 1.0 - s
    p = aux['p']
    lam = p['lam_r'] * wt / vw
    Tm = (wt_cp(lam, 0.0, p) / p['Cpmax']) * vw ** 3 / wt   # turbine pu
    Tsh = p['Ksh'] * ttw + p['Dsh'] * (wt - wr)
    fwt = (Tm - Tsh) / (2 * p['Ht'])
    fttw = ws * (wt - wr)
    fs = -(Tsh - Te_t) / (2 * p['Hg'])        # ds/dt = -dwr/dt (turbine pu)
    return np.array([fEd, fEq, fs, fwt, fttw]), np.array([g1, g2]), P, Q


def wt1_f(xi, za, Vg, Thg, aux, prm, u):
    Ed, Eq, s, wt, ttw = xi
    Ids, Iqs = za
    vw = u.get('vw', None)
    vw = aux['vw0'] if vw is None else vw
    f5, g2, P, Q = _wt1_body(Ed, Eq, s, wt, ttw, Ids, Iqs, Vg, Thg, aux, vw)
    Qcap = aux['Bcap'] * Vg ** 2              # shunt compensation capacitor
    return f5, P, Q + Qcap, g2


# ------------------------------------------------------------------- WT2 ---
# Type-2: Type-1 plus a controlled EXTERNAL rotor resistance (e.g. Vestas
# OptiSlip) that smooths power above rating [Ackermann ch. 24].
# States: Edp Eqp s | wt ttw | xR       Algebraic: Ids Iqs
def wt2_init(case, i, prm=None):
    p = _p(WT2_DEF, prm)
    x0, alg0, aux = wt1_init(case, i, {k: v for k, v in p.items()
                                       if k not in ('Rext_max', 'KpR', 'KiR')})
    aux['p2'] = p
    aux['Prate'] = None                       # set below from operating point
    # operate below the smoothing threshold: Rext = 0, PI parked by
    # anti-windup exactly as the pitch loop (fixed point)
    Ids0, Iqs0 = alg0
    Ed0, Eq0 = x0[0], x0[1]
    _, _, P0, _ = _im_stator(Ed0, Eq0, Ids0, Iqs0, case.V0[i], case.TH0[i], aux['q'])
    aux['Prate'] = P0 / 0.9                   # rating 10% above the dispatch
    e0 = P0 - aux['Prate']                    # negative -> resistance inactive
    Kaw = 1.0
    xr = (p['KiR'] / Kaw) * e0
    for _ in range(80):
        R = s_clamp(xr, 0.0, p['Rext_max'] / max(aux['q']['Rr'], 1e-6))
        xr = (p['KiR'] * e0 + Kaw * R) / Kaw
    aux['xR0'] = xr
    # exact-equilibrium correction: the smooth clamp's tiny tail at xr0 is
    # subtracted so Rext is EXACTLY zero at the operating point
    aux['cR0'] = s_clamp(xr, 0.0, p['Rext_max'] / max(aux['q']['Rr'], 1e-6))
    return np.concatenate([x0, [xr]]), alg0, aux


def wt2_f(xi, za, Vg, Thg, aux, prm, u):
    Ed, Eq, s, wt, ttw, xR = xi
    Ids, Iqs = za
    p2 = aux['p2']
    vw = u.get('vw', None)
    vw = aux['vw0'] if vw is None else vw
    q = aux['q']
    Rmax_rel = p2['Rext_max'] / max(q['Rr'], 1e-6)
    Rrel = s_clamp(xR, 0.0, Rmax_rel) - aux['cR0']   # Rext as multiple of Rr
    Rr_eff = q['Rr'] * (1.0 + Rrel)
    f5, g2, P, Q = _wt1_body(Ed, Eq, s, wt, ttw, Ids, Iqs, Vg, Thg, aux, vw,
                             Rr_eff=Rr_eff)
    e = P - aux['Prate']                      # power-smoothing error
    fxR = p2['KiR'] * e - 1.0 * (xR - (Rrel + aux['cR0']))   # PI + anti-windup
    Qcap = aux['Bcap'] * Vg ** 2
    return np.concatenate([f5, [fxR]]), P, Q + Qcap, g2


# ------------------------------------------------------------------- WT3 ---
# Type-3 doubly-fed induction generator: the rotor-side converter imposes
# (vdr, vqr) through PI loops on total-power (torque/MPPT) and reactive-power
# errors; the grid-side converter exports the rotor power -s*Ps at unity
# power factor, so  P_total = Ps*(1 - s)  [Ekanayake et al. 2003; Holdsworth
# et al. 2003; Anaya-Lara et al. ch. 4].
# States: Edp Eqp s | wt ttw | xP xQ | be xp Po      Algebraic: Ids Iqs
def wt3_init(case, i, prm=None):
    p = _p(WT3_DEF, prm)
    scale = p.get('Smach') or max(abs(case.Pg[i]) / 0.9, 0.1)
    q = _im_derived(p, scale)
    ws = case.ws
    src = _wt_source_init(case, i, p)         # MPPT/pitch operating point
    wr0 = src['wg0']
    s0 = 1.0 - wr0
    # stator dispatch: P_total = Ps*(1-s0) (lossless back-to-back converter)
    Ps0 = case.Pg[i] / (1.0 - s0)
    Qs0 = case.Qg[i]                          # GSC at unity power factor
    Vb = case.V0[i] * np.exp(1j * case.TH0[i])
    iph = np.conj((Ps0 + 1j * Qs0) / Vb)      # generator-convention stator current
    Ids0, Iqs0 = iph.real, iph.imag
    Ed0, Eq0 = _im_E_from_alg(Ids0, Iqs0, case.V0[i], case.TH0[i], q)
    # rotor voltage that freezes the E' dynamics at this operating point
    T0p = q['Xrr'] / (ws * q['Rr'])
    kr = ws * q['Xm'] / q['Xrr']
    vqr0 = (s0 * ws * Eq0 - (Ed0 - (q['X'] - q['Xp']) * Iqs0) / T0p) / kr
    vdr0 = ((Eq0 + (q['X'] - q['Xp']) * Ids0) / T0p + s0 * ws * Ed0) / kr
    # the PI loops act in the TERMINAL-VOLTAGE-ORIENTED frame (vector
    # control): rotate the network-frame rotor voltage back to that frame
    vrc0 = (vdr0 + 1j * vqr0) * np.exp(-1j * case.TH0[i])
    # mechanical scale: air-gap torque (system pu) <-> turbine-pu torque,
    # chosen so the shaft balance is exact at the operating point
    Te0 = Ed0 * Ids0 + Eq0 * Iqs0
    kSm = Te0 * wr0 / src['Po0']
    # xP: active-power (MPPT) loop integrator -> d-axis rotor voltage
    # xQ: reactive-power loop integrator     -> q-axis rotor voltage
    x0 = np.array([Ed0, Eq0, s0, src['wt0'], src['ttw0'], vrc0.real, vrc0.imag,
                   src['be0'], src['xp0'], src['Po0']])
    aux = dict(q=q, p=p, ws=ws, src=src, kSm=kSm, Pset=case.Pg[i], Qset=Qs0,
               V0=case.V0[i])
    return x0, np.array([Ids0, Iqs0]), aux


def wt3_f(xi, za, Vg, Thg, aux, prm, u):
    Ed, Eq, s, wt, ttw, xP, xQ, be, xp, Po = xi
    Ids, Iqs = za
    q = aux['q']
    p = aux['p']
    ws = aux['ws']
    src = aux['src']
    vw = u.get('vw', None)
    vw = src['vw0'] if vw is None else vw
    T0p = q['Xrr'] / (ws * q['Rr'])
    kr = ws * q['Xm'] / q['Xrr']
    g1, g2, Ps, Qs = _im_stator(Ed, Eq, Ids, Iqs, Vg, Thg, q)
    Ptot = Ps * (1.0 - s)                     # stator + rotor(GSC) power
    # --- rotor-side converter PI loops (current-mode simplification) ---
    #     q-axis: track the MPPT power order      d(xT)/dt = KiT*(P* - P)
    #     d-axis: hold the reactive dispatch      d(xV)/dt = KiV*(Q* - Q)
    Pord = src['kS'] * Po + u.get('dP', 0.0)
    eP = Pord - Ptot
    eQ = aux['Qset'] - Qs
    # vector control in the TERMINAL-VOLTAGE-ORIENTED frame [Anaya-Lara
    # ch. 4]: the PI outputs are rotated to the network frame with the bus
    # angle so the loop pairing is independent of the operating point.  In
    # this frame the stator flux lies on the negative q-axis, hence the
    # d-axis rotor voltage drives torque/P and the q-axis drives Q with
    # inverted sense:
    vdr_c = xP + p['KpT'] * eP
    vqr_c = xQ - p['KpV'] * eQ
    vr = (vdr_c + 1j * vqr_c) * np.exp(1j * Thg)
    vdr, vqr = vr.real, vr.imag
    fxP = p['KiT'] * eP
    fxQ = -p['KiV'] * eQ
    # --- induction-machine rotor dynamics (see model header above) ---
    fEd = s * ws * Eq - (Ed - (q['X'] - q['Xp']) * Iqs) / T0p - kr * vqr
    fEq = -s * ws * Ed - (Eq + (q['X'] - q['Xp']) * Ids) / T0p + kr * vdr
    Te = Ed * Ids + Eq * Iqs
    # --- drivetrain / pitch / MPPT (shared Type-3/4 source block, turbine pu;
    #     the air-gap torque enters through the mechanical scale kSm) ---
    Tm, Tsh, fwt, fwg, fttw, fbe, fxp, fPo = _wt_source_f(
        wt, 1.0 - s, ttw, be, xp, Po, Te / aux['kSm'], vw, 0.0, p, src, ws)
    fs = -fwg
    return (np.array([fEd, fEq, fs, fwt, fttw, fxP, fxQ, fbe, fxp, fPo]),
            Ptot, Qs, np.array([g1, g2]))


# ============================ REGISTRY ======================================
# tag -> (n_diff_states, n_unit_algebraic, init_fn, f_fn, state name stubs)
REGISTRY = {
    'SG':  (11, 2, sg_init, sg_f,
            ['Eqp', 'Si1d', 'Edp', 'Si2q', 'delta', 'omega', 'Efd', 'RF', 'VR', 'TM', 'PSV']),
    'SG6': (6, 2, sg6_init, sg6_f, ['Eqp', 'delta', 'omega', 'Efd', 'RF', 'VR']),
    'SG6G': (8, 2, sg6g_init, sg6g_f,
             ['Eqp', 'delta', 'omega', 'Efd', 'RF', 'VR', 'TM', 'PSV']),
    'SG4': (4, 2, sg4_init, sg4_f, ['Eqp', 'Edp', 'delta', 'omega']),
    'SG4G': (6, 2, sg4g_init, sg4g_f, ['Eqp', 'Edp', 'delta', 'omega', 'TM', 'PSV']),
    'SG2': (2, 2, sg2_init, sg2_f, ['delta', 'omega']),
    'SGP': (14, 2, sgp_init, sgp_f,
            ['Eqp', 'Si1d', 'Edp', 'Si2q', 'delta', 'omega', 'Efd', 'RF', 'VR',
             'TM', 'PSV', 'Vw', 'V1', 'V2']),
    'SG6P': (9, 2, sg6p_init, sg6p_f,
             ['Eqp', 'delta', 'omega', 'Efd', 'RF', 'VR', 'Vw', 'V1', 'V2']),
    'SGF': (13, 2, sgf_init, sgf_f,
            ['Eqp', 'Si1d', 'Edp', 'Si2q', 'delta', 'omega', 'Efd', 'RF', 'VR',
             'TM', 'PSV', 'Vw', 'Xd']),
    'GFM': (3, 0, gfm_init, gfm_f, ['dg', 'wg', 'Qf']),
    'GFL': (4, 0, gfl_init, gfl_f, ['thpll', 'xpll', 'id', 'iq']),
    'PV-GFL': (7, 0, pvgfl_init, pvgfl_f,
               ['thpll', 'xpll', 'id', 'iq', 'Vdc', 'xdc', 'vref']),
    'PV-GFM': (4, 0, pvgfm_init, pvgfm_f, ['dg', 'wg', 'Qf', 'Pav']),
    'BESS-GFM': (4, 0, bessgfm_init, bessgfm_f, ['dg', 'wg', 'Qf', 'SOC']),
    'BESS-GFL': (7, 0, bessgfl_init, bessgfl_f,
                 ['thpll', 'xpll', 'id', 'iq', 'SOC', 'xw', 'Pf']),
    'WT4-GFL': (12, 0, wt4gfl_init, wt4gfl_f,
                ['thpll', 'xpll', 'id', 'iq', 'wt', 'wg', 'ttw', 'beta', 'xp',
                 'Po', 'xw', 'Psi']),
    'WT4-GFM': (9, 0, wt4gfm_init, wt4gfm_f,
                ['dg', 'wgc', 'Qf', 'wt', 'wg', 'ttw', 'beta', 'xp', 'Po']),
    'WT3': (10, 2, wt3_init, wt3_f,
            ['Edp', 'Eqp', 'slip', 'wt', 'ttw', 'xP', 'xQ', 'beta', 'xp', 'Po']),
    'WT1': (5, 2, wt1_init, wt1_f, ['Edp', 'Eqp', 'slip', 'wt', 'ttw']),
    'WT2': (6, 2, wt2_init, wt2_f, ['Edp', 'Eqp', 'slip', 'wt', 'ttw', 'xR']),
}


def register(tag, ns, na, init_fn, f_fn, names):
    REGISTRY[tag] = (ns, na, init_fn, f_fn, names)
