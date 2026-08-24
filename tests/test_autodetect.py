"""Feature 1 tests: column auto-detection from header + sample rows."""

from __future__ import annotations

from je_agent.autodetect import detect_columns


def test_sap_codes_detected():
    csv_text = ("BELNR,BUDAT,BLDAT,CPUDT,HKONT,SGTXT,UNAME,BLART,WAERS,DMBTR\n"
                "DOC1,2024-01-02,2024-01-02,2024-01-02,1000,desc,JD,SA,USD,100.00\n"
                "DOC2,2024-01-03,2024-01-03,2024-01-03,2000,desc2,JD,SA,USD,200.00\n")
    d = detect_columns(csv_text)
    assert d.system == "sap"
    assert d.amount_column == "DMBTR"
    assert d.currency_column == "WAERS"
    assert d.column_map["posting_date"] == "BUDAT"
    assert d.column_map["account"] == "HKONT"
    assert d.column_map["username"] == "UNAME"
    assert d.column_map["description"] == "SGTXT"
    assert d.column_map["source_doc"] == "BELNR"
    assert d.column_map["entry_ref"] == "BELNR"
    assert d.confidence >= 0.8


def test_english_headers_detected():
    csv_text = ("Account Number,Posting Date,Amount,Currency,Description,User,Document No\n"
                "1000,2024-01-01,50.00,USD,Sale,JDOE,DOC3\n")
    d = detect_columns(csv_text)
    assert d.system == "generic"
    assert d.amount_column == "Amount"
    assert d.column_map["account"] == "Account Number"
    assert d.column_map["posting_date"] == "Posting Date"
    assert d.column_map["username"] == "User"
    assert d.column_map["source_doc"] == "Document No"


def test_fuzzy_match_near_miss():
    csv_text = ("amt_in_local,post_dt,gl,description,vendor_ref\n"
                "10.00,2024-05-01,4000,inv,REF1\n")
    d = detect_columns(csv_text)
    # 'amt_in_local' contains 'amt', 'post_dt' should not hit posting_date but gl->account
    assert d.column_map.get("account") == "gl"
    assert d.amount_column == "amt_in_local"


def test_empty_file_notes():
    d = detect_columns("")
    assert d.confidence == 0.0
    assert any("empty" in n for n in d.notes)


def test_no_amount_flagged():
    csv_text = ("id,whatever\n1,x\n")
    d = detect_columns(csv_text)
    assert any("no amount" in n for n in d.notes)
