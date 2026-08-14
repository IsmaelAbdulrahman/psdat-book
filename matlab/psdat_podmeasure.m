function s = psdat_podmeasure(pc, S, x, z)
%PSDAT_PODMEASURE  Raw POD feedback signal — local OR remote (WAMS/PMU).
%
%   s = psdat_podmeasure(pc, S, x, z)
%
% Mirror of system.System._pod_measure / _line_quantity in the Python reference.
% pc is a normalized POD config (sig, rbus, f, t, i, j, selfbus); S carries the
% network (S.branch 13-col, S.Vidx, S.THidx, S.spdcol); x,z are the current
% differential/algebraic vectors.  Returns the (undeviated) measured signal.
n = S.n; V = z(S.Vidx); TH = z(S.THidx);
sb = pc.selfbus; if sb < 1 || sb > n, sb = 1; end
s = V(sb);                                        % robust default: local bus |V|
try
    switch pc.sig
        case 'Vbus'
            i = pc.rbus; if i < 1 || i > n, i = sb; end
            s = V(i);
        case 'angle'
            i = pc.rbus; if i < 1 || i > n, i = sb; end
            s = TH(i);
        case 'adiff'
            i = pc.i; j = pc.j;
            if i >= 1 && i <= n && j >= 1 && j <= n, s = TH(i) - TH(j); end
        case 'wgen'
            i = pc.rbus; if i < 1 || i > n, i = sb; end
            col = S.spdcol(i);
            if col > 0, s = x(col); end
        case {'Pline', 'Qline', 'Iline'}
            f = pc.f; t = pc.t;
            if f >= 1 && f <= n && t >= 1 && t <= n && f ~= t
                s = line_quantity(S, f, t, V, TH, pc.sig);
            end
    end
catch
    s = V(sb);
end
end

function q = line_quantity(S, f, t, V, TH, sig)
% Line-quantity feedback at the branch's stored 'from' end: active power
% ('Pline'), reactive power ('Qline') or current magnitude ('Iline') on the
% branch f-t.  S.branch is the 13-col matrix: [f t r x b .. .. .. tap].
br = S.branch; r = 0;
for kk = 1:size(br,1)
    a = round(br(kk,1)); b = round(br(kk,2));
    if (a==f && b==t) || (a==t && b==f), r = kk; break; end
end
if r == 0, q = 0; return; end
fa = round(br(r,1)); ta = round(br(r,2));
y = 1/(br(r,3) + 1i*br(r,4)); bc = 1i*br(r,5)/2; a = 1;
if size(br,2) >= 9 && br(r,9) ~= 0, a = br(r,9); end          % off-nominal tap
Vf = V(fa)*exp(1i*TH(fa)); Vt = V(ta)*exp(1i*TH(ta));
If = (y + bc)/(a*a)*Vf - y/conj(a)*Vt;                        % current leaving 'from'
if strcmpi(sig,'Iline'), q = abs(If);
elseif strcmpi(sig,'Qline'), q = imag(Vf*conj(If));
else, q = real(Vf*conj(If)); end
end
