function out = psdat_sl_store(op, a, b)
% PSDAT_SL_STORE  Shared state for the PSDAT Simulink bridge.
%
% The Simulink model's Interpreted MATLAB Function blocks are stateless, so
% the system struct S (built once by PSDAT_BuildSimulink), the disturbance
% description D, and the warm-started algebraic solution live here in a
% persistent store:
%
%   psdat_sl_store('set', S, D)       store system + disturbance, reset z
%   psdat_sl_store('settag', name)    remember which model owns the store
%   S = psdat_sl_store('S')           get the system struct
%   D = psdat_sl_store('D')           get the disturbance struct
%   z = psdat_sl_store('z')           last algebraic solution (warm start)
%   psdat_sl_store('z', z)            update it
%   psdat_sl_store('resetz')          re-initialise z to the equilibrium
%   psdat_sl_store('check', tag)      guard called by the model's InitFcn:
%                                      errors clearly if the store belongs
%                                      to another model or is empty (fresh
%                                      MATLAB session) — rebuild to run.
persistent S D zlast tag
switch op
case 'set'
    S = a; D = b; zlast = S.z0; out = [];
case 'settag'
    tag = a; out = [];
case 'S', out = S;
case 'D', out = D;
case 'z'
    if nargin > 1, zlast = a; out = [];
    else, out = zlast; end
case 'resetz'
    zlast = S.z0; out = [];
case 'check'
    if isempty(S) || ~strcmp(tag, a)
        error(['PSDAT Simulink: the engine store is empty or belongs to a ' ...
               'different model. Run PSDAT_BuildSimulink (or ' ...
               'PSDAT_RunSimulink) for "%s" first, then press Play.'], a);
    end
    out = [];
otherwise
    error('psdat_sl_store: unknown op %s', op);
end
end
