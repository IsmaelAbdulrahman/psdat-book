function [f, g] = psdat_dae(x, z, S, u)
% PSDAT_DAE  Differential (f) and algebraic (g) residuals of the system.
%
%   [f, g] = psdat_dae(x, z, S, u)
%
% x : differential states of all units (S.U(k).xidx)
% z : [unit algebraic vars (stator currents); V(1:n); TH(1:n)]
% S : system struct from psdat_system
% u : input struct (all fields optional):
%       u.dPu    (1 x m)  generator-side set-point/mech-power offsets
%       u.dPload (n x 1)  network-side load changes
%       u.G      (1 x m)  PV irradiance (pu of STC; NaN = initial)
%       u.vw     (1 x m)  wind speed (pu of rated;  NaN = initial)
%       u.Yextra (n x n)  admittance perturbation (fault shunt / line out)
%
% THIS FILE IS THE MODEL.  Every equation of every unit type is written out
% below with its source:
%   SG   two-axis sub-transient machine + IEEE-T1 exciter + turbine-governor
%        [Sauer & Pai ch. 3-4; Anderson & Fouad; Kundur]
%   GFM  droop/VSM grid-forming converter [Zhong & Weiss 2011; D'Arco & Suul]
%   GFL  SRF-PLL + current-control grid-following converter
%        [Kaura & Blasko 1997; Chung 2000; Yazdani & Iravani ch. 8]
%   PV   simplified single-diode array + DC link + MPPT [Masters; Femia et al.]
%   BESS state-of-charge + capability limits + fast frequency response
%        [Plett; Kundur ch. 11; IEEE Std 2800-2022]
%   WT4  Cp(lambda,beta) aero + two-mass shaft + pitch + MPPT
%        [Heier; Ackermann ch. 24-25; Slootweg et al. 2003]
%   WT3  DFIG: 3rd-order induction machine + vector-controlled rotor
%        converter [Ekanayake 2003; Holdsworth 2003; Anaya-Lara ch. 4]
%   WT1/2 fixed-speed SCIG (+ external rotor resistance) [Ackermann ch. 24]
% Mirrors psdat/units.py + system.py of the validated Python reference.
L = S.L; m = S.m; n = S.n; ws = S.ws;
if nargin < 4, u = struct(); end
SY = isa(x,'sym') || isa(z,'sym');   % symbolic call (PSDAT_Symbolic):
                                     % inactive hard limits are omitted —
                                     % valid in a neighbourhood of the
                                     % operating point, where they are
                                     % exactly inactive by construction
dPu = getdef(u,'dPu',zeros(1,m)); Gset = getdef(u,'G',nan(1,m));
vwset = getdef(u,'vw',nan(1,m));
V = z(S.Vidx); TH = z(S.THidx); Vc = V.*exp(1i*TH);
Yb = S.Ybus; if isfield(u,'Yextra') && ~isempty(u.Yextra), Yb = Yb + u.Yextra; end
% dynamic series FACTS: stamp the compensation deviation ΔY(k) onto Ybus (state-
% dependent admittance) BEFORE the network power -- ΔY=0 at k=k0 reproduces the
% base-compensated Ybus.  (MATLAB copy-on-write leaves S.Ybus untouched.)
if isfield(S,'SF') && ~isempty(S.SF)
    for kf = 1:numel(S.SF)
        a = S.SF(kf).aux; kc = x(S.SF(kf).xidx(1));
        dy = 1/(a.r + 1i*a.xline*(1-kc)) - 1/(a.r + 1i*a.xline*(1-a.k0));
        fb = a.f; tb = a.t; tp = a.a;
        Yb(fb,fb) = Yb(fb,fb) + dy/(tp*tp);
        Yb(tb,tb) = Yb(tb,tb) + dy;
        Yb(fb,tb) = Yb(fb,tb) - dy/conj(tp);
        Yb(tb,fb) = Yb(tb,fb) - dy/tp;
    end
end
Snet = Vc.*conj(Yb*Vc);
PL = S.PL0; QL = S.QL0;
if isfield(u,'dPload') && ~isempty(u.dPload), PL = PL + u.dPload; end

f = []; galg = []; Pinj = zeros(n,1); Qinj = zeros(n,1);
if SY, Pinj = sym(Pinj); Qinj = sym(Qinj); end
for k = 1:m
    un = S.U(k); xi = x(un.xidx); a = un.aux; i = un.bus;
    Vg = V(i); Thg = TH(i);
    switch un.type
    % ------------------------------------------------ SYNCHRONOUS MACHINE
    % Full 11-state model + selectable reduced orders (SG2/4/6, governed
    % variants) + power-system stabiliser (SGP/SG6P) [Sauer & Pai ch.3-4,6,8].
    % All route through the stator/electrical helpers below; mirrors psdat/units.py.
    case {'SG','SG2','SG4','SG6','SG4G','SG6G','SGP','SG6P'}
        d = S.MD; Id = z(un.zidx(1)); Iq = z(un.zidx(2));
        switch un.type
        case 'SG2'
            [fx,ga,Pk,Qk] = sg2_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, a.Ep, a.Pm + dPu(k));
        case 'SG4'
            [fx,ga,Pk,Qk] = sg4_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, a.Efd, a.Pm + dPu(k));
        case 'SG6'
            [fx,ga,Pk,Qk] = sg6_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, a.Pm + dPu(k), a.Vref, 0);
        case 'SG4G'
            [fs,ga,Pk,Qk] = sg4_eqs(xi(1:4), Id, Iq, Vg, Thg, d, k, ws, a.Efd, xi(5));
            [gTM,gPSV] = gov_eqs(xi(5), xi(6), xi(4), ws, d, k, a.PC + dPu(k));
            fx = [fs; gTM; gPSV];
        case 'SG6G'
            [fs,ga,Pk,Qk] = sg6_eqs(xi(1:6), Id, Iq, Vg, Thg, d, k, ws, xi(7), a.Vref, 0);
            [gTM,gPSV] = gov_eqs(xi(7), xi(8), xi(3), ws, d, k, a.PC + dPu(k));
            fx = [fs; gTM; gPSV];
        case 'SGP'      % full SG + PSS: washout+2 lead-lag on dw -> AVR summing pt
            [fVw,fV1,fV2,Vpss] = L.pss_block(xi(12),xi(13),xi(14),(xi(6)-ws)/ws, a.pss);
            [fs,ga,Pk,Qk] = sg_eqs(xi(1:11), Id, Iq, Vg, Thg, d, k, ws, a.Vref, a.PC + dPu(k), Vpss);
            fx = [fs; fVw; fV1; fV2];
        case 'SG6P'
            [fVw,fV1,fV2,Vpss] = L.pss_block(xi(7),xi(8),xi(9),(xi(3)-ws)/ws, a.pss);
            [fs,ga,Pk,Qk] = sg6_eqs(xi(1:6), Id, Iq, Vg, Thg, d, k, ws, a.Pm + dPu(k), a.Vref, Vpss);
            fx = [fs; fVw; fV1; fV2];
        otherwise       % full 11-state SG
            [fx,ga,Pk,Qk] = sg_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, a.Vref, a.PC + dPu(k), 0);
        end
        f = [f; fx]; galg = [galg; ga];
        Pinj(i) = Pinj(i) + Pk; Qinj(i) = Qinj(i) + Qk;
    % ------------------------------------------------------- GRID-FORMING
    case {'GFM','PV-GFM','BESS-GFM','WT4-GFM'}
        p = a.p; dg = xi(1); wg = xi(2); Qf = xi(3);
        switch un.type
        case 'GFM'
            Pref = a.Pset + dPu(k);
        case 'PV-GFM'      % curtailed PV: cannot exceed the available sun
            Pav = xi(4);
            G = Gset(k); if isnan(G), G = p.G0; end
            [~, pmpG] = L.pv_mpp(p.voc, p.isc, G);
            f_extra = (a.kS*pmpG - Pav)/p.Tav;
            Pref = L.s_min(a.Pset + dPu(k), Pav) + a.c0;
        case 'BESS-GFM'    % battery: SOC capability window; both the
            % reference and the droop authority fade as the window closes,
            % so a depleted battery glides to zero ACTIVE power (it still
            % regulates voltage — reactive power needs no energy)
            SOC = xi(4);
            [~, Pdis, Pchg] = bess_soc_l(0, SOC, p, L);     % caps at this SOC
            fade = L.s_sig((SOC - p.SOCmin)/p.dSOC)* ...
                   L.s_sig((p.SOCmax - SOC)/p.dSOC)/a.fade0;
            Pref = fade*(L.s_clamp(a.Pset + dPu(k), -Pchg, Pdis) + a.c0);
        case 'WT4-GFM'     % wind: droop reference follows the MPPT order
            Po = xi(9);
            Pref = a.src.kS*Po + dPu(k);
        end
        % droop/VSM core [Zhong & Weiss; D'Arco & Suul]:
        %   d(dg)/dt = wg - ws
        %   2Hv/ws dwg/dt = Pref - Pe - Dp*(wg/ws - 1)   (instantaneous Pe)
        %   dQf/dt = wc*(Qe - Qf),  Eg = Eset + mq*(Qset - Qf)
        Zc = p.Rc + 1i*p.Xc; Vbb = Vg*exp(1i*Thg);
        Egm = a.Eset + p.mq*(a.Qset - Qf); Eg = Egm*exp(1i*dg);
        Ic = (Eg - Vbb)/Zc; Sc = Vbb*conj(Ic); Pe = real(Sc); Qe = imag(Sc);
        f3 = [wg - ws;
              (ws/(2*p.Hv))*(Pref - Pe - p.Dp*(wg/ws - 1));
              p.wc*(Qe - Qf)];
        switch un.type
        case 'GFM',      f = [f; f3];
        case 'PV-GFM',   f = [f; f3; f_extra];
        case 'BESS-GFM'  % the droop authority fades with the SOC window too
            f3(2) = (ws/(2*p.Hv))*(Pref - Pe - fade*p.Dp*(wg/ws - 1));
            f = [f; f3; Pe_soc(Pe, xi(4), p, L)];
        case 'WT4-GFM'
            wt=xi(4); wg2=xi(5); ttw=xi(6); be=xi(7); xp=xi(8); Po=xi(9);
            vw = vwset(k); if isnan(vw), vw = a.src.vw0; end
            Te = (Pe/a.src.kS)/wg2;          % grid power drawn from the rotor
            [fwt,fwg2,fttw,fbe,fxp,fPo] = wt_source_l(wt,wg2,ttw,be,xp,Po,Te,vw,p,a.src,ws,L);
            f = [f; f3; fwt; fwg2; fttw; fbe; fxp; fPo];
        end
        Pinj(i) = Pinj(i) + Pe;  Qinj(i) = Qinj(i) + Qe;
    % ----------------------------------------------------- GRID-FOLLOWING
    case {'GFL','PV-GFL','BESS-GFL','WT4-GFL'}
        p = a.p; thp = xi(1); xpll = xi(2); idc = xi(3); iqc = xi(4);
        phi = Thg - thp; vq = Vg*sin(phi);
        if SY, vd = Vg*cos(phi);             % floor inactive at op. point
        else,  vd = max(Vg*cos(phi), 0.1);   % voltage floor (ride-through)
        end
        switch un.type
        case 'GFL'
            dw = xpll/ws;                                       % PLL freq deviation (pu)
            Pref = L.p_support(a.Pset + dPu(k), Vg, dw, a.V0, p);  % Volt-Watt + Freq-Watt
            Qref = L.q_support(Pref, a.Pset, a.Qset, Vg, a.V0, p); % Volt-VAR / const-PF
            idr = Pref/vd; iqr = -Qref/vd; f_extra = [];
        case 'PV-GFL'
            % PV array + DC link + MPPT; the DC-voltage PI sets id*.
            % Plant per-unit on the DC side (1.0 = plant MPP at G0), scaled
            % back to system pu at the current reference.
            Vdc = xi(5); xdc = xi(6); vref = xi(7);
            G = Gset(k); if isnan(G), G = p.G0; end
            Ppv_p = Vdc*L.pv_curve_I(Vdc, G, p.voc, p.isc)/a.pmp0;
            Pe  = Vg*(idc*cos(phi) + iqc*sin(phi));
            [vmpG, pmpG] = L.pv_mpp(p.voc, p.isc, G);
            % MPPT reference tracks Vmp, OR a curtailed (higher) voltage when
            % the active-support functions ask the array to de-load [Sangwongwanich]
            if getdef(p,'Kvw',0) > 0 || getdef(p,'Kfw',0) > 0
                dw = xpll/ws;
                Pav = a.Pset*(pmpG/a.pmp0);                   % available power at G
                Pdem = L.p_support(Pav, Vg, dw, a.V0, p);     % Volt-Watt / Freq-Watt
                frac = min(max(Pdem/max(Pav,1e-6), 0.1), 1.0);
                vtarget = L.pv_vpower(p.voc, p.isc, G, frac*pmpG, vmpG, pmpG);
            else
                vtarget = vmpG;
            end
            f_extra = [(Ppv_p - Pe/a.Spl)/(p.Cdc*Vdc);  % DC-link balance
                       p.Kidc*(Vdc - vref);             % PI integrator
                       (vtarget - vref)/p.Tm];          % MPPT / de-loading ref
            idr = a.Spl*(p.Kpdc*(Vdc - vref) + xdc);
            Qref = L.q_support(Pe, a.Pset, a.Qset, Vg, a.V0, p);   % Volt-VAR / const-PF
            iqr = -Qref/vd;
        case 'BESS-GFL'
            % fast frequency response on the PLL frequency estimate
            SOC = xi(5); xw = xi(6); Pf = xi(7);
            dw = (xpll + p.Kp*vq)/ws;
            rocof = (dw - xw)/p.Tw;
            Pfr = -p.Kf*L.s_dead(dw, p.db) - p.Kr*rocof;
            [~, Pdis, Pchg] = bess_soc_l(0, SOC, p, L);
            Pbase = L.p_support(a.Pset + dPu(k) + Pf, Vg, dw, a.V0, p);  % dispatch+FFR + Volt-Watt
            Pcmd = L.s_clamp(Pbase, -Pchg, Pdis) + a.c0;
            Pe  = Vg*(idc*cos(phi) + iqc*sin(phi));
            Qref = L.q_support(Pcmd, a.Pset, a.Qset, Vg, a.V0, p);       % Volt-VAR / const-PF
            f_extra = [Pe_soc(Pe, SOC, p, L);
                       (dw - xw)/p.Tw;
                       (Pfr - Pf)/p.Tf];
            idr = Pcmd/vd; iqr = -Qref/vd;
        case 'WT4-GFL'
            % turbine + optional synthetic inertia from the PLL RoCoF
            wt=xi(5); wg=xi(6); ttw=xi(7); be=xi(8); xp=xi(9); Po=xi(10);
            xw=xi(11); Psi=xi(12);
            vw = vwset(k); if isnan(vw), vw = a.src.vw0; end
            dw = (xpll + p.Kp*vq)/ws;
            rocof = (dw - xw)/p.Tsi;
            if p.syn_in, Psiref = -p.Ksi*rocof; else, Psiref = 0; end
            Te = (Po + Psi)/wg;              % machine-side torque execution
            [fwt,fwg,fttw,fbe,fxp,fPo] = wt_source_l(wt,wg,ttw,be,xp,Po,Te,vw,p,a.src,ws,L);
            f_extra = [fwt; fwg; fttw; fbe; fxp; fPo;
                       (dw - xw)/p.Tsi;
                       (Psiref - Psi)/0.2];
            idr = (a.src.kS*(Po + Psi) + dPu(k))/vd;  iqr = -a.Qset/vd;
        end
        if ~SY, [idr, iqr] = L.ilim(idr, iqr, a.Ilim); end
        % SRF-PLL + first-order current loops [Kaura & Blasko; Yazdani]:
        f = [f; xpll + p.Kp*vq; p.Ki*vq;
             (1/p.Ti)*(idr - idc); (1/p.Ti)*(iqr - iqc); f_extra];
        Pinj(i) = Pinj(i) + Vg*(idc*cos(phi) + iqc*sin(phi));
        Qinj(i) = Qinj(i) + Vg*(idc*sin(phi) - iqc*cos(phi));
    % ------------------------------------------- INDUCTION-MACHINE WIND
    case {'WT1','WT2','WT3'}
        q = a.q; p = a.p;
        Ed = xi(1); Eq = xi(2); s = xi(3); wt = xi(4); ttw = xi(5);
        Ids = z(un.zidx(1)); Iqs = z(un.zidx(2));
        Vd = Vg*cos(Thg); Vq = Vg*sin(Thg);
        % stator algebraic equations (generator convention):
        g1 = Ed - q.Rs*Ids + q.Xp*Iqs - Vd;
        g2 = Eq - q.Rs*Iqs - q.Xp*Ids - Vq;
        Ps = Vd*Ids + Vq*Iqs;  Qs = Vq*Ids - Vd*Iqs;
        Te = Ed*Ids + Eq*Iqs;
        wr = 1 - s;
        Rr_eff = q.Rr; vdr = 0; vqr = 0; fex = []; Qshunt = 0;
        if strcmp(un.type,'WT2')
            % external rotor resistance control (OptiSlip) [Ackermann]
            xR = xi(6);
            Rmax_rel = a.p.Rext_max/max(q.Rr,1e-6);
            Rrel = L.s_clamp(xR, 0, Rmax_rel) - a.cR0;
            Rr_eff = q.Rr*(1 + Rrel);
            fex = a.p.KiR*(Ps - a.Prate) - 1.0*(xR - (Rrel + a.cR0));
        end
        if strcmp(un.type,'WT3')
            % vector control in the terminal-voltage-oriented frame: the
            % stator flux lies on the -q axis, so vdr_c drives torque/P and
            % vqr_c drives Q with inverted sense [Anaya-Lara ch. 4]
            xP = xi(6); xQ = xi(7); be = xi(8); xp = xi(9); Po = xi(10);
            Ptot = Ps*(1 - s);               % stator + rotor (GSC) power
            Pord = a.src.kS*Po + dPu(k);
            eP = Pord - Ptot;  eQ = a.Qset - Qs;
            vdr_c = xP + p.KpT*eP;  vqr_c = xQ - p.KpV*eQ;
            vr = (vdr_c + 1i*vqr_c)*exp(1i*Thg);
            vdr = real(vr); vqr = imag(vr);
        end
        T0p = q.Xrr/(ws*Rr_eff); kr = ws*q.Xm/q.Xrr;
        % rotor-flux dynamics (see model header):
        fEd =  s*ws*Eq - (Ed - (q.X - q.Xp)*Iqs)/T0p - kr*vqr;
        fEq = -s*ws*Ed - (Eq + (q.X - q.Xp)*Ids)/T0p + kr*vdr;
        if strcmp(un.type,'WT3')
            vw = vwset(k); if isnan(vw), vw = a.src.vw0; end
            [fwt,fwg,fttw,fbe,fxp,fPo] = wt_source_l(wt,1-s,ttw,be,xp,Po, ...
                Te/a.kSm, vw, p, a.src, ws, L);
            fs = -fwg;
            f = [f; fEd; fEq; fs; fwt; fttw;
                 p.KiT*eP; -p.KiV*eQ; fbe; fxp; fPo];
            Pinj(i) = Pinj(i) + Ptot;  Qinj(i) = Qinj(i) + Qs;
        else
            % Types 1-2: fixed pitch, direct coupling, shunt compensation
            vw = vwset(k); if isnan(vw), vw = a.vw0; end
            lam = p.lam_r*wt/vw;
            Tm = (L.wt_cp(lam, 0, p.c)/p.Cpmax)*vw^3/wt;   % turbine pu
            Tsh = p.Ksh*ttw + p.Dsh*(wt - wr);
            fwt  = (Tm - Tsh)/(2*p.Ht);
            fttw = ws*(wt - wr);
            fs   = -(Tsh - Te/a.kSm)/(2*p.Hg);
            f = [f; fEd; fEq; fs; fwt; fttw; fex];
            Qshunt = a.Bcap*Vg^2;            % compensation capacitor
            Pinj(i) = Pinj(i) + Ps;  Qinj(i) = Qinj(i) + Qs + Qshunt;
        end
        galg = [galg; g1; g2];
    otherwise
        error('unknown unit type %s', un.type);
    end
end
% ---- FACTS devices (SVC/STATCOM): shunt reactive injection + integral voltage
% regulator with an output limiter and back-calculation anti-windup.  Injects Q
% at its bus, no algebraic variables.  Mirrors facts.py _reg_rate/_svc_f/_statcom_f.
%
% MODEL REFERENCE (identical to facts.py/system.py of the Python edition; the
% forms follow Hingorani & Gyugyi "Understanding FACTS" and Kundur ch.11):
%   SVC      steady state  Q = B·|V|²,  B∈[Bmin,Bmax]  (impedance-type limit)
%            dynamics      B' = (Kr/Tr)(Vref−V) + Kaw·(sat(B)−B)
%   STATCOM  steady state  Q = |V|·I,  I∈[Imin,Imax]   (current-type limit —
%            holds Q∝V at the ceiling, the key advantage over an SVC at low V)
%            dynamics      I' = (Kr/Tr)(Vref−V) + Kaw·(sat(I)−I)
%   TCSC/TSSC/SSSC   x_eff = x·(1−k), k∈[kmin,kmax]; a POD-modulated device adds
%            k' = (k_ord−k)/Tc and enters the network via the ΔY(k) stamp above.
%   POD/WADC washout sTw/(1+sTw) → nc lead-lags (1+sT1)/(1+sT2) → gain K →
%            limiter [lo,hi]; input = any psdat_podmeasure signal, local or
%            remote (remote bus/line + delay τ models the WAMS/PMU channel).
%   UPFC     composition = STATCOM (sending bus) + SSSC (line);  P-Q mode = the
%            corridor delivers Pset+jQset while the shunt holds V and the DC
%            link carries the series converter's real power.
%   IPFC     composition = two SSSCs;  P-Q mode = master line delivers
%            P1set+jQ1set, slave delivers Q2set and balances the DC link
%            (P_se1+P_se2=0) — solved by the augmented Newton in psdat_system.
if isfield(S,'Facts')
    for kf = 1:numel(S.Facts)
        fd = S.Facts(kf); a = fd.aux; i = fd.bus; Vg = V(i);
        xf = x(fd.xidx); st = xf(1);                  % regulator state (B or I)
        Vpod = 0; dxc = [];                           % supplementary POD controller
        if isfield(a,'pod') && a.pod.on
            s_dev = psdat_podmeasure(a.pod, S, x, z) - a.pod.s0;
            [dxc, Vpod] = psdat_podstep(xf(2:end), s_dev, a.pod);
        end
        sat  = min(max(st, a.lo), a.hi);              % output limiter (B or I)
        err  = (a.Vref + Vpod) - Vg - a.droop*sat;    % reference + POD modulation
        rate = (a.Kr/a.Tr)*err + a.Kaw*(sat - st);    % integral regulator + anti-windup
        f = [f; rate; dxc(:)];                        %#ok<AGROW>
        if strcmp(a.type,'SVC'), Qk = sat*Vg*Vg; else, Qk = sat*Vg; end
        Qinj(i) = Qinj(i) + Qk;
    end
end
% ---- dynamic series FACTS state derivatives: k tracks its (POD-modulated,
% limited) reference through a first-order lag; the network coupling was already
% applied as the ΔY stamp above.  Mirrors system.System.dae's sfacts block.
if isfield(S,'SF')
    for kf = 1:numel(S.SF)
        a = S.SF(kf).aux; xs = x(S.SF(kf).xidx); kc = xs(1);
        Vpod = 0; dxc = [];
        if a.pod.on
            s_dev = psdat_podmeasure(a.pod, S, x, z) - a.pod.s0;
            [dxc, Vpod] = psdat_podstep(xs(2:end), s_dev, a.pod);
        end
        kcmd = min(max(a.k0 + Vpod, a.kmin), a.kmax);
        f = [f; (kcmd - kc)/a.Tc; dxc(:)];               %#ok<AGROW>
    end
end
% -------- algebraic: unit equations + polar power balance [Sauer & Pai] --
g = [galg; Pinj - PL - real(Snet); Qinj - QL - imag(Snet)];
end

% ------------------------------------------------------------------------
function v = getdef(u, fld, dv)
if isfield(u, fld) && ~isempty(u.(fld)), v = u.(fld); else, v = dv; end
end

function [fSOC, Pdis, Pchg] = bess_soc_l(Pe, SOC, p, L)
Pb = Pe + (1/p.eta - 1)*L.s_relu(Pe) + (1 - p.eta)*L.s_relu(-Pe);
fSOC = -Pb/(3600*p.Eh*p.Pmax);
Pdis = p.Pmax*L.s_sig((SOC - p.SOCmin)/p.dSOC);
Pchg = p.Pmax*L.s_sig((p.SOCmax - SOC)/p.dSOC);
end

function fSOC = Pe_soc(Pe, SOC, p, L)
fSOC = bess_soc_l(Pe, SOC, p, L);
end

function [fwt, fwg, fttw, fbe, fxp, fPo] = wt_source_l(wt, wg, ttw, be, xp, Po, Te, vw, p, src, ws, L)
% shared Type-3/4 source block: two-mass drivetrain + pitch PI + MPPT lag
% (turbine per-unit; see psdat_lib for the aerodynamic functions)
Kaw = 1.0;
Tm  = L.wt_pm(wt, vw, be, p)/wt;
Tsh = p.Ksh*ttw + p.Dsh*(wt - wg);
fwt  = (Tm - Tsh)/(2*p.Ht);
fttw = ws*(wt - wg);
fwg  = (Tsh - Te)/(2*p.Hg);
e = wg - 1;
be_raw = p.Kpp*e + xp;
be_sat = L.s_clamp(be_raw, 0, p.bmax);
fbe = (be_sat - be)/p.Tp;
fxp = p.Kip*e - Kaw*(be_raw - be);
Pcl = L.s_min(p.kopt*wg^3, 1.0) + src.cPo;
fPo = (Pcl - Po)/p.TPo;
end

% ================= SYNCHRONOUS-MACHINE EQUATION HELPERS ==================
% One validated copy of the stator/electrical equations per model order, so
% the full model, the reduced orders, the governed variants and the PSS
% models all solve identical physics.  Mirrors psdat/units.py sg*_f.  Vpss is
% the stabiliser output summed into the AVR reference (0 when no PSS).

function [fx, ga, Pinj, Qinj] = sg_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, Vref, PC, Vpss)
% full two-axis sub-transient (11 states) + IEEE-T1 exciter + turbine-governor
Eqp=xi(1);Si1d=xi(2);Edp=xi(3);Si2q=xi(4);Delta=xi(5);w=xi(6);
Efd=xi(7);RF=xi(8);VR=xi(9);TM=xi(10);PSV=xi(11);
ad = Delta - Thg;
fx = [
 (1/d.Td0p(k))*(-Eqp-(d.Xd(k)-d.Xdp(k))*(Id-((d.Xdp(k)-d.Xdpp(k))/(d.Xdp(k)-d.Xls(k))^2)*(Si1d+(d.Xdp(k)-d.Xls(k))*Id-Eqp))+Efd);
 (1/d.Td0pp(k))*(-Si1d+Eqp-(d.Xdp(k)-d.Xls(k))*Id);
 (1/d.Tq0p(k))*(-Edp+(d.Xq(k)-d.Xqp(k))*(Iq-((d.Xqp(k)-d.Xqpp(k))/(d.Xqp(k)-d.Xls(k))^2)*(Si2q+(d.Xqp(k)-d.Xls(k))*Iq+Edp)));
 (1/d.Tq0pp(k))*(-Si2q-Edp-(d.Xqp(k)-d.Xls(k))*Iq);
 w - ws;
 (ws/(2*d.H(k)))*(TM ...
    -((d.Xdpp(k)-d.Xls(k))/(d.Xdp(k)-d.Xls(k)))*Eqp*Iq ...
    -((d.Xdp(k)-d.Xdpp(k))/(d.Xdp(k)-d.Xls(k)))*Si1d*Iq ...
    -((d.Xqpp(k)-d.Xls(k))/(d.Xqp(k)-d.Xls(k)))*Edp*Id ...
    +((d.Xqp(k)-d.Xqpp(k))/(d.Xqp(k)-d.Xls(k)))*Si2q*Id ...
    -(d.Xqpp(k)-d.Xdpp(k))*Id*Iq - d.Dm(k)*(w-ws));
 (1/d.TE(k))*((-(d.KE(k)+d.Ax(k)*exp(d.Bx(k)*Efd)))*Efd+VR);
 (1/d.TF(k))*(-RF+(d.KF(k)/d.TF(k))*Efd);
 (1/d.TA(k))*(-VR+d.KA(k)*RF-((d.KA(k)*d.KF(k))/d.TF(k))*Efd+d.KA(k)*(Vref-Vg+Vpss));
 (1/d.TCH(k))*(-TM+PSV);
 (1/d.TSV(k))*(-PSV+PC-(1/d.RD(k))*(w/ws-1))];
