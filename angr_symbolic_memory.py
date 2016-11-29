import angr, logging
from itertools import product
import struct
import claripy
import resource
import pdb
import simuvex
import sys
import os
import pyvex
from bitstring import Bits
import traceback
import bisect

l = logging.getLogger('angrSymbolicMemory')
l.setLevel(logging.DEBUG)

class SymbolicMemory(simuvex.plugins.plugin.SimStatePlugin):

    def __init__(self, memory_backer=None, 
                permissions_backer=None, 
                kind=None, 
                arch=None, 
                endness=None, 
                check_permissions=None,
                angr_memory=None):
        simuvex.plugins.plugin.SimStatePlugin.__init__(self)

        if angr_memory is not None:
            self._angr_memory = angr_memory
            return

        if kind == 'mem':
            self._angr_memory = simuvex.plugins.SimSymbolicMemory(memory_backer=memory_backer, permissions_backer=permissions_backer, memory_id='mem')
        elif kind == 'reg':
            self._angr_memory = simuvex.plugins.SimSymbolicMemory(memory_id="reg", endness=arch.register_endness)


    def set_state(self, state):
        self._angr_memory.set_state(state) 


    def load(self, addr, size=None, condition=None, fallback=None, add_constraints=None, action=None, endness=None, inspect=True, ignore_endness=False):
        self.log("Loading at " + str(addr) + " " + str(size) + " bytes.")
        data = self._angr_memory.load(addr, size, condition, fallback, add_constraints, action, endness, inspect)
        return data


    def store(self, addr, data, size=None, condition=None, add_constraints=None, endness=None, action=None, inspect=True, priv=None, ignore_endness=False):
        self.log("Storing at " + str(addr) + " " + str(size) + " bytes. Content: " + str(data))
        self._angr_memory.store(addr, data, size, condition, add_constraints, endness, action, inspect, priv)


    @property
    def category(self):
        return self._angr_memory.category


    def copy(self):
        return SymbolicMemory(angr_memory=self._angr_memory.copy())

    @property
    def id(self):
        return self._angr_memory.id


    @property
    def mem(self):
        return self._angr_memory.mem


    def log(self, msg):
        l.debug("[" + self.id + "] " + msg)


    def verbose(self, v):
        if not v:
            l.setLevel(logging.INFO)