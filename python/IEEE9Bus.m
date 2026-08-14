function mpc = IEEE9Bus
% This file is obtained from MATPOWER package- case 9-Bus system [1].
% [1]	R. D. Zimmerman, C. E. Murillo-Sánchez, and R. J. Thomas, "MATPOWER: Steady-State Operations, Planning and Analysis Tools for Power Systems Research and Education," Power Systems, IEEE Transactions on, vol. 26, no. 1, pp. 12-19, Feb. 2011.
mpc.baseMVA = 100;
%% bus data
%	bus_i	type	Pd	Qd	  Gs	Bs	area	Vm	    Va	baseKV	zone	Vmax	Vmin
mpc.bus = [
	1	    3	    0	0	   0	0	1	    1.04	0   345	    1	    1.1	    0.9;
	2	    2	    0	0	   0	0	1	    1.025	0	345	    1	    1.1	    0.9;
	3	    2	    0	0	   0	0	1	    1.025	0	345	    1	    1.1	    0.9;
	4	    1	    0	0	   0	0	1	    1   	0	345	    1	    1.1	    0.9;
	5	    1	    125	50	   0	0	1	    1	    0	345	    1	    1.1	    0.9;
	6	    1	    90	30	   0	0	1	    1	    0	345	    1	    1.1	    0.9;
	7	    1	    0	0	   0	0	1	    1	    0	345	    1	    1.1	    0.9;
	8	    1	    100 35	   0	0	1	    1	    0	345	    1	    1.1	    0.9;
	9	    1	    0	0	   0	0	1	    1	    0	345	    1	    1.1	    0.9;
];

%% generator data
%	bus	Pg	Qg	Qmax Qmin	Vg	    mBase	status	Pmax	Pmin	Pc1	Pc2	Qc1min	Qc1max	Qc2min	Qc2max	ramp_agc	ramp_10	ramp_30	ramp_q	apf
mpc.gen = [
	1	0	0	300	-300	1.040	100	    1	    250	    10	    0	0	0	    0	    0	    0	    0	        0	    0	    0	    0;
	2	163	0	300	-300	1.025	100	    1	    300	    10	    0	0	0	    0	    0	    0	    0	        0	    0	    0	    0;
	3	85	0	300	-300	1.025	100	    1	    270	    10	    0	0	0	    0	    0	    0	    0	        0	    0	    0	    0;
];
%% branch data
%	fbus	tbus	r	   x	    b	    rateA rateB	rateC	ratio	    angle	status	angmin	angmax
mpc.branch = [
	1	    4	    0	    0.0576	0	    250	  250	250	    0	        0	    1	    -360	360;
	4	    6	    0.017	0.092	0.158	250	  250	250	    0           0	    1	    -360	360;
	6	    9	    0.039	0.17	0.358	150	  150	150	    0           0	    1	    -360	360;
	3	    9	    0	    0.0586	0	    300	  300	300	    0	        0	    1	    -360	360;
	8	    9	    0.0119	0.1008	0.209	150	  150	150	    0	        0	    1	    -360	360;
	7	    8	    0.0085	0.072	0.149	250	  250	250	    0	        0	    1	    -360	360;
	2	    7	    0	    0.0625	0	    250	  250	250	    0	        0	    1	    -360	360;
	5	    7	    0.032	0.161	0.306	250	  250	250	    0	        0	    1	    -360	360;
	4	    5	    0.01	0.085	0.176	250	  250	250	    0	        0	    1	    -360	360;
];