ga = [
 d.Rs(k)*Id-d.Xqpp(k)*Iq-((d.Xqpp(k)-d.Xls(k))/(d.Xqp(k)-d.Xls(k)))*Edp+((d.Xqp(k)-d.Xqpp(k))/(d.Xqp(k)-d.Xls(k)))*Si2q+Vg*sin(ad);
 d.Rs(k)*Iq+d.Xdpp(k)*Id-((d.Xdpp(k)-d.Xls(k))/(d.Xdp(k)-d.Xls(k)))*Eqp-((d.Xdp(k)-d.Xdpp(k))/(d.Xdp(k)-d.Xls(k)))*Si1d+Vg*cos(ad)];
Pinj = Id*Vg*sin(ad) + Iq*Vg*cos(ad);
Qinj = Id*Vg*cos(ad) - Iq*Vg*sin(ad);
end

function [fx, ga, Pinj, Qinj] = sg6_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, Pm, Vref, Vpss)
% one-axis flux-decay (E'd=0, salient Xq) + IEEE-T1 AVR (6 states)
Eqp=xi(1); Delta=xi(2); w=xi(3); Efd=xi(4); RF=xi(5); VR=xi(6);
ad = Delta - Thg;
TE = Eqp*Iq + (d.Xq(k)-d.Xdp(k))*Id*Iq;
fx = [
 (1/d.Td0p(k))*(-Eqp - (d.Xd(k)-d.Xdp(k))*Id + Efd);
 w - ws;
 (ws/(2*d.H(k)))*(Pm - TE - d.Dm(k)*(w-ws));
 (1/d.TE(k))*((-(d.KE(k)+d.Ax(k)*exp(d.Bx(k)*Efd)))*Efd + VR);
 (1/d.TF(k))*(-RF + (d.KF(k)/d.TF(k))*Efd);
 (1/d.TA(k))*(-VR + d.KA(k)*RF - ((d.KA(k)*d.KF(k))/d.TF(k))*Efd + d.KA(k)*(Vref - Vg + Vpss))];
ga = [d.Rs(k)*Id - d.Xq(k)*Iq + Vg*sin(ad);
      d.Rs(k)*Iq + d.Xdp(k)*Id - Eqp + Vg*cos(ad)];
Pinj = Id*Vg*sin(ad) + Iq*Vg*cos(ad);
Qinj = Id*Vg*cos(ad) - Iq*Vg*sin(ad);
end

function [fx, ga, Pinj, Qinj] = sg4_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, Efd, Pm)
% two-axis (E'q, E'd) with constant field Efd (4 states)
Eqp=xi(1); Edp=xi(2); Delta=xi(3); w=xi(4);
ad = Delta - Thg;
TE = Edp*Id + Eqp*Iq + (d.Xqp(k)-d.Xdp(k))*Id*Iq;
fx = [
 (1/d.Td0p(k))*(-Eqp - (d.Xd(k)-d.Xdp(k))*Id + Efd);
 (1/d.Tq0p(k))*(-Edp + (d.Xq(k)-d.Xqp(k))*Iq);
 w - ws;
 (ws/(2*d.H(k)))*(Pm - TE - d.Dm(k)*(w-ws))];
