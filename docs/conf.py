#!/usr/bin/env python3
# Modified for asynckb:
# independent distribution and KingbaseES compatibility.

import os
import sys

sys.path.insert(0, os.path.abspath('..'))

version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'asynckb', '_version.py')

with open(version_file, 'r') as f:
    for line in f:
        if line.startswith('__version__: typing.Final ='):
            _, _, version = line.partition('=')
            version = version.strip(" \n'\"")
            break
    else:
        raise RuntimeError(
            'unable to read the version from asynckb/_version.py')

# -- General configuration ------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.doctest',
    'sphinx.ext.viewcode',
    'sphinx.ext.githubpages',
    'sphinx.ext.intersphinx',
]

add_module_names = False

templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'
project = 'asynckb'
copyright = '2016-present, the asyncpg authors and contributors'
author = '<See AUTHORS file>'
release = version
language = "en"
exclude_patterns = ['_build']
pygments_style = 'sphinx'
todo_include_todos = False
suppress_warnings = ['image.nonlocal_uri']

# -- Options for HTML output ----------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_title = 'asynckb Documentation'
html_short_title = 'asynckb'
html_static_path = ['_static']
html_sidebars = {
    '**': [
        'about.html',
        'navigation.html',
    ]
}
html_show_sourcelink = False
html_show_sphinx = False
html_show_copyright = True
htmlhelp_basename = 'asynckbdoc'


# -- Options for LaTeX output ---------------------------------------------

latex_elements = {}

latex_documents = [
    (master_doc, 'asynckb.tex', 'asynckb Documentation',
     author, 'manual'),
]


# -- Options for manual page output ---------------------------------------

man_pages = [
    (master_doc, 'asynckb', 'asynckb Documentation',
     [author], 1)
]


# -- Options for Texinfo output -------------------------------------------

texinfo_documents = [
    (master_doc, 'asynckb', 'asynckb Documentation',
     author, 'asynckb',
     'asynckb is an asyncio driver for KingbaseES compatibility modes',
     'Miscellaneous'),
]

# -- Options for intersphinx ----------------------------------------------

intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
