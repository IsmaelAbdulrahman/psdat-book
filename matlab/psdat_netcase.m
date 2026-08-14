function C = psdat_netcase(NET)
% PSDAT_NETCASE  Turn a drawn single-line diagram into an analyzable case.
%
%   C = psdat_netcase(NET)
%
% Converts the interactive editor's network description NET into a case
% struct C that plugs straight into psdat_system(C, UT, ...).  Mirrors
% net_to_case() + default_md() of the validated Python reference
% (psdat_gui.py) one-for-one, so a network drawn in the MATLAB app and the
% same network drawn in the Python lab produce identical power flows,
% dynamics and eigenvalues.
%
% NET is a struct of parallel arrays (as stored by PSDAT_App in guidata):
%   .name              char, network name
%   .btype  (n x 1)    bus type code: 1=PQ, 2=PV, 3=slack
%   .Pd,.Qd (n x 1)    bus active / reactive load           (MW, MVAr)
%   .Bs     (n x 1)    bus shunt susceptance                (MVAr at 1 pu)
%   .Vset   (n x 1)    bus set / initial voltage            (pu)
%   .g_bus  (m x 1)    terminal bus of each generator       (1-based)
%   .g_tag  (m x 1)    cell of unit tags ('SG','GFM',...)
%   .g_Pg   (m x 1)    scheduled active power               (MW)
%   .g_Vset (m x 1)    generator voltage set point          (pu)
%   .g_S    (m x 1)    generator MVA rating (0 => auto)
%   .g_md   (m x 1)    cell of machine-data structs ([]=default_md)
%   .br_f,.br_t (b x 1) branch from / to buses              (1-based)
%   .br_r,.br_x,.br_b   branch r, x, charging b             (pu)
%   .br_tap (b x 1)    off-nominal tap ratio (0 = nominal)
%
% Returns C with fields consumed by psdat_system:
%   name m n ws baseMVA bus_type Pd Qd Vm0 gen_bus Pg_sched Vg_sched
%   branch tap gs bs MD Sbase_gen UT.

baseMVA = 100; ws = 2*pi*60;
n = numel(NET.btype);
m = numel(NET.g_bus);
if m == 0, error('PSDAT:netcase', 'the network needs at least one generator'); end
if n == 0, error('PSDAT:netcase', 'the network needs at least one bus'); end
nbr = numel(NET.br_f);
if nbr == 0 && n > 1
    error('PSDAT:netcase', 'connect the buses with lines first');
end

% ---- bus types: guarantee exactly one slack -----------------------------
bt = NET.btype(:);
gb = round(NET.g_bus(:));
if sum(bt == 3) == 0
    bt(gb(1)) = 3;                       % no slack -> first generator bus
elseif sum(bt == 3) > 1
    s = find(bt == 3); first = s(1);     % many slacks -> keep the first
    bt(bt == 3) = 2; bt(first) = 3;
end
for k = 1:m                              % every generator bus regulates V
    if bt(gb(k)) == 1, bt(gb(k)) = 2; end
end

% ---- loads, shunts, voltages (to per-unit on 100 MVA) -------------------
Pd  = NET.Pd(:)  / baseMVA;
Qd  = NET.Qd(:)  / baseMVA;
bs  = NET.Bs(:)  / baseMVA;
Vm0 = NET.Vset(:); Vm0(~(Vm0 > 0)) = 1.0;

% ---- branches -----------------------------------------------------------
if nbr > 0
    branch = [NET.br_f(:) NET.br_t(:) NET.br_r(:) NET.br_x(:) NET.br_b(:)];
    tap    = NET.br_tap(:);
    if any(branch(:,4) == 0)
        error('PSDAT:netcase', 'every line needs a nonzero reactance x');
    end
else
    branch = zeros(0,5); tap = zeros(0,1);
end

% ---- generators ---------------------------------------------------------
Pg   = NET.g_Pg(:)   / baseMVA;
Vg   = NET.g_Vset(:); Vg(~(Vg > 0)) = 1.0;
Srat = NET.g_S(:);
for k = 1:m
    if ~(Srat(k) > 0)                    % auto rating (Python: max(|Pg|,50)/0.8)
        Srat(k) = max(abs(NET.g_Pg(k)), 50.0) / 0.8;
    end
end

% ---- machine dynamic data, one column per generator (position k) --------
MD = md_alloc(m);
haveMD = isfield(NET,'g_md') && ~isempty(NET.g_md);
for k = 1:m
    if haveMD && numel(NET.g_md) >= k && ~isempty(NET.g_md{k})
        md = NET.g_md{k};
    else
        md = default_md(Srat(k));
    end
    MD = md_set(MD, k, md);
end

% ---- assemble the case --------------------------------------------------
C = struct();
C.name = NET.name; C.m = m; C.n = n; C.ws = ws; C.baseMVA = baseMVA;
C.bus_type = bt; C.Pd = Pd; C.Qd = Qd; C.Vm0 = Vm0;
C.gen_bus = gb; C.Pg_sched = Pg; C.Vg_sched = Vg;
C.branch = branch; C.tap = tap;
C.gs = zeros(n,1); C.bs = bs;
C.MD = MD; C.Sbase_gen = Srat(:).';
if isfield(NET,'g_tag') && ~isempty(NET.g_tag)
    C.UT = NET.g_tag(:).';
