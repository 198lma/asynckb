.. Modified for asynckb:
   independent distribution and KingbaseES compatibility.

.. image:: https://github.com/198lma/asynckb/actions/workflows/tests.yml/badge.svg
   :target: https://github.com/198lma/asynckb/actions/workflows/tests.yml
   :alt: GitHub Actions status

asynckb
===========

**asynckb** is a standalone asynchronous driver based on asyncpg 0.31.0,
adapted for KingbaseES MySQL, Oracle, and SQL Server compatibility modes.
Its distribution and Python import names are both ``asynckb``.

**asynckb** requires Python 3.9 or later.  The recorded acceptance suite
targets KingbaseES V009R001C010 MySQL, Oracle, and SQL Server compatibility
modes.  PostgreSQL is not part of this fork's acceptance matrix.

Contents
--------

中文交付文档可在线阅读，也可以下载 Word 版本：

* :doc:`quickstart_zh`
* :doc:`user_manual_zh`
* :download:`asynckb 快速上手（Word） <asynckb快速上手.docx>`
* :download:`asynckb 用户手册（Word） <asynckb用户手册.docx>`

.. toctree::
   :maxdepth: 2

   installation
   quickstart_zh
   user_manual_zh
   usage
   api/index
   faq
