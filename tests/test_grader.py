from searchapi_eval.evaluation.grader import exact_match, token_f1


def test_exact_match_normalizes_articles_punctuation_and_case():
    assert exact_match("The Serban Ghenea.", "serban ghenea")


def test_token_f1_partial_overlap():
    assert round(token_f1("Taylor Swift", "Taylor Alison Swift"), 3) == 0.8

