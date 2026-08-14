function dx = psdat_sl_rhs(u)
% PSDAT_SL_RHS  Right-hand side of the PSDAT phasor-DAE for Simulink.
%
% Wired by PSDAT_BuildSimulink as an Interpreted MATLAB Function block:
% input u = [x; t] (all differential states + simulation time), output the
% state derivatives dx.  At every call the network algebraic equations
% 0 = g(x, z) are solved by a warm-started damped Newton iteration and the
% derivatives f(x, z) are returned — the SAME validated equation file
% psdat_dae.m used by the code drivers, so the Simulink model and
% PSDAT_TimeDomain produce the same trajectories by construction.
persistent fac cnt
S = psdat_sl_store('S');
D = psdat_sl_store('D');
x = u(1:end-1); t = u(end);
z = psdat_sl_store('z');

uu = local_inputs(t, S, D);

if ~isempty(fac) && size(fac,1) ~= numel(z)
    fac = [];                              % model was rebuilt: stale factor
end
if isempty(cnt), cnt = 0; end
refresh = isempty(fac) || mod(cnt, 30) == 0 || local_near_event(t, D);
cnt = cnt + 1;
for it = 1:12
    [f, g] = psdat_dae(x, z, S, uu);
    if max(abs(g)) < 1e-9, break; end
    if refresh || it > 4
        fac = local_gz(x, z, S, uu);        % numeric dg/dz, LU-factored
        refresh = false;
    end
    dz = fac \ g;
    s = 1; mx = max(abs(dz));
    if mx > 0.25, s = 0.25/mx; end          % damp large algebraic jumps
    z = z - s*dz;
end
psdat_sl_store('z', z);
dx = f;
end

% ------------------------------------------------------------------------
function J = local_gz(x, z, S, uu)
[~, g0] = psdat_dae(x, z, S, uu);
N = numel(z); J = zeros(numel(g0), N); h = 1e-7;
for k = 1:N
    zp = z; zp(k) = zp(k) + h;
    [~, g1] = psdat_dae(x, zp, S, uu);
    J(:,k) = (g1 - g0)/h;
end
end

function tf = local_near_event(t, D)
ev = [];
for fld = {'fault','linetrip','dPload','dPgen'}
    if isfield(D, fld{1}), v = D.(fld{1}); ev = [ev v(3) v(min(4,end))]; end %#ok<AGROW>
end
for fld = {'cloud','gust'}
    if isfield(D, fld{1}), v = D.(fld{1}); ev = [ev v(3)]; end %#ok<AGROW>
end
tf = any(abs(t - ev(isfinite(ev))) < 0.1);
end

function uu = local_inputs(t, S, D)
% disturbance inputs at time t — SAME semantics as PSDAT_TimeDomain:
%   D.fault    = [bus  Xf  ton toff]      D.dPload = [bus dP ton toff]
%   D.linetrip = [f  t  ton toff]         D.dPgen  = [unit dP ton toff]
%   D.cloud    = [unit depth t0]          D.gust   = [unit A t0]
tr = 0.05;
sr = @(t0) 0.5*(1 - cos(pi*min(max((t - t0)/tr, 0), 1)));
uu = struct();
if isfield(D,'dPload')
    v = D.dPload; uu.dPload = zeros(S.n,1);
    uu.dPload(v(1)) = v(2)*(sr(v(3)) - sr(v(4)));
end
if isfield(D,'dPgen')
    v = D.dPgen; uu.dPu = zeros(1,S.m);
    uu.dPu(v(1)) = v(2)*(sr(v(3)) - sr(v(4)));
end
Ye = zeros(S.n); any_ = false;
if isfield(D,'fault')
    v = D.fault;
    Ye(v(1),v(1)) = Ye(v(1),v(1)) + (1/(1i*v(2)))*(sr(v(3)) - sr(v(4)));
    any_ = true;
end
if isfield(D,'linetrip')                    % D.Ytrip precomputed by the builder
    v = D.linetrip;
    Ye = Ye + D.Ytrip*(sr(v(3)) - sr(v(4)));
    any_ = true;
end
if any_, uu.Yextra = Ye; end
if isfield(D,'cloud')
    v = D.cloud; uu.G = nan(1,S.m);
    uu.G(v(1)) = local_cloud(t, v(3), v(2));
end
if isfield(D,'gust')
    v = D.gust; uu.vw = nan(1,S.m);
    a = S.U(v(1)).aux;
    if isfield(a,'src'), base = a.src.vw0; else, base = a.vw0; end
    uu.vw(v(1)) = local_gust(t, v(3), v(2), base);
end
end

function G = local_cloud(t, t0, depth)
td = 2; tl = 6; tu = 3; G = 1;
if t >= t0 && t < t0+td
    G = 1 - depth*0.5*(1 - cos(pi*(t-t0)/td));
elseif t >= t0+td && t < t0+td+tl
    G = 1 - depth;
elseif t >= t0+td+tl && t < t0+td+tl+tu
    G = 1 - depth*0.5*(1 + cos(pi*(t-t0-td-tl)/tu));
end
end

function v = local_gust(t, t0, A, base)
T = 10.5; tau = t - t0; v = base;
if tau >= 0 && tau <= T
    v = base - 0.37*A*sin(3*pi*tau/T)*(1 - cos(2*pi*tau/T));
end
end
