# Modified for asynckb:
# independent distribution and KingbaseES compatibility.
.PHONY: compile debug test quicktest clean all


PYTHON ?= python3
ROOT = $(dir $(realpath $(firstword $(MAKEFILE_LIST))))


all: compile


clean:
	rm -fr dist/ doc/_build/
	rm -fr asynckb/pgproto/*.c asynckb/pgproto/*.html
	rm -fr asynckb/pgproto/codecs/*.html
	rm -fr asynckb/pgproto/*.so
	rm -fr asynckb/protocol/*.c asynckb/protocol/*.html
	rm -fr asynckb/protocol/*.so build *.egg-info
	rm -fr asynckb/protocol/codecs/*.html
	find . -name '__pycache__' | xargs rm -rf


compile:
	env ASYNCKB_BUILD_CYTHON_ALWAYS=1 $(PYTHON) -m pip install -e .


debug:
	env ASYNCKB_DEBUG=1 $(PYTHON) -m pip install -e .

test:
	PYTHONASYNCIODEBUG=1 $(PYTHON) -m pytest tests/kes


testinstalled:
	cd "$${HOME}" && $(PYTHON) $(ROOT)/tests/__init__.py -q


quicktest:
	$(PYTHON) -m pytest tests/kes/unit -q


htmldocs:
	$(PYTHON) -m pip install -e .[docs]
	$(MAKE) -C docs html
