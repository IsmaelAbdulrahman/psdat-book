function [V, th, Pg, Qg, info] = psdat_powerflow(Ybus, btype, Pd, Qd, Vm0, ...
                                                 gen_bus, Pg_sched, Vg_sched, ...
                                                 method, branch, tap)
% PSDAT_POWERFLOW  Polar power flow with three selectable textbook solvers.
%
%   [V, th, Pg, Qg, info] = psdat_powerflow(Ybus, btype, Pd, Qd, Vm0, ...
%                              gen_bus, Pg_sched, Vg_sched, method, branch, tap)
%
% Native (MATPOWER-free) load flow in polar form [Sauer & Pai ch.7].  All three
% methods drive the identical nonlinear power-balance mismatch to zero and land
% on the SAME solution -- only the path/rate differ (the teaching point):
%   'nr'   full Newton-Raphson, polar   [Tinney & Hart 1967]  (quadratic)
%   'fdlf' fast-decoupled, XB           [Stott & Alsac 1974]  (linear, cheap)
%   'gs'   Gauss-Seidel + SOR (a=1.6)   [Ward & Hale 1956]    (linear, simple)
% Returns bus voltage V, angle th (rad), and the NET generator injections Pg,Qg
% (load added back), plus info = struct('method','iters','mismatch').
% Mirrors psdat/network.py {power_flow,_pf_newton,_pf_fdlf,_pf_gauss} one-for-one.
if nargin < 9  || isempty(method), method = 'nr'; end
if nargin < 10, branch = []; end
if nargin < 11, tap = []; end
n = numel(btype); btype = btype(:);
V = Vm0(:); th = zeros(n,1);
pv = find(btype==2); pq = find(btype==1);
Psp = zeros(n,1);
for a = 1:numel(gen_bus)
    gb = gen_bus(a);
    Psp(gb) = Psp(gb) + Pg_sched(a);
    if btype(gb)==2 || btype(gb)==3, V(gb) = Vg_sched(a); end   % PV + slack |V| fixed
end
Psp = Psp - Pd; Qsp = -Qd;
pvpq = sort([pv; pq]);
tol = 1e-8;
switch lower(method)
case {'fdlf','fd','fast'}
    [V, th, iters] = pf_fdlf(Ybus, Psp, Qsp, V, th, pq, pvpq, tol, 400, branch, tap, n);
    mname = 'fdlf';
case {'gs','gauss','gauss-seidel'}
    [V, th, iters] = pf_gauss(Ybus, Psp, Qsp, V, th, btype, gen_bus, Vg_sched, pq, pvpq, tol, 20000);
    mname = 'gs';
otherwise
    [V, th, iters] = pf_newton(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol, 60);
    mname = 'nr';
end
Vc = V.*exp(1i*th);
Sc = Vc.*conj(Ybus*Vc);
mis = [ (Psp - real(Sc)); (Qsp - imag(Sc)) ];
sel = [pvpq; n+pq];
info = struct('method',mname,'iters',iters,'mismatch',max(abs(mis(sel))));
Pg = real(Sc) + Pd;  Qg = imag(Sc) + Qd;
end

% ------------------------------------------------------------ Newton-Raphson
function [V, th, it] = pf_newton(Ybus, Psp, Qsp, V, th, pv, pq, pvpq, tol, itmax)
G = real(Ybus); B = imag(Ybus);
it = 0;
for it = 0:itmax-1
    Vc = V.*exp(1i*th); S = Vc.*conj(Ybus*Vc); P = real(S); Q = imag(S);
    dPa = Psp - P; dQa = Qsp - Q;
    mism = [ dPa(pvpq); dQa(pq) ];
    if max(abs(mism)) < tol, break; end
    np_ = numel(pvpq); nq = numel(pq);
    J11 = zeros(np_,np_); J12 = zeros(np_,nq);
    J21 = zeros(nq,np_);  J22 = zeros(nq,nq);
    for a = 1:np_
        i = pvpq(a);
        for b = 1:np_
            k = pvpq(b);
            if i==k, J11(a,b) = -Q(i) - B(i,i)*V(i)^2;
            else, J11(a,b) = V(i)*V(k)*(G(i,k)*sin(th(i)-th(k)) - B(i,k)*cos(th(i)-th(k))); end
        end
        for b = 1:nq
            k = pq(b);
            if i==k, J12(a,b) = P(i)/V(i) + G(i,i)*V(i);
            else, J12(a,b) = V(i)*(G(i,k)*cos(th(i)-th(k)) + B(i,k)*sin(th(i)-th(k))); end
        end
    end
    for a = 1:nq
        i = pq(a);
        for b = 1:np_
            k = pvpq(b);
            if i==k, J21(a,b) = P(i) - G(i,i)*V(i)^2;
            else, J21(a,b) = -V(i)*V(k)*(G(i,k)*cos(th(i)-th(k)) + B(i,k)*sin(th(i)-th(k))); end
        end
        for b = 1:nq
            k = pq(b);
            if i==k, J22(a,b) = Q(i)/V(i) - B(i,i)*V(i);
            else, J22(a,b) = V(i)*(G(i,k)*sin(th(i)-th(k)) - B(i,k)*cos(th(i)-th(k))); end
        end
    end
    dx = [J11 J12; J21 J22] \ mism;
    th(pvpq) = th(pvpq) + dx(1:np_);
    V(pq)    = V(pq)    + dx(np_+1:end);
