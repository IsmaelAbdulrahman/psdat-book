function d = psdat_machinedata(SYS, ws)
% PSDAT_MACHINEDATA  Synchronous-machine dynamic data for the bundled systems.
%
%   d = psdat_machinedata(SYS, ws)
%
% Returns the per-machine round-rotor data (2-axis sub-transient model +
% IEEE Type-1 exciter + turbine-governor) as struct-of-arrays d.H, d.Xd, ...
% on the 100-MVA system base, indexed by machine position.  Shared by
% psdat_system (benchmark assembly) and psdat_benchmark (load a benchmark as
% an editable single-line diagram), so the two never drift.  ws = 2*pi*f0.
if nargin < 2 || isempty(ws), ws = 2*pi*60; end
switch SYS
case 'IEEE9'
    d.H    = [23.640 6.4000 3.0100];
    d.Xd   = [0.1460 0.8958 1.3125];  d.Xdp  = [0.0608 0.1198 0.1813];
    d.Xdpp = [0.0489 0.0881 0.1133];  d.Xq   = [0.0969 0.8645 1.2578];
    d.Xqp  = [0.0969 0.1969 0.2500];  d.Xqpp = [0.0396 0.0887 0.0833];
    d.Td0p = [8.9600 6.0000 5.8900];  d.Td0pp= [0.1150 0.0337 0.0420];
    d.Tq0p = [0.3100 0.5350 0.6000];  d.Tq0pp= [0.0330 0.0780 0.1875];
    d.Rs   = [0.0041 0.0026 0.0035];  d.Xls  = [0.1200 0.1020 0.0750];
    d.Dm   = [0.1*(2*23.64)/ws 0.2*(2*6.4)/ws 0.3*(2*3.01)/ws];
    o = ones(1,3);
    d.KA = 20*o;  d.TA = 0.2*o;  d.KE = 1*o;    d.TE = 0.314*o;
    d.KF = 0.063*o; d.TF = 0.35*o; d.Ax = 0.0039*o; d.Bx = 1.555*o;
    d.TCH = 0.10*o; d.TSV = 0.05*o; d.RD = 0.05*o;
case 'Kundur2A'
    o = ones(1,4);
    d.H    = [58.5 58.5 55.575 55.575];
    d.Xd   = 0.2*o;      d.Xdp  = 0.0333*o;  d.Xdpp = 0.02778*o;
    d.Xq   = 0.18889*o;  d.Xqp  = 0.06111*o; d.Xqpp = 0.02778*o;
    d.Td0p = 8.0*o;      d.Td0pp= 0.03*o;    d.Tq0p = 0.4*o;   d.Tq0pp = 0.05*o;
    d.Rs   = 0.000278*o; d.Xls  = 0.02222*o;
    d.Dm   = 0.10*o;
    d.KA = 200*o; d.TA = 0.01*o; d.KE = 1*o; d.TE = 0.05*o;
    d.KF = 0.001*o; d.TF = 0.1*o; d.Ax = 0*o; d.Bx = 0*o;
    d.TCH = 0.10*o; d.TSV = 0.05*o; d.RD = 0.05*o;
case {'case68','NE68','NETS68'}
    d.H    = [42 30.2 35.8 28.6 26 34.8 26.4 24.3 34.5 31 28.2 92.3 248 300 300 225];
    d.Xd   = [0.1 0.295 0.2495 0.262 0.33 0.254 0.295 0.29 0.2106 0.169 0.128 0.101 0.0296 0.018 0.018 0.0356];
    d.Xdp  = [0.031 0.0697 0.0531 0.0436 0.066 0.05 0.049 0.057 0.057 0.0457 0.018 0.031 0.0055 0.0029 0.0029 0.0071];
    d.Xdpp = [0.025 0.05 0.045 0.035 0.05 0.04 0.04 0.045 0.045 0.04 0.012 0.025 0.004 0.0023 0.0023 0.0055];
    d.Xq   = [0.069 0.282 0.237 0.258 0.31 0.241 0.292 0.28 0.205 0.115 0.123 0.095 0.0286 0.0173 0.0173 0.0334];
    d.Xqp  = [0.0417 0.0933 0.0714 0.0586 0.0883 0.0675 0.0667 0.0767 0.0767 0.0615 0.0241 0.042 0.0074 0.0038 0.0038 0.0095];
    d.Xqpp = [0.025 0.05 0.045 0.035 0.05 0.04 0.04 0.045 0.045 0.04 0.012 0.025 0.004 0.0023 0.0023 0.0055];
    d.Td0p = [10.2 6.56 5.7 5.69 5.4 7.3 5.66 6.7 4.79 9.37 4.1 7.4 5.9 4.1 4.1 7.8];
    d.Td0pp= 0.05*ones(1,16);
    d.Tq0p = [1.5 1.5 1.5 1.5 0.44 0.4 1.5 0.41 1.96 1.5 1.5 1.5 1.5 1.5 1.5 1.5];
    d.Tq0pp= 0.035*ones(1,16);
    d.Rs   = zeros(1,16);
    d.Xls  = [0.0125 0.035 0.0304 0.0295 0.027 0.0224 0.0322 0.028 0.0298 0.0199 0.0103 0.022 0.003 0.0017 0.0017 0.0041];
    d.Dm   = 0.01*[4 9.75 10 10 3 10 8 9 14 5.56 13.6 13.5 33 100 100 50];
    o = ones(1,16);
    d.KA = 40*o; d.TA = 0.02*o; d.KE = 1*o; d.TE = 0.785*o;
    d.KF = 0.063*o; d.TF = 0.35*o; d.Ax = 0.07*o; d.Bx = 0.91*o;
    d.TCH = 0.10*o; d.TSV = 0.05*o; d.RD = 0.05*o;
otherwise
    error('psdat_machinedata: unknown system %s', SYS);
end
end
