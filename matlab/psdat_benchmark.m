function NET = psdat_benchmark(SYS)
% PSDAT_BENCHMARK  Load a bundled benchmark as an editable single-line diagram.
%
%   NET = psdat_benchmark('IEEE9' | 'IEEE14' | 'IEEE30' | 'IEEE39' | ...
%                         'IEEE57' | 'IEEE118' | 'IEEE300' | 'Kundur2A' | 'case68')
%
% Returns the editor network struct NET (parallel arrays) for one of the
% bundled systems, complete with a hand-drawn schematic layout, so the user
% can open a benchmark in the interactive editor, modify any component, and
% re-analyse it -- exactly mirroring "load a built-in system as a diagram" in
% the Python lab (api_netload).  Reads the MATPOWER case file directly with
% feval (NO MATPOWER needed) and takes machine data from psdat_machinedata.
switch SYS
case {'IEEE9'}
    casefile = 'IEEE9Bus'; mdkey = 'IEEE9'; Sbase = [100 300 270];
    XY = [300 540; 80 120; 520 120; 300 440; 170 360; 430 360; ...
          170 210; 300 130; 430 210];
case {'IEEE14'}                        % read straight from MATPOWER case14.m
    casefile = 'case14'; mdkey = ''; Sbase = []; XY = [];
case {'IEEE30'}                        % read straight from MATPOWER case30.m
    casefile = 'case30'; mdkey = ''; Sbase = []; XY = [];
case {'IEEE39','NE39'}                 % New England 39-bus (MATPOWER case39.m)
    casefile = 'case39'; mdkey = ''; Sbase = []; XY = [];
case {'IEEE57'}                        % read straight from MATPOWER case57.m
    casefile = 'case57'; mdkey = ''; Sbase = []; XY = [];
case {'IEEE118'}                       % read straight from MATPOWER case118.m
    casefile = 'case118'; mdkey = ''; Sbase = []; XY = [];
case {'IEEE300'}                       % read straight from MATPOWER case300.m
    casefile = 'case300'; mdkey = ''; Sbase = []; XY = [];
case {'Kundur2A'}
    casefile = 'Kundur2A'; mdkey = 'Kundur2A'; Sbase = [900 900 900 900];
    XY = [90 250; 270 430; 810 250; 630 430; 180 250; 270 250; ...
          360 250; 450 250; 540 250; 630 250; 720 250];
case {'case68','NE68'}
    casefile = 'case68_16m'; mdkey = 'case68'; Sbase = 100*ones(1,16);
    XY = [550 358;691 139;852 182;885 440;960 491;849 593;766 620;588 501; ...
          493 592;378 367;368 298;422 135;367 60;126 436;60 369;70 280; ...
          351 103;114 289;859 465;920 484;806 513;818 566;773 580;761 523; ...
          561 469;527 494;547 436;492 521;504 546;441 302;405 338;393 271; ...
          343 247;333 188;266 161;391 164;664 446;323 300;204 97;218 428; ...
          149 407;109 355;299 81;240 93;213 133;244 298;373 417;288 434; ...
          179 294;130 223;159 174;654 401;465 382;551 390;630 361;679 299; ...
          648 233;686 185;626 183;581 210;475 220;806 204;750 182;765 218; ...
          783 250;749 316;769 387;772 467];
otherwise
    error('psdat_benchmark: unknown system %s', SYS);
end

