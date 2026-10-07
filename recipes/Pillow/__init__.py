"""Retain upstream cross-compilation behavior with Pillow 12's setup layout."""

from pythonforandroid.recipes.Pillow import PillowRecipe as _BuiltinPillowRecipe


class PillowRecipe(_BuiltinPillowRecipe):
    version = "12.3.0"
    patches = ["setup.py.patch"]


recipe = PillowRecipe()
