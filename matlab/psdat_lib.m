function L = psdat_lib()
% PSDAT_LIB  Shared helper functions of the PSDAT toolbox.
%
% Returns a struct of function handles so every driver uses ONE copy of the
% smooth-limit, PV-array and wind-aerodynamics helpers (MATLAB & Octave).
% The equations mirror psdat/units.py of the validated Python reference
% one-for-one.
%
% Smooth limits: all converter/source limits are continuously differentiable
% so the exact linearization stays valid; each limit is inactive (with an
% exact-equilibrium correction) at the operating point.
L.s_relu  = @s_relu;
L.s_min   = @s_min;
L.s_clamp = @s_clamp;
L.s_dead  = @s_dead;
L.s_sig   = @s_sig;
L.pv_curve_I = @pv_curve_I;
L.pv_mpp  = @pv_mpp;
L.wt_cp   = @wt_cp;
L.wt_pm   = @wt_pm;
L.pitch_init = @pitch_init;
L.ilim    = @ilim;
L.q_support = @q_support;      % IEEE 1547-2018 reactive support
L.p_support = @p_support;      % IEEE 1547-2018 active support
L.pv_vpower = @pv_vpower;      % PV de-loading (upper P-V branch)
L.pss_block = @pss_block;      % power-system stabiliser block
end

% =============== IEEE 1547-2018 GRID-SUPPORT FUNCTIONS ===================
% Autonomous inverter functions that make a grid-following converter respond
% to local voltage/frequency -- the "bridge to industry" (same controls a
% real PV/battery inverter must implement per IEEE Std 1547-2018, and IEEE
% 2800-2022 for bulk plants).  Written as explicit droops that reduce EXACTLY
% to constant-P/Q at the dispatched operating point (gains 0 or signals at
% reference), so the initial equilibrium is untouched.  Mirrors
% psdat/units.py {q_support, p_support, pv_vpower} one-for-one.
function Qr = q_support(Pref, Pset, Qset, Vg, V0, p)
% Reactive-power reference (clause 5.14): 0 const-Q, 1 Volt-VAR, 2 const-PF.
mode = round(getf(p,'qmode',0));
if mode==1 && getf(p,'Kqv',0) > 0                    % Volt-VAR  [1547 5.14.4]
    Vdb = getf(p,'Vdb',0);
    if Vdb > 0, dv = s_dead(Vg-V0, Vdb); else, dv = Vg-V0; end
    Qraw = Qset - getf(p,'Kqv',0)*dv;
elseif mode==2 && abs(Pset) > 1e-6                   % constant power factor [5.14.2]
    Qraw = (Qset/Pset)*Pref;
else
    Qr = Qset; return                                % constant reactive power
end
qm = getf(p,'Qmax',0.44);
c0 = Qset - s_clamp(Qset,-qm,qm);                    % exact-equilibrium correction
Qr = s_clamp(Qraw,-qm,qm) + c0;
end

function Pr = p_support(Pset, Vg, dw, V0, p)
% Active-power reference: Volt-Watt (over-voltage curtail) + Freq-Watt (droop).
% dw = per-unit frequency deviation.  Both inactive at V=V0, dw=0.
Pr = Pset;
if getf(p,'Kvw',0) > 0                                % Volt-Watt  [1547 5.14.6]
    Vvw = getf(p,'Vvw',1.06);
    Pr = Pr - getf(p,'Kvw',0)*(s_relu(Vg-Vvw) - s_relu(V0-Vvw));
end
if getf(p,'Kfw',0) > 0                                % Freq-Watt  [1547 6.4]
    Pr = Pr - getf(p,'Kfw',0)*s_dead(dw, getf(p,'fdb',0));
end
end

function V = pv_vpower(voc, isc, G, Ptgt, Vmp, Pmp)
% DC-side voltage on the UPPER (deloading) branch of the P-V curve delivering
% array power Ptgt (<=Pmp): how a PV plant provides active support without a
% battery [Sangwongwanich et al., IEEE T-PE 2017].  Returns Vmp if no curtail.
if Ptgt >= Pmp*0.999, V = Vmp; return; end
lo = Vmp; hi = voc*0.999;
for k = 1:40                     % bisection: power falls as V rises above Vmp
    mid = 0.5*(lo+hi);
    if mid*pv_curve_I(mid,G,voc,isc) > Ptgt, lo = mid; else, hi = mid; end
end
V = 0.5*(lo+hi);
end

