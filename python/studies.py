"""
studies.py — the scenario runner: every named study reproduces one
educational experiment (and its figure) with a single call.

    import studies
    studies.run('pv_cloud')            # or: python3 run_scenario.py pv_cloud
    studies.run('all', outdir='figs')

Scenarios:
  validate     base-case validation table across the three test systems
  pv_cloud     cloud transient over a PV plant: GFL-PV vs curtailed GFM-PV
  wind_types   the SAME wind gust hitting a Type-1, Type-3 and Type-4 turbine
  bess_inertia GFM battery virtual inertia: Hv sweep + SOC-depletion collapse
  ffr          GFL battery fast-frequency response: droop-gain sweep
  pod          Kundur inter-area POD on a GFM battery: design + verification
  penetration  9-bus renewable-displacement paths: GFL route vs GFM route
  syn_inertia  Type-4 synthetic inertia: support and the recovery dip
  mix68        68-bus NETS wind/PV/BESS displacement: inter-area damping
"""
import os
import numpy as np
import figstyle as FS
import matplotlib.pyplot as plt
import cases
from system import System
from linearize import linearize, modes
from simulate import simulate, cloud_profile, gust_profile
import design as D


def _save(fig, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name)
    fig.savefig(p, bbox_inches='tight')
    plt.close(fig)
    print(f"  figure -> {p}")
    return p


# ============================================================== validate ==
def sc_validate(outdir):
    """Base-case validation across the three systems (prints a table)."""
    print("system            mode            this toolbox        reference")
    c9 = cases.ieee9()
    R = linearize(System(c9, ['SG'] * 3))
    lam = R['ev']
    ia = lam[np.argmin(np.abs(lam - (-0.6512 + 9.0749j)))]
    print(f"IEEE 9-bus        inter-area      {ia.real:.4f}{ia.imag:+.4f}j   -0.65117+9.0749j [OAJPE'20]")
    lo = lam[np.argmin(np.abs(lam - (-1.1563 + 14.9046j)))]
    print(f"IEEE 9-bus        local           {lo.real:.4f}{lo.imag:+.4f}j   -1.15629+14.9046j [OAJPE'20]")
    ck = cases.kundur2a()
    R = linearize(System(ck, ['SG'] * 4))
    o = sorted([(-l.real / abs(l) * 100, l.imag / 2 / np.pi) for l in R['ev']
                if 0.3 < l.imag / 2 / np.pi < 0.9])[0]
    print(f"Kundur two-area   inter-area      {o[1]:.3f} Hz / {o[0]:.2f}%      ~0.64 Hz lightly damped [Kundur ex.12.6]")
    c68 = cases.ne68()
    R = linearize(System(c68, ['SG'] * 16))
    o = sorted([(-l.real / abs(l) * 100, l.imag / 2 / np.pi) for l in R['ev']
                if 0.1 < l.imag / 2 / np.pi < 1.4])[0]
    print(f"68-bus NETS-NYPS  critical mode   {o[1]:.3f} Hz / {o[0]:.2f}%      inter-area band 0.4-1.3 Hz [Rogers; Pal]")
    return {}


# ============================================================== pv_cloud ==
def sc_pv_cloud(outdir):
    """Cloud transient: GFL PV loses everything the sun loses; curtailed
    GFM PV rides part of it through its headroom."""
    c9 = cases.ieee9()
    prof = {2: cloud_profile(2.0, depth=0.6, tdown=2, tlow=6, tup=3)}
    out = {}
    for tag in ('PV-GFL', 'PV-GFM'):
        s = System(c9, ['SG', 'SG', tag])
        T, X, Z = simulate(s, tsim=18.0, dt=2e-3, G_prof=prof)
        out[tag] = (s, T, X, Z)
    fig, ax = plt.subplots(2, 1, figsize=(6.6, 5.6), sharex=True)
    G = [prof[2](t) for t in out['PV-GFL'][1]]
    ax[0].plot(out['PV-GFL'][1], G, color=FS.GRY, ls='--', label='irradiance $G$ (pu)')
    for tag, col in (('PV-GFL', FS.C_GFL), ('PV-GFM', FS.C_GFM)):
        s, T, X, Z = out[tag]
        fc = s.coi_freq(X)
        ax[1].plot(T, fc, color=col, label=tag)
        if tag == 'PV-GFL':
            Vdc = s.unit_state(X, 2, 'Vdc')
            ax[0].plot(T, Vdc, color=FS.C_PV, label='DC-link $V_{dc}$ (pu, GFL)')
    ax[0].set_ylabel('pu'); ax[0].legend(loc='lower right', fontsize=9)
    ax[1].set_ylabel('COI frequency (Hz)'); ax[1].set_xlabel('Time (s)')
    ax[1].legend(fontsize=9)
    ax[0].set_title('Cloud transient over the bus-3 PV plant (source-side disturbance)')
    _save(fig, outdir, 'sc_pv_cloud.png')
    for tag in out:
        s, T, X, Z = out[tag]
        print(f"  {tag}: frequency nadir {s.coi_freq(X).min():.3f} Hz")
    return out


