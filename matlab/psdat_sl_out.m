function y = psdat_sl_out(u)
% PSDAT_SL_OUT  Measurement block of the PSDAT Simulink model.
%
% Input u = [x; t]; output y = [f_COI ; unit frequencies (Hz, one per
% unit)].  EVERY unit reports a finite frequency (Simulink requires finite
% outputs):
%   SG                rotor speed
%   GFM family        virtual-swing speed
%   GFL family        PLL frequency estimate (ws + xpll + Kp*vq, using the
%                     stored algebraic bus voltage)
%   WT1/WT2/WT3       induction-machine rotor speed (1 - slip)
% If the mix has no SG/GFM unit the "COI" channel falls back to the mean of
% the unit frequencies.
S = psdat_sl_store('S');
z = psdat_sl_store('z');
x = u(1:end-1);
m = S.m; ws = S.ws;
num = 0; den = 0;
w = zeros(m,1);
V = z(S.Vidx); TH = z(S.THidx);
for k = 1:m
    xi = x(S.U(k).xidx);
    i = S.U(k).bus;
    switch S.U(k).type
    case 'SG'
        wk = xi(6); Mi = 2*S.MD.H(k)*S.Sbase_gen(k);
        num = num + Mi*wk; den = den + Mi;
        w(k) = wk/(2*pi);
    case {'GFM','PV-GFM','BESS-GFM','WT4-GFM'}
        wk = xi(2); Mi = 2*S.U(k).aux.p.Hv*S.Sbase_gen(k);
        num = num + Mi*wk; den = den + Mi;
        w(k) = wk/(2*pi);
    case {'GFL','PV-GFL','BESS-GFL','WT4-GFL'}
        thp = xi(1); xpll = xi(2); p = S.U(k).aux.p;
        vq = V(i)*sin(TH(i) - thp);
        w(k) = (ws + xpll + p.Kp*vq)/(2*pi);   % PLL frequency estimate
    case {'WT1','WT2','WT3'}
        w(k) = (1 - xi(3))*ws/(2*pi);          % rotor speed
    otherwise
        w(k) = ws/(2*pi);
    end
end
if den > 0
    f = (num/den)/(2*pi);
else
    f = mean(w);                               % no inertial unit: mean freq
end
if ~isfinite(f), f = ws/(2*pi); end
w(~isfinite(w)) = ws/(2*pi);
y = [f; w];
end
