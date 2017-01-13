import angr 
import logging
import claripy
import pdb
import simuvex
import sys
import os
import pyvex
import traceback
import bisect
import cffi
import utils

l = logging.getLogger('naiveFullySymbolicMemory')
l.setLevel(logging.DEBUG)

class MemoryObject(object):

    def __init__(self, obj, offset):
        self.obj = obj
        self.offset = offset
        self.raw_byte = None


    def __repr__(self):
        return "(" + str(self.obj) + " @ " + str(self.offset) + ")"


    def get_byte(self):

        if self.raw_byte is None:
            self.raw_byte = utils.get_obj_bytes(self.obj, self.offset, 1)[0]
            self.obj = self.raw_byte
            self.offset = 0

        return self.raw_byte


class MappedRegion(object):

    PROT_READ = 1
    PROT_WRITE = 2
    PROT_EXEC = 4

    def __init__(self, addr, length, permissions):
        self.addr = addr
        self.length = length
        self.permissions = permissions


    def __repr__(self):
        rwx_s  = "r" if self.is_readable() else ''
        rwx_s += "w" if self.is_writable() else ''
        rwx_s += "x" if self.is_executable() else ''
        return "(" + str(hex(self.addr)) + ", " + str(hex(self.addr + self.length)) + ") [" + rwx_s +"]"


    def is_readable(self):
        return self.permissions.args[0] & MappedRegion.PROT_READ


    def is_writable(self):
        return self.permissions.args[0] & MappedRegion.PROT_WRITE    


    def is_executable(self):
        return self.permissions.args[0] & MappedRegion.PROT_EXEC


