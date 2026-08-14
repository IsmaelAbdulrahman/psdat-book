function out = PSDAT_Linearization(SYS, UT, UTP)
% PSDAT_LINEARIZATION  Small-signal analysis of a mixed-technology system.
%
%   PSDAT_Linearization                          % default demo (see below)
%   PSDAT_Linearization('IEEE9', {'SG','GFM','PV-GFL'})
%   R = PSDAT_Linearization('Kundur2A', {'SG','BESS-GFM','SG','BESS-GFM'})
%
% Builds the system, checks the operating point is an exact equilibrium,
% forms the state matrix by eliminating the algebraic variables
% [Kundur ch. 12; Sauer & Pai ch. 7; PSDAT (OAJPE 2020)]:
%
%       A = fx - fz * inv(gz) * gx
%
% (exact numerical Jacobians, finite differences, ~7-digit accuracy; the
% symbolic route of PSDAT_Symbolic.m gives the same matrix), then prints
% the oscillatory modes with frequency and damping, and computes the
% participation factors of every mode.
%
% Unit tags: SG GFM GFL PV-GFL PV-GFM BESS-GFM BESS-GFL WT4-GFL WT4-GFM
%            WT3 WT1 WT2       (parameters: see psdat_system.m defaults)
%
% Returns out.A, out.lambda, out.freq, out.zeta, out.P (participation),
% out.S (system struct), out.names (state names).
if nargin < 1, SYS = 'IEEE9'; end
if nargin < 2, UT = {'SG','GFM','PV-GFL'}; end
if nargin < 3, UTP = cell(1, numel(UT)); end

S = psdat_system(SYS, UT, UTP);
[f0, g0] = psdat_dae(S.x0, S.z0, S);
res = equilibrium_residual(f0, g0, S);
fprintf('Equilibrium residual (SOC drift excluded): %.2e\n', res);
if res > 1e-6
    warning('operating point is not an exact equilibrium — check the setup');
end

% ---------------- exact numerical Jacobians + state matrix ---------------
Jx = numjac(@(xx) fg(xx, S.z0, S), S.x0);
Jz = numjac(@(zz) fg(S.x0, zz, S), S.z0);
fx = Jx(1:S.NX,:);      gx = Jx(S.NX+1:end,:);
fz = Jz(1:S.NX,:);      gz = Jz(S.NX+1:end,:);
A  = fx - fz*(gz\gx);

