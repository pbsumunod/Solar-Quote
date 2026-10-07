"""Build fontTools from source with its optional host accelerators disabled.

pip's fallback host wheel can contain x86_64 extensions even when the setup
environment disables Cython. A source recipe guarantees a portable package.
"""

from pythonforandroid.recipe import PythonRecipe


class FontToolsRecipe(PythonRecipe):
    version = "4.65.0"
    url = "https://files.pythonhosted.org/packages/source/f/fonttools/fonttools-{version}.tar.gz"
    depends = ["setuptools"]
    site_packages_name = "fontTools"

    def get_recipe_env(self, arch=None, **kwargs):
        env = super().get_recipe_env(arch, **kwargs)
        env["FONTTOOLS_WITH_CYTHON"] = "0"
        return env


recipe = FontToolsRecipe()
