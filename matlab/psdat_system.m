function S = psdat_system(SYS, UT, UTP, PFM)
% PSDAT_SYSTEM  Build a PSDAT study system: case data + load flow + units.
%
%   S = psdat_system('IEEE9',   {'SG','GFM','PV-GFL'})
%   S = psdat_system('Kundur2A',{'SG','BESS-GFM','SG','GFL'})
%   S = psdat_system('case68',  [repmat({'WT4-GFL'},1,8) repmat({'SG'},1,8)])
%
% SYS : 'IEEE9' | 'Kundur2A' | 'case68'
% UT  : 1 x m cell array of unit tags, one per machine position:
%       'SG' 'GFM' 'GFL' 'PV-GFL' 'PV-GFM' 'BESS-GFM' 'BESS-GFL'
%       'WT4-GFL' 'WT4-GFM' 'WT3' 'WT1' 'WT2'
% UTP : optional 1 x m cell array of parameter-override structs ([] = defaults)
%
% Requires MATPOWER (runpf/makeYbus) and the bundled case files on the path.
% Every model equation lives in psdat_dae.m; this file computes the load
% flow, the machine data and the exact initial conditions of every unit.
% Mirrors psdat/{cases,system,units}.py of the validated Python reference.
L = psdat_lib();
ws = 2*pi*60; baseMVA = 100;

if isstruct(SYS)
% ================= custom drawn network (from psdat_netcase) =============
% A single-line diagram built in the interactive editor: identical unit
% assembly and initial conditions as the benchmarks, but the network,
% admittance matrix and load flow come from the drawing, not a case file.
    C = SYS;
    if nargin < 2 || isempty(UT)
        if isfield(C,'UT'), UT = C.UT; else, UT = repmat({'SG'},1,C.m); end
    end
    m = C.m; n = C.n;
    if nargin < 3 || isempty(UTP), UTP = cell(1, numel(UT)); end
    if nargin < 4 || isempty(PFM) || strcmpi(PFM,'mp'), PFM = 'nr'; end
    assert(numel(UT) == m, 'UT must have %d entries (one per generator)', m);
    facts = []; if isfield(C,'facts'), facts = C.facts; end
    C.branch = apply_series_m(C.branch, facts);                % series FACTS -> compensate the line
    Ybus = psdat_ybus(n, C.branch, C.tap, C.gs, C.bs);
    % DC-coupled UPFC in P-Q control mode: remove its line, shift the loads to
    % deliver Pset+jQset along the corridor, and drop in a shunt regulator at the
    % sending bus (mirrors facts.upfc_pq_prepare / cases.Case of the Python ref).
    [facts, C.Pd, C.Qd, pqstamps] = upfc_pq_prepare_m(facts, C.branch, C.tap, n, C.Pd, C.Qd);
    for kk = 1:numel(pqstamps), Ybus = Ybus - pqstamps{kk}; end
    % DC-coupled IPFC in P-Q control mode: both lines stay in Ybus; each device is
    % solved by an augmented Newton (network + 4 control equations) and folded in as
    % constant ΔS load injections at the four terminals (mirrors facts.ipfc_pq_solve /
    % cases.Case of the Python reference).
    [facts, C.Pd, C.Qd] = ipfc_pq_prepare_m(facts, Ybus, C.bus_type, C.Vm0, ...
                              C.gen_bus, C.Pg_sched, C.Vg_sched, C.branch, C.tap, C.Pd, C.Qd, n);
    [btf, vmf] = facts_pf_setup(C.bus_type, C.Vm0, facts, n);   % shunt FACTS -> PV at Vref
    [V0, TH0, Pg, Qg, S_pf] = psdat_powerflow(Ybus, btf, C.Pd, C.Qd, ...
                                 vmf, C.gen_bus, C.Pg_sched, C.Vg_sched, ...
                                 PFM, C.branch, C.tap);
    [facts, shB, shbus] = facts_oppoint(facts, V0, Qg);         % operating point + saturation
    if ~isempty(shbus)                                          % re-solve, saturated devices fixed as shunts
        bs2 = C.bs(:); btf2 = btf;
        for jj = 1:numel(shbus)
            ii = shbus(jj); bs2(ii) = bs2(ii) + shB(jj);
            if C.bus_type(ii)==1, btf2(ii) = 1; end
        end
        % The saturated-device shunts go into a PF-ONLY admittance matrix.
        % S.Ybus (used by the dynamics) stays CLEAN: each device's reactive
        % output is produced by its own regulator state at the limit, so the
        % injection would be counted twice if the shunt were also baked in.
        Ypf = psdat_ybus(n, C.branch, C.tap, C.gs, bs2);
        for kk = 1:numel(pqstamps), Ypf = Ypf - pqstamps{kk}; end     % keep P-Q UPFC lines removed
        [V0, TH0, Pg, Qg, S_pf] = psdat_powerflow(Ypf, btf2, C.Pd, C.Qd, ...
                                     vmf, C.gen_bus, C.Pg_sched, C.Vg_sched, ...
                                     PFM, C.branch, C.tap);
        % Refresh the UNSATURATED operating points only: at a saturated bus the
        % device's Q now flows through the bs2 shunt, so Qg no longer carries
        % it -- recomputing there would wrongly zero the device output.  The
        % saturated devices keep their limit values (B_/I_ = the ceiling), and
        % B_lim*V0^2 (resp. I_lim*V0) reproduces the shunt's Q at the solved
        % V0 exactly, so the initial condition stays an equilibrium of psdat_dae.
        facts = facts_oppoint(facts, V0, Qg, shbus);
    end
    C.facts = facts;
    % P-Q-controlled corridors (UPFC / IPFC): the raw line-admittance flow no
    % longer tells the story (line removed, or series source not in Ybus), so
    % export [f t P(MW) Q(MVAr)] per corridor for the SLD overlay / reports.
    pqlines = zeros(0,4);
    for kf = 1:numel(facts)
        d = facts(kf); md = lower(getfld_s(d,'mode',''));
        if ~any(strcmp(md,{'pq','p-q','pqctrl'})), continue; end
        if strcmpi(getfld_s(d,'type',''),'STATCOM') && ~isempty(getfld_s(d,'Pset',[]))
            pqlines(end+1,:) = [round(d.f) round(d.t) d.Pset d.Qset];            %#ok<AGROW>
        elseif strcmpi(getfld_s(d,'type',''),'IPFC') && ~isempty(getfld_s(d,'P1set',[]))
            pqlines(end+1,:) = [round(d.f) round(d.t) d.P1set d.Q1set];          %#ok<AGROW>
            rp = getfld_s(d,'rep',[]);
            if isstruct(rp) && isfield(rp,'S2')
                pqlines(end+1,:) = [round(d.f2) round(d.t2) real(rp.S2) imag(rp.S2)]; %#ok<AGROW>
            end
        end
    end
    if any(~isfinite(V0)) || min(V0) < 0.5 || max(V0) > 1.6
        error(['power flow did not converge -- check impedances, loads and ' ...
               'that the network is fully connected']);
    end
    PL0 = C.Pd; QL0 = C.Qd; gb = C.gen_bus(:);
    MD = C.MD; Sbase_gen = C.Sbase_gen;
    % MATPOWER-style branch matrix so line_stamp() and the SLD reuse the
    % same column layout as the benchmarks ([.,.,r,x,b,.,.,.,tap])
    nbr = size(C.branch,1); branch = zeros(max(nbr,0), 13);
    if nbr > 0
        branch(:,1:5) = C.branch; branch(:,9) = C.tap(:); branch(:,11) = 1;
    end
    name = C.name;