else
    C.UT = repmat({'SG'}, 1, m);
end
% ---- FACTS devices: SHUNT (SVC/STATCOM, at a bus), SERIES (TCSC/TSSC/SSSC, on a
% line) and COMBINED (UPFC/IPFC, expanded here into their STATCOM + SSSC parts,
% mirroring facts.expand_combined).  One struct array with the UNION of fields
% (unused ones empty); psdat_system folds them into the load flow and, for shunt
% devices, the dynamics.
C.facts = mkfact_empty();
if isfield(NET,'facts') && ~isempty(NET.facts)
    for kf = 1:numel(NET.facts)
        d = NET.facts(kf); ty = upper(getfld(d,'type',''));
        if any(strcmpi(ty,{'SVC','STATCOM'}))
            b = round(getfld(d,'bus',0));
            if b>=1 && b<=n
                C.facts(end+1) = mkfact(ty,'bus',b,'Vref',getfld(d,'Vref',1.0), ...
                    'Bmax',getfld(d,'Bmax',2),'Bmin',getfld(d,'Bmin',-2), ...
                    'Imax',getfld(d,'Imax',2),'Imin',getfld(d,'Imin',-2), ...
                    'Kr',getfld(d,'Kr',20),'Tr',getfld(d,'Tr',0.05), ...
                    'Kaw',getfld(d,'Kaw',150),'droop',getfld(d,'droop',0), ...
                    'pod',getfld(d,'pod',[])); %#ok<AGROW>
            end
        elseif any(strcmpi(ty,{'TCSC','TSSC','SSSC'}))
            f = round(getfld(d,'f',0)); t = round(getfld(d,'t',0));
            if f>=1 && f<=n && t>=1 && t<=n && f~=t
                C.facts(end+1) = mkfact(ty,'f',f,'t',t,'kcomp',getfld(d,'kcomp',0.4), ...
                    'kmin',getfld(d,'kmin',-0.2),'kmax',getfld(d,'kmax',0.7), ...
                    'Tc',getfld(d,'Tc',0.02),'Vsemax',getfld(d,'Vsemax',0.2), ...
                    'pod',getfld(d,'pod',[])); %#ok<AGROW>
            end
        elseif any(strcmpi(ty,{'UPFC','IPFC'}))
            % COMBINED (UPFC/IPFC): expand into the STATCOM + SSSC primitives the
            % engine already solves -- mirrors facts.expand_combined() of the
            % Python reference exactly (same default parameters), so a combined
            % device solves identically in both toolboxes.  v1 composes the two
            % verified primitives; common-DC-link real-power coupling is the next
            % refinement.
            if strcmpi(ty,'UPFC')
                b = round(getfld(d,'bus',0)); f = round(getfld(d,'f',0)); t = round(getfld(d,'t',0));
                Ps = getfld(d,'Pset',[]); Qs = getfld(d,'Qset',[]); md = lower(getfld(d,'mode','comp'));
                ispq = ~isempty(Ps) && ~isempty(Qs) && any(strcmp(md,{'pq','p-q','pqctrl'}));
                if b>=1 && b<=n && f>=1 && f<=n && t>=1 && t<=n && f~=t
                    if ispq                                         % DC-coupled P-Q control: keep it for psdat_system
                        C.facts(end+1) = mkfact('UPFC','bus',b,'f',f,'t',t,'Vref',getfld(d,'Vref',1.0), ... %#ok<AGROW>
                            'Imax',getfld(d,'Imax',2),'Imin',getfld(d,'Imin',-2),'Kr',getfld(d,'Kr',20), ...
                            'Tr',getfld(d,'Tr',0.05),'Kaw',getfld(d,'Kaw',150),'droop',getfld(d,'droop',0), ...
                            'Pset',Ps,'Qset',Qs,'mode','pq','pod',getfld(d,'pod',[]));
                    else                                            % composition mode -> STATCOM + SSSC
                        C.facts(end+1) = mkfact('STATCOM','bus',b,'Vref',getfld(d,'Vref',1.0), ...   %#ok<AGROW>
                            'Imax',getfld(d,'Imax',2),'Imin',getfld(d,'Imin',-2), ...
                            'Kr',getfld(d,'Kr',20),'Tr',getfld(d,'Tr',0.05), ...
                            'Kaw',getfld(d,'Kaw',150),'droop',getfld(d,'droop',0), ...
                            'pod',getfld(d,'pod',[]));
                        C.facts(end+1) = mkfact('SSSC','f',f,'t',t,'kcomp',getfld(d,'kcomp',0.3), ... %#ok<AGROW>
                            'kmin',getfld(d,'kmin',-0.2),'kmax',getfld(d,'kmax',0.7),'Vsemax',getfld(d,'Vsemax',0.2));
                    end
                end
            else                                                    % IPFC
                f = round(getfld(d,'f',0)); t = round(getfld(d,'t',0));
                f2 = round(getfld(d,'f2',0)); t2 = round(getfld(d,'t2',0));
                P1 = getfld(d,'P1set',[]); Q1 = getfld(d,'Q1set',[]); Q2 = getfld(d,'Q2set',[]);
                md = lower(getfld(d,'mode','comp'));
                ispq = ~isempty(P1) && ~isempty(Q1) && ~isempty(Q2) && any(strcmp(md,{'pq','p-q','pqctrl'})) ...
                       && f2>=1 && f2<=n && t2>=1 && t2<=n && f2~=t2;
                if f>=1 && f<=n && t>=1 && t<=n && f~=t
                    if ispq                                         % DC-coupled P-Q control: keep both
                        C.facts(end+1) = mkfact('IPFC','f',f,'t',t,'f2',f2,'t2',t2, ...        %#ok<AGROW>
                            'P1set',P1,'Q1set',Q1,'Q2set',Q2,'mode','pq', ...
                            'Vsemax',getfld(d,'Vsemax',0.2));         % lines stay in Ybus, solved in psdat_system
                    else                                            % composition mode -> two SSSC converters
                        C.facts(end+1) = mkfact('SSSC','f',f,'t',t,'kcomp',getfld(d,'kcomp',0.3), ...  %#ok<AGROW>
                            'kmin',getfld(d,'kmin',-0.2),'kmax',getfld(d,'kmax',0.7),'Vsemax',getfld(d,'Vsemax',0.2));
                        if f2>=1 && f2<=n && t2>=1 && t2<=n && f2~=t2
                            C.facts(end+1) = mkfact('SSSC','f',f2,'t',t2,'kcomp',getfld(d,'kcomp2',0.2), ... %#ok<AGROW>
                                'kmin',getfld(d,'kmin',-0.2),'kmax',getfld(d,'kmax',0.7),'Vsemax',getfld(d,'Vsemax',0.2));
                        end
                    end
                end
            end
        end
    end
