ENGINE_DIR := engine
DFROTZ    := $(ENGINE_DIR)/dfrotz

.PHONY: all bootstrap engine venv run clean test test-only

all: bootstrap engine venv

bootstrap: $(ENGINE_DIR)/.git
$(ENGINE_DIR)/.git:
	@echo "==> fetching frotz (DavidGriffith/frotz) into engine/ (one time)"
	git clone --depth=1 https://gitlab.com/DavidGriffith/frotz.git $(ENGINE_DIR)
	@echo "==> bootstrap complete"

engine: $(DFROTZ)
$(DFROTZ):
	@echo "==> building dfrotz (dumb frontend)"
	$(MAKE) -C $(ENGINE_DIR) dumb
	@echo "==> dfrotz ready at $(DFROTZ)"

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv $(DFROTZ)
	.venv/bin/python frotz.py

test: venv $(DFROTZ)
	.venv/bin/python -m tests.qa

test-only: venv $(DFROTZ)
	.venv/bin/python -m tests.qa $(PAT)

perf: venv $(DFROTZ)
	.venv/bin/python -m tests.perf

clean:
	rm -rf .venv
	-$(MAKE) -C $(ENGINE_DIR) clean
