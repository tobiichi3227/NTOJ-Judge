import cffi
import json
from typing import Dict

FFI = None
FFILIB = None

def init():
    global FFI, FFILIB

    FFI = cffi.FFI()

    # Init initialize the sandbox environment
    FFI.cdef('''
    int Init(char* i);
    ''')

    # Exec runs command inside container runner
    # Remember to free the return char pointer value
    FFI.cdef('''
    char* Exec(char* e);
    ''')

    # FileList get the list of files in the file store.
    # Remember to free the 2-d char array `ids` and `names`
    FFI.cdef('''
    size_t FileList(char*** ids, char*** names);
    ''')

    # FileAdd adds file to the file store
    # Remember to free the return char pointer value
    FFI.cdef('''
    char* FileAdd(char* content, int contentLen, char* name);
    ''')

    # FileGet gets file from file store by id.
    # If the return value is a positive number or zero, the value represents the length of the file.
    # Otherwise, if the return value is negative, the following error occurred:
    #
    # - `-1`: The file does not exist.
    # - `-2`: go-judge internal error.
    #
    # Remember to free `out`.

    FFI.cdef('''
    int FileGet(char* e, char** out);
    ''')

    # FileDelete deletes file from file store by id, returns 0 if failed.
    FFI.cdef('''
    int FileDelete(char* e);
    ''')

    FFI.cdef('''
    int DiffStrictly(char* e1, char* e2);
    ''')

    FFI.cdef('''
    int DiffIgnoreTrailiingSpace(char* e1, char* e2);
    ''')

    FFILIB = FFI.dlopen('./executor_server_lib_without_seccomp.so')

def init_container(conf: Dict):
    assert FFILIB is not None

    return FFILIB.Init(json.dumps(conf).encode('utf-8'))

def exec(cmd: Dict) -> Dict:
    assert FFILIB is not None
    res = FFILIB.Exec(json.dumps(cmd).encode('utf-8'))

    return json.loads(FFI.string(res).decode('utf-8'))

async def file_delete(fileid: str):
    assert FFILIB is not None

    FFILIB.FileDelete(fileid.encode('utf-8'))

def diff_strictly(ans: str, out: str):
    assert FFILIB is not None

    res = FFILIB.DiffStrictly(ans.encode('utf-8'), out.encode('utf-8'))
    return res == 0

def diff_ignore_space(ans: str, out: str):
    assert FFILIB is not None

    res = FFILIB.DiffIgnoreTrailiingSpace(ans.encode('utf-8'), out.encode('utf-8'))
    return res == 0
