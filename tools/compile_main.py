import py_compile,sys
try:
    py_compile.compile('backend/main.py', doraise=True)
    print('COMPILE_OK')
except Exception as e:
    print('COMPILE_FAIL')
    print(e)
    sys.exit(1)
