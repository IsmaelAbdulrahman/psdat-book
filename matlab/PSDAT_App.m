function PSDAT_App
% PSDAT_APP  Professional interactive single-line-diagram lab (MATLAB / Octave).
%
%   PSDAT_App
%
% A full schematic environment that MIRRORS the Python PSDAT lab, built
% entirely with classic figure / uicontrol / axes graphics so it runs on
% GNU Octave AND every MATLAB release (no App-Designer uifigure/uilabel).
%
%   RIBBON (top)   File  - New/Open/Save + benchmark loader
%                  Edit  - Undo/Redo/Delete + the Arrange... menu
%                  View  - Fit / zoom / Area / Select + the Layout... menu
%                  Visualize - Labels/Arrows/Heat/Alerts/Snap + display menus
%                  Results   - Report / PNG / SVG / About
%   PALETTE (left) two tabs: BUILD (drawing tools + FACTS palette) and
%                  ANALYZE (Power flow / Small-signal / Time domain /
%                  Design / Scenario workspaces + Reset).
%   CANVAS         click-to-add, drag-to-move, box-select, rubber-band lines.
%   INSPECTOR      right panel tabs: Properties (edit any component, incl. a
%                  29-parameter machine editor) - Data (editable input
%                  tables) - Report (results) - About (via the ribbon).
%   STATUS BAR     one full-width strip: tool guidance on the left,
%                  run/status messages on the right.
%
% Every analysis runs on the DRAWN network via psdat_netcase -> psdat_system
% (native, MATPOWER-free), validated to reproduce the Python reference to
% machine precision.  All model equations live in psdat_dae.m.

% ---- unit catalogue -----------------------------------------------------
h.UNITS = {'SG','SGP','SG6','SG6P','SG6G','SG4','SG4G','SG2', ...
           'GFM','GFL','PV-GFL','PV-GFM','BESS-GFM','BESS-GFL', ...
           'WT4-GFL','WT4-GFM','WT3','WT1','WT2'};
h.SGFAM = {'SG','SGP','SG6','SG6P','SG6G','SG4','SG4G','SG2'};
h.PFN   = {'nr','fdlf','gs'};
h.PFL   = {'Newton (NR)','Fast-dec.','Gauss-S.'};
h.KV    = {'fault','load','trip','gen','cloud','gust'};
h.KL    = {'network: 3-ph fault','network: load step','network: line outage', ...
           'generator: set-point pulse','source: cloud (PV)','source: gust (wind)'};
h.SCN   = {'pv_cloud','wind_types','bess_inertia','ffr','pod','syn_inertia','validate'};
h.TOOLS = {'select','bus','line','xfmr','gen','load','shunt','delete', ...
           'svc','statcom','tcsc','tssc','sssc','upfc','ipfc'};
h.TOOLL = {'Select','Bus','Line','Transformer', ...
           'Generator','Load','Shunt','Delete', ...
           'SVC','STATCOM','TCSC','TSSC','SSSC','UPFC','IPFC'};
h.NBASETOOL = 8;                         % tools 1..8 = editing; 9..15 = the grouped FACTS palette
h.MDF   = {'H','Xd','Xdp','Xdpp','Xq','Xqp','Xqpp','Td0p','Td0pp','Tq0p', ...
           'Tq0pp','Rs','Xls','Dm','KA','TA','KE','TE','KF','TF','Ax','Bx', ...
           'TCH','TSV','RD','Kpss','Tw','T1','T2'};   % last four: PSS (SGP / SG6P types)
h.BENCH = {'IEEE9','IEEE14','IEEE30','IEEE39','Kundur2A','case68'};
% (psdat_benchmark still understands IEEE57/IEEE118/IEEE300 for scripted
%  use -- the menu deliberately lists only the classroom set.)

% ---- theme: one coherent professional palette ---------------------------
%   navy   primary actions / active states     steel  captions, secondary text
%   ink    button + body text                  grey   field labels
%   panel  card surfaces    light  button faces    hair  hairline separators
%   tglon  the tint of an ACTIVE toggle (reads instantly, like a checked chip)
h.C.navy  = [0.12 0.23 0.43];  h.C.steel = [0.33 0.42 0.56];
h.C.ink   = [0.16 0.21 0.30];  h.C.hair  = [0.855 0.880 0.915];
h.C.light = [0.925 0.945 0.975]; h.C.panel = [0.972 0.980 0.992];
h.C.tglon = [0.845 0.885 0.955];
h.C.sel   = [0.92 0.45 0.08];  h.C.sel2  = [0.98 0.78 0.52];
h.C.load  = [0.478 0.318 0.118]; h.C.gen  = [0.12 0.23 0.43];   % load bronze: reads instantly as CONSUMPTION, never confusable with the green flow arrows
h.C.line  = [0.42 0.48 0.58];  h.C.grey  = [0.44 0.47 0.54];
h.C.bg    = [0.885 0.905 0.935]; h.C.ribbon= [0.985 0.990 1.0];
h.C.flow  = [0.16 0.42 0.30];  h.C.shunt = [0.15 0.42 0.32];

% ---- editor state -------------------------------------------------------
h.ED = struct('tool','select','selkind','none','selidx',0,'selset',[], ...
    'lineFrom',0,'drag',false,'dragPrev',[0 0],'boxsel',false,'boxstart',[0 0], ...
    'zoomarm',false,'zoomrect',false,'zoomstart',[0 0], ...
    'xlim',[0 1000],'ylim',[-680 20],'pf',[],'undo',{{}},'redo',{{}}, ...
    'snap',false,'gridsz',40,'grid',false,'flow',true,'flowphase',0,'heat',true, ...
    'flegend',false, ...
    'field','vmag','falpha',0.5,'arrowscale',1.0,'rptab','props','rescat',1, ...
    'labels',false,'detail',true,'alerts',false, ...
    'show',struct('busno',true,'lineno',false,'genlab',true,'loadlab',true, ...
                  'type',true,'volt',true,'flowlab',false,'factlab',true));

% ======================= window ==========================================
% classic figure; strip the default MATLAB menu/tool bars for a clean app shell
fig = figure('Name',['PSDAT - Interactive Single-Line-Diagram Lab   [' buildtag() ']'], ...
    'NumberTitle','off','Units','normalized','Position',[.02 .05 .96 .90], ...
    'Color',h.C.bg,'MenuBar','none','ToolBar','none','DockControls','off', ...
    'GraphicsSmoothing','on','DeleteFcn',@onAppClose);
fprintf('PSDAT %s   (%s)\n', buildtag(), which(mfilename));
try   % INSTALL SANITY CHECK -- a stale shadow copy on the MATLAB path is the
      % recurring support issue: the old file runs, the old bugs return, and
      % the new controls are nowhere to be seen.  Detect it AT STARTUP.
    aw = which('PSDAT_App','-all'); if ischar(aw), aw = {aw}; end
    me = fileparts(which(mfilename));
    td = which('PSDAT_TimeDomain');
    if numel(aw) > 1
        warndlg([{'More than one copy of PSDAT is on the MATLAB path:',''}, aw(:).', ...
                 {'','Only the FIRST one runs.  Delete or rename the stale folder', ...
                  '(or fix the path order) - mixed versions bring old bugs back.'}], ...
                'PSDAT - duplicate install detected');
    elseif ~isempty(td) && ~strcmp(fileparts(td), me)
        warndlg({'PSDAT files are loading from TWO different folders:', ...
                 ['  app:         ' me], ['  time domain: ' fileparts(td)], '', ...
                 'Mixed versions bring old bugs back - keep exactly ONE', ...
                 'PSDAT folder on the MATLAB path.'}, 'PSDAT - mixed install detected');
    end
    % COMPLETENESS: every engine file must exist AND load from the SAME
    % folder as the app -- a partial copy ("Undefined function
    % 'psdat_benchmark'") is diagnosed here, at startup, by name.
    req = {'psdat_benchmark','psdat_netcase','psdat_system','psdat_dae', ...
           'psdat_ybus','psdat_machinedata','psdat_netjson','psdat_podstep', ...
           'psdat_podmeasure','PSDAT_TimeDomain','PSDAT_Linearization', ...
           'PSDAT_Design','PSDAT_Scenarios'};
    miss = {}; wrng = {};
    for q = 1:numel(req)
        w = which(req{q});
        if isempty(w), miss{end+1} = ['   missing:  ' req{q} '.m'];        %#ok<AGROW>
        elseif ~strcmp(fileparts(w), me), wrng{end+1} = ['   foreign:  ' w]; %#ok<AGROW>
        end
    end
    if ~isempty(miss) || ~isempty(wrng)
        warndlg([{'This PSDAT installation is INCOMPLETE or MIXED:',''}, miss, wrng, ...
                 {'','Fix: delete the old PSDAT matlab folder, extract the ENTIRE', ...
                  'matlab folder from the delivered zip in its place, restart MATLAB.'}], ...
                'PSDAT - incomplete install detected');
    end
catch
end
% (no DefaultLineAlignVertexCenters here: pixel-snapping every line is a
% known native-crash correlate when combined with animated line updates in
% the new desktop's graphics pipeline -- crispness comes from the vector
% glyph weights instead)
% NOTE: no root-level DefaultAxesCreateFcn here.  Disabling the new-desktop
% interaction machinery from INSIDE an axes CreateFcn (mid-construction,
% inside a uicontrol callback) can deadlock the desktop outright -- the
% "app and MATLAB jam forever on Small-signal / Time domain" failure.  Every
% axes this app makes gets noAxInteract() AFTER creation instead, and result
% figures are opened OUTSIDE callbacks entirely (see deferFig).
% consistent modern typography everywhere (uicontrols inherit these defaults);
% fall back silently where a font is unavailable (Linux/Octave).
try
    fl = listfonts;
    for cand = {'Segoe UI','Helvetica Neue','DejaVu Sans','Helvetica'}
        if any(strcmpi(cand{1}, fl))
            set(fig,'DefaultUicontrolFontName',cand{1}, ...
                    'DefaultTextFontName',cand{1},'DefaultAxesFontName',cand{1});
            break;
        end
    end
catch
end
try   % ~30% larger UI type across the app chrome (barely-readable small text
      % on dense/high-DPI displays was the complaint); controls that set an
      % explicit size (report tables, dialogs) keep their own.
    set(fig,'DefaultUicontrolFontSize',10.5);
catch
end

% ==== RIBBON — clean TEXT toolstrip:  File · Edit · View · Visualize · Results
% Frequently-used commands sit directly on the ribbon; the selection utilities
% (align / distribute / rotate / flip) and the display details fold into two
% compact menus.  Slimmer than before, so the diagram gets more vertical space.
RB = uipanel('Parent',fig,'Units','normalized','Position',[.004 .852 .992 .143], ...
    'BackgroundColor',h.C.ribbon,'BorderType','line','HighlightColor',[.8 .82 .87]);
ribgroup = @(x,w,name) uipanel('Parent',RB,'Units','normalized','Position',[x .04 w .92], ...
    'Title',name,'TitlePosition','centertop','FontSize',9.5,'FontWeight','bold','ForegroundColor',h.C.steel, ...
    'BackgroundColor',h.C.ribbon,'BorderType','line','HighlightColor',[.85 .87 .91]);
ribbtn = @(par,x,y,w,ht,s,cb,tip) uicontrol('Parent',par,'Style','pushbutton','Units','normalized', ...
    'Position',[x y w ht],'String',s,'Callback',cb,'TooltipString',tip, ...
    'BackgroundColor',[1 1 1],'FontSize',10);
ribtgl = @(par,x,y,w,ht,s,tag,val,tip) uicontrol('Parent',par,'Style','togglebutton','Units','normalized', ...
    'Position',[x y w ht],'String',s,'Callback',@onToggle,'UserData',tag,'Value',val, ...
    'TooltipString',tip,'BackgroundColor',[1 1 1],'FontSize',10);
% pbtn carries a parameter in UserData so its callback is a NAMED handle
pbtn = @(par,x,y,w,ht,s,cb,tip,ud) uicontrol('Parent',par,'Style','pushbutton','Units','normalized', ...
    'Position',[x y w ht],'String',s,'Callback',cb,'TooltipString',tip,'UserData',ud, ...
    'BackgroundColor',[1 1 1],'FontSize',10);
R1 = .533; R2 = .067; RH = .40;               % two tall equal-height rows with EQUAL air above, between and below (1 - 2*RH = .20 split into three .067 pads)

% File --------------------------------------------------------------------
gF = ribgroup(.004,.132,'File');
ribbtn(gF,.03,R1,.30,RH,'New', @onNew, 'Start an empty network');
ribbtn(gF,.35,R1,.30,RH,'Open',@onOpen,'Open a saved .mat network');
ribbtn(gF,.67,R1,.30,RH,'Save',@onSave,'Save this network to .mat');
h.ddBench = uicontrol('Parent',gF,'Style','popupmenu','Units','normalized','Position',[.03 R2 .94 RH], ...
    'String',{'- load benchmark -','IEEE 9-bus','IEEE 14-bus','IEEE 30-bus', ...
              'IEEE 39-bus (New England)','Kundur two-area','68-bus NETS-NYPS'}, ...
    'Callback',@onLoadBench,'FontSize',9.8,'TooltipString','load a bundled benchmark system onto the canvas');

% Edit — undo / redo / delete, and EVERY selection utility in one menu ----
gE = ribgroup(.140,.138,'Edit');
h.bUndo = ribbtn(gE,.03,R1,.30,RH,'Undo',@onUndo,'Undo the last edit');
h.bRedo = ribbtn(gE,.35,R1,.30,RH,'Redo',@onRedo,'Redo the undone edit');
ribbtn(gE,.67,R1,.30,RH,'Delete',@onDelSel,'Delete the selected component');
h.ddArr = uicontrol('Parent',gE,'Style','popupmenu','Units','normalized','Position',[.03 R2 .94 RH], ...
    'String',{'Arrange...','Align left','Align centres','Align right','Align top','Align middles', ...
              'Distribute evenly','Rotate 90 deg','Flip horizontal','Flip vertical'}, ...
    'Callback',@onArrangeMenu,'FontSize',9.8, ...
    'TooltipString','selection utilities - box-select 2+ buses for the align commands');

% View — zoom + the full layout catalogue ---------------------------------
gV = ribgroup(.282,.178,'View');
ribbtn(gV,.030,R1,.200,RH,'Fit',@onFit,'Zoom to fit the whole network');
pbtn(gV,.245,R1,.115,RH,'-',@onZoom,'Zoom out (mouse wheel / two-finger scroll works anywhere on the canvas)',1.25);
pbtn(gV,.375,R1,.115,RH,'+',@onZoom,'Zoom in (mouse wheel / two-finger scroll works anywhere on the canvas)',0.8);
ribbtn(gV,.505,R1,.215,RH,'Area',@onZoomArea,'Drag a rectangle on the canvas to zoom into exactly that area (a plain click steps in)');
ribbtn(gV,.735,R1,.235,RH,'Select',@onSelTool,'Back to the SELECTION pointer from any drawing tool - click components to select and edit them');
h.ddLayout = uicontrol('Parent',gV,'Style','popupmenu','Units','normalized','Position',[.03 R2 .94 RH], ...
    'String',{'Layout...','Auto (smart)','Force-directed','Hierarchical','Tree','Radial','Circular','Grid','Orthogonal','Kamada-Kawai','Electrical','Beautify (snap)','Min. crossings','Equal spacing','Straighten','Compact','Expand','Restore default'}, ...
    'Callback',@onLayout,'FontSize',9.8,'TooltipString','professional graph layouts + arrange commands');

% Visualize — five master toggles + three compact menus -------------------
gVi = ribgroup(.464,.362,'Visualize');
h.cLabels = ribtgl(gVi,.012,R1,.144,RH,'Labels','labels',0,'Show / hide ALL diagram labels (off by default for a clean SLD; pick individual label types under Labels...)');
h.cFlow   = ribtgl(gVi,.170,R1,.144,RH,'Arrows','flow',1,'Animated power-flow arrows (run a power flow first)');
h.cHeat   = ribtgl(gVi,.328,R1,.144,RH,'Heat','heat',1,'Voltage / loading heat-map overlay (the colour-bar legend card is a separate switch under Display options)');
h.cAlert  = ribtgl(gVi,.486,R1,.144,RH,'Alerts','alerts',0,'Highlight overloads and voltage violations');
h.cSnap   = ribtgl(gVi,.644,R1,.144,RH,'Snap','snap',0,'Snap dragged components to the grid');
h.ddMode  = uicontrol('Parent',gVi,'Style','popupmenu','Units','normalized','Position',[.800 R1 .188 RH], ...
    'String',{'Simplified','Detailed'},'Value',2,'Callback',@onMode,'FontSize',9.8, ...
    'TooltipString','Simplified = clean essential labels; Detailed = full readouts');
h.ddField = uicontrol('Parent',gVi,'Style','popupmenu','Units','normalized','Position',[.012 R2 .30 RH], ...
    'String',{'Heat: |V| (pu)','Heat: angle (deg)','Heat: line loading','Heat: line loss','Heat: reactive Q'}, ...
    'Callback',@onField,'FontSize',9.8,'TooltipString','quantity painted by the heat-map overlay');
h.ddLab = uicontrol('Parent',gVi,'Style','popupmenu','Units','normalized','Position',[.322 R2 .30 RH], ...
    'String',{'Labels...'},'Callback',@onLabMenu,'FontSize',9.8, ...
    'TooltipString','choose WHICH labels appear on the diagram (bus numbers, voltages, flows, ...)');
h.ddViz = uicontrol('Parent',gVi,'Style','popupmenu','Units','normalized','Position',[.632 R2 .356 RH], ...
    'String',{'Display options...'},'Callback',@onVizMenu,'FontSize',9.8, ...
    'TooltipString','background grid, arrow size and heat transparency');

% Results — report + exports ----------------------------------------------
gRes = ribgroup(.830,.162,'Results');
pbtn(gRes,.03,R1,.55,RH,'Report',@onTab,'Open the results browser (bus / line / generator tables)','report');
% Reset lives HERE now (moved out of the left palette so the analysis
% workspaces get the vertical room): stop any running analysis and clear
% results/overlays; press twice within 2 s to force-free a wedged interface.
h.bReset = uicontrol('Parent',gRes,'Style','pushbutton','Units','normalized', ...
    'Position',[.61 R1 .36 RH],'String','Reset','FontSize',10,'FontWeight','bold', ...
    'BackgroundColor',[1 1 1],'ForegroundColor',[.55 .10 .10],'Callback',@onReset, ...
    'TooltipString','Stop any running analysis and clear results / overlays (press twice to force-free)');
pbtn(gRes,.03,R2,.30,RH,'PNG',@onExport,'Export the diagram as a PNG image','png');
pbtn(gRes,.35,R2,.30,RH,'SVG',@onExport,'Export the diagram as an SVG vector drawing','svg');
pbtn(gRes,.67,R2,.30,RH,'About',@onTab,'About PSDAT - version, references, credits','about');

% (the disturbance controls live in the left palette's SIMULATION group, with
%  the other run controls — the strip that used to sit over the canvas is gone,
%  so the drawing area reads as a clean dedicated SLD canvas.)

% ======================= LEFT PALETTE ====================================
% TABBED like the right-hand inspector: two tabs — BUILD | ANALYZE — with one
% full-width panel visible at a time.  Everything fits without scrolling, on a
% generous row rhythm, mirroring the Properties/Report/About idiom.
h.tabBuild = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.004 .806 .0875 .040],'String','Build','FontWeight','bold','FontSize',11.5, ...
    'Callback',@onLeftTab,'UserData','build','TooltipString','network components: buses, lines, machines, FACTS');
h.tabAnalyze = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.0915 .806 .0875 .040],'String','Analyze','FontWeight','bold','FontSize',11.5, ...
    'Callback',@onLeftTab,'UserData','analyze','TooltipString','studies: power flow, dynamics, design, scenarios');
% ---- SCROLLABLE PALETTES ------------------------------------------------
% Each tab is a clipping VIEWPORT (PAv/PBv) holding a full-height CONTENT
% panel (PA/PB -- every control below parents into these, unchanged).  On
% tall windows the content fills its viewport 1:1 and nothing differs from
% before.  On short windows, updatePalScroll pins the content to a
% comfortable minimum PIXEL height and reveals a slim slider: controls can
% then never shrink below their native pixel size and overpaint their
% neighbours (the popup/edit-field bleed on small screens) -- you scroll
% instead.  The mouse wheel over the palette scrolls it too.
PAv = uipanel('Parent',fig,'Units','normalized','Position',[.004 .046 .175 .752], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87]);
PBv = uipanel('Parent',fig,'Units','normalized','Position',[.004 .046 .175 .752], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87],'Visible','off');
PA = uipanel('Parent',PAv,'Units','normalized','Position',[0 0 1 1], ...
    'BackgroundColor',h.C.panel,'BorderType','none');
PB = uipanel('Parent',PBv,'Units','normalized','Position',[0 0 1 1], ...
    'BackgroundColor',h.C.panel,'BorderType','none');
h.sPA = uicontrol('Parent',PAv,'Style','slider','Units','normalized', ...
    'Position',[.952 0 .048 1],'Min',0,'Max',1,'Value',1, ...
    'SliderStep',[.08 .30],'Callback',@onPalScroll,'UserData','A','Visible','off');
h.sPB = uicontrol('Parent',PBv,'Style','slider','Units','normalized', ...
    'Position',[.952 0 .048 1],'Min',0,'Max',1,'Value',1, ...
    'SliderStep',[.08 .30],'Callback',@onPalScroll,'UserData','B','Visible','off');
h.PA = PAv; h.PB = PBv;          % the tab switch toggles the VIEWPORTS
h.PAi = PA; h.PBi = PB;          % the scrolling content panels
% section titles: CENTRED (matching the ribbon groups' centred titles), bold,
% in a box TALL enough for ascenders + descenders at any window size / DPI
% scaling, with clear air between the hairline above, the title, and the
% row below -- the title text can never touch a border.
subA = @(par,y,txt) uicontrol('Parent',par,'Style','text','Units','normalized', ...
    'Position',[.05 y .90 .038],'String',txt,'FontSize',9.5,'FontWeight','bold', ...
    'ForegroundColor',h.C.steel,'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
hr = @(par,y) uicontrol('Parent',par,'Style','frame','Units','normalized', ...
    'Position',[.05 y .90 .0022],'BackgroundColor',h.C.hair,'ForegroundColor',h.C.hair);

% ---- BUILD tab -----------------------------------------------------------
h.toolBtn = cell(1,numel(h.TOOLS));
tb = @(y,k,tip) uicontrol('Parent',PA,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 y .90 .044],'String',h.TOOLL{k},'Callback',@onTool,'UserData',k, ...
    'BackgroundColor',h.C.light,'ForegroundColor',h.C.ink,'FontSize',11,'TooltipString',tip);
tipsB = {'Click to select / drag components','Click the canvas to place a busbar', ...
         'Click the FROM busbar, then the TO busbar','Click FROM then TO busbar (tap editable)', ...
         'Click the busbar the machine connects to','Click a busbar to add a P+jQ demand', ...
         'Click a busbar to add a +/- MVAr shunt','Click a component to remove it'};
% EDITING ACTIONS first -- Select and Delete are modes of the POINTER, not
% network components, so they share their own half-width row on top and
% never mix into the component palette below.
tb2 = @(x,y,k,tip) uicontrol('Parent',PA,'Style','pushbutton','Units','normalized', ...
    'Position',[x y .435 .044],'String',h.TOOLL{k},'Callback',@onTool,'UserData',k, ...
    'BackgroundColor',h.C.light,'ForegroundColor',h.C.ink,'FontSize',11,'TooltipString',tip);
h.toolBtn{1} = tb2(.050,.946,1,tipsB{1});
h.toolBtn{8} = tb2(.515,.946,8,tipsB{8});
hr(PA,.932); subA(PA,.884,'COMPONENTS — click to place');
for k = 2:7
    h.toolBtn{k} = tb(.832 - .052*(k-2), k, tipsB{k});
end
hr(PA,.556); subA(PA,.506,'FACTS — shunt, drop on a bus');
h.toolBtn{9}  = tb(.454, 9,'SVC — thyristor shunt compensator holding its bus voltage (Q = B|V|^2)');
h.toolBtn{10} = tb(.402,10,'STATCOM — VSC shunt compensator, current-limited (Q = |V|I)');
hr(PA,.386); subA(PA,.336,'FACTS — series, click a line');
h.toolBtn{11} = tb(.284,11,'TCSC — continuously-variable series compensation (x_eff = x(1-k))');
h.toolBtn{12} = tb(.232,12,'TSSC — step-switched series capacitor');
h.toolBtn{13} = tb(.180,13,'SSSC — VSC injecting a controllable series voltage');
hr(PA,.164); subA(PA,.114,'FACTS — combined, click a line');
h.toolBtn{14} = tb(.062,14,'UPFC — shunt + series converters on a common DC link; composition or P-Q mode');
h.toolBtn{15} = tb(.010,15,'IPFC — two series converters, DC-coupled; set line 2 in Properties');

% ---- ANALYZE tab ---------------------------------------------------------
% Row heights are GENEROUS on purpose: popup/edit controls render at their
% font's natural pixel height, which on high-DPI displays overflows a tight
% box and clips the bottom border.  Every row here leaves clear air below
% its control, so all four border edges always show at any DPI scaling.
% MODULAR WORKSPACES: one dedicated sub-panel per analysis, the idiom of
% commercial tools (PSS(R)E / PowerFactory study environments).  The selector
% below switches which workspace is visible; every workspace operates on the
% SAME shared network model, but shows ONLY its own controls -- steady-state
% settings never mix with disturbance settings or design settings.
h.AMODS = {'pf','ss','td','ds','sc'};
alab = {'Power flow','Small-signal','Time domain','Design','Scenario'};
atip = {'steady-state workspace: solver method + results overlay', ...
        'modal workspace: eigenvalues, damping, participation factors', ...
        'dynamic workspace: disturbance, simulation time, run/stop', ...
        'design workspace: POD damping-controller synthesis', ...
        'study workspace: guided comparison scenarios'};
h.amodBtn = cell(1,5);
for q = 1:5
    h.amodBtn{q} = uicontrol('Parent',PB,'Style','pushbutton','Units','normalized', ...
        'Position',[.05 .944-.056*(q-1) .90 .048],'String',alab{q},'FontSize',11, ...
        'Callback',@onModule,'UserData',h.AMODS{q},'TooltipString',atip{q}, ...
        'BackgroundColor',[1 1 1],'ForegroundColor',h.C.ink);
end
hr(PB,.708);
% workspaces run all the way to the panel bottom -- Reset moved to the
% ribbon's Results group, so the analysis content gets every pixel.
mp = @() uipanel('Parent',PB,'Units','normalized','Position',[0 .010 1 .692], ...
    'BackgroundColor',h.C.panel,'BorderType','none','Visible','off');
runb = @(par,s,cb,tip) uicontrol('Parent',par,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 .918 .90 .068],'String',s,'FontWeight','bold','FontSize',11, ...
    'BackgroundColor',h.C.navy,'ForegroundColor','w','Callback',cb,'TooltipString',tip);
hint = @(par,y,hh,s) uicontrol('Parent',par,'Style','text','Units','normalized', ...
    'Position',[.05 y .90 hh],'String',s,'FontSize',9.3,'ForegroundColor',h.C.steel, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','left');
% ---- POWER FLOW workspace ------------------------------------------------
h.MPF = mp();
runb(h.MPF,'Run power flow',@onPF,'Solve the steady state and overlay the results on the diagram');
uicontrol('Parent',h.MPF,'Style','text','Units','normalized','Position',[.05 .838 .90 .052], ...
    'String','solver method','FontSize',10.5,'ForegroundColor',h.C.grey, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','left');
h.ddPF = uicontrol('Parent',h.MPF,'Style','popupmenu','Units','normalized','Position',[.05 .758 .90 .064], ...
    'String',h.PFL,'FontSize',10.5,'TooltipString','Newton-Raphson / fast-decoupled / Gauss-Seidel');
hint(h.MPF,.30,.44,sprintf(['Steady-state analysis of the drawn network.\n\n' ...
    'Results go to the diagram overlay (voltages, flows,\nheat map) and to the Report tab tables.\n\n' ...
    'All three solvers reach the same solution -- compare\ntheir iteration counts in the report header.']));
% ---- SMALL-SIGNAL workspace ----------------------------------------------
h.MSS = mp();
runb(h.MSS,'Run small-signal',@onSS,'Linearize at the operating point: eigenvalues, damping, mode table');
hint(h.MSS,.30,.56,sprintf(['Modal analysis at the power-flow operating point.\n\n' ...
    'Opens the eigenvalue map and fills the Report tab\nwith every oscillatory mode: frequency, damping\nratio and stability verdict.\n\n' ...
    'Machine technologies and FACTS/POD controllers on\nthe diagram are all part of the state matrix.']));
% ---- TIME DOMAIN workspace -----------------------------------------------
h.MTD = mp();
runb(h.MTD,'Run time domain',@onTD,'Integrate the nonlinear DAE with the disturbance configured below');
uicontrol('Parent',h.MTD,'Style','text','Units','normalized','Position',[.05 .842 .90 .050], ...
    'String','DISTURBANCE','FontWeight','bold','ForegroundColor',h.C.navy,'FontSize',11, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
h.ddK = uicontrol('Parent',h.MTD,'Style','popupmenu','Units','normalized', ...
    'Position',[.05 .756 .90 .066],'String',h.KL,'FontSize',10.5, ...
    'TooltipString','event applied when the simulation runs','Callback',@onDisturb);
lbls = {'bus','size','t_on (s)','t_off (s)','t_sim (s)'}; defs = {'1','0.15','1.0','1.1','10'};
ed = cell(1,5); h.eLab = cell(1,5);
for j = 1:5
    y = .664 - .086*(j-1);
    h.eLab{j} = uicontrol('Parent',h.MTD,'Style','text','Units','normalized', ...
        'Position',[.05 y-.006 .32 .056],'String',lbls{j},'FontSize',10.5, ...
        'HorizontalAlignment','left','BackgroundColor',h.C.panel,'ForegroundColor',h.C.grey);
    ed{j} = uicontrol('Parent',h.MTD,'Style','edit','Units','normalized', ...
        'Position',[.39 y .56 .066],'String',defs{j},'BackgroundColor','w','FontSize',11, ...
        'HorizontalAlignment','center');
end
h.eLoc = ed{1}; h.eMag = ed{2}; h.eT1 = ed{3}; h.eT2 = ed{4}; h.eTs = ed{5};
% ---- RESULT SIGNAL: after a run, plot ANY stored trajectory -- rotor
% angles / speeds, bus voltages / angles or the COI frequency -- straight
% from the kept solution, no re-simulation.
hr(h.MTD,.300);
uicontrol('Parent',h.MTD,'Style','text','Units','normalized','Position',[.05 .244 .90 .042], ...
    'String','RESULT SIGNAL','FontWeight','bold','ForegroundColor',h.C.navy,'FontSize',10.5, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
h.ddTDsig = uicontrol('Parent',h.MTD,'Style','popupmenu','Units','normalized', ...
    'Position',[.05 .164 .58 .064],'FontSize',9.5,'Value',1, ...
    'String',{'COI frequency (Hz)','Rotor angles (deg)','Rotor speeds (pu)', ...
              'Bus voltages (pu)','Bus angles (deg)'}, ...
    'TooltipString','which signal of the LAST time-domain run to plot');
h.bTDplot = uicontrol('Parent',h.MTD,'Style','pushbutton','Units','normalized', ...
    'Position',[.66 .162 .29 .068],'String','Plot','FontWeight','bold','FontSize',10.5, ...
    'BackgroundColor',h.C.light,'ForegroundColor',h.C.ink,'Callback',@onTDPlot, ...
    'TooltipString','open the chosen signal of the last run as a figure');
hint(h.MTD,.016,.116,sprintf(['Stop floats over the canvas while a run is active.\n' ...
    'After the run: pick a signal above, press Plot.']));
% ---- DESIGN workspace ----------------------------------------------------
h.MDS = mp();
runb(h.MDS,'Run POD design',@onDS,'Residue-based damping-controller synthesis + exact closed-loop check');
dsl = {'actuator unit #','target damping (%)'}; dsd = {'2','20'};
h.dsEd = cell(1,2);
for j = 1:2
    y = .790 - .084*(j-1);
    uicontrol('Parent',h.MDS,'Style','text','Units','normalized','Position',[.05 y-.006 .52 .054], ...
        'String',dsl{j},'FontSize',10.5,'HorizontalAlignment','left', ...
        'BackgroundColor',h.C.panel,'ForegroundColor',h.C.grey);
    h.dsEd{j} = uicontrol('Parent',h.MDS,'Style','edit','Units','normalized', ...
        'Position',[.60 y .35 .064],'String',dsd{j},'BackgroundColor','w','FontSize',11, ...
        'HorizontalAlignment','center');
end
hint(h.MDS,.20,.40,sprintf(['Designs a power-oscillation damper on the chosen\n' ...
    'machine: washout + lead-lag phase compensation\nfrom the residue of the least-damped mode.\n\n' ...
    'The figure compares open- vs closed-loop\neigenvalues; the Report tab lists K, Tw, T1, T2.']));
% ---- SCENARIO workspace --------------------------------------------------
h.MSC = mp();
runb(h.MSC,'Run scenario',@onSC,'Execute the guided study picked below (opens comparison figures)');
uicontrol('Parent',h.MSC,'Style','text','Units','normalized','Position',[.05 .838 .90 .052], ...
    'String','guided study','FontSize',10.5,'ForegroundColor',h.C.grey, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','left');
h.ddScn = uicontrol('Parent',h.MSC,'Style','popupmenu','Units','normalized','Position',[.05 .758 .90 .064], ...
    'String',h.SCN,'FontSize',10.5,'TooltipString','pick a guided scenario');
hint(h.MSC,.26,.48,sprintf(['Ready-made comparison studies on the bundled\nbenchmarks:\n\n' ...
    'pv_cloud - GFL vs GFM PV through a cloud\nwind_types - one gust, three turbine types\n' ...
    'bess_inertia - SOC limits of battery support\nffr - fast-frequency-response gain sweep\n' ...
    'pod - the Kundur POD design showcase\nsyn_inertia - synthetic-inertia payback\nvalidate - published-mode self test']));
% (Reset moved to the ribbon's Results group -- the workspaces above now
%  use the full palette height.  Stop still lives ONLY as the red button
%  that floats over the canvas while a run is active.)

% ======================= CANVAS ==========================================
% A dedicated SLD drawing surface, not a MATLAB plot: no title, no box, no
% ticks, no grid, and the axis lines painted in the background colour so no
% frame is visible — the diagram floats on a clean white canvas.
h.ax = axes('Parent',fig,'Units','normalized','Position',[.183 .046 .511 .796], ...
    'XTick',[],'YTick',[],'Box','off','Color',[1 1 1], ...
    'XColor',[1 1 1],'YColor',[1 1 1],'XGrid','off','YGrid','off','Visible','on');
noAxInteract(h.ax);                                % the SLD has its own mouse handling
% ---- STATUS BAR: one full-width strip along the bottom (the professional
% idiom): tool guidance on the LEFT, run/status messages on the RIGHT, with
% a hairline separating it from the three columns above.  Tall enough that
% its text can never clip at any DPI (the old 0.8%-high strip clipped).
uicontrol('Parent',fig,'Style','frame','Units','normalized', ...
    'Position',[.004 .040 .992 .0016],'BackgroundColor',h.C.hair,'ForegroundColor',h.C.hair);
h.hint = uicontrol('Parent',fig,'Style','text','Units','normalized', ...
    'Position',[.010 .006 .432 .028],'String','','BackgroundColor',h.C.bg, ...
    'ForegroundColor',h.C.steel,'HorizontalAlignment','left','FontAngle','italic','FontSize',9.5);

% ======================= RIGHT INSPECTOR (tabbed) ========================
h.tabP = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.700 .822 .099 .040],'String','Properties','Callback',@onTab,'UserData','props', ...
    'FontWeight','bold','FontSize',11.5);
h.tabD = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.799 .822 .098 .040],'String','Data','Callback',@onTab,'UserData','data', ...
    'FontWeight','bold','FontSize',11.5,'TooltipString','ALL input data / parameters - editable tables');
h.tabR = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.897 .822 .099 .040],'String','Report','Callback',@onTab,'UserData','report', ...
    'FontWeight','bold','FontSize',11.5,'TooltipString','numerical RESULTS - read-only');
h.tabA = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.926 .822 .070 .040],'String','About','Callback',@onTab,'UserData','about', ...
    'FontWeight','bold','FontSize',11.5,'Visible','off');   % lives in the ribbon now

% --- Properties panel ---
RP = uipanel('Parent',fig,'Units','normalized','Position',[.700 .046 .296 .768], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87]);
h.RP = RP;
h.pTitle = uicontrol('Parent',RP,'Style','text','Units','normalized', ...
    'Position',[.05 .952 .90 .040],'String','Properties','FontWeight','bold', ...
    'FontSize',12,'ForegroundColor',h.C.navy,'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
uicontrol('Parent',RP,'Style','frame','Units','normalized','Position',[.05 .944 .90 .0022], ...
    'BackgroundColor',h.C.hair,'ForegroundColor',h.C.hair);
h.pTypeLab = uicontrol('Parent',RP,'Style','text','Units','normalized', ...
    'Position',[.05 .898 .43 .036],'String','Type','BackgroundColor',h.C.panel, ...
    'ForegroundColor',h.C.grey,'HorizontalAlignment','left');
h.pType = uicontrol('Parent',RP,'Style','popupmenu','Units','normalized', ...
    'Position',[.50 .894 .45 .046],'String',{' '},'Callback',@onPropType, ...
    'TooltipString','component type / technology');
h.pEd = cell(1,5); h.pEdLab = cell(1,5);
for j = 1:5
    y = 0.838 - (j-1)*0.058;
    h.pEdLab{j} = uicontrol('Parent',RP,'Style','text','Units','normalized', ...
        'Position',[.05 y+.004 .43 .036],'String','','BackgroundColor',h.C.panel, ...
        'ForegroundColor',h.C.grey,'HorizontalAlignment','left');
    h.pEd{j} = uicontrol('Parent',RP,'Style','edit','Units','normalized', ...
        'Position',[.50 y .45 .044],'String','','BackgroundColor','w', ...
        'HorizontalAlignment','center');
end
h.pBtnMD = uicontrol('Parent',RP,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 .540 .90 .050],'String','Machine data...','Callback',@onEditMachine, ...
    'BackgroundColor',h.C.light);
h.pApply = uicontrol('Parent',RP,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 .472 .43 .052],'String','Apply','FontWeight','bold', ...
    'BackgroundColor',h.C.navy,'ForegroundColor','w','Callback',@onApply, ...
    'TooltipString','write these values into the network (undo-able)');
h.pDel = uicontrol('Parent',RP,'Style','pushbutton','Units','normalized', ...
    'Position',[.52 .472 .43 .052],'String','Delete','FontWeight','bold', ...
    'BackgroundColor',[0.7 0.2 0.15],'ForegroundColor','w','Callback',@onDelSel, ...
    'TooltipString','remove the selected component from the diagram');
h.pInfo = uicontrol('Parent',RP,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 .404 .90 .046],'String','Model equations & theory...', ...
    'Callback',@onTheory,'BackgroundColor',h.C.light,'FontSize',10, ...
    'TooltipString',['EDUCATIONAL MODE: the governing equations, state variables, ' ...
    'parameters, assumptions and textbook references of the selected component''s model ' ...
    '- exactly the equations psdat_dae.m integrates'],'Visible','off');
h.pHelp = uicontrol('Parent',RP,'Style','text','Units','normalized','Position',[.05 .025 .90 .360], ...
    'String','','BackgroundColor',h.C.panel,'ForegroundColor',h.C.steel, ...
    'HorizontalAlignment','left','FontSize',9.5);

% --- Report panel ---
RR = uipanel('Parent',fig,'Units','normalized','Position',[.700 .046 .296 .768], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87],'Visible','off');
h.RR = RR;
uicontrol('Parent',RR,'Style','text','Units','normalized','Position',[.05 .952 .90 .040], ...
    'String','Results','FontWeight','bold','FontSize',12,'ForegroundColor',h.C.navy, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
uicontrol('Parent',RR,'Style','frame','Units','normalized','Position',[.05 .944 .90 .0022], ...
    'BackgroundColor',h.C.hair,'ForegroundColor',h.C.hair);
h.ddCat = uicontrol('Parent',RR,'Style','popupmenu','Units','normalized','Position',[.05 .892 .90 .046], ...
    'String',{'Results'},'Callback',@onCat,'FontSize',9.5,'TooltipString','result category');
uicontrol('Parent',RR,'Style','text','Units','normalized','Position',[.05 .856 .46 .030], ...
    'String','click = highlight; double-click = zoom', ...
    'FontSize',8,'FontAngle','italic','ForegroundColor',h.C.grey, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','left');
h.resCopy = uicontrol('Parent',RR,'Style','pushbutton','Units','normalized', ...
    'Position',[.53 .852 .20 .036],'String','Copy','FontSize',8.5, ...
    'BackgroundColor',h.C.light,'Callback',@onResCopy, ...
    'TooltipString','copy this whole table to the clipboard (paste into Excel / a report)');
h.resCsv = uicontrol('Parent',RR,'Style','pushbutton','Units','normalized', ...
    'Position',[.75 .852 .20 .036],'String','CSV...','FontSize',8.5, ...
    'BackgroundColor',h.C.light,'Callback',@onResExport, ...
    'TooltipString','export this table to a CSV file (opens in Excel / Python / LaTeX tooling)');
h.ddSort = uicontrol('Parent',RR,'Style','popupmenu','Units','normalized', ...
    'Position',[.05 .800 .55 .044],'String',{'Sort: original order'},'Value',1, ...
    'FontSize',8.5,'Callback',@onSortCol,'Enable','off', ...
    'TooltipString','sort the table by any column (Excel-style)');
h.bSortDir = uicontrol('Parent',RR,'Style','pushbutton','Units','normalized', ...
    'Position',[.62 .802 .33 .040],'String','ascending','FontSize',8.5, ...
    'BackgroundColor',h.C.light,'Callback',@onSortDir, ...
    'TooltipString','flip between ascending and descending order');
h.res = uicontrol('Parent',RR,'Style','listbox','Units','normalized', ...
    'Position',[.05 .050 .90 .742],'FontName','Courier','FontSize',9, ...
    'BackgroundColor','w','String',{'Run an analysis to see results here.'}, ...
    'Callback',@onResClick,'Value',1);
h.resStat = uicontrol('Parent',RR,'Style','text','Units','normalized', ...
    'Position',[.05 .012 .90 .030],'String','','FontSize',8.5, ...
    'ForegroundColor',h.C.steel,'BackgroundColor',h.C.panel,'HorizontalAlignment','left');
h.repmap = {[]}; h.RC = {};

% --- About panel ---
RA = uipanel('Parent',fig,'Units','normalized','Position',[.700 .046 .296 .768], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87],'Visible','off');
h.RA = RA;
uicontrol('Parent',RA,'Style','text','Units','normalized','Position',[.05 .885 .90 .090], ...
    'String','PSDAT','FontWeight','bold','FontSize',22,'ForegroundColor',h.C.navy, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
uicontrol('Parent',RA,'Style','text','Units','normalized','Position',[.06 .10 .88 .760], ...
    'String',sprintf(['Power System Dynamic Analysis Toolbox\n\n' ...
    'Interactive single-line-diagram lab.\n\n' ...
    'Draw a network, edit every component, and analyse it with power flow, ' ...
    'small-signal (eigenvalues), time-domain simulation, POD design and the ' ...
    'guided scenarios - the same validated engine as the Python edition and ' ...
    'the paper.\n\nSynchronous machines (full + reduced + PSS), grid-forming / ' ...
    'grid-following converters, PV, battery storage and wind types 1-4, with ' ...
    'IEEE 1547 grid support.\n\n' ...
    'Dr. Ismael Khorshed Abdulrahman\nErbil Polytechnic University\n\n' ...
    'Successor to PSDAT [IEEE OAJPE, vol. 7, pp. 59-69, 2020].']), ...
    'BackgroundColor',h.C.panel,'ForegroundColor',[.2 .25 .35], ...
    'HorizontalAlignment','left','FontSize',10);
% --- Data panel: EVERY input parameter, editable in place -----------------
% The complement of Report: Report shows RESULTS (read-only by design);
% Data shows the network's INPUT data -- loads, impedances, set-points,
% device settings -- as tables whose selected row exposes editable fields.
RD = uipanel('Parent',fig,'Units','normalized','Position',[.700 .046 .296 .768], ...
    'BackgroundColor',h.C.panel,'BorderType','line','HighlightColor',[.8 .82 .87],'Visible','off');
h.RD = RD;
uicontrol('Parent',RD,'Style','text','Units','normalized','Position',[.05 .952 .90 .040], ...
    'String','Input data','FontWeight','bold','FontSize',12,'ForegroundColor',h.C.navy, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
uicontrol('Parent',RD,'Style','frame','Units','normalized','Position',[.05 .944 .90 .0022], ...
    'BackgroundColor',h.C.hair,'ForegroundColor',h.C.hair);
uicontrol('Parent',RD,'Style','text','Units','normalized','Position',[.05 .906 .90 .030], ...
    'String','parameters are editable here - Report values are results (read-only)', ...
    'FontSize',8,'FontAngle','italic','ForegroundColor',h.C.grey, ...
    'BackgroundColor',h.C.panel,'HorizontalAlignment','center');
h.ddDat = uicontrol('Parent',RD,'Style','popupmenu','Units','normalized','Position',[.05 .848 .90 .048], ...
    'String',{'Buses (type, V set, load, shunt)','Lines (r, x, b, tap)', ...
              'Generators (Pg, V set, rating)','FACTS devices'}, ...
    'Callback',@onDatCat,'FontSize',9.5,'TooltipString','input-data category');
h.datL = uicontrol('Parent',RD,'Style','listbox','Units','normalized', ...
    'Position',[.05 .316 .90 .524],'FontName','Courier','FontSize',9, ...
    'BackgroundColor','w','String',{''},'Callback',@onDatSel,'Value',1);
h.datLab = cell(1,4); h.datEd = cell(1,4);
for j = 1:4
    y = .256 - .058*(j-1);
    h.datLab{j} = uicontrol('Parent',RD,'Style','text','Units','normalized', ...
        'Position',[.05 y+.004 .40 .036],'String','','FontSize',9, ...
        'HorizontalAlignment','left','BackgroundColor',h.C.panel,'ForegroundColor',h.C.grey);
    h.datEd{j} = uicontrol('Parent',RD,'Style','edit','Units','normalized', ...
        'Position',[.50 y .45 .048],'String','','BackgroundColor','w','FontSize',9.5, ...
        'HorizontalAlignment','center','Visible','off');
end
h.datApply = uicontrol('Parent',RD,'Style','pushbutton','Units','normalized', ...
    'Position',[.05 .022 .43 .050],'String','Apply changes','FontWeight','bold', ...
    'BackgroundColor',h.C.navy,'ForegroundColor','w','Callback',@onDatApply, ...
    'TooltipString','write the edited values into the network (undo-able)');
uicontrol('Parent',RD,'Style','text','Units','normalized','Position',[.52 .028 .43 .040], ...
    'String','select a row above to edit it','FontSize',8,'FontAngle','italic', ...
    'ForegroundColor',h.C.grey,'BackgroundColor',h.C.panel,'HorizontalAlignment','left');

h.status = uicontrol('Parent',fig,'Style','text','Units','normalized', ...
    'Position',[.450 .006 .546 .028],'String','','BackgroundColor',h.C.bg, ...
    'ForegroundColor',h.C.ink,'HorizontalAlignment','right','FontSize',9.5);
% ---- STOP button: floats over the canvas, hidden until a long run (a
% time-domain simulation) begins.  Pressing it sets the cooperative-cancel
% flag that PSDAT_TimeDomain's ode15s OutputFcn polls, so the integration
% halts within a step and returns the partial solution (never a hard kill).
h.bStop = uicontrol('Parent',fig,'Style','pushbutton','Units','normalized', ...
    'Position',[.372 .745 .100 .040],'String',[char(9632) ' Stop'], ...
    'FontWeight','bold','FontSize',10,'BackgroundColor',[.78 .13 .13],'ForegroundColor','w', ...
    'Callback',@onStop,'TooltipString','Stop the running simulation (returns the partial result)','Visible','off');

% ---- hover tooltip (floating info card; mirrors the Python SLD tooltip) --
% a dark, bordered card that follows the cursor and shows the hovered
% component's key properties + live power-flow results.  Created last so it
% always floats on top of the diagram; hidden until the pointer is over a part.
h.tipPanel = uipanel('Parent',fig,'Units','normalized','Position',[0 0 .12 .06], ...
    'BackgroundColor',[.09 .15 .26],'BorderType','line','HighlightColor',[.20 .30 .48], ...
    'Visible','off');
h.tip = uicontrol('Parent',h.tipPanel,'Style','text','Units','normalized', ...
    'Position',[.045 .06 .91 .88],'String','','BackgroundColor',[.09 .15 .26], ...
    'ForegroundColor',[.93 .95 .98],'HorizontalAlignment','left','FontName','Courier','FontSize',10);

% ---- mouse + keyboard handlers -------------------------------------------
set(fig,'WindowButtonDownFcn',@onCanvasDown, ...
        'WindowButtonMotionFcn',@onCanvasMove, ...
        'WindowButtonUpFcn',@onCanvasUp, ...
        'WindowScrollWheelFcn',@onWheel, ...
        'WindowKeyPressFcn',@onKeyPress);
% ---- right-click context menu: the fewer-clicks path to the common actions.
% Opened by onCanvasDown on any right-click over the canvas (which first
% selects the component under the cursor), so every entry acts on exactly
% what the user is pointing at.
h.ctxMenu = uicontextmenu('Parent',fig);
uimenu(h.ctxMenu,'Label','Properties','Callback',@ctxProps);
h.ctxTheory = uimenu(h.ctxMenu,'Label','Model equations...','Callback',@onTheory);
uimenu(h.ctxMenu,'Label','Delete','Callback',@onDelSel);
uimenu(h.ctxMenu,'Label','Zoom to selection','Separator','on','Callback',@onZoomSel);
uimenu(h.ctxMenu,'Label','Fit view','Callback',@onFit);
uimenu(h.ctxMenu,'Label','Run power flow','Separator','on','Callback',@onPF);

% ---- flow-arrow animation timer (MATLAB; Octave has no timer -> static) --
h.ftimer = [];
try
    h.ftimer = timer('Name','psdatFlow','ExecutionMode','fixedRate', ...
        'Period',0.08,'BusyMode','drop','TimerFcn',@(o,e)onFlowTick(fig));
    % 12.5 fps with a proportionally smaller phase step per tick: the arrows
    % glide at the SAME speed as before but with ~50% more frames, so the
    % marching reads fluid; BusyMode drop + the watchdog below keep a slow
    % renderer perfectly safe (frames are skipped, never queued).
catch
    h.ftimer = [];      % no timer available: flow arrows are drawn but static
end
set(fig,'CloseRequestFcn',@onCloseApp);

noTips(fig);                       % control tooltips are OFF app-wide (user
                                   % preference): labels + the status-bar
                                   % hints carry the guidance instead
h.NET = emptyNet();
guidata(fig,h);
try   % one-time pixel-size cache for the hover card (refreshed on Fit + resize)
    uu = get(fig,'Units'); set(fig,'Units','pixels'); fp0 = get(fig,'Position'); set(fig,'Units',uu);
    setappdata(fig,'figpx', fp0(3:4));
catch
end
% keep that cache fresh across window resizes / maximise / DPI moves, so the
% hover card is always sized from the REAL window.  The hook touches ONLY
% appdata -- it can never interact with the normalized auto-layout, so
% resizing stays deterministic (no reflow callbacks, no overlap risk).
try
    set(fig,'SizeChangedFcn',@(s,e) refreshFigPx(s));
catch
    try, set(fig,'ResizeFcn',@(s,e) refreshFigPx(s)); catch, end   % Octave fallback
end
try, updatePalScroll(fig); catch, end      % engage the palette scroll mode
                                           % immediately if the window opened short
setTool(fig,1); setTab('props');
doLoadBench(fig,'IEEE9');
vizMenuBuild(fig);                 % populate the Display-options menu from the live state
labMenuBuild(fig);                 % populate the Labels picker with live checkmarks
setLeftTab(fig, guidata(fig), 'analyze'); % left tabs start on ANALYZE (running
                                          % studies is the common first action;
                                          % BUILD is one click away for editing)
setModule(fig, 'pf');                      % ANALYZE opens on the Power-flow workspace
syncToggles(fig);                          % tint the active Visualize toggles
end

% =========================================================================
%                          DATA MODEL
% =========================================================================
function NET = emptyNet()
NET = struct('name','custom', ...
    'btype',zeros(0,1),'Pd',zeros(0,1),'Qd',zeros(0,1),'Bs',zeros(0,1), ...
    'Vset',zeros(0,1),'bx',zeros(0,1),'by',zeros(0,1), ...
    'g_bus',zeros(0,1),'g_tag',{{}},'g_Pg',zeros(0,1),'g_Vset',zeros(0,1), ...
    'g_S',zeros(0,1),'g_md',{{}},'gx',zeros(0,1),'gy',zeros(0,1), ...
    'br_f',zeros(0,1),'br_t',zeros(0,1),'br_r',zeros(0,1),'br_x',zeros(0,1), ...
    'br_b',zeros(0,1),'br_tap',zeros(0,1),'facts',emptyFacts());
end
% ---- FACTS devices: a STRUCT ARRAY (one struct per device) exactly as
% psdat_netcase reads it.  The field UNION covers shunt (SVC/STATCOM), series
% (TCSC/TSSC/SSSC) and combined (UPFC/IPFC), plus the supplementary POD sub-struct
% and the glyph position (x,y).  Mirrors facts.default_facts / _pod_defaults.
function s = emptyFacts()
s = struct('type',{},'bus',{},'Vref',{},'Bmax',{},'Bmin',{},'Imax',{},'Imin',{}, ...
    'Kr',{},'Tr',{},'Kaw',{},'droop',{},'signal',{},'f',{},'t',{},'kcomp',{}, ...
    'kmin',{},'kmax',{},'Tc',{},'Vsemax',{},'f2',{},'t2',{},'kcomp2',{},'mode',{}, ...
    'Pset',{},'Qset',{},'P1set',{},'Q1set',{},'Q2set',{},'pod',{},'x',{},'y',{});
end
function p = podDefaultApp()
p = struct('on',false,'sig','Vbus','rbus',0,'f',0,'t',0,'i',0,'j',0,'tau',0, ...
    'Tw',10,'T1',0.30,'T2',0.05,'nc',2,'K',0,'lo',-0.10,'hi',0.10, ...
    'ctype','leadlag','Ki',0.5,'Kd',0.05,'Tf',0.02);
end
function fd = factDefault(ty)
% one FACTS device with the full field union (same order as emptyFacts), defaults
% per facts.default_facts.  pod disabled -> the device is purely steady-state.
ty = upper(ty);
kc = 0.4; if strcmp(ty,'UPFC'), kc = 0.3; end
fd = struct('type',ty,'bus',0,'Vref',1.0,'Bmax',2,'Bmin',-2,'Imax',2,'Imin',-2, ...
    'Kr',20,'Tr',0.05,'Kaw',150,'droop',0,'signal','V','f',0,'t',0,'kcomp',kc, ...
    'kmin',-0.2,'kmax',0.7,'Tc',0.05,'Vsemax',0.20,'f2',0,'t2',0,'kcomp2',0.2, ...
    'mode','comp','Pset',[],'Qset',[],'P1set',[],'Q1set',[],'Q2set',[], ...
    'pod',podDefaultApp(),'x',0,'y',0);
end
function m = nfac(NET), if isfield(NET,'facts'), m = numel(NET.facts); else, m = 0; end, end
function NET = addFactShunt(NET, ty, ibus)
fd = factDefault(ty); fd.bus = ibus; fd.Vref = NET.Vset(ibus);
sp = netspan(NET); fd.x = NET.bx(ibus); fd.y = NET.by(ibus) + 0.10*sp;
NET.facts(end+1) = fd;
end
function NET = addFactSeries(NET, ty, kbr)
fd = factDefault(ty); fd.f = NET.br_f(kbr); fd.t = NET.br_t(kbr);
fd.x = 0.5*(NET.bx(fd.f)+NET.bx(fd.t)); fd.y = 0.5*(NET.by(fd.f)+NET.by(fd.t));
NET.facts(end+1) = fd;
end
function NET = addFactCombined(NET, ty, kbr)
fd = factDefault(ty); f = NET.br_f(kbr); t = NET.br_t(kbr); fd.f = f; fd.t = t;
if strcmp(upper(ty),'UPFC')
    fd.bus = f; fd.Vref = NET.Vset(f);
    sp = netspan(NET); fd.x = NET.bx(f); fd.y = NET.by(f) + 0.10*sp;
else
    fd.x = 0.5*(NET.bx(f)+NET.bx(t)); fd.y = 0.5*(NET.by(f)+NET.by(t));
end
NET.facts(end+1) = fd;
end
function NET = delFact(NET, k)
keep = true(1,nfac(NET)); keep(k) = false; NET.facts = NET.facts(keep);
end
function NET = refacts(NET, buses)
% Re-anchor FACTS glyphs to the network geometry: shunt devices to their bus,
% series devices to their line midpoint, exactly the insertion-time formulas.
% Called whenever bus coordinates change (drag, align/distribute, rotate/flip,
% auto-arrange, layouts) so a device NEVER stays behind, floating disconnected
% from a diagram that moved on without it.  buses = [] re-anchors every
% device; a bus list re-anchors only devices attached to those buses (drags).
if nfac(NET) == 0, return; end
nb = nbus(NET); sp = netspan(NET);
for k = 1:nfac(NET)
    d = NET.facts(k); ty = upper(d.type);
    if isShuntFac(ty) || strcmp(ty,'UPFC')
        b = round(d.bus);
        if strcmp(ty,'UPFC') && (b < 1 || b > nb), b = round(d.f); end
        if b < 1 || b > nb, continue; end
        anch = b;
        if strcmp(ty,'UPFC'), anch = [b round(d.f) round(d.t)]; end
        if ~isempty(buses) && ~any(ismember(anch, buses)), continue; end
        d.x = NET.bx(b); d.y = NET.by(b) + 0.10*sp;
    else                                            % series / IPFC: line-1 midpoint
        f = round(d.f); t = round(d.t);
        if f < 1 || f > nb || t < 1 || t > nb, continue; end
        anch = [f t];
        if strcmp(ty,'IPFC'), anch = [anch round(d.f2) round(d.t2)]; end
        if ~isempty(buses) && ~any(ismember(anch, buses)), continue; end
        d.x = 0.5*(NET.bx(f)+NET.bx(t)); d.y = 0.5*(NET.by(f)+NET.by(t));
    end
    NET.facts(k) = d;
end
end
function tf = isSeriesFac(ty), tf = any(strcmp(upper(ty),{'TCSC','TSSC','SSSC'})); end
function tf = isShuntFac(ty), tf = any(strcmp(upper(ty),{'SVC','STATCOM'})); end
function tf = isCombFac(ty),  tf = any(strcmp(upper(ty),{'UPFC','IPFC'})); end
function NET = removeFactsOnLine(NET, f, t)
% drop series/UPFC on line f-t; clear an IPFC's second line if it was f-t
if nfac(NET)==0, return; end
same = @(a,b) (a==f && b==t) || (a==t && b==f);
keep = true(1,nfac(NET));
for k = 1:nfac(NET)
    d = NET.facts(k); ty = upper(d.type);
    if isSeriesFac(ty) || strcmp(ty,'UPFC')
        if same(d.f,d.t), keep(k) = false; end
    elseif strcmp(ty,'IPFC')
        if same(d.f,d.t), keep(k) = false;
        elseif ~isempty(d.f2) && d.f2>0 && same(d.f2,d.t2), NET.facts(k).f2 = 0; NET.facts(k).t2 = 0; end
    end
end
NET.facts = NET.facts(keep);
end
function NET = renumFacts(NET, i)
% after deleting bus i: drop devices that reference it, decrement refs > i
if nfac(NET)==0, return; end
keep = true(1,nfac(NET));
for k = 1:nfac(NET)
    d = NET.facts(k); ty = upper(d.type);
    if isShuntFac(ty)
        if d.bus==i, keep(k) = false; end
    elseif isSeriesFac(ty)
        if d.f==i || d.t==i, keep(k) = false; end
    elseif strcmp(ty,'UPFC')
        if d.bus==i || d.f==i || d.t==i, keep(k) = false; end
    else                                                  % IPFC
        if d.f==i || d.t==i, keep(k) = false;
        elseif (~isempty(d.f2)&&d.f2==i) || (~isempty(d.t2)&&d.t2==i), NET.facts(k).f2=0; NET.facts(k).t2=0; end
    end
end
NET.facts = NET.facts(keep);
dec = @(v) v - double(~isempty(v) && v>i);
for k = 1:nfac(NET)
    NET.facts(k).bus = dec(NET.facts(k).bus);
    NET.facts(k).f   = dec(NET.facts(k).f);
    NET.facts(k).t   = dec(NET.facts(k).t);
    NET.facts(k).f2  = dec(NET.facts(k).f2);
    NET.facts(k).t2  = dec(NET.facts(k).t2);
end
end
function n = nbus(NET),  n = numel(NET.btype); end
function m = ngen(NET),  m = numel(NET.g_bus); end
function b = nbr(NET),   b = numel(NET.br_f);  end

function h = pushUndo(h)
h.ED.undo{end+1} = h.NET;
if numel(h.ED.undo) > 80, h.ED.undo(1) = []; end
h.ED.redo = {}; h.ED.pf = [];
h = bumprev(h);
end
function h = markrun(fig, h, key)
% record the network revision this analysis is running on (drives the
% "edited since last run" hints in setModule)
if ~isfield(h.ED,'netrev'), h.ED.netrev = 0; end
h.ED.lastrun.(key) = h.ED.netrev;
guidata(fig, h);
end
function h = bumprev(h)
% network REVISION counter: every mutation bumps it; each analysis records
% the revision it ran on, so the app can say -- honestly and automatically --
% when a module's last results predate the current network.  (Every Run
% callback rebuilds from the drawn network anyway; this only powers the
% "edited since last run" hints.)
if ~isfield(h.ED,'netrev'), h.ED.netrev = 0; end
h.ED.netrev = h.ED.netrev + 1;
end

function NET = addBus(NET, x, y)
NET.btype(end+1,1) = 1; NET.Pd(end+1,1) = 0; NET.Qd(end+1,1) = 0;
NET.Bs(end+1,1) = 0;    NET.Vset(end+1,1) = 1.0;
NET.bx(end+1,1) = x;    NET.by(end+1,1) = y;
end
function NET = addGen(NET, ibus)
NET.g_bus(end+1,1) = ibus; NET.g_tag{end+1} = 'SG';
NET.g_Pg(end+1,1) = 50;    NET.g_Vset(end+1,1) = NET.Vset(ibus);
NET.g_S(end+1,1) = 100;    NET.g_md{end+1} = [];
sp = netspan(NET);
NET.gx(end+1,1) = NET.bx(ibus); NET.gy(end+1,1) = NET.by(ibus) - 0.10*sp;
if sum(NET.btype==3) == 0, NET.btype(ibus) = 3;
elseif NET.btype(ibus) == 1, NET.btype(ibus) = 2; end
end
function NET = addBranch(NET, f, t, isX)
NET.br_f(end+1,1) = f; NET.br_t(end+1,1) = t;
NET.br_r(end+1,1) = 0.01; NET.br_x(end+1,1) = 0.10; NET.br_b(end+1,1) = 0.0;
if isX, NET.br_tap(end+1,1) = 1.0; else, NET.br_tap(end+1,1) = 0.0; end
end
function s = netspan(NET)
if nbus(NET) == 0, s = 1000; return; end
s = max([max(NET.bx)-min(NET.bx), max(NET.by)-min(NET.by), 200]);
end
function NET = delBus(NET, i)
kB = true(nbus(NET),1); kB(i) = false;
NET.btype = NET.btype(kB); NET.Pd = NET.Pd(kB); NET.Qd = NET.Qd(kB);
NET.Bs = NET.Bs(kB); NET.Vset = NET.Vset(kB); NET.bx = NET.bx(kB); NET.by = NET.by(kB);
kb = (NET.br_f ~= i) & (NET.br_t ~= i);
NET.br_f = renum(NET.br_f(kb), i); NET.br_t = renum(NET.br_t(kb), i);
NET.br_r = NET.br_r(kb); NET.br_x = NET.br_x(kb);
NET.br_b = NET.br_b(kb); NET.br_tap = NET.br_tap(kb);
kg = NET.g_bus ~= i; NET = filterGens(NET, kg); NET.g_bus = renum(NET.g_bus, i);
NET = renumFacts(NET, i);
end
function v = renum(v, i), v(v > i) = v(v > i) - 1; end
function NET = filterGens(NET, keep)
NET.g_bus = NET.g_bus(keep); NET.g_Pg = NET.g_Pg(keep);
NET.g_Vset = NET.g_Vset(keep); NET.g_S = NET.g_S(keep);
NET.gx = NET.gx(keep); NET.gy = NET.gy(keep);
NET.g_tag = NET.g_tag(keep); NET.g_md = NET.g_md(keep);
end
function NET = delGen(NET, k)
keep = true(ngen(NET),1); keep(k) = false; NET = filterGens(NET, keep);
end
function NET = delBranch(NET, k)
f = NET.br_f(k); t = NET.br_t(k);
keep = true(nbr(NET),1); keep(k) = false;
NET.br_f = NET.br_f(keep); NET.br_t = NET.br_t(keep);
NET.br_r = NET.br_r(keep); NET.br_x = NET.br_x(keep);
NET.br_b = NET.br_b(keep); NET.br_tap = NET.br_tap(keep);
NET = removeFactsOnLine(NET, f, t);
end

% =========================================================================
%                          TABS / TOOLS / TOGGLES
% =========================================================================
function setTab(name, fig)
% optional 2nd arg: the app figure (REQUIRED from timer/deferred contexts,
% where gcbf is empty and gcf may be a result window, not the app)
if nargin < 2 || isempty(fig) || ~ishghandle(fig)
    fig = gcbf; if isempty(fig), fig = gcf; end
end
h = guidata(fig);
if ~isstruct(h) || ~isfield(h,'ED'), return; end   % not the app figure: ignore
h.ED.rptab = name; guidata(fig,h);
names = {'props','data','report','about'};
pans  = {'RP','RD','RR','RA'};  tabs = {'tabP','tabD','tabR','tabA'};
hi = h.C.tglon; lo = [1 1 1];
for q = 1:4
    onq = strcmp(name, names{q});
    if isfield(h,pans{q}) && ishghandle(h.(pans{q})), set(h.(pans{q}),'Visible',tern(onq,'on','off')); end
    if isfield(h,tabs{q}) && ishghandle(h.(tabs{q}))
        set(h.(tabs{q}),'BackgroundColor',tern(onq,hi,lo),'ForegroundColor',tern(onq,h.C.navy,h.C.ink), ...
            'FontWeight',tern(onq,'bold','normal'));
    end
end
if strcmp(name,'data'), datBuild(fig); end        % tables always reflect the live network
end
function v = tern(c,a,b), if c, v = a; else, v = b; end, end

function onTool(src,~), if busyBlock(gcbf), return; end, setTool(gcbf, get(src,'UserData')); end
function setTool(fig, k)
h = guidata(fig); h.ED.tool = h.TOOLS{k}; h.ED.lineFrom = 0;
for j = 1:numel(h.toolBtn)
    if j == k
        set(h.toolBtn{j},'BackgroundColor',h.C.tglon,'ForegroundColor',h.C.navy,'FontWeight','bold');
    else
        fgj = h.C.ink; if j == 8, fgj = [.55 .10 .10]; end   % Delete keeps its destructive red
        set(h.toolBtn{j},'BackgroundColor',h.C.light,'ForegroundColor',fgj,'FontWeight','normal');
    end
end
H = struct('select','Select / Move: click to edit; drag a bus/generator; drag empty space to box-select.', ...
   'bus','Add Bus: click the canvas to place a busbar.', ...
   'line','Add Line: click the FROM busbar, then the TO busbar.', ...
   'xfmr','Add Transformer: click FROM then TO busbar (tap = 1.0, editable).', ...
   'gen','Add Generator: click the busbar it connects to.', ...
   'load','Add Load: click a busbar (edit P/Q on the right).', ...
   'shunt','Add Shunt: click a busbar (edit B on the right).', ...
   'delete','Delete: click a component to remove it.', ...
   'svc','SVC: click a busbar - a shunt compensator that holds its bus voltage (Q = B|V|^2).', ...
   'statcom','STATCOM: click a busbar - a VSC reactive source that holds its bus voltage (Q = |V|I).', ...
   'tcsc','TCSC: click a LINE - continuously-variable series compensation (lowers X, boosts transfer).', ...
   'tssc','TSSC: click a LINE - step-switched series compensation.', ...
   'sssc','SSSC: click a LINE - a VSC injecting a controllable series voltage.', ...
   'upfc','UPFC: click a LINE - shunt (holds V) + series (controls flow), DC-coupled.', ...
   'ipfc','IPFC: click a LINE - two DC-coupled series converters (set line 2 in Properties).');
set(h.hint,'String',H.(h.TOOLS{k}));
guidata(fig,h); redraw(fig);
end
function onModule(src,~)
% Switch the ANALYZE workspace -- RESET FIRST, THEN GO, guaranteed:
%   1. the switch itself is visibility-only and always safe, so it is
%      NEVER blocked;
%   2. if an analysis is still running, the click signals the cooperative
%      STOP (the run halts at its next poll and keeps its partial result)
%      and stamps the stop time;
%   3. the moment the old run unwinds, the interface is idle and the new
%      workspace's Run button works.  If the old run ever fails to unwind
%      (a wedged latch -- the old "switching modules jams the app" bug),
%      the stamped stop time lets busyBlock FREE the latch by itself on
%      your next click, so no switch sequence can strand the interface.
global PSDAT_STOP %#ok<GVMIS>
fig = gcbf; h = guidata(fig);
setappdata(fig,'pendingRun','');             % switching cancels any queued run
if isBusy(fig)
    PSDAT_STOP = true;
    setappdata(fig,'stopReqT', now*86400);   %#ok<TNOW1> % arms the auto-heal
    if isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','stopping the previous analysis (partial result kept) - the new workspace is ready, press Run');
    end
end
setModule(fig, get(src,'UserData'));
end
function setModule(fig, key)
% show ONE analysis workspace; every module operates on the same network
% model, but its controls live in a dedicated panel -- nothing ever mixes.
h = guidata(fig); h.ED.amod = key; guidata(fig,h);
pans = {'MPF','MSS','MTD','MDS','MSC'};
for q = 1:numel(h.AMODS)
    onq = strcmp(key, h.AMODS{q});
    if isfield(h,pans{q}) && ishghandle(h.(pans{q}))
        set(h.(pans{q}),'Visible',tern(onq,'on','off'));
    end
    if isfield(h,'amodBtn') && ishghandle(h.amodBtn{q})
        set(h.amodBtn{q},'BackgroundColor',tern(onq,h.C.tglon,[1 1 1]), ...
            'ForegroundColor',tern(onq,h.C.navy,h.C.ink),'FontWeight',tern(onq,'bold','normal'));
    end
end
% honest freshness hint: every Run always rebuilds from the drawn network,
% so results can never be computed on a stale model -- but if this module's
% LAST results predate the current network, say so the moment it opens.
try
    if any(strcmp(key,{'pf','ss','td','ds'})) && isfield(h.ED,'lastrun') && ...
            isfield(h.ED.lastrun,key) && isfield(h.ED,'netrev') && h.ED.lastrun.(key) ~= h.ED.netrev
        nm = struct('pf','power flow','ss','small-signal','td','time domain','ds','design');
        set(h.status,'String',['network edited since the last ' nm.(key) ...
            ' run - press Run to analyze the current model']);
    end
catch
end
end
function onLeftTab(src,~)
% visibility-only: never blocked (a swallowed tab click reads as a jam)
fig = gcbf; h = guidata(fig); which = get(src,'UserData');
setLeftTab(fig, h, which);
end
function setLeftTab(fig, h, which)
onB = strcmp(which,'build');
set(h.PA,'Visible',tern(onB,'on','off'));
set(h.PB,'Visible',tern(onB,'off','on'));
on  = {h.C.tglon, h.C.navy};   off = {[1 1 1], h.C.ink};
cb = tern(onB,on,off); ca = tern(onB,off,on);
set(h.tabBuild,  'BackgroundColor',cb{1},'ForegroundColor',cb{2},'FontWeight',tern(onB,'bold','normal'));
set(h.tabAnalyze,'BackgroundColor',ca{1},'ForegroundColor',ca{2},'FontWeight',tern(onB,'normal','bold'));
guidata(fig,h);
end
function onArrangeMenu(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% one menu for every selection utility: align / distribute / rotate / flip.
fig = gcbf; v = get(src,'Value'); set(src,'Value',1);
if v <= 1 || isempty(fig), return; end
modes = {'l','cx','r','t','cy','dist','rot','fliph','flipv'};
m = modes{v-1};
set(src,'UserData',m);
if any(strcmp(m,{'rot','fliph','flipv'})), onTransform(src,[]);
else, onAlign(src,[]); end
set(src,'UserData',[]);
end
function vizMenuBuild(fig)
% (re)build the Display-options menu with live checkmarks + current cycles
h = guidata(fig); if isempty(h) || ~isfield(h,'ddViz'), return; end
mk = '* '; try, mk = [char(10003) ' ']; catch, end   % checkmark, ASCII fallback
ck = @(b) tern(b,mk,'    ');
al = [.3 .5 .7 .9]; ai = find(abs(al-h.ED.falpha)<1e-9,1); if isempty(ai), ai = 2; end
ar = [0.7 1.0 1.45]; ri = find(abs(ar-h.ED.arrowscale)<1e-9,1); if isempty(ri), ri = 2; end
aln = {'30%','50%','70%','90%'}; arn = {'small','medium','large'};
set(h.ddViz,'String',{ 'Display options...', ...
    [ck(isfield(h.ED,'grid')&&h.ED.grid) 'Background grid'], ...
    [ck(isfield(h.ED,'flegend')&&h.ED.flegend) 'Heat colour-bar legend'], ...
    ['Heat transparency: ' aln{ai} '  (cycle)'], ...
    ['Arrow size: ' arn{ri} '  (cycle)'], ...
    'Zoom to selection'},'Value',1);
end
function onVizMenu(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% Display-options dispatcher: grid / legend card / heat alpha / arrow size
fig = gcbf; h = guidata(fig); v = get(src,'Value'); set(src,'Value',1);
if v <= 1, return; end
if v == 2
    h.ED.grid = ~(isfield(h.ED,'grid') && h.ED.grid);
elseif v == 3
    h.ED.flegend = ~(isfield(h.ED,'flegend') && h.ED.flegend);
elseif v == 4
    al = [.3 .5 .7 .9]; ai = find(abs(al-h.ED.falpha)<1e-9,1); if isempty(ai), ai = 1; end
    h.ED.falpha = al(mod(ai,4)+1);
elseif v == 6
    zoomToSel(fig); return;
else
    ar = [0.7 1.0 1.45]; ri = find(abs(ar-h.ED.arrowscale)<1e-9,1); if isempty(ri), ri = 1; end
    h.ED.arrowscale = ar(mod(ri,3)+1);
end
guidata(fig,h); vizMenuBuild(fig); redraw(fig);
end
function labMenuBuild(fig)
% the LABELS picker: every label class with a live checkmark, plus all/none.
% The ribbon "Labels" toggle is the master switch; this list decides WHICH
% label types appear when it is on.
h = guidata(fig); if isempty(h) || ~isfield(h,'ddLab'), return; end
s = h.ED.show;
mk = '* '; try, mk = [char(10003) ' ']; catch, end
ck = @(b) tern(b,mk,'    ');
fl = ~isfield(s,'factlab') || s.factlab;
set(h.ddLab,'String',{ 'Labels...', ...
    [ck(s.busno)   'Bus numbers'],      [ck(s.type)   'Bus types'], ...
    [ck(s.volt)    'Bus voltages (pu, angle)'],[ck(s.genlab) 'Generator labels'], ...
    [ck(s.loadlab) 'Load values'],      [ck(s.lineno) 'Line numbers'], ...
    [ck(s.flowlab) 'Line flows (MW)'],  [ck(fl)       'FACTS device names'], ...
    'Show all','Hide all'},'Value',1);
end
function onLabMenu(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); v = get(src,'Value'); set(src,'Value',1);
if v <= 1, return; end
tags = {'busno','type','volt','genlab','loadlab','lineno','flowlab','factlab'};
if v-1 <= numel(tags)
    tg = tags{v-1};
    cur = ~isfield(h.ED.show,tg) || h.ED.show.(tg);
    h.ED.show.(tg) = ~cur;
elseif v-1 == numel(tags)+1                     % Show all (+ master on)
    for q = 1:numel(tags), h.ED.show.(tags{q}) = true; end
    h.ED.labels = true;
    if isfield(h,'cLabels') && ishghandle(h.cLabels), set(h.cLabels,'Value',1); end
else                                            % Hide all label classes
    for q = 1:numel(tags), h.ED.show.(tags{q}) = false; end
end
guidata(fig,h); syncToggles(fig); labMenuBuild(fig); redraw(fig);
end
function onToggle(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); tag = get(src,'UserData'); v = get(src,'Value');
if any(strcmp(tag,{'snap','flow','heat','labels','alerts'})), h.ED.(tag) = logical(v);
else, h.ED.show.(tag) = logical(v); end
if strcmp(tag,'labels') && v
    % turning Labels ON must always be able to show something: if every
    % class was off (a stale "Hide all"), restore the default classes.
    fn = {'busno','type','volt','genlab','loadlab','lineno','flowlab','factlab'};
    anyon = false;
    for q = 1:numel(fn)
        anyon = anyon || (isfield(h.ED.show,fn{q}) && h.ED.show.(fn{q}));
    end
    if ~anyon
        h.ED.show.busno = true; h.ED.show.volt = true; h.ED.show.type = true;
        h.ED.show.genlab = true; h.ED.show.loadlab = true; h.ED.show.factlab = true;
    end
end
guidata(fig,h); syncToggles(fig); labMenuBuild(fig); redraw(fig);
if strcmp(tag,'flow'), syncFlowTimer(fig); end
end
function syncToggles(fig)
% an ACTIVE toggle wears a navy-tinted face — the state reads at a glance
h = guidata(fig); if isempty(h), return; end
tg = {'cLabels','cFlow','cHeat','cAlert','cSnap'};
for q = 1:numel(tg)
    if isfield(h,tg{q}) && ishghandle(h.(tg{q}))
        on = get(h.(tg{q}),'Value') > 0;
        set(h.(tg{q}),'BackgroundColor',tern(on,h.C.tglon,[1 1 1]), ...
                      'FontWeight',tern(on,'bold','normal'));
    end
end
end
function onField(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); keys = {'vmag','vang','load','loss','q'};
h.ED.field = keys{get(src,'Value')}; if ~h.ED.heat, h.ED.heat = true; set(h.cHeat,'Value',1); end
guidata(fig,h); redraw(fig);
end
function onMode(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% Simplified (1) = clean, essential labels only; Detailed (2) = full readouts.
fig = gcbf; h = guidata(fig); h.ED.detail = (get(src,'Value') == 2);
guidata(fig,h); redraw(fig);
set(h.status,'String',tern(h.ED.detail,'detailed view','simplified view'));
end
function [tf, px, py] = inCanvas(fig, h)
u = get(fig,'Units'); set(fig,'Units','normalized');
cp = get(fig,'CurrentPoint'); set(fig,'Units',u);
p = get(h.ax,'Position');
tf = cp(1) >= p(1) && cp(1) <= p(1)+p(3) && cp(2) >= p(2) && cp(2) <= p(2)+p(4);
q = get(h.ax,'CurrentPoint'); px = q(1,1); py = q(1,2);
end

function onCanvasDown(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
[tf,px,py] = inCanvas(fig,h); if ~tf, return; end
if strcmp(get(fig,'SelectionType'),'alt')
    % RIGHT-CLICK: select whatever is under the cursor, then open the
    % context menu -- never a draw/delete action, whatever tool is active
    % (the professional editor contract: right-click is always safe).
    [kind,idx] = hitTest(h,px,py);
    if ~strcmp(kind,'none')
        h.ED.selkind = kind; h.ED.selidx = idx;
        h.ED.selset = tern(strcmp(kind,'bus'), idx, []);
        guidata(fig,h); syncListSel(fig); syncReportSel(fig); showProps(fig); redraw(fig);
    end
    showCtxMenu(fig, kind);
    return;
end
if h.ED.snap, px = snapv(px,h.ED.gridsz); py = snapv(py,h.ED.gridsz); end
if isfield(h.ED,'zoomarm') && h.ED.zoomarm      % armed area-zoom: next press
    h.ED.zoomrect = true; h.ED.zoomstart = [px py];   % starts the rubber band,
    guidata(fig,h); return;                           % whatever tool is active
end
switch h.ED.tool
case 'select'
    [kind,idx] = hitTest(h,px,py);
    if strcmp(kind,'none')
        h.ED.boxsel = true; h.ED.boxstart = [px py];
        h.ED.selkind = 'none'; h.ED.selidx = 0; h.ED.selset = [];
        guidata(fig,h); showProps(fig); return;
    end
    h.ED.selkind = kind; h.ED.selidx = idx;
    if strcmp(kind,'bus'), h.ED.selset = idx; else, h.ED.selset = []; end
    if any(strcmp(kind,{'bus','gen'})), h.ED.drag = true; h.ED.dragPrev = [px py]; end
    guidata(fig,h); syncListSel(fig); syncReportSel(fig); showProps(fig);
    setTab('props', fig);              % clicking a component surfaces its editable
    redraw(fig);                       % parameters immediately (results stay one tab away)
    if strcmp(get(fig,'SelectionType'),'open')   % double-click a component -> its data
        h = guidata(fig); h.ED.drag = false; guidata(fig,h); setTab('props');
    end
case 'bus'
    h = pushUndo(h); h.NET = addBus(h.NET,px,py);
    h.ED.selkind = 'bus'; h.ED.selidx = nbus(h.NET); h.ED.selset = nbus(h.NET);
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    autoPF(fig, sprintf('bus %d added',nbus(h.NET)));
case {'line','xfmr'}
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'bus'), return; end
    if h.ED.lineFrom == 0 || h.ED.lineFrom > nbus(h.NET)   % 0 = none; stale (> bus count after a smaller system loaded) -> restart cleanly
        h.ED.lineFrom = idx; set(h.status,'String',sprintf('from bus %d...',idx));
        guidata(fig,h); redraw(fig);
    else
        if idx ~= h.ED.lineFrom
            h = pushUndo(h);
            h.NET = addBranch(h.NET,h.ED.lineFrom,idx,strcmp(h.ED.tool,'xfmr'));
            h.ED.selkind = 'branch'; h.ED.selidx = nbr(h.NET);
        end
        h.ED.lineFrom = 0; guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
        if strcmp(h.ED.selkind,'branch')
            autoPF(fig, sprintf('line %d-%d added',h.NET.br_f(end),h.NET.br_t(end)));
        end
    end
case 'gen'
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'bus'), return; end
    h = pushUndo(h); h.NET = addGen(h.NET,idx);
    h.ED.selkind = 'gen'; h.ED.selidx = ngen(h.NET); h.ED.selset = [];
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    autoPF(fig, sprintf('generator added at bus %d',idx));
case 'load'
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'bus'), return; end
    h = pushUndo(h);
    if h.NET.Pd(idx)==0 && h.NET.Qd(idx)==0, h.NET.Pd(idx)=100; h.NET.Qd(idx)=40; end
    h.ED.selkind = 'bus'; h.ED.selidx = idx; h.ED.selset = idx;
    guidata(fig,h); showProps(fig); redraw(fig);
    autoPF(fig, sprintf('load %.0f+j%.0f MVA at bus %d',h.NET.Pd(idx),h.NET.Qd(idx),idx));
case 'shunt'
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'bus'), return; end
    h = pushUndo(h); if h.NET.Bs(idx)==0, h.NET.Bs(idx)=50; end
    h.ED.selkind = 'bus'; h.ED.selidx = idx; h.ED.selset = idx;
    guidata(fig,h); showProps(fig); redraw(fig);
    autoPF(fig, sprintf('%+.0f MVAr shunt at bus %d',h.NET.Bs(idx),idx));
case {'svc','statcom'}                                % shunt FACTS: click a bus
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'bus'), return; end
    ty = upper(h.ED.tool); h = pushUndo(h); h.NET = addFactShunt(h.NET,ty,idx);
    h.ED.selkind = 'facts'; h.ED.selidx = nfac(h.NET); h.ED.selset = [];
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    factsImpact(fig, sprintf('%s added at bus %d',ty,idx));
case {'tcsc','tssc','sssc'}                            % series FACTS: click a line
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'branch'), set(h.status,'String','click a LINE to place the series FACTS device'); return; end
    ty = upper(h.ED.tool); h = pushUndo(h); h.NET = addFactSeries(h.NET,ty,idx);
    h.ED.selkind = 'facts'; h.ED.selidx = nfac(h.NET); h.ED.selset = [];
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    factsImpact(fig, sprintf('%s added on line %d-%d',ty,h.NET.br_f(idx),h.NET.br_t(idx)));
case {'upfc','ipfc'}                                   % combined FACTS: click a line
    [kind,idx] = hitTest(h,px,py); if ~strcmp(kind,'branch'), set(h.status,'String','click a LINE to place the combined FACTS device'); return; end
    ty = upper(h.ED.tool); h = pushUndo(h); h.NET = addFactCombined(h.NET,ty,idx);
    h.ED.selkind = 'facts'; h.ED.selidx = nfac(h.NET); h.ED.selset = [];
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    factsImpact(fig, sprintf('%s added on line %d-%d',ty,h.NET.br_f(idx),h.NET.br_t(idx)));
case 'delete'
    [kind,idx] = hitTest(h,px,py);
    if strcmp(kind,'none'), return; end
    h = pushUndo(h); h = deleteElement(h,kind,idx);
    guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
    autoPF(fig, [kind ' deleted']);
end
end

function onCanvasMove(src,~)
fig = gcbf; if isempty(fig), return; end
if isBusy(fig), return; end                    % motion is inert while a run is active
h = guidata(fig); if isempty(h), return; end

if h.ED.drag
    hideTip(h);
    q = get(h.ax,'CurrentPoint'); px = q(1,1); py = q(1,2);
    if h.ED.snap, px = snapv(px,h.ED.gridsz); py = snapv(py,h.ED.gridsz); end
    dx = px - h.ED.dragPrev(1); dy = py - h.ED.dragPrev(2); h.ED.dragPrev = [px py];
    if strcmp(h.ED.selkind,'bus')
        i = h.ED.selidx; h.NET.bx(i) = h.NET.bx(i)+dx; h.NET.by(i) = h.NET.by(i)+dy;
        g = find(h.NET.g_bus == i);
        for gg = g(:)', h.NET.gx(gg)=h.NET.gx(gg)+dx; h.NET.gy(gg)=h.NET.gy(gg)+dy; end
        h.NET = refacts(h.NET, i);              % attached FACTS ride along live
    elseif strcmp(h.ED.selkind,'gen')
        k = h.ED.selidx; h.NET.gx(k) = h.NET.gx(k)+dx; h.NET.gy(k) = h.NET.gy(k)+dy;
    end
    guidata(fig,h); redraw(fig); return;
end
if isfield(h.ED,'zoomrect') && h.ED.zoomrect, hideTip(h); redraw(fig); return; end
if h.ED.boxsel, hideTip(h); redraw(fig); return; end
if any(strcmp(h.ED.tool,{'line','xfmr'})) && h.ED.lineFrom > 0, hideTip(h); redraw(fig); return; end
% ---- hover: show the info card for whatever component sits under the cursor
[tf,px,py] = inCanvas(fig,h);
if tf
    [kind,idx] = hitTest(h,px,py);
    if strcmp(kind,'none'), hideTip(h); else, showTip(fig,h,kind,idx); end
else
    hideTip(h);
end
end

function onCanvasUp(src,~)
if isBusy(gcbf), return; end
fig = gcbf; if isempty(fig), return; end
h = guidata(fig); if isempty(h), return; end
if h.ED.drag, h.ED.drag = false; guidata(fig,h); return; end
if isfield(h.ED,'zoomrect') && h.ED.zoomrect
    q = get(h.ax,'CurrentPoint'); px = q(1,1); py = q(1,2);
    x0 = h.ED.zoomstart(1); y0 = h.ED.zoomstart(2);
    h.ED.zoomrect = false; h.ED.zoomarm = false;
    xl = h.ED.xlim; yl = h.ED.ylim;
    w = abs(px-x0); ht = abs(py-y0);
    if w < 0.01*diff(xl) || ht < 0.01*diff(yl)
        f = 1/1.6;                              % a plain click: step in at that point
        h.ED.xlim = px + (xl - px)*f; h.ED.ylim = py + (yl - py)*f;
    else
        cx = (x0+px)/2; cy = (y0+py)/2;         % fit the rectangle, preserving the
        a0 = diff(xl)/max(diff(yl),1e-9);       % on-screen aspect so nothing distorts
        if w/max(ht,1e-9) > a0, ht = w/a0; else, w = ht*a0; end
        w = w*1.04; ht = ht*1.04;
        h.ED.xlim = [cx-w/2 cx+w/2]; h.ED.ylim = [cy-ht/2 cy+ht/2];
    end
    guidata(fig,h);
    if isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','zoomed - Fit restores the full view');
    end
    redraw(fig); return;
end
if h.ED.boxsel
    q = get(h.ax,'CurrentPoint'); px = q(1,1); py = q(1,2);
    x0 = h.ED.boxstart(1); y0 = h.ED.boxstart(2);
    lo = [min(x0,px) min(y0,py)]; hi = [max(x0,px) max(y0,py)];
    sel = find(h.NET.bx >= lo(1) & h.NET.bx <= hi(1) & h.NET.by >= lo(2) & h.NET.by <= hi(2));
    h.ED.selset = sel(:).'; h.ED.boxsel = false;
    if numel(sel) == 1, h.ED.selkind = 'bus'; h.ED.selidx = sel(1); end
    guidata(fig,h); showProps(fig); redraw(fig);
end
end

function h = deleteElement(h,kind,idx)
switch kind
case 'bus',    h.NET = delBus(h.NET,idx);
case 'gen',    h.NET = delGen(h.NET,idx);
case 'branch', h.NET = delBranch(h.NET,idx);
case 'facts',  h.NET = delFact(h.NET,idx);
otherwise, return;
end
h.ED.selkind = 'none'; h.ED.selidx = 0; h.ED.selset = []; h.ED.pf = [];
end

function v = snapv(v,g), v = round(v/g)*g; end

% =========================================================================
%                 HOVER TOOLTIP  (mirrors the Python SLD tooltip)
% =========================================================================
function showTip(fig, h, kind, idx)
% build the info card for the hovered component and place it beside the cursor
L = tipLines(h, kind, idx);
if isempty(L), hideTip(h); return; end
% pointer position in normalised figure coords + figure size in pixels
u = get(fig,'Units');
if ~strcmp(u,'normalized'), set(fig,'Units','normalized'); end
cp = get(fig,'CurrentPoint');
if ~strcmp(u,'normalized'), set(fig,'Units',u); end
% figure pixel size from the STARTUP/Fit cache -- measuring it live here
% would toggle figure Units on every hover move (hot path)
fp = getappdata(fig,'figpx');
if isempty(fp) || numel(fp) < 2 || any(~isfinite(fp)) || fp(1) <= 1, fp = [1280 800]; end
figW = max(fp(1),1); figH = max(fp(2),1);
% card size estimated from the (monospaced) text block
nL = numel(L); maxc = 1;
for r = 1:nL, maxc = max(maxc, numel(L{r})); end
wpx = maxc*8.3 + 28; hpx = nL*17.5 + 16;              % Courier-10 metrics + padding (matches h.tip's font, so the card never clips its text)
bw = min(wpx/figW, 0.9); bh = min(hpx/figH, 0.9);
ox = 16/figW; oy = 18/figH;
x = cp(1) + ox; y = cp(2) - bh - oy;                  % below-right of the pointer
if x + bw > 0.998, x = cp(1) - bw - ox; end           % flip if it would clip an edge
if y < 0.002,      y = cp(2) + oy; end
x = max(0.002, min(x, 1-bw-0.002));
y = max(0.002, min(y, 1-bh-0.002));
set(h.tip,'String',L);
set(h.tipPanel,'Position',[x y bw bh],'Visible','on');
end

function hideTip(h)
if isfield(h,'tipPanel') && ishghandle(h.tipPanel) && strcmp(get(h.tipPanel,'Visible'),'on')
    set(h.tipPanel,'Visible','off');
end
end

function refreshFigPx(fig)
% re-cache the figure's pixel size (used by the hover card AND the palette
% scroll mode).  Called from the resize hook.
try
    u = get(fig,'Units'); set(fig,'Units','pixels'); p = get(fig,'Position'); set(fig,'Units',u);
    if numel(p) >= 4 && all(isfinite(p(3:4))) && p(3) > 1
        setappdata(fig,'figpx', p(3:4));
    end
catch
end
try, updatePalScroll(fig); catch, end
end

function updatePalScroll(fig)
% SHORT-WINDOW SCROLL MODE for the left palettes.  The content panels keep
% a comfortable minimum PIXEL height: when the viewport is taller, content
% fills it 1:1 (slider hidden, identical to the classic layout); when the
% viewport is shorter, the content is pinned at that minimum and a slim
% slider appears -- controls therefore never drop below their native pixel
% size, which is exactly what made popups/edits overpaint their neighbours
% on small screens.  Pure arithmetic from the cached figure size.
h = guidata(fig);
if ~isstruct(h) || ~isfield(h,'PAi') || ~isfield(h,'PBi'), return; end
fp = getappdata(fig,'figpx');
if isempty(fp) || numel(fp) < 2 || ~isfinite(fp(2)) || fp(2) <= 1, return; end
vppx = 0.752*fp(2);                    % palette viewport height in pixels
PALMIN = 640;                          % the content's comfortable design height
F = max(1, min(2.6, PALMIN/max(vppx,1)));
sides = {{'PAi','sPA','palF_A'},{'PBi','sPB','palF_B'}};
for q = 1:2
    pin = h.(sides{q}{1});
    sl  = []; if isfield(h,sides{q}{2}), sl = h.(sides{q}{2}); end
    if ~ishghandle(pin), continue; end
    setappdata(fig, sides{q}{3}, F);
    if F <= 1.001
        set(pin,'Position',[0 0 1 1]);
        if ~isempty(sl) && ishghandle(sl), set(sl,'Visible','off','Value',1); end
    else
        v = 1; if ~isempty(sl) && ishghandle(sl), v = get(sl,'Value'); end
        set(pin,'Position',[0 (1-F)*v 1 F]);
        if ~isempty(sl) && ishghandle(sl), set(sl,'Visible','on'); end
    end
end
end

function onPalScroll(src,~)
fig = gcbf; if isempty(fig) || ~ishghandle(fig), fig = ancestor(src,'figure'); end
h = guidata(fig); side = get(src,'UserData');
F = getappdata(fig, ['palF_' side]); if isempty(F), F = 1; end
if side == 'A', pin = h.PAi; else, pin = h.PBi; end
if ~ishghandle(pin) || F <= 1, return; end
set(pin,'Position',[0 (1-F)*get(src,'Value') 1 F]);
end

function palWheel(fig, h, n)
% mouse wheel over the palette scrolls the ACTIVE tab's content (inert
% unless the short-window scroll mode is engaged)
onB = strcmp(get(h.PA,'Visible'),'on');
if onB, sl = h.sPA; key = 'palF_A'; pin = h.PAi;
else,   sl = h.sPB; key = 'palF_B'; pin = h.PBi; end
F = getappdata(fig, key);
if isempty(F) || F <= 1 || ~ishghandle(sl) || ~ishghandle(pin), return; end
v = max(0, min(1, get(sl,'Value') - 0.10*n));   % wheel down = move down the list
set(sl,'Value',v);
set(pin,'Position',[0 (1-F)*v 1 F]);
end

function L = tipLines(h, kind, idx)
% compact key/value card (ASCII, monospaced) matching the Python hover content
NET = h.NET; L = {};
pf = []; if isfield(h.ED,'pf'), pf = h.ED.pf; end
haspf = ~isempty(pf) && isfield(pf,'V') && numel(pf.V)==nbus(NET);
switch kind
case 'bus'
    i = idx; tp = {'PQ','PV','slack'};
    L{end+1} = sprintf('Bus %d', i);
    L{end+1} = kvline('type', upper(tp{NET.btype(i)}));
    if haspf
        L{end+1} = kvline('|V|',   sprintf('%.4f pu', pf.V(i)));
        L{end+1} = kvline('angle', sprintf('%.1f deg', pf.th(i)));
    end
    if NET.Pd(i) > 1e-9 || NET.Qd(i) > 1e-9
        L{end+1} = kvline('load', sprintf('%g + j%g MVA', NET.Pd(i), NET.Qd(i)));
    end
    if NET.Bs(i) ~= 0
        L{end+1} = kvline('shunt', sprintf('%g MVAr', NET.Bs(i)));
    end
    if haspf, L{end+1} = kvline('status', busWarn(pf.V(i))); end
case 'load'
    i = idx;
    L{end+1} = sprintf('Load @ bus %d', i);
    L{end+1} = kvline('demand', sprintf('%g + j%g MVA', NET.Pd(i), NET.Qd(i)));
    if haspf
        L{end+1} = kvline('|V|',    sprintf('%.4f pu', pf.V(i)));
        L{end+1} = kvline('status', busWarn(pf.V(i)));
    end
case 'gen'
    k = idx; ib = NET.g_bus(k); tag = NET.g_tag{k};
    isSG = numel(tag) >= 2 && strcmpi(tag(1:2),'SG');
    ttl = 'IBR'; if isSG, ttl = 'Generator'; end
    L{end+1} = sprintf('%s  (unit %d)', ttl, k);
    L{end+1} = kvline('at bus', sprintf('%d', ib));
    L{end+1} = kvline('tech',   tag);
    L{end+1} = kvline('P set',  sprintf('%g MW', NET.g_Pg(k)));
    if haspf && isfield(pf,'Pg') && numel(pf.Pg)==nbus(NET)
        L{end+1} = kvline('output', sprintf('%.1f + j%.1f MVA', pf.Pg(ib), pf.Qg(ib)));
    end
    L{end+1} = kvline('rating', sprintf('%g MVA', NET.g_S(k)));
case 'branch'
    k = idx; f = NET.br_f(k); t = NET.br_t(k); isX = NET.br_tap(k) ~= 0;
    ty = 'Line'; if isX, ty = 'Transformer'; end
    L{end+1} = sprintf('%s %d -> %d', ty, f, t);
    L{end+1} = kvline('R + jX', sprintf('%g + j%g pu', NET.br_r(k), NET.br_x(k)));
    if NET.br_b(k) ~= 0, L{end+1} = kvline('B', sprintf('%g pu', NET.br_b(k))); end
    if isX, L{end+1} = kvline('tap', sprintf('%.3f', NET.br_tap(k))); end
    if haspf && isfield(pf,'flows') && size(pf.flows,1)==nbr(NET)
        Pf = pf.flows(k,1); Qf = pf.flows(k,2); loss = pf.flows(k,4);
        L{end+1} = kvline('flow', sprintf('%.1f MW  %.1f MVAr', Pf, Qf));
        L{end+1} = kvline('loss', sprintf('%.2f MW', loss));
        ld = branchLoadPct(pf, k);
        if ~isnan(ld)
            L{end+1} = kvline('loading', sprintf('%.0f%% of peak', ld));
            if ld >= 90, L{end+1} = kvline('status', '! heavily loaded'); end
        end
    end
end
end

function s = kvline(k, v), s = sprintf('%-8s %s', k, v); end

function w = busWarn(V)
if V < 0.95,     w = '! undervoltage';
elseif V > 1.05, w = '! overvoltage';
else,            w = 'OK'; end
end

function ld = branchLoadPct(pf, k)
ld = NaN;
if ~isfield(pf,'flows') || isempty(pf.flows), return; end
S = hypot(pf.flows(:,1), pf.flows(:,2)); Smax = max(S);
if Smax < 1e-9, return; end
ld = 100*S(k)/Smax;
end

% =========================================================================
%                          HIT TESTING
% =========================================================================
function [kind,idx] = hitTest(h,px,py)
NET = h.NET; kind = 'none'; idx = 0; span = curspan(h); best = inf; tol = 0.03*span;
GP = [NET.gx(:) NET.gy(:)];
try
    gd = getappdata(h.ax,'gdisp');
    if size(gd,1) == ngen(NET), GP = gd; end
catch
end
for k = 1:ngen(NET)
    d = hypot(px-GP(k,1), py-GP(k,2));
    if d < 0.035*span && d < best, best = d; kind = 'gen'; idx = k; end
end
if ~strcmp(kind,'none'), return; end
% FACTS glyphs (point-like: shunt/combined at (x,y); series box at the line mid)
for k = 1:nfac(NET)
    d = NET.facts(k);
    if ~isempty(d.x) && ~isempty(d.y)
        dd = hypot(px-d.x, py-d.y);
        if dd < 0.045*span && dd < best, best = dd; kind = 'facts'; idx = k; end
    end
end
if ~strcmp(kind,'none'), return; end
% load glyphs (filled arrowheads sitting just above their busbar)
ul = netunit(NET, span); bwl = 0.62*ul;
for i = 1:nbus(NET)
    if NET.Pd(i) > 1e-9 || NET.Qd(i) > 1e-9
        lx = NET.bx(i)-bwl*0.5; ly = NET.by(i)+bwl*1.35;
        d = hypot(px-lx, py-(ly+0.20*ul));
        if d < 0.55*ul && d < best, best = d; kind = 'load'; idx = i; end
    end
end
if ~strcmp(kind,'none'), return; end
bw = 0.030*span;
for i = 1:nbus(NET)
    if abs(px-NET.bx(i)) < bw*1.3 && abs(py-NET.by(i)) < tol
        d = abs(py-NET.by(i)); if d < best, best = d; kind = 'bus'; idx = i; end
    end
end
if ~strcmp(kind,'none'), return; end
for k = 1:nbr(NET)
    f = NET.br_f(k); t = NET.br_t(k);
    d = seg_dist(px,py, NET.bx(f),NET.by(f), NET.bx(t),NET.by(t));
    if d < tol && d < best, best = d; kind = 'branch'; idx = k; end
end
end
function s = curspan(h), s = max([diff(h.ED.xlim), diff(h.ED.ylim), 200]); end
function d = seg_dist(px,py, x1,y1, x2,y2)
vx = x2-x1; vy = y2-y1; L2 = vx*vx+vy*vy;
if L2 < 1e-12, d = hypot(px-x1,py-y1); return; end
t = ((px-x1)*vx + (py-y1)*vy)/L2; t = max(0,min(1,t));
d = hypot(px-(x1+t*vx), py-(y1+t*vy));
end

% =========================================================================
%                          DRAWING
% =========================================================================
function redraw(fig)
if ~ishghandle(fig), return; end
bz = beBusy(fig);                                       %#ok<NASGU>
h = guidata(fig); NET = h.NET; ax = h.ax; cla(ax); hold(ax,'on');
set(ax,'XTick',[],'YTick',[]);
xl = h.ED.xlim; yl = h.ED.ylim; xlim(ax,xl); ylim(ax,yl); daspect(ax,[1 1 1]);
span = max([diff(xl), diff(yl), 200]);
[u, dmed] = netunit(NET, span);               % glyph size ~ network spacing (data units)
% ---- adaptive sizing, PURE data-space ----------------------------------
% No pixel queries here: toggling axes Units at redraw rate destabilizes the
% new desktop's layout pipeline (stalls -> ViewModel errors -> crashes).
% The VIEW SPAN plays the role of the screen instead: symbols hold at least
% ~3% of the visible width, so they never collapse to specks; the same pure
% ratio drives the tag visibility, the tag font and every stroke weight --
% identical adaptive behaviour, zero graphics-state churn.
u = max(u, min(0.030*span, 0.80*dmed));       % on-view floor, capped by bus spacing
gsc = u/(0.045*span);                         % 1.0 at the reference proportion
strokescale(gsc);                             % stroke weights track glyph size
tagok = (gsc >= 0.60);                        % in-circle tech tag only when it fits
tagfs = @(s) max(5, min(10, tern(numel(s)<=2, 8.6, 7.2)*min(gsc,1.25)));
bw = 0.62*u; R = 0.34*u; sh = h.ED.show;
if ~isfield(sh,'factlab'), sh.factlab = true; end   % older saved state: default on
selK = h.ED.selkind; selI = h.ED.selidx; sset = h.ED.selset;
% Explicit draw layers (back -> front), enforced with per-object ZData so the
% flow-animation timer can never re-raise arrows, and the SELECTED component is
% lifted to the selection layer so it always sits above everything:
%   0 heat/contour < 1 lines < 2 flow arrows < 3 FACTS devices + shunts
%   < 4 loads < 5 generators < 6 transformers < 7 BUSBARS (always dominant
%   at the connection point, on top of every terminal stub -- NOTHING may
%   hide a busbar) < 7.6 selection outlines (which never mask the heat)
%   < 8 labels < 10 temporary editing graphics.
Zln=1; Zsh=3; Zload=4; Zgen=5; Zxf=6; Zbus=7; Zselo=7.6; Ztx=8; Ztmp=10;
% adaptive labels: font scales with zoom relative to the fitted view
fitsp = span; if isfield(h.ED,'fitspan') && h.ED.fitspan>0, fitsp=h.ED.fitspan; end
zf = max(0.72, min(2.1, sqrt(fitsp/max(span,1))));
nb = nbus(NET);
% ---- PREDICTABLE LABELS: the ribbon "Labels" toggle is a REAL master
% switch.  ON means every class ticked under "Labels..." is drawn -- at any
% zoom, in either view mode, on any system size; OFF means NONE, with no
% exceptions: newly-added, selected and alerted components all read from
% their colour highlights alone.  Crowding on big diagrams is handled where
% it belongs: the overlap cells below skip a label whose spot is already
% taken and zooming in frees cells -- classes are never silently vetoed by
% zoom/size heuristics (that made the toggle look like it does nothing).
% The Simplified/Detailed view keeps ONE simple, explicit meaning: Detailed
% draws all ticked classes, Simplified trims to the essentials (bus numbers,
% voltages, generator tags) -- still clearly "labels are on".
master = ~isfield(h.ED,'labels') || h.ED.labels;      % master Show/Hide-labels switch
detail = ~isfield(h.ED,'detail') || h.ED.detail;      % default = detailed
if ~master, lvl = -1; elseif detail, lvl = 3; else, lvl = 2; end
heavy = nb <= 60;                                      % rich white halo only on small nets
chip = false;                                  % readability aid only over the heat map

if isfield(h.ED,'grid') && h.ED.grid           % optional CAD reference grid (View setting; OFF by default
    draw_grid(ax, xl, yl, u);                  %  -- a clean plain canvas is the professional default)
end
FI = fieldinfo(h, NET);                        % heat/contour field (V, angle, loading, loss)
if FI.on && strcmp(FI.mode,'bus') && ~h.ED.drag
    draw_contour(ax, NET, FI, xl, yl, h.ED.falpha); chip = true;
end
% while the heat wash is on, white glyph interiors (machines, transformer
% windings, FACTS cards) turn translucent so the field reads THROUGH them
% instead of leaving white holes; on the plain canvas they stay crisp white.
glyphface(tern(chip, 0.42, 1));
% ---- power-flow availability + critical-component sets (drive the Alert
%      overlay AND force labels onto problem components) -------------------
haspf = ~isempty(h.ED.pf) && isfield(h.ED.pf,'V') && numel(h.ED.pf.V)==nb;
deg = zeros(nb,1);
for kk = 1:nbr(NET), deg(NET.br_f(kk))=deg(NET.br_f(kk))+1; deg(NET.br_t(kk))=deg(NET.br_t(kk))+1; end
iso = (deg==0);
vcrit = false(nb,1); vhigh = false(nb,1); lcrit = false(nbr(NET),1);
if haspf
    vcrit = h.ED.pf.V(:)<0.95 | h.ED.pf.V(:)>1.05;
    vhigh = h.ED.pf.V(:)>1.05;              % over-voltage gets the BLUE of the Python SLD
    if isfield(h.ED.pf,'flows') && size(h.ED.pf.flows,1)==nbr(NET)
        Sf = hypot(h.ED.pf.flows(:,1), h.ED.pf.flows(:,2)); Smx = max([Sf;1e-9]);
        lcrit = Sf >= 0.90*Smx & Sf > 1e-6;
    end
end
alertOn = ~isfield(h.ED,'alerts') || h.ED.alerts;

% ---- (1) transmission lines: a selected line gets a glow but keeps its own
%      (heat) colour and stays BELOW the busbars ------------------------------
for k = 1:nbr(NET)
    f = NET.br_f(k); t = NET.br_t(k); issel = strcmp(selK,'branch') && selI==k;
    x1=NET.bx(f); y1=NET.by(f); x2=NET.bx(t); y2=NET.by(t);
    col = h.C.line; lw = 2.0*strokescale();
    if FI.on && strcmp(FI.mode,'line'), col = fcmap(fieldT(FI, FI.val(k))); lw = 4.6*strokescale(); end
    zc = Zln;
    if issel, line(ax,[x1 x2],[y1 y2],[Zln+0.4 Zln+0.4],'Color',[1.00 0.86 0.64],'LineWidth',lw+7); zc = Zln+0.5; end
    line(ax,[x1 x2],[y1 y2],[zc zc],'Color',col,'LineWidth',lw);
end
% ---- (2) flow animation + power-flow arrows (z=2, above lines) ----
drawFlowLayer(fig);
% ---- (4) transformer symbols (above buses) ----
for k = 1:nbr(NET)
    if NET.br_tap(k) ~= 0
        x1=NET.bx(NET.br_f(k)); y1=NET.by(NET.br_f(k)); x2=NET.bx(NET.br_t(k)); y2=NET.by(NET.br_t(k));
        sld_xfmr(ax,(x1+x2)/2,(y1+y2)/2, R*0.60, x2-x1, y2-y1, Zxf);
    end
end
% ---- loads + shunts: drawn BELOW the busbars so the bar covers their stubs -
for i = 1:nbus(NET)
    if NET.Pd(i) > 1e-9 || NET.Qd(i) > 1e-9
        lx=NET.bx(i)-bw*0.5; ly=NET.by(i)+bw*1.35;
        lsel = strcmp(selK,'load') && selI==i;
        if lsel
            tha=linspace(0,2*pi,32);
            patch('Parent',ax,'XData',lx+R*1.55*cos(tha),'YData',ly+0.55*R+R*1.55*sin(tha), ...
                  'ZData',(Zload-0.1)*ones(size(tha)),'FaceColor',[1.00 0.89 0.72],'EdgeColor','none');
        end
        line(ax,[lx lx],[NET.by(i) ly],[Zload Zload],'Color',h.C.load,'LineWidth',1.6*strokescale());
        sld_load(ax,lx,ly,R*0.80,h,Zload);
    end
    if NET.Bs(i) ~= 0
        sx=NET.bx(i)+bw*0.5; sy=NET.by(i)+bw*1.35;
        line(ax,[sx sx],[NET.by(i) sy],[Zsh Zsh],'Color',h.C.shunt,'LineWidth',1.6*strokescale());
        sld_shunt(ax,sx,sy,R*0.7,Zsh);
    end
end
% ---- FACTS devices (SVC/STATCOM shunt, TCSC/TSSC/SSSC series, UPFC/IPFC
%      combined): drawn at the shunt/FACTS layer with their own symbols + labels
drawFactsLayer(ax, NET, u, h, Zsh, selK, selI, master && sh.factlab, haspf, h.ED.pf);
% ---- busbars: ALWAYS on top of the connection stubs, ALWAYS keep their own
%      heat / type colour; selection is a bright OUTLINE (never a refill), so
%      the heat map stays visible under a selected or highlighted bus ---------
tp = {'PQ','PV','slack'};
for i = 1:nbus(NET)
    issel = (strcmp(selK,'bus') && selI==i); inset = any(sset==i);
    if FI.on && strcmp(FI.mode,'bus'), col = fcmap(fieldT(FI, FI.val(i))); ec=[.12 .17 .28];
    else, col = busbarcol(NET.btype(i), h); ec=[.05 .09 .18]; end
    rrect(ax, NET.bx(i), NET.by(i), bw, u*0.10, col, ec, Zbus);
    if issel || inset
        % selection = a soft warm GLOW under the bar (same shape, no border ring)
        % -- the same visual grammar as the alert glows, just in selection amber
        rrect(ax, NET.bx(i), NET.by(i), bw*1.34, u*0.175, ...
              tern(issel,[1.00 0.87 0.68],[1.00 0.93 0.82]), 'none', Zbus-0.10);
    end
end
% ---- generators (drawn below the busbars; the terminal stub is covered) ----
% each machine wears its TECHNOLOGY colour + short tag (SG/GFM/PV/W4/BES...),
% exactly as the Python SLD, so the fleet mix reads directly off the diagram
% COLLISION-AWARE placement: the drawn position is only a PREFERENCE.  Each
% machine keeps its stored spot when clear, but when a system change / the
% on-screen size floor would land the circle on ANY busbar or another
% machine, it slides around its own bus to the direction with the most
% clearance -- symbols can never overlap, on any system, at any zoom.
GXE = zeros(1,ngen(NET)); GYE = zeros(1,ngen(NET));
GDX = zeros(1,ngen(NET)); GDY = zeros(1,ngen(NET));
for k = 1:ngen(NET)
    ib=NET.g_bus(k); issel = strcmp(selK,'gen') && selI==k;
    tc = tagcol(NET.g_tag{k});
    bx0 = NET.bx(ib); by0 = NET.by(ib);
    vx = NET.gx(k)-bx0; vy = NET.gy(k)-by0; L0 = hypot(vx,vy);
    if L0 < 1e-9, vx = 0; vy = -1; L0 = 1; end
    sd = max(L0, 2.30*R);                                  % stand-off from the bar
    dirs = [vx/L0 vy/L0; 0 -1; 0 1; -1 0; 1 0; ...
            -0.71 -0.71; 0.71 -0.71; -0.71 0.71; 0.71 0.71];
    best = [bx0 by0-sd]; bd = [0 -1]; bc = -inf;
    for q = 1:size(dirs,1)
        cx = bx0 + dirs(q,1)*sd; cy = by0 + dirs(q,2)*sd;
        clr = inf;
        for j = 1:nb                                       % clearance to every busbar
            if j == ib, continue; end
            ddx = max(abs(cx-NET.bx(j)) - bw, 0);
            ddy = max(abs(cy-NET.by(j)) - u*0.10, 0);
            clr = min(clr, hypot(ddx,ddy) - R);
        end
        for j2 = 1:k-1                                     % ... and earlier machines
            clr = min(clr, hypot(cx-GXE(j2), cy-GYE(j2)) - 2.1*R);
        end
        if q == 1 && clr >= 0.25*R                         % stored spot is clear: keep it
            best = [cx cy]; bd = dirs(q,:); bc = clr; break;
        end
        if clr > bc, bc = clr; best = [cx cy]; bd = dirs(q,:); end
    end
    gx = best(1); gy = best(2);
    GXE(k) = gx; GYE(k) = gy; GDX(k) = bd(1); GDY(k) = bd(2);
    line(ax,[bx0 gx-bd(1)*R],[by0 gy-bd(2)*R],[Zgen Zgen],'Color',tc,'LineWidth',1.5*strokescale());
    if issel, sld_gen(ax,gx,gy,R*1.26,[1.00 0.87 0.68],[1.00 0.87 0.68],true,Zgen-0.1); end   % soft glow
    tg = ''; if tagok, tg = tagtxt(NET.g_tag{k}); end
    sld_gen(ax,gx,gy,R,[1 1 1],tern(issel,h.C.sel,tc),issel,Zgen,tg,tc,tagfs(tagtxt(NET.g_tag{k})));
end
setappdata(h.ax,'gdisp',[GXE(:) GYE(:)]);      % displayed spots (for hit-testing)
% ---- critical-component ALERT overlay: problems stand out by COLOUR, the
%      idiom of commercial tools -- the component itself turns alert-red
%      (amber for an isolated bus) over a soft same-shape glow.  No rings.
%      When the heat map paints the component, only the glow + red labels
%      carry the alert so the field colouring stays readable underneath.
if alertOn
    for k = 1:nbr(NET)
        if lcrit(k)
            x1=NET.bx(NET.br_f(k)); y1=NET.by(NET.br_f(k));
            x2=NET.bx(NET.br_t(k)); y2=NET.by(NET.br_t(k));
            line(ax,[x1 x2],[y1 y2],[Zln-0.15 Zln-0.15],'Color',[0.99 0.82 0.76],'LineWidth',9);  % soft glow UNDER
            if ~(FI.on && strcmp(FI.mode,'line'))
                line(ax,[x1 x2],[y1 y2],[Zln+0.05 Zln+0.05],'Color',[0.85 0.22 0.14],'LineWidth',2.4);
            end
        end
    end
    for i = 1:nb
        if iso(i) || vcrit(i)
            if iso(i),      cbad = [0.93 0.60 0.10]; soft = [0.99 0.89 0.72];   % unconnected: amber
            elseif vhigh(i),cbad = [0.11 0.30 0.85]; soft = [0.80 0.86 0.99];   % overvoltage: blue (#1d4ed8)
            else,           cbad = [0.71 0.14 0.09]; soft = [0.99 0.82 0.76];   % undervoltage: red (#b42318)
            end
            rrect(ax, NET.bx(i), NET.by(i), bw*1.32, u*0.165, soft, soft, Zbus-0.12);   % bar-shaped glow
            if ~(FI.on && strcmp(FI.mode,'bus'))
                rrect(ax, NET.bx(i), NET.by(i), bw, u*0.10, cbad, [.05 .09 .18], Zbus+0.25);  % the bar itself
            end
        end
    end
end
% ---- (8) labels: adaptive + decluttered, forced onto selected/critical parts
% lvl (from view mode + zoom + size):  -1 none | 0 sel/critical only |
%   1 +bus# | 2 +V,gen | 3 +type,load,line#,flow
% SMART DECLUTTER (the idiom of professional SLD tools): every label class
% claims a screen cell in PRIORITY order -- bus number > voltage > bus type
% > generator tag > load value > line flow > line number.  A lower-priority
% label whose cell is already taken is simply skipped this frame; selected
% and critical components always win their cell; and the cells are a fixed
% fraction of the VISIBLE span, so zooming in shrinks them and the hidden
% labels reappear progressively.  Large systems therefore stay readable
% with no class ever silently vetoed -- exactly what the Labels menu
% promises, decluttered instead of overprinted.
occ = zeros(0,2); cellD = labelCell(ax, xl);
for i = 1:nb
    isSel = strcmp(selK,'bus') && selI==i;
    % THE LABELS SWITCH IS ABSOLUTE (user rule): OFF means no label on any
    % component, ever -- not on a just-added part (which is auto-selected),
    % not on a clicked part, not on an alerted part.  Selection and alerts
    % read from their colour highlights alone.  With Labels ON, selected
    % and alerted components merely get PRIORITY for their label cell.
    isBad = alertOn && (iso(i) || vcrit(i));
    force = master && (isSel || isBad);
    if (lvl>=1 && sh.busno) || force
        [ok,occ] = claimCell(occ, NET.bx(i)+bw*1.2, NET.by(i), cellD, force);
        if ok, lbl(ax,NET.bx(i)+bw*1.2, NET.by(i), Ztx, sprintf('%d',i), 9*zf, [.15 .2 .3], 'left', chip, true, heavy); end
    end
    if haspf && sh.volt && master && (lvl>=2 || isSel || (alertOn && vcrit(i)))
        [ok,occ] = claimCell(occ, NET.bx(i), NET.by(i)+u*0.32, cellD, force);
        if ok
            vc = [.16 .34 .24];
            if vhigh(i), vc = [.11 .30 .85]; elseif vcrit(i), vc = [.72 .10 .08]; end
            vs = sprintf('%.3f pu', h.ED.pf.V(i));   % |V| and the angle: the full phasor
            if isfield(h.ED.pf,'th') && numel(h.ED.pf.th) >= i
                vs = sprintf('%.3f pu  %.1f%c', h.ED.pf.V(i), h.ED.pf.th(i), 176);
            end
            lbl(ax,NET.bx(i), NET.by(i)+u*0.32, Ztx, vs, 7*zf, vc, 'center', chip, true, heavy);
        end
    end
    if lvl>=3 && sh.type
        [ok,occ] = claimCell(occ, NET.bx(i)-bw*1.2, NET.by(i), cellD, false);
        if ok, lbl(ax,NET.bx(i)-bw*1.2, NET.by(i), Ztx, tp{NET.btype(i)}, 7*zf, h.C.grey, 'right', chip, false, heavy); end
    end
end
if lvl >= 2 && sh.genlab
    for k = 1:ngen(NET)
        gsel = strcmp(selK,'gen') && selI==k;
        [ok,occ] = claimCell(occ, GXE(k)+GDX(k)*R*1.9, GYE(k)+GDY(k)*R*1.9, cellD, gsel);
        if ok
            lbl(ax, GXE(k)+GDX(k)*R*1.9, GYE(k)+GDY(k)*R*1.9, Ztx, NET.g_tag{k}, ...
                7*zf, tagcol(NET.g_tag{k}), 'center', chip, true, heavy);
        end
    end
end
if lvl >= 3 && sh.loadlab
    for i = 1:nb
        if NET.Pd(i) > 1e-9 || NET.Qd(i) > 1e-9
            lx=NET.bx(i)-bw*0.5; ly=NET.by(i)+bw*1.35;
            [ok,occ] = claimCell(occ, lx-R*0.6, ly+R*1.95, cellD, false);
            if ok, lbl(ax,lx-R*0.6, ly+R*1.95, Ztx, sprintf('%.0f+j%.0f',NET.Pd(i),NET.Qd(i)), 6*zf, h.C.load, 'right', chip, false, heavy); end
        end
    end
end
if lvl >= 3 && sh.flowlab && haspf && isfield(h.ED.pf,'flows') && size(h.ED.pf.flows,1)==nbr(NET)
    for k = 1:nbr(NET)
        x1=NET.bx(NET.br_f(k)); y1=NET.by(NET.br_f(k)); x2=NET.bx(NET.br_t(k)); y2=NET.by(NET.br_t(k));
        [ok,occ] = claimCell(occ, (x1+x2)/2, (y1+y2)/2 + bw*0.5, cellD, false);
        if ok, lbl(ax,(x1+x2)/2,(y1+y2)/2 + bw*0.5, Ztx, sprintf('%.0f MW',h.ED.pf.flows(k,1)), 6.5*zf, [.14 .30 .22], 'center', chip, false, heavy); end
    end
end
if lvl >= 3 && sh.lineno
    for k = 1:nbr(NET)
        x1=NET.bx(NET.br_f(k)); y1=NET.by(NET.br_f(k)); x2=NET.bx(NET.br_t(k)); y2=NET.by(NET.br_t(k));
        [ok,occ] = claimCell(occ, (x1+x2)/2, (y1+y2)/2 - bw*0.6, cellD, false);
        if ok, lbl(ax,(x1+x2)/2,(y1+y2)/2 - bw*0.6, Ztx, sprintf('L%d',k), 7*zf, h.C.grey, 'center', chip, false, heavy); end
    end
end
% ---- (9) selection / interaction overlays (frontmost) ----
if any(strcmp(h.ED.tool,{'line','xfmr'})) && h.ED.lineFrom > 0 && h.ED.lineFrom <= nbus(NET)
    q=get(ax,'CurrentPoint'); i=h.ED.lineFrom;
    line(ax,[NET.bx(i) q(1,1)],[NET.by(i) q(1,2)],[Ztmp Ztmp],'LineStyle','--','Color',h.C.sel,'LineWidth',1.4);
end
if h.ED.boxsel
    q=get(ax,'CurrentPoint'); x0=h.ED.boxstart(1); y0=h.ED.boxstart(2);
    line(ax,[x0 q(1,1) q(1,1) x0 x0],[y0 y0 q(1,2) q(1,2) y0],[Ztmp Ztmp Ztmp Ztmp Ztmp],'LineStyle','--','Color',h.C.sel,'LineWidth',1);
end
if isfield(h.ED,'zoomrect') && h.ED.zoomrect       % area-zoom rubber band
    q=get(ax,'CurrentPoint'); x0=h.ED.zoomstart(1); y0=h.ED.zoomstart(2);
    line(ax,[x0 q(1,1) q(1,1) x0 x0],[y0 y0 q(1,2) q(1,2) y0],[Ztmp Ztmp Ztmp Ztmp Ztmp],'LineStyle','-.','Color',[.16 .38 .89],'LineWidth',1.3);
end
% the colour-bar legend card is OFF by default (it covers diagram corner
% space); Display options -> "Heat colour-bar legend" brings it back.
if FI.on && isfield(h.ED,'flegend') && h.ED.flegend, draw_fieldlegend(ax, xl, yl, FI); end
hold(ax,'off');
% no axes title — the canvas is a clean SLD surface; the network name and
% component counts live in the window title and the Report tab instead.
set(fig,'Name',sprintf('PSDAT — %s  (%d buses, %d lines, %d generators)   [%s]', ...
    NET.name, nbus(NET), nbr(NET), ngen(NET), buildtag()));
end

function s = buildtag()
% version stamp shown in the window title and printed at startup, so a stale
% shadowed copy on the MATLAB path is visible at a glance -- "which file is
% actually running" has burned us before.  Bumped on every delivered build.
s = 'build 02-Aug-2026z11';
end

% ---------------- elegant SLD glyphs + sizing ----------------------------
function a = glyphface(na)
% FaceAlpha for white glyph interiors: 1 (opaque) on the plain canvas, and
% translucent while the heat wash is on, so the field shows through machines,
% transformer windings and FACTS cards instead of punching white holes.
persistent ga
if isempty(ga), ga = 1; end
if nargin >= 1, ga = max(0.25, min(1, na)); end
a = ga;
end
function s = strokescale(ns)
% shared stroke-weight scale: 1.0 at the reference glyph size (16-px machine
% radius), thinner on dense/zoomed-out diagrams, heavier zoomed in -- so
% component SIZE and line THICKNESS stay proportional at every zoom level
% and system size.
persistent cur
if isempty(cur), cur = 1; end
% upper clamp 1.05: strokes may SLIM DOWN on dense/zoomed-out diagrams but
% never fatten past the design weight -- upscaled borders read as chunky and
% unprofessional (they are the "thick border" look, not a feature)
if nargin >= 1 && isfinite(ns), cur = max(0.55, min(1.05, ns)); end
s = cur;
end
function [u, dmed] = netunit(NET, span)
% component size scaled to the network's own spacing (so shapes are
% proportional to the diagram, and zooming reveals detail); dmed = the raw
% median nearest-neighbour bus distance, for spacing-aware size floors.
n = numel(NET.btype);
if n < 2, u = 0.05*span; dmed = span; return; end
d = inf(n,1);
for i = 1:n
    dd = hypot(NET.bx-NET.bx(i), NET.by-NET.by(i)); dd(i) = inf; d(i) = min(dd);
end
dmed = median(d(isfinite(d)));
u = 0.42*dmed;
u = max(min(u, 0.11*span), 0.012*span);
end
function c = busbarcol(bt, h)
switch bt
case 3, c = [0.09 0.30 0.50];      % slack
case 2, c = [0.15 0.27 0.48];      % PV
otherwise, c = h.C.navy;           % PQ
end
end
function rrect(ax, cx, cy, hw, hh, fc, ec, z)
% horizontal busbar drawn as a rounded rectangle at draw-layer z
if nargin < 8, z = 3; end
r = hh; th = linspace(-pi/2, pi/2, 9);
xr = [cx+hw-r + r*cos(th),  cx-hw+r - r*cos(th)];
yr = [cy + r*sin(th),       cy - r*sin(th)];
zr = z*ones(size(xr));
if ischar(ec), patch('Parent',ax,'XData',xr,'YData',yr,'ZData',zr,'FaceColor',fc,'EdgeColor',ec);
else, patch('Parent',ax,'XData',xr,'YData',yr,'ZData',zr,'FaceColor',fc,'EdgeColor',ec,'LineWidth',0.9*strokescale()); end
end
function rrect_outline(ax, cx, cy, hw, hh, col, z)
% bright rounded-rectangle OUTLINE for a selection / highlight ring around a
% busbar - it never fills, so the heat-map colour underneath stays visible.
r = hh; th = linspace(-pi/2, pi/2, 9);
xr = [cx+hw-r + r*cos(th),  cx-hw+r - r*cos(th),  cx+hw-r + r*cos(th(1))];
yr = [cy + r*sin(th),       cy - r*sin(th),       cy + r*sin(th(1))];
line(ax, xr, yr, z*ones(size(xr)), 'Color', col, 'LineWidth', 2.6);
end
function sld_gen(ax, cx, cy, r, fc, ec, sel, z, tag, tc, fs)
% machine glyph, the exact idiom of the Python SLD: a clean white circle in
% the unit's TECHNOLOGY colour with the short technology tag inside (SG /
% GFM / PV / W4 / BES ...), so the fleet mix reads directly off the diagram.
if nargin < 8, z = 6; end
if nargin < 9, tag = ''; end
if nargin < 10, tc = ec; end
if nargin < 11, fs = 8; end
th = linspace(0,2*pi,64); lw = 1.7*strokescale(); if sel, lw = 2.4*strokescale(); end
patch('Parent',ax,'XData',cx+r*cos(th),'YData',cy+r*sin(th),'ZData',z*ones(size(th)),'FaceColor',fc,'EdgeColor',ec,'LineWidth',lw,'FaceAlpha',glyphface());
if ~isempty(tag)
    text(cx, cy, z+0.5, tag, 'Parent',ax, 'FontSize',round(fs*10)/10, 'FontWeight','bold', ...
        'Color',tc, 'HorizontalAlignment','center', 'Clipping','on');
end
end
function sld_load(ax, cx, cy, s, h, z)   %#ok<INUSD>
% load glyph, mirroring the Python SLD: a slim slate arrow -- thin shaft and
% a compact filled head pointing away from the busbar (delivery direction).
if nargin < 6, z = 5; end
sl = [0.478 0.318 0.118];                                   % bronze #7a511e -- distinct
patch('Parent',ax,'XData',[cx-s*0.62 cx+s*0.62 cx],'YData',[cy cy cy+s*1.15],'ZData',[z z z], ...
      'FaceColor',sl,'EdgeColor','none');                   % from the green FLOW arrows
line(ax,[cx cx],[cy cy-s*0.55],[z z],'Color',sl,'LineWidth',1.5*strokescale());
end
function sld_shunt(ax, cx, cy, s, z)
% shunt capacitor: two crisp plates + earth stem (teal, as the Python SLD)
if nargin < 5, z = 7; end
tc = [0.067 0.478 0.545];                                   % teal  #117a8b
line(ax,[cx-s cx+s],[cy cy],[z z],'Color',tc,'LineWidth',2.0*strokescale());
line(ax,[cx-s*0.72 cx+s*0.72],[cy-s*0.55 cy-s*0.55],[z z],'Color',tc,'LineWidth',2.0*strokescale());
line(ax,[cx cx],[cy-s*0.55 cy-s*1.5],[z z],'Color',tc,'LineWidth',1.3*strokescale());
end
function sld_xfmr(ax, cx, cy, r, dx, dy, z)
% two-winding transformer: interlocking circles, the first softly filled so
% the pair reads instantly on top of its line (Python SLD idiom).
if nargin < 7, z = 4; end
L=hypot(dx,dy); if L<1e-9, ux=1; uy=0; else, ux=dx/L; uy=dy/L; end
th=linspace(0,2*pi,48); zz=z*ones(size(th)); cc=[.3 .38 .52];
patch('Parent',ax,'XData',cx-ux*r*0.62+r*cos(th),'YData',cy-uy*r*0.62+r*sin(th),'ZData',zz,'FaceColor',[0.984 0.988 0.996],'EdgeColor',cc,'LineWidth',1.6*strokescale(),'FaceAlpha',glyphface());
patch('Parent',ax,'XData',cx+ux*r*0.62+r*cos(th),'YData',cy+uy*r*0.62+r*sin(th),'ZData',zz+0.05,'FaceColor','none','EdgeColor',cc,'LineWidth',1.6*strokescale());
end
function c = tagcol(t)
% unit-technology colour: the Python SLD's TAGC hues, gently DESATURATED so
% the fleet palette reads as engineering ink rather than highlighter -- the
% bright end of the spectrum stays reserved for alerts, violations, the
% selection amber and the heat map (the things that carry meaning).
t = upper(char(t));
if strcmp(t,'GFM'),                          c = [0.129 0.451 0.267];   % muted forest
elseif strcmp(t,'GFL'),                      c = [0.604 0.243 0.196];   % muted brick
elseif ~isempty(strfind(t,'PV')),            c = [0.612 0.502 0.106];   % muted gold
elseif ~isempty(strfind(t,'BESS')),          c = [0.541 0.263 0.078];   % muted umber
elseif ~isempty(strfind(t,'WT')),            c = [0.086 0.420 0.478];   % muted teal
elseif any(strcmp(t,{'SGP','SG6P'})),        c = [0.310 0.212 0.541];   % muted violet (PSS)
else,                                        c = [0.122 0.231 0.451];   % navy SG (house colour)
end
end
function s = tagtxt(t)
% short in-circle technology tag, identical to the Python SLD's TAGS map
map = {'SG','SG';'SGP','SGp';'SG6','SG6';'SG6P','S6p';'SG6G','S6g'; ...
       'SG4','SG4';'SG4G','S4g';'SG2','SG2';'GFM','GFM';'GFL','GFL'; ...
       'PV-GFL','PV';'PV-GFM','PV';'BESS-GFM','BES';'BESS-GFL','BES'; ...
       'WT4-GFL','W4';'WT4-GFM','W4';'WT3','W3';'WT1','W1';'WT2','W2'};
s = 'G';
for k = 1:size(map,1)
    if strcmpi(char(t), map{k,1}), s = map{k,2}; return; end
end
end
function lbl(ax, x, y, z, s, fs, col, ha, chip, bold, heavy)   %#ok<INUSD>
% clean SLD label: zoom-scaled font and high-contrast colour, drawn with NO
% boxy plate or white halo behind it (those read as clutter over the heat
% map).  The chip/heavy arguments are accepted for call-compatibility and
% intentionally ignored - one text object per label, which is also faster.
if nargin < 10, bold = false; end
fw = 'normal'; if bold, fw = 'bold'; end
% NO 'Clipping','on' here: on the new JS-rendered desktop a text object with
% an explicit z-position AND clipping enabled is clipped out entirely (the
% in-glyph SG/tech tags -- z, no clipping -- always rendered, while these
% labels -- z + clipping -- never did).  Un-clipped is the form proven to
% draw on every release this app has met.
text(x, y, z, s, 'Parent',ax, 'FontSize',max(5,round(fs)), 'Color',col, ...
    'FontWeight',fw, 'HorizontalAlignment',ha);
end
function ring(ax, cx, cy, r, col, z)
% open circle outline used to flag a critical bus (voltage violation / island)
th = linspace(0, 2*pi, 40);
line(ax, cx+r*cos(th), cy+r*sin(th), z*ones(size(th)), 'Color', col, 'LineWidth', 2.4);
end
% =========================================================================
%   FACTS device glyphs (mirror the Python SLD: shunt symbol at a bus, series
%   box on a line, combined shunt+series / two-series with a dashed DC link)
% =========================================================================
function drawFactsLayer(ax, NET, u, h, Z, selK, selI, labon, haspf, PF)  %#ok<INUSD>
if nfac(NET)==0, return; end
bw = 0.44*u; bh = 0.24*u; R = 0.30*u;
% PROFESSIONAL SLD CONVENTION (IEEE/IEC practice): equipment symbols are
% drawn in ONE neutral engineering ink -- the same dark slate-blue family as
% busbars, lines and transformers -- and the device TYPE is read from its
% symbol (thyristor pair, VSC step, staircase, sine), not from a colour.
% Saturated colours stay reserved for what carries MEANING: results (heat,
% flows), alarms/violations and the selection highlight.
ink = [0.22 0.29 0.43];
cS = ink; cT = ink; cA = ink; cI = ink;
for k = 1:nfac(NET)
    d = NET.facts(k); ty = upper(d.type); sel = strcmp(selK,'facts') && selI==k;
    hasPod = isstruct(d.pod) && isfield(d.pod,'on') && d.pod.on;
    if isShuntFac(ty)
        b = d.bus; if b<1 || b>nbus(NET), continue; end
        col = cS; if strcmp(ty,'STATCOM'), col = cT; end
        line(ax,[d.x d.x],[NET.by(b) d.y],[Z Z],'Color',col,'LineWidth',1.25*strokescale());
        if strcmp(ty,'SVC')
            facBox(ax,d.x,d.y,bw*0.62,bh*0.95,col,sel,Z);
            facSym(ax,d.x,d.y,'svcpair',bh*0.66,col,Z);      % antiparallel thyristors
        else
            facCircle(ax,d.x,d.y,R*0.82,col,sel,Z);
            facSym(ax,d.x,d.y,'step',R*0.62,col,Z);          % VSC waveform
        end
        if labon, lbl(ax,d.x,d.y+bh*1.7,8,facLbl(ty,hasPod),8,col,'center',false,true); end
    elseif isSeriesFac(ty)
        f=d.f; t=d.t; if f<1||f>nbus(NET)||t<1||t>nbus(NET), continue; end
        col = cA; if strcmp(ty,'SSSC'), col = cT; end
        facBox(ax,d.x,d.y,bw,bh,col,sel,Z);
        if strcmp(ty,'SSSC'),     facSym(ax,d.x,d.y,'sine',bh*0.62,col,Z);   % series VSC
        elseif strcmp(ty,'TCSC'), facSym(ax,d.x,d.y,'tcsc',bh*0.60,col,Z);   % cap + TCR bypass
        else,                     facSym(ax,d.x,d.y,'tssc',bh*0.60,col,Z); end % switched cap
        if labon, lbl(ax,d.x,d.y+bh*1.9,8,facLbl(ty,hasPod),8,col,'center',false,true); end
    elseif strcmp(ty,'UPFC')
        f=d.f; t=d.t; b=d.bus; if f<1||f>nbus(NET)||t<1||t>nbus(NET), continue; end
        mx=0.5*(NET.bx(f)+NET.bx(t)); my=0.5*(NET.by(f)+NET.by(t));
        facDash(ax,mx,my,d.x,d.y,Z,cS);
        if b>=1 && b<=nbus(NET), line(ax,[d.x d.x],[NET.by(b) d.y],[Z Z],'Color',cS,'LineWidth',1.25*strokescale()); end
        facBox(ax,mx,my,bw,bh,cS,sel,Z); facSym(ax,mx,my,'sine',bh*0.62,cS,Z);
        facCircle(ax,d.x,d.y,R*0.80,cS,sel,Z); facSym(ax,d.x,d.y,'step',R*0.60,cS,Z);
        if labon, lbl(ax,d.x,d.y+bh*1.7,8,facLbl('UPFC',hasPod),8,cS,'center',false,true); end
    else                                                   % IPFC
        f=d.f; t=d.t; if f<1||f>nbus(NET)||t<1||t>nbus(NET), continue; end
        m1x=0.5*(NET.bx(f)+NET.bx(t)); m1y=0.5*(NET.by(f)+NET.by(t));
        l2 = ~isempty(d.f2)&&d.f2>=1&&d.f2<=nbus(NET)&&~isempty(d.t2)&&d.t2>=1&&d.t2<=nbus(NET);
        if l2
            m2x=0.5*(NET.bx(d.f2)+NET.bx(d.t2)); m2y=0.5*(NET.by(d.f2)+NET.by(d.t2));
            facDash(ax,m1x,m1y,m2x,m2y,Z,cI);
            facBox(ax,m2x,m2y,bw,bh,cI,sel,Z); facSym(ax,m2x,m2y,'sine',bh*0.62,cI,Z);
        end
        facBox(ax,m1x,m1y,bw,bh,cI,sel,Z); facSym(ax,m1x,m1y,'sine',bh*0.62,cI,Z);
        if labon, lbl(ax,m1x,m1y+bh*1.9,8,facLbl('IPFC',hasPod),8,cI,'center',false,true); end
    end
end
end
function s = facLbl(ty, hasPod), s = ty; if hasPod, s = [ty ' +POD']; end, end
function facBox(ax,x,y,w,hh,col,sel,Z)
% ROUNDED-corner card with a hairline border -- the exact idiom of the Python
% SLD (rect rx=3, stroke-width 2 on a 30x18 card): light, crisp, never chunky.
r = 0.30*min(w,hh); q = linspace(0,pi/2,7);
xs = [x+w-r+r*cos(q), x-w+r-r*sin(q), x-w+r-r*cos(q), x+w-r+r*sin(q)];
ys = [y+hh-r+r*sin(q), y+hh-r+r*cos(q), y-hh+r-r*sin(q), y-hh+r-r*cos(q)];
if sel   % selection = soft warm glow behind the card, never a recoloured border
    ws_ = w + 0.24*min(w,hh); hs_ = hh*1.30; rs = 0.30*min(ws_,hs_);
    xg = [x+ws_-rs+rs*cos(q), x-ws_+rs-rs*sin(q), x-ws_+rs-rs*cos(q), x+ws_-rs+rs*sin(q)];
    yg = [y+hs_-rs+rs*sin(q), y+hs_-rs+rs*cos(q), y-hs_+rs-rs*sin(q), y-hs_+rs-rs*cos(q)];
    patch('Parent',ax,'XData',xg,'YData',yg,'ZData',(Z-0.15)*ones(size(xg)),'FaceColor',[1.00 0.87 0.68],'EdgeColor','none');
end
patch('Parent',ax,'XData',xs,'YData',ys,'ZData',Z*ones(size(xs)),'FaceColor','w','EdgeColor',col,'LineWidth',1.3*strokescale(),'FaceAlpha',glyphface());
end
function facCircle(ax,x,y,r,col,sel,Z)
th=linspace(0,2*pi,40);
if sel   % soft glow disc behind, device border stays its own colour
    patch('Parent',ax,'XData',x+r*1.30*cos(th),'YData',y+r*1.30*sin(th), ...
          'ZData',(Z-0.15)*ones(size(th)),'FaceColor',[1.00 0.87 0.68],'EdgeColor','none');
end
patch('Parent',ax,'XData',x+r*cos(th),'YData',y+r*sin(th),'ZData',Z*ones(size(th)),'FaceColor','w','EdgeColor',col,'LineWidth',1.3*strokescale(),'FaceAlpha',glyphface());
end
function facSym(ax,x,y,kind,s,col,Z)
% the DEVICE SYMBOL drawn inside a FACTS glyph (same idiom as the palette
% icons / the Python SLD): thyristor valve, VSC step, capacitor plates, sine.
switch kind
case 'tri'      % thyristor valve: triangle + commutation bar
    line(ax,[x-0.8*s x+0.8*s x x-0.8*s],[y+0.55*s y+0.55*s y-0.62*s y+0.55*s], ...
        Z+1+zeros(1,4),'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x-0.8*s x+0.8*s],[y-0.62*s y-0.62*s],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
case 'svcpair'  % ANTIPARALLEL thyristor pair (IEC SVC valve): two opposed
    % triangles side by side, each with its commutation bar -- the signature
    % that reads "thyristor-controlled" at a glance.
    xl2 = x - 0.48*s; xr = x + 0.48*s; wv = 0.40*s; hv = 0.62*s;
    line(ax,[xl2-wv xl2+wv xl2 xl2-wv],[y+hv y+hv y-hv y+hv], ...
        Z+1+zeros(1,4),'Color',col,'LineWidth',1.0*strokescale());                 % left: points down
    line(ax,[xl2-wv xl2+wv],[y-hv y-hv],[Z+1 Z+1],'Color',col,'LineWidth',1.0*strokescale());
    line(ax,[xr-wv xr+wv xr xr-wv],[y-hv y-hv y+hv y-hv], ...
        Z+1+zeros(1,4),'Color',col,'LineWidth',1.0*strokescale());                 % right: points up
    line(ax,[xr-wv xr+wv],[y+hv y+hv],[Z+1 Z+1],'Color',col,'LineWidth',1.0*strokescale());
case 'tcsc'     % CONTINUOUSLY-VARIABLE series capacitor: the plates carry the
    % IEC "adjustable" diagonal arrow -- reads instantly as thyristor-CONTROLLED
    % compensation (and can never be mistaken for the step-switched TSSC).
    line(ax,[x-0.28*s x-0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x+0.28*s x+0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x-1.5*s x-0.28*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x+0.28*s x+1.5*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x-1.25*s x+1.25*s],[y-1.30*s y+1.30*s],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x+1.25*s x+0.55*s],[y+1.30*s y+1.22*s],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x+1.25*s x+1.10*s],[y+1.30*s y+0.62*s],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
case 'tssc'     % STEP-SWITCHED series capacitor: plates + a small staircase
    % (compensation inserted in discrete steps, no continuous control).
    line(ax,[x-0.28*s x-0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x+0.28*s x+0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x-1.5*s x-0.28*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x+0.28*s x+1.5*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x-1.20*s x-0.50*s x-0.50*s x+0.20*s x+0.20*s x+0.90*s x+0.90*s], ...
        [y-1.42*s y-1.42*s y-1.12*s y-1.12*s y-0.82*s y-0.82*s y-0.52*s], ...
        Z+1+zeros(1,7),'Color',col,'LineWidth',0.95*strokescale());
case 'step'     % VSC switching waveform
    line(ax,[x-0.95*s x-0.45*s x-0.45*s x+0.15*s x+0.15*s x+0.65*s x+0.65*s x+0.95*s], ...
        [y y y+0.62*s y+0.62*s y-0.62*s y-0.62*s y y], ...
        Z+1+zeros(1,8),'Color',col,'LineWidth',1.0*strokescale());
case 'cap'      % series capacitor plates + leads
    line(ax,[x-0.28*s x-0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x+0.28*s x+0.28*s],[y-s y+s],[Z+1 Z+1],'Color',col,'LineWidth',1.35*strokescale());
    line(ax,[x-1.5*s x-0.28*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
    line(ax,[x+0.28*s x+1.5*s],[y y],[Z+1 Z+1],'Color',col,'LineWidth',0.95*strokescale());
case 'sine'     % injected AC voltage
    tt = linspace(0,2*pi,25);
    line(ax,x+linspace(-1.05*s,1.05*s,25),y+0.62*s*sin(tt), ...
        Z+1+zeros(1,25),'Color',col,'LineWidth',1.0*strokescale());
end
end
function facDash(ax,x1,y1,x2,y2,Z,col)
n=9; t=linspace(0,1,2*n+1);
for j=1:2:2*n
    line(ax,[x1+(x2-x1)*t(j) x1+(x2-x1)*t(j+1)],[y1+(y2-y1)*t(j) y1+(y2-y1)*t(j+1)],[Z Z],'Color',col,'LineWidth',0.95*strokescale());
end
end
function cellD = labelCell(ax, xl)   %#ok<INUSL>
% overlap-avoidance cell size as a fixed fraction of the VISIBLE span (~2%,
% the old 22 px on a typical canvas).  Pure arithmetic -- no Units queries in
% the draw path (axes-Units round-trips destabilize the new desktop).
cellD = 0.020*max(diff(xl), 1e-9);
end
function [ok, occ] = claimCell(occ, x, y, cellD, force)
ix = round(x/cellD); iy = round(y/cellD);
taken = ~isempty(occ) && any(occ(:,1)==ix & occ(:,2)==iy);
if force || ~taken, ok = true; occ(end+1,:) = [ix iy]; else, ok = false; end
end

% ---- toolbar glyphs: small CData icons drawn programmatically (NaN pixels
%      are transparent, so the button's own colour shows through) ----------
function draw_grid(ax, xl, yl, u)
g = u*2.2; if g <= 0, return; end
if diff(xl)/g > 90 || diff(yl)/g > 90, return; end     % avoid a dense mesh
for x = ceil(xl(1)/g)*g : g : xl(2), line(ax,[x x],yl,'Color',[.935 .95 .965],'LineWidth',0.5); end
for y = ceil(yl(1)/g)*g : g : yl(2), line(ax,xl,[y y],'Color',[.935 .95 .965],'LineWidth',0.5); end
end

% ---------------- multi-quantity heat / contour field --------------------
function FI = fieldinfo(h, NET)
% Risk-based heat convention (identical in both platforms): RED = most
% critical / highest risk, BLUE = safest.  For voltage the risk grows as V
% FALLS (undervoltage), so vmag is inverted; loading/loss risk grows with
% the value, so they map straight.
FI = struct('on',false,'mode','','val',[],'lo',0,'hi',1,'label','','invert',false);
if ~(h.ED.heat && ~isempty(h.ED.pf) && isfield(h.ED.pf,'V') && numel(h.ED.pf.V)==nbus(NET)), return; end
FI.on = true; pf = h.ED.pf;
switch h.ED.field
case 'vang', FI.mode='bus';  FI.val=pf.th(:);                  FI.label='angle  (deg)';
case 'load', FI.mode='line'; FI.val=linevals(pf,'load',nbr(NET)); FI.label='loading  (MVA)';
case 'loss', FI.mode='line'; FI.val=linevals(pf,'loss',nbr(NET)); FI.label='loss  (MW)';
case 'q',    FI.mode='bus';
    if isfield(pf,'Qg') && numel(pf.Qg)==nbus(NET), FI.val=pf.Qg(:)-NET.Qd(:);
    else, FI.val=-NET.Qd(:); end
    FI.label='reactive Q  (MVAr)';
otherwise,   FI.mode='bus';  FI.val=pf.V(:);                   FI.label='|V|  (pu)'; FI.invert=true;
end
if isempty(FI.val) || (strcmp(FI.mode,'line') && nbr(NET)==0), FI.on=false; return; end
FI.lo=min(FI.val); FI.hi=max(FI.val);
if any(strcmp(h.ED.field,{'load','loss'})), FI.lo=0; end
if FI.hi-FI.lo < 1e-6, FI.hi=FI.lo+1; end
end
function v = linevals(pf, which, nb)
v = zeros(nb,1);
if ~isfield(pf,'flows') || size(pf.flows,1) ~= nb, return; end
if strcmp(which,'load'), v = hypot(pf.flows(:,1), pf.flows(:,2));   % |S from|  (MVA)
else, v = abs(pf.flows(:,4)); end                                   % loss      (MW)
end
function c = fcmap(t)
t = max(0,min(1,t));
cp = [0.05 0.24 0.62; 0.00 0.62 0.92; 0.10 0.72 0.24; 0.98 0.80 0.10; 0.86 0.14 0.10];
x = t*4; i = min(4,max(1,floor(x)+1)); f = x-(i-1);
c = cp(i,:)*(1-f) + cp(i+1,:)*f;
end
function t = fieldT(FI, val)
% map a quantity value to the colour parameter t (0=blue/safe, 1=red/critical)
t = (val - FI.lo) ./ max(FI.hi - FI.lo, 1e-9);
if FI.invert, t = 1 - t; end
t = max(0, min(1, t));
end
function CM = buildcmap(n)
CM = zeros(n,3); for i = 1:n, CM(i,:) = fcmap((i-1)/max(n-1,1)); end
end
function draw_contour(ax, NET, FI, xl, yl, alpha)
ng = min(220, max(100, round(80 + 8*sqrt(nbus(NET)))));   % fine, size-adaptive grid -> smooth field, no visible facets
xg = linspace(xl(1),xl(2),ng); yg = linspace(yl(1),yl(2),ng);
[XG,YG] = meshgrid(xg,yg); Ws = zeros(ng); Vs = zeros(ng);
soft = (0.04*max(diff(xl),diff(yl)))^2;
for i = 1:nbus(NET)
    d2 = (XG-NET.bx(i)).^2 + (YG-NET.by(i)).^2 + soft; w = 1./d2;
    Ws = Ws + w; Vs = Vs + w*FI.val(i);
end
ZG = fieldT(FI, Vs ./ Ws);         % risk-transformed field (0=blue, 1=red)
hs = surface(ax, XG, YG, zeros(ng), ZG, 'EdgeColor','none','FaceColor','interp');
try, set(hs,'FaceAlpha',alpha); catch, end
try, colormap(ax, buildcmap(64)); catch, colormap(buildcmap(64)); end
try, caxis(ax,[0 1]); catch, end
end
function draw_fieldlegend(ax, xl, yl, FI)
n=26; x0=xl(2)-0.32*diff(xl); x1=xl(2)-0.04*diff(xl);
y0=yl(1)+0.05*diff(yl); hgt=0.020*diff(yl); xs=linspace(x0,x1,n+1);
% card backing: the legend floats as a small white widget over the heat map
pw=(x1-x0)*0.10; 
patch('Parent',ax,'XData',[x0-pw x1+pw x1+pw x0-pw], ...
      'YData',[y0-hgt*1.9 y0-hgt*1.9 y0+hgt*3.4 y0+hgt*3.4], ...
      'FaceColor',[1 1 1],'FaceAlpha',0.88,'EdgeColor',[.80 .83 .88],'LineWidth',0.6);
for j=1:n
    v = FI.lo + (j-0.5)/n*(FI.hi-FI.lo);
    patch('Parent',ax,'XData',[xs(j) xs(j+1) xs(j+1) xs(j)],'YData',[y0 y0 y0+hgt y0+hgt], ...
          'FaceColor',fcmap(fieldT(FI,v)),'EdgeColor','none');
end
patch('Parent',ax,'XData',[x0 x1 x1 x0],'YData',[y0 y0 y0+hgt y0+hgt],'FaceColor','none','EdgeColor',[.5 .5 .55],'LineWidth',0.6);
text((x0+x1)/2, y0+hgt*2.3, FI.label,'Parent',ax,'FontSize',8,'FontWeight','bold','Color',[.25 .28 .34],'HorizontalAlignment','center','Clipping','on');
text(x0,        y0-hgt*0.9, sprintf('%.3g',FI.lo),'Parent',ax,'FontSize',6,'Color',[.3 .3 .35],'HorizontalAlignment','center','Clipping','on');
text((x0+x1)/2, y0-hgt*0.9, sprintf('%.3g',(FI.lo+FI.hi)/2),'Parent',ax,'FontSize',6,'Color',[.3 .3 .35],'HorizontalAlignment','center','Clipping','on');
text(x1,        y0-hgt*0.9, sprintf('%.3g',FI.hi),'Parent',ax,'FontSize',6,'Color',[.3 .3 .35],'HorizontalAlignment','center','Clipping','on');
end

% ---- flow-direction arrows: a train of chevrons marching along each line,
%      pointing in the real-power direction (animated by the timer) ---------
function drawFlowLayer(fig)
% ALL arrows live in a SINGLE patch object (N triangles via Faces/Vertices),
% updated in place every animation tick.  The old implementation deleted and
% re-created one patch PER ARROW per tick -- on a 57-bus system that was
% ~400 graphics objects destroyed + built 8x each second, which saturates
% the new desktop's pipeline (the jam that grew with system size).  Object
% churn per tick is now ZERO: one Vertices/Faces write, nothing else.
h = guidata(fig); ax = h.ax; NET = h.NET;
hp = getappdata(ax,'flowpatch');
if ~h.ED.flow || isempty(h.ED.pf) || ~isfield(h.ED.pf,'flowdir') || numel(h.ED.pf.flowdir) ~= nbr(NET)
    if ~isempty(hp) && ishghandle(hp), set(hp,'Faces',zeros(0,3)); end
    delete(findobj(ax,'Tag','flowarrow','Type','patch','-not','UserData','pool'));
    return;
end
% ---- adaptive arrow SIZE ------------------------------------------------
% base size follows the network's own component spacing (netunit); it is then
% shrunk for larger systems (many buses -> smaller arrows) and finally clamped
% to a sensible ON-SCREEN pixel size, so arrows read the same at any zoom level
% or canvas dimension.  A small S/M/L user factor still nudges it up or down.
span = curspan(h); u = netunit(NET, span);
nb = max(nbus(NET),1);
fN = min(1.0, max(0.45, sqrt(9/nb)));               % big systems -> smaller arrows
sc = 1.0; if isfield(h.ED,'arrowscale'), sc = h.ED.arrowscale; end
sz = 0.26*u*fN*sc;
% size clamp as a pure fraction of the view span (the old 4..18-px window on
% a typical canvas) -- NO Units/pixel queries here: this function runs at
% animation-timer rate, and axes-Units round-trips at 8 Hz destabilize the
% new desktop's layout pipeline.
vsp = max(max(diff(h.ED.xlim), diff(h.ED.ylim)), 1e-9);
sz = max(0.006*vsp, min(0.024*vsp, sz));
hw = 0.60*sz;
% ---- adaptive DENSITY ---------------------------------------------------
% one arrow on short lines, only a few on long lines; the count grows slowly
% with length relative to the average branch, so long feeders are not crowded
% and the arrow spacing scales automatically with line length.
Lsum = 0; Lc = 0;
for kk = 1:nbr(NET)
    Lk = hypot(NET.bx(NET.br_t(kk))-NET.bx(NET.br_f(kk)), NET.by(NET.br_t(kk))-NET.by(NET.br_f(kk)));
    if Lk > 0, Lsum = Lsum + Lk; Lc = Lc + 1; end
end
Lavg = 1; if Lc > 0, Lavg = Lsum/Lc; end
ph = getappdata(fig,'flowphase'); if isempty(ph), ph = 0; end
maxA = 600; drawn = 0;                               % hard cap: bound animation cost on huge nets
V = zeros(3*maxA, 3); F = zeros(maxA, 3);            % triangle pool (vertices are 3-D: z=2 layer)
for k = 1:nbr(NET)
    f = NET.br_f(k); t = NET.br_t(k);
    if h.ED.pf.flowdir(k) >= 0, x1=NET.bx(f); y1=NET.by(f); x2=NET.bx(t); y2=NET.by(t);
    else,                       x1=NET.bx(t); y1=NET.by(t); x2=NET.bx(f); y2=NET.by(f); end
    dx=x2-x1; dy=y2-y1; L=hypot(dx,dy); if L<1e-6, continue; end
    ux=dx/L; uy=dy/L; nx=-uy; ny=ux;
    nA = min(6, max(1, round(L/(1.7*Lavg))));       % fewer arrows on long lines
    for a = 0:nA-1
        frac = mod((a+ph)/nA, 1);                   % gentle marching glide
        d = (0.10 + 0.80*frac)*L;                   % keep arrows clear of the busbars
        px=x1+ux*d; py=y1+uy*d;                     % filled, tapered arrowhead
        b0 = 3*drawn;
        V(b0+1,:) = [px+ux*sz          py+uy*sz          2];
        V(b0+2,:) = [px-ux*sz*0.5+nx*hw py-uy*sz*0.5+ny*hw 2];
        V(b0+3,:) = [px-ux*sz*0.5-nx*hw py-uy*sz*0.5-ny*hw 2];
        drawn = drawn + 1; F(drawn,:) = [b0+1 b0+2 b0+3];
        if drawn >= maxA, break; end
    end
    if drawn >= maxA, break; end
end
if isempty(hp) || ~ishghandle(hp)                    % create the pool patch ONCE
    was = ishold(ax); hold(ax,'on');
    hp = patch('Parent',ax,'Vertices',zeros(0,3),'Faces',zeros(0,3), ...
        'FaceColor',h.C.flow,'EdgeColor','none','FaceAlpha',1.0, ...
        'Tag','flowarrow','UserData','pool','PickableParts','none');
    if ~was, hold(ax,'off'); end
    setappdata(ax,'flowpatch',hp);
end
set(hp,'Vertices',V(1:3*drawn,:),'Faces',F(1:drawn,:));   % ONE in-place update
end

% ---- re-entrancy guard -------------------------------------------------
% The flow-animation timer must never draw while a redraw or an analysis is
% running: its drawnow used to fire in the middle of redraw's cla and nest
% other callbacks, which could invalidate the figure handle (the "guidata:
% Object must be a figure" / DestroyedObject crash).  A small nesting counter
% kept in appdata marks every long operation "busy"; the timer bails while
% busy and can never nest another callback.
function n = busyCount(fig)
if ishghandle(fig) && isappdata(fig,'busyN'), n = getappdata(fig,'busyN'); else, n = 0; end
end
function b = isBusy(fig), b = busyCount(fig) > 0; end
function tf = busyBlock(fig)
% Click guard for the analysis buttons.  A silently-swallowed click during a
% long run reads as "the app is frozen"; saying WHY the click was ignored --
% and what to do about it -- keeps the interface honest while a run is active.
%
% SELF-HEALING: if a stop was requested (Stop pressed, or the workspace was
% switched) and the interface STILL reads busy well past the cooperative
% grace window, the previous run either wedged or died without running its
% cleanup -- the exact state that used to swallow every later click and
% read as "the app jammed".  Free the latch right here, tell the user, and
% let the very next click work.  The generation tag in forceIdle guarantees
% the freed run's late cleanup can never corrupt a newer run's busy mark.
tf = isBusy(fig);
if tf
    ts = getappdata(fig,'stopReqT');
    if userStopped() && ~isempty(ts) && (now*86400 - ts) > 5      %#ok<TNOW1>
        forceIdle(fig, 'previous run released (it never finished stopping) - press the button again to run');
        return;                                    % tf stays true: this click
    end                                            % freed the latch, the next one runs
    h = guidata(fig);
    if isstruct(h) && isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','a run is active - press Stop (or wait for it to finish) first');
    end
    % NO drawnow here: this can execute INSIDE the solver's event pump, and a
    % nested flush there is a known UI-deadlock path -- the message paints on
    % the pump's next tick anyway.
end
end
function c = beBusy(fig)
% mark a long operation as running.  The cleanup token is GENERATION-TAGGED:
% if the interface is force-freed while this run is still unwinding (double
% Reset, workspace-switch heal), the generation advances and this token's
% eventual cleanup becomes a no-op -- a force-free can therefore never eat
% the busy mark of a run started AFTER it.
g = getappdata(fig,'busyGen'); if isempty(g), g = 0; end
setappdata(fig,'busyN', busyCount(fig)+1);
c = onCleanup(@() unbusy(fig, g));
end
function unbusy(fig, gen)
if ~ishghandle(fig), return; end
g = getappdata(fig,'busyGen'); if isempty(g), g = 0; end
if nargin >= 2 && ~isequal(gen, g), return; end   % stale token from before a force-free
setappdata(fig,'busyN', max(0, busyCount(fig)-1));
end
function armFreshRun(fig)
% every Run entry arms a FRESH stop state: the stop flag + timestamp of the
% PREVIOUS run must never abort this run at its first poll (the "switch
% workspace, press Run, it instantly says stopped" symptom) and must never
% trigger the auto-heal against a run that is alive and healthy.
global PSDAT_STOP %#ok<GVMIS>
PSDAT_STOP = false;
try, setappdata(fig,'stopReqT', []); catch, end
end
function tf = runGate(fig, key)
% ONE-CLICK "reset first, then run" for the five Run buttons.
%   idle -> tf=false: the run proceeds immediately.
%   busy -> tf=true:  the click signals the cooperative STOP, remembers
%           WHICH run was requested, and the run-queue timer starts it the
%           moment the previous run releases (or after 8 s force-frees a
%           wedged latch).  The click is never swallowed; nothing can jam.
% Octave has no timers: there the click degrades honestly to "press Run
% again in a moment".
global PSDAT_STOP %#ok<GVMIS>
tf = isBusy(fig);
if ~tf, setappdata(fig,'pendingRun',''); return; end
PSDAT_STOP = true;
setappdata(fig,'stopReqT', now*86400);   %#ok<TNOW1>
setappdata(fig,'pendingRun', key);
h = guidata(fig);
nmm = struct('pf','power flow','ss','small-signal','td','time domain', ...
             'ds','POD design','sc','scenario');
if isstruct(h) && isfield(h,'status') && ishghandle(h.status)
    set(h.status,'String',['stopping the previous analysis - the ' nmm.(key) ...
        ' run starts automatically the moment it releases']);
end
tq = getappdata(fig,'runQ');
if ~isempty(tq) && isvalid(tq), return; end          % queue timer already alive
try
    tq = timer('Name','psdatRunQueue','ExecutionMode','fixedSpacing', ...
        'Period',0.30,'BusyMode','drop','TimerFcn',@(o,e) runQueueTick(fig));
    setappdata(fig,'runQ',tq); start(tq);
catch
    if isstruct(h) && isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','stopping the previous analysis - press Run again in a moment');
    end
end
end

function runQueueTick(fig)
% run-queue poller: waits for the old run to release, then dispatches the
% remembered Run.  Runs are dispatched from TIMER context -- the app's SAFE
% context for anything that opens figures (the same rule as deferFig).
try
    if ~ishghandle(fig), runQueueStop([]); return; end
    key = getappdata(fig,'pendingRun');
    if isempty(key), runQueueStop(fig); return; end
    if isBusy(fig)
        ts = getappdata(fig,'stopReqT');
        if ~isempty(ts) && (now*86400 - ts) > 8      %#ok<TNOW1>
            forceIdle(fig, 'previous run never released - starting the queued run');
        else
            return;                                   % keep waiting politely
        end
    end
    setappdata(fig,'pendingRun','');
    runQueueStop(fig);
    switch key
    case 'pf', onPF(fig,[]);
    case 'ss', onSS(fig,[]);
    case 'td', onTD(fig,[]);
    case 'ds', onDS(fig,[]);
    case 'sc', onSC(fig,[]);
    end
catch
end
end

function runQueueStop(fig)
try
    tq = [];
    if ~isempty(fig) && ishghandle(fig), tq = getappdata(fig,'runQ'); end
    if isempty(tq), tq = timerfindall('Name','psdatRunQueue'); end
    for q = 1:numel(tq)
        try, stop(tq(q)); catch, end
        try, delete(tq(q)); catch, end
    end
    if ~isempty(fig) && ishghandle(fig), setappdata(fig,'runQ',[]); end
catch
end
end

function forceIdle(fig, msg)
% the ONE recovery path back to a guaranteed-responsive interface: advance
% the busy generation (any still-unwinding run's cleanup turns into a
% no-op), zero the counter, hide the Stop button, say what happened.
if ~ishghandle(fig), return; end
g = getappdata(fig,'busyGen'); if isempty(g), g = 0; end
setappdata(fig,'busyGen', g+1);
setappdata(fig,'busyN', 0);
hideStop(fig);
if nargin >= 2 && ~isempty(msg)
    h = guidata(fig);
    if isstruct(h) && isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String',msg);
    end
end
end
function flowfree(fig)
if ishghandle(fig), setappdata(fig,'flowtick', 0); end
end
function tf = userStopped()
global PSDAT_STOP %#ok<GVMIS>
tf = ~isempty(PSDAT_STOP) && isequal(PSDAT_STOP, true);
end

% ---- Stop / Reset -------------------------------------------------------
% Stop is COOPERATIVE: it sets the shared PSDAT_STOP flag that the running
% ode15s OutputFcn (PSDAT_TimeDomain:odeStop) polls, so a long integration
% halts cleanly and keeps the partial result instead of being force-killed.
% Reset also clears the power-flow overlay, the report and the status line.
function showStop(fig)
global PSDAT_STOP %#ok<GVMIS>
PSDAT_STOP = false;                          % arm a fresh run
if ~ishghandle(fig), return; end
h = guidata(fig);
if isfield(h,'bStop') && ishghandle(h.bStop)
    set(h.bStop,'String',[char(9632) ' Stop'],'Enable','on','Visible','on');
end
drawnow limitrate;
end

function hideStop(fig)
if ~ishghandle(fig), return; end
h = guidata(fig);
if isfield(h,'bStop') && ishghandle(h.bStop), set(h.bStop,'Visible','off'); end
end

function onStop(src,~)                        %#ok<INUSD>
global PSDAT_STOP %#ok<GVMIS>
fig = gcbf; if isempty(fig) || ~ishghandle(fig), return; end
h = guidata(fig);
if ~isBusy(fig)                               % idle: an honest no-op
    PSDAT_STOP = false;
    if isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','nothing is running - Stop halts an active analysis and keeps its partial result');
    end
    return;
end
PSDAT_STOP = true;                            % the OutputFcn halts on its next poll
setappdata(fig,'stopReqT', now*86400);        %#ok<TNOW1> % arms busyBlock's auto-heal
if isfield(h,'bStop') && ishghandle(h.bStop), set(h.bStop,'String','stopping...','Enable','off'); end
if isfield(h,'status') && ishghandle(h.status)
    set(h.status,'String','stopping - the run will halt and keep the partial result');
end
end

function onReset(src,~)                        %#ok<INUSD>
global PSDAT_STOP %#ok<GVMIS>
PSDAT_STOP = true;                            % also cancel anything currently running
fig = gcbf; if isempty(fig) || ~ishghandle(fig), return; end
h = guidata(fig);
setappdata(fig,'pendingRun','');              % Reset also cancels any queued run
if isBusy(fig)                                % a run is active: just signal the stop
    % ESCAPE HATCH: a second Reset press within 2 s force-clears the busy
    % state.  If the busy counter ever wedged (a hard interrupt mid-callback),
    % every button would otherwise stay dead until MATLAB restarts -- this
    % guarantees the interface can ALWAYS be recovered from the app itself.
    tprev = getappdata(fig,'lastResetT'); tnow = now*86400; %#ok<TNOW1>
    setappdata(fig,'lastResetT', tnow);
    setappdata(fig,'stopReqT', tnow);          % arms busyBlock's auto-heal too
    if ~isempty(tprev) && (tnow - tprev) < 2
        forceIdle(fig, 'forced idle - the interface is back; any running result was discarded');
        return;
    end
    if isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','stopping the current run...  (press Reset again to force the interface free)');
    end
    return;
end
if isfield(h,'ED'), h.ED.pf = []; guidata(fig,h); end   % drop power-flow results/overlay
try, syncFlowTimer(fig); catch, end
try, setReport(fig,{'RESET'; ''; 'results and overlays cleared.'; 'run an analysis to populate this tab.'}); catch, end
if isfield(h,'status') && ishghandle(h.status), set(h.status,'String','reset - cleared results and overlays'); end
hideStop(fig);
try, redraw(fig); catch, end
end

function onFlowTick(fig)
try   % a tick must NEVER throw into timercb: its error bookkeeping races
      % timer deletion at app close ("Invalid or deleted object" in timercb)
if ~ishghandle(fig) || isBusy(fig), return; end
h = guidata(fig);
if ~isstruct(h) || ~isfield(h,'ED') || ~h.ED.flow || isempty(h.ED.pf), return; end
% Reentrancy latch for the ANIMATION ONLY -- deliberately NOT beBusy().  The
% tick below pumps drawnow, and a user click arriving during that pump runs
% its callback IMMEDIATELY, nested inside this tick.  If the tick held the
% global busy counter, that click would hit busyBlock and be swallowed with
% a false "a run is active" -- at ~12 ticks/s on a slow renderer that eats
% MOST clicks, and the whole app reads as jammed the moment the animation
% is on (i.e. right after a power flow).  The latch only stops a tick from
% re-entering itself; real user clicks land normally.
if isequal(getappdata(fig,'flowtick'), 1), return; end
setappdata(fig,'flowtick', 1);
lz = onCleanup(@() flowfree(fig));                      %#ok<NASGU>
ph = getappdata(fig,'flowphase'); if isempty(ph), ph = 0; end
setappdata(fig,'flowphase', mod(ph + 0.037, 1));        % gentle glide (scalar appdata,
tk = tic;                                               %  never a guidata write at 12 Hz)
try, drawFlowLayer(fig); drawnow limitrate; catch, end
% WATCHDOG: the animation must never be able to starve the UI.  If a tick
% runs slow three times in a row (a struggling renderer / huge system), the
% timer stops itself and the arrows stay as a static overlay -- the app
% remains fully responsive no matter what.  Toggle Arrows to re-enable.
el = toc(tk);
st = getappdata(fig,'flowslow'); if isempty(st), st = 0; end
if el > 0.45, st = st + 1; else, st = 0; end
setappdata(fig,'flowslow', st);
if st >= 3
    setappdata(fig,'flowslow', 0);
    try
        if isfield(h,'ftimer') && ~isempty(h.ftimer) && isvalid(h.ftimer), stop(h.ftimer); end
    catch
    end
    if isfield(h,'status') && ishghandle(h.status)
        set(h.status,'String','flow animation paused (renderer is slow here) - arrows stay static; toggle Arrows to re-enable');
    end
end
catch
end
end

function syncFlowTimer(fig)
h = guidata(fig);
if ~isfield(h,'ftimer') || isempty(h.ftimer) || ~isvalid(h.ftimer), return; end
runit = h.ED.flow && ~isempty(h.ED.pf);
if runit && strcmp(get(h.ftimer,'Running'),'off'), start(h.ftimer);
elseif ~runit && strcmp(get(h.ftimer,'Running'),'on'), stop(h.ftimer); end
end

function onCloseApp(src,~)
% ORDERLY teardown -- the new desktop delivers client events asynchronously,
% so everything that could still fire against this window is retired FIRST
% (animation timer, deferred-figure timers, queued callbacks), then the
% window is deleted.  Prevents the post-close "callback registered with
% ViewModel: Invalid or deleted object" echoes from the web controllers.
global PSDAT_STOP %#ok<GVMIS>
PSDAT_STOP = true;                               % end any cooperative run
h = guidata(src);
try
    if isfield(h,'ftimer') && ~isempty(h.ftimer) && isvalid(h.ftimer)
        stop(h.ftimer); delete(h.ftimer);
    end
catch
end
try
    tl = timerfindall('Name','psdatDeferredFigure');
    for q = 1:numel(tl), try, stop(tl(q)); catch, end, end
    try, delete(tl(isvalid(tl))); catch, end
catch
end
try
    tl = timerfindall('Name','psdatRunQueue');   % retire the run queue too
    for q = 1:numel(tl), try, stop(tl(q)); catch, end, end
    try, delete(tl(isvalid(tl))); catch, end
catch
end
try, setappdata(0,'PSDAT_noplot',0); catch, end
try, setappdata(0,'PSDAT_status',[]); catch, end
try, drawnow; catch, end                          % drain queued client events
delete(src);
end

% =========================================================================
%                          COMPONENT LIST
% =========================================================================
function refreshList(fig)
h = guidata(fig); NET = h.NET; S = {}; map = {}; tp = {'PQ','PV','slack'};
for i = 1:nbus(NET), S{end+1} = sprintf('Bus %-2d  %-5s', i, tp{NET.btype(i)}); map{end+1} = {'bus',i}; end
for k = 1:ngen(NET), S{end+1} = sprintf('Gen %-2d  %-7s @%d', k, NET.g_tag{k}, NET.g_bus(k)); map{end+1} = {'gen',k}; end
for k = 1:nbr(NET)
    tg = ''; if NET.br_tap(k)~=0, tg = ' (xfmr)'; end
    S{end+1} = sprintf('Line %-2d  %d-%d%s', k, NET.br_f(k), NET.br_t(k), tg); map{end+1} = {'branch',k};
end
for k = 1:nfac(NET)
    d = NET.facts(k);
    if isShuntFac(d.type), loc = sprintf('@%d',d.bus); else, loc = sprintf('%d-%d',d.f,d.t); end
    S{end+1} = sprintf('FACTS %-2d %-7s %s', k, d.type, loc); map{end+1} = {'facts',k}; %#ok<AGROW>
end
if isempty(S), S = {'(empty - draw or load a network)'}; end
if isfield(h,'list') && ishghandle(h.list)          % component list is now optional
    set(h.list,'String',S,'Value',min(max(get(h.list,'Value'),1),numel(S)));
end
h.listmap = map; guidata(fig,h);
end
function onList(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); v = get(src,'Value');
if ~isfield(h,'listmap') || v > numel(h.listmap), return; end
mp = h.listmap{v}; h.ED.selkind = mp{1}; h.ED.selidx = mp{2};
if strcmp(mp{1},'bus'), h.ED.selset = mp{2}; else, h.ED.selset = []; end
guidata(fig,h); syncReportSel(fig); showProps(fig); redraw(fig);
if strcmp(get(fig,'SelectionType'),'open')      % double-click -> zoom + properties
    zoomToSel(fig); setTab('props');
end
end

% =========================================================================
%                          PROPERTY INSPECTOR
% =========================================================================
function showProps(fig)
h = guidata(fig); NET = h.NET; kind = h.ED.selkind; i = h.ED.selidx;
for j = 1:5, set(h.pEdLab{j},'String',''); set(h.pEd{j},'String','','Visible','off'); end
set([h.pTypeLab h.pType],'Visible','off'); set(h.pBtnMD,'Visible','off');
if isfield(h,'pInfo') && ishghandle(h.pInfo), set(h.pInfo,'Visible','off'); end
set([h.pApply h.pDel],'Visible','on'); set(h.pHelp,'String','');
if numel(h.ED.selset) > 1
    set(h.pTitle,'String',sprintf('%d buses selected',numel(h.ED.selset)));
    set([h.pApply h.pDel],'Visible','off');
    set(h.pHelp,'String',sprintf(['%d buses box-selected.\n\nUse Edit > Arrange... ' ...
        '(align / distribute / rotate / flip) in the ribbon to ' ...
        'arrange them together.\n\nClick one component to edit its properties.'],numel(h.ED.selset)));
    return;
end
switch kind
case 'bus'
    set(h.pTitle,'String',sprintf('Bus %d',i));
    set([h.pTypeLab h.pType],'Visible','on'); set(h.pTypeLab,'String','Bus type');
    set(h.pType,'String',{'slack','PV','PQ'},'Value', 4-NET.btype(i));
    showRows(h,{'V set (pu)',NET.Vset(i); 'P load (MW)',NET.Pd(i); 'Q load (MVAr)',NET.Qd(i); 'Shunt B (MVAr)',NET.Bs(i)});
    set(h.pHelp,'String','Slack sets the reference angle; PV holds |V|; PQ is a load bus. A generator bus is auto-set to PV (first one to slack).');
case 'gen'
    set(h.pTitle,'String',sprintf('Generator %d  @ bus %d',i,NET.g_bus(i)));
    set([h.pTypeLab h.pType],'Visible','on'); set(h.pTypeLab,'String','Unit type');
    iv = find(strcmp(h.UNITS,NET.g_tag{i}),1); if isempty(iv), iv = 1; end
    set(h.pType,'String',h.UNITS,'Value',iv);
    showRows(h,{'P gen (MW)',NET.g_Pg(i); 'V set (pu)',NET.g_Vset(i); 'Rating S (MVA)',NET.g_S(i)});
    set(h.pBtnMD,'Visible','on','String','Machine data...','Callback',@onEditMachine);
    set(h.pHelp,'String','Choose any unit model (SG family, GFM/GFL, PV, BESS, wind 1-4). "Machine data..." edits the 25 synchronous-machine parameters; converters use validated defaults.');
case 'branch'
    tg = 'Line'; if NET.br_tap(i)~=0, tg = 'Transformer'; end
    set(h.pTitle,'String',sprintf('%s %d   (bus %d - %d)',tg,i,NET.br_f(i),NET.br_t(i)));
    showRows(h,{'R (pu)',NET.br_r(i); 'X (pu)',NET.br_x(i); 'B charge (pu)',NET.br_b(i); 'Tap (0 = line)',NET.br_tap(i)});
    set(h.pHelp,'String','Series R + jX and total line charging B (pu on 100 MVA). A non-zero tap makes it an off-nominal transformer.');
case 'load'
    set(h.pTitle,'String',sprintf('Load @ bus %d',i));
    showRows(h,{'P load (MW)',NET.Pd(i); 'Q load (MVAr)',NET.Qd(i)});
    set(h.pDel,'Visible','off');
    Pl = NET.Pd(i); Ql = NET.Qd(i); Sl = hypot(Pl,Ql);
    pf = 1; if Sl > 1e-9, pf = Pl/Sl; end
    vtxt = '(run power flow)'; atxt = '--'; itxt = '--';
    if ~isempty(h.ED.pf) && isfield(h.ED.pf,'V') && numel(h.ED.pf.V) >= i
        Vv = h.ED.pf.V(i); ang = h.ED.pf.th(i); Ipu = Sl/100/max(Vv,1e-6);
        vtxt = sprintf('%.4f pu',Vv); atxt = sprintf('%.2f deg',ang); itxt = sprintf('%.3f pu',Ipu);
    end
    st = 'in service'; if Sl < 1e-9, st = 'off'; end
    set(h.pHelp,'String',sprintf(['Load ID      L%d\nname         Load-%d\nbus          %d\n' ...
        'P            %.2f MW\nQ            %.2f MVAr\n|V|          %s\nangle        %s\n' ...
        'current      %s\npower factor %.3f %s\nstatus       %s'], ...
        i, i, i, Pl, Ql, vtxt, atxt, itxt, pf, tern(Ql>=0,'lag','lead'), st));
case 'facts'
    d = NET.facts(i); ty = upper(d.type);
    set(h.pBtnMD,'Visible','on','String','FACTS parameters...','Callback',@onEditFacts);
    if isShuntFac(ty)
        set(h.pTitle,'String',sprintf('%s  @ bus %d',ty,d.bus));
        if strcmp(ty,'SVC'), lim = {'Bmax (pu)',d.Bmax; 'Bmin (pu)',d.Bmin};
        else, lim = {'Imax (pu)',d.Imax; 'Imin (pu)',d.Imin}; end
        showRows(h,[{'V ref (pu)',d.Vref}; lim; {'gain Kr',d.Kr}]);
        set(h.pHelp,'String','Shunt compensator holding its bus voltage. "FACTS parameters..." opens the full editor incl. the supplementary POD / wide-area damping controller.');
    elseif isSeriesFac(ty)
        set(h.pTitle,'String',sprintf('%s  line %d-%d',ty,d.f,d.t));
        showRows(h,{'comp kcomp',d.kcomp; 'kmin',d.kmin; 'kmax',d.kmax; 'Tc (s)',d.Tc});
        hh = 'Series compensation (x_eff = x*(1-kcomp)).'; if any(strcmp(ty,{'TCSC','SSSC'})), hh = [hh ' "FACTS parameters..." adds the Vse limit + POD controller.']; end
        set(h.pHelp,'String',hh);
    elseif strcmp(ty,'UPFC')
        pq = strcmpi(valOr(d.mode,'comp'),'pq');
        set(h.pTitle,'String',sprintf('UPFC  bus %d + line %d-%d  [%s]',d.bus,d.f,d.t,tern(pq,'P-Q','comp')));
        if pq, showRows(h,{'V ref (pu)',d.Vref; 'P set (MW)',valOr(d.Pset,50); 'Q set (MVAr)',valOr(d.Qset,0)});
        else,  showRows(h,{'V ref (pu)',d.Vref; 'comp kcomp',d.kcomp; 'Vse max (pu)',d.Vsemax}); end
        set(h.pHelp,'String','UPFC = shunt (holds V) + series, DC-coupled. Switch composition <-> P-Q flow control (set line P and Q independently) and edit every parameter incl. the POD via "FACTS parameters...".');
    else
        pq = strcmpi(valOr(d.mode,'comp'),'pq');
        set(h.pTitle,'String',sprintf('IPFC  line %d-%d + %d-%d  [%s]',d.f,d.t,valOr(d.f2,0),valOr(d.t2,0),tern(pq,'P-Q','comp')));
        if pq, showRows(h,{'P1 set (MW)',valOr(d.P1set,80); 'Q1 set (MVAr)',valOr(d.Q1set,10); 'Q2 set (MVAr)',valOr(d.Q2set,5); 'line2 to bus',valOr(d.t2,0)});
        else,  showRows(h,{'comp kcomp',d.kcomp; 'kcomp2',d.kcomp2; 'line2 from bus',valOr(d.f2,0); 'line2 to bus',valOr(d.t2,0)}); end
        set(h.pHelp,'String','IPFC = two DC-coupled series converters. Switch composition <-> P-Q: the master line holds P1 and Q1, the slave holds Q2 and supplies the balancing real power via the DC link. Set line 2 + full parameters via "FACTS parameters...".');
    end
otherwise
    set(h.pTitle,'String','Properties'); set([h.pApply h.pDel],'Visible','off');
    set(h.pHelp,'String','Select a component on the canvas or in the list to edit it, or pick a tool to add one.');
end
% every real component carries a THEORY CARD (equations, states, parameters,
% references) -- the educational mode's entry point lives with the editor
if any(strcmp(kind,{'bus','gen','branch','load','facts'})) && ...
        isfield(h,'pInfo') && ishghandle(h.pInfo)
    set(h.pInfo,'Visible','on');
end
end
function v = valOr(x,dflt), if isempty(x), v = dflt; else, v = x; end, end
function showRows(h,fields)
for j = 1:size(fields,1)
    set(h.pEdLab{j},'String',fields{j,1}); set(h.pEd{j},'String',num2str(fields{j,2},'%g'),'Visible','on');
end
end
function onPropType(src,~), if busyBlock(gcbf), return; end, onApply(src,[]); end
function onApply(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); kind = h.ED.selkind; i = h.ED.selidx;
if ~any(strcmp(kind,{'bus','gen','branch','load','facts'})), return; end
h = pushUndo(h); NET = h.NET; gv = @(j) str2double(get(h.pEd{j},'String'));
switch kind
case 'bus'
    NET.btype(i) = 4-get(h.pType,'Value');
    if ~isnan(gv(1)), NET.Vset(i) = gv(1); end
    if ~isnan(gv(2)), NET.Pd(i)  = gv(2); end
    if ~isnan(gv(3)), NET.Qd(i)  = gv(3); end
    if ~isnan(gv(4)), NET.Bs(i)  = gv(4); end
case 'gen'
    NET.g_tag{i} = h.UNITS{get(h.pType,'Value')};
    if ~isnan(gv(1)), NET.g_Pg(i)   = gv(1); end
    if ~isnan(gv(2)), NET.g_Vset(i) = gv(2); end
    if ~isnan(gv(3)), NET.g_S(i)    = gv(3); end
case 'branch'
    if ~isnan(gv(1)), NET.br_r(i)   = gv(1); end
    if ~isnan(gv(2)), NET.br_x(i)   = gv(2); end
    if ~isnan(gv(3)), NET.br_b(i)   = gv(3); end
    if ~isnan(gv(4)), NET.br_tap(i) = gv(4); end
case 'load'
    if ~isnan(gv(1)), NET.Pd(i) = gv(1); end
    if ~isnan(gv(2)), NET.Qd(i) = gv(2); end
case 'facts'
    ty = upper(NET.facts(i).type);
    if isShuntFac(ty)
        if ~isnan(gv(1)), NET.facts(i).Vref = gv(1); end
        if strcmp(ty,'SVC')
            if ~isnan(gv(2)), NET.facts(i).Bmax = gv(2); end
            if ~isnan(gv(3)), NET.facts(i).Bmin = gv(3); end
        else
            if ~isnan(gv(2)), NET.facts(i).Imax = gv(2); end
            if ~isnan(gv(3)), NET.facts(i).Imin = gv(3); end
        end
        if ~isnan(gv(4)), NET.facts(i).Kr = gv(4); end
    elseif isSeriesFac(ty)
        if ~isnan(gv(1)), NET.facts(i).kcomp = gv(1); end
        if ~isnan(gv(2)), NET.facts(i).kmin  = gv(2); end
        if ~isnan(gv(3)), NET.facts(i).kmax  = gv(3); end
        if ~isnan(gv(4)), NET.facts(i).Tc    = gv(4); end
    elseif strcmp(ty,'UPFC')
        pq = strcmpi(valOr(NET.facts(i).mode,'comp'),'pq');
        if ~isnan(gv(1)), NET.facts(i).Vref = gv(1); end
        if pq
            if ~isnan(gv(2)), NET.facts(i).Pset = gv(2); end
            if ~isnan(gv(3)), NET.facts(i).Qset = gv(3); end
        else
            if ~isnan(gv(2)), NET.facts(i).kcomp  = gv(2); end
            if ~isnan(gv(3)), NET.facts(i).Vsemax = gv(3); end
        end
    else                                              % IPFC
        pq = strcmpi(valOr(NET.facts(i).mode,'comp'),'pq');
        if pq
            if ~isnan(gv(1)), NET.facts(i).P1set = gv(1); end
            if ~isnan(gv(2)), NET.facts(i).Q1set = gv(2); end
            if ~isnan(gv(3)), NET.facts(i).Q2set = gv(3); end
            t2 = gv(4);
            if ~isnan(t2) && t2>=1 && t2<=nbus(NET), NET.facts(i).t2 = round(t2); else, NET.facts(i).t2 = 0; end
            NET.facts(i).f2 = NET.facts(i).f;    % converters share the common sending bus
        else
            if ~isnan(gv(1)), NET.facts(i).kcomp  = gv(1); end
            if ~isnan(gv(2)), NET.facts(i).kcomp2 = gv(2); end
            f2 = gv(3); t2 = gv(4);
            if ~isnan(f2) && f2>=1 && f2<=nbus(NET), NET.facts(i).f2 = round(f2); else, NET.facts(i).f2 = 0; end
            if ~isnan(t2) && t2>=1 && t2<=nbus(NET), NET.facts(i).t2 = round(t2); else, NET.facts(i).t2 = 0; end
        end
    end
end
h.NET = NET; guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
if strcmp(kind,'facts'), factsImpact(fig, sprintf('%s updated', upper(NET.facts(i).type)), i);
else, autoPF(fig, 'properties applied'); end
end
function onDelSel(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if numel(h.ED.selset) > 1
    h = pushUndo(h); s = sort(h.ED.selset,'descend');
    for i = s, h.NET = delBus(h.NET,i); end
    h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
elseif any(strcmp(h.ED.selkind,{'bus','gen','branch','facts'}))
    h = pushUndo(h); h = deleteElement(h,h.ED.selkind,h.ED.selidx);
else
    return;
end
guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
end

% =========================================================================
%                       UNDO / REDO / VIEW / ARRANGE
% =========================================================================
function onUndo(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if isempty(h.ED.undo), set(h.status,'String','nothing to undo'); return; end
h.ED.redo{end+1} = h.NET; h.NET = h.ED.undo{end}; h.ED.undo(end) = [];
h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
h = bumprev(h);
guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
autoPF(fig,'undo');
end
function onRedo(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if isempty(h.ED.redo), set(h.status,'String','nothing to redo'); return; end
h.ED.undo{end+1} = h.NET; h.NET = h.ED.redo{end}; h.ED.redo(end) = [];
h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
h = bumprev(h);
guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
autoPF(fig,'redo');
end

function onTab(src,~), setTab(get(src,'UserData')); end   % visibility-only: never blocked
function onZoom(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); f = get(src,'UserData');
cx = mean(h.ED.xlim); cy = mean(h.ED.ylim);
wx = diff(h.ED.xlim)*f/2; wy = diff(h.ED.ylim)*f/2;
h.ED.xlim = [cx-wx cx+wx]; h.ED.ylim = [cy-wy cy+wy];
guidata(fig,h); redraw(fig);
end
function onZoomSel(src,~), if busyBlock(gcbf), return; end, zoomToSel(gcbf); end
function onSelTool(src,~), setTool(gcbf,'select'); end   %#ok<INUSD> % always reachable
function onZoomArea(src,~)                     %#ok<INUSD>
% arm the one-shot rubber-band zoom: the NEXT press-drag-release on the
% canvas zooms into the dragged rectangle, then the previous tool resumes
if busyBlock(gcbf), return; end
fig = gcbf; h = guidata(fig);
h.ED.zoomarm = true; h.ED.zoomrect = false;
guidata(fig,h);
if isfield(h,'status') && ishghandle(h.status)
    set(h.status,'String','zoom: drag a rectangle over the area to magnify (a plain click steps in)');
end
end
function onWheel(src,ev)
% Mouse-wheel / two-finger zoom about the cursor -- the standard CAD gesture.
% Pure data-space math: NO Units toggling in this high-rate path (that class
% of churn destabilizes the new desktop).  Full redraws are throttled to
% ~8/s; between them only the axes limits move (instant), so a fast trackpad
% burst stays fluid and glyphs re-scale on the next full pass.
fig = src;
if isBusy(fig), return; end
h = guidata(fig);
if ~isstruct(h) || ~isfield(h,'ED') || ~isfield(h,'ax') || ~ishghandle(h.ax), return; end
q = get(h.ax,'CurrentPoint'); px = q(1,1); py = q(1,2);
xl = h.ED.xlim; yl = h.ED.ylim;
if px < xl(1) || px > xl(2) || py < yl(1) || py > yl(2)
    % over a side panel: if it is the left palette in its short-window
    % scroll mode, the wheel scrolls IT (the natural gesture); else ignore.
    cp = get(fig,'CurrentPoint');              % figure Units are normalized
    if cp(1) >= .004 && cp(1) <= .179 && cp(2) >= .046 && cp(2) <= .798
        palWheel(fig, h, double(ev.VerticalScrollCount));
    end
    return;
end
f = 1.16^double(ev.VerticalScrollCount);       % scroll up = in, down = out
fs = max(diff(xl), 200);
if isfield(h.ED,'fitspan') && ~isempty(h.ED.fitspan) && h.ED.fitspan > 0, fs = h.ED.fitspan; end
ns = diff(xl)*f;
if ns < fs/60 || ns > fs*8, return; end        % sane zoom range either way
h.ED.xlim = px + (xl - px)*f;                  % the point under the cursor stays put
h.ED.ylim = py + (yl - py)*f;
guidata(fig,h);
tprev = getappdata(fig,'wheelT'); tnow = now*86400;   %#ok<TNOW1>
if isempty(tprev) || tnow - tprev > 0.12
    setappdata(fig,'wheelT',tnow); redraw(fig);
else
    set(h.ax,'XLim',h.ED.xlim,'YLim',h.ED.ylim);      % instant, cheap between redraws
end
end
function zoomToSel(fig)
% centre + zoom the view on the current selection (bus set, bus, generator,
% or line) -- the "Zoom to Selected Component" function
h = guidata(fig); NET = h.NET; X = []; Y = [];
if numel(h.ED.selset) >= 1
    X = NET.bx(h.ED.selset); Y = NET.by(h.ED.selset);
elseif strcmp(h.ED.selkind,'bus') && h.ED.selidx>=1
    X = NET.bx(h.ED.selidx); Y = NET.by(h.ED.selidx);
elseif strcmp(h.ED.selkind,'gen') && h.ED.selidx>=1
    k = h.ED.selidx; X = [NET.gx(k); NET.bx(NET.g_bus(k))]; Y = [NET.gy(k); NET.by(NET.g_bus(k))];
elseif strcmp(h.ED.selkind,'branch') && h.ED.selidx>=1
    k = h.ED.selidx; X = [NET.bx(NET.br_f(k)); NET.bx(NET.br_t(k))]; Y = [NET.by(NET.br_f(k)); NET.by(NET.br_t(k))];
elseif strcmp(h.ED.selkind,'load') && h.ED.selidx>=1
    i = h.ED.selidx; sp2 = netunit(NET, max([diff(h.ED.xlim) diff(h.ED.ylim) 200]));
    X = [NET.bx(i); NET.bx(i)]; Y = [NET.by(i); NET.by(i)+0.85*sp2];
end
if isempty(X), fitView(fig); redraw(fig); return; end
sp = netunit(NET, max([diff(h.ED.xlim) diff(h.ED.ylim) 200]));
mx = max([max(X)-min(X), max(Y)-min(Y)])*0.6 + 4*sp;    % pad so the glyph + labels fit
cx = (min(X)+max(X))/2; cy = (min(Y)+max(Y))/2;
h.ED.xlim = [cx-mx cx+mx]; h.ED.ylim = [cy-mx cy+mx];
guidata(fig,h); redraw(fig);
end
function onFit(src,~)
if busyBlock(gcbf), return; end
fig = gcbf;
try   % refresh the cached figure pixel size (user-invoked: safe moment)
    uu = get(fig,'Units'); set(fig,'Units','pixels'); fp0 = get(fig,'Position'); set(fig,'Units',uu);
    setappdata(fig,'figpx', fp0(3:4));
catch
end
fitView(fig); redraw(fig);
end
function fitView(fig)
h = guidata(fig); NET = h.NET;
if nbus(NET) == 0, h.ED.xlim=[0 1000]; h.ED.ylim=[-680 20]; guidata(fig,h); return; end
X = [NET.bx; NET.gx]; Y = [NET.by; NET.gy];
mx = 0.12*max([max(X)-min(X), max(Y)-min(Y), 200]);
h.ED.xlim = [min(X)-mx max(X)+mx]; h.ED.ylim = [min(Y)-mx max(Y)+1.6*mx];
h.ED.fitspan = max([diff(h.ED.xlim), diff(h.ED.ylim), 200]);   % zoom reference for adaptive label fonts
guidata(fig,h);
end

function onBeautify(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if nbus(h.NET) < 2, return; end
h = pushUndo(h); XY = force_layout(h.NET);
% rescale into the current world extent, then snap to a grid so the result
% reads as an orderly schematic (mirrors the Python "Beautify: snap to grid")
xl = h.ED.xlim; yl = h.ED.ylim;
XY(:,1) = rescale_col(XY(:,1), xl(1)+0.10*diff(xl), xl(2)-0.10*diff(xl));
XY(:,2) = rescale_col(XY(:,2), yl(1)+0.28*diff(yl), yl(2)-0.12*diff(yl));
g = 0.5*max([diff(xl) diff(yl)])/12;          % tidy grid pitch
XY = round(XY/g)*g;
h.NET.bx = XY(:,1); h.NET.by = XY(:,2); h = rederive_gens(h);
guidata(fig,h); redraw(fig); set(h.status,'String','auto-arranged (untangled + snapped to grid)');
end
function c = rescale_col(c, lo, hi)
a = min(c); b = max(c); if b-a < 1e-9, c = (lo+hi)/2*ones(size(c)); else, c = lo + (c-a)/(b-a)*(hi-lo); end
end
function XY = force_layout(NET)
n = nbus(NET); a = linspace(0,2*pi,n+1); a(end) = [];
XY = [cos(a(:)) sin(a(:))]*(0.5*sqrt(n));
E = [NET.br_f(:) NET.br_t(:)]; k = 1.0; k2 = k*k;
for it = 1:250
    dx = bsxfun(@minus, XY(:,1), XY(:,1).'); dy = bsxfun(@minus, XY(:,2), XY(:,2).');
    d2 = dx.^2 + dy.^2; d2(1:n+1:end) = inf;
    dsp = [sum(k2.*dx./d2, 2), sum(k2.*dy./d2, 2)];
    for e = 1:size(E,1)
        i = E(e,1); j = E(e,2); vx = XY(i,1)-XY(j,1); vy = XY(i,2)-XY(j,2);
        f = sqrt(vx*vx+vy*vy)/k; dsp(i,:) = dsp(i,:) - [vx vy]*f; dsp(j,:) = dsp(j,:) + [vx vy]*f;
    end
    temp = 0.1*sqrt(n)*(1 - it/250) + 0.01; dl = sqrt(sum(dsp.^2,2)); dl(dl<1e-9) = 1;
    XY = XY + bsxfun(@times, dsp, min(dl,temp)./dl);
end
XY = bsxfun(@minus, XY, mean(XY,1));
end

% =========================================================================
%          PROFESSIONAL GRAPH LAYOUTS + ARRANGE COMMANDS (Layout menu)
% =========================================================================
function onLayout(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); v = get(src,'Value'); set(src,'Value',1);
if v < 2 || nbus(h.NET) < 1, return; end
NET = h.NET; XY = []; snap = false; msg = '';
switch v
case 2,  [XY,msg] = lay_auto(NET);
case 3,  XY = lay_fr(NET);        msg = 'force-directed (Fruchterman-Reingold)';
case 4,  XY = lay_hier(NET,0);    msg = 'hierarchical (Sugiyama / layered)';
case 5,  XY = lay_tree(NET);      msg = 'tree';
case 6,  XY = lay_radial(NET);    msg = 'radial';
case 7,  XY = lay_circular(NET);  msg = 'circular';
case 8,  XY = lay_grid(NET);      msg = 'grid';
case 9,  XY = lay_fr(NET); snap = true;   msg = 'orthogonal (grid-snapped)';
case 10, XY = lay_kk(NET);        msg = 'Kamada-Kawai / stress majorization';
case 11, XY = lay_hier(NET,1);    msg = 'electrical (layered from slack)';
case 12, XY = lay_fr(NET); snap = true;   msg = 'beautified (untangled + snapped)';
case 13, writeXY(fig, cmd_barycenter(NET), 'minimized line crossings'); return;
case 14, writeXY(fig, cmd_equal(NET),      'equalized bus spacing');    return;
case 15, writeXY(fig, cmd_straighten(NET), 'straightened transmission lines'); return;
case 16, writeXY(fig, cmd_scale(NET,0.82), 'compacted layout');         return;
case 17, writeXY(fig, cmd_scale(NET,1.20), 'expanded layout');          return;
case 18
    if isfield(h.ED,'homeXY') && size(h.ED.homeXY,1)==nbus(NET)
        writeXY(fig, h.ED.homeXY, 'restored default layout');
    else
        writeXY(fig, lay_fr(NET), 'no saved default - applied a clean force-directed layout');
    end
    return;
end
if isempty(XY), return; end
applyXY(fig, XY, snap, msg);
end

function applyXY(fig, XY, snap, msg)
% place a normalized layout into the current world extent (+ optional grid snap)
h = guidata(fig); h = pushUndo(h);
xl = h.ED.xlim; yl = h.ED.ylim;
XY(:,1) = rescale_col(XY(:,1), xl(1)+0.10*diff(xl), xl(2)-0.10*diff(xl));
XY(:,2) = rescale_col(XY(:,2), yl(1)+0.26*diff(yl), yl(2)-0.12*diff(yl));
if snap, g = 0.5*max([diff(xl) diff(yl)])/12; XY = round(XY/g)*g; end
h.NET.bx = XY(:,1); h.NET.by = XY(:,2); h = rederive_gens(h);
guidata(fig,h); redraw(fig); set(h.status,'String',['layout: ' msg]);
end
function writeXY(fig, XY, msg)
% write world coordinates directly (used by the in-place arrange commands)
h = guidata(fig); h = pushUndo(h);
h.NET.bx = XY(:,1); h.NET.by = XY(:,2); h = rederive_gens(h);
guidata(fig,h); redraw(fig); set(h.status,'String',msg);
end
function h = rederive_gens(h)
% every attached glyph follows a rewritten geometry: machines AND FACTS
sp = netspan(h.NET);
for k = 1:ngen(h.NET)
    ib = h.NET.g_bus(k); h.NET.gx(k) = h.NET.bx(ib); h.NET.gy(k) = h.NET.by(ib) - 0.10*sp;
end
h.NET = refacts(h.NET, []);
end

% ---- graph helpers (Octave-safe: no graph/digraph objects) --------------
function A = lay_adj(NET)
n = nbus(NET); A = zeros(n);
for k = 1:nbr(NET)
    i = NET.br_f(k); j = NET.br_t(k);
    if i>=1 && j>=1 && i<=n && j<=n, A(i,j)=1; A(j,i)=1; end
end
end
function r = lay_root(NET)
r = find(NET.btype==3,1);
if isempty(r), d = sum(lay_adj(NET),2); [~,r] = max(d); end
if isempty(r), r = 1; end
end
function [lev,ord,par] = lay_bfs(NET)
n = nbus(NET); A = lay_adj(NET); r = lay_root(NET);
lev = -ones(n,1); par = zeros(n,1); ord = []; q = r; lev(r) = 0; head = 1;
while head <= numel(q)
    c = q(head); head = head+1; ord(end+1) = c; %#ok<AGROW>
    nb = find(A(c,:)>0);
    for j = nb, if lev(j) < 0, lev(j)=lev(c)+1; par(j)=c; q(end+1)=j; end, end %#ok<AGROW>
end
rem = find(lev<0); mx = max(lev);
for j = rem(:)', mx = mx+1; lev(j) = mx; ord(end+1) = j; end %#ok<AGROW>
end
function D = lay_apsp(NET)
n = nbus(NET); A = lay_adj(NET); D = inf(n);
for s = 1:n
    d = inf(n,1); d(s) = 0; q = s; head = 1;
    while head <= numel(q)
        c = q(head); head = head+1; nb = find(A(c,:)>0);
        for j = nb, if isinf(d(j)), d(j)=d(c)+1; q(end+1)=j; end, end %#ok<AGROW>
    end
    D(s,:) = d.';
end
D(1:n+1:end) = 0;
end

% ---- layout algorithms (return normalized XY, n x 2) --------------------
function XY = lay_fr(NET), XY = force_layout(NET); end
function XY = lay_circular(NET)
n = nbus(NET); [~,ord] = lay_bfs(NET); a = zeros(n,1);
for p = 1:n, a(ord(p)) = 2*pi*(p-1)/n; end
XY = [cos(a) sin(a)];
end
function XY = lay_grid(NET)
n = nbus(NET); [~,ord] = lay_bfs(NET); c = ceil(sqrt(n)); XY = zeros(n,2);
for p = 1:n, i = ord(p); XY(i,:) = [mod(p-1,c), -floor((p-1)/c)]; end
end
function XY = lay_hier(NET, elec)
n = nbus(NET); [lev,~,~] = lay_bfs(NET); XY = zeros(n,2); levs = unique(lev);
for li = 1:numel(levs)
    idx = find(lev==levs(li));
    for m = 1:numel(idx), XY(idx(m),1) = m-1-(numel(idx)-1)/2; end
    XY(idx,2) = -levs(li);
end
A = lay_adj(NET);
for sweep = 1:4
    for li = 1:numel(levs)
        idx = find(lev==levs(li)); if numel(idx) < 2, continue; end
        bc = zeros(numel(idx),1);
        for m = 1:numel(idx)
            nb = find(A(idx(m),:)>0);
            if isempty(nb), bc(m) = XY(idx(m),1); else, bc(m) = mean(XY(nb,1)); end
        end
        xs = sort(XY(idx,1)); [~,so] = sort(bc); XY(idx(so),1) = xs;
    end
end
if elec, XY(:,2) = -XY(:,2); end
end
function XY = lay_tree(NET)
n = nbus(NET); [lev,~,par] = lay_bfs(NET); XY = zeros(n,2);
kids = cell(n,1); for i = 1:n, if par(i)>0, kids{par(i)}(end+1) = i; end, end %#ok<AGROW>
xcur = 0;
for li = max(lev):-1:0
    idx = find(lev==li);
    for m = 1:numel(idx)
        i = idx(m);
        if isempty(kids{i}), XY(i,1) = xcur; xcur = xcur+1; else, XY(i,1) = mean(XY(kids{i},1)); end
    end
end
% guarantee no two nodes overlap within a level (spread to >=1 apart, keep order)
for li = 0:max(lev)
    idx = find(lev==li); if numel(idx) < 2, continue; end
    [~,so] = sort(XY(idx,1)); sidx = idx(so);
    for m = 2:numel(sidx)
        if XY(sidx(m),1) < XY(sidx(m-1),1) + 1, XY(sidx(m),1) = XY(sidx(m-1),1) + 1; end
    end
    XY(idx,1) = XY(idx,1) - mean(XY(idx,1));
end
XY(:,2) = -lev;
end
function XY = lay_radial(NET)
n = nbus(NET); [lev,~,~] = lay_bfs(NET); XY = zeros(n,2); levs = unique(lev);
for li = 1:numel(levs)
    idx = find(lev==levs(li)); L = levs(li); m = numel(idx);
    if L == 0, XY(idx,:) = 0; continue; end
    for p = 1:m, a = 2*pi*(p-1)/m; XY(idx(p),:) = L*[cos(a) sin(a)]; end
end
end
function XY = lay_kk(NET)
n = nbus(NET); if n < 2, XY = zeros(n,2); return; end
D = lay_apsp(NET); fin = D(~isinf(D)); mx = max([fin(:); 1]); D(isinf(D)) = mx+1;
a = linspace(0,2*pi,n+1); a(end) = []; XY = [cos(a(:)) sin(a(:))]*0.5*sqrt(n);
W = 1./(D.^2); W(1:n+1:end) = 0;
for it = 1:80
    Xn = zeros(n,2);
    for i = 1:n
        num = [0 0]; den = 0;
        for j = 1:n
            if j == i, continue; end
            dx = XY(i,1)-XY(j,1); dy = XY(i,2)-XY(j,2); dij = hypot(dx,dy); if dij < 1e-9, dij = 1e-9; end
            num = num + W(i,j)*(XY(j,:) + D(i,j)*[dx dy]/dij); den = den + W(i,j);
        end
        if den > 0, Xn(i,:) = num/den; else, Xn(i,:) = XY(i,:); end
    end
    XY = Xn;
end
XY = bsxfun(@minus, XY, mean(XY,1));
end
function [XY,msg] = lay_auto(NET)
n = nbus(NET); e = nbr(NET);
if n <= 2, XY = lay_grid(NET); msg = 'auto -> grid'; return; end
[lev,~,~] = lay_bfs(NET); connected = all(lev >= 0);
if connected && e == n-1, XY = lay_tree(NET); msg = 'auto -> tree'; return; end
if n <= 10, XY = lay_circular(NET); msg = 'auto -> circular'; return; end
if 2*e/max(n,1) >= 3.5, XY = lay_hier(NET,1); msg = 'auto -> hierarchical'; return; end
XY = lay_fr(NET); msg = 'auto -> force-directed';
end

% ---- in-place arrange commands (operate on current world coords) --------
function XY = cmd_barycenter(NET)
n = nbus(NET); XY = [NET.bx(:) NET.by(:)]; A = lay_adj(NET); ys = XY(:,2);
tol = 0.06*max(max(ys)-min(ys),1); [~,ord] = sort(ys); rowid = zeros(n,1); rid = 1; rowid(ord(1)) = 1;
for p = 2:n, if ys(ord(p))-ys(ord(p-1)) > tol, rid = rid+1; end, rowid(ord(p)) = rid; end
for r = 1:max(rowid)
    idx = find(rowid==r); if numel(idx) < 2, continue; end
    bc = zeros(numel(idx),1);
    for m = 1:numel(idx)
        nb = find(A(idx(m),:)>0);
        if isempty(nb), bc(m) = XY(idx(m),1); else, bc(m) = mean(XY(nb,1)); end
    end
    xs = sort(XY(idx,1)); [~,so] = sort(bc); XY(idx(so),1) = xs;
end
end
function XY = cmd_equal(NET)
XY = [NET.bx(:) NET.by(:)]; XY(:,1) = equalize_col(XY(:,1)); XY(:,2) = equalize_col(XY(:,2));
end
function c = equalize_col(c)
tol = 0.04*max(max(c)-min(c),1); [s,ord] = sort(c); grp = zeros(numel(c),1); g = 1; grp(ord(1)) = 1;
for p = 2:numel(c), if s(p)-s(p-1) > tol, g = g+1; end, grp(ord(p)) = g; end
ng = max(grp); lo = min(c); hi = max(c); if hi-lo < 1e-9, return; end
for k = 1:ng, c(grp==k) = lo + (hi-lo)*(k-1)/max(ng-1,1); end
end
function XY = cmd_straighten(NET)
XY = [NET.bx(:) NET.by(:)]; XY(:,1) = snap_col(XY(:,1)); XY(:,2) = snap_col(XY(:,2));
end
function c = snap_col(c)
tol = 0.05*max(max(c)-min(c),1); [s,ord] = sort(c); grp = zeros(numel(c),1); g = 1; grp(ord(1)) = 1;
for p = 2:numel(c), if s(p)-s(p-1) > tol, g = g+1; end, grp(ord(p)) = g; end
for k = 1:max(grp), idx = (grp==k); c(idx) = mean(c(idx)); end
end
function XY = cmd_scale(NET, f)
XY = [NET.bx(:) NET.by(:)]; c = mean(XY,1); XY = bsxfun(@plus, bsxfun(@minus,XY,c)*f, c);
end

function onAlign(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% align / distribute the box-selected buses (flat code, no nested functions)
fig = gcbf; h = guidata(fig); mode = get(src,'UserData'); s = h.ED.selset(:);
if numel(s) < 2, set(h.status,'String','box-select 2+ buses first'); return; end
h = pushUndo(h); NET = h.NET; bx = NET.bx(s); by = NET.by(s);
tx = bx; ty = by;
switch mode
case 'l',   tx = min(bx)*ones(numel(s),1);
case 'r',   tx = max(bx)*ones(numel(s),1);
case 'cx',  tx = mean(bx)*ones(numel(s),1);
case 't',   ty = max(by)*ones(numel(s),1);
case 'b',   ty = min(by)*ones(numel(s),1);
case 'cy',  ty = mean(by)*ones(numel(s),1);
case 'dist'
    [~,ord] = sort(bx); xs = linspace(min(bx),max(bx),numel(s)).'; tx(ord) = xs;
end
for a = 1:numel(s)
    i = s(a); dx = tx(a)-NET.bx(i); dy = ty(a)-NET.by(i);
    NET.bx(i) = tx(a); NET.by(i) = ty(a);
    g = find(NET.g_bus==i);
    for gg = g(:)', NET.gx(gg)=NET.gx(gg)+dx; NET.gy(gg)=NET.gy(gg)+dy; end
end
NET = refacts(NET, s(:).');
h.NET = NET; guidata(fig,h); redraw(fig); set(h.status,'String','aligned');
end

function onTransform(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); mode = get(src,'UserData');
s = h.ED.selset; if isempty(s) && strcmp(h.ED.selkind,'bus'), s = h.ED.selidx; end
if isempty(s), s = 1:nbus(h.NET); end
if numel(s) < 1, return; end
h = pushUndo(h); NET = h.NET; cx = mean(NET.bx(s)); cy = mean(NET.by(s));
for a = 1:numel(s)
    i = s(a); x = NET.bx(i)-cx; y = NET.by(i)-cy;
    switch mode
    case 'rot',   nx = -y; ny = x;
    case 'fliph', nx = -x; ny =  y;
    case 'flipv', nx =  x; ny = -y;
    end
    dx = (cx+nx)-NET.bx(i); dy = (cy+ny)-NET.by(i);
    NET.bx(i) = cx+nx; NET.by(i) = cy+ny;
    g = find(NET.g_bus==i); for gg=g(:)', NET.gx(gg)=NET.gx(gg)+dx; NET.gy(gg)=NET.gy(gg)+dy; end
end
NET = refacts(NET, s(:).');
h.NET = NET; guidata(fig,h); redraw(fig); set(h.status,'String',['applied ' mode]);
end

% =========================================================================
%                       MACHINE-DATA SUB-EDITOR
% =========================================================================
function onEditMachine(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if ~strcmp(h.ED.selkind,'gen'), return; end
k = h.ED.selidx; tag = h.NET.g_tag{k};
if ~any(strcmp(tag,h.SGFAM))
    helpdlg(sprintf(['Unit "%s" is a converter / renewable model.\n\nIt uses PSDAT''s ' ...
      'validated default control parameters (grid-forming / grid-following, IEEE 1547 ' ...
      'support, PV / BESS / wind source dynamics). The machine-data editor applies to ' ...
      'synchronous-machine (SG-family) units.'],tag),'Converter unit'); return;
end
md = h.NET.g_md{k}; if isempty(md), md = default_md_local(h.NET.g_S(k)); end
d = figure('Name',sprintf('Machine data - Generator %d (%s)',k,tag),'NumberTitle','off', ...
    'Units','normalized','Position',[.27 .19 .46 .62],'Color',[1 1 1]);
try, set(d,'DefaultUicontrolFontName',get(fig,'DefaultUicontrolFontName'), ...
       'DefaultUicontrolFontSize',10); catch, end    % same typography as the app
uicontrol('Parent',d,'Style','text','Units','normalized','Position',[.04 .925 .92 .050], ...
    'String',sprintf('Synchronous-machine parameters (pu on 100 MVA) - Gen %d',k), ...
    'FontWeight','bold','FontSize',10.5,'ForegroundColor',[.12 .23 .45], ...
    'BackgroundColor','w','HorizontalAlignment','center');
F = h.MDF; eds = cell(1,numel(F));
pssdv = struct('Kpss',10,'Tw',10,'T1',0.25,'T2',0.02);   % Larsen & Swann defaults
for a = 1:numel(F)
    col = floor((a-1)/6); row = mod(a-1,6); x = 0.04 + col*0.192; y = 0.820 - row*0.112;
    lb = F{a}; if a > numel(F)-4, lb = ['PSS ' lb]; end
    uicontrol('Parent',d,'Style','text','Units','normalized','Position',[x y .155 .040], ...
        'String',lb,'BackgroundColor','w','ForegroundColor',[.4 .43 .5],'HorizontalAlignment','left','FontSize',8.5);
    if isfield(md,F{a}) && ~isempty(md.(F{a})), val = md.(F{a});
    elseif a > numel(F)-4, val = pssdv.(F{a});           % missing PSS field -> textbook default
    else, val = 0; end
    eds{a} = uicontrol('Parent',d,'Style','edit','Units','normalized','Position',[x y-0.049 .17 .048], ...
        'String',num2str(val,'%g'),'BackgroundColor',[.98 .99 1],'FontSize',9.5, ...
        'HorizontalAlignment','center');
end
uicontrol('Parent',d,'Style','text','Units','normalized','Position',[.04 .112 .92 .045], ...
    'String','PSS Kpss/Tw/T1/T2 take effect when the unit type is SGP or SG6P (stabilizer on the AVR).', ...
    'BackgroundColor','w','ForegroundColor',[.5 .5 .55],'HorizontalAlignment','center','FontSize',8);
% context for the dialog's own callbacks stored in ITS guidata, so Apply/Reset
% are NAMED handles (Octave-safe) rather than anonymous functions calling subfns
gd = struct('mainfig',fig,'k',k,'S',h.NET.g_S(k),'F',{F},'eds',{eds});
guidata(d, gd);
uicontrol('Parent',d,'Style','pushbutton','Units','normalized','Position',[.55 .03 .18 .07], ...
    'String','Apply','FontWeight','bold','BackgroundColor',[.12 .23 .45],'ForegroundColor','w','Callback',@mdApply);
uicontrol('Parent',d,'Style','pushbutton','Units','normalized','Position',[.76 .03 .18 .07], ...
    'String','Cancel','Callback',@(s,e) delete(d));
uicontrol('Parent',d,'Style','pushbutton','Units','normalized','Position',[.04 .03 .22 .07], ...
    'String','Reset to typical','Callback',@mdReset);
noTips(d);
end
function mdApply(src,~)
d = gcbf; gd = guidata(d); h = guidata(gd.mainfig); h = pushUndo(h); md = struct();
for a = 1:numel(gd.F), v = str2double(get(gd.eds{a},'String')); if ~isnan(v), md.(gd.F{a}) = v; end, end
h.NET.g_md{gd.k} = md; guidata(gd.mainfig,h); redraw(gd.mainfig); delete(d);
autoPF(gd.mainfig, sprintf('machine data applied to generator %d', gd.k));
end
function mdReset(src,~)
d = gcbf; gd = guidata(d); md = default_md_local(gd.S);
for a = 1:numel(gd.F), v = 0; if isfield(md,gd.F{a}), v = md.(gd.F{a}); end, set(gd.eds{a},'String',num2str(v,'%g')); end
end
function d = default_md_local(S)
k = S/100.0;
d = struct('H',5.0*k,'Xd',1.8/k,'Xdp',0.30/k,'Xdpp',0.25/k,'Xq',1.7/k,'Xqp',0.55/k, ...
    'Xqpp',0.25/k,'Td0p',8.0,'Td0pp',0.03,'Tq0p',0.4,'Tq0pp',0.05,'Rs',0.0025/k,'Xls',0.2/k, ...
    'Dm',0.0,'KA',20.0,'TA',0.2,'KE',1.0,'TE',0.314,'KF',0.063,'TF',0.35,'Ax',0.0039,'Bx',1.555, ...
    'TCH',0.1,'TSV',0.05,'RD',0.05);
end

% =========================================================================
%   FACTS parameter editor: full device parameters + the supplementary POD /
%   wide-area-damping controller (mirrors the Python FACTS + controller editor)
% =========================================================================
function F = factFields(d)
ty = upper(d.type);
if isShuntFac(ty)
    if strcmp(ty,'SVC'), lim = {'Bmax (pu)','Bmax'; 'Bmin (pu)','Bmin'};
    else, lim = {'Imax (pu)','Imax'; 'Imin (pu)','Imin'}; end
    F = [{'V ref (pu)','Vref'}; lim; {'gain Kr','Kr'; 'Tr (s)','Tr'; 'Kaw','Kaw'; 'droop (pu)','droop'}];
elseif isSeriesFac(ty)
    F = {'comp kcomp','kcomp'; 'kmin','kmin'; 'kmax','kmax'; 'Tc (s)','Tc'};
    if strcmp(ty,'SSSC'), F = [F; {'Vse max (pu)','Vsemax'}]; end
elseif strcmp(ty,'UPFC')
    F = {'shunt bus','bus'; 'V ref (pu)','Vref'; 'Imax (pu)','Imax'; 'Imin (pu)','Imin'; ...
         'comp kcomp','kcomp'; 'Vse max (pu)','Vsemax'; 'P set (MW, P-Q)','Pset'; 'Q set (MVAr)','Qset'};
else
    F = {'comp kcomp','kcomp'; 'kcomp2','kcomp2'; 'line2 from bus','f2'; 'line2 to bus','t2'; 'Vse max (pu)','Vsemax'; ...
         'P1 set (MW, P-Q)','P1set'; 'Q1 set (MVAr)','Q1set'; 'Q2 set (MVAr)','Q2set'};
end
end
function tf = factPodCapable(ty), tf = isShuntFac(ty) || strcmp(upper(ty),'UPFC') || any(strcmp(upper(ty),{'TCSC','SSSC'})); end
function idx = sigIdx(s)
sigs = {'Vbus','Pline','Qline','Iline','adiff','wgen','angle'};
idx = find(strcmp(s,sigs),1); if isempty(idx), idx = 1; end
end
function c = ctypeCodes(), c = {'leadlag','p','lead','lag','washout','lp1','pi','pid'}; end
function p = podDlgRead(gd)
% assemble the pod struct from the CURRENT dialog contents (unapplied edits)
p = podDefaultApp();
sigs = {'Vbus','Pline','Qline','Iline','adiff','wgen','angle'};
p.sig = sigs{get(gd.pod.sig,'Value')};
cc = ctypeCodes(); p.ctype = cc{get(gd.pod.ctype,'Value')};
for a = 1:numel(gd.pod.pf)
    v = str2double(get(gd.pod.eds{a},'String'));
    if ~isnan(v), p.(gd.pod.pf{a}) = v; end
end
p.nc = round(p.nc); p.rbus = round(p.rbus);
p.f = round(p.f); p.t = round(p.t); p.i = round(p.i); p.j = round(p.j);
p.on = true;
end
function p = podRecommend(p, ty) %#ok<INUSD>
% textbook starting values per controller type + signal [Kundur ch.12;
% Larsen & Swann; Astrom & Hagglund].  Regulation types get gains that WORK
% immediately (negative feedback on the measured deviation, oracle-verified
% stable on the bundled benchmarks); damping types get the standard time
% constants -- their GAIN is genuinely system-dependent, so it comes from
% Auto-tune, never from a blind constant.
ct = lower(p.ctype); sg = lower(p.sig);
if any(strcmp(ct, {'p','pi','pid','lag','lp1'}))
    p.K = -0.5; p.Ki = -2.0; p.Kd = -0.02; p.Tf = 0.02;
    if any(strcmp(sg, {'pline','qline','iline'})), p.K = -0.3; p.Ki = -1.0; end
    p.lo = -0.10; p.hi = 0.10;
else
    p.Tw = 10; p.T1 = 0.25; p.T2 = 0.05; p.nc = 2;
    p.lo = -0.10; p.hi = 0.10;
end
end
function podRecBtn(src,~) %#ok<INUSD>
dlg = gcbf; gd = guidata(dlg);
if ~isstruct(gd) || ~isfield(gd,'pod') || ~gd.pod.has, return; end
p = podRecommend(podDlgRead(gd), gd.ty);
podDlgWrite(gd, p);
h = guidata(gd.mainfig);
if isfield(h,'status') && ishghandle(h.status)
    if any(strcmp(lower(p.ctype),{'p','pi','pid','lag','lp1'}))
        set(h.status,'String','recommended regulation settings filled in - Apply to activate them');
    else
        set(h.status,'String','standard damping time constants filled in - use Auto-tune to set the gain from this network');
    end
end
end
function podDlgWrite(gd, p)
sl = {'rbus','f','t','i','j','tau','Tw','T1','T2','nc','K','Ki','Kd','Tf','lo','hi'};
for a = 1:numel(gd.pod.pf)
    fn = gd.pod.pf{a};
    if any(strcmp(fn, sl)) && isfield(p, fn) && ishghandle(gd.pod.eds{a})
        set(gd.pod.eds{a},'String',num2str(p.(fn),'%g'));
    end
end
cc = ctypeCodes(); q = find(strcmp(lower(p.ctype), cc), 1);
if ~isempty(q) && isfield(gd.pod,'ctype') && ishghandle(gd.pod.ctype)
    set(gd.pod.ctype,'Value',q);
    if isfield(gd.pod,'tf') && ishghandle(gd.pod.tf), set(gd.pod.tf,'String',ctypeTF(q)); end
end
end
function podTuneBtn(src,~) %#ok<INUSD>
% ADAPTIVE INITIALIZATION (mode-sensitivity continuation): probe d(lambda)/dK
% of the most controllable poorly-damped mode, design the phase lead from the
% probe angle (the PSDAT_Design formulas), then raise the gain in ~1.5%-of-
% damping steps, re-verifying the FULL eigenvalue set at every step.  The
% result either improves the target mode with nothing destabilized, or the
% user is told exactly why not (no authority).  Stop aborts between steps.
dlg = gcbf; gd = guidata(dlg); fig = gd.mainfig;
if busyBlock(fig), return; end
bz = beBusy(fig); %#ok<NASGU>
armFreshRun(fig);              % a lingering stop request must not abort the tuner
h = guidata(fig);
fd = h.NET.facts(gd.k);
for a = 1:size(gd.F,1)
    v = str2double(get(gd.eds{a},'String'));
    if ~isnan(v), fd.(gd.F{a,2}) = v; end
end
p = podDlgRead(gd);
[res, msg] = podAutoTune(fig, h, gd.k, fd, p);
if isempty(res)
    if isfield(h,'status') && ishghandle(h.status), set(h.status,'String',['auto-tune: ' msg]); end
    return;
end
podDlgWrite(gd, res.p);
if isfield(h,'status') && ishghandle(h.status)
    set(h.status,'String',sprintf(['auto-tune: %.2f-Hz mode damping %.1f%% -> %.1f%% ' ...
        '(K=%+.3g, T1=%.3g, T2=%.3g, nc=%d) - press Apply to keep'], ...
        res.f, res.z0, res.z1, res.p.K, res.p.T1, res.p.T2, res.p.nc));
end
end
function [res, msg] = podAutoTune(fig, h, k, fd, p)
res = []; msg = '';
global PSDAT_STOP %#ok<GVMIS>
PSDAT_STOP = false;
base = p; base.ctype = 'leadlag'; base.Tw = 10; base.T1 = 0.05; base.T2 = 0.05;
base.nc = 1; base.K = 0; eps_ = 2e-3;
stat_ = @(s) tstat(h, s);
stat_('auto-tune: probing the open loop (1/3)...');
[l0, ok] = tuneEig(h.NET, k, fd, base); if ~ok, msg = 'linearization failed'; return; end
pk = base; pk.K = eps_;
stat_('auto-tune: probing mode sensitivity (2/3)...');
[l1, ok] = tuneEig(h.NET, k, fd, pk); if ~ok, msg = 'stopped'; return; end
cnd = find(imag(l0) > 2*pi*0.1 & imag(l0) < 2*pi*3.0 & -real(l0)./abs(l0) < 0.20);
if isempty(cnd), msg = 'no poorly-damped oscillatory mode to target (all modes > 20%)'; return; end
S = zeros(numel(cnd),1) + 0i;
for a = 1:numel(cnd)
    [~, jj] = min(abs(l1 - l0(cnd(a)))); S(a) = (l1(jj) - l0(cnd(a)))/eps_;
end
[Smax, pick] = max(abs(S));
if Smax < 1e-6, msg = 'target modes are not controllable from this device/signal'; return; end
lref = l0(cnd(pick)); w = abs(imag(lref)); sgn = 1;
phi = mod(pi - angle(S(pick)) + pi, 2*pi) - pi;
if abs(phi) > pi/2, sgn = -1; phi = phi - sign(phi)*pi; end
ncs = min(3, max(1, ceil(abs(phi)/(65*pi/180)))); phic = phi/ncs;
aa = (1 + sin(phic))/(1 - sin(phic));
T2 = 1/(w*sqrt(aa)); T1 = aa*T2;
zmin0 = tzmin(l0); K = 0; lprev = l0; zbest = [];
for it = 1:8
    if ~isempty(PSDAT_STOP) && isequal(PSDAT_STOP, true), break; end
    stat_(sprintf('auto-tune: raising the gain, step %d (3/3)...  K = %+.3g', it, K));
    pk = base; pk.T1 = T1; pk.T2 = T2; pk.nc = ncs; pk.K = K + sgn*eps_;
    [lp, ok] = tuneEig(h.NET, k, fd, pk); if ~ok, break; end
    [~, jj] = min(abs(lp - lref)); S2 = (lp(jj) - lref)/(sgn*eps_);
    if abs(real(S2)) < 1e-9, break; end
    Knew = K - 0.015*abs(lref)/real(S2);
    if abs(Knew) > 30, break; end
    pv = base; pv.T1 = T1; pv.T2 = T2; pv.nc = ncs; pv.K = Knew;
    [lv, ok] = tuneEig(h.NET, k, fd, pv); if ~ok, break; end
    if sum(real(lv) > 1e-6) > sum(real(l0) > 1e-6) || tzmin(lv) < tzmin(lprev) - 0.05, break; end
    K = Knew; lprev = lv;
    [~, jj] = min(abs(lv - lref)); lref = lv(jj);
    zbest = [tzmin(l0), tzmin(lv)];
    if -real(lref)/abs(lref) > 0.15, break; end
end
if isempty(zbest) || zbest(2) < zmin0 + 0.3
    msg = 'no stable improving gain found - this device/signal has too little authority over the target mode';
    return;
end
pr = p; pr.ctype = 'leadlag'; pr.Tw = 10; pr.T1 = T1; pr.T2 = T2; pr.nc = ncs; pr.K = K;
res = struct('p', pr, 'f', w/2/pi, 'z0', zbest(1), 'z1', zbest(2));
end
function z = tzmin(lam)
osc = lam(imag(lam) > 2*pi*0.1 & imag(lam) < 2*pi*3.0);
z = min(-real(osc)./abs(osc)*100);
if isempty(z), z = inf; end
end
function tstat(h, s)
if isfield(h,'status') && ishghandle(h.status), set(h.status,'String',s); drawnow limitrate; end
end
function [lam, ok] = tuneEig(NET, k, fd, pp)
% eigenvalues of the drawn network with device k's pod replaced by pp
lam = []; ok = false;
try
    fd.pod = pp; NET.facts(k) = fd;
    np_ = getappdata(0,'PSDAT_noplot'); setappdata(0,'PSDAT_noplot',1);
    cl = onCleanup(@() setappdata(0,'PSDAT_noplot',np_)); %#ok<NASGU>
    C = psdat_netcase(NET);
    R = PSDAT_Linearization(C, C.UT, []);
    lam = R.lambda; ok = true;
catch
end
end
function idx = ctypeIdx(p)
idx = 1;
if isstruct(p) && isfield(p,'ctype') && ~isempty(p.ctype)
    q = find(strcmp(p.ctype, ctypeCodes()),1); if ~isempty(q), idx = q; end
end
end
function s = ctypeTF(idx)
% the textbook transfer function of each controller type -- shown live in
% the editor so students see exactly WHAT they are configuring
T = {['u = K (sTw/(1+sTw)) [(1+sT1)/(1+sT2)]^nc' 10 'phase-lead damping controller (POD/WADC); tune with Design'], ...
     ['u = K * dsig          (pure gain)' 10 'washout bypassed (Tw very large), nc = 0'], ...
     ['u = K (1+sT1)/(1+sT2),  T1 > T2' 10 'phase LEAD = practical (filtered) PD:  Kd ~ K(T1-T2)'], ...
     ['u = K (1+sT1)/(1+sT2),  T1 < T2' 10 'phase LAG: boosts low-frequency action (PI-like behaviour)'], ...
     ['u = K sTw/(1+sTw)' 10 'washout / rate feedback: passes CHANGES, blocks steady offset'], ...
     ['u = K / (1+sT2)' 10 'first-order low-pass: measurement smoothing / noise filter'], ...
     ['u = Kp e + Ki (integral of e)' 10 'PI: zero steady-state error; conditional-integration anti-windup'], ...
     ['u = Kp e + Ki (int e) + Kd de/dt (filtered, Tf)' 10 'PID: full three-term control; derivative through 1/(1+sTf)']};
s = T{max(1,min(numel(T),idx))};
end
function factsCtype(src,~)
% selecting a controller type presets the standard textbook parameters and
% shows its transfer function (existing K / limits / signal stay untouched)
dlg = gcbf; gd = guidata(dlg);
if ~isstruct(gd) || ~isfield(gd,'pod') || ~gd.pod.has, return; end
v = get(src,'Value');
if isfield(gd.pod,'tf') && ishghandle(gd.pod.tf), set(gd.pod.tf,'String',ctypeTF(v)); end
%          Tw     T1      T2    nc      (slots 7..10 of the parameter list)
PR = {[10   0.30   0.05  2]; [1e6  0.30   0.05  0]; [1e6  0.30   0.05  1]; ...
      [1e6  0.05   0.30  1]; [10   0.30   0.05  0]; [1e6  1e-4   0.05  1]; ...
      [10   0.30   0.05  0]; [10   0.30   0.05  0]};
pv = PR{max(1,min(numel(PR),v))};
sl = [7 8 9 10];
for a = 1:4
    if numel(gd.pod.eds) >= sl(a) && ishghandle(gd.pod.eds{sl(a)})
        set(gd.pod.eds{sl(a)},'String',num2str(pv(a),'%g'));
    end
end
end
function onEditFacts(src,~)   %#ok<INUSD>
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
if ~strcmp(h.ED.selkind,'facts'), return; end
k = h.ED.selidx; d = h.NET.facts(k); ty = upper(d.type);
F = factFields(d);
dlg = figure('Name',sprintf('FACTS parameters - %s',ty),'NumberTitle','off', ...
    'Units','normalized','Position',[.29 .12 .44 .74],'Color',[1 1 1],'MenuBar','none');
try, set(dlg,'DefaultUicontrolFontName',get(fig,'DefaultUicontrolFontName'), ...
         'DefaultUicontrolFontSize',10); catch, end  % same typography as the app
uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.04 .942 .92 .042], ...
    'String',sprintf('%s parameters (pu on 100 MVA)',ty),'FontWeight','bold', ...
    'ForegroundColor',[.12 .23 .45],'BackgroundColor','w','HorizontalAlignment','center','FontSize',10.5);
eds = cell(1,size(F,1));
for a = 1:size(F,1)
    y = 0.880 - (a-1)*0.064;
    uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.04 y .30 .048], ...
        'String',F{a,1},'BackgroundColor','w','ForegroundColor',[.4 .43 .5],'HorizontalAlignment','left');
    v = d.(F{a,2}); if isempty(v), v = 0; end
    eds{a} = uicontrol('Parent',dlg,'Style','edit','Units','normalized','Position',[.35 y .20 .054], ...
        'String',num2str(v,'%g'),'BackgroundColor',[.98 .99 1],'HorizontalAlignment','center');
end
modeC = [];
if strcmp(ty,'UPFC')
    y = 0.880 - size(F,1)*0.064;
    modeC = uicontrol('Parent',dlg,'Style','checkbox','Units','normalized','Position',[.04 y .52 .05], ...
        'String','P-Q flow control (DC-coupled)','Value',strcmpi(valOr(d.mode,'comp'),'pq'),'BackgroundColor','w', ...
        'TooltipString','on = set line P and Q independently (uses P set / Q set); off = composition (STATCOM+SSSC)');
elseif strcmp(ty,'IPFC')
    y = 0.880 - size(F,1)*0.064;
    modeC = uicontrol('Parent',dlg,'Style','checkbox','Units','normalized','Position',[.04 y .52 .05], ...
        'String','P-Q flow control (DC-coupled)','Value',strcmpi(valOr(d.mode,'comp'),'pq'),'BackgroundColor','w', ...
        'TooltipString',['on = master line delivers P1+jQ1, slave line delivers Q2 and supplies the balancing ' ...
        'real power through the DC link (needs line 2 set, same sending bus); off = composition (two SSSCs)']);
end
podC = struct('has',false);
if factPodCapable(ty)
    p = podDefaultApp();                     % merge the device's pod onto the
    if isstruct(d.pod)                       % full-field defaults, so a device
        fp = fieldnames(p);                  % saved before Ki/Kd/Tf/ctype shows
        for q = 1:numel(fp)                  % textbook values, never zeros
            if isfield(d.pod,fp{q}) && ~isempty(d.pod.(fp{q})), p.(fp{q}) = d.pod.(fp{q}); end
        end
    end
    uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.60 .90 .38 .040], ...
        'String','Supplementary POD / WADC','FontWeight','bold','ForegroundColor',[.12 .23 .45], ...
        'BackgroundColor','w','HorizontalAlignment','center','FontSize',9.5);
    podC.on = uicontrol('Parent',dlg,'Style','checkbox','Units','normalized','Position',[.60 .858 .38 .038], ...
        'String','enable supplementary controller','Value',logical(p.on),'BackgroundColor','w','FontSize',9);
    uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.60 .818 .15 .036], ...
        'String','controller type','BackgroundColor','w','ForegroundColor',[.4 .43 .5],'HorizontalAlignment','left','FontSize',7.5);
    podC.ctype = uicontrol('Parent',dlg,'Style','popupmenu','Units','normalized','Position',[.76 .814 .22 .044], ...
        'String',{'Lead-lag + washout (POD)','Proportional (P)','Lead (PD-like)', ...
                  'Lag (PI-like)','Washout (rate)','Low-pass filter', ...
                  'PI + anti-windup','PID (filtered D)'}, ...
        'Value',ctypeIdx(p),'FontSize',8,'Callback',@factsCtype, ...
        'TooltipString',['controller structure, textbook form: selecting a type presets Tw/T1/T2/nc to the ' ...
        'standard values and shows its transfer function below - every type integrates automatically into ' ...
        'power flow, small-signal (exact states) and time domain']);
    podC.tf = uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.60 .754 .38 .056], ...
        'String',ctypeTF(ctypeIdx(p)),'BackgroundColor',[.97 .98 1],'ForegroundColor',[.20 .28 .45], ...
        'HorizontalAlignment','left','FontSize',7.5);
    uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.60 .712 .15 .036], ...
        'String','input signal','BackgroundColor','w','ForegroundColor',[.4 .43 .5],'HorizontalAlignment','left','FontSize',7.5);
    podC.sig = uicontrol('Parent',dlg,'Style','popupmenu','Units','normalized','Position',[.76 .708 .22 .044], ...
        'String',{'bus |V| (local/remote)','line P (tie-line)','line Q','line I','angle diff (PMU pair)','rotor speed / freq','bus angle (PMU)'}, ...
        'Value',sigIdx(p.sig),'FontSize',8, ...
        'TooltipString',['feedback signal, local or WIDE-AREA: any bus (meas bus), any line (sig line f-t), any ' ...
        'bus pair (angle bus i/j) or any machine, with the WAMS/PMU channel latency as delay tau (first-order lag)']);
    pf = {'meas bus','rbus'; 'sig line f','f'; 'sig line t','t'; 'angle bus i','i'; 'angle bus j','j'; ...
          'delay tau (s)','tau'; 'washout Tw','Tw'; 'lead T1','T1'; 'lag T2','T2'; 'stages nc','nc'; ...
          'gain K (Kp)','K'; 'Ki (PI/PID)','Ki'; 'Kd (PID)','Kd'; 'deriv Tf (s)','Tf'; ...
          'out lo','lo'; 'out hi','hi'};
    podeds = cell(1,size(pf,1));
    for a = 1:size(pf,1)
        y = 0.662 - (a-1)*0.0385;
        uicontrol('Parent',dlg,'Style','text','Units','normalized','Position',[.60 y .22 .034], ...
            'String',pf{a,1},'BackgroundColor','w','ForegroundColor',[.4 .43 .5],'HorizontalAlignment','left','FontSize',7.5);
        vpd = 0; if isfield(p,pf{a,2}) && ~isempty(p.(pf{a,2})), vpd = p.(pf{a,2}); end
        podeds{a} = uicontrol('Parent',dlg,'Style','edit','Units','normalized','Position',[.83 y .15 .036], ...
            'String',num2str(vpd,'%g'),'BackgroundColor',[.98 .99 1],'FontSize',8, ...
            'HorizontalAlignment','center');
    end
    podC.has = true; podC.eds = podeds; podC.pf = {pf{:,2}};
    uicontrol('Parent',dlg,'Style','pushbutton','Units','normalized','Position',[.55 .018 .20 .058], ...
        'String','Recommended','FontSize',9.5,'Callback',@podRecBtn, ...
        'TooltipString','fill textbook starting values for the chosen controller type and signal (regulation types get working gains immediately)');
    uicontrol('Parent',dlg,'Style','pushbutton','Units','normalized','Position',[.77 .018 .20 .058], ...
        'String','Auto-tune','FontSize',9.5,'FontWeight','bold','Callback',@podTuneBtn, ...
        'TooltipString',['design phase compensation and gain FROM THIS NETWORK: probes the target mode''s ' ...
        'sensitivity to this device, steps the gain up with a stability check at every step (mode-sensitivity ' ...
        'method), and writes the result into the fields - Apply to keep it']);
end
gd = struct('mainfig',fig,'k',k,'ty',ty,'F',{F},'eds',{eds},'pod',podC,'mode',modeC);
guidata(dlg,gd);
uicontrol('Parent',dlg,'Style','pushbutton','Units','normalized','Position',[.03 .018 .20 .058], ...
    'String','Apply','FontWeight','bold','BackgroundColor',[.12 .23 .45],'ForegroundColor','w','Callback',@factsApply);
uicontrol('Parent',dlg,'Style','pushbutton','Units','normalized','Position',[.25 .018 .16 .058], ...
    'String','Cancel','Callback',@(s,e) delete(dlg));
noTips(dlg);
end
function factsApply(src,~)   %#ok<INUSD>
dlg = gcbf; gd = guidata(dlg);
if isBusy(gd.mainfig)                          % never re-solve inside a running solve
    hm = guidata(gd.mainfig);
    if isfield(hm,'status') && ishghandle(hm.status)
        set(hm.status,'String','a run is active - press Stop first, then Apply the device edit');
    end
    return;
end
h = guidata(gd.mainfig); h = pushUndo(h);
k = gd.k; fd = h.NET.facts(k);
for a = 1:size(gd.F,1)
    v = str2double(get(gd.eds{a},'String'));
    if ~isnan(v), fd.(gd.F{a,2}) = v; end
end
inms = {'bus','f','t','f2','t2'};
for a = 1:numel(inms)
    if isfield(fd,inms{a}) && ~isempty(fd.(inms{a})), fd.(inms{a}) = round(fd.(inms{a})); end
end
if strcmp(gd.ty,'UPFC') && ~isempty(gd.mode) && ishghandle(gd.mode)
    if get(gd.mode,'Value'), fd.mode = 'pq';
    else, fd.mode = 'comp'; fd.Pset = []; fd.Qset = []; end   % composition: drop the P-Q targets
elseif strcmp(gd.ty,'IPFC') && ~isempty(gd.mode) && ishghandle(gd.mode)
    if get(gd.mode,'Value')
        fd.mode = 'pq';
        if isempty(fd.P1set), fd.P1set = 80; end              % sensible starting targets
        if isempty(fd.Q1set), fd.Q1set = 10; end
        if isempty(fd.Q2set), fd.Q2set = 5;  end
        if ~isempty(fd.t2) && fd.t2 > 0, fd.f2 = fd.f; end    % converters share the sending bus
    else
        fd.mode = 'comp'; fd.P1set = []; fd.Q1set = []; fd.Q2set = [];
    end
end
if gd.pod.has
    p = fd.pod; if ~isstruct(p), p = podDefaultApp(); end
    p.on = logical(get(gd.pod.on,'Value'));
    sigs = {'Vbus','Pline','Qline','Iline','adiff','wgen','angle'};
    p.sig = sigs{get(gd.pod.sig,'Value')};
    for a = 1:numel(gd.pod.pf)
        v = str2double(get(gd.pod.eds{a},'String'));
        if ~isnan(v), p.(gd.pod.pf{a}) = v; end
    end
    p.nc = round(p.nc); p.rbus = round(p.rbus);
    p.f = round(p.f); p.t = round(p.t); p.i = round(p.i); p.j = round(p.j);
    if isfield(gd.pod,'ctype') && ishghandle(gd.pod.ctype)
        cc = ctypeCodes(); p.ctype = cc{get(gd.pod.ctype,'Value')};
    end
    % a controller enabled with K = 0 does NOTHING -- never let that pass
    % silently: regulation types get the oracle-verified recommended gains;
    % damping types get an explicit pointer to Auto-tune.
    podnote = '';
    if p.on && (isempty(p.K) || p.K == 0)
        if any(strcmp(lower(p.ctype), {'p','pi','pid','lag','lp1'}))
            p = podRecommend(p, gd.ty);
            podnote = 'controller had K=0: recommended regulation gains applied (K=-0.5, Ki=-2)';
        else
            podnote = 'controller enabled with K=0 (no action yet) - open FACTS parameters and press Auto-tune';
        end
    end
    setappdata(gd.mainfig,'podnote',podnote);
    fd.pod = p;
end
h.NET.facts(k) = fd; guidata(gd.mainfig,h);
refreshList(gd.mainfig); showProps(gd.mainfig); redraw(gd.mainfig); delete(dlg);
% re-solve immediately so the edit's effect shows up without a manual run
factsImpact(gd.mainfig, sprintf('%s updated', upper(fd.type)), k);
pn = getappdata(gd.mainfig,'podnote');
if ~isempty(pn)
    setappdata(gd.mainfig,'podnote','');
    hm = guidata(gd.mainfig);
    if isfield(hm,'status') && ishghandle(hm.status), set(hm.status,'String',pn); end
end
end

% =========================================================================
%   EDUCATIONAL MODE -- the theory card of every component: the governing
%   equations, state variables, parameters, assumptions and textbook
%   references of the model psdat_dae.m / psdat_system.m actually solve.
%   Entry points: Properties > "Model equations & theory..." and the
%   right-click menu.  Notation in the cards: x' = transient quantity,
%   x" = subtransient, w = rotor speed, ws = synchronous speed; everything
%   is per unit on the 100 MVA system base unless stated otherwise.
% =========================================================================
function onTheory(src,~)   %#ok<INUSD>
fig = gcbf; if isempty(fig) || ~ishghandle(fig), return; end
h = guidata(fig); if ~isstruct(h) || ~isfield(h,'ED'), return; end
[ttl, L] = theoryFor(h, h.ED.selkind, h.ED.selidx);
if isempty(L)
    set(h.status,'String','select a component first - every bus, line, machine and FACTS device carries a theory card');
    return;
end
d = figure('Name',['PSDAT model reference - ' ttl],'NumberTitle','off', ...
    'Units','normalized','Position',[.30 .10 .40 .78],'Color','w','MenuBar','none');
try, set(d,'DefaultUicontrolFontName',get(fig,'DefaultUicontrolFontName')); catch, end
uicontrol('Parent',d,'Style','text','Units','normalized','Position',[.05 .938 .90 .044], ...
    'String',ttl,'FontWeight','bold','FontSize',11.5,'ForegroundColor',[.12 .23 .43], ...
    'BackgroundColor','w','HorizontalAlignment','center');
uicontrol('Parent',d,'Style','frame','Units','normalized','Position',[.05 .930 .90 .0022], ...
    'BackgroundColor',[.855 .88 .915],'ForegroundColor',[.855 .88 .915]);
uicontrol('Parent',d,'Style','edit','Units','normalized','Position',[.05 .088 .90 .828], ...
    'String',L,'Max',2,'Enable','inactive','HorizontalAlignment','left', ...
    'BackgroundColor',[.985 .99 1],'ForegroundColor',[.13 .18 .28], ...
    'FontName','Courier','FontSize',9.5);
uicontrol('Parent',d,'Style','text','Units','normalized','Position',[.05 .020 .62 .042], ...
    'String','the same equations run in psdat_dae.m - open it to see them in code', ...
    'FontSize',8,'FontAngle','italic','ForegroundColor',[.44 .47 .54], ...
    'BackgroundColor','w','HorizontalAlignment','left');
uicontrol('Parent',d,'Style','pushbutton','Units','normalized','Position',[.72 .016 .23 .052], ...
    'String','Close','Callback',@(s,e) delete(d));
noTips(d);
end

function [ttl, L] = theoryFor(h, kind, i)
NET = h.NET; ttl = ''; L = {};
switch kind
case 'bus'
    if i < 1 || i > nbus(NET), return; end
    tps = {'PQ load bus','PV voltage-controlled bus','slack / reference bus'};
    ttl = sprintf('Bus %d  -  %s', i, tps{max(1,min(3,NET.btype(i)))});
    L = thBus();
case 'branch'
    if i < 1 || i > nbr(NET), return; end
    if NET.br_tap(i) ~= 0
        ttl = sprintf('Transformer %d-%d  -  off-nominal-tap branch', NET.br_f(i), NET.br_t(i));
        L = thXfmr();
    else
        ttl = sprintf('Line %d-%d  -  lumped pi-model', NET.br_f(i), NET.br_t(i));
        L = thLine();
    end
case 'load'
    if i < 1 || i > nbus(NET), return; end
    ttl = sprintf('Load @ bus %d  -  constant-power demand', i);
    L = thLoad();
case 'gen'
    if i < 1 || i > ngen(NET), return; end
    tag = upper(char(NET.g_tag{i}));
    if any(strcmpi(NET.g_tag{i}, h.SGFAM))
        ttl = sprintf('Generator %d (%s)  -  synchronous machine', i, tag);
        L = thSG(tag);
    elseif ~isempty(strfind(tag,'GFM'))
        ttl = sprintf('Unit %d (%s)  -  grid-forming converter', i, tag);
        L = thGFM(tag);
    elseif strcmp(tag,'WT3')
        ttl = sprintf('Unit %d (WT3)  -  DFIG wind turbine', i);
        L = thWT3();
    elseif any(strcmp(tag,{'WT1','WT2'}))
        ttl = sprintf('Unit %d (%s)  -  fixed-speed induction wind turbine', i, tag);
        L = thWT12(tag);
    else
        ttl = sprintf('Unit %d (%s)  -  grid-following converter', i, tag);
        L = thGFL(tag);
    end
case 'facts'
    if i < 1 || i > nfac(NET), return; end
    ty = upper(NET.facts(i).type);
    switch ty
    case {'SVC','STATCOM'}
        ttl = [ty '  -  shunt FACTS compensator'];  L = thShuntFac(ty);
    case {'TCSC','TSSC','SSSC'}
        ttl = [ty '  -  series FACTS compensator']; L = thSeriesFac(ty);
    case 'UPFC'
        ttl = 'UPFC  -  unified power flow controller';   L = thUPFC();
    otherwise
        ttl = 'IPFC  -  interline power flow controller'; L = thIPFC();
    end
    if factPodCapable(ty), L = [L; thPOD()]; end
end
end

function L = thBus()
L = { ...
'MODEL'
'  A node of the positive-sequence phasor network.  Kirchhoff current'
'  law, written as a complex power balance, must hold at every bus:'
''
'    S_i = V_i * conj( sum_k  Y_ik * V_k )        (network injection)'
'    P_gen,i - P_load,i - Re{S_i} = 0'
'    Q_gen,i - Q_load,i - Im{S_i} = 0'
''
'  These are the algebraic equations g(x,z)=0 of the DAE; the power flow'
'  solves them alone, the dynamic studies solve them together with the'
'  machine ODEs at every integration step.'
''
'BUS TYPES (power-flow roles)'
'  slack   V and angle fixed        - balances system P and Q'
'  PV      P and |V| fixed          - a generator holds its voltage'
'  PQ      P and Q fixed            - a demand node'
'  The first generator bus is auto-promoted to slack; every other'
'  generator bus becomes PV.'
''
'FIXED SHUNT (the Bs field)'
'  Q_sh = Bs * |V|^2      (capacitive Bs > 0 injects vars)'
''
'STATE / ALGEBRAIC VARIABLES'
'  none / V_i, theta_i  (two per bus; slack contributes references)'
''
'ASSUMPTIONS AND LIMITS'
'  Balanced three-phase operation, fundamental frequency, constant'
'  network parameters; per unit on 100 MVA.'
''
'REFERENCES'
'  Bergen & Vittal, Power Systems Analysis, ch. 9-10.'
'  Kundur, Power System Stability and Control, 1994, ch. 6.'
'  Sauer & Pai, Power System Dynamics and Stability, 1998, ch. 2.'
};
end

function L = thLine()
L = { ...
'MODEL  (lumped pi-equivalent)'
'  Series impedance z = r + jx with total line charging b, split'
'  half-and-half onto the two terminals:'
''
'         f o----[ r + jx ]----o t'
'           |                  |'
'          jb/2               jb/2'
''
'  With y = 1/(r+jx) and bc = jb/2, the terminal power flows are'
''
'    S_f = V_f * conj( (y+bc) V_f - y V_t )'
'    S_t = V_t * conj( (y+bc) V_t - y V_f )'
'    losses = Re{ S_f + S_t }'
''
'  exactly the expressions the Report tab evaluates.'
''
'SERIES COMPENSATION'
'  A TCSC/TSSC/SSSC on this line replaces x by  x_eff = x*(1 - k):'
'  the device page (click the FACTS card) carries the control model.'
''
'PARAMETERS'
'  r, x   series resistance / reactance   (pu on 100 MVA)'
'  b      total charging susceptance      (pu)'
'  tap    0 for a plain line (nonzero turns it into a transformer)'
''
'ASSUMPTIONS AND LIMITS'
'  Lumped parameters (electrically short line), balanced positive'
'  sequence, constant impedance with frequency.'
''
'REFERENCES'
'  Bergen & Vittal, ch. 4-5.   Grainger & Stevenson, ch. 6.'
'  Kundur, 1994, ch. 6.'
};
end

function L = thXfmr()
L = { ...
'MODEL  (two-winding, off-nominal tap a on the FROM side)'
'  Series admittance y = 1/(r+jx), charging bc = jb/2 (usually 0),'
'  ideal-transformer ratio a : 1.  The branch stamps into Ybus as'
''
'    Y_ff += (y+bc)/a^2      Y_ft -= y/conj(a)'
'    Y_tf -= y/a             Y_tt += (y+bc)'
''
'  and the sending-end power (what the Report shows) is'
''
'    S_f = V_f * conj( (y+bc)/a^2 V_f - y/conj(a) V_t )'
''
'PARAMETERS'
'  r, x   short-circuit (leakage) impedance    (pu on 100 MVA)'
'  tap    off-nominal ratio a  (1.0 = nominal; 0 = plain line)'
''
'STATE VARIABLES'
'  none - the transformer is algebraic; tap is a fixed input here.'
''
'ASSUMPTIONS AND LIMITS'
'  Magnetising branch and core losses neglected (transmission-level'
'  practice); phase shift not modelled (a is real); balanced operation.'
''
'REFERENCES'
'  Grainger & Stevenson, ch. 2.   Kundur, 1994, ch. 6.'
'  Bergen & Vittal, ch. 5.'
};
end

function L = thLoad()
L = { ...
'MODEL  (constant-power demand)'
'  The load draws  S_L = P_L + jQ_L  independent of voltage:'
''
'    P_i(V,theta) + P_L = 0 ,   Q_i(V,theta) + Q_L = 0'
''
'  entering the bus power balance with negative sign.  In the dynamic'
'  studies the same constant-PQ demand appears in the algebraic set,'
'  and the "load step" disturbance perturbs it as  P_L + dP(t).'
''
'DERIVED QUANTITIES (shown in Properties / hover card)'
'  |S| = hypot(P,Q)         power factor = P/|S|  (lag if Q>0)'
'  I   = |S| / (100 * |V|)  per-unit current at the solved voltage'
''
'PARAMETERS'
'  P (MW), Q (MVAr) - edit them in Properties or the Data tab.'
''
'ASSUMPTIONS AND LIMITS'
'  Constant-power behaviour is the stiffest textbook choice: voltage'
'  dips do not relieve the demand.  Static V/f sensitivity (ZIP or'
'  exponential mixes) and load dynamics (motor stalling, OLTC'
'  recovery) are not represented.'
''
'REFERENCES'
'  IEEE Task Force on Load Representation, IEEE Trans. PWRS, 1993.'
'  Kundur, 1994, ch. 7.'
};
end

function L = thSG(tag)
switch tag
case 'SG',   hd = 'FULL MODEL - 11 states (this unit): two-axis + subtransient machine, IEEE Type-1 exciter, steam turbine + governor.';
case 'SGP',  hd = 'FULL MODEL + PSS - 14 states (this unit): the 11-state set below plus a 3-state stabiliser (washout + two lead-lags).';
case 'SG6',  hd = 'SUBTRANSIENT MODEL - 6 states (this unit): two-axis + subtransient machine with a simplified excitation loop; no governor (constant Pm).';
case 'SG6P', hd = 'SUBTRANSIENT + PSS - 9 states (this unit): the 6-state machine plus the 3-state stabiliser.';
case 'SG6G', hd = 'SUBTRANSIENT + GOVERNOR - 8 states (this unit): the 6-state machine plus the 2-state turbine/governor.';
case 'SG4',  hd = 'TWO-AXIS MODEL - 4 states (this unit): delta, w, Eq'', Ed'' with CONSTANT field voltage Efd (no exciter, no governor).';
case 'SG4G', hd = 'TWO-AXIS + GOVERNOR - 6 states (this unit): the 4-state machine plus the 2-state turbine/governor.';
otherwise,   hd = 'CLASSICAL MODEL - 2 states (this unit): delta and w behind the constant transient emf E'' (the swing-equation machine).';
end
L = { ...
hd
''
'CORE EQUATIONS  (per unit, machine quantities on the system base)'
'  d(delta)/dt = w - ws                              rotor angle'
'  (2H/ws) dw/dt = TM - TE - D*(w - ws)/ws           swing equation'
'  Td0''  dEq''/dt = -Eq'' - (Xd - Xd'')*Id + Efd       d-axis flux decay'
'  Tq0''  dEd''/dt = -Ed'' + (Xq - Xq'')*Iq             q-axis flux decay'
'  Td0"  and Tq0"  drive the subtransient flux states psi_d", psi_q"'
'  (6-state and 11-state orders only).'
''
'  Stator (algebraic, solved with the network):'
'    resistance Rs and leakage Xls link (Id, Iq) to the bus phasor;'
'    TE follows from the air-gap fluxes and currents [Sauer & Pai].'
''
'EXCITATION SYSTEM  (IEEE Type-1 / DC1A family; full model)'
'  TE_ex dEfd/dt = -( KE + SE(Efd) )*Efd + VR ,  SE = Ax*exp(Bx*Efd)'
'  TA    dVR /dt = -VR + KA*RF - (KA*KF/TF)*Efd + KA*(Vref - V + Vpss)'
'  TF    dRF /dt = -RF + (KF/TF)*Efd'
''
'TURBINE + GOVERNOR  (steam; full and ...G orders)'
'  TCH dTM /dt = -TM + PSV'
'  TSV dPSV/dt = -PSV + PC - (1/RD)*(w/ws - 1)       droop RD'
''
'POWER SYSTEM STABILISER  (SGP / SG6P)'
'  Vpss = Kpss * [ sTw/(1+sTw) ] * [ (1+sT1)/(1+sT2) ]^2 * (w-ws)/ws'
'  washout blocks steady offset; the lead pair compensates the phase'
'  lag from AVR input to electrical torque [Larsen & Swann, 1981].'
''
'PARAMETERS  (the 29 fields behind "Machine data...")'
'  H, D            inertia (s), damping'
'  Xd Xd'' Xd" Xq Xq'' Xq" Xls Rs      reactances / stator'
'  Td0'' Td0" Tq0'' Tq0"               open-circuit time constants'
'  KA TA KE TE KF TF Ax Bx           IEEE-T1 exciter + saturation'
'  TCH TSV RD                        turbine / governor / droop'
'  Kpss Tw T1 T2                     stabiliser (SGP / SG6P types)'
''
'ASSUMPTIONS AND LIMITS'
'  Balanced operation; stator transients neglected (phasor model);'
'  one machine per entry (use rating S to scale); saturation only in'
'  the exciter ceiling term SE(Efd).'
''
'REFERENCES'
'  Sauer & Pai, 1998, ch. 3-4 (machine), 6 (reduced orders), 8.'
'  Anderson & Fouad, Power System Control and Stability, 2003.'
'  Kundur, 1994, ch. 3, 12-13.   IEEE Std 421.5 (exciter models).'
'  Larsen & Swann, "Applying power system stabilizers", 1981.'
};
end

function L = thGFM(tag)
switch tag
case 'PV-GFM',   ex = 'THIS UNIT adds a PV source: available power Pav tracks kS*Pmp(G) of the single-diode array, and the droop reference can never exceed the sun (cloud events ramp G).';
case 'BESS-GFM', ex = 'THIS UNIT adds a battery: a state-of-charge integrator with capability limits; as SOC approaches its window edges both the reference and the droop authority fade smoothly to zero ACTIVE power (voltage support continues).';
case 'WT4-GFM',  ex = 'THIS UNIT adds a full-converter wind chain: Cp(lambda,beta) aerodynamics, two-mass shaft, pitch control and MPPT; the droop reference follows the MPPT order Po.';
otherwise,       ex = 'THIS UNIT is the plain grid-forming converter: Pref comes from its dispatch set-point.';
end
L = { ...
'MODEL  (droop / virtual-synchronous-machine grid-forming control)'
'  The converter BEHAVES AS A VOLTAGE SOURCE  E /_ dg  behind the'
'  coupling impedance Rc + jXc, and creates its own frequency:'
''
'    d(dg)/dt = wg - ws                       internal angle'
'    (2Hv/ws) dwg/dt = Pref - Pe - Dp*(wg/ws - 1)     P-f droop/VSM'
'    dQf/dt  = wc*(Qe - Qf)                   Q measurement filter'
'    E = Eset + mq*(Qset - Qf)                Q-V droop'
''
'  Hv is VIRTUAL inertia and Dp the damping/droop gain: the converter'
'  swings like a light machine and shares load without communication.'
''
ex
''
'STATE VARIABLES'
'  dg, wg, Qf  (+ Pav / SOC / wind chain states per variant)'
''
'PARAMETERS (validated defaults; rating S scales the base)'
'  Hv, Dp     virtual inertia and P-f droop'
'  mq, wc     Q-V droop gain and filter corner'
'  Rc, Xc     coupling (filter + transformer) impedance'
''
'ASSUMPTIONS AND LIMITS'
'  Average-value converter (no switching); current limiting not'
'  explicit -- size S conservatively for fault studies; DC side ideal'
'  except where the variant models it (PV / BESS / WT4).'
''
'REFERENCES'
'  Zhong & Weiss, "Synchronverters", IEEE Trans. IE, 2011.'
'  D''Arco & Suul, virtual synchronous machines, 2013-2015.'
'  IEEE Std 2800-2022 (IBR interconnection performance).'
};
end

function L = thGFL(tag)
switch tag
case 'PV-GFL',   ex = 'THIS UNIT adds the PV source chain: irradiance G -> single-diode Pmp -> DC link; the current reference tracks kS*Pmp(G) (cloud events ramp G).';
case 'BESS-GFL', ex = 'THIS UNIT adds a battery behind the injection: SOC integrator, capability window and fast-frequency-response droop on measured frequency.';
case 'WT4-GFL',  ex = 'THIS UNIT adds the type-4 wind chain (aero Cp, two-mass shaft, pitch, MPPT) ahead of the current-controlled injection.';
otherwise,       ex = 'THIS UNIT is the plain grid-following converter: P/Q references come from dispatch plus the IEEE 1547 support curves.';
end
L = { ...
'MODEL  (SRF-PLL synchronised, current-controlled injection)'
'  The converter measures the bus angle with a synchronous-reference-'
'  frame PLL and injects controlled current INTO that frame -- it'
'  follows the grid, it does not form it:'
''
'    PLL:   x_p'' = Ki_pll * v_q'
'           th_pll'' = ws*( 1 + Kp_pll*v_q + x_p ) - ws'
'    (v_q = the q-axis bus voltage seen through th_pll; v_q -> 0'
'     locks the PLL to the bus phasor)'
''
'    current loops: first-order tracking of (Id*, Iq*) with limits;'
'    P = V*Id,  Q = -V*Iq  at the point of connection.'
''
'  IEEE 1547 grid support shapes the references: volt-var Q(V),'
'  frequency-watt P(f) and voltage ride-through behaviour.'
''
ex
''
'STATE VARIABLES'
'  PLL states (x_p, th_pll), current-loop states, + source states'
'  (DC link / SOC / wind chain) per variant.'
''
'ASSUMPTIONS AND LIMITS'
'  Average-value model; stiff-grid assumption weakens in very weak'
'  grids (low SCR) where PLL dynamics dominate -- exactly the regime'
'  the small-signal tool exposes; unbalanced faults not modelled.'
''
'REFERENCES'
'  Kaura & Blasko, PLL synchronisation, IEEE Trans. IA, 1997.'
'  Chung, "Phase-locked loop for grid-connected...", 2000.'
'  Yazdani & Iravani, Voltage-Sourced Converters, 2010, ch. 8.'
'  IEEE Std 1547-2018.'
};
end

function L = thWT3()
L = { ...
'MODEL  (type-3 DFIG wind turbine)'
'  Induction machine of 3rd order (slip, rotor flux components) with'
'  the rotor winding driven by a vector-controlled converter:'
''
'    aero      Pm = 0.5 rho A Cp(lambda,beta) v_w^3   (pu-normalised)'
'    shaft     two-mass turbine-generator with stiffness/damping'
'    machine   3rd-order induction model (stator transients removed)'
'    rotor VSC torque/reactive control tracks the MPPT curve'
''
'  A gust event ramps the wind speed v_w; the MPPT + pitch limit the'
'  captured power and the DFIG rides through the transient.'
''
'STATE VARIABLES'
'  slip, rotor flux (2), shaft states (2), converter/control states.'
''
'ASSUMPTIONS AND LIMITS'
'  Crowbar action and unbalanced ride-through not modelled; converter'
'  is average-value; protection settings are out of scope.'
''
'REFERENCES'
'  Ekanayake et al., DFIG dynamic modelling, IEEE Trans. PWRS, 2003.'
'  Holdsworth et al., fixed vs DFIG comparison, 2003.'
'  Anaya-Lara et al., Wind Energy Generation, 2009, ch. 4.'
};
end

function L = thWT12(tag)
if strcmp(tag,'WT2'), ex = 'Type 2 adds an EXTERNAL ROTOR RESISTANCE control: slip is allowed to vary a few percent, softening gust torque peaks.';
else, ex = 'Type 1 is the plain squirrel-cage machine: nearly fixed speed, stall or active-stall regulated.'; end
L = { ...
'MODEL  (fixed-speed induction generator, directly grid-coupled)'
'  Squirrel-cage induction machine on the network with a soft-starter'
'  bypassed in operation; reactive magnetising demand is drawn from'
'  the grid (usually compensated by capacitors at the terminal):'
''
'    aero    Pm = 0.5 rho A Cp(lambda) v_w^3'
'    shaft   two-mass model (drive-train oscillations matter here)'
'    machine induction model with slip s as the key state'
''
ex
''
'STATE VARIABLES'
'  slip, shaft states (2), flux states.'
''
'ASSUMPTIONS AND LIMITS'
'  No converter, so no fault-ride-through shaping: terminal voltage'
'  dips pull the machine toward overspeed -- the classic stability'
'  concern the time-domain tool reproduces.'
''
'REFERENCES'
'  Ackermann (ed.), Wind Power in Power Systems, ch. 24-25.'
'  Heier, Grid Integration of Wind Energy, 3rd ed.'
'  Slootweg et al., general wind model, IEEE Trans. PWRS, 2003.'
};
end

function L = thShuntFac(ty)
if strcmp(ty,'SVC')
    L1 = { ...
'MODEL  (Static Var Compensator - thyristor-controlled susceptance)'
'  The SVC is a variable shunt susceptance B holding its bus voltage:'
''
'    steady state   Q = B * |V|^2 ,   B in [Bmin, Bmax]'
'    regulator      dB/dt = (Kr/Tr)*(Vref - V) + Kaw*( sat(B) - B )'
''
'  The IMPEDANCE-type limit is the SVC signature: at the ceiling the'
'  device becomes a fixed capacitor, so its vars collapse with V^2 --'
'  support fades exactly when the network needs it most.'
''
'  An optional droop tilts the V-Q characteristic so parallel'
'  compensators share duty predictably.'
    };
else
    L1 = { ...
'MODEL  (STATCOM - voltage-source-converter shunt compensator)'
'  The STATCOM is a controlled CURRENT source holding its bus voltage:'
''
'    steady state   Q = |V| * I ,   I in [Imin, Imax]'
'    regulator      dI/dt = (Kr/Tr)*(Vref - V) + Kaw*( sat(I) - I )'
''
'  The CURRENT-type limit is the key advantage over an SVC: at the'
'  ceiling the vars fall only linearly with V (not with V^2), so'
'  support survives deep sags [Hingorani & Gyugyi].'
    };
end
L = [L1; { ...
''
'ANTI-WINDUP'
'  The Kaw back-calculation term bleeds the regulator state back to'
'  its saturated value, so recovery from a limit is immediate and'
'  overshoot-free [Astrom & Hagglund].'
''
'STATE VARIABLES'
'  one regulator state (B or I) + POD states when the supplementary'
'  controller is enabled (card below).'
''
'PARAMETERS'
'  Vref, Kr, Tr, Kaw, droop, and the limit pair (Bmin/Bmax or'
'  Imin/Imax) - all editable in "FACTS parameters...".'
''
'ASSUMPTIONS AND LIMITS'
'  Fundamental-frequency injection only (no harmonics); converter'
'  losses neglected; single-phase-equivalent balanced model.'
''
'REFERENCES'
'  Hingorani & Gyugyi, Understanding FACTS, 2000, ch. 5.'
'  Kundur, 1994, ch. 11.   CIGRE TB 145.'
}];
end

function L = thSeriesFac(ty)
switch ty
case 'TCSC', hd = { ...
'MODEL  (Thyristor-Controlled Series Capacitor)'
'  Continuously-variable series compensation of the host line:'
''
'    x_eff = x * (1 - k) ,        k in [kmin, kmax]'
'    dk/dt = ( k_ord - k ) / Tc   (firing-control lag)'
''
'  Raising k cancels line reactance, shortening the line electrically:'
'  transfer capability rises as 1/x_eff and the transmission angle'
'  relaxes.  k_ord is the setting, or the POD output when enabled.'
};
case 'TSSC', hd = { ...
'MODEL  (Thyristor-Switched Series Capacitor)'
'  Step-switched series compensation: capacitor modules are inserted'
'  in discrete blocks, so k takes a few fixed values only:'
''
'    x_eff = x * (1 - k) ,   k in {0 ... kmax} by steps'
''
'  No continuous modulation - and therefore no POD channel: the TSSC'
'  reshapes the steady state, not the oscillations.'
};
otherwise, hd = { ...
'MODEL  (Static Synchronous Series Compensator)'
'  A series VSC injecting a controllable quadrature voltage Vse into'
'  the line (|Vse| <= Vsemax).  In compensation form it emulates'
''
'    x_eff = x * (1 - k) ,        k in [kmin, kmax]'
'    dk/dt = ( k_ord - k ) / Tc'
''
'  but, being a converter, the injection is INDEPENDENT of line'
'  current - an SSSC keeps compensating through light loading where'
'  a capacitor''s effect fades [Hingorani & Gyugyi].'
};
end
L = [hd; { ...
''
'NETWORK COUPLING'
'  The device stamps  dY = 1/(r + jx(1-k)) - 1/(r + jx(1-k0))  onto'
'  Ybus at every step (state-dependent admittance), so power flow,'
'  small-signal and time domain all see the same compensated line.'
''
'STATE VARIABLES'
'  k (one lag state) + POD states when enabled (TCSC/SSSC).'
''
'PARAMETERS'
'  kcomp (setting), kmin/kmax, Tc, and Vsemax for the SSSC.'
''
'ASSUMPTIONS AND LIMITS'
'  Fundamental-frequency model: SSR interaction, harmonics and gate-'
'  level firing are beyond scope (see CIGRE/IEEE SSR guides).'
''
'REFERENCES'
'  Hingorani & Gyugyi, Understanding FACTS, 2000, ch. 6.'
'  Kundur, 1994, ch. 11.'
}];
end

function L = thUPFC()
L = { ...
'MODEL  (Unified Power Flow Controller = STATCOM + SSSC, common DC)'
'  A shunt VSC at the sending bus and a series VSC in the line share'
'  one DC capacitor.  Two operating modes are implemented:'
''
'  COMPOSITION MODE  (mode = comp)'
'    shunt half  : STATCOM law    Q = |V| I, holds Vref'
'    series half : SSSC law       x_eff = x (1 - k), |Vse| <= Vsemax'
''
'  P-Q FLOW-CONTROL MODE  (mode = pq)'
'    the corridor DELIVERS the commanded  Pset + jQset  at its'
'    receiving end while the shunt converter holds Vref and the DC'
'    link supplies the series converter''s real power:'
''
'      P_shunt = P_series          (DC-link active-power balance)'
''
'    Power flow solves this with line f-t replaced by the commanded'
'    transfer (the augmented Newton in psdat_system).'
''
'STATE VARIABLES'
'  shunt regulator state, series lag state, + POD when enabled.'
''
'PARAMETERS'
'  bus / Vref / Imax / Imin (shunt),  kcomp / Vsemax (series),'
'  Pset / Qset (P-Q mode) - all in "FACTS parameters...".'
''
'ASSUMPTIONS AND LIMITS'
'  Lossless converters and DC link; fundamental frequency; the P-Q'
'  command must be feasible for the network or the solver reports'
'  divergence honestly.'
''
'REFERENCES'
'  Gyugyi et al., "The unified power flow controller", IEEE Trans.'
'  Power Delivery, 1995.   Hingorani & Gyugyi, ch. 8.'
};
end

function L = thIPFC()
L = { ...
'MODEL  (Interline Power Flow Controller = two series VSCs, common DC)'
'  Series converters in TWO different lines share one DC bus, letting'
'  the device shift real power between corridors:'
''
'  COMPOSITION MODE  (mode = comp)'
'    each converter emulates series compensation on its own line:'
'    x_eff,1 = x1 (1 - k1),   x_eff,2 = x2 (1 - k2)'
''
'  P-Q MODE  (mode = pq)'
'    master line 1 delivers  P1set + jQ1set;'
'    slave  line 2 delivers  Q2set  and supplies whatever real power'
'    balances the DC link:'
''
'      P_se1 + P_se2 = 0            (DC-link constraint)'
''
'    solved simultaneously with the network by the augmented Newton.'
''
'STATE VARIABLES'
'  the two series lag states (composition mode).'
''
'PARAMETERS'
'  kcomp / kcomp2, line-2 endpoints (f2-t2, same sending bus),'
'  Vsemax, P1set / Q1set / Q2set.'
''
'ASSUMPTIONS AND LIMITS'
'  Lossless DC exchange; both lines must terminate the same sending'
'  bus (the implemented topology); feasibility as for the UPFC.'
''
'REFERENCES'
'  Gyugyi, Sen & Schauder, "The interline power flow controller",'
'  IEEE Trans. Power Delivery, 1999.   Hingorani & Gyugyi, ch. 8.'
};
end

function L = thPOD()
L = { ...
''
'---------------------------------------------------------------'
'SUPPLEMENTARY POD / WADC  (this device type can carry one)'
'  A damping controller modulates the device order from a measured'
'  signal y (local or wide-area with channel delay tau):'
''
'    u = K * [ sTw/(1+sTw) ] * [ (1+sT1)/(1+sT2) ]^nc * y(t - tau)'
'    u clamped to [lo, hi], added to the device reference'
''
'  The washout passes CHANGES only (no steady-state bias); the lead-'
'  lag stages supply the phase advance the residue analysis asks for.'
'  Regulation variants (P / PI / PID / lag / low-pass) reuse the same'
'  slot with their textbook transfer functions - the editor shows'
'  each form live.'
''
'  TUNING PATHS'
'  Recommended  : textbook starting values per type and signal.'
'  Auto-tune    : probes d(lambda)/dK of the target mode, designs the'
'                 phase from the residue angle, then walks the gain up'
'                 with a full eigenvalue check at every step.'
'  Design tab   : residue-based synthesis on a chosen machine.'
''
'  REFERENCES'
'  Larsen & Swann, 1981 (structure).  Pagola, Perez-Arriaga & Verghese,'
'  residues, IEEE Trans. PWRS, 1989.  Kundur, ch. 12.  Astrom &'
'  Hagglund, Advanced PID Control (anti-windup forms).'
};
end

% =========================================================================
%                 KEYBOARD SHORTCUTS + CONTEXT MENU
% =========================================================================
% The standard editor bindings, so common actions cost one keystroke:
%   Delete/Backspace  remove the selection          Esc  back to Select
%   Ctrl+Z / Ctrl+Y   undo / redo                   F    fit the view
%   Ctrl+C / Ctrl+V   copy / paste a bus (type, V set, load, shunt ride along)
%   Ctrl+A            select every bus              Ctrl+S / Ctrl+O  save/open
%   arrows            nudge the selected bus (Shift = larger steps)
% Keys are inert while an analysis runs (Stop/Reset are the run controls),
% and they never fire while typing in an edit field (the field consumes its
% own keystrokes before the figure sees them).
function onKeyPress(src,ev)
fig = src;
h = guidata(fig); if ~isstruct(h) || ~isfield(h,'ED'), return; end
if isBusy(fig), return; end
key = ''; try, key = lower(ev.Key); catch, return; end
mods = {}; try, mods = ev.Modifier; catch, end
ctrl = any(strcmpi(mods,'control')) || any(strcmpi(mods,'command'));
switch key
case {'delete','backspace'}
    onDelSel(fig,[]);
case 'escape'
    h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.lineFrom=0;
    guidata(fig,h); showProps(fig); setTool(fig,1);
case 'z', if ctrl, onUndo(fig,[]); end
case 'y', if ctrl, onRedo(fig,[]); end
case 'c', if ctrl, copySel(fig); end
case 'v', if ctrl, pasteSel(fig); end
case 'a'
    if ctrl && nbus(h.NET) > 0
        h.ED.selkind='bus'; h.ED.selidx=1; h.ED.selset=1:nbus(h.NET);
        guidata(fig,h); showProps(fig); redraw(fig);
        set(h.status,'String',sprintf('%d buses selected - Arrange... aligns them, Delete removes them',nbus(h.NET)));
    end
case 's', if ctrl, onSave(fig,[]); end
case 'o', if ctrl, onOpen(fig,[]); end
case 'f', if ~ctrl, fitView(fig); redraw(fig); end
case {'leftarrow','rightarrow','uparrow','downarrow'}
    nudgeSel(fig, key, any(strcmpi(mods,'shift')));
end
end

function copySel(fig)
% Ctrl+C: capture the selected bus as a reusable template
h = guidata(fig);
if ~strcmp(h.ED.selkind,'bus') || h.ED.selidx < 1 || h.ED.selidx > nbus(h.NET)
    set(h.status,'String','copy: select a BUS first (Ctrl+C copies its type, V set, load and shunt)');
    return;
end
i = h.ED.selidx; NET = h.NET;
cb = struct('btype',NET.btype(i),'Vset',NET.Vset(i),'Pd',NET.Pd(i), ...
            'Qd',NET.Qd(i),'Bs',NET.Bs(i),'x',NET.bx(i),'y',NET.by(i));
setappdata(fig,'clipbus',cb);
set(h.status,'String',sprintf('bus %d copied - Ctrl+V pastes a duplicate beside it',i));
end

function pasteSel(fig)
% Ctrl+V: paste the copied bus as a NEW bus (never a second slack), offset
% from the original so the duplicate is immediately visible and draggable
h = guidata(fig); cb = getappdata(fig,'clipbus');
if isempty(cb), set(h.status,'String','nothing to paste - Ctrl+C a bus first'); return; end
h = pushUndo(h);
sp = curspan(h);
h.NET = addBus(h.NET, cb.x + 0.06*sp, cb.y - 0.06*sp);
i = nbus(h.NET);
bt = cb.btype; if bt == 3, bt = 1; end          % one slack per network
h.NET.btype(i) = bt;   h.NET.Vset(i) = cb.Vset;
h.NET.Pd(i)    = cb.Pd; h.NET.Qd(i)  = cb.Qd;  h.NET.Bs(i) = cb.Bs;
h.ED.selkind = 'bus'; h.ED.selidx = i; h.ED.selset = i;
guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig);
autoPF(fig, sprintf('bus %d pasted', i));
end

function nudgeSel(fig, key, big)
% arrow keys: nudge the selected bus (its machines + FACTS ride along);
% the same live-edit contract as a mouse drag, so no undo churn per tap
h = guidata(fig);
if ~strcmp(h.ED.selkind,'bus') || h.ED.selidx < 1 || h.ED.selidx > nbus(h.NET), return; end
st = 0.012*curspan(h); if big, st = st*4; end
dx = 0; dy = 0;
switch key
case 'leftarrow',  dx = -st;
case 'rightarrow', dx =  st;
case 'uparrow',    dy =  st;
case 'downarrow',  dy = -st;
end
i = h.ED.selidx;
h.NET.bx(i) = h.NET.bx(i) + dx; h.NET.by(i) = h.NET.by(i) + dy;
g = find(h.NET.g_bus == i);
for gg = g(:)', h.NET.gx(gg) = h.NET.gx(gg) + dx; h.NET.gy(gg) = h.NET.gy(gg) + dy; end
h.NET = refacts(h.NET, i);
guidata(fig,h); redraw(fig);
end

function showCtxMenu(fig, kind)
% open the canvas context menu at the cursor; theory entry needs a selection
h = guidata(fig);
if ~isfield(h,'ctxMenu') || ~ishghandle(h.ctxMenu), return; end
if isfield(h,'ctxTheory') && ishghandle(h.ctxTheory)
    set(h.ctxTheory,'Enable',tern(~strcmp(kind,'none'),'on','off'));
end
u = get(fig,'Units'); set(fig,'Units','pixels');
cp = get(fig,'CurrentPoint'); set(fig,'Units',u);
try, set(h.ctxMenu,'Position',cp(1,1:2),'Visible','on'); catch, end
end

function ctxProps(src,~)   %#ok<INUSD>
fig = gcbf; if isempty(fig) || ~ishghandle(fig), return; end
setTab('props', fig); showProps(fig);
end

function noTips(f)
% Disable hover tooltip descriptions on EVERY control of the given window
% (user preference: the pop-up description bubbles read as clutter).  The
% TooltipString properties stay in the creation calls as in-code
% documentation; this one sweep blanks them all at runtime, so re-enabling
% is a single-line change (delete the noTips calls).
try, set(findall(f,'Type','uicontrol'),'TooltipString',''); catch, end
end

% =========================================================================
%                       FILE / BENCHMARK / EXPORT
% =========================================================================
function onNew(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); h = pushUndo(h);
h.NET = emptyNet(); h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
h.ED.xlim=[0 1000]; h.ED.ylim=[-680 20];
guidata(fig,h); refreshList(fig); showProps(fig); redraw(fig); set(h.status,'String','new network');
end
function onLoadBench(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; v = get(src,'Value');
names = {'','IEEE9','IEEE14','IEEE30','IEEE39','Kundur2A','case68'};
if v >= 2, doLoadBench(fig, names{v}); end
set(src,'Value',1);
end
function doLoadBench(fig, sys)
h = guidata(fig);
try, NET = psdat_benchmark(sys); catch err, errordlg(err.message,'Load benchmark'); return; end
if ~isfield(NET,'facts'), NET.facts = emptyFacts(); end   % benchmarks carry no FACTS
if ~isempty(h.NET.btype), h = pushUndo(h); end
h.NET = NET; h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
h.ED.homeXY = [NET.bx(:) NET.by(:)];              % canonical layout for Restore Default
guidata(fig,h); fitView(fig); refreshList(fig); showProps(fig); redraw(fig);
set(h.status,'String',sprintf('loaded %s (%d buses)',NET.name,nbus(NET)));
end
function onSave(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
[f,p] = uiputfile({'*.json','Shared network (Python + MATLAB) (*.json)'; ...
                   '*.mat','MATLAB network (*.mat)'}, 'Save network', [h.NET.name '.json']);
if isequal(f,0), return; end
NET = h.NET;
if ~isempty(regexpi(f,'\.json$','once'))
    % the SHARED format: the same file opens in the Python lab unchanged
    try, psdat_netjson(fullfile(p,f), NET);
    catch err, errordlg(err.message,'Save'); return; end
else
    save(fullfile(p,f),'NET');
end
set(h.status,'String',['saved ' f '  (json opens in BOTH editions)']);
end
function onOpen(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig);
[f,p] = uigetfile({'*.json;*.mat','PSDAT networks (*.json, *.mat)'; ...
                   '*.json','Shared network (Python + MATLAB) (*.json)'; ...
                   '*.mat','MATLAB network (*.mat)'}, 'Open network');
if isequal(f,0), return; end
if ~isempty(regexpi(f,'\.json$','once'))
    try, NETIN = psdat_netjson(fullfile(p,f));
    catch err, errordlg(['not a PSDAT network json: ' err.message],'Open'); return; end
else
    S = load(fullfile(p,f)); if ~isfield(S,'NET'), errordlg('file has no NET variable','Open'); return; end
    NETIN = S.NET;
    if ~isfield(NETIN,'facts'), NETIN.facts = emptyFacts(); end   % older saves predate FACTS
end
h = pushUndo(h); h.NET = NETIN; h.ED.selkind='none'; h.ED.selidx=0; h.ED.selset=[]; h.ED.pf=[]; h.ED.lineFrom=0;
h.ED.homeXY = [h.NET.bx(:) h.NET.by(:)];
guidata(fig,h); fitView(fig); refreshList(fig); showProps(fig); redraw(fig); set(h.status,'String',['opened ' f]);
end
function onAppClose(~,~)
% app teardown (DeleteFcn -- deletion continues); clear any legacy root hook
try, set(groot,'DefaultAxesCreateFcn','remove'); catch, end
end

% ---- callback-safe result windows ---------------------------------------
% Creating a figure + axes + plots from INSIDE a uicontrol callback can
% deadlock the new MATLAB desktop.  deferFig runs the plotting function on a
% one-shot timer AFTER the current callback has fully unwound, on the main
% event loop, where figure creation is safe.  Falls back to an inline call
% where timers are unavailable (Octave).
function deferFig(fig, fn)
try
    t = timer('StartDelay',0.08,'ExecutionMode','singleShot', ...
        'TimerFcn',@(o,~) deferRun(fig, fn), 'StopFcn',@(o,~) tdelete(o), ...
        'Name','psdatDeferredFigure');
    start(t);
catch
    try, fn(); catch, end
end
end
function tdelete(o)
% delete a timer only when it is valid and fully stopped -- and never throw
try, if isvalid(o) && strcmp(get(o,'Running'),'off'), delete(o); end, catch, end
end
function deferRun(fig, fn)
if ~ishghandle(fig), return; end
bz = [];
try, bz = beBusy(fig); catch, end                  %#ok<NASGU>
try
    fn();
catch err
    try, h = guidata(fig); set(h.status,'String',['result window failed: ' err.message]); catch, end
end
end
function noAxInteract(ax)
% Disable the NEW-desktop deferred axes interactions (zoom/pan/datatip
% installers).  They are queued asynchronously after an axes first renders;
% if the axes is deleted before the queue drains, MATLAB prints
% "Invalid or deleted object ... createWebInteraction".  The app manages its
% own interactivity, so switching the default machinery off both silences the
% race and removes per-redraw overhead.  No-ops on Octave / classic graphics.
%
% TOOLBAR: materialize a REAL (empty, hidden) axes toolbar up front instead
% of leaving the lazy default.  An untouched axes stores a
% GraphicsPlaceholder in ax.Toolbar, and the desktop's deferred "stranded
% toolbar" sweep (WebToolbarController>cleanupStrandedToolbars) later walks
% those placeholders and can die inside createToolbar with
%   "Unrecognized method, property, or field 'setPosition' for class
%    'matlab.graphics.GraphicsPlaceholder'".
% A real toolbar object -- even empty and invisible -- takes every axes this
% app makes out of that sweep entirely.
try, disableDefaultInteractivity(ax); catch, end
try, set(ax,'Interactions',[]); catch, end
try
    tb = axtoolbar(ax);                    % real AxesToolbar, never a placeholder
    set(tb,'Visible','off');
catch
    try, ax.Toolbar.Visible = 'off'; catch, end   % classic graphics / Octave path
end
end
function onExport(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = gcbf; h = guidata(fig); fmt = get(src,'UserData');
[f,p] = uiputfile(['*.' fmt],'Export diagram',[h.NET.name '.' fmt]);
if isequal(f,0), return; end
tmp = figure('Visible','off','Color','w','Units','normalized','Position',[.1 .1 .6 .6]);
try
    ax2 = copyobj(h.ax, tmp); set(ax2,'Units','normalized','Position',[.05 .05 .9 .9]);
    noAxInteract(ax2);
    print(tmp, fullfile(p,f), ['-d' fmt]);
    set(h.status,'String',['exported ' f]);
catch err
    errordlg(err.message,'Export failed');
end
drawnow;                                           % drain pending graphics work first
if ishandle(tmp), delete(tmp); end
drawnow limitrate;                                 % ... and the toolbar/interaction
end                                                % cleanup queued against tmp, so no
                                                   % stranded-toolbar sweep fires later

% =========================================================================
%                          ANALYSES
% =========================================================================
function [S,ok] = buildSystem(fig, pfm)
h = guidata(fig); S = []; ok = false;
try
    C = psdat_netcase(h.NET); S = psdat_system(C, C.UT, [], pfm); ok = true;
catch err
    errordlg(err.message,'Cannot analyse this network'); set(h.status,'String','error');
end
end
function b0 = figsnap(), b0 = findobj(0,'Type','figure'); end
function closeNew(fig,b0)
drawnow limitrate;                                 % settle pending graphics (throttled)
nowf = findobj(0,'Type','figure');
for f = nowf(:)', if f ~= fig && ~any(f == b0), try, close(f); catch, end, end, end
drawnow limitrate;                                 % drain the DELETIONS too: the desktop
end                                                % toolstrip must never touch a dead handle

function setResults(fig, RC)
% RC = cell of category structs, each struct('label',..,'L',{rows},'M',{maps});
% M{i} = {'bus'|'branch'|'gen', idx} for a clickable row, or [] otherwise.
h = guidata(fig);
if isempty(RC), RC = {struct('label','Results','L',{{'(no results)'}},'M',{{[]}})}; end
h.RC = RC; guidata(fig,h);
labels = cell(1,numel(RC)); for c = 1:numel(RC), labels{c} = RC{c}.label; end
set(h.ddCat, 'String', labels, 'Value', 1);
showCat(fig, 1);
end
function setReport(fig, L, map)
% simple one-category report (used by the non-tabular analyses)
if nargin < 3, map = {}; end
if isempty(map), map = cell(1, numel(L)); end
setResults(fig, {struct('label','Summary','L',{L(:)'},'M',{map})});
end
function showCat(fig, idx)
h = guidata(fig);
if ~isfield(h,'RC') || isempty(h.RC), return; end
idx = max(1, min(idx, numel(h.RC)));
set(h.ddCat, 'Value', idx);
set(h.res, 'String', h.RC{idx}.L, 'Value', 1);
h.repmap = h.RC{idx}.M; guidata(fig,h);
% sortable columns (Excel-style): tabular categories publish their column
% header; switching category always returns to the original order.
if isfield(h,'ddSort') && ishghandle(h.ddSort)
    C = h.RC{idx}; cols = {};
    if isfield(C,'hdr') && C.hdr >= 2 && numel(C.L) >= C.hdr
        cols = regexp(strtrim(C.L{C.hdr}), '\s+', 'split');
    end
    ss = {'Sort: original order'};
    for q = 1:numel(cols), ss{end+1} = ['Sort: ' cols{q}]; end   %#ok<AGROW>
    set(h.ddSort,'String',ss,'Value',1,'Enable',tern(numel(ss)>1,'on','off'));
    setappdata(fig,'resSort', struct('col',0,'dir',1));
    if isfield(h,'bSortDir') && ishghandle(h.bSortDir)
        set(h.bSortDir,'String','ascending');
    end
end
% statistics bar: each category can carry its own summary line (min/max,
% totals); categories without one get an honest row count.
if isfield(h,'resStat') && ishghandle(h.resStat)
    st = '';
    if isfield(h.RC{idx},'stat'), st = h.RC{idx}.stat; end
    if isempty(st), st = sprintf('%d lines', numel(h.RC{idx}.L)); end
    set(h.resStat,'String',st);
end
end

function onSortCol(src,~)
% pick the sort column; view-only, so never blocked
fig = gcbf; S = getappdata(fig,'resSort');
if ~isstruct(S), S = struct('col',0,'dir',1); end
S.col = get(src,'Value') - 1;                 % 0 = original order
setappdata(fig,'resSort',S); applySort(fig);
end

function onSortDir(src,~)
fig = gcbf; S = getappdata(fig,'resSort');
if ~isstruct(S), S = struct('col',0,'dir',1); end
S.dir = -S.dir;
set(src,'String',tern(S.dir>0,'ascending','descending'));
setappdata(fig,'resSort',S); applySort(fig);
end

function applySort(fig)
% re-render the current category sorted by the chosen column.  Header rows
% stay pinned on top, note/blank rows sink to the bottom, and the row ->
% component map is reordered IN LOCKSTEP so clicking a sorted row still
% selects the right component.  Numeric columns sort numerically, anything
% else lexicographically -- exactly the spreadsheet contract.
h = guidata(fig);
if ~isfield(h,'RC') || isempty(h.RC), return; end
idx = max(1, min(get(h.ddCat,'Value'), numel(h.RC)));
C = h.RC{idx}; L = C.L; M = C.M;
hdr = 0; if isfield(C,'hdr'), hdr = C.hdr; end
S = getappdata(fig,'resSort');
sc = 0; sd = 1;
if isstruct(S), sc = S.col; sd = S.dir; end
n = numel(L);
if sc >= 1 && hdr >= 1 && n > hdr+1
    body = (hdr+1):n;
    keep = true(1,numel(body)); vals = cell(1,numel(body));
    for q = 1:numel(body)
        toks = regexp(strtrim(L{body(q)}), '\s+', 'split');
        if isempty(toks) || isempty(toks{1}), keep(q) = false; vals{q} = ''; continue; end
        if sc <= numel(toks), vals{q} = toks{sc}; else, vals{q} = ''; end
    end
    bi = body(keep); vv = vals(keep);
    if ~isempty(bi)
        nums = str2double(vv);
        if all(isfinite(nums)), [~,ord] = sort(nums);
        else,                   [~,ord] = sort(lower(vv));
        end
        if sd < 0, ord = ord(end:-1:1); end
        newIdx = [1:hdr, bi(ord), body(~keep)];
        L = L(newIdx); M = M(newIdx);
    end
end
set(h.res,'String',L,'Value',1);
h.repmap = M; guidata(fig,h);
end
function onCat(src,~), if busyBlock(gcbf), return; end, showCat(gcbf, get(src,'Value')); end

function onResCopy(src,~)   %#ok<INUSD>
% copy the visible results table to the system clipboard, tab-preserving
fig = gcbf; h = guidata(fig);
L = get(h.res,'String'); if ischar(L), L = cellstr(L); end
if isempty(L), return; end
s = '';
for q = 1:numel(L), s = [s L{q} sprintf('\n')]; end          %#ok<AGROW>
ok = false;
try, clipboard('copy', s); ok = true; catch, end
if ok, set(h.status,'String',sprintf('copied %d lines to the clipboard', numel(L)));
else,  set(h.status,'String','clipboard is not available here - use CSV... instead');
end
end

function onResExport(src,~)   %#ok<INUSD>
% export the CURRENT result category as CSV (aligned columns -> comma cells)
if busyBlock(gcbf), return; end
fig = gcbf; h = guidata(fig);
if ~isfield(h,'RC') || isempty(h.RC)
    set(h.status,'String','run an analysis first - there is no table to export'); return;
end
idx = max(1, min(get(h.ddCat,'Value'), numel(h.RC)));
lab = h.RC{idx}.label; L = h.RC{idx}.L; if ischar(L), L = cellstr(L); end
stem = regexprep(lower(lab), '[^a-z0-9]+', '_');
[f,p] = uiputfile('*.csv','Export results table',sprintf('%s_%s.csv', h.NET.name, stem));
if isequal(f,0), return; end
fid = fopen(fullfile(p,f),'w');
if fid < 0, errordlg('cannot write the file','Export'); return; end
for q = 1:numel(L)
    row = regexprep(strtrim(L{q}), '\s{2,}', ',');   % 2+ spaces = a column break
    fprintf(fid, '%s\n', row);
end
fclose(fid);
set(h.status,'String',['exported ' f]);
end

function onResClick(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% click a row -> select + highlight; double-click -> also zoom + properties
fig = gcbf; h = guidata(fig); v = get(src,'Value');
if ~isfield(h,'repmap') || v > numel(h.repmap) || isempty(h.repmap{v}), return; end
mp = h.repmap{v}; h.ED.selkind = mp{1}; h.ED.selidx = mp{2};
if strcmp(mp{1},'bus'), h.ED.selset = mp{2}; else, h.ED.selset = []; end
guidata(fig,h); syncListSel(fig); showProps(fig); redraw(fig);
if strcmp(get(fig,'SelectionType'),'open'), zoomToSel(fig); setTab('props'); end
end

function syncListSel(fig)
% (optional) mirror the current selection into the left component list, if present
h = guidata(fig);
if ~isfield(h,'list') || ~ishghandle(h.list) || ~isfield(h,'listmap'), return; end
for v = 1:numel(h.listmap)
    mp = h.listmap{v};
    if strcmp(mp{1}, h.ED.selkind) && isequal(mp{2}, h.ED.selidx)
        set(h.list, 'Value', v); return;
    end
end
end

function syncReportSel(fig)
% switch the Results panel to the category holding the selection and
% highlight its row (full bidirectional link across all categories)
h = guidata(fig);
if ~isfield(h,'RC') || isempty(h.RC), return; end
for c = 1:numel(h.RC)
    M = h.RC{c}.M;
    for v = 1:numel(M)
        if iscell(M{v}) && strcmp(M{v}{1}, h.ED.selkind) && isequal(M{v}{2}, h.ED.selidx)
            showCat(fig, c); set(h.res, 'Value', v); return;
        end
    end
end
end

function onPF(src,~)
fig = ancestor(src,'figure'); if isempty(fig), fig = gcbf; end   % src = the app figure when the run queue dispatches
if runGate(fig,'pf'), return; end
bz = beBusy(fig);   %#ok<NASGU>
armFreshRun(fig);              % the last run's stop request must not kill this one
h = guidata(fig); pfm = h.PFN{get(h.ddPF,'Value')};
set(h.status,'String','solving power flow...'); drawnow;
[S,ok] = buildSystem(fig,pfm); if ~ok, return; end
h = markrun(fig, h, 'pf');
n = S.n; V = S.V0; th = S.TH0*180/pi; Vc = S.V0.*exp(1i*S.TH0);
flows = zeros(nbr(h.NET),4); fdir = zeros(nbr(h.NET),1);
useSB = isfield(S,'branch') && size(S.branch,1) == nbr(h.NET);   % engine branch = WITH series compensation
for k = 1:nbr(h.NET)
    if useSB      % r/x/b/tap as the SOLVER saw them (x_eff = x*(1-k) for series FACTS)
        f = round(S.branch(k,1)); t = round(S.branch(k,2));
        r = S.branch(k,3); x = S.branch(k,4); bb = S.branch(k,5); a = S.branch(k,9);
    else
        f = h.NET.br_f(k); t = h.NET.br_t(k); r = h.NET.br_r(k); x = h.NET.br_x(k); bb = h.NET.br_b(k);
        a = h.NET.br_tap(k);
    end
    if a==0, a = 1; end
    y = 1/(r+1i*x); bc = 1i*bb/2;
    Sf = Vc(f)*conj((y+bc)/(a*a)*Vc(f) - y/conj(a)*Vc(t));
    St = Vc(t)*conj((y+bc)*Vc(t) - y/a*Vc(f));
    flows(k,:) = [real(Sf)*100 imag(Sf)*100 real(St)*100 real(Sf+St)*100]; fdir(k) = real(Sf);
end
% P-Q-controlled corridors (UPFC / IPFC): show the commanded / DC-set flow, not
% the raw admittance flow (line removed or series source outside Ybus).
if isfield(S,'pqlines') && ~isempty(S.pqlines)
    for q = 1:size(S.pqlines,1)
        pf_ = S.pqlines(q,1); pt_ = S.pqlines(q,2);
        for k = 1:nbr(h.NET)
            if (h.NET.br_f(k)==pf_ && h.NET.br_t(k)==pt_) || (h.NET.br_f(k)==pt_ && h.NET.br_t(k)==pf_)
                flows(k,:) = [S.pqlines(q,3) S.pqlines(q,4) S.pqlines(q,3) 0];
                fdir(k) = S.pqlines(q,3)/100 * (2*(h.NET.br_f(k)==pf_)-1);
                break;
            end
        end
    end
end
h.ED.pf = struct('V',V,'th',th,'flowdir',fdir,'flows',flows, ...
    'Pg',S.Pg(:)*S.baseMVA,'Qg',S.Qg(:)*S.baseMVA); guidata(fig,h); redraw(fig); syncFlowTimer(fig);
pfReport(fig, S, flows, S.baseMVA, n, V, th);
setTab('report', fig); set(h.status,'String','power flow done');
end

function pfReport(fig, S, flows, base, n, V, th)
% build the category tables (Bus/Line/Generator/Load/Shunt/Summary) for the
% Results panel; every row carries a map linking it to its SLD component
h = guidata(fig); NET = h.NET; RC = {};
hd = sprintf('[%s]  %d buses, %d lines, %d gen', pfstr(S), S.n, nbr(NET), ngen(NET));
Lb = {hd; sprintf('%-3s %-8s %-8s %-8s %-8s','bus','|V|pu','ang','Pg','Qg')}; Mb = {[];[]};
for i = 1:n
    Lb{end+1} = sprintf('%-3d %-8.4f %-8.2f %-8.1f %-8.1f', i, V(i), th(i), S.Pg(i)*base, S.Qg(i)*base);
    Mb{end+1} = {'bus', i};
end
[vmn,ivn] = min(V); [vmx,ivx] = max(V);
RC{end+1} = struct('label','Bus results','L',{Lb},'M',{Mb}, ...
    'hdr',2,'stat',sprintf('%d buses  -  |V| %.4f (bus %d) ... %.4f (bus %d)', n, vmn, ivn, vmx, ivx));
Ll = {hd; sprintf('%-7s %-7s %-7s %-7s %-6s','line','Pfrom','Qfrom','loss','load%')}; Ml = {[];[]};
SfM = max([hypot(flows(:,1),flows(:,2)); 1e-6]);
for k = 1:nbr(NET)
    ld = 100*hypot(flows(k,1),flows(k,2))/SfM;
    Ll{end+1} = sprintf('%d-%-5d %-7.1f %-7.1f %-7.2f %-6.0f', NET.br_f(k), NET.br_t(k), flows(k,1), flows(k,2), flows(k,4), ld);
    Ml{end+1} = {'branch', k};
end
RC{end+1} = struct('label','Line results','L',{Ll},'M',{Ml}, ...
    'hdr',2,'stat',sprintf('%d lines  -  total losses %.2f MW', nbr(NET), sum(flows(:,4))));
% ---- FACTS operating points: SHOW what every device is doing ------------
if isfield(S,'facts') && ~isempty(S.facts)
    Lf = {hd; sprintf('%-9s %-9s %-24s','device','where','solved operating point')}; Mf = {[];[]};
    for kf = 1:numel(S.facts)
        d = S.facts(kf); ty = upper(d.type); wh = ''; op = '';
        if any(strcmpi(ty,{'SVC','STATCOM'}))
            wh = sprintf('bus %d', round(d.bus));
            q = []; if isfield(d,'Q_'), q = d.Q_; end
            sat = isfield(d,'sat_') && ~isempty(d.sat_) && d.sat_;
            if ~isempty(q), op = sprintf('Q = %+.1f MVAr%s', q*100, tern(sat,'  (AT LIMIT)',''));
            else, op = 'holds its bus voltage'; end
        elseif any(strcmpi(ty,{'TCSC','TSSC','SSSC'}))
            wh = sprintf('line %d-%d', round(d.f), round(d.t));
            kc = min(max(d.kcomp, d.kmin), d.kmax);
            op = sprintf('k = %.0f%%  ->  x_eff = %.0f%% of x', kc*100, (1-kc)*100);
        elseif strcmpi(ty,'IPFC')
            wh = sprintf('lines %d-%d / %d-%d', round(d.f), round(d.t), round(d.f2), round(d.t2));
            if isfield(d,'rep') && isstruct(d.rep) && isfield(d.rep,'S1')
                op = sprintf('P1=%.1f Q1=%.1f | Q2=%.1f MW/MVAr (DC-coupled)', ...
                    real(d.rep.S1), imag(d.rep.S1), imag(d.rep.S2));
            else, op = 'P-Q mode'; end
        else
            wh = '-'; op = '';
        end
        Lf{end+1} = sprintf('%-9s %-9s %-24s', ty, wh, op);   %#ok<AGROW>
        Mf{end+1} = [];                                        %#ok<AGROW>
    end
    Lf{end+1} = ''; Mf{end+1} = [];
    Lf{end+1} = '(series compensation is inside the line'; Mf{end+1} = [];
    Lf{end+1} = ' flows above; shunt Q is at its bus)';    Mf{end+1} = [];
    RC{end+1} = struct('label','FACTS','L',{Lf},'M',{Mf}, ...
        'hdr',2,'stat',sprintf('%d FACTS device(s) in the solved network', numel(S.facts)));
end
Lg = {hd; sprintf('%-4s %-4s %-8s %-8s %-8s','gen','bus','Pg(MW)','Qg(MVA)','|V|')}; Mg = {[];[]};
for k = 1:ngen(NET)
    i = NET.g_bus(k);
    Lg{end+1} = sprintf('%-4d %-4d %-8.1f %-8.1f %-8.4f', k, i, S.Pg(i)*base, S.Qg(i)*base, V(i));
    Mg{end+1} = {'gen', k};
end
RC{end+1} = struct('label','Generator results','L',{Lg},'M',{Mg}, ...
    'hdr',2,'stat',sprintf('%d units  -  total Pg %.1f MW, Qg %.1f MVAr', ...
    ngen(NET), sum(S.Pg(S.gb))*base, sum(S.Qg(S.gb))*base));
Ld = {hd; sprintf('%-4s %-7s %-7s %-7s %-7s %-6s %-6s','bus','Pd','Qd','|V|','ang','I pu','pf')}; Md = {[];[]};
for i = 1:n
    if NET.Pd(i) > 1e-9 || NET.Qd(i) > 1e-9
        Sl = hypot(NET.Pd(i),NET.Qd(i)); pf = 1; if Sl > 1e-9, pf = NET.Pd(i)/Sl; end
        Ipu = Sl/base/max(V(i),1e-6);
        Ld{end+1} = sprintf('%-4d %-7.1f %-7.1f %-7.4f %-7.2f %-6.3f %-6.3f', ...
            i, NET.Pd(i), NET.Qd(i), V(i), th(i), Ipu, pf);
        Md{end+1} = {'load', i};
    end
end
if numel(Ld) > 2
    RC{end+1} = struct('label','Load results','L',{Ld},'M',{Md}, ...
        'hdr',2,'stat',sprintf('total load %.1f MW + j%.1f MVAr', sum(NET.Pd), sum(NET.Qd)));
end
Ls = {hd; sprintf('%-4s %-11s %-8s','bus','Bsh(MVAr)','|V|')}; Ms = {[];[]};
for i = 1:n
    if NET.Bs(i) ~= 0
        Ls{end+1} = sprintf('%-4d %-11.1f %-8.4f', i, NET.Bs(i), V(i)); Ms{end+1} = {'bus', i};
    end
end
if numel(Ls) > 2, RC{end+1} = struct('label','Shunt results','L',{Ls},'M',{Ms},'hdr',2); end
[~,imn] = min(V); [~,imx] = max(V);
Lm = {'POWER-FLOW SUMMARY'; ''; sprintf('method     %s', pfstr(S)); ...
      sprintf('gen total  %.1f MW', sum(S.Pg(S.gb))*base); ...
      sprintf('load total %.1f MW', sum(S.PL0)*base); ...
      sprintf('losses     %.2f MW', sum(flows(:,4))); ...
      sprintf('min |V|    %.4f pu (bus %d)', V(imn), imn); ...
      sprintf('max |V|    %.4f pu (bus %d)', V(imx), imx)};
RC{end+1} = struct('label','Summary','L',{Lm},'M',{cell(1,numel(Lm))});
setResults(fig, RC);
end
function s = pfstr(S)
s = 'power flow';
if isfield(S,'pf') && isstruct(S.pf) && isfield(S.pf,'method')
    if isfield(S.pf,'iters') && ~isnan(S.pf.iters), s = sprintf('%s, %g iters', S.pf.method, S.pf.iters);
    else, s = S.pf.method; end
end
end

% ================== DATA TAB: editable input tables =======================
function onDatCat(src,~), if busyBlock(gcbf), return; end, datBuild(ancestor(src,'figure')); end
function datBuild(fig)
% (re)fill the Data table for the selected category from the LIVE network
h = guidata(fig); if ~isfield(h,'datL') || ~ishghandle(h.datL), return; end
NET = h.NET; c = get(h.ddDat,'Value');
rows = {}; map = {};
switch c
case 1
    rows{end+1} = sprintf('%-4s %-5s %-7s %-8s %-8s %-7s','bus','type','Vset','Pd(MW)','Qd(MVA)','Bs'); map{end+1} = [];
    tpn = {'PQ','PV','SL'};
    for i = 1:nbus(NET)
        rows{end+1} = sprintf('%-4d %-5s %-7.3f %-8.1f %-8.1f %-7.1f', i, ...
            tpn{max(1,min(3,NET.btype(i)))}, NET.Vset(i), NET.Pd(i), NET.Qd(i), NET.Bs(i)); %#ok<AGROW>
        map{end+1} = {'bus', i};                                                            %#ok<AGROW>
    end
case 2
    rows{end+1} = sprintf('%-3s %-7s %-8s %-8s %-8s %-6s','#','f-t','r(pu)','x(pu)','b(pu)','tap'); map{end+1} = [];
    for k = 1:nbr(NET)
        rows{end+1} = sprintf('%-3d %-7s %-8.4f %-8.4f %-8.4f %-6.3f', k, ...
            sprintf('%d-%d',NET.br_f(k),NET.br_t(k)), NET.br_r(k), NET.br_x(k), NET.br_b(k), NET.br_tap(k)); %#ok<AGROW>
        map{end+1} = {'branch', k};                                                         %#ok<AGROW>
    end
case 3
    rows{end+1} = sprintf('%-3s %-4s %-9s %-8s %-7s %-7s','#','bus','tech','Pg(MW)','Vset','S(MVA)'); map{end+1} = [];
    for k = 1:ngen(NET)
        rows{end+1} = sprintf('%-3d %-4d %-9s %-8.1f %-7.3f %-7.0f', k, NET.g_bus(k), ...
            NET.g_tag{k}, NET.g_Pg(k), NET.g_Vset(k), NET.g_S(k));                          %#ok<AGROW>
        map{end+1} = {'gen', k};                                                            %#ok<AGROW>
    end
otherwise
    rows{end+1} = sprintf('%-3s %-8s %-10s %-20s','#','type','where','key settings'); map{end+1} = [];
    for k = 1:nfac(NET)
        d = NET.facts(k); ty = upper(d.type);
        if isShuntFac(ty),      wh = sprintf('bus %d',d.bus);        ks = sprintf('Vref=%.3f',d.Vref);
        elseif isSeriesFac(ty), wh = sprintf('%d-%d',d.f,d.t);       ks = sprintf('kcomp=%.2f',d.kcomp);
        elseif strcmp(ty,'UPFC'), wh = sprintf('b%d %d-%d',d.bus,d.f,d.t); ks = sprintf('Vref=%.3f k=%.2f',d.Vref,d.kcomp);
        else,                   wh = sprintf('%d-%d',d.f,d.t);       ks = sprintf('kcomp=%.2f',d.kcomp);
        end
        rows{end+1} = sprintf('%-3d %-8s %-10s %-20s', k, ty, wh, ks);                      %#ok<AGROW>
        map{end+1} = {'facts', k};                                                          %#ok<AGROW>
    end
    if nfac(NET) == 0, rows{end+1} = '(no FACTS devices on the diagram)'; map{end+1} = []; end
end
h.DATmap = map; guidata(fig,h);
set(h.datL,'String',rows,'Value',max(1,min(get(h.datL,'Value'),numel(rows))));
datFields(fig);
end

function datFields(fig)
% expose the SELECTED row's editable parameters in the field strip below
h = guidata(fig); NET = h.NET;
v = get(h.datL,'Value'); mp = [];
if isfield(h,'DATmap') && v >= 1 && v <= numel(h.DATmap), mp = h.DATmap{v}; end
F = {};                                   % {label, value, key}
if iscell(mp)
    switch mp{1}
    case 'bus',    i = mp{2};
        F = {'Vset (pu)',NET.Vset(i),'b.Vset';'Pd (MW)',NET.Pd(i),'b.Pd'; ...
             'Qd (MVAr)',NET.Qd(i),'b.Qd';'Bs shunt (MVAr)',NET.Bs(i),'b.Bs'};
    case 'branch', k = mp{2};
        F = {'r (pu)',NET.br_r(k),'l.r';'x (pu)',NET.br_x(k),'l.x'; ...
             'b charging (pu)',NET.br_b(k),'l.b';'tap (0 = none)',NET.br_tap(k),'l.tap'};
    case 'gen',    k = mp{2};
        F = {'Pg (MW)',NET.g_Pg(k),'g.Pg';'Vset (pu)',NET.g_Vset(k),'g.Vset'; ...
             'rating S (MVA)',NET.g_S(k),'g.S'};
    case 'facts',  k = mp{2}; d = NET.facts(k); ty = upper(d.type);
        if isShuntFac(ty)
            F = {'Vref (pu)',d.Vref,'f.Vref';'droop',d.droop,'f.droop'};
            if strcmp(ty,'SVC'), F(end+1,:) = {'Bmax (pu)',d.Bmax,'f.Bmax'};
            else,                F(end+1,:) = {'Imax (pu)',d.Imax,'f.Imax'}; end
        elseif isSeriesFac(ty)
            F = {'kcomp',d.kcomp,'f.kcomp';'kmin',d.kmin,'f.kmin';'kmax',d.kmax,'f.kmax'};
        else
            F = {'Vref (pu)',d.Vref,'f.Vref';'kcomp',d.kcomp,'f.kcomp'};
        end
    end
end
ky = {}; if ~isempty(F), ky = F(:,3).'; end
h.DATF = struct('mp',{mp},'key',{ky}); guidata(fig,h);
for j = 1:4
    if j <= size(F,1)
        set(h.datLab{j},'String',F{j,1});
        set(h.datEd{j},'String',num2str(F{j,2},'%g'),'Visible','on');
    else
        set(h.datLab{j},'String',''); set(h.datEd{j},'String','','Visible','off');
    end
end
end

function onDatSel(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = ancestor(src,'figure'); h = guidata(fig);
datFields(fig);
v = get(h.datL,'Value'); mp = [];
if isfield(h,'DATmap') && v >= 1 && v <= numel(h.DATmap), mp = h.DATmap{v}; end
if iscell(mp)                              % mirror the selection onto the canvas
    h = guidata(fig); h.ED.selkind = mp{1}; h.ED.selidx = mp{2};
    h.ED.selset = tern(strcmp(mp{1},'bus'), mp{2}, []);
    guidata(fig,h); redraw(fig);
    if strcmp(get(fig,'SelectionType'),'open'), zoomToSel(fig); end
end
end

function onDatApply(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
fig = ancestor(src,'figure'); h = guidata(fig);
if ~isfield(h,'DATF') || ~iscell(h.DATF.mp), set(h.status,'String','select a data row first'); return; end
mp = h.DATF.mp; keys = h.DATF.key;
vals = nan(1,numel(keys));
for j = 1:numel(keys), vals(j) = str2double(get(h.datEd{j},'String')); end
if any(isnan(vals)), set(h.status,'String','every field needs a number'); return; end
h = pushUndo(h); NET = h.NET; i = mp{2};
for j = 1:numel(keys)
    v = vals(j);
    switch keys{j}
    case 'b.Vset', NET.Vset(i) = v;   case 'b.Pd',  NET.Pd(i) = v;
    case 'b.Qd',   NET.Qd(i) = v;     case 'b.Bs',  NET.Bs(i) = v;
    case 'l.r',    NET.br_r(i) = v;   case 'l.x',   NET.br_x(i) = v;
    case 'l.b',    NET.br_b(i) = v;   case 'l.tap', NET.br_tap(i) = v;
    case 'g.Pg',   NET.g_Pg(i) = v;   case 'g.Vset',NET.g_Vset(i) = v;
    case 'g.S',    NET.g_S(i) = v;
    case 'f.Vref', NET.facts(i).Vref = v;   case 'f.droop', NET.facts(i).droop = v;
    case 'f.Bmax', NET.facts(i).Bmax = v;   case 'f.Imax',  NET.facts(i).Imax = v;
    case 'f.kcomp',NET.facts(i).kcomp = v;  case 'f.kmin',  NET.facts(i).kmin = v;
    case 'f.kmax', NET.facts(i).kmax = v;
    end
end
h.NET = NET; guidata(fig,h); redraw(fig); datBuild(fig);
if strcmp(mp{1},'facts')
    factsImpact(fig, sprintf('%s updated', upper(NET.facts(i).type)), i);
else
    autoPF(fig, 'input data applied');
end
end

% ---- automatic results refresh after ANY network edit --------------------
% The FACTS path proved the workflow: an edit should show its consequence
% immediately.  autoPF re-solves the power flow silently after loads, shunts,
% generators, lines, deletions and parameter edits, refreshing the overlay
% and the Results tables -- no manual "Run power flow" needed.  Failures stay
% quiet and honest (a half-wired network simply reports "pending").
function autoPF(fig, ftxt)
h = guidata(fig);
if nbus(h.NET) > 120                        % huge nets: keep edits instant
    set(h.status,'String',[ftxt ' - run Power flow to refresh results']); return;
end
if nbus(h.NET) == 0 || ngen(h.NET) == 0 || nbr(h.NET) == 0
    set(h.status,'String',[ftxt '  (add buses, lines and a generator to solve)']); return;
end
pfm = h.PFN{get(h.ddPF,'Value')};
try
    C = psdat_netcase(h.NET); S = psdat_system(C, C.UT, [], pfm);
catch err
    set(h.status,'String',[ftxt '  (power flow pending: ' err.message ')']); return;
end
[flows, fdir] = overlayFlows(h, S);
h.ED.pf = struct('V',S.V0,'th',S.TH0*180/pi,'flowdir',fdir,'flows',flows, ...
    'Pg',S.Pg(:)*S.baseMVA,'Qg',S.Qg(:)*S.baseMVA);
if isfield(h.ED,'netrev'), h.ED.lastrun.pf = h.ED.netrev; end   % PF is fresh again
guidata(fig,h); redraw(fig);
try, syncFlowTimer(fig); catch, end
try, pfReport(fig, S, flows, S.baseMVA, S.n, S.V0, S.TH0*180/pi); catch, end
[~,imn] = min(S.V0);
set(h.status,'String',sprintf('%s - solved: min |V| %.4f pu (bus %d), losses %.2f MW', ...
    ftxt, S.V0(imn), imn, sum(flows(:,4))));
end

% ---- FACTS insertion feedback -------------------------------------------
% Dropping a device used to change nothing on screen until the next manual
% Power flow -- which read as "the device does nothing".  factsImpact solves
% the power flow silently, refreshes the overlay + Results, and states the
% device's measured effect (before -> after) in the status line, flagging the
% one genuine no-effect case (a shunt compensator on a machine-held bus).
function factsImpact(fig, ftxt, kdev)
h = guidata(fig);
if nfac(h.NET) == 0, return; end
if nargin < 3 || isempty(kdev) || kdev < 1 || kdev > nfac(h.NET), kdev = nfac(h.NET); end
if nbus(h.NET) > 120
    set(h.status,'String',[ftxt ' - run Power flow to see its effect']); return;
end
pfm = h.PFN{get(h.ddPF,'Value')};
try
    C1 = psdat_netcase(h.NET); S1 = psdat_system(C1, C1.UT, [], pfm);
catch err
    set(h.status,'String',[ftxt ' - power flow FAILED with this device (' err.message ')']); return;
end
S0 = [];
try
    if isfield(h.ED,'undo') && ~isempty(h.ED.undo)   % the pre-insertion network
        N0 = h.ED.undo{end};
        C0 = psdat_netcase(N0); S0 = psdat_system(C0, C0.UT, [], pfm);
    end
catch, S0 = []; end
[flows, fdir] = overlayFlows(h, S1);                 % refresh overlay + tables
h.ED.pf = struct('V',S1.V0,'th',S1.TH0*180/pi,'flowdir',fdir,'flows',flows, ...
    'Pg',S1.Pg(:)*S1.baseMVA,'Qg',S1.Qg(:)*S1.baseMVA);
guidata(fig,h); redraw(fig);
try, syncFlowTimer(fig); catch, end
try, pfReport(fig, S1, flows, S1.baseMVA, S1.n, S1.V0, S1.TH0*180/pi); catch, end
d = h.NET.facts(kdev); ty = upper(d.type); msg = ftxt;
try
    switch ty
    case {'SVC','STATCOM'}
        i = round(d.bus);
        was = ''; if ~isempty(S0), was = sprintf('%.4f -> ', S0.V0(i)); end
        msg = sprintf('%s: bus %d |V| %s%.4f pu, device Q = %+.1f MVAr', ...
                      ftxt, i, was, S1.V0(i), devQ(S1, i, ty));
        if any(round(h.NET.g_bus(:)) == i) || h.NET.btype(i) == 3
            msg = [msg '   (machine-regulated bus: expect no change - drop it on a load bus)'];
        end
    case {'TCSC','TSSC','SSSC'}
        was = ''; if ~isempty(S0), was = sprintf('%+.1f -> ', lineFlowP(h, S0, round(d.f), round(d.t))); end
        kc = min(max(d.kcomp, d.kmin), d.kmax);
        msg = sprintf('%s: P(%d-%d) %s%+.1f MW   (x_eff = x*(1-%.2f))', ...
                      ftxt, round(d.f), round(d.t), was, lineFlowP(h, S1, round(d.f), round(d.t)), kc);
    case 'UPFC'
        i = round(d.bus);
        wv = ''; wp = '';
        if ~isempty(S0)
            wv = sprintf('%.4f -> ', S0.V0(i));
            wp = sprintf('%+.1f -> ', lineFlowP(h, S0, round(d.f), round(d.t)));
        end
        msg = sprintf('%s: bus %d |V| %s%.4f pu, P(%d-%d) %s%+.1f MW', ...
                      ftxt, i, wv, S1.V0(i), round(d.f), round(d.t), wp, lineFlowP(h, S1, round(d.f), round(d.t)));
    case 'IPFC'
        wp = ''; if ~isempty(S0), wp = sprintf('%+.1f -> ', lineFlowP(h, S0, round(d.f), round(d.t))); end
        msg = sprintf('%s: P(%d-%d) %s%+.1f MW - set line 2 in Properties for the DC-coupled pair', ...
                      ftxt, round(d.f), round(d.t), wp, lineFlowP(h, S1, round(d.f), round(d.t)));
    end
catch, end
set(h.status,'String',msg);
end

function [flows, fdir] = overlayFlows(h, S)
% branch flows for the SLD overlay, from the branch data THE SOLVER USED
% (x_eff = x*(1-k) for series FACTS) -- same math as onPF, callable silently.
Vc = S.V0.*exp(1i*S.TH0);
flows = zeros(nbr(h.NET),4); fdir = zeros(nbr(h.NET),1);
useSB = isfield(S,'branch') && size(S.branch,1) == nbr(h.NET);
for k = 1:nbr(h.NET)
    if useSB
        f = round(S.branch(k,1)); t = round(S.branch(k,2));
        r = S.branch(k,3); x = S.branch(k,4); bb = S.branch(k,5); a = S.branch(k,9);
    else
        f = h.NET.br_f(k); t = h.NET.br_t(k); r = h.NET.br_r(k); x = h.NET.br_x(k); bb = h.NET.br_b(k);
        a = h.NET.br_tap(k);
    end
    if a==0, a = 1; end
    y = 1/(r+1i*x); bc = 1i*bb/2;
    Sf = Vc(f)*conj((y+bc)/(a*a)*Vc(f) - y/conj(a)*Vc(t));
    St = Vc(t)*conj((y+bc)*Vc(t) - y/a*Vc(f));
    flows(k,:) = [real(Sf)*100 imag(Sf)*100 real(St)*100 real(Sf+St)*100]; fdir(k) = real(Sf);
end
if isfield(S,'pqlines') && ~isempty(S.pqlines)       % P-Q corridors: commanded flow
    for q = 1:size(S.pqlines,1)
        pf_ = S.pqlines(q,1); pt_ = S.pqlines(q,2);
        for k = 1:nbr(h.NET)
            if (h.NET.br_f(k)==pf_ && h.NET.br_t(k)==pt_) || (h.NET.br_f(k)==pt_ && h.NET.br_t(k)==pf_)
                flows(k,:) = [S.pqlines(q,3) S.pqlines(q,4) S.pqlines(q,3) 0];
                fdir(k) = S.pqlines(q,3)/100 * (2*(h.NET.br_f(k)==pf_)-1);
                break;
            end
        end
    end
end
end

function P = lineFlowP(h, S, f, t)
% active power (MW) leaving bus f on branch f-t, as the solver saw the line;
% P-Q-controlled corridors report their commanded setpoint instead.
P = 0;
if isfield(S,'pqlines') && ~isempty(S.pqlines)
    for q = 1:size(S.pqlines,1)
        if (S.pqlines(q,1)==f && S.pqlines(q,2)==t), P = S.pqlines(q,3); return; end
        if (S.pqlines(q,1)==t && S.pqlines(q,2)==f), P = -S.pqlines(q,3); return; end
    end
end
Vc = S.V0.*exp(1i*S.TH0);
useSB = isfield(S,'branch') && size(S.branch,1) == nbr(h.NET);
for k = 1:nbr(h.NET)
    bf = h.NET.br_f(k); bt = h.NET.br_t(k);
    if ~((bf==f && bt==t) || (bf==t && bt==f)), continue; end
    if useSB
        fa = round(S.branch(k,1)); ta = round(S.branch(k,2));
        r = S.branch(k,3); x = S.branch(k,4); bb = S.branch(k,5); a = S.branch(k,9);
    else
        fa = bf; ta = bt; r = h.NET.br_r(k); x = h.NET.br_x(k); bb = h.NET.br_b(k); a = h.NET.br_tap(k);
    end
    if a==0, a = 1; end
    y = 1/(r+1i*x); bc = 1i*bb/2;
    if fa == f    % power leaving the stored 'from' end
        P = real(Vc(fa)*conj((y+bc)/(a*a)*Vc(fa) - y/conj(a)*Vc(ta)))*100;
    else          % f is the stored 'to' end
        P = real(Vc(ta)*conj((y+bc)*Vc(ta) - y/a*Vc(fa)))*100;
    end
    return;
end
end

function q = devQ(S, i, ty)
% solved reactive output (MVAr) of the shunt device of type ty at bus i
q = 0;
if ~isfield(S,'facts') || isempty(S.facts), return; end
for k = 1:numel(S.facts)
    d = S.facts(k);
    if isfield(d,'bus') && ~isempty(d.bus) && round(d.bus) == i && ...
       isfield(d,'type') && strcmpi(d.type, ty) && isfield(d,'Q_') && ~isempty(d.Q_)
        q = d.Q_ * S.baseMVA; return;
    end
end
end

function onSS(src,~)
fig = ancestor(src,'figure'); if isempty(fig), fig = gcbf; end   % src = the app figure when the run queue dispatches
if runGate(fig,'ss'), return; end
bz = beBusy(fig);   %#ok<NASGU>
armFreshRun(fig);              % the last run's stop request must not kill this one
h = guidata(fig);
set(h.status,'String','linearizing...'); drawnow;
try, C = psdat_netcase(h.NET); catch err, errordlg(err.message,'Small-signal'); return; end
h = markrun(fig, h, 'ss');
b0 = figsnap();
setappdata(0,'PSDAT_noplot',1); np = onCleanup(@() setappdata(0,'PSDAT_noplot',0)); %#ok<NASGU>
try, R = PSDAT_Linearization(C, C.UT, []);
catch err
    if strcmp(err.identifier,'psdat:stopped')
        set(h.status,'String','small-signal run stopped by user'); return;
    end
    errordlg(err.message,'Linearization failed'); set(h.status,'String',''); return;
end
closeNew(fig,b0); lam = R.lambda;
osc = find(imag(lam) > 2*pi*0.02 & imag(lam) < 2*pi*8);
z = -real(lam(osc))./abs(lam(osc))*100; [z,ix] = sort(z); osc = osc(ix);
L = {'SMALL-SIGNAL'; sprintf('%d states, %d oscillatory modes',size(R.A,1),numel(osc)); ''; sprintf('%-8s %-8s %-9s','f[Hz]','damp%','Re')};
for j = 1:numel(osc), L{end+1} = sprintf('%-8.3f %-8.2f %-9.4f', imag(lam(osc(j)))/2/pi, z(j), real(lam(osc(j)))); end
L{end+1} = sprintf('unstable modes: %d', sum(real(lam) > 1e-6));
setReport(fig,L); setTab('report', fig); set(h.status,'String','small-signal done - opening the eigenvalue map...');
% the figure opens OUTSIDE this callback (deferred) -- see deferFig
nm = h.NET.name;
deferFig(fig, @() ssFigure(fig, lam, nm));
end
function ssFigure(fig, lam, nm)
fg = figure('Name','PSDAT - eigenvalue map','NumberTitle','off','Color','w','HandleVisibility','off','IntegerHandle','off'); ax = axes('Parent',fg); hold(ax,'on'); noAxInteract(ax);
st = real(lam) <= 1e-6;
plot(ax,real(lam(st)),imag(lam(st)),'x','Color',[.12 .23 .45],'MarkerSize',8,'LineWidth',1.5);
plot(ax,real(lam(~st)),imag(lam(~st)),'x','Color',[.7 .1 .1],'MarkerSize',9,'LineWidth',1.8);
yl = get(ax,'YLim'); plot(ax,[0 0],yl,'-','Color',[.7 .1 .1]); hold(ax,'off'); grid(ax,'on');
xlabel(ax,'Real (1/s)'); ylabel(ax,'Imag (rad/s)'); title(ax,sprintf('Eigenvalue map - %s',nm),'Interpreter','none');
styleResultAxes(ax);
try, h = guidata(fig); set(h.status,'String','small-signal done (see figure)'); catch, end
end

function onDisturb(src,~)
if busyBlock(gcbf), return; end   % never do real work inside a running solve
% reshape the disturbance input strip to match the selected disturbance:
% a line outage needs a from-to pair and no size; PV/wind events need a unit
% and only a start time; faults/steps use one bus with both times.
fig = ancestor(src,'figure'); h = guidata(fig);
cls = h.KV{get(src,'Value')};
locL = 'bus'; showMag = true; showT2 = true;
switch cls
case 'trip',  locL = 'from-to'; showMag = false;   % line outage: two buses, no magnitude
case 'gen',   locL = 'unit';                        % generator set-point pulse
case 'cloud', locL = 'unit';  showT2 = false;       % PV cloud: single ramp event
case 'gust',  locL = 'unit';  showT2 = false;       % wind gust: single ramp event
end
lo = [.8 .82 .87];
set(h.eLab{1},'String',locL);
set(h.eMag,'Enable',tern(showMag,'on','off')); set(h.eLab{2},'ForegroundColor',tern(showMag,h.C.grey,lo));
set(h.eT2, 'Enable',tern(showT2, 'on','off')); set(h.eLab{4},'ForegroundColor',tern(showT2, h.C.grey,lo));
cur = get(h.eLoc,'String');                         % keep the location box sensible
if strcmp(cls,'trip') && isempty(strfind(cur,'-')),       set(h.eLoc,'String','7-8');
elseif ~strcmp(cls,'trip') && ~isempty(strfind(cur,'-')), set(h.eLoc,'String','1'); end
end

function onTD(src,~)
fig = ancestor(src,'figure'); if isempty(fig), fig = gcbf; end   % src = the app figure when the run queue dispatches
if runGate(fig,'td'), return; end
bz = beBusy(fig);   %#ok<NASGU>
armFreshRun(fig);              % the last run's stop request must not kill this one
h = guidata(fig);
setappdata(fig,'TDres',[]);    % the previous trajectory is invalid from here on
try, C = psdat_netcase(h.NET); catch err, errordlg(err.message,'Time domain'); return; end
h = markrun(fig, h, 'td');
UT = C.UT; D = struct('tsim', str2double(get(h.eTs,'String')));
t2 = str2double(get(h.eT2,'String')); if isnan(t2), t2 = inf; end
loc = sscanf(get(h.eLoc,'String'),'%d-%d'); if isempty(loc), errordlg('give bus/unit number','Location'); return; end
Lc = loc(1); mag = str2double(get(h.eMag,'String')); t1 = str2double(get(h.eT1,'String'));
cls = h.KV{get(h.ddK,'Value')};
if any(strcmp(cls,{'gen','cloud','gust'})) && (Lc < 1 || Lc > numel(UT))
    errordlg(sprintf('this disturbance targets a UNIT: give generator 1..%d',numel(UT)),'Location'); return;
end
switch cls
case 'fault', if isinf(t2), t2 = t1+0.1; end; D.fault = [Lc mag t1 t2];
case 'load',  D.dPload = [Lc mag t1 t2];
case 'trip',  if numel(loc) < 2, errordlg('give the line as  from-to  (e.g. 7-8)','Line outage'); return; end
              if isinf(t2), t2 = 1e9; end; D.linetrip = [loc(1) loc(2) t1 t2];
case 'gen',   D.dPgen = [Lc mag t1 t2];
case 'cloud', if isempty(strfind(UT{Lc},'PV')), errordlg('a cloud needs a PV unit','Source'); return; end
              D.cloud = [Lc mag t1];
case 'gust',  if isempty(strfind(UT{Lc},'WT')), errordlg('a gust needs a wind unit','Source'); return; end
              D.gust = [Lc mag t1];
end
set(h.status,'String','integrating... (press Stop to abort)'); drawnow; b0 = figsnap();
ws = warning('off','MATLAB:ode15s:IntegrationTolNotMet');   % keep the console clean
showStop(fig);                              % reveal the Stop button while this run lasts
% exit-guaranteed cleanup: WHATEVER happens in the run (error, Stop, timeout,
% Ctrl-C), the Stop button is hidden and the warning state restored the moment
% this callback leaves -- no path can strand the interface in a running look.
hg = onCleanup(@() hideStop(fig));          %#ok<NASGU>
wg = onCleanup(@() warning(ws));            %#ok<NASGU>
setappdata(0,'PSDAT_noplot',1); np = onCleanup(@() setappdata(0,'PSDAT_noplot',0)); %#ok<NASGU>
% publish the status line so the integrator can stream live progress into it
% (t = ... advancing), and give GUI runs a wall-clock budget: whatever the
% case does, the click ALWAYS comes back with a result and a message.
setappdata(0,'PSDAT_status',h.status);
D.walltime = min(360, max(120, 6*C.n));     % bigger fleets earn a bigger budget
ns = onCleanup(@() setappdata(0,'PSDAT_status',[]));        %#ok<NASGU>
try, out = PSDAT_TimeDomain(C, UT, D, []);
catch err
    warning(ws); hideStop(fig);
    if userStopped()
        % the user pressed Stop while the run was still preparing (operating
        % point polish / Jacobian setup): present it as a clean stop, never
        % as a failure
        setReport(fig,{'TIME DOMAIN - stopped'; ''; 'stopped by user during run preparation.'});
        setTab('report', fig);
        set(h.status,'String','time-domain run stopped by user'); return;
    end
    % NEVER a silent failure: the report carries the reason too, so "no
    % results" always comes with its explanation in the Report tab.
    setReport(fig,{'TIME DOMAIN - failed'; ''; err.message; ''; ...
        'check the disturbance values and the network, then run again.'});
    setTab('report', fig);
    errordlg(err.message,'Simulation failed'); set(h.status,'String','simulation failed - see Report'); return;
end
warning(ws); hideStop(fig); closeNew(fig,b0);
% ---- keep the FULL trajectory for the workspace's signal plotter --------
% states X, bus voltages/angles (the tail of Z), the unit map and ws; the
% big arrays live in APPDATA, never in guidata (guidata copies on every
% write).  Partial results (Stop / stall / timeout) are kept too -- what
% integrated is what plots.
try
    S_ = out.S; n_ = S_.n;
    TD = struct('t',{out.t},'fCOI',{out.fCOI},'X',{out.X}, ...
                'V',{out.Z(:, end-2*n_+1:end-n_)},'TH',{out.Z(:, end-n_+1:end)}, ...
                'ws',{S_.ws},'n',{n_});
    TD.units = S_.U;                       % type + xidx + bus per unit
    setappdata(fig,'TDres', TD);
catch
    setappdata(fig,'TDres', []);
end
tend = 0; if isfield(out,'t') && ~isempty(out.t), tend = out.t(end); end
% ---- the response window opens OUTSIDE this callback (deferred): creating
% a figure+axes inside a uicontrol callback can deadlock the new desktop.
% Every outcome below that says "plotted" is honest -- full or partial, the
% trace that exists is what gets drawn.
hasplot = ~isempty(out.fCOI);
if hasplot
    tt = out.t; ff = out.fCOI; nm = h.NET.name; cl2 = cls;
    deferFig(fig, @() tdFigure(tt, ff, nm, cl2));
end
if isfield(out,'stopped') && out.stopped     % user pressed Stop -> keep the partial result
    setReport(fig,{'TIME DOMAIN - stopped'; ''; ...
        sprintf('aborted by user at t = %.2f s of %.0f s', tend, D.tsim); ...
        tern(hasplot,'the partial response is plotted in the figure.','(no COI trace: no SG/GFM inertial units)')});
    setTab('report', fig);
    set(h.status,'String',sprintf('stopped by user - partial result to t = %.2f s', tend));
    return;
end
if isfield(out,'stalled') && out.stalled     % t stopped advancing -> honest partial
    setReport(fig,{'TIME DOMAIN - solver stalled'; ''; ...
        sprintf('the integration stopped advancing at t = %.2f s of %.0f s', tend, D.tsim); ...
        tern(hasplot,'the partial response is plotted in the figure.','(no COI trace: no SG/GFM inertial units)'); ...
        'the operating point could not ride this disturbance -'; ...
        'try a smaller disturbance, a shorter fault window,'; ...
        'or wider device limits.'});
    setTab('report', fig);
    set(h.status,'String',sprintf('solver stalled at t = %.2f s - partial result kept', tend));
    return;
end
if isfield(out,'timeout') && out.timeout     % wall budget -> honest partial result
    setReport(fig,{'TIME DOMAIN - time limit'; ''; ...
        sprintf('reached the %d-s compute budget at t = %.2f s of %.0f s', round(D.walltime), tend, D.tsim); ...
        tern(hasplot,'the partial response is plotted in the figure.','(no COI trace: no SG/GFM inertial units)'); ...
        'a run this slow usually means the case went unstable or'; ...
        'extremely stiff - try a smaller disturbance or shorter t_sim.'});
    setTab('report', fig);
    set(h.status,'String',sprintf('time limit reached - partial result to t = %.2f s of %.0f s', tend, D.tsim));
    return;
end
if hasplot
    setReport(fig,{sprintf('TIME DOMAIN - %s',cls); ''; sprintf('nadir  = %.4f Hz', min(out.fCOI)); ...
        sprintf('final  = %.4f Hz', out.fCOI(end)); sprintf('states = %d', size(out.X,2))});
else
    setReport(fig,{'TIME DOMAIN done';'no COI frequency (no SG/GFM inertial units)'});
end
setTab('report', fig);
if isfield(out,'t') && ~isempty(out.t) && out.t(end) < 0.98*D.tsim
    % the solver could not carry the response further (a stiff spot the fine-
    % step retry inside PSDAT_TimeDomain also could not clear) -- say exactly
    % what happened and what usually fixes it; the partial response IS plotted.
    set(h.status,'String',sprintf(['solver stopped at t = %.2f s of %.0f s - response plotted to there; ' ...
        'try a smaller disturbance, a shorter fault window or wider device limits'], out.t(end), D.tsim));
else
    set(h.status,'String','simulation done (see figure)');
end
end

function tdFigure(t, fCOI, nm, cls)
fg = figure('Name','PSDAT - time-domain response','NumberTitle','off','Color','w','HandleVisibility','off','IntegerHandle','off'); ax = axes('Parent',fg); noAxInteract(ax);
plot(ax,t,fCOI,'LineWidth',1.8,'Color',[.12 .23 .45]); grid(ax,'on');
xlabel(ax,'Time (s)'); ylabel(ax,'COI frequency (Hz)');
title(ax,sprintf('%s - %s  (nadir %.4f Hz)', nm, cls, min(fCOI)),'Interpreter','none');
styleResultAxes(ax);
end

function onTDPlot(src,~)   %#ok<INUSD>
% plot ANY stored signal of the LAST time-domain run -- rotor angles,
% rotor speeds, bus voltages/angles or the COI frequency -- straight from
% the kept solution.  No re-simulation; partial (stopped) runs plot too.
if busyBlock(gcbf), return; end
fig = gcbf; h = guidata(fig);
TD = getappdata(fig,'TDres');
if isempty(TD) || ~isstruct(TD) || ~isfield(TD,'t') || isempty(TD.t)
    set(h.status,'String','run a time-domain simulation first - then any of its signals can be plotted');
    return;
end
sel = 1;
if isfield(h,'ddTDsig') && ishghandle(h.ddTDsig), sel = get(h.ddTDsig,'Value'); end
t = TD.t; Y = []; nm = {}; ylab = '';
switch sel
case 1
    if isempty(TD.fCOI)
        set(h.status,'String','this run has no COI frequency (no SG/GFM inertial units) - pick another signal');
        return;
    end
    Y = TD.fCOI; nm = {'COI'}; ylab = 'COI frequency (Hz)';
case {2,3}
    [Y, nm] = tdRotor(TD, sel == 2);
    if isempty(Y)
        set(h.status,'String','no machines with rotor states on this diagram (GFL-only fleet)');
        return;
    end
    if sel == 2, ylab = 'rotor angle rel. unit 1 (deg)';
    else,        ylab = 'rotor speed (pu)'; end
case 4
    Y = TD.V; ylab = 'bus voltage (pu)';
    nm = cell(1, size(Y,2));
    for q = 1:size(Y,2), nm{q} = sprintf('bus %d', q); end
otherwise
    Y = (TD.TH - repmat(TD.TH(:,1), 1, size(TD.TH,2)))*180/pi;
    ylab = 'bus angle rel. bus 1 (deg)';
    nm = cell(1, size(Y,2));
    for q = 1:size(Y,2), nm{q} = sprintf('bus %d', q); end
end
labs = get(h.ddTDsig,'String');
ttl = sprintf('%s - %s', h.NET.name, lower(strtrim(labs{sel})));
set(h.status,'String','opening the signal figure...');
% the figure opens OUTSIDE this callback (deferred), like every result window
deferFig(fig, @() tdSigFigure(t, Y, nm, ylab, ttl));
end

function [Y, nm] = tdRotor(TD, wantAngle)
% extract delta (deg, rel. unit 1) or speed (pu) for every unit that has a
% rotor.  State layouts (psdat_dae): delta sits ONE SLOT BELOW omega in
% every family --
%   SG/SGP  w = state 6 | SG6/SG6G/SG6P  w = 3 | SG4/SG4G  w = 4
%   SG2     w = state 2 | GFM / PV-GFM / BESS-GFM / WT4-GFM  w = 2
Y = []; nm = {};
U = TD.units; X = TD.X; ws = TD.ws;
for k = 1:numel(U)
    switch U(k).type
    case {'SG','SGP'},                          iw = 6;
    case {'SG6','SG6G','SG6P'},                 iw = 3;
    case {'SG4','SG4G'},                        iw = 4;
    case 'SG2',                                 iw = 2;
    case {'GFM','PV-GFM','BESS-GFM','WT4-GFM'}, iw = 2;
    otherwise, continue;                        % GFL family: no rotor states
    end
    xi = U(k).xidx;
    if wantAngle, col = X(:, xi(iw-1));         % delta, just below omega
    else,         col = X(:, xi(iw))/ws;        % omega -> per-unit speed
    end
    Y(:,end+1) = col;                                       %#ok<AGROW>
    nm{end+1}  = sprintf('%s bus %d', U(k).type, U(k).bus); %#ok<AGROW>
end
if wantAngle && ~isempty(Y)
    Y = (Y - repmat(Y(:,1), 1, size(Y,2)))*180/pi;   % swing rel. the first unit
end
end

function tdSigFigure(t, Y, nm, ylab, ttl)
fg = figure('Name','PSDAT - time-domain signals','NumberTitle','off','Color','w', ...
    'HandleVisibility','off','IntegerHandle','off');
ax = axes('Parent',fg); noAxInteract(ax);
plot(ax, t, Y, 'LineWidth', 1.4);
grid(ax,'on'); xlabel(ax,'Time (s)'); ylabel(ax, ylab);
title(ax, ttl, 'Interpreter','none');
if numel(nm) > 1 && numel(nm) <= 12       % a 12+ legend covers the traces
    lg = legend(ax, nm, 'Location','best');
    try, set(lg,'Box','off','TextColor',[.25 .30 .40],'FontSize',9); catch, end
end
styleResultAxes(ax);
end

function styleResultAxes(ax)
% one consistent look for every result window (eigenvalue map, time-domain
% response, POD comparison): the app's own typography scale and ink colours,
% soft grid, open box -- so a result figure is recognisably PSDAT's and never
% reads as a foreign default-MATLAB plot.  Every set is try-guarded: on
% Octave / older releases the unsupported properties silently keep defaults.
try
    set(ax,'FontSize',10.5,'TickDir','out','Box','off','LineWidth',0.8, ...
        'XColor',[.35 .40 .50],'YColor',[.35 .40 .50]);
catch
end
try, set(ax,'GridColor',[.60 .65 .74],'GridAlpha',0.45); catch, end
try
    set(get(ax,'Title'),'Color',[.12 .23 .43],'FontWeight','bold','FontSize',11.5);
    set(get(ax,'XLabel'),'Color',[.30 .35 .45]);
    set(get(ax,'YLabel'),'Color',[.30 .35 .45]);
catch
end
end

function onDS(src,~)
fig = ancestor(src,'figure'); if isempty(fig), fig = gcbf; end   % src = the app figure when the run queue dispatches
if runGate(fig,'ds'), return; end
bz = beBusy(fig);   %#ok<NASGU>
armFreshRun(fig);              % the last run's stop request must not kill this one
h = guidata(fig);
try, C = psdat_netcase(h.NET); catch err, errordlg(err.message,'Design'); return; end
h = markrun(fig, h, 'ds');
if C.m < 2, errordlg('POD design needs at least two generators','Design'); return; end
% actuator + target from the Design workspace fields (validated + clamped)
un = min(2, C.m); zt = 0.20;
if isfield(h,'dsEd') && ishghandle(h.dsEd{1})
    v = round(str2double(get(h.dsEd{1},'String')));
    if ~isnan(v), un = max(1, min(C.m, v)); end
    v = str2double(get(h.dsEd{2},'String'))/100;
    if ~isnan(v) && v > 0, zt = min(v, 0.90); end
end
opts = struct('unit', un, 'zeta_target', zt);
set(h.status,'String','designing POD (a figure will open)...'); drawnow;
setappdata(0,'PSDAT_noplot',1); np = onCleanup(@() setappdata(0,'PSDAT_noplot',0)); %#ok<NASGU>
try, out = PSDAT_Design(C, C.UT, [], opts);
catch err
    if ~isempty(strfind(err.message,'stopped by user')) || strcmp(err.identifier,'psdat:stopped')
        set(h.status,'String','design run stopped by user'); return;
    end
    errordlg(err.message,'POD design failed'); set(h.status,'String',''); return;
end
zo = -real(out.lam_open)/abs(out.lam_open)*100; zc = -real(out.lam_closed)/abs(out.lam_closed)*100;
setReport(fig,{sprintf('POD DESIGN on generator %d',opts.unit); ''; sprintf('K=%.2f  Tw=%.0fs  %d lead-lag', out.K, out.Tw, out.nc); ...
    sprintf('T1=%.3f  T2=%.3f', out.T1, out.T2); sprintf('target mode  %.3f Hz', imag(out.lam_open)/2/pi); ...
    sprintf('damping  %.2f%% -> %.2f%%', zo, zc)});
setTab('report', fig); set(h.status,'String','POD design done - opening the comparison figure...');
la = out.lam_all; lc = out.lam_cl; nm = h.NET.name; ku = out.unit; ut = out.unittype;
deferFig(fig, @() dsFigure(fig, la, lc, nm, ku, ut));
end
function dsFigure(fig, lam_all, lcl, nm, ku, ut)
fg = figure('Name','PSDAT - POD design','NumberTitle','off','Color','w','HandleVisibility','off','IntegerHandle','off'); ax = axes('Parent',fg); hold(ax,'on'); noAxInteract(ax);
plot(ax,real(lam_all), imag(lam_all), 'x', 'MarkerSize', 9, 'LineWidth', 1.5, 'Color',[.12 .23 .45]);
plot(ax,real(lcl), imag(lcl), 'o', 'MarkerSize', 7, 'LineWidth', 1.2, 'Color',[.10 .52 .29]);
hold(ax,'off'); grid(ax,'on');
lg = legend(ax,'open loop','with POD');
try, set(lg,'Box','off','TextColor',[.25 .30 .40],'FontSize',9.5); catch, end
xlabel(ax,'Real (1/s)'); ylabel(ax,'Imag (rad/s)');
title(ax,sprintf('%s: POD on unit %d (%s)', nm, ku, ut),'Interpreter','none');
styleResultAxes(ax);
try, h = guidata(fig); set(h.status,'String','POD design done (see figure)'); catch, end
end

function onSC(src,~)
% scenarios open several comparison figures, so the WHOLE study is deferred
% out of this callback (figure creation inside a uicontrol callback can
% deadlock the new desktop); the click returns instantly and the run happens
% on the main event loop under the usual busy protection.
fig = ancestor(src,'figure'); if isempty(fig), fig = gcbf; end   % src = the app figure when the run queue dispatches
if runGate(fig,'sc'), return; end
armFreshRun(fig);              % a lingering stop request must not abort the study
h = guidata(fig); name = h.SCN{get(h.ddScn,'Value')};
set(h.status,'String',['running scenario "' name '" - figures will open shortly...']);
deferFig(fig, @() scRun(fig, name));
end
function scRun(fig, name)
h = guidata(fig);
try, PSDAT_Scenarios(name); catch err, errordlg(err.message,'Scenario failed'); set(h.status,'String',''); return; end
setReport(fig,{['Scenario "' name '" finished.']; 'Result figures have opened.'; ''; '(Scenarios run on the bundled benchmark systems.)'});
setTab('report', fig); set(h.status,'String','scenario done');
end
