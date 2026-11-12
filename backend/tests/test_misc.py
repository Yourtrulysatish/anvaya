import asyncio
import pytest
from fastapi import HTTPException

from anvaya import decisions, ingest, security
from anvaya.engines import mirofish
from anvaya.intel import analytics, extract
from anvaya.config import settings


def test_password_hash_roundtrip():
    h = security.hash_password("correct horse battery")
    assert security.verify_password("correct horse battery", h) and not security.verify_password("wrong", h)
    assert "correct" not in h


def test_registration_rules():
    with pytest.raises(HTTPException):
        security.register("bad", "longenoughpassword")
    with pytest.raises(HTTPException):
        security.register("a@b.co", "short")
    security.register("a@b.co", "longenoughpassword")
    with pytest.raises(HTTPException):
        security.register("A@b.co", "longenoughpassword")      # duplicate, case-insensitive


def test_upload_validation():
    with pytest.raises(ingest.IngestError):
        ingest.validate_upload("evil.exe", b"MZ")
    with pytest.raises(ingest.IngestError):
        ingest.validate_upload("fake.pdf", b"not a pdf")
    with pytest.raises(ingest.IngestError):
        ingest.validate_upload("empty.txt", b"")
    settings.max_upload_mb = 1
    with pytest.raises(ingest.IngestError):
        ingest.validate_upload("big.txt", b"x" * (1024 * 1024 + 1))
    settings.max_upload_mb = 15
    assert ingest.validate_upload("ok.csv", b"a,b\n1,2") == "csv"
    assert ingest.safe_filename("../../etc/passwd") == "passwd"


def test_extract_formats():
    assert ingest.extract_text("json", b'[{"a":1},{"a":2}]')["table"]["columns"] == ["a"]
    import io, docx, openpyxl
    d = docx.Document(); d.add_paragraph("Hello docx world"); b = io.BytesIO(); d.save(b)
    assert "Hello docx" in ingest.extract_text("docx", b.getvalue())["text"]
    wb = openpyxl.Workbook(); wb.active.append(["x", "y"]); wb.active.append([1, 2]); b = io.BytesIO(); wb.save(b)
    assert ingest.extract_text("xlsx", b.getvalue())["table"]["rows"] == [["1", "2"]]


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "ftp://x.y/z"])
def test_ssrf_blocked(url):
    with pytest.raises(ingest.IngestError):
        asyncio.run(ingest.fetch_url(url))


def test_method_selection_avoids_needless_simulation():
    m = analytics.select_methods("What was average revenue by region and the trend over time?", has_dataset=True, has_docs=False)
    assert not m["simulation_recommended"] and m["note"]
    m2 = analytics.select_methods("How will customers react if a competitor cuts prices 20%?", False, False)
    assert m2["simulation_recommended"] and {"scenario", "monte_carlo"} <= {x["id"] for x in m2["methods"]}


def test_stats_functions():
    t = analytics.linear_trend([1, 2, 3, 4, 5, 6.1, 7, 8])
    assert t["significant"] and 0.9 < t["slope_per_step"] < 1.1
    p = analytics.beta_posterior(8, 10)
    assert p["ci95"][0] < p["mean"] < p["ci95"][1]
    d = analytics.describe_table({"columns": ["a", "b"], "rows": [[str(i), str(2 * i)] for i in range(10)]})
    assert d["correlations"][0]["r"] == pytest.approx(1.0)


def test_heuristic_extraction_is_labelled_and_sourced():
    doc = {"id": "d1", "name": "n.txt"}
    kb = extract.merge_and_build([extract.extract_heuristic("Acme Corp cut prices in 2024. Acme Corp rivals Zenith Mobile. Zenith Mobile grew 20% in 2024.", doc, 0)], "heuristic")
    assert kb["method"].startswith("heuristic") and kb["nodes"] and all(n["sources"] for n in kb["nodes"])
    assert all(f["source_ref"]["doc"] == "n.txt" for f in kb["facts"])


def test_priority_formula():
    hi = decisions.priority({"impact": 5, "feasibility": 5, "urgency": 5, "risk": 1})
    lo = decisions.priority({"impact": 1, "feasibility": 1, "urgency": 1, "risk": 5})
    assert hi == 100 and lo == 0


LINES = [
    '{"round":0,"event_type":"simulation_start","platform":"twitter","total_rounds":3,"agents_count":3}',
    '{"round":1,"event_type":"round_start","simulated_hour":8}',
    '{"round":1,"agent_id":7,"agent_name":"Ann","action_type":"CREATE_POST","action_args":{"content":"hello"},"result":"ok","success":true}',
    '{"round":1,"agent_id":9,"agent_name":"Bob","action_type":"FOLLOW","action_args":{"followee_id":7},"success":true}',
    '{"round":1,"agent_id":4,"agent_name":"Cy","action_type":"LIKE_POST","action_args":{"post_id":1},"success":true}',
    '{"round":1,"agent_id":4,"agent_name":"Cy","action_type":"DO_NOTHING","action_args":{}}', "garbage",
    '{"round":1,"event_type":"round_end","actions_count":3}', '{"event_type":"simulation_end","total_actions":3}']


def test_mirofish_adapter_preserves_provenance_and_never_invents_targets():
    p = mirofish.normalise(LINES, "mf", "twitter")
    assert p["skipped"] == {"ignored_action": 1, "bad_line": 1}
    ev = {e["type"]: e for e in p["events"]}
    assert ev["post"]["target_agent"] is None
    assert ev["agree"]["target_agent"] is None and ev["agree"]["result"]["target_unknown"] is True   # LIKE_POST has only post_id
    assert ev["relationship_change"]["target_agent"] == 7
    assert ev["post"]["provenance"]["engine"] == "mirofish" and ev["post"]["provenance"]["original"]["agent_id"] == 7
    agents, events = mirofish.to_dataset(p, "mf", "t")
    assert [a["mirofish_agent_id"] for a in agents] == [4, 7, 9]
    assert all(0 <= a < 3 for e in events for a in e["agents"])


def test_spec_from_llm_accepts_messy_model_shapes():
    from anvaya.agents.generator import spec_from_llm, sample
    spec = spec_from_llm({
        "title": "T", "topics": [{"label": "Issue", "pos_label": "yes", "neg_label": "no"}],
        "segments": [
            {"name": "A", "share": "60%", "traits": {"openness": 0.7, "bogus": 1, "conformity": {"mean": 0.4, "sd": 0.1}}, "sensitivities": {"price": "0.8"},
             "opinion": {"t1": [0.3]}, "activity": 0.4, "influence": {"mean": 0.2}, "goals": "save money", "age": "27", "first_names": ["Ann"], "last_names": "Lee"},
            {"name": "B", "share": 0.4, "traits": [], "opinion": "none"}, "junk"],
        "assumptions": "an assumption", "suggested_rounds": "15"})
    assert [s.name for s in spec.segments] == ["A", "B"] and spec.suggested_rounds == 15
    ags = sample(spec, 20, 1)
    assert len(ags) == 20 and all(-1 <= a.opinions["t1"] <= 1 for a in ags)
    import pytest
    with pytest.raises(ValueError):
        spec_from_llm([1, 2])
    with pytest.raises(ValueError):
        spec_from_llm({"topics": [], "segments": []})
