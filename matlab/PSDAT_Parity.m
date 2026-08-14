function ok = PSDAT_Parity()
% PSDAT_PARITY  One-command twin-implementation cross-validation.
%
%   PSDAT_Parity          % prints a PASS/FAIL table; ok = all passed
%
% Runs the MATLAB engine on the bundled benchmarks and compares against
% REFERENCE VALUES frozen from the validated Python edition (generated with
% psdat/{cases,system,simulate,linearize}.py; the two editions share
% byte-identical case data -- IEEE9Bus.m / Kundur2A.m / case68_16m.m were
% verified equal to cases.py field by field).  Checks:
%
%   1. machine dynamic data      (H of every unit, all three benchmarks)
%   2. power flow                (native NR bus voltages + angles)
%   3. small-signal              (least-damped oscillatory mode f, zeta)
%   4. time domain               (COI nadir, sustained 15-MW load step)
%   5. FACTS operating points    (SVC B, STATCOM I, TCSC line flow, P-Q UPFC)
%
% Every tolerance is stated in the table.  Run this after ANY edit to the
% models, the solvers or the case data: a red line here means the editions
% have drifted and the twin-validation claim no longer holds.
% MATPOWER-free: everything runs through psdat_benchmark -> psdat_netcase ->
% psdat_system, the same path the interactive app uses.
fprintf('\nPSDAT twin-implementation parity check (MATLAB engine vs frozen Python references)\n');
fprintf('%s\n', repmat('-',1,86));
T = {}; % {label, value, ref, tol}

% ---------------- frozen references (Python edition) ----------------------
V9r  = [1.0400000000 1.0250000000 1.0250000000 1.0257883928 0.9956308580 ...
        1.0126543240 1.0257693724 1.0158825836 1.0323529490];
TH9r = [0.0000000000 0.1619666503 0.0814152696 -0.0386902459 -0.0696177852 ...
        -0.0643572040 0.0649210323 0.0126979000 0.0343256710];
VKr  = [1.0300000000 1.0100000000 1.0300000000 1.0100000000 1.0063742215 ...
        0.9780249306 0.9608923581 0.9484696562 0.9712623381 0.9833749077 1.0081875077];
V68r = [1.0450000000 0.9806132136 1.0442213283 0.9061746021 0.9482893038]; % buses 1 20 40 60 68
H9r  = [23.64 6.4 3.01];
HKr  = [58.5 58.5 55.575 55.575];
H68r = [42 30.2 35.8 28.6 26 34.8 26.4 24.3 34.5 31 28.2 92.3 248 300 300 225];
M9r  = [1.44431163 7.15714307];     % least-damped osc mode: f (Hz), zeta (%)
MKr  = [0.63100266 3.53477113];     % the Kundur inter-area mode
M68r = [1.26988746 6.97869648];
TDr  = [59.869016 59.869198];       % COI nadir / final (Hz)
SVCr = 0.18883586;  STAr = 0.07971493;  TCSCr = 79.729893;  UPFCr = 1.02600000;

np_ = getappdata(0,'PSDAT_noplot');                 % suppress module figures
setappdata(0,'PSDAT_noplot',1);
cln = onCleanup(@() setappdata(0,'PSDAT_noplot',np_)); %#ok<NASGU>

% ---------------- 1) machine data -----------------------------------------
d9 = psdat_machinedata('IEEE9');   T{end+1} = {'IEEE9    H (3 units)',      mx(d9.H - H9r),   0, 1e-9};
dK = psdat_machinedata('Kundur2A');T{end+1} = {'Kundur2A H (4 units)',      mx(dK.H - HKr),   0, 1e-9};
d6 = psdat_machinedata('case68');  T{end+1} = {'case68   H (16 units)',     mx(d6.H - H68r),  0, 1e-9};

