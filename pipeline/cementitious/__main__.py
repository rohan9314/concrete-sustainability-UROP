"""Allow ``python -m pipeline.cementitious`` as an alias for the main CLI."""

from pipeline.run_cementitious_materials import main

if __name__ == "__main__":
    raise SystemExit(main())
