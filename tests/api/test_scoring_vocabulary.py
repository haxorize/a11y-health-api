from httpx import AsyncClient

# Expected values come from DOMAIN.md ("Scoring & Metrics"), not from the module
# under test: ordering worst -> best, weights per health, total Impact mapping.
EXPECTED_VOCABULARY = {
    "page_health_ordering": ["critical", "serious", "fair", "good"],
    "page_health_weights": {"critical": 0.0, "serious": 0.4, "fair": 0.8, "good": 1.0},
    "impact_to_page_health": {
        "critical": "critical",
        "serious": "serious",
        "moderate": "fair",
        "minor": "good",
    },
}


async def test_get_scoring_vocabulary(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scoring-vocabulary")
    assert response.status_code == 200
    assert response.json() == EXPECTED_VOCABULARY
