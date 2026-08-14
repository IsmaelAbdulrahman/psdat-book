function PSDAT_Scenarios(name)
% PSDAT_SCENARIOS  Named guided studies — each reproduces one educational
% experiment with a single command (MATLAB twin of psdat/studies.py).
%
%   PSDAT_Scenarios            % list the scenarios
%   PSDAT_Scenarios('pv_cloud')
%
% Scenarios: validate | pv_cloud | wind_types | bess_inertia | ffr | pod |
%            syn_inertia
if nargin < 1
    help PSDAT_Scenarios
    return
end
% Each scenario draws its own composite comparison figure; suppress the
% per-run COI/eigenvalue figures the modules would open on top (a 4-run
% sweep would otherwise open five windows).  Standalone module use is
% unaffected -- the flag is cleared the moment the scenario returns.
setappdata(0,'PSDAT_noplot',1); np = onCleanup(@() setappdata(0,'PSDAT_noplot',0)); %#ok<NASGU>
switch name
case 'validate'
    fprintf('--- base-case validation (published modes) ---\n');
    PSDAT_SelfTest(1);
case 'pv_cloud'
    % cloud transient: GFL PV vs curtailed GFM PV
    D = struct('cloud',[3 0.6 2.0],'tsim',18);
    o1 = PSDAT_TimeDomain('IEEE9', {'SG','SG','PV-GFL'}, D);
    o2 = PSDAT_TimeDomain('IEEE9', {'SG','SG','PV-GFM'}, D);
    figure; hold on; grid on;
    plot(o1.t, o1.fCOI, 'r', 'LineWidth', 1.8);
    plot(o2.t, o2.fCOI, 'g', 'LineWidth', 1.8);
    legend('PV-GFL','PV-GFM (10% headroom)');
    xlabel('Time (s)'); ylabel('COI frequency (Hz)');
    title('Cloud transient over the bus-3 PV plant');
case 'wind_types'
    % the same IEC gust on Type-1 / Type-3 / Type-4 turbines
    D = struct('gust',[3 0.15 2.0],'tsim',16);
    tags = {'WT1','WT3','WT4-GFL'}; cols = {'r','b','g'};
    figure; hold on; grid on;
    for a = 1:3
        o = PSDAT_TimeDomain('IEEE9', {'SG','SG',tags{a}}, D);
        % plant output from the network side at bus 3
        V = o.Z(:, o.S.Vidx); TH = o.Z(:, o.S.THidx);
        P = zeros(size(o.t));
        for b = 1:numel(o.t)
            Vc = (V(b,:).').*exp(1i*TH(b,:).');
            Sn = Vc.*conj(o.S.Ybus*Vc);
            P(b) = real(Sn(3)) + o.S.PL0(3);
        end
        plot(o.t, P*100, cols{a}, 'LineWidth', 1.6);
        fprintf('  %-8s output swing %.1f MW\n', tags{a}, 100*(max(P)-min(P)));
    end
    legend('Type-1 (fixed speed)','Type-3 (DFIG)','Type-4 (full conv.)');
    xlabel('Time (s)'); ylabel('plant output (MW)');
    title('Same gust, three wind-turbine generations');
case 'bess_inertia'
    % SOC depletion: an under-sized GFM battery loses its droop share
    UTP = {[],[],struct('Eh',0.004,'SOC0',0.16,'SOCmin',0.10,'dSOC',0.02)};
    D = struct('dPload',[8 0.15 1.0 inf],'tsim',25);
    o = PSDAT_TimeDomain('IEEE9', {'SG','SG','BESS-GFM'}, D, UTP);
    soc = o.X(:, o.S.U(3).xidx(4));
    figure; yyaxis left; plot(o.t, o.fCOI, 'LineWidth', 1.8);
    ylabel('COI frequency (Hz)');
    yyaxis right; plot(o.t, 100*soc, '--', 'LineWidth', 1.4);
    ylabel('SOC (%)'); grid on; xlabel('Time (s)');
    title('SOC depletion: frequency support collapses at SOC_{min}');
case 'ffr'
    D = struct('dPload',[8 0.15 1.0 inf],'tsim',12);
    figure; hold on; grid on;
    for Kf = [0 10 25 50]
        UTP = {[], struct('Kf',Kf), []};
        o = PSDAT_TimeDomain('IEEE9', {'SG','BESS-GFL','GFL'}, D, UTP);
        plot(o.t, o.fCOI, 'LineWidth', 1.6, 'DisplayName', sprintf('K_f = %d', Kf));
        fprintf('  Kf=%2d: nadir %.3f Hz\n', Kf, min(o.fCOI(o.t >= 1)));
    end
    legend show; xlabel('Time (s)'); ylabel('COI frequency (Hz)');
    title('Battery fast-frequency response: droop-gain sweep');
case 'pod'
    PSDAT_Design;                 % Kundur GFM-battery POD showcase
case 'syn_inertia'
    D = struct('dPload',[8 0.15 1.0 inf],'tsim',20);
    figure; hold on; grid on;
    lbls = {'synthetic inertia off','synthetic inertia on'};
    for si = [0 1]
        UTP = {[],[],struct('syn_in',si,'Ksi',120,'Tsi',0.5)};
        o = PSDAT_TimeDomain('IEEE9', {'SG','SG','WT4-GFL'}, D, UTP);
        plot(o.t, o.fCOI, 'LineWidth', 1.6, 'DisplayName', lbls{si+1});
    end
    legend show; xlabel('Time (s)'); ylabel('COI frequency (Hz)');
    title('Type-4 synthetic inertia: first-dip help, recovery-dip payback');
otherwise
    error('unknown scenario %s (run PSDAT_Scenarios with no argument for the list)', name);
end
end