else
% ================= bundled benchmark (MATPOWER case file) ================
    if nargin < 3 || isempty(UTP), UTP = cell(1, numel(UT)); end
    if nargin < 4 || isempty(PFM), PFM = 'mp'; end   % 'mp'=MATPOWER (default)
    switch SYS                                       % or 'nr'/'fdlf'/'gs'
    case 'IEEE9'
        m = 3; n = 9; casefile = 'IEEE9Bus';
        MD = psdat_machinedata('IEEE9', ws);
        Sbase_gen = [100 300 270];
    case 'Kundur2A'
        m = 4; n = 11; casefile = 'Kundur2A';
        MD = psdat_machinedata('Kundur2A', ws);
        Sbase_gen = [900 900 900 900];
    case 'case68'
        m = 16; n = 68; casefile = 'case68_16m';
        MD = psdat_machinedata('case68', ws);
        Sbase_gen = 100*ones(1,16);
    otherwise
        error('unknown SYS %s', SYS);
    end
    assert(numel(UT) == m, 'UT must have %d entries for %s', m, SYS);
    mpc = loadcase(casefile);
    branch = mpc.branch;
    Ybus = full(makeYbus(baseMVA, mpc.bus, mpc.branch));
    if strcmpi(PFM,'mp')               % MATPOWER Newton-Raphson (default)
        mpopt = mpoption('PF_ALG',1,'ENFORCE_Q_LIMS',0,'VERBOSE',0,'OUT_ALL',0);
        R1 = runpf(casefile, mpopt);
        if ~R1.success, error('load flow did not converge'); end
        bus = R1.bus; gen = R1.gen;
        V0  = bus(:,8);  TH0 = bus(:,9)*pi/180;
        PL0 = bus(:,3)/baseMVA;  QL0 = bus(:,4)/baseMVA;
        Pg  = zeros(n,1); Qg = zeros(n,1);
        gb  = gen(1:m,1);              % generator buses (may be ~= 1..m)
        Pg(gb) = gen(1:m,2)/baseMVA;  Qg(gb) = gen(1:m,3)/baseMVA;
        S_pf = struct('method','mp (MATPOWER NR)','iters',NaN,'mismatch',NaN);
    else                               % native NR/FDLF/GS [psdat_powerflow]
        bt  = mpc.bus(:,2);            % 1=PQ 2=PV 3=slack
        Pd  = mpc.bus(:,3)/baseMVA;  Qd = mpc.bus(:,4)/baseMVA;
        Vm0 = mpc.bus(:,8);
        gbus = mpc.gen(:,1);  Pgs = mpc.gen(:,2)/baseMVA;  Vgs = mpc.gen(:,6);
        br5 = mpc.branch(:,1:5);  tapv = mpc.branch(:,9);
        [V0, TH0, Pg, Qg, S_pf] = psdat_powerflow(Ybus, bt, Pd, Qd, Vm0, ...
                                                  gbus, Pgs, Vgs, PFM, br5, tapv);
        PL0 = Pd;  QL0 = Qd;  gb = mpc.gen(1:m,1);
    end
    name = SYS;
end

S = struct('name',name,'m',m,'n',n,'ws',ws,'baseMVA',baseMVA,'Ybus',Ybus, ...
           'V0',V0,'TH0',TH0,'PL0',PL0,'QL0',QL0,'Pg',Pg,'Qg',Qg, ...
           'Sbase_gen',Sbase_gen,'MD',MD,'gb',gb,'branch',branch);
S.UT = UT; S.L = L; S.pf = S_pf;   % power-flow method + iteration report
S.iscustom = isstruct(SYS);
if ~exist('pqlines','var'), pqlines = zeros(0,4); end
S.pqlines = pqlines;               % P-Q-controlled corridors [f t P(MW) Q(MVAr)]
if isstruct(SYS) && isfield(C,'facts'), S.facts = C.facts; else, S.facts = []; end
% ^ solved FACTS operating points (B_/I_/Q_/sat_ for shunts, rep for P-Q IPFC)
%   so the app's power-flow report can SHOW what each device is doing.

% ---------------- unit initial conditions --------------------------------
pos = 0; zpos = 0; x0 = []; z0u = [];
U = struct('type',{},'bus',{},'xidx',{},'zidx',{},'aux',{});
for k = 1:m
    i = gb(k);                        % terminal bus of unit k
    [st, alg, aux, ns, na] = init_unit(UT{k}, i, k, S, UTP{k}, L);
    U(k).type = UT{k}; U(k).bus = i;
    U(k).xidx = pos+(1:ns); pos = pos+ns;
    U(k).zidx = zpos+(1:na); zpos = zpos+na;
    U(k).aux = aux;
    x0 = [x0; st(:)]; z0u = [z0u; alg(:)];             %#ok<AGROW>
end
% ---- FACTS devices: one state each (susceptance B / reactive current I) plus
% an integral voltage regulator, appended after the machines so power balance,
% small-signal and time-domain include them with no special-casing. ----
Fc = struct('type',{},'bus',{},'xidx',{},'aux',{});
if S.iscustom && isfield(C,'facts') && ~isempty(C.facts)
    for kf = 1:numel(C.facts)
        if ~any(strcmpi(C.facts(kf).type,{'SVC','STATCOM'})), continue; end  % series = no dynamic state
        [stf, auxf] = facts_init(C.facts(kf), S);
        ns = numel(stf);                                 % 1 regulator + POD states
        Fc(end+1).type = upper(C.facts(kf).type);        %#ok<AGROW>
        Fc(end).bus  = round(C.facts(kf).bus);
        Fc(end).xidx = pos + (1:ns); pos = pos + ns;
        Fc(end).aux  = auxf;
        x0 = [x0; stf(:)];                               %#ok<AGROW>
    end
end
% ---- dynamic series FACTS (POD-modulated TCSC/SSSC): a first-order compensation
% state k(t) (+ POD states).  The network coupling is a state-dependent admittance
% stamp ΔY(k) applied in psdat_dae (NOT a bus injection); k=k0 reproduces the base-
% compensated Ybus exactly.  Mirrors facts.series_dynamic / system.System.sfacts.
SF = struct('f',{},'t',{},'xidx',{},'aux',{});
if S.iscustom && isfield(C,'facts') && ~isempty(C.facts)
    for kf = 1:numel(C.facts)
        fd = C.facts(kf); ty = upper(fd.type);
        if ~any(strcmp(ty,{'TCSC','SSSC'})), continue; end
        pc = pod_parse(getfld_s(fd,'pod',[]));
        if ~pc.on, continue; end
        f = round(fd.f); t = round(fd.t); row = 0;
        for kk = 1:size(S.branch,1)
            bf = round(S.branch(kk,1)); bt = round(S.branch(kk,2));
            if (bf==f && bt==t) || (bf==t && bt==f), row = kk; break; end
        end
        if row == 0, continue; end
        k0 = min(max(fd.kcomp, fd.kmin), fd.kmax);
        xeff = S.branch(row,4); xline = xeff/max(1-k0, 1e-6);   % recover base reactance
        rr = S.branch(row,3); a = 1;
        if size(S.branch,2) >= 9 && S.branch(row,9) ~= 0, a = S.branch(row,9); end
        pc.selfbus = round(S.branch(row,1));
        ns = 1 + pc.npod;
        SF(end+1).f = round(S.branch(row,1)); SF(end).t = round(S.branch(row,2)); %#ok<AGROW>
        SF(end).xidx = pos + (1:ns); pos = pos + ns;
        SF(end).aux = struct('f',round(S.branch(row,1)),'t',round(S.branch(row,2)), ...
            'r',rr,'xline',xline,'a',a,'k0',k0,'kmin',fd.kmin,'kmax',fd.kmax, ...
            'Tc',max(fd.Tc,1e-3),'pod',pc);
        x0 = [x0; k0; zeros(pc.npod,1)];                 %#ok<AGROW>
    end
