"""Load optional reference WCRT files bundled with a test case."""

from __future__ import annotations

import csv
from pathlib import Path


def load_reference_wcrts(case_directory: str | Path) -> dict[int, float]:
    csv_path = Path(case_directory) / "WCRTs.csv"
    if not csv_path.exists():
        return {}

    results: dict[int, float] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            raw_value = str(row["WCRT"]).replace(",", ".")
            results[int(row["ID"])] = float(raw_value)
    return results

