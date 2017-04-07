
def start():
	return 0x4004d6

def end():
	return [0x4004ff]

def avoid():
	return []

def do_start(state):
	params = {}
	params['edi'] = state.regs.edi
	params['veritesting'] = True
	params['max_rounds'] = 2
	state.se.add(params['edi'] < 9)
	return params

def do_end(state, params, pg):

	o = state.se.Concat(params['edi'], state.regs.eax)
	sol = state.se.any_n_int(o, 10)
	import ctypes
	eax = []
	edi = []
	for k in range(len(sol)):
		edi.append(ctypes.c_int((sol[k] & (0xFFFFFFFF << 32)) >> 32).value)
		eax.append(ctypes.c_int(sol[k] & 0xFFFFFFFF).value)
		assert edi[-1] == eax[-1]

	assert len(edi) == 9
	assert len(eax) == 9
	print "I: " + str(edi)
	print "SUM:" + str(eax)
