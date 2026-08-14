function nm = psdat_sysname(SYS)
% PSDAT_SYSNAME  Display name for a system argument that may be either a
% benchmark name (char) or a drawn-network case struct (from psdat_netcase).
% Used by the analysis drivers so their printouts/titles work in both cases.
if ischar(SYS)
    nm = SYS;
elseif isstruct(SYS) && isfield(SYS,'name')
    nm = SYS.name;
else
    nm = 'custom network';
end
end
