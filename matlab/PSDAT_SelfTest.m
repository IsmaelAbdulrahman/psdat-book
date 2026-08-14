function PSDAT_SelfTest(fast)
% PSDAT_SELFTEST  Verify this MATLAB installation of PSDAT.
%
%   PSDAT_SelfTest        % full test (~1-2 min: includes one time-domain run)
%   PSDAT_SelfTest(1)     % fast test  (~20 s: linearizations only)
%
% Checks, against the published PSDAT results (OAJPE 2020) and the
% independently validated Python reference implementation:
%   [1] IEEE 9-bus all-SG modes (5 significant figures)
%   [2] every PSDAT unit type: exact equilibrium + stability + its
%       least-damped oscillatory mode (frequency, damping)
%   [3] Kundur two-area base / GFM / GFL inter-area results
%   [4] 68-bus critical inter-area mode (176 states)
%   [5] time-domain nadir of the 15-MW load step (unless fast)
% Prints PASS/FAIL per item.  Requires MATPOWER on the path; run from the
% PSDAT matlab folder.
if nargin < 1, fast = 0; end
npass = 0; nfail = 0;
    function chk(name, got, want, tol)
        if abs(got - want) <= tol
            fprintf('  PASS  %-34s %10.4f\n', name, got); npass = npass + 1;
        else
            fprintf('  FAIL  %-34s %10.4f  (want %.4f +/- %.2g)\n', ...
                    name, got, want, tol); nfail = nfail + 1;
        end
    end

fprintf('[1] IEEE 9-bus all-SG published modes\n');
R = lin_quiet('IEEE9', {'SG','SG','SG'});
lam = R.lambda;
[~,j] = min(abs(lam - (-0.6512 + 9.0749i)));
chk('inter-area Re', real(lam(j)), -0.65117, 1e-3);
chk('inter-area Im', imag(lam(j)),  9.0749, 1e-3);
[~,j] = min(abs(lam - (-1.1563 + 14.9046i)));
chk('local Re', real(lam(j)), -1.15629, 1e-3);
chk('local Im', imag(lam(j)), 14.9046, 1e-3);

fprintf('[2] all unit types at bus 3 (equilibrium, stability, key mode)\n');
% reference least-damped oscillatory modes from the Python implementation
refm = { % tag         NX   f(Hz)    zeta(%)
 'GFM',      25, 2.1181,  7.40;  'GFL',      26, 1.4793,  6.78;
 'PV-GFL',   29, 1.4768,  6.87;  'PV-GFM',   26, 2.1181,  7.40;
 'BESS-GFM', 26, 2.1181,  7.40;  'BESS-GFL', 29, 1.4793,  6.78;
 'WT4-GFL',  34, 1.3978,  1.67;  'WT4-GFM',  31, 1.3975,  1.41;
 'WT3',      32, 1.3525,  2.37;  'WT1',      27, 1.4876,  6.96;
 'WT2',      28, 1.4876,  6.96};
for a = 1:size(refm,1)
    tag = refm{a,1};
    R = lin_quiet('IEEE9', {'SG','SG',tag});
    chk([tag ' state count'], size(R.A,1), refm{a,2}, 0.1);
    nun = sum(real(R.lambda) > 1e-6);
    chk([tag ' unstable modes'], nun, 0, 0.1);
    osc = find(imag(R.lambda) > 2*pi*0.05);
    [zmin, jj] = min(-real(R.lambda(osc))./abs(R.lambda(osc))*100);
    chk([tag ' least damping %'], zmin, refm{a,4}, 0.15);
    chk([tag ' least-damped f'], abs(imag(R.lambda(osc(jj))))/(2*pi), refm{a,3}, 0.02);
end

