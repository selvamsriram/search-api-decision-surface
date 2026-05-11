from __future__ import annotations

import re
import string
from collections import Counter
from typing import Iterable

NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}


def normalize_answer(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = text.translate(str.maketrans("", "", string.punctuation))
    tokens = [NUMBER_WORDS.get(token, token) for token in text.split()]
    return " ".join(tokens)


def exact_match(predicted: str, gold: str) -> bool:
    return normalize_answer(predicted) == normalize_answer(gold)


def token_f1(predicted: str, gold: str) -> float:
    pred_tokens = normalize_answer(predicted).split()
    gold_tokens = normalize_answer(gold).split()
    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0
    overlap = Counter(pred_tokens) & Counter(gold_tokens)
    common = sum(overlap.values())
    if common == 0:
        return 0.0
    precision = common / len(pred_tokens)
    recall = common / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def any_exact_match(predicted: str, gold_answers: str | Iterable[str]) -> bool:
    if isinstance(gold_answers, str):
        gold_answers = [gold_answers]
    return any(exact_match(predicted, gold) for gold in gold_answers)

