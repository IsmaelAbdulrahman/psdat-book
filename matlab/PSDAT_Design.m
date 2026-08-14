function out = PSDAT_Design(SYS, UT, UTP, opts)
% PSDAT_DESIGN  Residue-based damping-controller (POD) design.
%
%   PSDAT_Design    % demo: GFM battery damps the Kundur inter-area mode
%   out = PSDAT_Design(SYS, UT, UTP, opts)
%
% Revives Program 3 of the original PSDAT for the converter era.  For a
% chosen actuator unit (opts.unit: its power set-point P* is the input) and
% measurement (that unit's speed), the tool:
%   1. forms the exact input matrix  B = fu - fz*inv(gz)*gu ;
%   2. forms the output row          C  (unit speed deviation, pu);
%   3. computes the residue of the target mode  R = (C*v)(w'*B)
%      [Kundur ch. 12; Pal & Chaudhuri ch. 5-6];
%   4. designs  K * sTw/(1+sTw) * ((1+sT1)/(1+sT2))^nc  by residue-angle
%      phase compensation, gain from the first-order mode sensitivity
%      dlam = K*R*H(lam)  (positive-feedback convention u = +F(s)*y);
%   5. verifies on the EXACT closed-loop eigenvalues.
%
% opts fields: unit (actuator index, default 2), band ([f1 f2] Hz of the
% target mode, default [0.3 0.9]), zeta_target (default 0.15), Tw (10 s).
if nargin < 1, SYS = 'Kundur2A'; end
if nargin < 2
    UT = {'SG','BESS-GFM','SG','SG'};
    GFM_K = struct('Hv',45,'Dp',180,'wc',31.4,'mq',0.0056, ...
                   'Rc',0.0006,'Xc',0.0056,'Eh',1.0,'SOC0',0.6);
    UTP = {[], GFM_K, [], []};
end
if ~exist('UTP','var') || isempty(UTP), UTP = cell(1, numel(UT)); end
if nargin < 4, opts = struct(); end
ku   = getdef(opts,'unit',2);
band = getdef(opts,'band',[0.3 0.9]);
zt   = getdef(opts,'zeta_target',0.20);
Tw   = getdef(opts,'Tw',10);

R = evalc_lin(SYS, UT, UTP);
S = R.S; lam_all = R.lambda;
% ---------------- target mode: least damped in the band ------------------
osc = find(imag(lam_all) > 2*pi*band(1) & imag(lam_all) < 2*pi*band(2));
if isempty(osc)          % no oscillatory mode in the requested band (e.g. a
    % system whose modes are all local, ~1-2 Hz): fall back to EVERY oscillatory
    % mode up to 20 Hz so POD still targets the least-damped one it can see,
    % instead of failing on an empty lam0 ("Arrays have incompatible sizes").
    osc = find(imag(lam_all) > 0.2 & imag(lam_all) < 2*pi*20);
end
if isempty(osc)
    error('no oscillatory mode found to damp (the system has only real / non-oscillatory modes).');
end
[~, jj] = min(-real(lam_all(osc))./abs(lam_all(osc)));
i0 = osc(jj); lam0 = lam_all(i0);
fprintf('Target mode: %.3f Hz, %.2f %% damping\n', imag(lam0)/2/pi, ...
        -real(lam0)/abs(lam0)*100);

% ---------------- exact B (input = unit ku set-point) --------------------
eps_ = 1e-7; u = struct('dPu', zeros(1,S.m)); u.dPu(ku) = eps_;
[f0, g0] = psdat_dae(S.x0, S.z0, S);
[f1, g1] = psdat_dae(S.x0, S.z0, S, u);
fu = (f1 - f0)/eps_;  gu = (g1 - g0)/eps_;
B = fu - R.fz*(R.gz\gu);

% ---------------- output row C (speed of unit ku, pu) --------------------
xsl = S.U(ku).xidx;
c_x = zeros(1, S.NX);
switch S.U(ku).type
case {'SG','SGP'},                           c_x(xsl(6)) = 1/S.ws;
case {'SG6','SG6G','SG6P'},                  c_x(xsl(3)) = 1/S.ws;
case {'SG4','SG4G'},                         c_x(xsl(4)) = 1/S.ws;
case 'SG2',                                  c_x(xsl(2)) = 1/S.ws;
case {'GFM','PV-GFM','BESS-GFM','WT4-GFM'},  c_x(xsl(2)) = 1/S.ws;
otherwise, error('speed output needs an SG or GFM-type actuator unit');
end
C = c_x;                                    % speed is a pure state -> hz = 0

% ---------------- residue + POD design -----------------------------------
[VV, DD] = eig(R.A); lamv = diag(DD); W = inv(VV);
[~, im] = min(abs(lamv - lam0)); lam = lamv(im);
res = (C*VV(:,im)) * (W(im,:)*B);
fprintf('Residue: |R| = %.4g, angle = %.1f deg\n', abs(res), angle(res)*180/pi);
w = abs(imag(lam));
Hw = @(s) (s*Tw)./(1 + s*Tw);
phi = pi - angle(res*Hw(lam));
phi = mod(phi + pi, 2*pi) - pi;
if abs(phi) > pi/2, phi = phi - sign(phi)*pi; end   % flip loop sign instead
nc = min(3, max(1, ceil(abs(phi)/deg2rad(65))));
phic = phi/nc;
aa = (1 + sin(phic))/(1 - sin(phic));
T2 = 1/(w*sqrt(aa)); T1 = aa*T2;
H = @(s) Hw(s).*((1 + s*T1)./(1 + s*T2)).^nc;
dlam_needed = -zt*abs(lam) - real(lam);
K = dlam_needed/real(res*H(lam));
fprintf('POD: K = %.2f, washout %.0f s, %d lead-lag(s) T1 = %.3f, T2 = %.3f\n', ...
        K, Tw, nc, T1, T2);

% ---------------- exact closed-loop verification -------------------------
[Ac, Bc, Cc, Dc] = pod_ss(K, Tw, T1, T2, nc);
b = B(:); c = C(:).';
Acl = [R.A + Dc*(b*c), b*Cc; Bc*c, Ac];
lcl = eig(Acl);
[~, im2] = min(abs(lcl - lam));
z1 = -real(lcl(im2))/abs(lcl(im2))*100;
fprintf('Closed loop: mode %.3f Hz -> %.2f %% damping (target %.0f %%), %d unstable\n', ...
        imag(lcl(im2))/2/pi, z1, zt*100, sum(real(lcl) > 1e-6));
if ~(exist('psdat_noplot','file') == 2 && psdat_noplot())   % the app defers its own figure
    figure; hold on; grid on;
    plot(real(lam_all), imag(lam_all), 'x', 'MarkerSize', 9, 'LineWidth', 1.5);
    plot(real(lcl), imag(lcl), 'o', 'MarkerSize', 7, 'LineWidth', 1.2);
    legend('open loop','with POD'); xlabel('Real (1/s)'); ylabel('Imag (rad/s)');
    title(sprintf('%s: POD on unit %d (%s)', psdat_sysname(SYS), ku, S.U(ku).type));
end
out = struct('K',K,'Tw',Tw,'T1',T1,'T2',T2,'nc',nc,'residue',res, ...
             'lam_open',lam,'lam_closed',lcl(im2),'Acl',Acl,'B',B,'C',C, ...
             'lam_all',lam_all,'lam_cl',lcl,'unit',ku,'unittype',S.U(ku).type);
end

% ------------------------------------------------------------------------
function [A, B, C, D] = pod_ss(K, Tw, T1, T2, nc)
% state space of K * washout * leadlag^nc (SISO)
A = -1/Tw; B = 1; C = -1/Tw; D = 1;
for a = 1:nc
    Al = -1/T2; Bl = 1/T2; Cl = 1 - T1/T2; Dl = T1/T2;
    A = [A, zeros(size(A,1),1); Bl*C, Al];
    B = [B; Bl*D];
    C = [Dl*C, Cl];
    D = Dl*D;
end
C = K*C; D = K*D;
end

function R = evalc_lin(SYS, UT, UTP)
f0 = findall(0, 'Type', 'figure');                       % remember open figures
[~, R] = evalc('PSDAT_Linearization(SYS, UT, UTP)');
delete(setdiff(findall(0,'Type','figure'), f0));         % close ONLY the eigenvalue
end                                                      % figure it opened, never the app

function v = getdef(s, f, dv)
if isfield(s, f) && ~isempty(s.(f)), v = s.(f); else, v = dv; end
end
