function tf = psdat_noplot()
%PSDAT_NOPLOT  True while the app suppresses module-side plotting.
%
% The interactive app draws its OWN result figures (eigenvalue map, COI
% response); when it drives PSDAT_Linearization / PSDAT_TimeDomain it sets
% this flag so the modules skip their standalone plots — otherwise every run
% would open the same figure twice.  Standalone module use (flag unset) and
% the guided scenarios (flag cleared) plot exactly as before.
tf = isequal(getappdata(0,'PSDAT_noplot'), 1);
end
