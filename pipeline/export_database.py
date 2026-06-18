"""Stage 6: export consolidated technology records to a static database file."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pipeline.config import get_tech_database_path, resolve_data_path
from pipeline.schema import TechnologyDatabase, TechnologyRecord, finalize_record

logger = logging.getLogger(__name__)


def export_database(
    records: list[TechnologyRecord],
    output_path: str | Path | None = None,
    *,
    as_jsonl: bool = False,
) -> Path:
    """Write technology records to a static JSON or JSONL database file."""
    path = Path(output_path) if output_path else get_tech_database_path()
    if not path.is_absolute():
        path = resolve_data_path(str(path))
    else:
        path = path.resolve()

    finalized = [finalize_record(record) for record in records]
    path.parent.mkdir(parents=True, exist_ok=True)

    if as_jsonl or path.suffix == ".jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for record in finalized:
                handle.write(json.dumps(record.model_dump()) + "\n")
    else:
        payload = TechnologyDatabase(
            version="1.0",
            record_count=len(finalized),
            records=finalized,
        )
        path.write_text(
            json.dumps(payload.model_dump(), indent=2),
            encoding="utf-8",
        )

    logger.info("export_database: wrote %s records to %s", len(finalized), path)
    return path


def load_database(path: str | Path | None = None) -> TechnologyDatabase:
    """Load a prepared technology database from disk."""
    if path is None:
        db_path = get_tech_database_path()
    else:
        db_path = Path(path)
        if not db_path.is_absolute():
            db_path = resolve_data_path(str(db_path))
        else:
            db_path = db_path.resolve()

    if not db_path.is_file():
        logger.warning("load_database: file not found at %s", db_path)
        return TechnologyDatabase(version="1.0", record_count=0, records=[])

    if db_path.suffix == ".jsonl":
        records: list[TechnologyRecord] = []
        for line in db_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(TechnologyRecord.model_validate(json.loads(line)))
        return TechnologyDatabase(version="1.0", record_count=len(records), records=records)

    data = json.loads(db_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        records = [TechnologyRecord.model_validate(item) for item in data]
        return TechnologyDatabase(version="1.0", record_count=len(records), records=records)

    return TechnologyDatabase.model_validate(data)
