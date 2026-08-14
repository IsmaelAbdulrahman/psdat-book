function [dx, Vpod] = psdat_podstep(xc, s_dev, pc)
%PSDAT_PODSTEP  One evaluation of a supplementary POD / wide-area-damping block.
%
%   [dx, Vpod] = psdat_podstep(xc, s_dev, pc)
%
% Byte-for-byte mirror of facts.pod_output() in the validated Python reference
% (and the same state-space design.pod_ss designs): a washout sTw/(1+sTw), then
% nc identical lead-lags (1+sT1)/(1+sT2), a gain K and a hard output limiter.
%
%   xc     controller sub-states, in order  [lag?; washout; LL1 .. LLnc]
%   s_dev  the DEVIATION input signal (measured signal minus its s0)
%   pc     normalized POD config (fields Tw,T1,T2,nc,K,lo,hi,tau)
%
% Returns the state derivatives dx (same length as xc) and the limited output
% Vpod that modulates the device reference (ΔVref for a shunt regulator).
Tw = max(pc.Tw, 1e-3); T1 = max(pc.T1, 1e-4); T2 = max(pc.T2, 1e-4);
nc = max(0, round(pc.nc)); K = pc.K; lo = pc.lo; hi = pc.hi; tau = pc.tau;
ct = 'leadlag';
if isfield(pc,'ctype') && ~isempty(pc.ctype), ct = lower(pc.ctype); end
dx = zeros(numel(xc), 1); idx = 1; u = s_dev;
if tau > 1e-9                                    % measurement lag 1/(1+s*tau)
    xl = xc(idx); dx(idx) = (s_dev - xl)/max(tau,1e-3); u = xl; idx = idx + 1;
end
if any(strcmp(ct, {'pi','pid'}))
    % PI / PID on the deviation input [Astrom & Hagglund]: y = Kp e + Ki xI
    % (+ Kd * filtered de/dt).  Anti-windup by CONDITIONAL INTEGRATION: the
    % integrator freezes while the output is clamped AND the error keeps
    % pushing further into the limit.  Mirrors facts.pod_output exactly.
    Ki = 0.5; if isfield(pc,'Ki') && ~isempty(pc.Ki), Ki = pc.Ki; end
    Kd = 0.05; if isfield(pc,'Kd') && ~isempty(pc.Kd), Kd = pc.Kd; end
    Tf = 0.02; if isfield(pc,'Tf') && ~isempty(pc.Tf), Tf = pc.Tf; end
    Tf = max(Tf, 1e-3);
    ii = idx; xi_ = xc(ii); idx = idx + 1;
    y = K*u + Ki*xi_;
    if strcmp(ct, 'pid')
        xd = xc(idx); yd = (u - xd)/Tf;
        dx(idx) = yd; y = y + Kd*yd;
    end
    Vpod = min(max(y, lo), hi);
    if (y > hi && u > 0) || (y < lo && u < 0), dx(ii) = 0; else, dx(ii) = u; end
    return;
end
xw = xc(idx); dx(idx) = -xw/Tw + u; y = u - xw/Tw; idx = idx + 1;      % washout
for s = 1:nc                                                          % lead-lag x nc
    xj = xc(idx); dx(idx) = (y - xj)/T2; y = (1 - T1/T2)*xj + (T1/T2)*y; idx = idx + 1;
end
Vpod = min(max(K*y, lo), hi);                                         % gain + limiter
end
