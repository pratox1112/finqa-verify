"""Company resolver: share classes, former names, brands, ambiguity. No network."""

import pytest

from finqa.config import BASE_CONFIG, load_config
from finqa.tools.resolver import Company, CompanyResolver, normalize

# Alphabet and Meta are not FinanceBench companies, so they are added here to test share
# classes and a renamed company. CIKs and names as on SEC EDGAR.
ALPHABET = Company(
    name="Alphabet",
    cik="0001652044",
    ticker="GOOGL",
    tickers=("GOOGL", "GOOG"),
    sec_name="Alphabet Inc.",
    former_names=(),
    aliases=("Alphabet", "Google"),
    fiscal_year_end="1231",
)
META = Company(
    name="Meta",
    cik="0001326801",
    ticker="META",
    tickers=("META", "FB"),
    sec_name="Meta Platforms, Inc.",
    former_names=("FACEBOOK INC",),
    aliases=("Meta", "Meta Platforms", "Instagram", "WhatsApp"),
    fiscal_year_end="1231",
)


@pytest.fixture(scope="module")
def resolver() -> CompanyResolver:
    """The real company table (data/companies.csv) plus Alphabet and Meta."""
    table = CompanyResolver.from_csv()
    return CompanyResolver([*table.companies, ALPHABET, META], table.threshold, table.margin)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("The Coca-Cola Company", "coca cola"),
        ("Alphabet Inc. Class C", "alphabet"),
        ("JOHNSON & JOHNSON", "johnson and johnson"),
        ("Block, Inc.", "block"),
    ],
)
def test_normalize(name: str, expected: str) -> None:
    assert normalize(name) == expected


@pytest.mark.parametrize("name", ["GOOGL", "GOOG", "Alphabet Inc. Class A", "Alphabet Class C"])
def test_alphabet_share_classes_resolve_to_one_cik(resolver: CompanyResolver, name: str) -> None:
    assert resolver.resolve(name).company == ALPHABET


@pytest.mark.parametrize("name", ["Facebook", "Facebook, Inc.", "FB", "Meta Platforms"])
def test_meta_under_its_former_name(resolver: CompanyResolver, name: str) -> None:
    assert resolver.resolve(name).company == META


def test_block_under_its_former_name(resolver: CompanyResolver) -> None:
    result = resolver.resolve("Square")
    assert result.company is not None and result.company.cik == "0001512673"
    assert result.candidates[0].matched == "Square, Inc."


@pytest.mark.parametrize(
    "name, company", [("Coke", "Coca-Cola"), ("Cash App", "Block"), ("Instagram", "Meta")]
)
def test_brand_name(resolver: CompanyResolver, name: str, company: str) -> None:
    result = resolver.resolve(name)
    assert result.company is not None and result.company.name == company


def test_ambiguous_name_returns_candidates_not_a_guess(resolver: CompanyResolver) -> None:
    result = resolver.resolve("American")
    assert result.company is None and not result.resolved
    top_two = {c.company.name for c in result.candidates[:2]}
    assert top_two == {"American Express", "American Water Works"}


@pytest.mark.parametrize("name", ["Apple", ""])
def test_unknown_name_is_not_resolved(resolver: CompanyResolver, name: str) -> None:
    assert resolver.resolve(name).company is None


def test_small_typo_still_resolves(resolver: CompanyResolver) -> None:
    result = resolver.resolve("Wallmart")
    assert result.company is not None and result.company.name == "Walmart"


def test_ticker_is_case_insensitive(resolver: CompanyResolver) -> None:
    result = resolver.resolve(" jpm ")
    assert result.company is not None and result.company.name == "JPMorgan"


def test_every_financebench_name_resolves_to_itself() -> None:
    resolver = CompanyResolver.from_csv()
    for company in resolver.companies:
        assert resolver.resolve(company.name).company == company


def test_threshold_and_margin_come_from_config() -> None:
    r = load_config(BASE_CONFIG).retrieval
    resolver = CompanyResolver.from_csv()
    assert (resolver.threshold, resolver.margin) == (r.resolver_threshold, r.resolver_margin)


def test_margin_turns_a_near_tie_into_candidates() -> None:
    near_twins = [
        Company("Acme Foods", "1", "AF", ("AF",), "ACME FOODS", (), (), "1231"),
        Company("Acme Goods", "2", "AG", ("AG",), "ACME GOODS", (), (), "1231"),
    ]
    assert CompanyResolver(near_twins, threshold=80, margin=0).resolve("Acme Foods").resolved
    assert not CompanyResolver(near_twins, threshold=80, margin=50).resolve("Acme Foods").resolved