% ---------------- modal analysis -----------------------------------------
[VV, DD] = eig(A); lam = diag(DD); W = inv(VV);
freq = abs(imag(lam))/(2*pi);
zeta = -real(lam)./abs(lam)*100; zeta(abs(lam) < 1e-9) = 0;
P = zeros(size(A));
for j = 1:size(A,1)
    pj = abs(VV(:,j).*(W(j,:).'));
    P(:,j) = pj/max(pj);
end
osc = find(imag(lam) > 1e-3 & freq < 6);
[~, ix] = sort(freq(osc));
fprintf('\n%s  [%s]   (%d states, %d unstable)\n', psdat_sysname(SYS), strjoin(UT,','), ...
        size(A,1), sum(real(lam) > 1e-6));
fprintf(' %10s %12s   %s\n','freq(Hz)','damping(%)','eigenvalue');
for j = ix.'
    kk = osc(j);
    fprintf(' %10.4f %12.2f   %9.4f%+9.4fi\n', freq(kk), zeta(kk), ...
            real(lam(kk)), imag(lam(kk)));
end
if ~(exist('psdat_noplot','file') == 2 && psdat_noplot())   % the app draws its own map
    figure; plot(real(lam), imag(lam), 'x', 'MarkerSize', 9, 'LineWidth', 1.6);
    grid on; xlabel('Real (1/s)'); ylabel('Imag (rad/s)');
    title(sprintf('Eigenvalues  %s [ %s ]', psdat_sysname(SYS), strjoin(UT,', ')));
end

out = struct('A',A,'lambda',lam,'freq',freq,'zeta',zeta,'P',P,'S',S, ...
             'fx',fx,'fz',fz,'gx',gx,'gz',gz);
out.names = {state_names(S)};
end

% ------------------------------------------------------------------------
function y = fg(xx, zz, S)
[f, g] = psdat_dae(xx, zz, S);
y = [f; g];
end

function J = numjac(fun, v0)
% dense FD Jacobian -- COOPERATIVE: it pumps the UI (throttled) and honors
% the GUI Stop flag, so a big linearization can always be interrupted and
% never reads as a frozen app.  Standalone runs are unaffected (no status
% handle -> the pump is a cheap no-op; PSDAT_STOP empty -> never trips).
global PSDAT_STOP %#ok<GVMIS>
f0 = fun(v0); N = numel(v0); M = numel(f0); J = zeros(M, N); h = 1e-7;
hs = getappdata(0,'PSDAT_status'); tprev = tic;
for k = 1:N
    vp = v0; vp(k) = vp(k) + h;
    J(:,k) = (fun(vp) - f0)/h;
    if toc(tprev) > 0.4
        tprev = tic;
        if ~isempty(hs) && ishghandle(hs)
            set(hs,'String',sprintf('linearizing...  state %d / %d  (Stop aborts)', k, N));
        end
        drawnow limitrate
        if ~isempty(PSDAT_STOP) && isequal(PSDAT_STOP, true)
            error('psdat:stopped','stopped by user');
        end
    end
end
end

function r = equilibrium_residual(f0, g0, S)
% max |f;g| excluding battery-SOC drift (a pure integrator of power: it
% legitimately drifts while the unit dis/charges)
names = state_names(S);
keep = ~strncmp(names, 'SOC', 3);
r = max([abs(f0(keep(:))); abs(g0)]);
end

function nm = state_names(S)
nm = {};
for k = 1:S.m
    b = S.U(k).bus;
    switch S.U(k).type
    case 'SG',       s = {'Eqp','Si1d','Edp','Si2q','delta','omega','Efd','RF','VR','TM','PSV'};
    case 'SGP',      s = {'Eqp','Si1d','Edp','Si2q','delta','omega','Efd','RF','VR','TM','PSV','Vw','V1','V2'};
    case 'SG6',      s = {'Eqp','delta','omega','Efd','RF','VR'};
    case 'SG6P',     s = {'Eqp','delta','omega','Efd','RF','VR','Vw','V1','V2'};
    case 'SG6G',     s = {'Eqp','delta','omega','Efd','RF','VR','TM','PSV'};
    case 'SG4',      s = {'Eqp','Edp','delta','omega'};
    case 'SG4G',     s = {'Eqp','Edp','delta','omega','TM','PSV'};
    case 'SG2',      s = {'delta','omega'};
    case 'GFM',      s = {'dg','wg','Qf'};
    case 'GFL',      s = {'thpll','xpll','id','iq'};
    case 'PV-GFL',   s = {'thpll','xpll','id','iq','Vdc','xdc','vref'};
    case 'PV-GFM',   s = {'dg','wg','Qf','Pav'};
    case 'BESS-GFM', s = {'dg','wg','Qf','SOC'};
    case 'BESS-GFL', s = {'thpll','xpll','id','iq','SOC','xw','Pf'};
    case 'WT4-GFL',  s = {'thpll','xpll','id','iq','wt','wg','ttw','beta','xp','Po','xw','Psi'};
    case 'WT4-GFM',  s = {'dg','wgc','Qf','wt','wg','ttw','beta','xp','Po'};
    case 'WT3',      s = {'Edp','Eqp','slip','wt','ttw','xP','xQ','beta','xp','Po'};
    case 'WT1',      s = {'Edp','Eqp','slip','wt','ttw'};
    case 'WT2',      s = {'Edp','Eqp','slip','wt','ttw','xR'};
    end
    for a = 1:numel(s), nm{end+1} = sprintf('%s%d', s{a}, b); end %#ok<AGROW>
end
% ---- FACTS states appended after the machines (see psdat_system) --------
% shunt regulators (B for an SVC, I for a STATCOM) + their POD sub-states,
% then dynamic series compensation states k(t) + POD.  Keeping the name
% list exactly NX long makes participation tables and the SOC mask correct
% with devices on the diagram.
if isfield(S,'Facts')
    for kf = 1:numel(S.Facts)
        if strcmpi(S.Facts(kf).type,'SVC'), base = sprintf('Bsvc%d', S.Facts(kf).bus);
        else,                               base = sprintf('Istat%d', S.Facts(kf).bus); end
        nm{end+1} = base;                                              %#ok<AGROW>
        for a = 1:(numel(S.Facts(kf).xidx)-1)
            nm{end+1} = sprintf('%s_pod%d', base, a);                  %#ok<AGROW>
        end
    end
end
if isfield(S,'SF')
    for kf = 1:numel(S.SF)
        base = sprintf('kser%d_%d', S.SF(kf).f, S.SF(kf).t);
        nm{end+1} = base;                                              %#ok<AGROW>
        for a = 1:(numel(S.SF(kf).xidx)-1)
            nm{end+1} = sprintf('%s_pod%d', base, a);                  %#ok<AGROW>
        end
    end
end
end
