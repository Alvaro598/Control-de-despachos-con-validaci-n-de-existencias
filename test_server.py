import math
import unittest

import server


class PayloadValidationTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "solicitante": "Ana Pérez",
            "correo": "ana@empresa.co",
            "codigo_producto": "INS-0101",
            "cantidad": 4,
            "destino": "Sede Centro",
            "motivo": "despacho",
        }

    def test_valid_payload_normalizes_quantity(self):
        payload, error = server.validate_payload(self.payload)
        self.assertIsNone(error)
        self.assertEqual(payload["cantidad"], 4.0)

    def test_missing_field_is_rejected(self):
        payload = dict(self.payload)
        payload.pop("destino")
        cleaned, error = server.validate_payload(payload)
        self.assertIsNone(cleaned)
        self.assertIn("destino", error)

    def test_zero_negative_non_finite_or_non_numeric_quantity_is_rejected(self):
        for quantity in (0, -1, math.inf, -math.inf, math.nan, "no-numérica"):
            with self.subTest(quantity=quantity):
                payload = dict(self.payload, cantidad=quantity)
                cleaned, error = server.validate_payload(payload)
                self.assertIsNone(cleaned)
                self.assertIn("cantidad", error)

    def test_invalid_email_sku_and_motive_are_rejected(self):
        invalid_values = (
            ("correo", "no-es-correo"),
            ("codigo_producto", "INS 0101"),
            ("motivo", "otro"),
        )
        for field, value in invalid_values:
            with self.subTest(field=field):
                cleaned, error = server.validate_payload(dict(self.payload, **{field: value}))
                self.assertIsNone(cleaned)
                self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