mpc = feval(casefile);                 % MATPOWER case struct (no MATPOWER req.)
bus = mpc.bus; br = mpc.branch; gen = mpc.gen;
n = size(bus,1);
% MATPOWER status columns: drop out-of-service branches and offline units so
% the drawn diagram matches what actually operates.  (Every bundled small
% case is fully in service; this matters for the big IEEE imports.)
if size(br,2)  >= 11, br  = br(br(:,11) ~= 0, :);  end
if size(gen,2) >= 8,  gen = gen(gen(:,8) > 0, :);  end
m = size(gen,1);
% EXTERNAL -> INTERNAL numbering: the large IEEE imports ship with
% non-consecutive bus IDs (case300's numbering reaches 9533).  Every array
% in this editor indexes buses by ROW, so remap the branch endpoints and
% generator buses whenever the id column is not already 1..n.
ids = round(bus(:,1));
if ~isequal(ids(:).', 1:n)
    idmap = zeros(max(ids),1); idmap(ids) = 1:n;
    br(:,1)  = idmap(round(br(:,1)));  br(:,2) = idmap(round(br(:,2)));
    gen(:,1) = idmap(round(gen(:,1)));
end
if isempty(XY), XY = fd_layout(n, br(:,1:2)); end   % auto-layout when none is shipped
% MATPOWER bus columns: 1=id 2=type 3=Pd 4=Qd 5=Gs 6=Bs 8=Vm ; internal id=row
% (bundled cases are numbered 1..n contiguously, matching the engine's indexing)
NET.name  = SYS;
NET.btype = bus(:,2);
NET.Pd    = bus(:,3);
NET.Qd    = bus(:,4);
NET.Bs    = bus(:,6);
NET.Vset  = bus(:,8);
NET.bx    = XY(1:n,1);
NET.by    = -XY(1:n,2);                 % screen y-down -> MATLAB y-up

% branches
NET.br_f = br(:,1); NET.br_t = br(:,2);
NET.br_r = br(:,3); NET.br_x = br(:,4); NET.br_b = br(:,5);
if size(br,2) >= 9, NET.br_tap = br(:,9); else, NET.br_tap = zeros(size(br,1),1); end

% generators
gb = gen(:,1);
NET.g_bus  = gb;
NET.g_tag  = repmat({'SG'}, 1, m);
NET.g_Pg   = gen(:,2);
NET.g_Vset = gen(:,6);
if isempty(Sbase)                              % use each machine's own MVA base
    if size(gen,2) >= 7, Sbase = gen(:,7).'; else, Sbase = 100*ones(1,m); end
    Sbase(~(Sbase > 0)) = 100;
    % Cases WITHOUT validated dynamic data (IEEE14/30/57) get textbook default
    % machines scaled by their RATING -- but the case MBASE column often says
    % 100 MVA even for a 450-MW unit.  A rating below the dispatch puts the
    % default machine at delta0 ~ 70-80 deg with the exciter at ceiling: an
    % equilibrium on the edge of existence that the first disturbance kills
    % (the "time domain shows nothing" symptom).  Rate each machine from its
    % dispatch instead: S >= P/0.8, so delta0 lands in the healthy 20-40 deg.
    for kk = 1:m
        Sbase(kk) = max([Sbase(kk), abs(gen(kk,2))/0.8, 50]);
    end
end
NET.g_S    = Sbase(1:m).';
for k = 1:m, NET.Vset(gb(k)) = gen(k,6); end   % gen buses hold scheduled V
% a PV bus whose only unit is offline has nothing to hold its voltage:
% demote it to PQ so the power flow stays well-posed (IEEE 300 has several)
hasg = false(n,1); hasg(round(gb)) = true;
NET.btype(NET.btype == 2 & ~hasg) = 1;

% machine data: use the validated set when we have one; otherwise leave the
% cells empty so psdat_netcase assigns default_md() to every generator.
NET.g_md = cell(1, m);
if ~isempty(mdkey)
    MD = psdat_machinedata(mdkey, 2*pi*60);
    f  = fieldnames(MD);
    for k = 1:m
        md = struct();
        for a = 1:numel(f), md.(f{a}) = MD.(f{a})(k); end
        NET.g_md{k} = md;
    end
end

% generator glyph position: a short stub below the terminal busbar
span = max([max(NET.bx)-min(NET.bx), max(NET.by)-min(NET.by), 1]);
off  = 0.11*span;
NET.gx = zeros(m,1); NET.gy = zeros(m,1);
for k = 1:m
    NET.gx(k) = NET.bx(gb(k));
    NET.gy(k) = NET.by(gb(k)) - off;
end
end

% =========================================================================
function XY = fd_layout(n, ed)
% Deterministic Fruchterman-Reingold force-directed layout (no rand, so it is
% reproducible) for benchmark cases that ship without a hand-drawn schematic.
% Returns positive screen-style coordinates; View > Layout can refine it.
if n <= 1, XY = [400 400]; return; end
th = (0:n-1).'/n*2*pi; r0 = 4*sqrt(n);
XY = [r0*cos(th), r0*sin(th)];              % deterministic circular seed
if isempty(ed), ed = zeros(0,2); end
ed = ed(ed(:,1)>=1 & ed(:,2)>=1 & ed(:,1)<=n & ed(:,2)<=n, :);
k = 1.3*r0/sqrt(n);                         % ideal edge length
for it = 1:250
    D = zeros(n,2);
    for i = 1:n                             % repulsion (every pair)
        dx = XY(i,1)-XY(:,1); dy = XY(i,2)-XY(:,2);
        d2 = dx.^2 + dy.^2; d2(i) = inf; d2 = max(d2, 0.01);
        fr = (k*k)./d2;
        D(i,1) = D(i,1) + sum(dx.*fr); D(i,2) = D(i,2) + sum(dy.*fr);
    end
    for e = 1:size(ed,1)                    % attraction (along edges)
        a = ed(e,1); b = ed(e,2);
        dx = XY(a,1)-XY(b,1); dy = XY(a,2)-XY(b,2); fa = hypot(dx,dy)/k;
        D(a,1)=D(a,1)-dx*fa; D(a,2)=D(a,2)-dy*fa;
        D(b,1)=D(b,1)+dx*fa; D(b,2)=D(b,2)+dy*fa;
    end
    temp = r0*0.15*(1 - it/250) + 0.5;      % cooling schedule
    dl = hypot(D(:,1),D(:,2)); dl = max(dl,0.01);
    XY = XY + [D(:,1)./dl, D(:,2)./dl].*min(dl,temp);
end
XY = XY - min(XY);                          % shift to positive quadrant
s = 720/max(max(XY(:)),1); XY = XY*s + 60;
% ---- minimum-spacing relaxation: force-directed layouts can leave a few
% bus pairs almost touching (IEEE57's tightest pair lands ~10 px apart),
% which makes their busbars overlap at ANY glyph size.  A few deterministic
% push-apart passes guarantee every pair at least ~55 px of separation.
dmin = 55;
for pass = 1:30
    moved = false;
    for i = 1:n
        for j = i+1:n
            dx = XY(j,1)-XY(i,1); dy = XY(j,2)-XY(i,2);
            d = hypot(dx,dy);
            if d < dmin
                if d < 1e-6, dx = 1; dy = 0; d = 1; end   % coincident: split on x
                push = (dmin - d)/2 + 0.5;
                ux = dx/d; uy = dy/d;
                XY(i,:) = XY(i,:) - [ux uy]*push;
                XY(j,:) = XY(j,:) + [ux uy]*push;
                moved = true;
            end
        end
    end
    if ~moved, break; end
end
XY = XY - min(XY) + 60;                     % re-anchor after relaxation
end
