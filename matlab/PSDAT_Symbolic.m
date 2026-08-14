function out = PSDAT_Symbolic(SYS, UT, UTP)
% PSDAT_SYMBOLIC  EXACT (analytical) linearization by symbolic
% differentiation — for EVERY unit type, from the SAME equation file.
%
%   PSDAT_Symbolic                          % default: {'SG','GFM','PV-GFL'}
%   R = PSDAT_Symbolic('IEEE9', {'SG','BESS-GFM','WT4-GFL'})
%
% PSDAT's distinguishing feature is that the state matrix is obtained by
% exact symbolic differentiation rather than numerical perturbation
% [Abdulrahman, OAJPE 2020].  PSDAT generalises this: the differential-
% algebraic residual file psdat_dae.m accepts SYMBOLIC state vectors, so
%
%     fx = jacobian(f, x),  fz = jacobian(f, z),
%     gx = jacobian(g, x),  gz = jacobian(g, z),
%     A  = fx - fz*inv(gz)*gx        (evaluated at the operating point)
%
% is exact for the converter, PV, battery and wind models alike — including
% the PLL trigonometric coupling, the PV-array exponential, the smooth
% limits and the Cp(lambda,beta) aerodynamic surface.  (Hard limits such as
% the converter current ceiling are exactly inactive at the operating point
% and are omitted from the symbolic expressions; the linearization is valid
% in the neighbourhood where they stay inactive.)
%
% Requires the Symbolic Math Toolbox and MATPOWER.  For large systems use
% the numerical route (PSDAT_Linearization) — identical A to ~7 digits.
% Also prints the maximum difference between the symbolic and numerical A.
if nargin < 1, SYS = 'IEEE9'; end
if nargin < 2, UT = {'SG','GFM','PV-GFL'}; end
if nargin < 3, UTP = cell(1, numel(UT)); end

S = psdat_system(SYS, UT, UTP);
fprintf('Symbolic linearization of %s [%s] (%d states)...\n', ...
        SYS, strjoin(UT,','), S.NX);

% ---------------- symbolic state/algebraic vectors -----------------------
xs = sym('x', [S.NX 1], 'real');
zs = sym('z', [S.NZ 1], 'real');
[fs, gs] = psdat_dae(xs, zs, S);          % SAME equation file, symbolic

% ---------------- exact Jacobians + state matrix -------------------------
fx = jacobian(fs, xs);  fz = jacobian(fs, zs);
gx = jacobian(gs, xs);  gz = jacobian(gs, zs);
sub = [xs; zs]; val = [S.x0; S.z0];
fx = double(subs(fx, sub, val));  fz = double(subs(fz, sub, val));
gx = double(subs(gx, sub, val));  gz = double(subs(gz, sub, val));
A  = fx - fz*(gz\gx);

% ---------------- compare with the numerical route -----------------------
Rn = evalc_lin(SYS, UT, UTP);
dA = max(abs(A(:) - Rn.A(:)));
fprintf('max |A_symbolic - A_numerical| = %.2e\n', dA);

lam = eig(A);
freq = abs(imag(lam))/(2*pi);
zeta = -real(lam)./abs(lam)*100; zeta(abs(lam) < 1e-9) = 0;
osc = find(imag(lam) > 1e-3 & freq < 6);
[~, ix] = sort(freq(osc));
fprintf('\n %10s %12s   %s\n','freq(Hz)','damping(%)','eigenvalue');
for j = ix.'
    kk = osc(j);
    fprintf(' %10.4f %12.2f   %9.4f%+9.4fi\n', freq(kk), zeta(kk), ...
            real(lam(kk)), imag(lam(kk)));
end
out = struct('A',A,'lambda',lam,'fx',fx,'fz',fz,'gx',gx,'gz',gz,'S',S, ...
             'dA_vs_numeric',dA,'f_sym',fs,'g_sym',gs);
end

function R = evalc_lin(SYS, UT, UTP)
[~, R] = evalc('PSDAT_Linearization(SYS, UT, UTP)');
close all
end
