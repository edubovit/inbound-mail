from tools.check_docs import check_docs


def test_documentation_links_and_screenshots():
    assert check_docs() == []


def test_missing_links_are_reported(tmp_path):
    (tmp_path / "README.md").write_text("[Missing](docs/missing.md)")
    (tmp_path / "CONTRIBUTING.md").write_text("# Development\n[Missing section](#missing)")
    errors = check_docs(tmp_path)
    assert len(errors) == 2
    assert any("missing/outside target" in error for error in errors)
    assert any("missing heading" in error for error in errors)
