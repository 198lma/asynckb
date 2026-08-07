.PHONY: compile debug test quicktest clean all


PYTHON ?= python3
ROOT = $(dir $(realpath $(firstword $(MAKEFILE_LIST))))


all: compile


clean:
	rm -fr dist/ doc/_build/
	rm -fr asyncpg/pgproto/*.c asyncpg/pgproto/*.html
	rm -fr asyncpg/pgproto/codecs/*.html
	rm -fr asyncpg/pgproto/*.so
	rm -fr asyncpg/protocol/*.c asyncpg/protocol/*.html
	rm -fr asyncpg/protocol/*.so build *.egg-info
	rm -fr asyncpg/protocol/codecs/*.html
	find . -name '__pycache__' | xargs rm -rf


compile:
	env ASYNCPG_BUILD_CYTHON_ALWAYS=1 $(PYTHON) -m pip install -e .


debug:
	env ASYNCPG_DEBUG=1 $(PYTHON) -m pip install -e .

test:
	PYTHONASYNCIODEBUG=1 $(PYTHON) -m pytest tests/kes


testinstalled:
	cd "$${HOME}" && $(PYTHON) $(ROOT)/tests/__init__.py -q


quicktest:
	$(PYTHON) -m pytest tests/kes/unit -q


htmldocs:
	$(PYTHON) -m pip install -e .[docs]
	$(MAKE) -C docs html
