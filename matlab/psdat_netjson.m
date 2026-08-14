function out = psdat_netjson(file, NET)
% PSDAT_NETJSON  Shared network file: the bridge between the two editions.
%
%   NET = psdat_netjson('mynet.json')        % IMPORT a Python-lab diagram
%   psdat_netjson('mynet.json', NET)         % EXPORT for the Python lab
%
% Reads/writes the exact JSON the Python edition's "Save network data
% (.json)" produces (the browser NET object), so ONE drawn network opens in
% BOTH toolboxes and gives the same power flow, dynamics and eigenvalues --
% the cleanest possible cross-validation workflow for teaching and papers.
%
% Schema (Python side):
%   buses    [{x,y,type:'slack'|'pv'|'pq',Vset,Pd,Qd,Bs, rot?,flip?,name?}]
%   branches [{f,t,r,x,b,tap, xf?,name?}]           (1-based; tap 0 = none)
%   gens     [{bus,tag,Pg,Vset,S,md?,x,y}]          (md = machine-data map)
%   facts    [{type,...}]                            (union per device kind)
% Screen coordinates are y-DOWN; the MATLAB canvas is y-UP, so y negates on
% both directions of the bridge.  Unknown fields are preserved-by-omission:
% each side reads what it knows and defaults the rest, so files stay
% compatible across versions.
if nargin >= 2                                      % ---------------- EXPORT
    j = struct();
    j.name = NET.name;
    nb = numel(NET.btype);
    tp = {'pq','pv','slack'};
    buses = cell(1, nb);
    for i = 1:nb
        buses{i} = struct('x', NET.bx(i), 'y', -NET.by(i), ...
            'type', tp{max(1,min(3,round(NET.btype(i))))}, ...
            'Vset', NET.Vset(i), 'Pd', NET.Pd(i), 'Qd', NET.Qd(i), 'Bs', NET.Bs(i));
    end
    j.buses = buses;
    brs = cell(1, numel(NET.br_f));
    for k = 1:numel(NET.br_f)
        s = struct('f', NET.br_f(k), 't', NET.br_t(k), 'r', NET.br_r(k), ...
                   'x', NET.br_x(k), 'b', NET.br_b(k), 'tap', NET.br_tap(k));
        if NET.br_tap(k) ~= 0, s.xf = 1; end        % Python draws the 2-winding symbol
        brs{k} = s;
    end
    j.branches = brs;
    gs = cell(1, numel(NET.g_bus));
    for k = 1:numel(NET.g_bus)
        s = struct('bus', NET.g_bus(k), 'tag', NET.g_tag{k}, 'Pg', NET.g_Pg(k), ...
                   'Vset', NET.g_Vset(k), 'S', NET.g_S(k), ...
                   'x', NET.gx(k), 'y', -NET.gy(k));
        if numel(NET.g_md) >= k && ~isempty(NET.g_md{k}), s.md = NET.g_md{k}; end
        gs{k} = s;
    end
    j.gens = gs;
    fx = {};
    for k = 1:numel(NET.facts)
        d = NET.facts(k); s = struct('type', upper(d.type));
        fn = {'bus','Vref','Bmax','Bmin','Imax','Imin','Kr','Tr','Kaw','droop', ...
              'f','t','kcomp','kmin','kmax','Tc','Vsemax','f2','t2','kcomp2', ...
              'mode','Pset','Qset','P1set','Q1set','Q2set'};
        for a = 1:numel(fn)
            if isfield(d,fn{a}) && ~isempty(d.(fn{a})), s.(fn{a}) = d.(fn{a}); end
        end
        if isfield(d,'pod') && isstruct(d.pod), s.pod = d.pod; end
        if isfield(d,'x') && ~isempty(d.x), s.x = d.x; s.y = -d.y; end
        fx{end+1} = s;                                             %#ok<AGROW>
    end
    j.facts = fx;
    txt = jsonencode(j);
    fid = fopen(file, 'w');
    if fid < 0, error('psdat_netjson: cannot write %s', file); end
    fwrite(fid, txt, 'char'); fclose(fid);
    out = file;
    return;
end
% -------------------------------------------------------------------- IMPORT
txt = fileread(file);
j = jsondecode(txt);
gj = @(s, f, dv) getj(s, f, dv);
NET = struct('name','imported','btype',zeros(0,1),'Pd',zeros(0,1),'Qd',zeros(0,1), ...
    'Bs',zeros(0,1),'Vset',zeros(0,1),'bx',zeros(0,1),'by',zeros(0,1), ...
    'g_bus',zeros(0,1),'g_tag',{{}},'g_Pg',zeros(0,1),'g_Vset',zeros(0,1), ...
    'g_S',zeros(0,1),'g_md',{{}},'gx',zeros(0,1),'gy',zeros(0,1), ...
    'br_f',zeros(0,1),'br_t',zeros(0,1),'br_r',zeros(0,1),'br_x',zeros(0,1), ...
    'br_b',zeros(0,1),'br_tap',zeros(0,1));
NET.facts = jfacts_empty();
if isfield(j,'name') && ~isempty(j.name), NET.name = char(j.name); end
B = aslist(getj(j,'buses',[]));
tmap = struct('slack',3,'pv',2,'pq',1);
for i = 1:numel(B)
    b = B{i};
    ty = lower(char(gj(b,'type','pq')));
    if isfield(tmap, ty), NET.btype(i,1) = tmap.(ty); else, NET.btype(i,1) = 1; end
    NET.Pd(i,1)   = gj(b,'Pd',0);   NET.Qd(i,1)  = gj(b,'Qd',0);
    NET.Bs(i,1)   = gj(b,'Bs',0);   NET.Vset(i,1)= gj(b,'Vset',1.0);
    NET.bx(i,1)   = gj(b,'x',100*i); NET.by(i,1) = -gj(b,'y',0);
