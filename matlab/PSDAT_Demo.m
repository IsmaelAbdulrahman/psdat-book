%% PSDAT classroom tour
% Open this file in the MATLAB *Live Editor* (right-click > Open as Live
% Script) and run it section by section.  It walks through the whole
% toolbox: unit mixes, exact linearization, the three disturbance classes,
% and control design.  Requires MATPOWER on the path.

%% 1. A familiar starting point — the all-synchronous IEEE 9-bus
% PSDAT reproduces the published PSDAT modes to five significant figures:
% the 1.4443-Hz inter-area and 2.3721-Hz local electromechanical modes.
R = PSDAT_Linearization('IEEE9', {'SG','SG','SG'});

%% 2. Change ONE line to re-equip the grid
% Replace G2 by a grid-forming battery and G3 by a PV plant.  Everything
% else — network, load flow, analysis — is untouched.  New physics appears
% in the eigenvalues: a DC-link mode, converter synchronization modes.
R = PSDAT_Linearization('IEEE9', {'SG','BESS-GFM','PV-GFL'});

%% 3. Who drives that mode?  Ask the participation factors
% Column j of R.P is mode j, row i is state i (names in R.names).  Find
% the least-damped oscillatory mode and its top states:
lam = R.lambda;  osc = find(imag(lam) > 2*pi*0.05);
[~, jj] = min(-real(lam(osc))./abs(lam(osc)));  j = osc(jj);
[p, ix] = sort(R.P(:, j), 'descend');
fprintf('mode %.2f Hz, %.1f%%:\n', imag(lam(j))/2/pi, -real(lam(j))/abs(lam(j))*100);
nm = R.names{1};
for a = 1:4, fprintf('   %-10s %.2f\n', nm{ix(a)}, p(a)); end

%% 4. Source-side disturbance: a cloud crosses the PV plant
% The third disturbance class of PSDAT — the renewable resource itself.
D = struct('cloud', [3 0.6 2.0], 'tsim', 18);
PSDAT_TimeDomain('IEEE9', {'SG','BESS-GFM','PV-GFL'}, D);

%% 5. Wind: three turbine generations, one gust
% Type 1 passes the gust to the grid; the DFIG and the full-converter
% machine buffer it in the rotor.  (Takes ~a minute.)
PSDAT_Scenarios('wind_types');

%% 6. Virtual inertia is a dial
% A 100%-converter grid with GFM batteries: the initial slope (RoCoF) is
% set by Hv, the settling frequency by the droop.
D = struct('dPload', [8 0.15 1.0 inf], 'tsim', 12);
figure; hold on; grid on
for Hv = [2 5 10]
    UTP = {[], struct('Hv',Hv), struct('Hv',Hv)};
    o = PSDAT_TimeDomain('IEEE9', {'SG','BESS-GFM','BESS-GFM'}, D, UTP);
    plot(o.t, o.fCOI, 'LineWidth', 1.6, 'DisplayName', sprintf('H_v = %d s', Hv));
end
legend show; xlabel('Time (s)'); ylabel('COI frequency (Hz)');
title('Virtual-inertia sweep');

%% 7. Exact symbolic linearization — of everything
% The same equation file psdat_dae.m is differentiated SYMBOLICALLY
% (Symbolic Math Toolbox required); the state matrix matches the numerical
% one to ~7 digits, PLL trigonometry, PV exponential, Cp surface and all.
PSDAT_Symbolic('IEEE9', {'SG','BESS-GFM','PV-GFL'});

%% 8. Control design: damp the Kundur inter-area mode from a battery
% Residue-based POD placement and tuning, verified on the exact closed loop.
PSDAT_Design;

%% 9. Verify your installation any time
PSDAT_SelfTest(1);
