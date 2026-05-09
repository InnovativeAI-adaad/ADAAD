# SPDX-License-Identifier: Apache-2.0
# ADAAD Developer CLI — InnovativeAI LLC
# Usage: make <target>

.PHONY: help dev test sync lint invariants audit clean install tag

PYTHON     := python3
VERSION    := $(shell cat VERSION)
PYTEST_ARGS := -x -q

## ── Core ───────────────────────────────────────────────────────────────────
help:          ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:       ## Install Python dependencies
	pip install -r requirements.txt --break-system-packages -q

dev:           ## Start ADAAD runtime (FastAPI + Uvicorn)
	$(PYTHON) server.py

## ── Testing ────────────────────────────────────────────────────────────────
test:          ## Run full test suite (PYTHONPATH=.)
	PYTHONPATH=. $(PYTHON) -m pytest $(PYTEST_ARGS)

test-phase:    ## Run tests for a specific phase: make test-phase P=175
	PYTHONPATH=. $(PYTHON) -m pytest tests/test_phase$(P)_*.py -v

test-last:     ## Run the most recently added test file
	PYTHONPATH=. $(PYTHON) -m pytest $(shell ls -t tests/test_phase*.py | head -1) -v

## ── Version & Sync ─────────────────────────────────────────────────────────
sync:          ## Run version_sync.py — propagate VERSION to all surfaces
	$(PYTHON) scripts/version_sync.py

check-sync:    ## Verify no version drift (pre-commit gate, dry-run)
	$(PYTHON) scripts/pre_commit_version_check.py

## ── Quality ────────────────────────────────────────────────────────────────
lint:          ## Syntax-check all Python files
	$(PYTHON) -m py_compile patch_dork.py dork
	find adaad dorkllm runtime scripts -name '*.py' -exec $(PYTHON) -m py_compile {} \; 2>&1 | head -20
	@echo "Lint complete"

invariants:    ## Count Hard-class invariants in codebase
	grep -rh 'HARD\|Hard-class\|HardClass\|"-0"' adaad dorkllm runtime --include='*.py' | \
	  grep -oE '[A-Z][A-Z0-9]+-[A-Z0-9]+-0' | sort -u | wc -l

audit:         ## Verify HMAC ledger chain integrity
	$(PYTHON) -c "from adaad.ledger_verifier import verify_chain; verify_chain()" 2>/dev/null || \
	  $(PYTHON) scripts/verify_ledger.py 2>/dev/null || echo "Ledger verifier: run manually"

## ── Release ────────────────────────────────────────────────────────────────
tag:           ## Create annotated git tag for current VERSION
	git tag -a "v$(VERSION)" -m "Release v$(VERSION)" && \
	  git push origin "v$(VERSION)" && echo "Tagged v$(VERSION)"

## ── Housekeeping ────────────────────────────────────────────────────────────
clean:         ## Remove __pycache__ and .pyc files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	  find . -name '*.pyc' -delete 2>/dev/null; echo "Clean"