end
end

function v = getfld(s, f, dv)
if isstruct(s) && isfield(s, f) && ~isempty(s.(f)), v = s.(f); else, v = dv; end
end

function s = mkfact_empty()
s = struct('type',{},'bus',{},'Vref',{},'Bmax',{},'Bmin',{},'Imax',{},'Imin',{}, ...
           'Kr',{},'Tr',{},'Kaw',{},'droop',{},'f',{},'t',{},'kcomp',{}, ...
           'kmin',{},'kmax',{},'Tc',{},'Vsemax',{},'pod',{},'Pset',{},'Qset',{}, ...
           'mode',{},'f2',{},'t2',{},'P1set',{},'Q1set',{},'Q2set',{});
end

function s = mkfact(ty, varargin)
% one FACTS device with the full union of fields (defaults []), then overrides
s = struct('type',upper(ty),'bus',[],'Vref',[],'Bmax',[],'Bmin',[],'Imax',[], ...
           'Imin',[],'Kr',[],'Tr',[],'Kaw',[],'droop',[],'f',[],'t',[], ...
           'kcomp',[],'kmin',[],'kmax',[],'Tc',[],'Vsemax',[],'pod',[], ...
           'Pset',[],'Qset',[],'mode',[],'f2',[],'t2',[],'P1set',[],'Q1set',[],'Q2set',[]);
for a = 1:2:numel(varargin), s.(varargin{a}) = varargin{a+1}; end
end

% =========================================================================
function d = default_md(S)
% DEFAULT_MD  Typical round-number synchronous machine (rating S MVA)
% referred to the 100-MVA system base -- for machines ADDED in the editor.
% Mirrors default_md() in psdat_gui.py exactly.
k = S / 100.0;
d = struct('H',5.0*k, 'Xd',1.8/k, 'Xdp',0.30/k, 'Xdpp',0.25/k, ...
           'Xq',1.7/k, 'Xqp',0.55/k, 'Xqpp',0.25/k, 'Td0p',8.0, ...
           'Td0pp',0.03, 'Tq0p',0.4, 'Tq0pp',0.05, 'Rs',0.0025/k, ...
           'Xls',0.2/k, 'Dm',0.0, 'KA',20.0, 'TA',0.2, 'KE',1.0, ...
           'TE',0.314, 'KF',0.063, 'TF',0.35, 'Ax',0.0039, 'Bx',1.555, ...
           'TCH',0.1, 'TSV',0.05, 'RD',0.05);
end

function f = md_fields()
f = {'H','Xd','Xdp','Xdpp','Xq','Xqp','Xqpp','Td0p','Td0pp','Tq0p', ...
     'Tq0pp','Rs','Xls','Dm','KA','TA','KE','TE','KF','TF','Ax','Bx', ...
     'TCH','TSV','RD'};
end

function MD = md_alloc(m)
f = md_fields(); MD = struct();
for i = 1:numel(f), MD.(f{i}) = zeros(1, m); end
end

function MD = md_set(MD, k, md)
% copy one machine-data struct into column k of the MD arrays
f = md_fields();
for i = 1:numel(f)
    nm = f{i};
    if isfield(md, nm) && ~isempty(md.(nm)), MD.(nm)(k) = md.(nm); end
end
end
