function mpc = Kundur2A
% KUNDUR2A  Kundur two-area, four-machine test system (MATPOWER case).
%
% The classical inter-area oscillation benchmark [Kundur, Power System
% Stability and Control, Example 12.6; Klein, Rogers & Kundur, 1991].
% 100-MVA system base, 60 Hz.  Loads: bus 7 (967 MW + 100 MVAr, 200 MVAr
% cap) and bus 9 (1767 MW + 100 MVAr, 350 MVAr cap).  Lines: 230-kV
% constants r = 0.0001, x = 0.001, b = 0.00175 pu/km; the 7-8 and 8-9
% corridors are double circuits of 110 km each.
mpc.version = '2';
mpc.baseMVA = 100;

%    bus_i type  Pd     Qd   Gs  Bs  area  Vm     Va  baseKV zone Vmax Vmin
mpc.bus = [
    1   3    0     0    0    0   1   1.03   0   230  1  1.1  0.9;
    2   2    0     0    0    0   1   1.01   0   230  1  1.1  0.9;
    3   2    0     0    0    0   2   1.03   0   230  1  1.1  0.9;
    4   2    0     0    0    0   2   1.01   0   230  1  1.1  0.9;
    5   1    0     0    0    0   1   1.00   0   230  1  1.1  0.9;
    6   1    0     0    0    0   1   1.00   0   230  1  1.1  0.9;
    7   1  967   100    0  200   1   1.00   0   230  1  1.1  0.9;
    8   1    0     0    0    0   3   1.00   0   230  1  1.1  0.9;
    9   1 1767   100    0  350   2   1.00   0   230  1  1.1  0.9;
   10   1    0     0    0    0   2   1.00   0   230  1  1.1  0.9;
   11   1    0     0    0    0   2   1.00   0   230  1  1.1  0.9;
];

%     bus  Pg    Qg  Qmax  Qmin  Vg    mBase status Pmax Pmin
mpc.gen = [
    1   700   0   500  -300  1.03  900  1  900  0;
    2   700   0   500  -300  1.01  900  1  900  0;
    3   719   0   500  -300  1.03  900  1  900  0;
    4   700   0   500  -300  1.01  900  1  900  0;
];

%      fbus tbus  r        x       b        rateA rateB rateC ratio angle status
mpc.branch = [
    1   5   0        0.0167  0        900 0 0 0 0 1;
    2   6   0        0.0167  0        900 0 0 0 0 1;
    3  11   0        0.0167  0        900 0 0 0 0 1;
    4  10   0        0.0167  0        900 0 0 0 0 1;
    5   6   0.0025   0.025   0.04375  500 0 0 0 0 1;
    6   7   0.0010   0.010   0.0175   500 0 0 0 0 1;
    7   8   0.0055   0.055   0.38500  500 0 0 0 0 1;   % 110 km double circuit
    8   9   0.0055   0.055   0.38500  500 0 0 0 0 1;   % 110 km double circuit
    9  10   0.0010   0.010   0.0175   500 0 0 0 0 1;
   10  11   0.0025   0.025   0.04375  500 0 0 0 0 1;
];
end
