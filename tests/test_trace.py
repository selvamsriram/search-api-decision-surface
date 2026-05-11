from searchapi_eval.agent.trace import extract_final_answer


def test_extract_final_answer_requires_prefix_for_answered():
    answer, answered = extract_final_answer("FINAL ANSWER: Serban Ghenea")
    assert answer == "Serban Ghenea"
    assert answered is True


def test_extract_final_answer_detects_abstention():
    answer, answered = extract_final_answer("FINAL ANSWER: I cannot determine the answer from available sources.")
    assert answer
    assert answered is False

