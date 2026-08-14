function out = PSDAT_TimeDomain(SYS, UT, DIST, UTP)
% PSDAT_TIMEDOMAIN  Nonlinear time-domain simulation (ode15s, DAE).
%
%   PSDAT_TimeDomain                       % default demo: PV cloud transient
%   PSDAT_TimeDomain('IEEE9', {'SG','GFM','PV-GFL'}, DIST)
%
% DIST selects the disturbance (struct; leave fields out for none).  The
% THREE disturbance classes of PSDAT:
%
%  NETWORK-SIDE
%   DIST.fault    = [bus  Xf  ton  toff]   3-ph fault through jXf (pu)
%   DIST.linetrip = [fbus tbus ton toff]   line outage (reclosed at toff)
%   DIST.dPload   = [bus  dP  ton  toff]   load change (toff=inf: sustained)
%  GENERATOR-SIDE
%   DIST.dPgen    = [unit dP  ton  toff]   set-point / mech-power pulse
%  SOURCE-SIDE (new in PSDAT — the renewable resource is the disturbance)
%   DIST.cloud    = [unit depth t0]        irradiance dip (PV units)
%   DIST.gust     = [unit A t0]            IEC gust (wind units)
%   DIST.vwramp   = [unit dv t0 t1]        wind ramp
%
% tsim via DIST.tsim (default 12 s).  Events use smooth 50-ms ramps and the
% integration restarts at each event time (multistep DAE solvers stall on
% mid-step discontinuities — the implicit-solver method of PSDAT).
%
% Examples:
%   D.fault = [8 0.15 1.0 1.1];  PSDAT_TimeDomain('IEEE9',{'SG','SG','SG'},D)
%   D.cloud = [3 0.5 2.0];  PSDAT_TimeDomain('IEEE9',{'SG','SG','PV-GFL'},D)
%   D.gust  = [3 0.12 2.0]; PSDAT_TimeDomain('IEEE9',{'SG','SG','WT3'},D)
if nargin < 1, SYS = 'IEEE9'; end
if nargin < 2, UT = {'SG','SG','PV-GFL'}; end
if nargin < 3 || isempty(DIST), DIST = struct('cloud',[3 0.5 2.0]); end
if nargin < 4, UTP = cell(1, numel(UT)); end
tsim = 12; if isfield(DIST,'tsim'), tsim = DIST.tsim; end

% Cooperative-cancel flag shared with the GUI Stop button (PSDAT_App:onStop).
% ode15s calls odeStop after every accepted step; that pumps drawnow so the
% Stop button can fire and, once this flag is set, halts with partial output.
global PSDAT_STOP PSDAT_TDMON %#ok<GVMIS>
PSDAT_STOP = false;
% Run monitor: live progress + a hard WALL-CLOCK budget, so no pathological
% case (a pole-slipping trajectory ground at micro-steps, a stiff corner the
% solver cannot pass) can ever freeze the caller -- the run always ends with
% a partial result and an honest message.  The GUI publishes its status-line
% handle in appdata; standalone runs just skip the on-screen updates.
wall = 600;                        % standalone default: generous (long studies)
if isfield(DIST,'walltime') && ~isempty(DIST.walltime), wall = DIST.walltime; end
PSDAT_TDMON = struct('t0',tic,'budget',wall,'lastdraw',-1,'lastmsg',-1, ...
                     'status',getappdata(0,'PSDAT_status'),'timedout',false);

S = psdat_system(SYS, UT, UTP);
fprintf('Simulating %s [%s]  (%d diff + %d alg states)...\n', psdat_sysname(SYS), ...
        strjoin(UT,','), S.NX, S.NZ);

% ---------------- disturbance machinery ----------------------------------
tr = 0.05;                                    % smooth event ramp (s)
sramp = @(t,t0) 0.5*(1 - cos(pi*min(max((t-t0)/tr,0),1)));
events = [];
if isfield(DIST,'fault')
    fb = DIST.fault(1); Yf = 1/(1i*DIST.fault(2));
    tf1 = DIST.fault(3); tf2 = DIST.fault(4); events = [events tf1 tf2];
