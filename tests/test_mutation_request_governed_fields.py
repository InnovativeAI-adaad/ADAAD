# SPDX-License-Identifier: Apache-2.0

import unittest

from app.agents.mutation_request import MutationRequest


class MutationRequestGovernedFieldsTest(unittest.TestCase):
    def test_round_trip_governed_fields(self) -> None:
        request = MutationRequest(
            agent_id="a",
            generation_ts="ts",
            intent="i",
            ops=[],
            signature="sig",
            nonce="n",
            epoch_id="epoch-9",
            bundle_id="bundle-1",
            random_seed=42,
            capability_scopes=["docs"],
            authority_level="governor-review",
        )
        rebuilt = MutationRequest.from_dict(request.to_dict())
        self.assertEqual(rebuilt.epoch_id, "epoch-9")
        self.assertEqual(rebuilt.bundle_id, "bundle-1")
        self.assertEqual(rebuilt.random_seed, 42)
        self.assertEqual(rebuilt.capability_scopes, ["docs"])
        self.assertEqual(rebuilt.authority_level, "governor-review")


if __name__ == "__main__":
    unittest.main()
