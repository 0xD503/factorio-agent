-- factorio-agent: this file and agent/*.lua are written into the save by `fx` (see fxa/savefile.py).
if not helpers then error("factorio-agent needs Factorio 2.0 or newer") end
require('__base__/script/freeplay/control.lua')
require('event_handler').add_lib(require('agent.main'))
