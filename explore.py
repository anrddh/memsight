"""Explore a binary using angr or memsight symbolic execution engine."""
import sys
import logging
import utils
from executor import executor
from memory import factory

if __name__ == '__main__':

    # logging.getLogger('angr').setLevel(logging.DEBUG)
    # logging.getLogger('simuvex').setLevel(logging.DEBUG)

    logging.getLogger('angr.analyses.veritesting').setLevel(logging.DEBUG)

    t, fname = utils.parse_args(sys.argv)

    explorer = executor.Executor(fname)
    angr_project = explorer.project

    if t == 0:
        mem_memory, reg_memory = factory.get_angr_symbolic_memory(angr_project)
    elif t == 1:
        mem_memory, reg_memory = factory.get_range_fully_symbolic_memory(
            angr_project)
        mem_memory.verbose = False

    explorer.explore(mem_memory=mem_memory, reg_memory=reg_memory)
