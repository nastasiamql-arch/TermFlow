from termflow.core.result_cache import ResultCache, cache_key


def identity(**changes):
    values = {
        "workflow": "search-step-a", "provider": "openai", "base_url": "https://example.test/v1",
        "model": "model-a", "prompt": "prompt", "source": "source", "vocab": "vocab", "user_input": "input",
        "validator_version": "step-a-v1",
    }
    values.update(changes)
    return cache_key(**values)


def test_exact_identity_cache_reuses_only_matching_key_and_valid_values(tmp_path):
    cache = ResultCache(tmp_path / "cache.json")
    key = identity()
    assert cache.put(key, "valid", lambda value: value == "valid")
    assert cache.get(key, lambda value: value == "valid") == "valid"
    for field, value in (("prompt", "other"), ("source", "other"), ("vocab", "other"),
                         ("model", "model-b"), ("provider", "compatible"),
                         ("base_url", "https://other.test"), ("user_input", "other")):
        assert cache.get(identity(**{field: value}), lambda _: True) is None
    def reject(_value):
        raise ValueError("does not validate")

    assert cache.get(key, reject) is None


def test_corrupt_cache_is_ignored(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json", encoding="utf-8")
    assert ResultCache(path).get(identity(), lambda _: True) is None
