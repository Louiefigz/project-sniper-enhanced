"""claims_contract tests — the pre-render truth gate on numeric card copy.

MODULE_STUDY §1.2#11 / §5 item 6: every numeric token in a card's copy must
be SPOKEN in the card's window — arithmetic string/number match (scales,
spelled cardinals by lookup), never regex semantics. evidence*/icon* exempt.
"""
import unittest

from _common import *  # noqa: F401,F403
import claims_contract as cc
import plan_lint


def _words(text: str, start: float = 10.0, step: float = 0.5) -> list[dict]:
    out, t = [], start
    for tok in text.split():
        out.append({"word": tok, "start": round(t, 3), "end": round(t + 0.4, 3)})
        t += step
    return out


def _plan(spec: dict, s: float = 10.0, e: float = 14.0) -> dict:
    return {"graphicsTrack": [{"outStart": s, "outEnd": e, "kind": "stat-card",
                               "anchor": "free-band", "reason": "x",
                               "spec": spec}]}


def _errors(plan: dict, words: list[dict]) -> list[str]:
    rep = plan_lint.Report()
    cc.check_claims_contract(plan, words, rep)
    return rep.errors


class TokenValueTests(unittest.TestCase):
    def test_arithmetic_forms(self) -> None:
        cases = {"92%": 92.0, "$300": 300.0, "$300+": 300.0, "1,000": 1000.0,
                 "450M": 450e6, "10k": 10e3, "4.5": 4.5, "10x": 10.0,
                 "3rd": 3.0, "(12)": 12.0}
        for tok, want in cases.items():
            self.assertEqual(cc.token_value(tok), want, tok)

    def test_non_numbers_are_none(self) -> None:
        for tok in ("9:16", "24/7", "GPT-5.6", "#c6f542", "word"):
            self.assertIsNone(cc.token_value(tok), tok)

    def test_claim_tokens_skip_digit_bearing_names(self) -> None:
        text = "GPT-5.6 scored 92% on 9:16 at #c6f542 v2"
        self.assertEqual(cc.claim_tokens(text), ["92%", "9:16"])


class ClaimsMatchTests(unittest.TestCase):
    def test_digit_copy_matches_digit_speech(self) -> None:
        words = _words("it scored 92 on the benchmark")
        self.assertEqual(_errors(_plan({"value": "92%"}), words), [])

    def test_spelled_cardinals_compose(self) -> None:
        words = _words("it scored ninety two percent overall")
        self.assertEqual(_errors(_plan({"value": "92%"}), words), [])

    def test_hundreds_compose(self) -> None:
        words = _words("cost me three hundred dollars total")
        self.assertEqual(_errors(_plan({"value": "$300+"}), words), [])

    def test_digit_scale_composes(self) -> None:
        words = _words("about 450 million tokens in total")
        self.assertEqual(_errors(_plan({"value": "450M"}), words), [])

    def test_word_scale_composes(self) -> None:
        words = _words("we made ten thousand dollars that week")
        self.assertEqual(_errors(_plan({"value": "$10k"}), words), [])

    def test_wrong_number_fails_loudly(self) -> None:
        # "scored overall" keeps the LL-009 coverage floor satisfied so the
        # ONE error is the numeric mismatch (the gate under test here).
        words = _words("it scored eighty seven percent overall")
        errs = _errors(_plan({"value": "92% scored overall"}), words)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("'92%'", errs[0])
        self.assertIn("not spoken", errs[0])

    def test_number_outside_window_fails(self) -> None:
        # spoken at 30s; card window [10,14] + 3s near band ends at 17s
        words = _words("we hit 92 later on", start=30.0)
        self.assertTrue(_errors(_plan({"value": "92%"}), words))

    def test_ratio_token_string_matches(self) -> None:
        words = _words("we reframe to 9:16 for shorts")
        self.assertEqual(_errors(_plan({"label": "9:16"}), words), [])
        self.assertTrue(_errors(_plan({"label": "9:16"}),
                                _words("no ratio spoken here")))

    def test_evidence_and_icon_slots_exempt(self) -> None:
        spec = {"evidence": {"source": "GPT-5.6 RELEASE", "date": "JUL 09 2026"},
                "icon1": "arrow2.svg"}
        self.assertEqual(_errors(_plan(spec), _words("nothing numeric here")), [])

    def test_nested_spec_strings_are_checked(self) -> None:
        spec = {"statements": [{"text": "Day 1"}, {"text": "92% pass"}]}
        words = _words("day one it hit ninety two percent pass")
        self.assertEqual(_errors(_plan(spec), words), [])
        # "pass" keeps the LL-009 coverage floor met ("1" + "pass" spoken) so
        # the ONE error is the nested numeric miss (the gate under test).
        errs = _errors(_plan(spec), _words("day one pass only spoken"))
        self.assertEqual(len(errs), 1, errs)          # only the 92% is owed
        self.assertIn("statements", errs[0])

    def test_ordinal_copy_matches_ordinal_word(self) -> None:
        words = _words("the third agent finished first")
        self.assertEqual(_errors(_plan({"item1": "3rd agent"}), words), [])

    def test_card_without_numbers_owes_nothing(self) -> None:
        # <=2-word copy: no numeric obligation AND under the >2-word phrase
        # grounding floor (LL-003). It still owes the LL-009 beat-coverage
        # floor — spoken-in-window copy passes with zero errors.
        plan = _plan({"title": "Plan wins"})
        self.assertEqual(_errors(plan, _words("this plan wins every time")), [])

    def test_title_cards_are_claim_bearing_too(self) -> None:
        plan = {"titleCards": [{"outStart": 10.0, "outEnd": 12.5,
                                "text": "Made $10k in 30 days"}]}
        ok = _words("made ten thousand dollars in thirty days")
        self.assertEqual(_errors(plan, ok), [])
        errs = _errors(plan, _words("made five thousand dollars in thirty days"))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("titleCards[0]", errs[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
