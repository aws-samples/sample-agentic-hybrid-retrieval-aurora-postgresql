.PHONY: validate test schemas checksums render-1024

validate:
	python scripts/validate_package.py

schemas:
	python scripts/export_json_schemas.py

checksums:
	python scripts/build_checksums.py

test: validate
	python -m unittest discover -s tests -v

render-1024:
	python scripts/render_dimension.py --dimension 1024 --output build/sql-1024
