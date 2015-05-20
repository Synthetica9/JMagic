__author__ = 'Synthetica'

from IPython.core.magic import (Magics, magics_class, line_magic)
import ctypes
import numpy as np
import itertools
import os
from inspect import getsourcefile, currentframe

@magics_class
class JMagics(Magics):
    def __init__(self, shell):
        Magics.__init__(self, shell)
        self.J_sessions = dict()

    @line_magic
    def J(self, line):
        caller_locs = return_caller_locals(6)
        # print caller_locs
        session = id(caller_locs)
        # print session
        if session not in self.J_sessions:
            self.create_session(session)
        self.update_internal_values(session)
        self.J_sessions[session].get_changed_var_names()
        return_value = self.J_sessions[session](line)
        self.update_external_values(session)
        return return_value

    def create_session(self, session):
        J_ses = JInstance()
        self.J_sessions[session] = J_ses

    def update_internal_values(self, session):
        vars = []
        for level in itertools.count(6):
            try:
                vars.append(return_caller_locals(level))
            except AttributeError as E:
                # top level reached
                break

        initial_dict = vars.pop().copy()
        while vars:
            initial_dict.update(vars.pop())

        for name, value in initial_dict.iteritems():
            try:
                self.J_sessions[session].set_var(name, value)
            except TypeError as E:
                continue  # unable to parse
            #
            # else:
            #     print name, ':', `value`

    def update_external_values(self, session):
        locs = return_caller_locals(7) #TODO: magic number, replace
        for name in self.J_sessions[session].get_changed_var_names():
            name = ''.join(str(i) for i in name)
            if name.endswith('_base_'):
                name = name[:-6]  # strip off _base_
                locs[name] = self.J_sessions[session](name)


def return_caller_locals(levels=1):
    frame = currentframe()
    try:
        for i in range(levels):
            frame = frame.f_back
    finally:
        vrs = frame.f_locals
        del frame
    return vrs

type_table = {1: ctypes.c_bool,
              2: ctypes.c_char,
              4: ctypes.c_int,
              8: ctypes.c_double
              }

_path = os.path.abspath(os.path.dirname(getsourcefile(lambda: None)))
if os.name == 'nt':
    try:
        std_lib = ctypes.oledll.LoadLibrary(os.path.join(_path, 'j64.dll'))
    except WindowsError:
        std_lib = ctypes.oledll.LoadLibrary(os.path.join(_path, 'j32.dll'))
elif os.name == 'posix':
    std_lib = ctypes.CDLL(os.path.join(_path, 'libj.so'))
else:
    raise OSError('Unsupported os {o}'.format(repr(os.name)))

class JInstance(object):
    def __init__(self):
        self.j_dll = std_lib
        self.start_address = self.j_dll.JInit()

    def __call__(self, command):
        temp_name = 'TMP__'
        type_name = 'TYPE__'
        kind_name = 'KIND__'
        error_name = 'ERROR__'

        command = str(command)
        #Delete all variables that are going to be used:
        self.delete_var(temp_name, type_name, kind_name)
        self.execute_command(command, temp_name, return_result=False)
        return_type = self.execute_command(
            "4!:0 < '{tmp}'".format(tmp=temp_name), type_name)

        # Return the result, or raise an error:
        if return_type == -2:
            raise Exception("Invalid. That's all we know, sorry. "
                            "It would probably be wise to contact your "
                            "friendly neighbourhood library developer about "
                            "this error, because this shouldn't ever happen")
        elif return_type == -1:
            error_text = ''.join(
                self.execute_command(
                    "(13 !: 12)''",
                    var_name=error_name
                )
            )
            raise Exception("Undefined, an error probably "
                            "occurred somewhere along the way.\n"
                            "The last error raised:\n:"
                            "{t}".format(t=error_text))


        if return_type == 0: # Only nouns allowed.
            # self.JGetM(temp_name, *data_pointers)
            # return JRepr(*data_pointers)
            return self.get_var(temp_name)
        else:
            raise TypeError(
                "Impossible to return type {0}, must be 0.\n"
                "(Piece of advice: are you trying to return a "
                "verb/adverb/conjuction? Don't.)".format(return_type)
            )



    def __del__(self):
        self.JFree()

    def delete_var(self, *names):
        if len(names) == 0:
            return
        elif len(names) == 1:
            query = "4!:55 <'{name}'".format(name=names[0])
        else:
            names = ["'{}'".format(name) for name in
                     names]  # Surround with quotes
            query = "4!:55 {names}".format(names='; '.join(names))

        self.execute_command(query)

    def execute_command(self, command, var_name=None, return_result=True):
        #print command
        if var_name is not None:
            self.set_var_raw(var_name, command)
            if return_result:
                return self.get_var(var_name)
        else:
            self.JDo(command)


        if var_name is not None:
            if return_result:
                return self.get_var(var_name)

    def set_var(self, name, value):
        self.execute_command('{n} =: {v}'.format(n=name, v=pyToJ(value)))

    def set_var_raw(self, name, value):
        self.execute_command('{n} =: {v}'.format(n=name, v=value))

    def get_var(self, var_name):
        pointers = [ctypes.pointer(ctypes.c_int()) for _ in range(4)]
        self.JGetM(var_name, *pointers)
        data = JRepr(*(p.contents.value for p in pointers))
        return data

    def get_changed_var_names(self):
        return self('>4!:5]1')

    def __getattr__(self, item):
        def wrapper(*args, **kwargs):
            return getattr(self.j_dll, item)(self.start_address, *args,
                                             **kwargs)

        wrapper.__name__ = item
        return wrapper

def JRepr(tpe, rnk, shp, pos, typelist=type_table):
    #tpe, rnk, shp, pos = (int(i.contents.value) for i in (tpe, rnk, shp, pos))
    shape = tuple(typelist[4].from_address(shp + i*ctypes.sizeof(typelist[4])).value
                  for i in range(rnk))
    datalen = np.product(shape) if shape else 1
    if tpe in typelist:
        ctype = typelist[tpe]
        ctypesize = ctypes.sizeof(ctype)

        array = np.fromiter(
            (ctype.from_address(pos + i*ctypesize).value
                for i in itertools.count()),
            dtype=ctype,
            count=datalen
        )

        return np.resize(array, shape)
    elif tpe == 32:
        pointers = [map(lambda x: x.value,
                        (ctypes.c_int.from_address(pos + i*16 + 0),
                         ctypes.c_int.from_address(pos + i*16 + 4),
                         ctypes.c_int.from_address(pos + i*16 + 8),
                         ctypes.c_int.from_address(pos + i*16 + 12))
                        )
                    for i in range(datalen)]
        return [JRepr(*i) for i in pointers]
    else:
        raise TypeError


def debug(command):
    return compile(command, '<string>', 'single')()

def pyToJ(item):
    if type(item) in (int, float, long):
        return str(item)
    elif type(item) in (list, tuple):
        return ','.join('(<{})'.format(pyToJ(i)) for i in item)
    elif type(item) == np.ndarray:
        shp = (' '.join(str(i) for i in item.shape) if item.shape else '0 $ 0')
        if item.dtype in (int, float, long):

            return '(({shape}) $ ({items}))'.format(
                shape=shp,
                items=' '.join(str(i) for i in item.flat)
            )
        if item.dtype == str:
            return '(({shape{) $ (\'{items\'))'.format(
                shape=shp,
                items=''.join(str(i).replace("'", "''") for i in item.flat)
            )
    raise TypeError()

if __name__ == '__main__':
    import IPython
    print 'Please call get_ipython().register_magics(JMagics)'
    IPython.embed()