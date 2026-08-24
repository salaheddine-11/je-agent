"""Shared pytest fixtures: minimal engagement configs + synthetic extracts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def base_config_dict(**overrides) -> dict:
    cfg = {
        "run_id": "TEST_2026Q2",
        "period_end": "2026-06-30",
        "materiality": {"overall": 250000, "performance": 175000, "currency": "USD"},
        "source": {
            "system": "generic",
            "amount_column": "AMOUNT",
            "currency_column": "CURRENCY",
            "column_map": {
                "posting_date": "POST_DATE",
                "account": "ACCOUNT",
                "username": "USER",
                "description": "DESCR",
                "source_doc": "DOC",
                "entry_ref": "ENTRY",
            },
        },
        "reviewer": {"name": "jdoe"},
    }
    cfg.update(overrides)
    return cfg


def write_config(path: Path, cfg: dict) -> Path:
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def config_dict():
    return base_config_dict()


@pytest.fixture
def config_file(tmp_path, config_dict):
    return write_config(tmp_path / "config.yaml", config_dict)


@pytest.fixture
def clean_extract(tmp_path) -> Path:
    """Small benign population: system entries + routine manual entries."""
    rows = [
        # header: ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE
        ("JE001", 1, "2026-04-05", "4000", "SAPUSER", "Customer invoice batch", "DOC100", 1500.00, "USD", "system"),
        ("JE001", 2, "2026-04-05", "1200", "SAPUSER", "Customer invoice batch", "DOC100", -1500.00, "USD", "system"),
        ("JE002", 1, "2026-05-12", "6000", "JDOE", "Office supplies purchase", "DOC101", -230.50, "USD", "manual"),
        ("JE002", 2, "2026-05-12", "1000", "JDOE", "Office supplies purchase", "DOC101", 230.50, "USD", "manual"),
        ("JE003", 1, "2026-06-20", "5000", "WF-BATCH", "Payroll posting run", "DOC102", 9200.00, "USD", "system"),
        ("JE003", 2, "2026-06-20", "2100", "WF-BATCH", "Payroll posting run", "DOC102", -9200.00, "USD", "system"),
        ("JE004", 1, "2026-03-18", "7000", "MARTIN_B", "Travel expense claim", "DOC103", -410.25, "USD", "manual"),
        ("JE004", 2, "2026-03-18", "1000", "MARTIN_B", "Travel expense claim", "DOC103", 410.25, "USD", "manual"),
        ("JE005", 1, "2026-07-12", "4000", "SAPUSER", "Post-close customer invoice", "DOC104", 2000.00, "USD", "system"),
        ("JE005", 2, "2026-07-12", "1200", "SAPUSER", "Post-close customer invoice", "DOC104", -2000.00, "USD", "system"),
    ]
    p = tmp_path / "extract.csv"
    lines = ["ENTRY,LINE,POST_DATE,ACCOUNT,USER,DESCR,DOC,AMOUNT,CURRENCY,ENTRY_TYPE"]
    lines += [",".join(str(x) for x in r) for r in rows]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