class SymbolicMemory(simuvex.plugins.plugin.SimStatePlugin):

    def __init__(self, memory_backer=None, 
                permissions_backer=None, 
                kind=None, 
                arch=None, 
                endness=None, 
                check_permissions=None, 
                concrete_memory={},
                symbolic_memory=[],
                initialized=False,
                stack_range=None,
                mapped_regions=[]):
        simuvex.plugins.plugin.SimStatePlugin.__init__(self)

        self._memory_backer = memory_backer
        self._permissions_backer = permissions_backer
        self._id = kind
        self._arch = arch
        self._endness = "Iend_BE" if endness is None else endness
        
        self._concrete_memory = concrete_memory
        self._symbolic_memory = symbolic_memory

        self._initialized = initialized

        # some threshold
        self._maximum_symbolic_size = 8 * 1024
        self._maximum_concrete_size = 0x1000000

        # stack range
        self._stack_range = stack_range

        # mapped regions
        self._mapped_regions = mapped_regions

        self.log("symbolic memory has been created")

    def _init_memory(self):

        if self._initialized:
            return

        # init mapped regions
        for start, end in self._permissions_backer[1]:

            perms = self._permissions_backer[1][(start, end)]
            self.map_region(start, end-start, perms)

        # init memory
        if self._memory_backer is not None:

            _ffi = cffi.FFI()

            for addr, backer in self._memory_backer.cbackers:

                data = _ffi.buffer(backer)[:]
                obj = claripy.BVV(data)

                self.log("Initialing memory at " + hex(addr) + " with " + str(len(obj) / 8) + " bytes")

                for k in range(len(obj) / 8):
                    self._concrete_memory[k + addr] = MemoryObject(obj, k)

        self._initialized = True

    def set_state(self, state):
        self.log("setting current state...")
        self.state = state    
        self._init_memory()

    def memory_op(self, addr, size, data=None):

        reg_name = None
        if self._id == 'reg': 

            if type(addr) in (int, long):
                reg_name = utils.reverse_addr_reg(self, addr)
                self.log("\t" + str(addr) + " => " + str(reg_name))

            if isinstance(addr, basestring):
                reg_name = addr
                addr, size_reg = utils.resolve_location_name(self, addr)
                self.log("\t" + str(addr) + " => " + str(reg_name))

                # a load from a register, derive size from reg size
                if size is None:
                    size = size_reg
                    self.log("\tsize => " + str(size))

                assert size_reg == size

            assert reg_name is not None
            
        # if this is a store then size can be derived from data that needs to be stored
        if size is None and type(data) in (claripy.ast.bv.BV,):
            size = len(data) / 8
            assert type(size) in (int, long)
            self.log("\tsize => " + str(size))

        # convert size to BVV if concrete
        if type(size) in (int, long):
            size = self.state.se.BVV(size, self.state.arch.bits)

        # make size concrete
        if size is not None:
            min_size, max_size = self._resolve_size_range(size)
            size = max_size

        # if addr is constant, make it concrete
        if type(addr) in (claripy.ast.bv.BV,) and not addr.symbolic:
            addr = addr.args[0]

        assert size is not None
        if self._id == 'reg':
            assert type(addr) in (int, long)

        return addr, size, reg_name

    def _find_concrete_memory(self, a, b):

        assert b >= a
        addresses = []

        if b - a > 1024:

            addrs = sorted(self._concrete_memory.keys()) # expensive, we should keep it sorted across ops
            index = bisect.bisect_left(addrs, a)

            while index < len(addrs):

                if addrs[index] > b: 
                    break

                elif addrs[index] >= a:
                    if addrs[index] in self._concrete_memory:
                        addresses.append(addrs[index])
                index += 1

        else:
            for addr in range(a, b + 1):
                if addr in self._concrete_memory:
                    addresses.append(addr)

        return addresses

    def build_ite(self, addr, addrs, v, obj):

        if len(addrs) == 1:
            cond = addr == addrs[0] 
        else:
            cond = self.state.se.And(addr >= addrs[0], addr <= addrs[-1])

        return self.state.se.If(cond, v, obj)

    def load(self, addr, size=None, condition=None, fallback=None, add_constraints=None, action=None, endness=None, inspect=True, ignore_endness=False):

        try:

            self.log("Loading at " + str(addr) + " " + str(size) + " bytes.")

            i_addr = addr
            i_size = size

            assert self._id == 'mem' or self._id == 'reg'

            addr, size, reg_name = self.memory_op(addr, size)        

            if type(size) in (int, long):

                min_addr = None
                max_addr = None

                # concrete address
                if type(addr) in (int, long):
                    min_addr = addr
                    max_addr = addr

                # symbolic addr
                else:
                    min_addr = self.state.se.min_int(addr)
                    max_addr = self.state.se.max_int(addr)
                    if min_addr == max_addr:
                        addr = min_addr

                # check permissions
                self.check_sigsegv_and_refine(addr, min_addr, max_addr, False)

                data = None
                for k in range(size):

                    obj = utils.get_unconstrained_bytes(self.state, "bottom", 8)

                    self.log("\tLoading from: " + str(addr + k))

                    # check versus concrete addresses
                    concrete_addresses = self._find_concrete_memory(min_addr + k, max_addr + k)
                    if len(concrete_addresses) == 1:

                        v = self._concrete_memory[concrete_addresses[0]].get_byte()
                        if min_addr == max_addr: # constant addr
                            obj = v
                        else:
                            obj = self.state.se.If(addr + k == concrete_addresses[0], v, obj)

                    else:

                        addrs = []
                        for i in range(len(concrete_addresses)):

                            concrete_addr = concrete_addresses[i]
                            addrs.append(concrete_addr)
                            v = self._concrete_memory[concrete_addr].get_byte()

                            # lookahead for merging
                            merged = False
                            if i + 1 < len(concrete_addresses) and concrete_addr + 1 == concrete_addresses[i + 1]:

                                next_v = self._concrete_memory[concrete_addr + 1].get_byte()
                                if v.op == 'BVV':

                                    # both constant and equal
                                    if next_v.op == 'BVV' and v.args[0] == next_v.args[0]:
                                        #self.log("\tmerging ite with same constant and consecutive address")
                                        merged = True

                                # same symbolic object
                                elif v is next_v:
                                    #self.log("\tmerging ite with same sym and consecutive address")
                                    merged = True

                            if not merged:
                                self.log("\tbuilding ite with " + str(len(addrs)) + " addresses")
                                obj = self.build_ite(addr + k, addrs, v, obj)
                                addrs = []

                        if len(addrs) > 0:
                            self.log("\tbuilding ite with " + str(len(addrs)) + " addresses")
                            obj = self.build_ite(addr + k, addrs, v, obj)
                            addrs = []

                    # check versus any symbolic address                
                    for o in self._symbolic_memory:

                        e = o[0]
                        v = o[1].get_byte()

                        #self.log("\tchecking symbolic address: " + str(e) + " with " + str(addr + k))
                        #pdb.set_trace()

                        if self.intersect(e, addr + k):
                            #self.log("\tadding ite with symbolic address")
                            obj = self.state.se.If(e == addr + k, v, obj)


                    #self.log("\tappending data: " + str(obj))
                    data = self.state.se.Concat(data, obj) if data is not None else obj

                # fix endness
                endness = self._endness if endness is None else endness
                if not ignore_endness and endness == "Iend_LE":
                    #self.log("\treversing data: " + str(data))
                    data = data.reversed

                #self.log("\treturning data: " + str(data))
                return data

            assert False

        except Exception as e:
            print str(e)
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def store(self, addr, data, size=None, condition=None, add_constraints=None, endness=None, action=None, inspect=True, priv=None, ignore_endness=False, internal=False):

        try:

            if not internal:
                self.log("Storing at " + str(addr) + " " + str(size) + " bytes. Content: " + str(data))

            i_addr = addr
            i_size = size
            i_data = data

            assert self._id == 'mem' or self._id == 'reg'

            addr, size, reg_name = self.memory_op(addr, size, data)

            # convert data to BVV if concrete
            data = utils.convert_to_ast(self.state, data, size if isinstance(size, (int, long)) else None)

            if type(size) in (int, long):

                assert len(data) / 8 == size

                # simplify
                data = self.state.se.simplify(data)

                # fix endness
                endness = self._endness if endness is None else endness
                if not ignore_endness and endness == "Iend_LE":
                    if not internal:
                        #self.log("\treversing data: " + str(data))
                        pass
                    data = data.reversed
                    #self.log("\treversed data: " + str(data))


                min_addr = None
                max_addr = None

                # concrete address
                if type(addr) in (int, long):
                    min_addr = addr
                    max_addr = addr

                # symbolic addr
                else:
                    min_addr = self.state.se.min_int(addr)
                    max_addr = self.state.se.max_int(addr)
                    if min_addr == max_addr:
                        addr = min_addr

                # check permissions
                self.check_sigsegv_and_refine(addr, min_addr, max_addr, True)

                to_add = []
                to_replace = []
                to_remove = []
                for k in range(size):

                    obj = MemoryObject(data, k)

                    if not internal:
                        #self.log("\tSlicing data with offset " + str(k) + " => " + str(obj))
                        pass

                    # concrete addr
                    if type(addr) in (int, long):
                        if not internal:
                            self.log("\tAdding to concrete memory as: " + str(addr + k))
                        self._concrete_memory[addr + k] = obj

                    flag = False
                    count = 0
                    for o in self._symbolic_memory:

                        e = o[0]
                        v = o[1]

                        #self.log("\tEval: " + str(e) + " with " + str(addr + k))

                        if self.disjoint(e, addr + k):
                            self.log("\tDisjoint")
                            continue

                        elif self.equiv(e, addr + k):
                            self.log("\tEquiv")

                            # if addr was
                            if type(addr + k) in (int, long):
                                to_remove.append(count)
                            else:
                                to_replace.append([e, obj])

                            flag = True

                        else:
                            self.log("\tOther")
                            to_replace.append([e, self.state.se.If(e == addr + k, obj, v)])

                        count += 1

                    if not flag and type(addr) not in (int, long):
                        self.log("\tNot inserted. Added later.")
                        to_add.append([addr + k, obj])

                for q in range(len(to_remove)):
                    index = to_remove[q]
                    self._symbolic_memory.pop(index - q)

                for o in to_replace:
                    for oo in self._symbolic_memory:
                        if oo[0] is o[0]:
                            #self.log("\tReplacing for " + str(o[0]) + " data: " + str(oo[1]) + " => " + str(o[1]))
                            oo[1] = o[1]

                for o in to_add:
                    #self.log("\tAdding: " + str(o[0]) + " data: " + str(o[1]))
                    self._symbolic_memory.append(o)

                return

            assert False   

        except Exception as e:
            import traceback
            print str(e)
            traceback.print_exc()
            sys.exit(1)

    def equiv(self, a, b):
        try:
            cond = a != b
            return not self.state.se.satisfiable(extra_constraints=(cond,))
        except Exception as e:
            import traceback
            traceback.print_exc()
            sys.exit(1)


    def intersect(self, a, b):
        try:
            cond = a == b
            return self.state.se.satisfiable(extra_constraints=(cond,))
        except Exception as e:
            import traceback
            traceback.print_exc()
            sys.exit(1)


    def disjoint(self, a, b):
        return not self.intersect(a, b)

    def dump_memory(self):
        pass

    def _resolve_size_range(self, size):

        if not self.state.se.symbolic(size):
            i = self.state.se.any_int(size)
            if i > self._maximum_concrete_size:
                raise SimMemoryLimitError("Concrete size %d outside of allowable limits" % i)
            return i, i

        max_size = self.state.se.max_int(size)
        min_size = self.state.se.min_int(size)

        # we do not support symbolic size yet...
        if min_size != max_size:
            #print "addr " + str(self.state.ip)
            #print self.full_stack()
            #assert min_size == max_size
            self.log("size is symbolic: using the max size")

        if min_size > self._maximum_symbolic_size:
            assert False
            min_size = self._maximum_symbolic_size

        return min_size, min(max_size, self._maximum_symbolic_size)


    @property
    def category(self):
        if self._id in ('reg', 'mem'):
            return self._id


    def copy(self):
        self.log("Copying memory")
        s = SymbolicMemory(memory_backer=self._memory_backer, 
                                permissions_backer=self._permissions_backer, 
                                kind=self._id, 
                                arch=self._arch, 
                                endness=self._endness, 
                                check_permissions=None, 
                                concrete_memory=self._concrete_memory.copy(),
                                symbolic_memory=self._symbolic_memory[:],
                                initialized=self._initialized,
                                stack_range=self._stack_range,
                                mapped_regions=self._mapped_regions[:])

        return s


    @property
    def id(self):
        return self._id


    @property
    def mem(self):

        # In angr, this returns a reference to the (internal) paged memory
        # We do not have (yet) a paged memory. We instead return self
        # that exposes a _preapproved_stack attribute
        # (similarly as done by a paged memory)

        self.log("getting reference to paged memory")
        #traceback.print_stack()
        return self


    @property
    def _preapproved_stack(self):
        return self._stack_range


    @_preapproved_stack.setter
    def _preapproved_stack(self, value):
        self.log("Boundaries on stack have been set by the caller: (" + str(hex(value.start)) + ", " + str(hex(value.end)) + ")")
        
        if self._stack_range is not None:
            self.log("\tUnnmapping old stack...")
            for k in range(len(self._mapped_regions)):
                region = self._mapped_regions[k]
                if region.addr == self._stack_range.start:
                    del self._mapped_regions[k]
                    self.log("\tDone.")
                    break

        self._stack_range = value
        self.map_region(value.start, value.end - value.start, MappedRegion.PROT_READ | MappedRegion.PROT_WRITE)


    def log(self, msg):
        l.debug("[" + self._id + "] " + msg)


    def verbose(self, v):
        if not v:
            l.setLevel(logging.INFO)


    def map_region(self, addr, length, permissions):

        self.log("Required mapping of length " + str(length) + " at " + str(hex(addr)) + ".")

        if self.state.se.symbolic(addr) or self.state.se.symbolic(length):
            assert False

        # make if concrete
        if isinstance(addr, claripy.ast.bv.BV):
            addr = self.state.se.max_int(addr)

        # make perms a bitvector to easily check them
        if isinstance(permissions, (int, long)):
            permissions = claripy.BVV(permissions, 3)

        # keep track of this region
        self._mapped_regions.append(MappedRegion(addr, length, permissions))

        self.log("\t" + str(self._mapped_regions[-1]))

        # sort mapped regions 
        self._mapped_regions = sorted(self._mapped_regions, key=lambda x: x.addr)


    def unmap_region(self, addr, length):
        assert False


    def permissions(self, addr):

        # return permissions of the addr's region

        if self.state.se.symbolic(addr):
            assert False

        if isinstance(addr, claripy.ast.bv.BV):
            addr = self.state.se.any_int(addr)

        for region in self._mapped_regions:
            if addr >= region.addr and addr <= region.addr + region.length:
                return region.permissions

        # Unmapped region?
        assert False

    def check_sigsegv_and_refine(self, addr, min_addr, max_addr, write_access):

        if simuvex.o.STRICT_PAGE_ACCESS not in self.state.options:
            return

        # (min_addr, max_addr) is our range addr

        access_type = "write" if write_access else "read"

        if len(self._mapped_regions) == 0:
            raise simuvex.s_errors.SimSegfaultError(min_addr, "Invalid " + access_type + " access: [" + str(hex(min_addr)) + ", " + str(hex(max_addr)) + "]")

        last_covered_addr = min_addr - 1
        for region in self._mapped_regions:

            # region is after our range addr
            if max_addr < region.addr:
                break

            # region is before our range addr
            if last_covered_addr + 1 > region.addr + region.length:
                continue

            # there is one addr in our range that could be not covered by any region
            if last_covered_addr + 1 < region.addr:

                # check with the solver: is there a solution for addr?
                if self.state.se.satisfiable(extra_constraints=(addr >= last_covered_addr + 1, addr < region.addr,)):
                    raise simuvex.s_errors.SimSegfaultError(last_covered_addr + 1, "Invalid " + access_type + " access: [" + str(hex(min_addr)) + ", " + str(hex(max_addr)) + "]")

            # last_covered_addr + 1 is inside this region
            # let's check for permissions

            upper_addr = min(region.addr + region.length, max_addr)
            if access_type == 'write':
                if not region.is_writable() and self.state.se.satisfiable(extra_constraints=(addr >= last_covered_addr + 1, addr <= upper_addr,)):
                    raise simuvex.s_errors.SimSegfaultError(last_covered_addr + 1, "Invalid " + access_type + " access: [" + str(hex(min_addr)) + ", " + str(hex(max_addr)) + "]")

            elif access_type == 'read':
                if not region.is_readable() and self.state.se.satisfiable(extra_constraints=(addr >= last_covered_addr + 1, addr <= upper_addr,)):
                    raise simuvex.s_errors.SimSegfaultError(last_covered_addr + 1, "Invalid " + access_type + " access: [" + str(hex(min_addr)) + ", " + str(hex(max_addr)) + "]")

            if max_addr > region.addr + region.length:
                last_covered_addr = region.addr + region.length
            else:
                last_covered_addr = max_addr

        # last region could not cover up to max_addr
        if last_covered_addr < max_addr:

            # we do not need to check with the solver since max_addr is already a valid solution for addr
            raise simuvex.s_errors.SimSegfaultError(last_covered_addr + 1, "Invalid " + access_type + " access: [" + str(hex(min_addr)) + ", " + str(hex(max_addr)) + "]")
                                     

    def full_stack(self):
        import traceback, sys
        exc = sys.exc_info()[0]
        stack = traceback.extract_stack()[:-1]  # last one would be full_stack()
        if not exc is None:     # i.e. if an exception is present
            del stack[-1]       # remove call of full_stack, the printed exception
                                # will contain the caught exception caller instead
        trc = 'Traceback (most recent call last):\n'
        stackstr = trc + ''.join(traceback.format_list(stack))
        if not exc is None:
             stackstr += '  ' + traceback.format_exc().lstrip(trc)
        return stackstr