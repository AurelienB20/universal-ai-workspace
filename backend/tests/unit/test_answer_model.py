from uaw.generation.answerer import Answer


def test_answers_cached_before_traces_existed_still_load() -> None:
    stored = {
        "repository": "octo/demo",
        "commit_sha": "a" * 40,
        "answer": "Done [S1].",
        "insufficient_context": False,
        "citations": [],
        "model": "claude-opus-5-5",
    }

    assert Answer.model_validate(stored).trace is None