% ---------------- 2) native-NR power flow ---------------------------------
[S9, SK, S68] = deal([]);
try
    C9 = psdat_netcase(psdat_benchmark('IEEE9'));    S9  = psdat_system(C9,  C9.UT,  [], 'nr');
    CK = psdat_netcase(psdat_benchmark('Kundur2A')); SK  = psdat_system(CK,  CK.UT,  [], 'nr');
    C6 = psdat_netcase(psdat_benchmark('case68'));   S68 = psdat_system(C6,  C6.UT,  [], 'nr');
catch err
    fprintf('  !! system build failed: %s\n', err.message);
end
if ~isempty(S9)
    T{end+1} = {'IEEE9    |V| all buses',    mx(S9.V0.'  - V9r),  0, 1e-6};
    T{end+1} = {'IEEE9    angles (rad)',     mx(S9.TH0.' - TH9r), 0, 1e-6};
end
if ~isempty(SK),  T{end+1} = {'Kundur2A |V| all buses',    mx(SK.V0.' - VKr),   0, 1e-6}; end
if ~isempty(S68), T{end+1} = {'case68   |V| (5 sample buses)', mx(S68.V0([1 20 40 60 68]).' - V68r), 0, 1e-6}; end

% ---------------- 3) small-signal: least-damped oscillatory mode ----------
try
    T = modechk(T, 'IEEE9   ', C9, M9r);
    T = modechk(T, 'Kundur2A', CK, MKr);
    T = modechk(T, 'case68  ', C6, M68r);
catch err
    fprintf('  !! linearization failed: %s\n', err.message);
end

% ---------------- 4) time domain: sustained load step ---------------------
try
    D = struct('tsim',15,'dPload',[8 0.15 1.0 inf]);
    o = PSDAT_TimeDomain(C9, C9.UT, D, []);
    T{end+1} = {'IEEE9    TD nadir (Hz)',  min(o.fCOI), TDr(1), 5e-3};
    T{end+1} = {'IEEE9    TD final (Hz)',  o.fCOI(end), TDr(2), 5e-3};
catch err
    fprintf('  !! time domain failed: %s\n', err.message);
end

% ---------------- 5) FACTS operating points -------------------------------
try
    T{end+1} = {'SVC bus 8 (Vref 1.03): B',    fdev('SVC',    struct('bus',8,'Vref',1.03),                    'B_'), SVCr,  1e-5};
    T{end+1} = {'STATCOM bus 6 (1.02):  I',    fdev('STATCOM',struct('bus',6,'Vref',1.02),                    'I_'), STAr,  1e-5};
    T{end+1} = {'TCSC 7-8 (k=0.40): P78 MW',   fflow(struct('type','TCSC','f',7,'t',8,'kcomp',0.4)),                TCSCr, 1e-2};
    T{end+1} = {'P-Q UPFC 7-8: |V7| held',     fupfc(),                                                             UPFCr, 1e-6};
catch err
    fprintf('  !! FACTS check failed: %s\n', err.message);
end

% ---------------- table ----------------------------------------------------
ok = true;
for a = 1:numel(T)
    lbl = T{a}{1}; val = T{a}{2}; ref = T{a}{3}; tol = T{a}{4};
    e = abs(val - ref); pass = e <= tol; ok = ok && pass;
    fprintf('  %-34s  %14.8f  ref %14.8f   |err| %.1e %s  %s\n', ...
        lbl, val, ref, e, tern(e<=tol,'<=','> '), tern(pass,'PASS','FAIL <<<<'));
end
fprintf('%s\n', repmat('-',1,86));
if ok, fprintf('  ALL PASS -- the two editions agree; the twin-validation claim holds.\n\n');
else,  fprintf('  FAILURES above -- the editions have DRIFTED; fix before trusting results.\n\n');
end
end

% ------------------------------------------------------------------------
function v = mx(e), v = max(abs(e(:))); end
function v = tern(c,a,b), if c, v = a; else, v = b; end, end

function T = modechk(T, name, C, ref)
% least-damped oscillatory mode (0.05-6 Hz) of the all-SG fleet
R = PSDAT_Linearization(C, C.UT, []);
lam = R.lambda;
osc = lam(imag(lam) > 2*pi*0.05 & imag(lam) < 2*pi*6);
z = -real(osc)./abs(osc)*100;
[zmin, i0] = min(z);
T{end+1} = {[name ' mode f (Hz)'],   abs(imag(osc(i0)))/2/pi, ref(1), 2e-3};
T{end+1} = {[name ' mode zeta (%)'], zmin,                    ref(2), 5e-2};
end

function N = bench9()
N = psdat_benchmark('IEEE9');
if ~isfield(N,'facts') || isempty(N.facts)     % benchmark ships with no devices
    e = jf('SVC'); e(1) = [];                  % 1x0 struct with the full field union
    N.facts = e;
end
end

function v = fdev(ty, p, fld)
% solved operating point of one shunt device on the drawn IEEE9
N = bench9(); d = jf(ty); d.bus = p.bus; d.Vref = p.Vref;
N.facts(end+1) = orderfields(d, N.facts);
C = psdat_netcase(N); S = psdat_system(C, C.UT, [], 'nr');
v = NaN;
for k = 1:numel(S.facts)
    if isfield(S.facts(k),fld) && ~isempty(S.facts(k).(fld)), v = S.facts(k).(fld); return; end
end
end

function v = fflow(p)
% P (MW) leaving bus f on the compensated line f-t
N = bench9(); d = jf(p.type); d.f = p.f; d.t = p.t; d.kcomp = p.kcomp;
N.facts(end+1) = orderfields(d, N.facts);
C = psdat_netcase(N); S = psdat_system(C, C.UT, [], 'nr');
Vc = S.V0.*exp(1i*S.TH0); v = NaN;
for k = 1:size(S.branch,1)
    fa = round(S.branch(k,1)); ta = round(S.branch(k,2));
    if ~((fa==p.f && ta==p.t) || (fa==p.t && ta==p.f)), continue; end
    r=S.branch(k,3); x=S.branch(k,4); bb=S.branch(k,5); a=S.branch(k,9); if a==0, a=1; end
    y=1/(r+1i*x); bc=1i*bb/2;
    if fa==p.f, v = real(Vc(fa)*conj((y+bc)/(a*a)*Vc(fa) - y/conj(a)*Vc(ta)))*100;
    else,       v = real(Vc(ta)*conj((y+bc)*Vc(ta) - y/a*Vc(fa)))*100; end
    return;
end
end

function v = fupfc()
% DC-coupled P-Q UPFC on 7-8: the shunt converter must hold |V7| at Vref
N = bench9(); d = jf('UPFC');
d.bus = 7; d.f = 7; d.t = 8; d.Vref = 1.026; d.mode = 'pq'; d.Pset = 80; d.Qset = 10;
N.facts(end+1) = orderfields(d, N.facts);
C = psdat_netcase(N); S = psdat_system(C, C.UT, [], 'nr');
v = S.V0(7);
end

function fd = jf(ty)
% one device with the full field union in the editor's field order
ty = upper(ty); kc = 0.4; if strcmp(ty,'UPFC'), kc = 0.3; end
pod = struct('on',false,'sig','Vbus','rbus',0,'f',0,'t',0,'i',0,'j',0,'tau',0, ...
             'Tw',10,'T1',0.30,'T2',0.05,'nc',2,'K',0,'lo',-0.10,'hi',0.10);
fd = struct('type',ty,'bus',0,'Vref',1.0,'Bmax',2,'Bmin',-2,'Imax',2,'Imin',-2, ...
    'Kr',20,'Tr',0.05,'Kaw',150,'droop',0,'signal','V','f',0,'t',0,'kcomp',kc, ...
    'kmin',-0.2,'kmax',0.7,'Tc',0.05,'Vsemax',0.20,'f2',0,'t2',0,'kcomp2',0.2, ...
    'mode','comp','Pset',[],'Qset',[],'P1set',[],'Q1set',[],'Q2set',[], ...
    'pod',pod,'x',0,'y',0);
end