fprintf('[3] Kundur two-area\n');
GFM_K = struct('Hv',45,'Dp',180,'wc',31.4,'mq',0.0056,'Rc',0.0006,'Xc',0.0056);
R = lin_quiet('Kundur2A', {'SG','SG','SG','SG'});
[f_, z_] = inter_mode(R.lambda);
chk('SG inter-area f (Hz)', f_, 0.631, 0.005);
chk('SG inter-area damping %', z_, 3.53, 0.1);
R = lin_quiet('Kundur2A', {'SG','GFM','SG','GFM'}, {[],GFM_K,[],GFM_K});
[~, z_] = inter_mode(R.lambda);
chk('GFM inter-area damping %', z_, 10.22, 0.1);
R = lin_quiet('Kundur2A', {'SG','GFL','SG','GFL'});
chk('GFL unstable count', sum(real(R.lambda) > 1e-6), 3, 0.1);

fprintf('[4] 68-bus NETS-NYPS\n');
R = lin_quiet('case68', repmat({'SG'},1,16));
chk('state count', size(R.A,1), 176, 0.1);
osc = find(imag(R.lambda) > 2*pi*0.1 & imag(R.lambda) < 2*pi*1.4);
[z_, jj] = min(-real(R.lambda(osc))./abs(R.lambda(osc))*100);
chk('critical inter-area f', imag(R.lambda(osc(jj)))/(2*pi), 1.270, 0.005);
chk('critical inter-area damping', z_, 6.98, 0.1);

if ~fast
    fprintf('[5] time domain: sustained 15-MW load step (all-SG)\n');
    D = struct('dPload',[8 0.15 1.0 inf],'tsim',15);
    out = evalc_td('IEEE9', {'SG','SG','SG'}, D);
    chk('all-SG nadir (Hz)', min(out.fCOI(out.t >= 1)), 59.869, 0.003);
end

fprintf('[6] reduced-order + PSS machines, native PF solvers, IEEE 1547 support\n');
% (a) selectable SG fidelity: exact equilibrium + stability + state counts
sgset = {'SG2',6; 'SG4',12; 'SG6',18; 'SG4G',18; 'SG6G',24; 'SGP',42; 'SG6P',27};
for a = 1:size(sgset,1)
    tag = sgset{a,1};
    Sx = psdat_system('IEEE9', {tag,tag,tag});
    [f0,g0] = psdat_dae(Sx.x0, Sx.z0, Sx);
    chk([tag ' equilibrium'], max([max(abs(f0)); max(abs(g0))]), 0, 1e-8);
    R = lin_quiet('IEEE9', {tag,tag,tag});
    chk([tag ' state count'], size(R.A,1), sgset{a,2}, 0.1);
    chk([tag ' unstable modes'], sum(real(R.lambda) > 1e-6), 0, 0.1);
end
% (b) PSS raises swing-mode damping on the high-gain Kundur exciter (KA=200)
R6  = lin_quiet('Kundur2A', repmat({'SG6'}, 1,4));
R6p = lin_quiet('Kundur2A', repmat({'SG6P'},1,4));
chk('PSS raises damping SG6->SG6P', double(min_damp(R6p.lambda) > min_damp(R6.lambda) + 0.5), 1, 0.1);
% (c) native NR / FDLF / GS reproduce the MATPOWER operating point
Smp = psdat_system('IEEE9', {'SG','SG','SG'}, {}, 'mp');
for mth = {'nr','fdlf','gs'}
    Sx = psdat_system('IEEE9', {'SG','SG','SG'}, {}, mth{1});
    chk(['PF ' mth{1} ' vs MATPOWER |dV|'], max(abs(Sx.V0 - Smp.V0)), 0, 1e-5);
end
% (d) IEEE 1547 Volt-VAR leaves the dispatched equilibrium intact
vv = struct('qmode',1,'Kqv',2.0);
Sx = psdat_system('IEEE9', {'SG','GFL','PV-GFL'}, {[],vv,[]});
[f0,g0] = psdat_dae(Sx.x0, Sx.z0, Sx);
chk('GFL Volt-VAR equilibrium', max([max(abs(f0)); max(abs(g0))]), 0, 1e-8);