# ============================================================ wind_types ==
def sc_wind_types(outdir):
    """The SAME IEC gust hits a Type-1, Type-3 and Type-4 turbine at bus 3:
    fixed-speed passes the gust straight to the grid; the DFIG and the
    full-converter machine buffer it in the rotor."""
    c9 = cases.ieee9()
    out = {}
    for tag in ('WT1', 'WT3', 'WT4-GFL'):
        s = System(c9, ['SG', 'SG', tag])
        prof = {2: gust_profile(2.0, A=0.15, T=10.5, base=0.9)}
        T, X, Z = simulate(s, tsim=16.0, dt=2e-3, vw_prof=prof)
        V = Z[:, s.Vsl]
        TH = Z[:, s.THsl]
        # electrical power injected at bus 3 (recompute from states)
        # plant output from the network side: P_inj = P_load + P_into_network
        P = np.zeros(len(T))
        for a in range(len(T)):
            Vc = V[a] * np.exp(1j * TH[a])
            P[a] = (Vc * np.conj(s.case.Ybus @ Vc))[2].real + s.case.Pd[2]
        out[tag] = (s, T, X, P)
    fig, ax = plt.subplots(2, 1, figsize=(6.6, 5.6), sharex=True)
    tgrid = out['WT1'][1]
    vw = [gust_profile(2.0, A=0.15, T=10.5, base=0.9)(t) for t in tgrid]
    ax[0].plot(tgrid, vw, color=FS.GRY, ls='--')
    ax[0].set_ylabel('wind speed (pu)')
    ax[0].set_title('IEC extreme operating gust, +15% at 0.9 pu wind')
    cols = {'WT1': FS.C_GFL, 'WT3': FS.C_WT, 'WT4-GFL': FS.C_GFM}
    for tag in out:
        s, T, X, P = out[tag]
        ax[1].plot(T, P * 100, color=cols[tag],
                   label={'WT1': 'Type-1 (fixed speed)',
                          'WT3': 'Type-3 (DFIG)',
                          'WT4-GFL': 'Type-4 (full converter)'}[tag])
    ax[1].set_ylabel('plant output (MW)'); ax[1].set_xlabel('Time (s)')
    ax[1].legend(fontsize=9)
    _save(fig, outdir, 'sc_wind_types.png')
    for tag in out:
        s, T, X, P = out[tag]
        print(f"  {tag:8s}: output swing {100*(P.max()-P.min()):.1f} MW")
    return out


