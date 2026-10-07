from termflow.core.request_planner import estimate_tokens, plan_search


def test_planner_uses_single_chunk_when_source_fits():
    plan = plan_search("prompt", "vocab", "source" * 20, context_window=1000, output_reserve=100)
    assert plan.chunk_count == 1


def test_planner_uses_only_required_chunks_and_accounts_for_repeated_fixed_input():
    plan = plan_search("p" * 200, "v" * 200, "s" * 4000, context_window=1300, output_reserve=100)
    assert plan.chunk_count > 1
    assert "repeated" in plan.warning
    assert plan.estimated_total_tokens >= plan.estimated_input_tokens


def test_token_estimate_is_conservative_for_mixed_script_text():
    assert estimate_tokens("中文ไทยEnglish") == 6
