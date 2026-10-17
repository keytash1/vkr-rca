"""Artificial integrity fixtures, not semantic quality or provider evaluation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from validate_assistant_review import validate


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="rca-review-integrity-")
        self.root=Path(self.temp.name);self.review=self.root/"review";self.review.mkdir()
        self.comparison=self.root/"comparison";self.comparison.mkdir()
        self.case="r2-capture-v2-g06-r01"
        config=b'{"fixture":true}\n'
        (self.comparison/"configuration.json").write_bytes(config)
        config_sha=hashlib.sha256(config).hexdigest()
        answers=[];key={};rows=[];plan=[]
        for mode in "CDE":
            for repeat in (1,2,3):
                attempt=f"{self.case}-{mode}-r{repeat}"
                identifier=hashlib.sha256((config_sha+attempt).encode()).hexdigest()[:12]
                outcome={"status":"completed","stop_reason":"REPORT_VALIDATED","report":{"summary":"fixture observation"}}
                receipt={"configuration_sha256":config_sha,"input_file_sha256":"input-fixture","outcome":outcome}
                encoded=(json.dumps(receipt)+"\n").encode()
                (self.comparison/(attempt+".json")).write_bytes(encoded)
                key[identifier]={"mode":mode,"repeat":repeat,"attempt_id":attempt,"receipt_sha256":hashlib.sha256(encoded).hexdigest()}
                answers.append(dict(review_id=identifier,**outcome))
                rows.append(dict(review_id=identifier,useful=True,next_check=True,critical_defects=[],factual_paths=["summary"],unsupported=[]))
                plan.append([self.case,repeat,mode])
        self.put(self.comparison/"assigned-attempts.json",plan)
        self.packet={"case_id":self.case,"role":"locked","input_sha256":"input-fixture","answers":answers}
        self.key=key;self.decisions={"all_report_fields_read":True,"decisions":rows}
        self.flush()

    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def put(path,value):path.write_text(json.dumps(value)+"\n")

    def flush(self):
        self.put(self.review/"packet.json",self.packet)
        self.decisions["packet_sha256"]=hashlib.sha256((self.review/"packet.json").read_bytes()).hexdigest()
        self.put(self.review/"mode-key.json",self.key)
        self.put(self.review/"decisions.json",self.decisions)

    def check_rejected(self):
        with self.assertRaises(ValueError):validate(self.review,self.comparison)

    def test_all_nine_are_accounted(self):
        result=validate(self.review,self.comparison)
        self.assertEqual({m:v["assigned"] for m,v in result["modes"].items()},{"C":3,"D":3,"E":3})
        self.assertFalse(result["independent_human_evaluation"])

    def test_packet_edit_requires_new_attestation(self):
        self.packet["answers"][0]["report"]["summary"]="changed"
        self.put(self.review/"packet.json",self.packet)
        self.check_rejected()

    def test_even_rehashed_packet_cannot_replace_original_report(self):
        self.packet["answers"][0]["report"]["summary"]="changed"
        self.flush();self.check_rejected()

    def test_modes_cannot_be_swapped(self):
        first=next(iter(self.key));self.key[first]["mode"]="D"
        self.flush();self.check_rejected()

    def test_original_receipt_cannot_change(self):
        entry=next(iter(self.key.values()))
        path=self.comparison/(entry["attempt_id"]+".json")
        path.write_bytes(path.read_bytes()+b" ")
        self.check_rejected()

    def test_quotes_must_be_in_reviewed_field(self):
        self.decisions["decisions"][0]["unsupported"]=[{"path":"summary","quote":"not present","reason":"fixture","severity":"noncritical"}]
        self.flush();self.check_rejected()

    def test_duplicate_decision_not_accepted(self):
        self.decisions["decisions"][-1]=self.decisions["decisions"][0]
        self.flush();self.check_rejected()

    def test_failed_answer_cannot_be_marked_useful(self):
        self.packet["answers"][0]["status"]="failed"
        self.flush()
        with self.assertRaises(ValueError):validate(self.review)


if __name__=="__main__":unittest.main()