else, fb = []; end
if isfield(DIST,'linetrip')
    lt = DIST.linetrip; events = [events lt(3) lt(4)];
    Ytrip = -line_stamp(S, lt(1), lt(2));
else, lt = []; end
if isfield(DIST,'dPload')
    dl = DIST.dPload; events = [events dl(3) min(dl(4),tsim)];
else, dl = []; end
if isfield(DIST,'dPgen')
    dg = DIST.dPgen; events = [events dg(3) min(dg(4),tsim)];
else, dg = []; end
Gfun = []; vwfun = [];
if isfield(DIST,'cloud')
    kc = DIST.cloud(1);
    Gfun = @(t) cloud_profile(t, DIST.cloud(3), DIST.cloud(2));
    events = [events DIST.cloud(3)];
end
if isfield(DIST,'gust')
    kg = DIST.gust(1); u0 = S.U(kg).aux;
    base = src_vw0(S, kg);
    vwfun = @(t) gust_profile(t, DIST.gust(3), DIST.gust(2), base);
    events = [events DIST.gust(3)];
end
if isfield(DIST,'vwramp')
    kg = DIST.vwramp(1); base = src_vw0(S, kg);
    vwfun = @(t) base + DIST.vwramp(2)* ...
        min(max((t-DIST.vwramp(3))/(DIST.vwramp(4)-DIST.vwramp(3)),0),1);
    events = [events DIST.vwramp(3) DIST.vwramp(4)];
end

    function uu = u_of_t(t)
        uu = struct();
        if ~isempty(dl)
            uu.dPload = zeros(S.n,1);
            uu.dPload(dl(1)) = dl(2)*(sramp(t,dl(3)) - sramp(t,dl(4)));
        end
        if ~isempty(dg)
            uu.dPu = zeros(1,S.m);
            uu.dPu(dg(1)) = dg(2)*(sramp(t,dg(3)) - sramp(t,dg(4)));
        end
        Ye = zeros(S.n);  any_ = false;
        if ~isempty(fb)
            Ye(fb,fb) = Ye(fb,fb) + Yf*(sramp(t,tf1) - sramp(t,tf2)); any_ = true;
        end
        if ~isempty(lt)
            Ye = Ye + Ytrip*(sramp(t,lt(3)) - sramp(t,lt(4))); any_ = true;
        end
        if any_, uu.Yextra = Ye; end
        if ~isempty(Gfun),  uu.G = nan(1,S.m);  uu.G(kc)  = Gfun(t);  end
        if ~isempty(vwfun), uu.vw = nan(1,S.m); uu.vw(kg) = vwfun(t); end
    end

% ---------------- ode15s on the singular-mass DAE ------------------------
M0 = spdiags([ones(S.NX,1); zeros(S.NZ,1)], 0, S.NX+S.NZ, S.NX+S.NZ);
opt = odeset('Mass', M0, 'MassSingular', 'yes', 'MStateDependence', 'none', ...
             'MaxStep', 1e-2, 'RelTol', 1e-6, 'AbsTol', 1e-8, 'OutputFcn', @odeStop);