ga = [d.Rs(k)*Id - d.Xqp(k)*Iq - Edp + Vg*sin(ad);
      d.Rs(k)*Iq + d.Xdp(k)*Id - Eqp + Vg*cos(ad)];
Pinj = Id*Vg*sin(ad) + Iq*Vg*cos(ad);
Qinj = Id*Vg*cos(ad) - Iq*Vg*sin(ad);
end

function [fx, ga, Pinj, Qinj] = sg2_eqs(xi, Id, Iq, Vg, Thg, d, k, ws, Ep, Pm)
% classical constant-flux model (E'=Ep, E'd=0, X'q=X'd=Xdp; 2 states)
Delta=xi(1); w=xi(2);
ad = Delta - Thg;
TE = Ep*Iq;
fx = [w - ws;
      (ws/(2*d.H(k)))*(Pm - TE - d.Dm(k)*(w-ws))];
ga = [d.Rs(k)*Id - d.Xdp(k)*Iq + Vg*sin(ad);
      d.Rs(k)*Iq + d.Xdp(k)*Id - Ep + Vg*cos(ad)];
Pinj = Id*Vg*sin(ad) + Iq*Vg*cos(ad);
Qinj = Id*Vg*cos(ad) - Iq*Vg*sin(ad);
end

function [fTM, fPSV] = gov_eqs(TM, PSV, w, ws, d, k, PC)
% turbine + speed-governor with droop RD (primary frequency response)
fTM  = (1/d.TCH(k))*(-TM + PSV);
fPSV = (1/d.TSV(k))*(-PSV + PC - (1/d.RD(k))*(w/ws - 1));
end
