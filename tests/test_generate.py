import json

import pytest

from lebenflo.generate.__main__ import generate


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("gen")
    truths = generate(count=10, seed=42, packets_dir=root / "packets", truth_dir=root / "truth")
    return root, truths


def test_ten_packets_three_flawed(generated):
    _, truths = generated
    assert len(truths) == 10
    flaws = sorted(t["flaw"] for t in truths if t["flaw"])
    assert flaws == ["income_gap", "missing_document", "name_mismatch"]


def test_generation_is_deterministic(generated, tmp_path):
    _, truths = generated
    again = generate(count=10, seed=42, packets_dir=tmp_path / "p", truth_dir=tmp_path / "t")
    assert again == truths


def test_ssns_are_in_never_issued_range(generated):
    _, truths = generated
    for t in truths:
        assert 900 <= int(t["applicant"]["ssn"][:3]) <= 999


def test_every_pdf_has_watermark(generated):
    root, _ = generated
    pdfs = list((root / "packets").rglob("*.pdf"))
    assert len(pdfs) == 39  # 10 packets x 4 docs, minus the missing one
    for pdf in pdfs:
        assert b"SYNTHETIC TEST DATA" in pdf.read_bytes(), pdf


def test_ground_truth_matches_files_on_disk(generated):
    root, truths = generated
    for t in truths:
        on_disk = {p.stem for p in (root / "packets" / t["packet_id"]).glob("*.pdf")}
        assert on_disk == set(t["documents"])
        assert set(t["missing_documents"]).isdisjoint(on_disk)


def test_flaws_are_really_present(generated):
    _, truths = generated
    by_flaw = {t["flaw"]: t for t in truths}
    named = by_flaw["name_mismatch"]["documents"]
    assert named["w2"]["fields"]["employee_name"] != named["pay_stub"]["fields"]["employee_name"]

    gap = by_flaw["income_gap"]
    annual = gap["applicant"]["annual_salary"]
    assert abs(annual - gap["documents"]["w2"]["fields"]["wages"]) / annual > 0.10

    assert "bank_statement" not in by_flaw["missing_document"]["documents"]


def test_expected_outcomes(generated):
    _, truths = generated
    for t in truths:
        if t["flaw"]:
            assert t["expected_outcome"] == "ESCALATE_TO_HUMAN" and len(t["expected_reasons"]) == 1
        else:
            assert (
                t["expected_outcome"] == "APPROVE_FOR_UNDERWRITING" and t["expected_reasons"] == []
            )


def test_application_json_has_no_ssn(generated):
    root, truths = generated
    for t in truths:
        text = (root / "packets" / t["packet_id"] / "application.json").read_text()
        assert t["applicant"]["ssn"] not in text
        json.loads(text)
