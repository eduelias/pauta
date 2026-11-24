from pauta.ratelimit import DEFAULT_LIMITS, RateLimiter


def test_allows_up_to_the_limit_then_says_how_long_to_wait():
    rl = RateLimiter({"login": (3, 60)})
    assert [rl.hit("login", "ip", now=100 + i) for i in range(3)] == [0, 0, 0]
    assert rl.hit("login", "ip", now=110) == 51  # the first hit (t=100) leaves at t=160
    assert rl.hit("login", "other-ip", now=110) == 0  # per address
    assert rl.hit("login", "ip", now=160.5) == 0  # window slid


def test_blocked_requests_dont_extend_the_wait():
    rl = RateLimiter({"b": (1, 10)})
    rl.hit("b", "k", now=0)
    for t in range(1, 10):
        assert rl.hit("b", "k", now=t) > 0
    assert rl.hit("b", "k", now=10) == 0


def test_unknown_bucket_is_unlimited_and_reset_clears():
    rl = RateLimiter({"b": (1, 10)})
    assert all(rl.hit("nope", "k") == 0 for _ in range(100))
    rl.hit("b", "k", now=0)
    rl.reset()
    assert rl.hit("b", "k", now=1) == 0


def test_forgets_idle_addresses_under_a_flood():
    rl = RateLimiter({"b": (5, 10)})
    for i in range(10001):
        rl.hit("b", f"ip{i}", now=0)
    rl.hit("b", "late", now=100)
    assert len(rl._hits) == 1


def test_defaults_cover_every_account_endpoint():
    assert set(DEFAULT_LIMITS) == {"invite", "register", "login"}
    assert RateLimiter().limits == DEFAULT_LIMITS
