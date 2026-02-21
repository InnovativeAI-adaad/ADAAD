# SPDX-License-Identifier: Apache-2.0

import unittest

from app.agents.mutation_request import MutationRequest
from app.agents.mutation_strategies import adapt_generated_request_payload, canonicalize_generated_op
from runtime.preflight import validate_mutation_proposal_schema


class MutationStrategyAdapterTest(unittest.TestCase):
    def test_canonicalize_generated_op_maps_new_code_and_filepath(self) -> None:
        op = canonicalize_generated_op({"op": "replace", "filepath": "app/agents/sample.py", "new_code": "import os\n"})
        self.assertEqual(op["filepath"], "app/agents/sample.py")
        self.assertEqual(op["source"], "import os\n")

    def test_adapt_generated_request_payload_injects_target_for_target_ops(self) -> None:
        payload = {
            "agent_id": "sample",
            "ops": [{"op": "replace", "filename": "app/agents/sample.py", "new_code": "print('x')\n"}],
            "targets": [
                {
                    "agent_id": "sample",
                    "path": "dna.json",
                    "target_type": "dna",
                    "ops": [{"op": "replace", "new_code": "{\"version\": 2}"}],
                }
            ],
        }

        adapted = adapt_generated_request_payload(payload)
        top_level_op = adapted["ops"][0]
        self.assertEqual(top_level_op["target"], "app/agents/sample.py")
        self.assertEqual(top_level_op["source"], "print('x')\n")

        target_op = adapted["targets"][0]["ops"][0]
        self.assertEqual(target_op["target"], "dna.json")
        self.assertEqual(target_op["source"], "{\"version\": 2}")

    def test_adapt_generated_request_payload_overwrites_targets_when_present(self) -> None:
        payload = {
            "agent_id": "sample",
            "ops": [],
            "targets": ["invalid-target-entry"],
            "signature": "",
            "nonce": "",
            "generation_ts": "",
            "intent": "generated",
        }
        adapted = adapt_generated_request_payload(payload)
        self.assertEqual(adapted["targets"], [])

    def test_roundtrip_adapter_schema_and_mutation_request(self) -> None:
        raw_request = {
            "agent_id": "sample",
            "generation_ts": "2026-01-01T00:00:00Z",
            "intent": "generated",
            "ops": [{"op": "replace", "filename": "agent.py", "new_code": "x = 1\n"}],
            "targets": [],
            "signature": "",
            "nonce": "",
        }
        adapted = adapt_generated_request_payload(raw_request)
        schema_result = validate_mutation_proposal_schema(adapted)
        self.assertTrue(schema_result["ok"])

        request = MutationRequest.from_dict(adapted)
        self.assertEqual(request.ops[0]["target"], "agent.py")
        self.assertEqual(request.ops[0]["source"], "x = 1\n")


if __name__ == "__main__":
    unittest.main()