% ---------------- power-system stabiliser (supplementary excitation) -----
% Classic delta-omega PSS [Sauer & Pai ch.8; Kundur ch.12; IEEE 421.5 PSS1A]:
% washout sTw/(1+sTw) then TWO lead-lag stages [(1+sT1)/(1+sT2)]^2, gain Kpss;
% output Vpss summed into the AVR reference.  States (Vw,V1,V2) all zero at the
% operating point (dw=0), so the equilibrium is untouched.
function [fVw, fV1, fV2, Vpss] = pss_block(Vw, V1, V2, dw, p)
r = p.T1/p.T2;  u = p.Kpss*dw;
fVw = (1/p.Tw)*(u - Vw);       yw = u - Vw;         % washout
fV1 = (1/p.T2)*(yw - V1);      y1 = r*yw + (1-r)*V1;   % lead-lag 1
fV2 = (1/p.T2)*(y1 - V2);      Vpss = r*y1 + (1-r)*V2; % lead-lag 2
end

function v = getf(p, f, dv)
if isfield(p,f) && ~isempty(p.(f)), v = p.(f); else, v = dv; end
end

% ---------------------------------------------------------- smooth helpers
function y = s_relu(x, eps_)
if nargin < 2, eps_ = 0.01; end
y = 0.5*(x + sqrt(x.*x + eps_*eps_));          % smooth max(x,0)
end
function y = s_min(a, b)
y = a - s_relu(a - b);                          % smooth min(a,b)
end
function y = s_clamp(x, lo, hi)
y = x - s_relu(x - hi) + s_relu(lo - x);        % smooth clamp to [lo,hi]
end
function y = s_dead(x, db)
y = x - db*tanh(x/db);                          % smooth deadband (0 slope at 0)
end
function y = s_sig(x)
y = 0.5*(1 + tanh(x));                          % smooth 0..1 saturation
end

% ------------------------------------------------------------ PV array ---
% Simplified explicit single-diode array model, normalised so the STC
% maximum-power point is (V,I) = (1,1); voc = Voc/Vmp, isc = Isc/Imp.
% [Masters; Femia et al.]  Irradiance G in pu of 1000 W/m2.
function I = pv_curve_I(V, G, voc, isc)
C2 = (1/voc - 1)/log(1 - 1/isc);
C1 = (1 - 1/isc)*exp(-1/(C2*voc));
I  = G.*isc.*(1 - C1*(exp(V/(C2*voc)) - 1));
end
function [Vmp, Pmp] = pv_mpp(voc, isc, G)
% numerical MPP by golden-section search on the smooth P(V) curve
a = 0.5; b = voc*0.999; gr = (sqrt(5)-1)/2;
c = b - gr*(b-a); d = a + gr*(b-a);
for k = 1:60
    if c*pv_curve_I(c,G,voc,isc) > d*pv_curve_I(d,G,voc,isc), b = d; else, a = c; end
    c = b - gr*(b-a); d = a + gr*(b-a);
end
Vmp = 0.5*(a+b); Pmp = Vmp*pv_curve_I(Vmp,G,voc,isc);
end

% ------------------------------------------------- wind aerodynamics -----
% Cp(lambda,beta) of Heier with the classical coefficients; speeds and wind
% in pu of rated; lambda = lam_r*wt/vw; Pm = (Cp/Cpmax)*vw^3 (turbine pu).
function Cp = wt_cp(lam, be, c, ~)
li = 1./(1./(lam + 0.08*be) - 0.035./(be.^3 + 1));
Cp = c(1)*(c(2)./li - c(3)*be - c(4)).*exp(-c(5)./li) + c(6)*lam;
end
function Pm = wt_pm(wt, vw, be, p)
lam = p.lam_r*wt/vw;
Pm  = (wt_cp(lam, be, p.c)/p.Cpmax)*vw^3;
end
function [be0, xp0] = pitch_init(e0, p)
% pitch PI + anti-windup equilibrium: fixed point of the smooth saturation
Kaw = 1.0; be_raw = (p.Kip/Kaw)*e0;
for k = 1:80
    be = s_clamp(be_raw, 0, p.bmax);
    be_raw = (p.Kip*e0 + Kaw*be)/Kaw;
end
be0 = s_clamp(be_raw, 0, p.bmax);
xp0 = be_raw - p.Kpp*e0;
end

% ------------------------------------------------- converter current limit
function [idr, iqr] = ilim(idr, iqr, Ilim)
% scale the reference vector down to the unit's current rating [IEEE 2800];
% Ilim is per-unit-of-SYSTEM: 1.2 x the unit's own rated current.
Iref = hypot(idr, iqr);
if Iref > Ilim, idr = idr*(Ilim/Iref); iqr = iqr*(Ilim/Iref); end
end