end
S.Facts = Fc; S.SF = SF;
S.U = U; S.NX = pos; S.NU = zpos;
S.Vidx = (zpos+(1:n)).'; S.THidx = (zpos+n+(1:n)).';
S.NZ = zpos + 2*n;
S.x0 = x0; S.z0 = [z0u; V0; TH0];
% ---- POD/WADC: bus -> SG rotor-speed state column (for the 'wgen' signal) and
% each enabled device's operating-point signal s0 (so the loop acts on the
% deviation s - s0 and every controller state is 0 at equilibrium). ----
S.spdcol = zeros(n,1);
for k = 1:numel(S.U)
    if strcmpi(S.U(k).type,'SG') && numel(S.U(k).xidx) >= 6
        S.spdcol(S.U(k).bus) = S.U(k).xidx(6);           % SG omega state (Eqp,Si1d,Edp,Si2q,delta,omega,...)
    end
end
for kf = 1:numel(S.Facts)
    if isfield(S.Facts(kf).aux,'pod') && S.Facts(kf).aux.pod.on
        S.Facts(kf).aux.pod.s0 = psdat_podmeasure(S.Facts(kf).aux.pod, S, S.x0, S.z0);
    end
end
for kf = 1:numel(S.SF)
    if S.SF(kf).aux.pod.on
        S.SF(kf).aux.pod.s0 = psdat_podmeasure(S.SF(kf).aux.pod, S, S.x0, S.z0);
    end
end
end

% ========================================================================
%                        UNIT INITIALISATION
% (exact equilibria: every limit carries its correction constant so the
%  initial state is a machine-precision equilibrium of psdat_dae)
% ========================================================================
function [st, alg, aux, ns, na] = init_unit(tag, i, k, S, prm, L)
ws = S.ws; V0 = S.V0(i); TH0 = S.TH0(i); Pg = S.Pg(i); Qg = S.Qg(i);
Vb = V0*exp(1i*TH0); Ssch = Pg + 1i*Qg;
aux = struct('i',i,'k',k,'V0',V0);     % V0 used by IEEE-1547 grid-support droops
alg = []; na = 0;
switch tag
% ------------------------------------------------------------------- SG --
case 'SG'
    d = S.MD;
    Iph = conj(Ssch/Vb); E0 = Vb + (d.Rs(k)+1i*d.Xq(k))*Iph; D0 = angle(E0);
    Id0 = real(Iph*exp(-1i*(D0-pi/2))); Iq0 = imag(Iph*exp(-1i*(D0-pi/2)));
    Edp0 = (d.Xq(k)-d.Xqp(k))*Iq0; Si2q0 = (d.Xls(k)-d.Xq(k))*Iq0;
    Eqp0 = d.Rs(k)*Iq0 + d.Xdp(k)*Id0 + V0*cos(D0-TH0);
    Si1d0 = Eqp0 - (d.Xdp(k)-d.Xls(k))*Id0;
    Efd0 = Eqp0 + (d.Xd(k)-d.Xdp(k))*Id0;
    TM0 = ((d.Xdpp(k)-d.Xls(k))/(d.Xdp(k)-d.Xls(k)))*Eqp0*Iq0 ...
        + ((d.Xdp(k)-d.Xdpp(k))/(d.Xdp(k)-d.Xls(k)))*Si1d0*Iq0 ...
        + ((d.Xqpp(k)-d.Xls(k))/(d.Xqp(k)-d.Xls(k)))*Edp0*Id0 ...
        - ((d.Xqp(k)-d.Xqpp(k))/(d.Xqp(k)-d.Xls(k)))*Si2q0*Id0 ...
        + (d.Xqpp(k)-d.Xdpp(k))*Id0*Iq0;
    VR0 = (d.KE(k)+d.Ax(k)*exp(d.Bx(k)*Efd0))*Efd0;
    RF0 = (d.KF(k)/d.TF(k))*Efd0;
    st = [Eqp0;Si1d0;Edp0;Si2q0;D0;ws;Efd0;RF0;VR0;TM0;TM0];
    alg = [Id0;Iq0]; na = 2;
    aux.Vref = V0 + VR0/d.KA(k); aux.PC = TM0;
    ns = 11;
% ------------------------------------------------------------------ GFM --
case 'GFM'
    p = defp('GFM', prm);
    Ic = conj(Ssch/Vb); Eg = Vb + (p.Rc+1i*p.Xc)*Ic;
    st = [angle(Eg); ws; Qg];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Eset = abs(Eg);
    ns = 3;