odef = @(t, y) rhs(t, y, S, @u_of_t);
brk = unique([0, events(events > 0 & events < tsim), tsim]);
t = []; y = []; yc = [S.x0; S.z0];
yc = consistent_ic(yc, S, u_of_t(0));   % polish the algebraic start so ode15s accepts it
% JACOBIAN: on large fleets the dense finite-difference Jacobian IS the
% runtime (one RHS call per state per refresh -- 344 on the 68-bus system --
% and the disturbed segments refresh constantly, so the wall budget expired
% right at the first event edge with only the flat pre-fault trace to show).
% MATLAB's own numjac/JPattern route proved RELEASE-DEPENDENT with a singular
% mass matrix, so PSDAT now computes the Jacobian ITSELF and hands the
% finished matrix to ode15s via odeset('Jacobian',...), bypassing numjac
% entirely: the structural pattern is detected numerically once, its columns
% are greedy-colored into independent groups (disjoint row sets), and every
% refresh perturbs one GROUP at a time -- 13 model evaluations instead of 344
% on case68, verified IDENTICAL to the dense matrix on the twin Python
% engine.  The same full sweep that detects the pattern also yields the exact
% dense Jacobian, so the setup cross-checks the colored evaluation against it
% and quietly stays on plain dense differences if anything disagrees.  Event
% admittance changes only re-VALUE existing couplings (fault shunt / line
% trip touch in-service network entries; load/set-point steps are additive),
% so the base-case pattern stays valid for the whole run.
if S.NX + S.NZ > 120
    try
        [CJ, Jd] = dae_colored_setup(S, yc, u_of_t(0));
        Jc  = dae_jac_colored(0, yc, S, @u_of_t, CJ);
        dev = max(max(abs(full(Jc) - Jd)));
        scl = max(1, max(max(abs(Jd))));
        if ~isfinite(dev) || dev > 1e-4*scl
            error('psdat:coloredjac', 'colored/dense mismatch %.3g', dev);
        end
        optJ = odeset(opt, 'Jacobian', @(tt, yy) dae_jac_colored(tt, yy, S, @u_of_t, CJ));
        % PRE-FLIGHT: one tiny probe integration proves this MATLAB release
        % accepts a user-supplied sparse Jacobian with the singular mass
        % matrix; any objection -> quietly continue on dense differences.
        ode15s(odef, [0 1e-4], yc, optJ);
        opt = optJ;
        fprintf('   (colored-FD Jacobian active: %d groups for %d states, checked vs dense: %.1e)\n', ...
                numel(CJ.grp), S.NX + S.NZ, dev/scl);
    catch
        fprintf('   (colored Jacobian unavailable here -- continuing with dense differences)\n');
    end
