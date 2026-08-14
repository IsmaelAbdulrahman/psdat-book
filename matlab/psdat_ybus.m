function Y = psdat_ybus(n, branch, tap, gs, bs)
% PSDAT_YBUS  Bus admittance matrix (native, MATPOWER-free).
%
%   Y = psdat_ybus(n, branch, tap, gs, bs)
%
%   n      : number of buses
%   branch : rows [from to r x b_charging]   (1-based bus numbers)
%   tap    : per-branch off-nominal ratio (0 or 1 = none)   [optional]
%   gs, bs : bus shunt conductance / susceptance (pu)        [optional]
%
% Off-nominal transformer taps and line charging are handled exactly as
% MATPOWER / the Python reference [Zimmerman et al., IEEE T-PWRS 2011]:
%   Yff = (y + j b/2)/a^2 ,  Yft = -y/conj(a),
%   Ytf = -y/a ,             Ytt =  y + j b/2 .
% Mirrors build_ybus() in psdat/network.py one-for-one.
if nargin < 3, tap = []; end
if nargin < 4, gs = []; end
if nargin < 5, bs = []; end
Y = zeros(n, n);
for k = 1:size(branch, 1)
    f = round(branch(k, 1));  t = round(branch(k, 2));
    r = branch(k, 3);  x = branch(k, 4);  b = branch(k, 5);
    a = 1.0;
    if ~isempty(tap) && tap(k) ~= 0, a = tap(k); end
    y  = 1.0 / (r + 1i*x);
    bc = 1i * b / 2;
    Y(f, f) = Y(f, f) + (y + bc) / (a * a);
    Y(t, t) = Y(t, t) + y + bc;
    Y(f, t) = Y(f, t) - y / conj(a);
    Y(t, f) = Y(t, f) - y / a;
end
if ~isempty(gs) || ~isempty(bs)
    % gs and bs stamp independently: a call that passes only bs (e.g. a
    % saturated-FACTS re-solve on a case with no conductive shunts) must
    % never have its susceptances silently dropped.
    if isempty(gs), gs = zeros(n,1); end
    if isempty(bs), bs = zeros(n,1); end
    for i = 1:n
        Y(i, i) = Y(i, i) + gs(i) + 1i*bs(i);
    end
end
end
