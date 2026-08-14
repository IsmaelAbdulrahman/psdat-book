#!/usr/bin/env python3
"""PSDAT scenario runner.  Usage:
    python3 run_scenario.py                 # list scenarios
    python3 run_scenario.py pv_cloud        # run one (figures -> ./figs)
    python3 run_scenario.py all             # run everything
"""
import sys
import studies

if len(sys.argv) < 2:
    print(__doc__)
    print("scenarios:", ", ".join(studies.REGISTRY))
    sys.exit(0)
studies.run(sys.argv[1], outdir=sys.argv[2] if len(sys.argv) > 2 else 'figs')
