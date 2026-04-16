# Makefile: удобные шорткаты для пайплайна tms-dedup-v2.
# Все команды работают через uv, чтобы не зависеть от активации venv.

PY ?= uv run python
INPUT ?= data_samples/sample_tests.csv
SECTION_SEP ?= /

.PHONY: install sync dataset sections pairs packs merge reports all clean lint test sample

install sync:
	uv sync

dataset:
	$(PY) scripts/build_dataset.py --input $(INPUT) --section-sep "$(SECTION_SEP)"

sections:
	$(PY) scripts/infer_section_hypotheses.py --section-sep "$(SECTION_SEP)"

pairs:
	$(PY) scripts/generate_candidate_pairs.py --section-sep "$(SECTION_SEP)"

packs:
	$(PY) scripts/build_qwen_review_packs.py

merge:
	$(PY) scripts/merge_qwen_results.py

reports:
	$(PY) scripts/build_final_reports.py

# Полный прогон Python-части (без Qwen review).
all: dataset sections pairs packs reports

# Только данные, без отчётов — для отладки.
sample: dataset sections pairs packs

test:
	uv run pytest

clean:
	rm -rf data/
