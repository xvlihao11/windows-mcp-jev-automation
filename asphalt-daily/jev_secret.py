"""Current-Windows-user DPAPI storage; no plaintext key in config or logs."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

PATH=Path(__file__).resolve().parent.parent/'.local-secrets/typesafe.dpapi'

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def transform(data,protect):
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    memory=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    source=Blob(len(data),memory)
    target=Blob()
    if protect:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fn(ctypes.byref(source),'Daily Jev',None,None,None,1,ctypes.byref(target))
    else:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    if not ok:
        raise RuntimeError('Windows凭据加解密失败')
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(ctypes.cast(target.data,ctypes.c_void_p))

def load_key():
    return transform(PATH.read_bytes(),False).decode('utf-8')

def save_key(key):
    if not key.strip():raise ValueError('Empty key')
    PATH.parent.mkdir(parents=True,exist_ok=True)
    PATH.write_bytes(transform(key.strip().encode('utf-8'),True))
    if load_key()!=key.strip():raise RuntimeError('Credential roundtrip failed')

if __name__=='__main__':
    if sys.argv[1:] == ['save']:
        save_key(sys.stdin.readline())
        print('OFFICIAL_KEY_ENCRYPTED_AND_VERIFIED')
    elif sys.argv[1:] == ['check']:
        if not load_key():raise RuntimeError('Missing key')
        print('OFFICIAL_KEY_READABLE')