end
stiff = false;
for sgi = 1:numel(brk)-1
    t2 = brk(sgi+1);
    [ts, yseg] = ode15s(odef, [brk(sgi) t2], yc, opt);
    stopped_now = ~isempty(PSDAT_STOP) && PSDAT_STOP;
    tout = isstruct(PSDAT_TDMON) && isfield(PSDAT_TDMON,'timedout') && PSDAT_TDMON.timedout;
    short = isempty(ts) || ts(end) < t2 - 1e-9;
    if short && ~stopped_now && ~tout && ~isempty(ts)
        % The solver gave up inside the segment (a stiff spot at an event
        % edge).  Re-polish the algebraic block at the last accepted point --
        % against the disturbance inputs ACTIVE AT THAT INSTANT, never the
        % undisturbed network -- and retry the remainder with a finer step cap.
        ycr = consistent_ic(yseg(end,:).', S, u_of_t(ts(end)));
        optf = odeset(opt, 'MaxStep', 1e-3, 'InitialStep', 1e-6);
        [ts2, yseg2] = ode15s(odef, [ts(end) t2], ycr, optf);
        if numel(ts2) > 1
            ts = [ts; ts2(2:end)]; yseg = [yseg; yseg2(2:end,:)]; %#ok<AGROW>
        end
        stopped_now = ~isempty(PSDAT_STOP) && PSDAT_STOP;
        tout = isstruct(PSDAT_TDMON) && isfield(PSDAT_TDMON,'timedout') && PSDAT_TDMON.timedout;
        short = ts(end) < t2 - 1e-9;
    end
    if isempty(t), t = ts; y = yseg;
    else, t = [t; ts(2:end)]; y = [y; yseg(2:end,:)]; end %#ok<AGROW>
    if isempty(ts), stiff = true; break; end
    yc = yseg(end,:).';
    if stopped_now || tout, break; end           % Stop / wall budget -> keep the partial result
    if short, stiff = true; break; end           % never integrate the NEXT segment from a bad state
end
X = y(:, 1:S.NX);

% ---------------- centre-of-inertia frequency ----------------------------
num = zeros(size(t)); den = 0;
for k = 1:S.m
    switch S.U(k).type
    case {'SG','SGP'}                        % omega = state 6
        w = X(:, S.U(k).xidx(6)); Mi = 2*S.MD.H(k)*S.Sbase_gen(k);
    case {'SG6','SG6G','SG6P'}               % omega = state 3
        w = X(:, S.U(k).xidx(3)); Mi = 2*S.MD.H(k)*S.Sbase_gen(k);
    case {'SG4','SG4G'}                       % omega = state 4
        w = X(:, S.U(k).xidx(4)); Mi = 2*S.MD.H(k)*S.Sbase_gen(k);
    case 'SG2'                                % omega = state 2
        w = X(:, S.U(k).xidx(2)); Mi = 2*S.MD.H(k)*S.Sbase_gen(k);
    case {'GFM','PV-GFM','BESS-GFM','WT4-GFM'}
        w = X(:, S.U(k).xidx(2)); Mi = 2*S.U(k).aux.p.Hv*S.Sbase_gen(k);
    otherwise, continue;
    end
    num = num + Mi*w; den = den + Mi;
end
if den > 0
    fCOI = (num/den)/(2*pi);
    % (exist-guard: stays quiet even if this file is run from a stale path
    %  where the psdat_noplot helper has not been picked up yet)
    if ~(exist('psdat_noplot','file') == 2 && psdat_noplot())
        figure; plot(t, fCOI, 'LineWidth', 2); grid on; set(gca,'FontSize',13);
        xlabel('Time (s)'); ylabel('COI frequency (Hz)');
        title(sprintf('%s  [ %s ]', psdat_sysname(SYS), strjoin(UT,', ')));
    end
    fprintf('Nadir = %.4f Hz,  final = %.4f Hz\n', min(fCOI), fCOI(end));
else
    fCOI = [];
end
out = struct('t',t,'X',X,'Z',y(:,S.NX+1:end),'fCOI',fCOI,'S',S, ...
             'stopped', ~isempty(PSDAT_STOP) && PSDAT_STOP, 'stiff', stiff, ...
             'timeout', isstruct(PSDAT_TDMON) && isfield(PSDAT_TDMON,'timedout') && PSDAT_TDMON.timedout, ...
             'stalled', isstruct(PSDAT_TDMON) && isfield(PSDAT_TDMON,'stalled') && PSDAT_TDMON.stalled);
end

% ------------------------------------------------------------------------
function status = odeStop(t, ~, flag)
% ODESTOP  ode15s OutputFcn: keep the UI responsive during integration, show
% live progress, stop cleanly on the GUI Stop flag, and enforce the run's
% wall-clock budget.  Returning status=1 halts with the partial solution.
%
% The drawnow pump is THROTTLED to ~20 Hz of wall time: flushing the event
% queue on every accepted step is what used to make a long or struggling
% integration feel like the whole app had frozen -- between throttle ticks
% the solver now runs at full speed, and clicks (Stop above all) are still
% picked up within 50 ms.  The status line shows the advancing simulation
% time, so a slow run visibly IS running, never silently jammed.
global PSDAT_STOP PSDAT_TDMON %#ok<GVMIS>
status = 0;
if ~isempty(flag), return; end      % 'init'/'done' bookkeeping calls
if ~isstruct(PSDAT_TDMON) || ~isfield(PSDAT_TDMON,'t0')   % standalone safety net
    PSDAT_TDMON = struct('t0',tic,'budget',300,'lastdraw',-1,'lastmsg',-1, ...
                         'status',[],'timedout',false);
end
el = toc(PSDAT_TDMON.t0);
if el - PSDAT_TDMON.lastdraw > 0.05
    PSDAT_TDMON.lastdraw = el;
    if el - PSDAT_TDMON.lastmsg > 0.5
        PSDAT_TDMON.lastmsg = el;
        hs = PSDAT_TDMON.status;
        if ~isempty(hs) && ishghandle(hs)
            set(hs,'String',sprintf('integrating...  t = %.2f s   (%.0f s elapsed - Stop keeps the partial result)', t(end), el));
        end
    end
    drawnow limitrate               % process the queue so a Stop click is handled
end
if ~isempty(PSDAT_STOP) && PSDAT_STOP, status = 1; end
if el > PSDAT_TDMON.budget          % wall budget: end the run, keep the partial
    PSDAT_TDMON.timedout = true; status = 1;
end
% SIMULATED-TIME STALL WATCHDOG: the wall budget alone lets a run that stops
% ADVANCING t (Newton grinding on a corner it will never pass) look alive for
% minutes.  If 25 s of wall time pass without t moving at all, end the run
% now with the partial result and say so -- a stall must never read as a jam.
if ~isfield(PSDAT_TDMON,'lastT') || t(end) > PSDAT_TDMON.lastT + 1e-9
    PSDAT_TDMON.lastT = t(end); PSDAT_TDMON.lastTwall = el;
elseif el - PSDAT_TDMON.lastTwall > 25
    PSDAT_TDMON.timedout = true; PSDAT_TDMON.stalled = true; status = 1;
    hs = PSDAT_TDMON.status;
    if ~isempty(hs) && ishghandle(hs)
        set(hs,'String',sprintf('integration stopped advancing at t = %.3f s - keeping the partial result', t(end)));
    end
end
end

% ------------------------------------------------------------------------
function cjpump(msg)
% Throttled status/UI pump for the one-time Jacobian setup.  The two sweeps
% are a few hundred model evaluations -- seconds of compute on a slower
% machine, and a silent callback that long reads as a frozen app.  Same
% throttled-drawnow pattern odeStop uses; the caller's busy guard keeps
% reentrant clicks out, and the message shows live counting progress.
global PSDAT_TDMON %#ok<GVMIS>
if ~isstruct(PSDAT_TDMON) || ~isfield(PSDAT_TDMON,'t0'), return; end
el = toc(PSDAT_TDMON.t0);
if el - PSDAT_TDMON.lastdraw > 0.4
    PSDAT_TDMON.lastdraw = el;
    hs = PSDAT_TDMON.status;
    if ~isempty(hs) && ishghandle(hs), set(hs,'String',msg); end
    drawnow limitrate
end
end

% ------------------------------------------------------------------------
function [CJ, Jd] = dae_colored_setup(S, y0, uu)
% One-time setup of PSDAT's self-computed sparse Jacobian.
%   1. full finite-difference sweep  ->  exact dense Jacobian Jd  AND the
%      structural pattern (entries with sensitivity above 1e-5; the diagonal
%      is kept structurally present -- ode15s factorizes M - h*gamma*J);
%   2. greedy column COLORING on that pattern: two columns share a color
%      only if their row sets are disjoint, so one perturbed evaluation
%      resolves every column of the group exactly;
%   3. triplet slots (ii, jj, per-column offsets) precomputed so each
%      refresh just fills values and calls sparse() once.
global PSDAT_STOP %#ok<GVMIS>
N = numel(y0); nx = S.NX;
[f0, g0] = psdat_dae(y0(1:nx), y0(nx+1:end), S, uu);
r0 = [f0; g0];
Jd = zeros(N, N);
for j = 1:N
    yp = y0; hj = 1e-7*max(1, abs(y0(j))); yp(j) = yp(j) + hj;
    [fp, gp] = psdat_dae(yp(1:nx), yp(nx+1:end), S, uu);
    Jd(:, j) = ([fp; gp] - r0)/hj;
    cjpump(sprintf('preparing sparse Jacobian...  %d / %d', j, 2*N));
    if ~isempty(PSDAT_STOP) && PSDAT_STOP, error('psdat:stopped','stopped'); end
end
P = abs(Jd) > 1e-5;                      % structural pattern (FD noise ~1e-9)
% UNION with the pattern at a deterministic GENERIC point.  An equilibrium is
% a special point: the stator currents of lightly-loaded units (IEEE57 keeps
% synchronous condensers at P ~ 0) sit at numerical zero, so real torque-
% equation couplings vanish coincidentally from the base sweep -- and then
% appear with magnitude ~0.4 the moment the system is disturbed, exactly
% where a missing Jacobian entry hurts most.  A 2% off-equilibrium probe
% breaks every such coincidence; the twin Python engine verified that the
% UNION pattern covers the true disturbed Jacobian with NOTHING outside it.
yg = y0 + 0.02*max(1, abs(y0)).*sin((1:N).');
[fg, gg] = psdat_dae(yg(1:nx), yg(nx+1:end), S, uu);
rg = [fg; gg];
if all(isfinite(rg))
    for j = 1:N
        yp = yg; hj = 1e-7*max(1, abs(yg(j))); yp(j) = yp(j) + hj;
        [fp, gp] = psdat_dae(yp(1:nx), yp(nx+1:end), S, uu);
        d = ([fp; gp] - rg)/hj;
        P(:, j) = P(:, j) | abs(d) > 1e-5 | ~isfinite(d);
        cjpump(sprintf('preparing sparse Jacobian...  %d / %d', N+j, 2*N));
        if ~isempty(PSDAT_STOP) && PSDAT_STOP, error('psdat:stopped','stopped'); end
    end
end
P(1:N+1:end) = true;                     % diagonal always present
rows = cell(1, N);
for j = 1:N, rows{j} = find(P(:, j)); end
color = zeros(1, N); nc = 0; taken = {};
for j = 1:N
    placed = false;
    for c = 1:nc
        if ~any(taken{c}(rows{j}))
            color(j) = c; taken{c}(rows{j}) = true; placed = true; break;
        end
    end
    if ~placed
        nc = nc + 1; color(j) = nc;
        tk = false(N, 1); tk(rows{j}) = true; taken{nc} = tk;   %#ok<AGROW>
    end
end
grp = cell(1, nc);
for c = 1:nc, grp{c} = find(color == c); end
nzc = cellfun(@numel, rows);
ofs = cumsum([0, nzc(:).']);
ii = zeros(ofs(end), 1); jj = zeros(ofs(end), 1);
for j = 1:N
    ii(ofs(j)+1:ofs(j+1)) = rows{j};
    jj(ofs(j)+1:ofs(j+1)) = j;
end
CJ = struct('grp', {grp}, 'rows', {rows}, 'ofs', ofs, 'ii', ii, 'jj', jj, 'N', N);
end

% ------------------------------------------------------------------------
function J = dae_jac_colored(t, y, S, ufun, CJ)
% d[f;g]/dy at (t, y) by COLORED finite differences: all columns of one
% color group are perturbed in a SINGLE evaluation (their pattern rows are
% disjoint), so a refresh costs 1 + numel(CJ.grp) model calls instead of one
% per state.  The disturbance inputs active at THIS instant are applied, so
% the matrix tracks the event ramps exactly as the residual does.
uu = ufun(t);
nx = S.NX;
[f0, g0] = psdat_dae(y(1:nx), y(nx+1:end), S, uu);
r0 = [f0; g0];
vals = zeros(numel(CJ.ii), 1);
for c = 1:numel(CJ.grp)
    cols = CJ.grp{c};
    yp = y; h = zeros(1, numel(cols));
    for a = 1:numel(cols)
        j = cols(a);
        h(a) = 1e-7*max(1, abs(y(j)));
        yp(j) = yp(j) + h(a);
    end
    [fp, gp] = psdat_dae(yp(1:nx), yp(nx+1:end), S, uu);
    dr = [fp; gp] - r0;
    for a = 1:numel(cols)
        j = cols(a);
        vals(CJ.ofs(j)+1:CJ.ofs(j+1)) = dr(CJ.rows{j})/h(a);
    end
end
J = sparse(CJ.ii, CJ.jj, vals, CJ.N, CJ.N);
end

% ------------------------------------------------------------------------
function y = consistent_ic(y, S, uu)
% Refine the initial ALGEBRAIC variables so g(x0,z0)=0 to ~machine precision.
% ode15s (MassSingular='yes') rejects even a slightly-inconsistent start with
% "Initial conditions are inconsistent" — and a drawn/custom network solves its
% power flow to a looser tolerance than the bundled cases.  Hold the differential
% states x0 fixed (they define the operating point) and Newton-correct the
% algebraic block z with the exact same equations the integrator uses — INCLUDING
% the disturbance inputs uu active at this instant (a mid-fault restart polished
% against the undisturbed network would land on the wrong root entirely).  If
% the algebraic Jacobian is ill-conditioned the step is skipped, so this can
% only help — never make a good start worse.
if nargin < 3, uu = struct(); end
global PSDAT_STOP %#ok<GVMIS>
nx = S.NX; x = y(1:nx); z = y(nx+1:end); nz = numel(z);
for it = 1:15
    [~, g] = psdat_dae(x, z, S, uu);
    if max(abs(g)) < 1e-12, break; end
    % cooperative: this polish is the longest un-pumped stretch of a run --
    % stream progress and honor Stop, so the click always lands and the app
    % never reads as frozen while the algebraic start is being refined
    if ~isempty(PSDAT_STOP) && isequal(PSDAT_STOP, true), break; end
    J = zeros(nz, nz); ep = 1e-7;
    for j = 1:nz
        zp = z; hj = ep*max(1, abs(z(j))); zp(j) = zp(j) + hj;
        [~, gp] = psdat_dae(x, zp, S, uu);
        J(:,j) = (gp - g)/hj;
        if mod(j, 24) == 0
            cjpump(sprintf('polishing the operating point...  %d / %d  (pass %d)', j, nz, it));
        end
    end
    dz = J \ (-g);
    if ~all(isfinite(dz)) || norm(dz) > 1e3, break; end   % ill-conditioned -> leave the start as-is
    z = z + dz;
end
y(nx+1:end) = z;
end

% ------------------------------------------------------------------------
function dy = rhs(t, y, S, ufun)
[f, g] = psdat_dae(y(1:S.NX), y(S.NX+1:end), S, ufun(t));
dy = [f; g];
end

function Y = line_stamp(S, fbus, tbus)
% admittance stamp of the FIRST branch fbus-tbus (with tap/charging)
br = S.branch;
kk = find(br(:,1) == fbus & br(:,2) == tbus, 1);
if isempty(kk), error('no branch %d-%d', fbus, tbus); end
r = br(kk,3); xl = br(kk,4); b = br(kk,5); a = br(kk,9);
if a == 0, a = 1; end
Y = zeros(S.n); yl = 1/(r + 1i*xl); bc = 1i*b/2;
Y(fbus,fbus) = (yl + bc)/a^2;  Y(tbus,tbus) = yl + bc;
Y(fbus,tbus) = -yl/conj(a);    Y(tbus,fbus) = -yl/a;
end

function G = cloud_profile(t, t0, depth)
% irradiance dip: down over 2 s, low for 6 s, back over 3 s (pu of STC)
td = 2; tl = 6; tu = 3; G = 1;
if t >= t0 && t < t0+td
    G = 1 - depth*0.5*(1 - cos(pi*(t-t0)/td));
elseif t >= t0+td && t < t0+td+tl
    G = 1 - depth;
elseif t >= t0+td+tl && t < t0+td+tl+tu
    G = 1 - depth*0.5*(1 + cos(pi*(t-t0-td-tl)/tu));
end
end

function v = gust_profile(t, t0, A, base)
% IEC 61400-1 extreme operating gust ('Mexican hat'), duration 10.5 s
T = 10.5; tau = t - t0; v = base;
if tau >= 0 && tau <= T
    v = base - 0.37*A*sin(3*pi*tau/T)*(1 - cos(2*pi*tau/T));
end
end

function v0 = src_vw0(S, k)
a = S.U(k).aux;
if isfield(a,'src'), v0 = a.src.vw0; else, v0 = a.vw0; end
end
