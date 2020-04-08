
def start():
    return 0x80483ed


def end():
    return [0x80483ec]


def avoid():
    return [0x8048405]


def do_start(state):
    params = {}
    return params


def do_end(state, params, pg):
    v = state.regs.eax
    sol = state.solver.eval_upto(v, 10)
    print(sol)
