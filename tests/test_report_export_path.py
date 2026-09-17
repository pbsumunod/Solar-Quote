from screens.report_screen import available_export_path


def test_export_path_preserves_existing_proposals(tmp_path):
    first = available_export_path(str(tmp_path), "solar_proposal.pdf")
    assert first == str(tmp_path / "solar_proposal.pdf")
    (tmp_path / "solar_proposal.pdf").write_bytes(b"old proposal")
    second = available_export_path(str(tmp_path), "solar_proposal.pdf")
    assert second == str(tmp_path / "solar_proposal_2.pdf")
    (tmp_path / "solar_proposal_2.pdf").write_bytes(b"another proposal")
    assert available_export_path(str(tmp_path), "solar_proposal.pdf") == str(tmp_path / "solar_proposal_3.pdf")
    assert (tmp_path / "solar_proposal.pdf").read_bytes() == b"old proposal"