% ------------------------------------------------------------------ GFL --
case 'GFL'
    p = defp('GFL', prm);
    st = [TH0; 0; Pg/V0; -Qg/V0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Ilim = irate(S,i,p);
    ns = 4;
% --------------------------------------------------------------- PV-GFL --
case 'PV-GFL'
    p = defp('PVGFL', prm);
    [vmp0, pmp0] = L.pv_mpp(p.voc, p.isc, p.G0);
    % DC side normalised PER PLANT (Spl = rating): the DC-link constant and
    % PI gains are then size-invariant, as physics requires
    st = [TH0; 0; Pg/V0; -Qg/V0; vmp0; 1/V0; vmp0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.kS = Pg/pmp0;
    aux.Spl = Pg; aux.pmp0 = pmp0;
    aux.Ilim = irate(S,i,p);
    ns = 7;
% --------------------------------------------------------------- PV-GFM --
case 'PV-GFM'
    p = defp('PVGFM', prm);
    Ic = conj(Ssch/Vb); Eg = Vb + (p.Rc+1i*p.Xc)*Ic;
    Pav0 = Pg/(1-p.curt);
    [~, pmp0] = L.pv_mpp(p.voc, p.isc, p.G0);
    st = [angle(Eg); ws; Qg; Pav0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Eset = abs(Eg);
    aux.kS = Pav0/pmp0;
    aux.c0 = Pg - L.s_min(Pg, Pav0);            % exact-equilibrium correction
    ns = 4;
% ------------------------------------------------------------- BESS-GFM --
case 'BESS-GFM'
    p = defp('BESSGFM', prm);
    if isnan(p.Pmax), p.Pmax = 1.5*max(abs(Pg),0.1); end
    Ic = conj(Ssch/Vb); Eg = Vb + (p.Rc+1i*p.Xc)*Ic;
    st = [angle(Eg); ws; Qg; p.SOC0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Eset = abs(Eg);
    [~,Pd0,Pc0] = bess_soc(Pg, p.SOC0, p, L);
    aux.c0 = Pg - L.s_clamp(Pg, -Pc0, Pd0);     % exact-equilibrium correction
    aux.fade0 = L.s_sig((p.SOC0 - p.SOCmin)/p.dSOC)* ...
                L.s_sig((p.SOCmax - p.SOC0)/p.dSOC);
    ns = 4;
% ------------------------------------------------------------- BESS-GFL --
case 'BESS-GFL'
    p = defp('BESSGFL', prm);
    if isnan(p.Pmax), p.Pmax = 1.5*max(abs(Pg),0.1); end
    st = [TH0; 0; Pg/V0; -Qg/V0; p.SOC0; 0; 0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Ilim = irate(S,i,p);
    [~,Pd0,Pc0] = bess_soc(Pg, p.SOC0, p, L);
    aux.c0 = Pg - L.s_clamp(Pg, -Pc0, Pd0);
    ns = 7;
% -------------------------------------------------------------- WT4-GFL --
case 'WT4-GFL'
    p = defp('WT4GFL', prm);
    src = wt_src_init(Pg, p, L);
    st = [TH0; 0; Pg/V0; -Qg/V0; src.wt0; src.wg0; src.ttw0; src.be0; ...
          src.xp0; src.Po0; 0; 0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.src = src;
    aux.Ilim = irate(S,i,p);
    ns = 12;
% -------------------------------------------------------------- WT4-GFM --
case 'WT4-GFM'
    p = defp('WT4GFM', prm);
    src = wt_src_init(Pg, p, L);
    Ic = conj(Ssch/Vb); Eg = Vb + (p.Rc+1i*p.Xc)*Ic;
    st = [angle(Eg); ws; Qg; src.wt0; src.wg0; src.ttw0; src.be0; ...
          src.xp0; src.Po0];
    aux.p = p; aux.Pset = Pg; aux.Qset = Qg; aux.Eset = abs(Eg); aux.src = src;
    ns = 9;
% ------------------------------------------------------------------ WT3 --
case 'WT3'
    p = defp('WT3', prm);
    if isfield(p,'Smach') && ~isempty(p.Smach), scale = p.Smach;
    else, scale = max(abs(Pg)/0.9, 0.1); end    % machine MVA in system pu
    q = im_derived(p, scale);
    src = wt_src_init(Pg, p, L);
    wr0 = src.wg0; s0 = 1 - wr0;
    Ps0 = Pg/(1 - s0); Qs0 = Qg;                % GSC at unity power factor
    iph = conj((Ps0+1i*Qs0)/Vb);
    Ids0 = real(iph); Iqs0 = imag(iph);
    Vd = V0*cos(TH0); Vq = V0*sin(TH0);
    Ed0 = Vd + q.Rs*Ids0 - q.Xp*Iqs0;
    Eq0 = Vq + q.Rs*Iqs0 + q.Xp*Ids0;
    T0p = q.Xrr/(ws*q.Rr); kr = ws*q.Xm/q.Xrr;
    vqr0 = (s0*ws*Eq0 - (Ed0 - (q.X-q.Xp)*Iqs0)/T0p)/kr;
    vdr0 = ((Eq0 + (q.X-q.Xp)*Ids0)/T0p + s0*ws*Ed0)/kr;
    vrc0 = (vdr0 + 1i*vqr0)*exp(-1i*TH0);       % voltage-oriented ctrl frame
    Te0 = Ed0*Ids0 + Eq0*Iqs0;
    st = [Ed0; Eq0; s0; src.wt0; src.ttw0; real(vrc0); imag(vrc0); ...
          src.be0; src.xp0; src.Po0];
    alg = [Ids0; Iqs0]; na = 2;
    aux.p = p; aux.q = q; aux.src = src; aux.kSm = Te0*wr0/src.Po0;
    aux.Pset = Pg; aux.Qset = Qs0;
    ns = 10;
% ------------------------------------------------------------- WT1/WT2 ---
case {'WT1','WT2'}
    p = defp(tag, prm);
    if isfield(p,'Smach') && ~isempty(p.Smach), scale = p.Smach;
    else, scale = max(abs(Pg)/0.9, 0.1); end
    q = im_derived(p, scale);
    [s0, iph] = im_ss_solve(Vb, q, Pg);
    Ids0 = real(iph); Iqs0 = imag(iph);
    Vd = V0*cos(TH0); Vq = V0*sin(TH0);
    Ed0 = Vd + q.Rs*Ids0 - q.Xp*Iqs0;
    Eq0 = Vq + q.Rs*Iqs0 + q.Xp*Ids0;
    Te0 = Ed0*Ids0 + Eq0*Iqs0;
    wr0 = 1 - s0; wt0 = wr0;
    lam0 = p.lam_r*wt0/p.vw0;
    Pm_t = (L.wt_cp(lam0, 0, p.c)/p.Cpmax)*p.vw0^3;
    kSm = Te0*wt0/Pm_t;                         % mechanical scale (exact)
    ttw0 = (Te0/kSm)/p.Ksh;
    P0 = Vd*Ids0 + Vq*Iqs0; Q0 = Vq*Ids0 - Vd*Iqs0;
    st = [Ed0; Eq0; s0; wt0; ttw0];
    alg = [Ids0; Iqs0]; na = 2;
    aux.p = p; aux.q = q; aux.kSm = kSm; aux.vw0 = p.vw0;
    aux.Bcap = (Qg - Q0)/V0^2;                  % compensation capacitor
    ns = 5;
    if strcmp(tag,'WT2')                        % + rotor-resistance control
        aux.Prate = P0/0.9;
        e0 = P0 - aux.Prate; Kaw = 1.0;
        xr = (p.KiR/Kaw)*e0;
        Rmax_rel = p.Rext_max/max(q.Rr,1e-6);
        for it = 1:80
            Rrel = L.s_clamp(xr, 0, Rmax_rel);
            xr = (p.KiR*e0 + Kaw*Rrel)/Kaw;
        end
        aux.cR0 = L.s_clamp(xr, 0, Rmax_rel);   % exact-equilibrium correction
        st = [st; xr]; ns = 6;
    end
% -------------------------------------------- REDUCED-ORDER & PSS SG -----
% Selectable machine fidelity beside the full 11-state SG [Sauer & Pai ch.6,8];
% mirrors psdat/units.py.  All initialise to a machine-precision equilibrium.
case 'SG2'                                       % classical (2-state)
    d = S.MD; Iph = conj(Ssch/Vb);
    E = Vb + (d.Rs(k)+1i*d.Xdp(k))*Iph; D0 = angle(E); Ep = abs(E);
    Id0 = real(Iph*exp(-1i*(D0-pi/2))); Iq0 = imag(Iph*exp(-1i*(D0-pi/2)));
    st = [D0; ws]; alg = [Id0; Iq0]; na = 2;
    aux.Ep = Ep; aux.Pm = Ep*Iq0; ns = 2;
case 'SG4'                                       % two-axis (4-state)
    d = S.MD; Iph = conj(Ssch/Vb);
    E0 = Vb + (d.Rs(k)+1i*d.Xq(k))*Iph; D0 = angle(E0);
    Id0 = real(Iph*exp(-1i*(D0-pi/2))); Iq0 = imag(Iph*exp(-1i*(D0-pi/2)));
    Edp0 = (d.Xq(k)-d.Xqp(k))*Iq0;
    Eqp0 = d.Rs(k)*Iq0 + d.Xdp(k)*Id0 + V0*cos(D0-TH0);
    Efd0 = Eqp0 + (d.Xd(k)-d.Xdp(k))*Id0;
    Pe0 = Edp0*Id0 + Eqp0*Iq0 + (d.Xqp(k)-d.Xdp(k))*Id0*Iq0;
    st = [Eqp0; Edp0; D0; ws]; alg = [Id0; Iq0]; na = 2;
    aux.Efd = Efd0; aux.Pm = Pe0; ns = 4;
case 'SG6'                                       % one-axis flux-decay + IEEE-T1 AVR (6)
    d = S.MD; Iph = conj(Ssch/Vb);
    E0 = Vb + (d.Rs(k)+1i*d.Xq(k))*Iph; D0 = angle(E0);
    Id0 = real(Iph*exp(-1i*(D0-pi/2))); Iq0 = imag(Iph*exp(-1i*(D0-pi/2)));
    Eqp0 = d.Rs(k)*Iq0 + d.Xdp(k)*Id0 + V0*cos(D0-TH0);
    Efd0 = Eqp0 + (d.Xd(k)-d.Xdp(k))*Id0;
    Pe0 = Eqp0*Iq0 + (d.Xq(k)-d.Xdp(k))*Id0*Iq0;
    VR0 = (d.KE(k)+d.Ax(k)*exp(d.Bx(k)*Efd0))*Efd0;
    RF0 = (d.KF(k)/d.TF(k))*Efd0;
    st = [Eqp0; D0; ws; Efd0; RF0; VR0]; alg = [Id0; Iq0]; na = 2;
    aux.Pm = Pe0; aux.Vref = V0 + VR0/d.KA(k); ns = 6;
case 'SG4G'                                      % two-axis + governor (6)
    [s4, alg, aux, ~, na] = init_unit('SG4', i, k, S, prm, L);
    aux.PC = aux.Pm; st = [s4; aux.Pm; aux.Pm]; ns = 6;
case 'SG6G'                                      % one-axis + AVR + governor (8)
    [s6, alg, aux, ~, na] = init_unit('SG6', i, k, S, prm, L);
    aux.PC = aux.Pm; st = [s6; aux.Pm; aux.Pm]; ns = 8;
case 'SGP'                                       % full SG + PSS (14)
    [s11, alg, aux, ~, na] = init_unit('SG', i, k, S, prm, L);
    aux.pss = pss_params(prm); st = [s11; 0; 0; 0]; ns = 14;
case 'SG6P'                                      % one-axis + AVR + PSS (9)
    [s6, alg, aux, ~, na] = init_unit('SG6', i, k, S, prm, L);
    aux.pss = pss_params(prm); st = [s6; 0; 0; 0]; ns = 9;
otherwise
    error('unknown unit tag %s', tag);
end
end

function pp = pss_params(prm)
% PSS parameters (defaults [Larsen & Swann 1981]); mirrors psdat _pss_params.
pp = struct('Kpss',10.0,'Tw',10.0,'T1',0.25,'T2',0.02);
if ~isempty(prm)
    for f = {'Kpss','Tw','T1','T2'}
        if isfield(prm, f{1}) && ~isempty(prm.(f{1})), pp.(f{1}) = prm.(f{1}); end
    end
end
end

% ---------------- default parameter sets (system pu on 100 MVA) ----------
function p = defp(kind, prm)
GFM  = struct('Hv',5,'Dp',20,'wc',31.4,'mq',0.05,'Rc',0.005,'Xc',0.05);
GFL  = struct('Kp',50,'Ki',900,'Ti',0.01);
% IEEE 1547-2018 grid-support defaults (all OFF -> constant P/Q).  Merged only
% into GFL/PV-GFL/BESS-GFL (not wind/PV-GFM), mirroring psdat/units.py.
GS   = struct('qmode',0,'Kqv',0,'Vdb',0,'Qmax',0.44,'Kvw',0,'Vvw',1.06,'Kfw',0,'fdb',0);
GSb  = struct('qmode',0,'Kqv',0,'Vdb',0,'Qmax',0.44,'Kvw',0,'Vvw',1.06); % BESS: freq via native FFR
PV   = struct('voc',1.25,'isc',1.08,'Cdc',0.20,'Kpdc',5,'Kidc',50,'Tm',0.5, ...
              'G0',1.0,'curt',0.10,'Tav',0.2);
BESS = struct('Eh',1.0,'eta',0.95,'SOC0',0.60,'SOCmin',0.10,'SOCmax',0.90, ...
              'dSOC',0.05,'Pmax',NaN,'Kf',15,'db',3e-4,'Tf',0.15,'Tw',0.5,'Kr',0);
WT4  = struct('Ht',4.0,'Hg',0.9,'Ksh',0.3,'Dsh',1.0,'lam_r',8.1,'Cpmax',0.48, ...
              'c',[0.5176 116 0.4 5 21 0.0068],'Kpp',150,'Kip',25,'Tp',0.3, ...
              'bmax',27,'TPo',5.0,'vw0',0.9,'kopt',1.0,'syn_in',0,'Ksi',10,'Tsi',1.0);
WT3  = struct('Rs',0.00706,'Xls',0.171,'Xm',2.9,'Rr',0.005,'Xlr',0.156, ...
              'Ht',4.29,'Hg',0.9,'Ksh',0.3,'Dsh',1.0,'lam_r',8.1,'Cpmax',0.48, ...
              'c',[0.5176 116 0.4 5 21 0.0068],'Kpp',150,'Kip',25,'Tp',0.3, ...
              'bmax',27,'TPo',5.0,'KpT',0.3,'KiT',8,'KpV',0.3,'KiV',8, ...
              'vw0',0.9,'kopt',1.0);
WT1  = struct('Rs',0.0064,'Xls',0.0929,'Xm',3.8,'Rr',0.0088,'Xlr',0.0999, ...
              'Ht',4.0,'Hg',0.6,'Ksh',0.3,'Dsh',1.0,'lam_r',6.3,'Cpmax',0.44, ...
              'c',[0.5176 116 0.4 5 21 0.0068],'vw0',0.9);
switch kind
case 'GFM',     p = GFM;
case 'GFL',     p = mergestruct(GFL, GS);
case 'PVGFL',   p = mergestruct(mergestruct(GFL, PV), GS);
case 'PVGFM',   p = mergestruct(GFM, PV);
case 'BESSGFM', p = mergestruct(GFM, BESS);
case 'BESSGFL', p = mergestruct(mergestruct(GFL, BESS), GSb);
case 'WT4GFL',  p = mergestruct(GFL, WT4);
case 'WT4GFM',  p = mergestruct(GFM, WT4);
case 'WT3',     p = WT3;
case 'WT1',     p = WT1;
case 'WT2',     p = mergestruct(WT1, struct('Rext_max',0.05,'KpR',0.5,'KiR',5));
end
if ~isempty(prm)
    fn = fieldnames(prm);
    for a = 1:numel(fn), p.(fn{a}) = prm.(fn{a}); end
end
end

function s = mergestruct(a, b)
s = a; fn = fieldnames(b);
for k = 1:numel(fn), s.(fn{k}) = b.(fn{k}); end
end

% ---------------- shared init helpers ------------------------------------
function Il = irate(S, i, p)
% unit current limit (system pu): Imax(default 1.2) x rated current,
% rating defaulting to the dispatched |S0| with a 0.3-pu floor
S0 = abs(S.Pg(i) + 1i*S.Qg(i));
if isfield(p,'Sconv') && ~isempty(p.Sconv), Sc = p.Sconv; else, Sc = max(S0,0.3); end
if isfield(p,'Imax'), Im = p.Imax; else, Im = 1.2; end
Il = Im*Sc/max(S.V0(i),0.5);
end

function [fSOC, Pdis, Pchg] = bess_soc(Pe, SOC, p, L)
% battery SOC derivative + smooth capability limits [Plett]
Pb = Pe + (1/p.eta - 1)*L.s_relu(Pe) + (1 - p.eta)*L.s_relu(-Pe);
fSOC = -Pb/(3600*p.Eh*p.Pmax);
Pdis = p.Pmax*L.s_sig((SOC - p.SOCmin)/p.dSOC);
Pchg = p.Pmax*L.s_sig((p.SOCmax - SOC)/p.dSOC);
end

function src = wt_src_init(Pg, p, L)
% Type-3/4 source operating point: MPPT below rated (wg = vw), pitch above
vw0 = p.vw0;
if vw0 <= 1
    wg0 = vw0;
    e0 = wg0 - 1;
    [be0, xp0] = L.pitch_init(e0, p);
else
    wg0 = 1; lo = 0; hi = p.bmax;
    for it = 1:80
        mid = 0.5*(lo+hi);
        if L.wt_pm(1, vw0, mid, p) > 1, lo = mid; else, hi = mid; end
    end
    be0 = 0.5*(lo+hi); xp0 = be0;
end
Pn  = L.wt_pm(wg0, vw0, be0, p);               % actual aero power
kS  = Pg/Pn;
Te0 = Pn/wg0;
Pcl0 = L.s_min(p.kopt*wg0^3, 1.0);
src = struct('vw0',vw0,'wg0',wg0,'wt0',wg0,'ttw0',Te0/p.Ksh,'be0',be0, ...
             'xp0',xp0,'Po0',Pn,'kS',kS,'cPo',Pn - Pcl0);
end

function q = im_derived(p, scale)
% machine-base -> system-base electrical constants (drivetrain stays in
% turbine pu; torques convert through kSm at the interface)
q = p;
q.Rs = p.Rs/scale; q.Xls = p.Xls/scale; q.Xm = p.Xm/scale;
q.Rr = p.Rr/scale; q.Xlr = p.Xlr/scale;
q.X   = q.Xls + q.Xm;
q.Xp  = q.Xls + q.Xm*q.Xlr/(q.Xm + q.Xlr);
q.Xrr = q.Xm + q.Xlr;
end

function [s0, iph] = im_ss_solve(Vb, q, Ptar)
% squirrel-cage steady state from the classical equivalent circuit
% [Kundur sec. 7.2]: bisection on slip so the machine DELIVERS Ptar
Zs = q.Rs + 1i*q.Xls; Zm = 1i*q.Xm;
lo = -0.2; hi = -1e-5;
for it = 1:90
    mid = 0.5*(lo+hi);
    Zr = q.Rr/mid + 1i*q.Xlr;
    Zin = Zs + Zm*Zr/(Zm+Zr);
    Pdel = -real(Vb*conj(Vb/Zin));
    if Pdel > Ptar, lo = mid; else, hi = mid; end
end
s0 = 0.5*(lo+hi);
Zr = q.Rr/s0 + 1i*q.Xlr;
Zin = Zs + Zm*Zr/(Zm+Zr);
iph = -Vb/Zin;                                 % generator convention
end

% ======================= FACTS device helpers ===========================
% Mirror facts.py: SVC = variable shunt susceptance (Q=B|V|^2, constant-impedance
% limit); STATCOM = reactive current source (Q=|V|I, constant-current limit).
function [bt, vm] = facts_pf_setup(bus_type, Vm0, facts, n)
% Before the load flow: each shunt-FACTS PQ bus becomes a voltage-regulated (PV)
% bus at the device Vref, reusing the PV machinery of psdat_powerflow.
bt = bus_type(:); vm = Vm0(:);
for kf = 1:numel(facts)
    if ~any(strcmpi(facts(kf).type,{'SVC','STATCOM'})), continue; end   % series handled separately
    i = round(facts(kf).bus);
    if i>=1 && i<=n
        if bt(i)==1, bt(i)=2; end
        if isfield(facts(kf),'Vref') && ~isempty(facts(kf).Vref), vm(i)=facts(kf).Vref; end
    end
end
end

function [facts, shB, shbus] = facts_oppoint(facts, V0, Qg, skipbus)
% Record each device operating point (B / I / Q + saturation flag) and return
% the equivalent shunt susceptances of the SATURATED devices for the re-solve.
% skipbus (optional): buses whose devices were already fixed at their limit in
% the re-solve -- their operating point is final and must not be recomputed.
if nargin < 4, skipbus = []; end
shB = []; shbus = [];
for kf = 1:numel(facts)
    if ~any(strcmpi(facts(kf).type,{'SVC','STATCOM'})), continue; end   % series carry no bus injection
    i = round(facts(kf).bus);
    if ~isempty(skipbus) && any(i == skipbus), continue; end
    V = max(V0(i),1e-6); Q = Qg(i);
    if strcmpi(facts(kf).type,'SVC')
        lo = facts(kf).Bmin; hi = facts(kf).Bmax;
        B = Q/(V*V); Bs = min(max(B,lo),hi);
        facts(kf).B_ = Bs; facts(kf).Q_ = Bs*V*V;
        facts(kf).sat_ = (B > hi+1e-9) || (B < lo-1e-9);
        if facts(kf).sat_, shB(end+1) = Bs;   shbus(end+1) = i; end %#ok<AGROW>
    else
        lo = facts(kf).Imin; hi = facts(kf).Imax;
        I = Q/V; Is = min(max(I,lo),hi);
        facts(kf).I_ = Is; facts(kf).Q_ = Is*V;
        facts(kf).sat_ = (I > hi+1e-9) || (I < lo-1e-9);
        if facts(kf).sat_, shB(end+1) = Is/V; shbus(end+1) = i; end %#ok<AGROW>
    end
end
end

function [st, aux] = facts_init(fd, S)
% Dynamic init: state (B0 / I0) from the solved reactive output; the regulator
% holds the bus at Vref within its limits (back-calculation anti-windup lives
% in psdat_dae).  Mirrors facts._svc_init / _statcom_init.  A supplementary POD
% controller (if enabled) appends washout + lead-lag states (=0 at equilibrium).
i = round(fd.bus); V0 = S.V0(i); Q0 = S.Qg(i);
if strcmpi(fd.type,'SVC')
    lo = fd.Bmin; hi = fd.Bmax;
    if isfield(fd,'B_') && ~isempty(fd.B_), s0 = fd.B_; else, s0 = Q0/max(V0*V0,1e-6); end
else
    lo = fd.Imin; hi = fd.Imax;
    if isfield(fd,'I_') && ~isempty(fd.I_), s0 = fd.I_; else, s0 = Q0/max(V0,1e-6); end
end
pc = pod_parse(getfld_s(fd,'pod',[]));           % normalized POD config (+ npod)
pc.selfbus = i;                                   % device's own bus (measurement fallback)
% A device saturated in the load flow starts at its wound-up anti-windup
% equilibrium, so rate = (Kr/Tr)*err + Kaw*(sat-st) = 0 EXACTLY in psdat_dae
% (sat stays clamped at the limit; only the internal state carries the wind-up):
sat0 = min(max(s0, lo), hi);
st0  = sat0;
if getfld_s(fd,'sat_',false) && fd.Kaw > 0
    err0 = fd.Vref - V0 - getfld_s(fd,'droop',0)*sat0;
    st0  = sat0 + (fd.Kr/(max(fd.Tr,1e-3)*fd.Kaw))*err0;
end
st = [st0; zeros(pc.npod,1)];                     % regulator + POD sub-states (0)
aux = struct('type',upper(fd.type),'Vref',fd.Vref,'Kr',fd.Kr,'Tr',max(fd.Tr,1e-3), ...
             'Kaw',fd.Kaw,'lo',lo,'hi',hi,'droop',fd.droop,'i',i,'pod',pc);
end

function v = getfld_s(s, f, dv)
if isstruct(s) && isfield(s,f) && ~isempty(s.(f)), v = s.(f); else, v = dv; end
end

function pc = pod_parse(pod)
% Normalize a device's POD sub-struct to a fixed schema + state count.  Mirrors
% facts.pod_cfg / pod_nstate.  npod = [lag?]+washout+nc lead-lag (0 if disabled).
D = struct('on',false,'sig','Vbus','rbus',0,'f',0,'t',0,'i',0,'j',0, ...
           'tau',0,'Tw',10,'T1',0.30,'T2',0.05,'nc',2,'K',0,'lo',-0.10,'hi',0.10, ...
           'ctype','leadlag','Ki',0.5,'Kd',0.05,'Tf',0.02);
fn = fieldnames(D); pc = D;
if isstruct(pod)
    for q = 1:numel(fn)
        if isfield(pod,fn{q}) && ~isempty(pod.(fn{q})), pc.(fn{q}) = pod.(fn{q}); end
    end
end
if ~(islogical(pc.on) && pc.on) && ~(isnumeric(pc.on) && pc.on~=0)
    pc.on = false; pc.npod = 0; pc.s0 = 0; return;
end
pc.on = true;
nlag = double(pc.tau > 1e-9);
pc.nc = max(0, round(pc.nc));
ct = lower(pc.ctype);
if strcmp(ct,'pi'),      pc.npod = nlag + 1;      % lag? + integrator
elseif strcmp(ct,'pid'), pc.npod = nlag + 2;      % lag? + integrator + D filter
else,                    pc.npod = nlag + 1 + pc.nc;   % lag? + washout + nc lead-lag
end
pc.s0 = 0;                                        % filled by the s0 pass in psdat_system
end

function branch = apply_series_m(branch, facts)
% Series FACTS (TCSC/TSSC/SSSC): insert the compensation into the line reactance
% BEFORE the Ybus is built -- x_eff = x*(1-kcomp), clamped to [kmin,kmax].
% Mirrors facts.apply_series of the Python reference.
for kf = 1:numel(facts)
    if ~any(strcmpi(facts(kf).type,{'TCSC','TSSC','SSSC'})), continue; end
    f = round(facts(kf).f); t = round(facts(kf).t); k = 0;
    for kk = 1:size(branch,1)
        bf = round(branch(kk,1)); bt = round(branch(kk,2));
        if (bf==f && bt==t) || (bf==t && bt==f), k = kk; break; end
    end
    if k==0, continue; end
    kc = min(max(facts(kf).kcomp, facts(kf).kmin), facts(kf).kmax);
    branch(k,4) = branch(k,4) * (1 - kc);
end
end

function [facts, Pd, Qd, stamps] = upfc_pq_prepare_m(facts, branch, tap, n, Pd, Qd)
% DC-coupled UPFC (P-Q control mode): decoupled-injection model.  For each such
% UPFC, remove its line f-t (return its admittance stamp to subtract from Ybus),
% draw Pset at the sending bus f and inject Pset+jQset at the receiving bus t, and
% replace the device with a STATCOM at f (holds V, supplies the series real power
% through the DC link).  Byte-for-byte mirror of facts.upfc_pq_prepare / cases.Case.
stamps = {};
if isempty(facts), return; end
keep = true(1,numel(facts)); newstat = {};
for kf = 1:numel(facts)
    d = facts(kf); ty = upper(getfld_s(d,'type',''));
    if ~strcmp(ty,'UPFC'), continue; end
    Ps = getfld_s(d,'Pset',[]); Qs = getfld_s(d,'Qset',[]); md = lower(getfld_s(d,'mode','comp'));
    if isempty(Ps) || isempty(Qs) || ~any(strcmp(md,{'pq','p-q','pqctrl'})), continue; end
    f = round(getfld_s(d,'f',0)); t = round(getfld_s(d,'t',0));
    if f<1 || f>n || t<1 || t>n || f==t, continue; end
    row = 0;
    for kk = 1:size(branch,1)
        bf = round(branch(kk,1)); bt = round(branch(kk,2));
        if (bf==f && bt==t) || (bf==t && bt==f), row = kk; break; end
    end
    if row == 0, continue; end
    tp = 1.0; if ~isempty(tap) && tap(row) ~= 0, tp = tap(row); end
    stamps{end+1} = line_stamp_m(n, branch(row,:), tp);        %#ok<AGROW>
    P = Ps/100; Q = Qs/100;
    Pd(f) = Pd(f) + P;  Pd(t) = Pd(t) - P;  Qd(t) = Qd(t) - Q;
    keep(kf) = false;
    st = d;                              % copy the full union struct -> becomes the shunt regulator
    st.type = 'STATCOM'; st.bus = round(getfld_s(d,'bus',f)); st.droop = 0;
    newstat{end+1} = st;                                       %#ok<AGROW>
end
facts = facts(keep);
for a = 1:numel(newstat), facts(end+1) = newstat{a}; end       %#ok<AGROW>
end

function Y = line_stamp_m(n, brow, tp)
% Y-matrix stamp of ONE branch (subtracted for a UPFC-controlled corridor).
% Mirrors network.line_admittance_stamp / psdat_ybus for a single line.
Y = zeros(n,n);
f = round(brow(1)); t = round(brow(2)); r = brow(3); x = brow(4); b = brow(5);
a = 1.0; if tp ~= 0, a = tp; end
y = 1/(r + 1i*x); bc = 1i*b/2;
Y(f,f) = Y(f,f) + (y+bc)/(a*a);  Y(t,t) = Y(t,t) + y + bc;
Y(f,t) = Y(f,t) - y/conj(a);     Y(t,f) = Y(t,f) - y/a;
end

% ======================= DC-coupled IPFC (P-Q mode) =====================
% Augmented-Newton mirror of facts.ipfc_pq_solve (Python).  Two series voltage
% sources, one per line, sharing a DC link: master (line 1) holds delivered
% S1 = P1set + jQ1set; slave (line 2) holds delivered Q2set and supplies the
% DC-balancing real power P_se2 = -P_se1.  Both lines stay in Ybus; the sources'
% effect is folded in as ΔS load injections at the four terminals.

function [facts, Pd, Qd] = ipfc_pq_prepare_m(facts, Ybus, bus_type, Vm0, ...
                                             gen_bus, Pg, Vg, branch, tap, Pd, Qd, n) %#ok<INUSD>
% For each DC-coupled IPFC (P-Q mode), solve the augmented power flow and add the
% converged ΔS injections to the loads (mirrors the cases.Case IPFC loop).
if isempty(facts), return; end
Pd = Pd(:); Qd = Qd(:);
for kf = 1:numel(facts)
    d = facts(kf); ty = upper(getfld_s(d,'type',''));
    if ~strcmp(ty,'IPFC'), continue; end
    md = lower(getfld_s(d,'mode','comp'));
    if ~any(strcmp(md,{'pq','p-q','pqctrl'})), continue; end
    [dPd, dQd, rep] = ipfc_pq_solve_m(d, Ybus, bus_type, Pd, Qd, Vm0, ...
                                      gen_bus, Pg, Vg, branch, tap);
    Pd = Pd + dPd(:);  Qd = Qd + dQd(:);
    facts(kf).rep = rep;                 % operating point / limit flags for display
end
end

function [dPd, dQd, rep] = ipfc_pq_solve_m(dev, Ybus, bus_type, Pd, Qd, Vm0, ...
                                           gen_bus, Pg, Vg, branch, tap)
n = numel(Pd);
f1 = round(dev.f); t1 = round(dev.t); f2 = round(dev.f2); t2 = round(dev.t2);
r1 = ipfc_row(branch, f1, t1); r2 = ipfc_row(branch, f2, t2);
if r1 == 0 || r2 == 0
    dPd = zeros(n,1); dQd = zeros(n,1); rep = struct('ok',false); return;
end
[y1, bc1] = ipfc_lineyb(branch, r1);
[y2, bc2] = ipfc_lineyb(branch, r2);
P1 = dev.P1set/100; Q1 = dev.Q1set/100; Q2 = dev.Q2set/100;
vmax = 0.30;
if isfield(dev,'Vsemax') && ~isempty(dev.Vsemax), vmax = dev.Vsemax; end
bt = bus_type(:); slack = find(bt==3, 1); pq = find(bt==1);
nonslack = find((1:n)' ~= slack);
Pgb = zeros(n,1);
for k = 1:numel(gen_bus), Pgb(round(gen_bus(k))) = Pg(k); end
Psch = Pgb - Pd(:); Qsch = -Qd(:);
Vfix = Vm0(:);
for k = 1:numel(gen_bus), Vfix(round(gen_bus(k))) = Vg(k); end
nx = numel(nonslack) + numel(pq) + 4;
P = struct('Ybus',Ybus,'Psch',Psch,'Qsch',Qsch,'Vfix',Vfix, ...
           'nonslack',nonslack,'pq',pq,'f1',f1,'t1',t1,'f2',f2,'t2',t2, ...
           'y1',y1,'bc1',bc1,'y2',y2,'bc2',bc2,'n',n,'nx',nx);
% natural corridor flows (Vse = 0) -- the continuation anchor
[V0, TH0] = psdat_powerflow(Ybus, bt, Pd, Qd, Vm0, gen_bus, Pg, Vg, 'nr', branch, tap);
Vc0 = V0(:) .* exp(1i*TH0(:));
S1n = ipfc_deliv(Vc0(f1), Vc0(t1), 0, y1, bc1);
S2n = ipfc_deliv(Vc0(f2), Vc0(t2), 0, y2, bc2);
x = ipfc_pack(TH0, V0, 1e-3+1e-3i, 1e-3+1e-3i, P);
lam = 0.0; dlam = 0.5; nf = 0; cap = 90;
while lam < 1 - 1e-9 && nf < cap
    trial = min(lam + dlam, 1.0);
    [S1t, Q2t] = ipfc_interp(trial, S1n, S2n, P1, Q1, Q2);
    [xn, ok, nf1] = ipfc_newton(x, S1t, Q2t, P); nf = nf + nf1;
    if ok && ipfc_maxvse(xn, P) <= vmax + 1e-9
        lam = trial; x = xn; dlam = min(dlam*1.5, 0.5);
    else
        dlam = dlam * 0.5;
        if dlam < 1e-3                    % boundary -- bisect to the last feasible point
            lo = lam; hi = min(lam + 2*dlam, 1.0);
            for bb = 1:30
                mid = 0.5*(lo + hi);
                [S1t, Q2t] = ipfc_interp(mid, S1n, S2n, P1, Q1, Q2);
                [xm, okm, nf1] = ipfc_newton(x, S1t, Q2t, P); nf = nf + nf1;
                if okm && ipfc_maxvse(xm, P) <= vmax + 1e-9, lo = mid; x = xm;
                else, hi = mid; end
            end
            lam = lo; break;
        end
    end
end
[th, Vm, V1, V2] = ipfc_unpack(x, P); V = Vm .* exp(1i*th);
dS = ipfc_injvec(V, V1, V2, P);
dPd = real(dS); dQd = imag(dS);
S1 = ipfc_deliv(V(f1), V(t1), V1, y1, bc1) * 100;
S2 = ipfc_deliv(V(f2), V(t2), V2, y2, bc2) * 100;
rep = struct('ok',true,'lam',lam,'limited',lam < 1-1e-6, ...
             'saturated',(abs(V1) >= vmax-1e-4) || (abs(V2) >= vmax-1e-4), ...
             'S1',S1,'S2',S2, ...
             'Pse1',ipfc_pse(V(f1),V(t1),V1,y1,bc1)*100, ...
             'Pse2',ipfc_pse(V(f2),V(t2),V2,y2,bc2)*100, ...
             'Vse1',abs(V1),'Vse2',abs(V2),'iters',nf);
end

function [x, ok, nf] = ipfc_newton(x0, S1t, Q2t, P)
x = x0; nf = 0; tol = 1e-11; itmax = 25; nx = P.nx;
for it = 1:itmax
    r = ipfc_resid(x, S1t, Q2t, P); nr = max(abs(r));
    if nr < tol, ok = true; return; end
    J = zeros(nx, nx);
    for j = 1:nx
        xp = x; xp(j) = xp(j) + 1e-7;
        J(:,j) = (ipfc_resid(xp, S1t, Q2t, P) - r) / 1e-7;
    end
    nf = nf + 1;
    dx = J \ (-r);
    if any(~isfinite(dx)), ok = false; return; end
    step = 1.0;                           % backtracking line search
    for ls = 1:20
        if max(abs(ipfc_resid(x + step*dx, S1t, Q2t, P))) < nr, break; end
        step = step * 0.5;
    end
    x = x + step*dx;
end
ok = max(abs(ipfc_resid(x, S1t, Q2t, P))) < 1e-8;
end

function r = ipfc_resid(x, S1t, Q2t, P)
[th, Vm, V1, V2] = ipfc_unpack(x, P); V = Vm .* exp(1i*th);
Sm = V .* conj(P.Ybus * V) + ipfc_injvec(V, V1, V2, P) - (P.Psch + 1i*P.Qsch);
S1 = ipfc_deliv(V(P.f1), V(P.t1), V1, P.y1, P.bc1);
S2 = ipfc_deliv(V(P.f2), V(P.t2), V2, P.y2, P.bc2);
Pse1 = ipfc_pse(V(P.f1), V(P.t1), V1, P.y1, P.bc1);
Pse2 = ipfc_pse(V(P.f2), V(P.t2), V2, P.y2, P.bc2);
r = [real(Sm(P.nonslack)); imag(Sm(P.pq)); ...
     real(S1) - real(S1t); imag(S1) - imag(S1t); imag(S2) - Q2t; Pse1 + Pse2];
end

function x = ipfc_pack(th, Vm, V1, V2, P)
th = th(:); Vm = Vm(:);
x = [th(P.nonslack); Vm(P.pq); real(V1); imag(V1); real(V2); imag(V2)];
end

function [th, Vm, V1, V2] = ipfc_unpack(x, P)
th = zeros(P.n,1); Vm = P.Vfix(:);
nns = numel(P.nonslack); npq = numel(P.pq);
th(P.nonslack) = x(1:nns);
Vm(P.pq) = x(nns+1:nns+npq);
off = nns + npq;
V1 = x(off+1) + 1i*x(off+2);
V2 = x(off+3) + 1i*x(off+4);
end

function dS = ipfc_injvec(V, V1, V2, P)
dS = zeros(P.n,1);
[s1f, s1t] = ipfc_inj(V(P.f1), V(P.t1), V1, P.y1, P.bc1);
[s2f, s2t] = ipfc_inj(V(P.f2), V(P.t2), V2, P.y2, P.bc2);
dS(P.f1) = dS(P.f1) + s1f; dS(P.t1) = dS(P.t1) + s1t;
dS(P.f2) = dS(P.f2) + s2f; dS(P.t2) = dS(P.t2) + s2t;
end

function m = ipfc_maxvse(x, P)
[~, ~, V1, V2] = ipfc_unpack(x, P); m = max(abs(V1), abs(V2));
end

function [S1t, Q2t] = ipfc_interp(lam, S1n, S2n, P1, Q1, Q2)
S1t = (real(S1n) + lam*(P1 - real(S1n))) + 1i*(imag(S1n) + lam*(Q1 - imag(S1n)));
Q2t = imag(S2n) + lam*(Q2 - imag(S2n));
end

function s = ipfc_deliv(Vf, Vt, Vse, y, bc)
% complex power delivered TO the receiving bus by a line with series source
s = Vt * conj(y*(Vf + Vse) - (y + bc)*Vt);
end

function p = ipfc_pse(Vf, Vt, Vse, y, bc)
% real power into the series source
Ef = Vf + Vse;
p = real(Vse * conj((y + bc)*Ef - y*Vt));
end

function [df, dt] = ipfc_inj(Vf, Vt, Vse, y, bc)
% ΔS extra load at the two terminals vs. the plain line in Ybus
df = Vf * conj((y + bc)*Vse);
dt = Vt * conj(-y*Vse);
end

function r = ipfc_row(branch, f, t)
r = 0;
for k = 1:size(branch,1)
    bf = round(branch(k,1)); bt = round(branch(k,2));
    if (bf==f && bt==t) || (bf==t && bt==f), r = k; return; end
end
end

function [y, bc] = ipfc_lineyb(branch, row)
rr = branch(row,3); xx = branch(row,4); bb = branch(row,5);
y = 1/(rr + 1i*xx); bc = 1i*bb/2;
end

% machine (SG) dynamic data now lives in psdat_machinedata.m (shared with
% psdat_benchmark so the benchmark-as-diagram loader never drifts).