end
BR = aslist(getj(j,'branches',[]));
for k = 1:numel(BR)
    br = BR{k};
    NET.br_f(k,1) = round(gj(br,'f',1)); NET.br_t(k,1) = round(gj(br,'t',1));
    NET.br_r(k,1) = gj(br,'r',0);        NET.br_x(k,1) = gj(br,'x',0.05);
    NET.br_b(k,1) = gj(br,'b',0);        NET.br_tap(k,1) = gj(br,'tap',0);
end
G = aslist(getj(j,'gens',[]));
sp = max([max(NET.bx)-min(NET.bx), max(NET.by)-min(NET.by), 200]);
for k = 1:numel(G)
    g = G{k};
    NET.g_bus(k,1)  = round(gj(g,'bus',1));
    NET.g_tag{k}    = char(gj(g,'tag','SG'));
    NET.g_Pg(k,1)   = gj(g,'Pg',0);
    NET.g_Vset(k,1) = gj(g,'Vset',1.0);
    NET.g_S(k,1)    = gj(g,'S',max(abs(NET.g_Pg(k,1)),50)/0.8);
    md = getj(g,'md',[]);
    if isstruct(md), NET.g_md{k} = md; else, NET.g_md{k} = []; end
    ib = max(1, min(numel(NET.bx), NET.g_bus(k,1)));
    NET.gx(k,1) = gj(g,'x', NET.bx(ib));
    NET.gy(k,1) = -gj(g,'y', -(NET.by(ib) - 0.11*sp));
end
F = aslist(getj(j,'facts',[]));
for k = 1:numel(F)
    d = F{k}; s = jfact_default(char(gj(d,'type','SVC')));
    fn = fieldnames(s);
    for a = 1:numel(fn)
        v = getj(d, fn{a}, []);
        if ~isempty(v) && ~strcmp(fn{a},'pod'), s.(fn{a}) = v; end
    end
    pd = getj(d,'pod',[]);
    if isstruct(pd)
        p = s.pod; pf = fieldnames(p);
        for a = 1:numel(pf)
            v = getj(pd, pf{a}, []);
            if ~isempty(v), p.(pf{a}) = v; end
        end
        if ~islogical(p.on), p.on = isequal(p.on,1) || isequal(p.on,true); end
        s.pod = p;
    end
    if isfield(d,'x') && ~isempty(getj(d,'x',[])), s.x = getj(d,'x',0); s.y = -getj(d,'y',0); end
    if isempty(s.x) || (isscalar(s.x) && s.x == 0)          % glyph position fallback
        if ~isempty(s.bus) && s.bus >= 1 && s.bus <= numel(NET.bx)
            s.x = NET.bx(s.bus); s.y = NET.by(s.bus) + 0.10*sp;
        elseif ~isempty(s.f) && s.f >= 1 && s.f <= numel(NET.bx) && ...
               ~isempty(s.t) && s.t >= 1 && s.t <= numel(NET.bx)
            s.x = 0.5*(NET.bx(s.f)+NET.bx(s.t)); s.y = 0.5*(NET.by(s.f)+NET.by(s.t));
        else
            s.x = mean(NET.bx); s.y = mean(NET.by);
        end
    end
    NET.facts(end+1) = orderfields(s, NET.facts);            %#ok<AGROW>
end
out = NET;
end

% --------------------------------------------------------------- helpers --
function v = getj(s, f, dv)
% tolerant field read: works for struct / missing / empty
v = dv;
if isstruct(s) && isfield(s, f) && ~isempty(s.(f)), v = s.(f); end
end

function L = aslist(v)
% jsondecode gives a STRUCT ARRAY for uniform objects and a CELL array for
% mixed ones (FACTS!); normalize both to a cell list of scalar structs.
if iscell(v), L = v(:).';
elseif isstruct(v), L = num2cell(v(:).');
else, L = {};
end
end

function s = jfacts_empty()
s = struct('type',{},'bus',{},'Vref',{},'Bmax',{},'Bmin',{},'Imax',{},'Imin',{}, ...
    'Kr',{},'Tr',{},'Kaw',{},'droop',{},'signal',{},'f',{},'t',{},'kcomp',{}, ...
    'kmin',{},'kmax',{},'Tc',{},'Vsemax',{},'f2',{},'t2',{},'kcomp2',{},'mode',{}, ...
    'Pset',{},'Qset',{},'P1set',{},'Q1set',{},'Q2set',{},'pod',{},'x',{},'y',{});
end

function fd = jfact_default(ty)
% one device with the full field union (same order as PSDAT_App's emptyFacts)
ty = upper(ty);
kc = 0.4; if strcmp(ty,'UPFC'), kc = 0.3; end
pod = struct('on',false,'sig','Vbus','rbus',0,'f',0,'t',0,'i',0,'j',0,'tau',0, ...
             'Tw',10,'T1',0.30,'T2',0.05,'nc',2,'K',0,'lo',-0.10,'hi',0.10, ...
             'ctype','leadlag','Ki',0.5,'Kd',0.05,'Tf',0.02);
fd = struct('type',ty,'bus',0,'Vref',1.0,'Bmax',2,'Bmin',-2,'Imax',2,'Imin',-2, ...
    'Kr',20,'Tr',0.05,'Kaw',150,'droop',0,'signal','V','f',0,'t',0,'kcomp',kc, ...
    'kmin',-0.2,'kmax',0.7,'Tc',0.05,'Vsemax',0.20,'f2',0,'t2',0,'kcomp2',0.2, ...
    'mode','comp','Pset',[],'Qset',[],'P1set',[],'Q1set',[],'Q2set',[], ...
    'pod',pod,'x',0,'y',0);
end