# ========================================================== bess_inertia ==
def sc_bess_inertia(outdir):
    """GFM battery: (a) virtual inertia Hv sweep on the load-step response;
    (b) SOC depletion — an under-sized battery loses the droop share."""
    c9 = cases.ieee9()
    fig, ax = plt.subplots(2, 1, figsize=(6.6, 5.8), sharex=False)
    for Hv, col in ((2, '#c7b8e0'), (5, FS.C_ALL), (10, '#4a235a')):
        s = System(c9, ['SG', 'BESS-GFM', 'BESS-GFM'],
                   [None, dict(Hv=Hv), dict(Hv=Hv)])
        T, X, Z = simulate(s, tsim=12.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
        fc = s.coi_freq(X)
        ax[0].plot(T, fc, color=col, label=f'$H_v$ = {Hv} s')
        i0 = np.searchsorted(T, 1.05)
        i1 = np.searchsorted(T, 1.30)
        rocof = (fc[i1] - fc[i0]) / (T[i1] - T[i0])
        print(f"  Hv={Hv:2d}: RoCoF {rocof:+.3f} Hz/s   nadir {fc[T>=1].min():.3f} Hz"
              "   (virtual inertia sets the slope; droop sets the nadir)")
    ax[0].legend(fontsize=9); ax[0].set_ylabel('COI frequency (Hz)')
    ax[0].set_title('(a) virtual-inertia sweep — 15 MW load step')
    ax[0].set_xlabel('Time (s)')
    # SOC depletion: a battery with seconds of storage runs dry mid-event
    s = System(c9, ['SG', 'SG', 'BESS-GFM'],
               [None, None, dict(Eh=0.004, SOC0=0.16, SOCmin=0.10, dSOC=0.02)])
    T, X, Z = simulate(s, tsim=25.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
    soc = s.unit_state(X, 2, 'SOC')
    ax2 = ax[1].twinx()
    ax[1].plot(T, s.coi_freq(X), color=FS.C_BESS, label='COI frequency')
    ax2.plot(T, 100 * soc, color=FS.GRY, ls='--', label='SOC')
    ax2.axhline(10, color=FS.C_GFL, lw=0.8, ls=':')
    ax2.set_ylabel('state of charge (%)')
    ax[1].set_ylabel('COI frequency (Hz)'); ax[1].set_xlabel('Time (s)')
    ax[1].set_title('(b) SOC depletion: support collapses at SOC$_{min}$')
    h1, l1 = ax[1].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax[1].legend(h1 + h2, l1 + l2, fontsize=9, loc='center right')
    fig.tight_layout()
    _save(fig, outdir, 'sc_bess_inertia.png')
    print(f"  depletion case: SOC {100*soc[0]:.0f}% -> {100*soc[-1]:.0f}%, "
          f"end frequency {s.coi_freq(X)[-1]:.3f} Hz")
    return {}


# ==================================================================== ffr ==
def sc_ffr(outdir):
    """GFL battery fast-frequency response: droop-gain sweep of the nadir."""
    c9 = cases.ieee9()
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    nads = []
    for Kf, col in ((0, FS.C_GFL), (10, '#d98880'), (25, FS.C_BESS), (50, '#6e2c00')):
        s = System(c9, ['SG', 'BESS-GFL', 'GFL'], [None, dict(Kf=Kf), None])
        T, X, Z = simulate(s, tsim=12.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
        fc = s.coi_freq(X)
        nads.append((Kf, fc[T >= 1].min()))
        ax.plot(T, fc, color=col, label=f'$K_f$ = {Kf}')
        print(f"  Kf={Kf:2d}: nadir {nads[-1][1]:.3f} Hz")
    ax.set_xlabel('Time (s)'); ax.set_ylabel('COI frequency (Hz)')
    ax.legend(fontsize=9, title='FFR droop gain')
    ax.set_title('Battery fast-frequency response (deadband 30 mHz), 15 MW step')
    _save(fig, outdir, 'sc_ffr.png')
    return dict(nadirs=nads)


# ==================================================================== pod ==
def sc_pod(outdir):
    """Kundur two-area: residue-based POD on a GFM battery raises the
    inter-area damping to a target — verified in the time domain."""
    ck = cases.kundur2a()
    BESS_K = dict(cases.GFM_K, Eh=1.0, SOC0=0.6)
    s = System(ck, ['SG', 'BESS-GFM', 'SG', 'SG'], [None, BESS_K, None, None])
    R = linearize(s)
    ia = sorted([l for l in R['ev'] if 0.3 < l.imag / 2 / np.pi < 0.9],
                key=lambda l: -l.real / abs(l))[0]
    B = D.input_matrix(R, units=[1])
    C = D.output_matrix(R, D.speed_output(s, 1))
    res, lam, i = D.residues(R, B, C, ia)
    pod = D.pod_design(res[0], lam, zeta_target=0.20)
    Acl = D.closed_loop(R, B[:, 0], C, pod)
    evcl = np.linalg.eig(Acl)[0]
    z1, lam1 = D.damping_of(evcl, lam)
    z0 = -lam.real / abs(lam) * 100
    print(f"  inter-area: {lam.imag/2/np.pi:.3f} Hz  {z0:.1f}% -> {z1:.1f}% "
          f"(POD: K={pod['K']:.1f}, {pod['nc']} lead-lag)")
    fig, ax = plt.subplots(figsize=(5.6, 4.4))
    ax.plot(R['ev'].real, R['ev'].imag, 'x', color=FS.C_SG, ms=8, label='open loop')
    ax.plot(evcl.real, evcl.imag, 'o', mfc='none', color=FS.C_BESS, ms=7,
            label='with POD on the GFM battery')
    ax.set_xlim(-3.5, 0.5); ax.set_ylim(0, 12)
    for zt in (0.05, 0.15):
        th = np.linspace(0.5 * np.pi, np.pi, 40)
        rr = 12 / np.sin(np.arccos(zt))
        ax.plot(rr * np.cos(th), rr * np.sin(th) * np.sqrt(1 - zt ** 2),
                ls=':', color=FS.GRY, lw=0.8)
    ax.axvline(0, color='k', lw=0.8)
    ax.set_xlabel('Real (1/s)'); ax.set_ylabel('Imag (rad/s)')
    ax.legend(fontsize=9)
    ax.set_title('Damping the Kundur inter-area mode from a battery')
    _save(fig, outdir, 'sc_pod.png')
    return dict(pod=pod, z0=z0, z1=z1)


# ============================================================ penetration ==
def sc_penetration(outdir):
    """9-bus displacement paths: replacing SGs by GFL renewables erodes
    inertia and damping; the GFM route (BESS/PV-GFM) preserves both."""
    c9 = cases.ieee9()
    paths = {
        'GFL route': ([['SG', 'SG', 'SG'], ['SG', 'SG', 'PV-GFL'],
                       ['SG', 'WT4-GFL', 'PV-GFL']], FS.C_GFL),
        'GFM route': ([['SG', 'SG', 'SG'], ['SG', 'SG', 'BESS-GFM'],
                       ['SG', 'WT4-GFM', 'BESS-GFM']], FS.C_GFM)}
    from linearize import dominant_mode
    fig, ax = plt.subplots(1, 2, figsize=(8.6, 3.8))
    for nm, (path, col) in paths.items():
        pen, He, zmin = [], [], []
        for mix in path:
            s = System(c9, mix)
            R = linearize(s)
            pen.append(s.penetration())
            He.append(s.eff_inertia())
            # least-damped oscillatory mode of ANY nature (0.2-6 Hz): in the
            # converter-dominated cases the critical mode CHANGES TYPE —
            # from electromechanical swing to wind-drivetrain torsional
            em = [z for f, z, l in modes(R['ev']) if 0.2 < f < 6.0]
            zmin.append(min(em))
        ax[0].plot(pen, He, 'o-', color=col, label=nm)
        ax[1].plot(pen, zmin, 'o-', color=col, label=nm)
        print(f"  {nm}: penetration {['%.0f%%' % p for p in pen]}, "
              f"H {['%.1f' % h for h in He]}, min-damping {['%.1f%%' % z for z in zmin]}")
    ax[0].set_xlabel('IBR share of generation (%)')
    ax[0].set_ylabel('effective inertia $H_{sys}$ (s)')
    ax[1].set_xlabel('IBR share of generation (%)')
    ax[1].set_ylabel('least damping, any mode 0.2-6 Hz (%)')
    for a in ax:
        a.legend(fontsize=9)
    fig.suptitle('Renewable displacement: grid-following vs grid-forming route', y=1.02)
    fig.tight_layout()
    _save(fig, outdir, 'sc_penetration.png')
    return {}


# ============================================================ syn_inertia ==
def sc_syn_inertia(outdir):
    """Type-4 synthetic inertia: the turbine lends kinetic energy after the
    event — and pays it back (the recovery dip)."""
    c9 = cases.ieee9()
    fig, ax = plt.subplots(2, 1, figsize=(6.6, 5.6), sharex=True)
    for si, col, lbl in ((False, FS.C_GFL, 'no synthetic inertia'),
                         (True, FS.C_GFM, 'synthetic inertia $K_{si}$=120')):
        s = System(c9, ['SG', 'SG', 'WT4-GFL'],
                   [None, None, dict(syn_in=si, Ksi=120.0, Tsi=0.5)])
        T, X, Z = simulate(s, tsim=20.0, dt=2e-3, t_dist=1.0, dPload={7: 0.15})
        fc = s.coi_freq(X)
        ax[0].plot(T, fc, color=col, label=lbl)
        ax[1].plot(T, s.unit_state(X, 2, 'wg'), color=col, label=lbl)
        first = fc[(T >= 1) & (T <= 5)].min()
        later = fc[T > 5].min()
        print(f"  syn_in={si}: first dip {first:.3f} Hz, recovery-phase min "
              f"{later:.3f} Hz, min rotor speed {s.unit_state(X,2,'wg').min():.3f} pu")
    print("  -> the kinetic boost softens the FIRST dip; paying the rotor "
          "back causes the SECOND dip (the classic recovery trade-off)")
    ax[0].set_ylabel('COI frequency (Hz)'); ax[0].legend(fontsize=9)
    ax[0].set_title('15 MW load step with a Type-4 wind plant at bus 3')
    ax[1].set_ylabel('turbine generator speed (pu)')
    ax[1].set_xlabel('Time (s)'); ax[1].legend(fontsize=9)
    _save(fig, outdir, 'sc_syn_inertia.png')
    return {}


# ================================================================== mix68 ==
def sc_mix68(outdir):
    """68-bus NETS-NYPS: displace the eight NETS machines by a wind/PV/BESS
    mix and track the critical inter-area modes."""
    c68 = cases.ne68()
    mixes = {
        'all-SG base': ['SG'] * 16,
        'NETS 8x GFL-RES': ['PV-GFL', 'WT4-GFL'] * 4 + ['SG'] * 8,
        'NETS 8x GFM-RES': ['BESS-GFM', 'WT4-GFM'] * 4 + ['SG'] * 8}
    from linearize import participation
    rows = []
    for nm, mix in mixes.items():
        s = System(c68, mix)
        R = linearize(s)
        names = s.state_names()
        # inter-area band and overall critical mode
        ia = sorted([(z, f) for f, z, l in modes(R['ev']) if 0.1 < f < 0.8])[:2]
        crit = sorted([(z, f) for f, z, l in modes(R['ev']) if 0.1 < f < 6.0])[0]
        nun = int(np.sum(R['ev'].real > 1e-6))
        msg = (f"  {nm:16s} pen={s.penetration():4.1f}%  unstable={nun}  "
               f"critical {crit[1]:.2f}Hz/{crit[0]:.1f}%  inter-area: "
               + ", ".join(f"{f:.2f}Hz/{z:.1f}%" for z, f in ia))
        print(msg)
        for lam in R['ev']:
            if lam.real > 1e-6 and lam.imag >= 0:
                p, _ = participation(R, lam=lam)
                top = np.argsort(p)[::-1][:3]
                print(f"      UNSTABLE {lam.real:+.3f}{lam.imag:+.3f}j "
                      f"({abs(lam.imag)/2/np.pi:.2f} Hz): "
                      + ", ".join(names[j] for j in top))
        rows.append((nm, s.penetration(), ia, crit, nun))
    return dict(rows=rows)


REGISTRY = {
    'validate': sc_validate, 'pv_cloud': sc_pv_cloud, 'wind_types': sc_wind_types,
    'bess_inertia': sc_bess_inertia, 'ffr': sc_ffr, 'pod': sc_pod,
    'penetration': sc_penetration, 'syn_inertia': sc_syn_inertia,
    'mix68': sc_mix68,
}


def run(name='all', outdir='figs'):
    if name == 'all':
        out = {}
        for nm in REGISTRY:
            print(f"\n=== {nm} ===")
            out[nm] = REGISTRY[nm](outdir)
        return out
    print(f"=== {name} ===")
    return REGISTRY[name](outdir)
