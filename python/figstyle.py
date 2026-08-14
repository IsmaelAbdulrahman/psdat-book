"""Shared plotting style for all PSDAT figures (serif, Times-compatible,
consistent with the published PSDAT-IBR paper figures)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Liberation Serif', 'Nimbus Roman', 'DejaVu Serif'],
    'mathtext.fontset': 'stix',
    'font.size': 11, 'axes.grid': True, 'grid.alpha': 0.3,
    'axes.axisbelow': True, 'figure.dpi': 160, 'savefig.dpi': 200,
    'axes.linewidth': 0.8, 'lines.linewidth': 1.8,
})
# consistent technology colours (as in the PSDAT-IBR paper)
C_SG = '#1f3b73'    # synchronous machine        (deep blue)
C_GFL = '#c0392b'   # grid-following             (red)
C_GFM = '#1e8449'   # grid-forming               (green)
C_ALL = '#8e44ad'   # 100%-converter / mixed     (purple)
C_PV = '#b7950b'    # photovoltaic               (dark gold)
C_WT = '#117a8b'    # wind                       (teal)
C_BESS = '#a04000'  # battery storage            (burnt orange)
GRY = '#555555'
EVENT = dict(color='#bbbbbb', alpha=0.35, zorder=0)