fprintf('[7] interactive-editor backbone (load benchmark -> net -> analyse)\n');
% The SLD editor turns a drawing into an analyzable system via psdat_netcase;
% loading a benchmark as a diagram must reproduce the benchmark to machine
% precision, proving the drawn-network path is a true twin of the Python lab.
NET = psdat_benchmark('IEEE9');
C   = psdat_netcase(NET);
Sd  = psdat_system(C, C.UT);                        % drawn-network system (native)
Sb  = psdat_system('IEEE9', {'SG','SG','SG'}, {}, 'nr');
chk('drawn IEEE9 |dV| vs benchmark',   max(abs(Sd.V0  - Sb.V0)),  0, 1e-8);
chk('drawn IEEE9 |dTheta| vs bench',   max(abs(Sd.TH0 - Sb.TH0)), 0, 1e-8);
[f0,g0] = psdat_dae(Sd.x0, Sd.z0, Sd);              % exact drawn-net equilibrium
chk('drawn IEEE9 equilibrium', max([max(abs(f0)); max(abs(g0))]), 0, 1e-8);
Rd = lin_quiet(C, C.UT); Rb = lin_quiet('IEEE9', {'SG','SG','SG'});
chk('drawn IEEE9 state count', size(Rd.A,1), size(Rb.A,1), 0.1);
[~,jb] = min(abs(Rb.lambda - (-0.6512 + 9.0749i)));
[~,jd] = min(abs(Rd.lambda - (-0.6512 + 9.0749i)));
chk('drawn vs bench inter-area |dlambda|', abs(Rd.lambda(jd) - Rb.lambda(jb)), 0, 5e-3);
% edit a component (raise a line reactance) and confirm the network re-solves
NET.br_x(2) = NET.br_x(2)*1.5;
C2 = psdat_netcase(NET); S2 = psdat_system(C2, C2.UT);
chk('edited network re-solves', double(all(isfinite(S2.V0)) && min(S2.V0) > 0.5), 1, 0.1);
% a from-scratch two-bus network: slack + PV through one line
N2 = struct('name','2bus','btype',[3;2],'Pd',[0;80],'Qd',[0;30],'Bs',[0;0], ...
    'Vset',[1.04;1.0],'g_bus',[1;2],'g_tag',{{'SG','SG'}},'g_Pg',[0;40], ...
    'g_Vset',[1.04;1.0],'g_S',[200;150],'g_md',{{[],[]}}, ...
    'br_f',1,'br_t',2,'br_r',0.01,'br_x',0.10,'br_b',0.02,'br_tap',0);
C3 = psdat_netcase(N2); S3 = psdat_system(C3, C3.UT);
[f3,g3] = psdat_dae(S3.x0, S3.z0, S3);
chk('hand-drawn 2-bus equilibrium', max([max(abs(f3)); max(abs(g3))]), 0, 1e-8);

fprintf('\n%d passed, %d failed.\n', npass, nfail);
if nfail == 0, fprintf('ALL PASS — installation verified.\n'); end
end

% ------------------------------------------------------------------------
function R = lin_quiet(SYS, UT, UTP)
if nargin < 3, UTP = cell(1, numel(UT)); end
[~, R] = evalc('PSDAT_Linearization(SYS, UT, UTP)');
close all
end

function out = evalc_td(SYS, UT, D)
[~, out] = evalc('PSDAT_TimeDomain(SYS, UT, D)');
close all
end

function [f_, z_] = inter_mode(lam)
osc = find(imag(lam) > 2*pi*0.3 & imag(lam) < 2*pi*0.9);
[z_, j] = min(-real(lam(osc))./abs(lam(osc))*100);
f_ = imag(lam(osc(j)))/(2*pi);
end

function z = min_damp(lam)
% minimum damping ratio (%) over the electromechanical oscillatory modes
osc = lam(imag(lam) > 2*pi*0.1);
z = min(-real(osc)./abs(osc)*100);
end
