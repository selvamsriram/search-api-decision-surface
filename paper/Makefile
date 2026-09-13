PYTHON ?= python3

# Compile frozen, audited sources without private records or live services.
all: camera-ready

camera-ready:
	$(PYTHON) ../scripts/build_camera_ready.py

# Explicit research regeneration; requires author-local raw inputs.
figures:
	$(PYTHON) figures/make_figures.py

.PHONY: all camera-ready figures
