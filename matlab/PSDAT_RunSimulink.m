function out = PSDAT_RunSimulink(SYS, UT, DIST, UTP)
% PSDAT_RUNSIMULINK  Build, simulate and VALIDATE the Simulink model.
%
%   PSDAT_RunSimulink                          % demo: PV cloud on the 9-bus
%   PSDAT_RunSimulink('IEEE9', {'SG','SG','WT3'}, struct('gust',[3 0.15 2]))
%
% Builds the model with PSDAT_BuildSimulink, runs it with the Simulink
% solver, then runs the SAME case through the code driver
% (PSDAT_TimeDomain, ode15s) and overlays the two centre-of-inertia
% frequency traces.  Because both front ends evaluate the same
% psdat_dae.m equations, the curves must coincide — the printed maximum
% deviation is the cross-solver validation of the Simulink version.
if nargin < 1, SYS = 'IEEE9'; end
if nargin < 2, UT = {'SG','BESS-GFM','PV-GFL'}; end
if nargin < 3 || isempty(DIST), DIST = struct('cloud',[3 0.6 2.0],'tsim',18); end
if nargin < 4, UTP = cell(1, numel(UT)); end

mdl = PSDAT_BuildSimulink(SYS, UT, DIST, UTP);
psdat_sl_store('resetz');
simOut = sim(mdl, 'ReturnWorkspaceOutputs', 'on');
t_sl = simOut.tout;
y_sl = simOut.yout;                    % [f_COI, unit freqs] columns
f_sl = y_sl(:,1);

% ---------------- reference: the code driver ------------------------------
ref = evalc_td(SYS, UT, DIST, UTP);

if isempty(ref.fCOI)
    warning(['no SG/GFM-type unit in this mix — there is no COI frequency ' ...
             'to compare; inspect simOut.yout directly.']);
    dev = NaN;
else
    figure('Color','w'); hold on; grid on;
    plot(ref.t, ref.fCOI, 'LineWidth', 2.2, 'Color', [0.12 0.23 0.45], ...
         'DisplayName', 'code driver (ode15s DAE)');
    plot(t_sl, f_sl, '--', 'LineWidth', 1.6, 'Color', [0.75 0.2 0.15], ...
         'DisplayName', 'Simulink model (ode23t)');
    xlabel('Time (s)'); ylabel('COI frequency (Hz)');
    title(sprintf('Simulink vs code — %s [%s]', SYS, strjoin(UT, ', ')));
    legend('Location', 'best');
    fi = interp1(ref.t, ref.fCOI, t_sl, 'linear', 'extrap');
    dev = max(abs(fi - f_sl));
    fprintf('Max |f_Simulink - f_code| = %.2e Hz  (same equations, two solvers)\n', dev);
    if dev < 2e-3
        fprintf('VALIDATED: the Simulink model reproduces the code solution.\n');
    else
        fprintf('Deviation above 2 mHz — tighten RelTol/MaxStep or report the case.\n');
    end
end
out = struct('t_sl', t_sl, 'f_sl', f_sl, 'y_sl', y_sl, 'ref', ref, ...
             'dev', dev, 'mdl', mdl);
end

function out = evalc_td(SYS, UT, DIST, UTP)
[~, out] = evalc('PSDAT_TimeDomain(SYS, UT, DIST, UTP)');
close(gcf);
end
