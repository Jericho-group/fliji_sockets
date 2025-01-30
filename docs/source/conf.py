import inspect
import os
import sys

sys.path.insert(0, os.path.abspath("../../"))

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "websockets"
copyright = "2024, Leo"
author = "Leo"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.napoleon",
    "sphinxcontrib.autodoc_pydantic"
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "alabaster"
html_static_path = ["_static"]

# -- autodoc_pydantic configuration
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False


# -- skip members without docstrings
def skip_undocumented_members(app, what, name, obj, skip, options):
    if not skip:
        # Include if the object is a class
        if inspect.isclass(obj):
            return False

        # Determine if the object has a docstring
        has_docstring = obj.__doc__ is not None and obj.__doc__.strip() != ""
        # Skip if there is no docstring
        return not has_docstring
    return skip


def setup(app):
    app.connect("autodoc-skip-member", skip_undocumented_members)
