from repost import find_reposts, token_similarity


def _job(title, company="Acme", url="https://b/1", location="NYC"):
    return {"title": title, "company": company, "url": url,
            "location": location}


def test_identical_title_new_url_flags_repost():
    closed = [_job("Applied AI Engineer", url="https://b/old")]
    new = [_job("Applied AI Engineer", url="https://b/new")]
    hits = find_reposts(new, closed)
    assert hits["https://b/new"][0] == "https://b/old"


def test_slightly_retitled_repost_flags():
    closed = [_job("Applied AI Engineer, Search", url="https://b/old")]
    new = [_job("Applied AI Engineer", url="https://b/new")]
    assert "https://b/new" in find_reposts(new, closed)


def test_different_company_not_flagged():
    closed = [_job("Applied AI Engineer", company="Other",
                   url="https://b/old")]
    new = [_job("Applied AI Engineer", url="https://b/new")]
    assert find_reposts(new, closed) == {}


def test_unrelated_title_not_flagged():
    closed = [_job("Staff Accountant", url="https://b/old")]
    new = [_job("Applied AI Engineer", url="https://b/new")]
    assert find_reposts(new, closed) == {}


def test_token_similarity_location_bonus():
    a = _job("Data Scientist", location="Boston")
    b = _job("Data Scientist, Platform", location="Boston")
    c = _job("Data Scientist, Platform", location="Remote")
    assert token_similarity(a, b) > token_similarity(a, c)


def test_best_match_wins():
    closed = [
        _job("Applied AI Engineer", url="https://b/old1"),
        _job("Applied AI Engineer, Recommendations", url="https://b/old2"),
    ]
    new = [_job("Applied AI Engineer", url="https://b/new")]
    assert find_reposts(new, closed)["https://b/new"][0] == "https://b/old1"
