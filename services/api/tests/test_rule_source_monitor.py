from scripts.check_rule_sources import _normalize_html


def test_nj_tax_fingerprint_ignores_dynamic_state_template_chrome() -> None:
    body = """
      <h3>Motor Vehicle Casual Sales Frequently Asked Questions</h3>
      <p>What is the Sales Tax rate?</p>
      <p>The rate is 6.625% on the purchase price.</p>
      <div>Last Updated: 09/09/25</div>
    """
    first = f"<html><header>Governor One</header>{body}<footer>Alert A</footer></html>"
    second = f"<html><header>Governor Two</header>{body}<footer>Alert B</footer></html>"

    first_text, first_basis = _normalize_html(
        "nj-casual-sales-tax",
        first.encode(),
    )
    second_text, second_basis = _normalize_html(
        "nj-casual-sales-tax",
        second.encode(),
    )

    assert first_text == second_text
    assert b"6.625%" in first_text
    assert b"Governor" not in first_text
    assert b"Alert" not in first_text
    assert first_basis == second_basis == "normalized_visible_text_window"
