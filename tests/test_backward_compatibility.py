#!/usr/bin/env python3
"""Check legacy fixture requirements against the current Evidence schema."""

import json
import unittest
from pathlib import Path


class BackwardCompatibilityTests(unittest.TestCase):
    """Check that the historical sample is not silently accepted by the current schema."""

    def setUp(self):
        """Load test fixtures and schema."""
        fixtures_dir = Path(__file__).parent / "fixtures"
        self.evidence_valid_path = fixtures_dir / "evidence-valid.json"

        schema_path = Path(__file__).parent.parent / "schemas" / "evidence-record.schema.json"
        with schema_path.open() as f:
            self.schema = json.load(f)

    def test_old_evidence_without_provenance_field_exists(self):
        """✅ Confirm test fixture doesn't have provenance (represents old format)."""
        with self.evidence_valid_path.open() as f:
            record = json.load(f)

        # Confirm: old record has no provenance
        self.assertNotIn("provenance", record)
        print("✅ Old fixture confirmed: no provenance field")

    def test_legacy_fixture_lacks_required_semantic_verdict(self):
        """The old fixture is invalid under the current schema; do not imply compatibility."""
        with self.evidence_valid_path.open() as f:
            record = json.load(f)

        schema_required = set(self.schema.get("required", []))
        record_keys = set(record.keys())

        missing = schema_required - record_keys
        self.assertEqual(missing, {"semantic_verdict"})

    def test_provenance_optional_in_schema(self):
        """Provenance is optional; this does not make other legacy fields valid."""
        schema_required = set(self.schema.get("required", []))

        self.assertNotIn("provenance", schema_required)

    def test_legacy_fixture_is_rejected_by_current_schema(self):
        """Historical invalid Evidence must not be silently repaired or accepted."""
        with self.evidence_valid_path.open() as f:
            record = json.load(f)

        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is required for this validation assertion")

        with self.assertRaises(jsonschema.ValidationError) as raised:
            jsonschema.validate(instance=record, schema=self.schema)
        self.assertEqual(raised.exception.validator, "required")
        self.assertIn("semantic_verdict", raised.exception.message)

    def test_provenance_assignment_is_in_memory_only(self):
        """Changing a fixture dictionary does not establish runtime provenance."""
        with self.evidence_valid_path.open() as f:
            record = json.load(f)

        record["provenance"] = "fixture_probe"

        self.assertEqual(record["provenance"], "fixture_probe")
        self.assertNotIn("provenance", json.loads(self.evidence_valid_path.read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
