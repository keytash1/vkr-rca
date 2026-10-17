"""Registration integrity only; these tests do not execute or score an LLM."""

import unittest
from evaluate_assistant_injections import assignments


class InjectionRegistrationTests(unittest.TestCase):
    def test_twenty_unique_explicit_exposures(self):
        plan=assignments()
        self.assertEqual(len(plan),20)
        self.assertEqual(len({(channel,name) for channel,name,_ in plan}),20)
        for channel in ("question","runbook"):
            self.assertEqual(sum(row[0]==channel for row in plan),10)

    def test_same_payload_compared_across_both_untrusted_channels(self):
        plan=assignments()
        question={name:text for channel,name,text in plan if channel=="question"}
        runbook={name:text for channel,name,text in plan if channel=="runbook"}
        self.assertEqual(question,runbook)
        self.assertTrue(all(isinstance(text,str) and text.strip() for text in question.values()))


if __name__ == "__main__":
    unittest.main()
