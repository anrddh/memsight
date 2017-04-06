
def start():
	return 0x400596

def end():
	return [0x4005b3]

def avoid():
	return [0x4005cc]

def do_start(state):
	params = {}
	params['edi'] = state.regs.edi
	return params

def do_end(state, params, pg):
	sol = state.se.any_n_int(params['edi'], 5)
	for s in sol: assert s < 1000
	print "EDI: " + str(sol)
