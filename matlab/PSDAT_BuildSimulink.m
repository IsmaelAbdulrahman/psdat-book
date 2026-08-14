function mdl = PSDAT_BuildSimulink(SYS, UT, DIST, UTP, mdl)
% PSDAT_BUILDSIMULINK  Generate the PSDAT Simulink model — natively, in
% YOUR Simulink version.
%
%   mdl = PSDAT_BuildSimulink                       % demo: PV cloud, 9-bus
%   mdl = PSDAT_BuildSimulink('IEEE9', {'SG','BESS-GFM','PV-GFL'}, ...
%                              struct('cloud',[3 0.6 2.0],'tsim',18))
%
% Rather than shipping .slx files (which age badly across Simulink releases
% — hence the RES_linearized_2018a/2019b/2020a copies in the old archive),
% this builder constructs the model programmatically with add_block /
% add_line, so it opens cleanly in whatever release you run.  The model is
% the classical phasor-DAE loop, honestly displayed:
%
%   [ Integrator bank (all unit states, exact initial conditions) ]
%        └──> [ x ; t ] ──> [ PSDAT DAE core ] ──> dx ──┐
%                    │        (solves the network        │
%                    │         algebra, then the unit    │
%                    │         equations of psdat_dae)  │
%                    └──< ─────────────────────────── <──┘
%   plus a measurement block (COI + unit frequencies) -> Scope + Outport.
%
% The DAE core and measurement blocks are Interpreted MATLAB Function
% blocks calling psdat_sl_rhs / psdat_sl_out, which reuse the SAME
% validated psdat_dae.m as every other PSDAT front end — one set of
% equations, four faces (scripts, browser lab, MATLAB app, Simulink).
%
% DIST takes the same fields as PSDAT_TimeDomain (fault, linetrip, dPload,
% dPgen, cloud, gust, tsim).  Run with PSDAT_RunSimulink (also overlays
% the code solution for validation), or just press Play in Simulink.
% Requires Simulink; solver is set to ode23t (moderately stiff, the
% classical choice for phasor DAE-in-ODE-form models).
if nargin < 1, SYS = 'IEEE9'; end
if nargin < 2, UT = {'SG','BESS-GFM','PV-GFL'}; end
if nargin < 3 || isempty(DIST), DIST = struct('cloud',[3 0.6 2.0],'tsim',18); end
if nargin < 4, UTP = cell(1, numel(UT)); end
if nargin < 5, mdl = 'PSDAT_model'; end
% Simulink presence: new_system is a BUILT-IN, so exist(...,'file') misses
% it even when Simulink is installed — query the product list instead.
if isempty(ver('simulink'))
    error(['Simulink was not found in this MATLAB installation (everything ' ...
           'else in PSDAT runs without it). If you do have Simulink, ' ...
           'check that its licence is available: license(''test'',''Simulink'').']);
end

% ---------------- engine: system + disturbance into the store ------------
S = psdat_system(SYS, UT, UTP);
tsim = 12; if isfield(DIST,'tsim'), tsim = DIST.tsim; end
if isfield(DIST,'linetrip')                 % precompute the line stamp
    v = DIST.linetrip;
    br = S.branch; kk = find(br(:,1)==v(1) & br(:,2)==v(2), 1);
    assert(~isempty(kk), 'no branch %d-%d', v(1), v(2));
    r = br(kk,3); xl = br(kk,4); b = br(kk,5); a = br(kk,9); if a==0, a=1; end
    Y = zeros(S.n); yl = 1/(r+1i*xl); bc = 1i*b/2;
    Y(v(1),v(1)) = (yl+bc)/a^2; Y(v(2),v(2)) = yl+bc;
    Y(v(1),v(2)) = -yl/conj(a); Y(v(2),v(1)) = -yl/a;
    DIST.Ytrip = -Y;
end
psdat_sl_store('set', S, DIST);
psdat_sl_store('settag', mdl);             % one live model per session:
                                            % the InitFcn guard below stops a
                                            % stale model from silently using
                                            % another build's system
assignin('base', 'PSDAT_x0', S.x0);        % integrator initial condition

% ---------------- build the diagram --------------------------------------
if bdIsLoaded(mdl), close_system(mdl, 0); end
new_system(mdl); open_system(mdl);
IB = sprintf('Interpreted\nMATLAB Function');
add_block('simulink/Continuous/Integrator', [mdl '/States x'], ...
    'InitialCondition', 'PSDAT_x0', 'Position', [420 150 460 190]);
add_block('simulink/Sources/Clock', [mdl '/t'], 'Position', [80 232 100 252]);
add_block('simulink/Signal Routing/Mux', [mdl '/xt'], 'Inputs', '2', ...
    'DisplayOption', 'bar', 'Position', [150 150 155 260]);
add_block(['simulink/User-Defined Functions/' IB], [mdl '/PSDAT DAE core'], ...
    'MATLABFcn', 'psdat_sl_rhs', 'OutputDimensions', num2str(S.NX), ...
    'Position', [220 175 340 235]);
add_block(['simulink/User-Defined Functions/' IB], [mdl '/COI + unit freqs'], ...
    'MATLABFcn', 'psdat_sl_out', 'OutputDimensions', num2str(1 + S.m), ...
    'Position', [220 300 340 360]);
add_block('simulink/Sinks/Scope', [mdl '/Frequency scope'], ...
    'Position', [420 310 460 350]);
add_block('simulink/Sinks/Out1', [mdl '/y'], 'Position', [420 380 450 394]);
add_line(mdl, 't/1', 'xt/2', 'autorouting', 'on');
add_line(mdl, 'xt/1', 'PSDAT DAE core/1', 'autorouting', 'on');
add_line(mdl, 'PSDAT DAE core/1', 'States x/1', 'autorouting', 'on');
add_line(mdl, 'States x/1', 'xt/1', 'autorouting', 'on');
add_line(mdl, 'xt/1', 'COI + unit freqs/1', 'autorouting', 'on');
add_line(mdl, 'COI + unit freqs/1', 'Frequency scope/1', 'autorouting', 'on');
add_line(mdl, 'COI + unit freqs/1', 'y/1', 'autorouting', 'on');
try     % annotation (cosmetic; API varies slightly across releases)
    a = Simulink.Annotation(mdl, 'psdat_note');
    a.Text = sprintf(['PSDAT phasor-DAE model — %s [%s].  Equations: ' ...
        'psdat_dae.m (open psdat_sl_rhs to read the loop).  Rebuild with ' ...
        'PSDAT_BuildSimulink after changing the mix.'], SYS, strjoin(UT, ','));
    a.Position = [90 40 760 70];
catch
end

% ---------------- solver + logging ---------------------------------------
set_param(mdl, 'InitFcn', sprintf('psdat_sl_store(''check'',''%s'');', mdl));
set_param(mdl, 'Solver', 'ode23t', 'RelTol', '1e-6', 'AbsTol', '1e-8', ...
    'MaxStep', '0.01', 'StopTime', num2str(tsim), ...
    'SaveTime', 'on', 'TimeSaveName', 'tout', ...
    'SaveOutput', 'on', 'OutputSaveName', 'yout', 'SaveFormat', 'Array');
save_system(mdl);
fprintf('Built %s.slx  (%s [%s], %d states, t_end = %g s).\n', ...
    mdl, SYS, strjoin(UT, ','), S.NX, tsim);
fprintf('Press Play in Simulink, or run PSDAT_RunSimulink for the validated comparison.\n');
end
