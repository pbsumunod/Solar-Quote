"""Override of python-for-android's built-in python3 recipe, changing only
get_recipe_env() -- everything else (build_arch, create_python_bundle,
set_libs_flags, patches, etc.) is delegated to the real installed recipe via
super(), not reimplemented, since hand-copying a ~500-line recipe risks
silently diverging from whatever p4a version actually ships in CI.

Why this override exists: a release build failed with

    Modules/grpmodule.c:281:5: error: implicit declaration of function
    'setgrent' is invalid in C99 [-Werror,-Wimplicit-function-declaration]

CPython's own configure script forces -Werror=implicit-function-declaration
into the compile flags unconditionally, as a hardening check it runs on its
own -- this cascaded into every subsequent recipe/pip install failing too,
since there was no working Python left to install into. Setting CFLAGS at
the CI-workflow level doesn't reach this compile at all: the built-in
get_recipe_env() below unconditionally *overwrites* env['CFLAGS'] to
'-fPIC -DANDROID', discarding anything inherited from the calling shell.

The real fix is -D_DEFAULT_SOURCE, not a -Wno-error flag: setgrent/
getgrent/endgrent aren't declared under strict -std=c11 without the right
glibc/bionic feature-test macro exposed, which is what actually triggers
the implicit-declaration warning in the first place. Defining the macro
means there's no implicit declaration for -Werror to catch regardless of
flag order -- unlike a competing -Wno-error=... flag, which loses to
configure's own -Werror appended later in the same command (flag order
decides for GCC/Clang -W-family flags on the same warning, and configure's
own flag comes after anything from CFLAGS).
"""

from pythonforandroid.recipes.python3 import Python3Recipe as _BuiltinPython3Recipe


class Python3Recipe(_BuiltinPython3Recipe):
    def get_recipe_env(self, arch=None, with_flags_in_cc=True):
        env = super().get_recipe_env(arch, with_flags_in_cc)
        env['CFLAGS'] += ' -D_DEFAULT_SOURCE'
        return env


recipe = Python3Recipe()