end
end

% ------------------------------------------------------ fast-decoupled (XB)
function [V, th, it] = pf_fdlf(Ybus, Psp, Qsp, V, th, pq, pvpq, tol, itmax, branch, tap, n)
B = imag(Ybus);
Bp = bprime(branch, n, pvpq);
if isempty(Bp), Bp = -B(pvpq,pvpq); end     % no branch data: -Im(Ybus) fallback
Bpp = -B(pq,pq);
hp = ~isempty(pvpq); hq = ~isempty(pq);
it = 0;
for it = 0:itmax-1
    Vc = V.*exp(1i*th); S = Vc.*conj(Ybus*Vc);
    dP = Psp - real(S); dQ = Qsp - imag(S);
    e1 = 0; if hp, e1 = max(abs(dP(pvpq))); end
    e2 = 0; if hq, e2 = max(abs(dQ(pq))); end
    if max(e1,e2) < tol, break; end
    if hp
        dth = Bp \ (dP(pvpq)./V(pvpq)); th(pvpq) = th(pvpq) + dth;
    end
    if hq
        Vc = V.*exp(1i*th); Q = imag(Vc.*conj(Ybus*Vc));
        dQv = Qsp - Q;
        dV = Bpp \ (dQv(pq)./V(pq)); V(pq) = V(pq) + dV;
    end
end
end

function Bp = bprime(branch, n, pvpq)
% B' : series-susceptance network from reactance only (Stott-Alsac XB).
if isempty(branch), Bp = []; return; end
Bp = zeros(n,n);
for k = 1:size(branch,1)
    f = round(branch(k,1)); t = round(branch(k,2)); x = branch(k,4);
    if x==0, continue; end
    b = 1/x;
    Bp(f,f) = Bp(f,f)+b; Bp(t,t) = Bp(t,t)+b;
    Bp(f,t) = Bp(f,t)-b; Bp(t,f) = Bp(t,f)-b;
end
Bp = Bp(pvpq,pvpq);
end

% ------------------------------------------------------ Gauss-Seidel (SOR)
function [Vm, Va, it] = pf_gauss(Ybus, Psp, Qsp, V, th, btype, gen_bus, Vg_sched, pq, pvpq, tol, itmax)
accel = 1.6;
Vc = V.*exp(1i*th); Ssp = Psp + 1i*Qsp;
n = numel(btype);
Vset = zeros(n,1); isPV = (btype==2);
for a = 1:numel(gen_bus)
    if btype(gen_bus(a))==2, Vset(gen_bus(a)) = Vg_sched(a); end
end
hp = ~isempty(pvpq); hq = ~isempty(pq);
it = 0;
for it = 0:itmax-1
    for i = 1:n
        if btype(i)==3, continue; end          % slack fixed
        ksum = Ybus(i,:)*Vc - Ybus(i,i)*Vc(i);
        if isPV(i)                             % PV: match Q, hold |V|
            Qi = -imag(conj(Vc(i))*(ksum + Ybus(i,i)*Vc(i)));
            Si = Psp(i) + 1i*Qi;
            Vnew = (conj(Si/Vc(i)) - ksum)/Ybus(i,i);
            Vacc = Vc(i) + accel*(Vnew - Vc(i));
            Vc(i) = Vset(i)*Vacc/abs(Vacc);
        else                                   % PQ: full update
            Vnew = (conj(Ssp(i)/Vc(i)) - ksum)/Ybus(i,i);
            Vc(i) = Vc(i) + accel*(Vnew - Vc(i));
        end
    end
    S = Vc.*conj(Ybus*Vc); dP = Psp - real(S); dQ = Qsp - imag(S);
    e1 = 0; if hp, e1 = max(abs(dP(pvpq))); end
    e2 = 0; if hq, e2 = max(abs(dQ(pq))); end
    if max(e1,e2) < tol, break; end
end
Vm = abs(Vc); Va = angle(Vc);
end
