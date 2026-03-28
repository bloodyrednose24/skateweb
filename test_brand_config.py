import json
import os
import unittest

from urllib.parse import urljoin

from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent

def python_filter_by_company(products, selected_companies):
    if not selected_companies:
        return products

    result = []
    lower_companies = {c.lower() for c in selected_companies}
    for p in products:
        brand = (p.get("brand") or "").lower()
        if any(comp in brand for comp in lower_companies):
            result.append(p)
    return result


class TestBrandConfig(unittest.TestCase):
    def test_config_includes_expected_brands(self):
        config_file = THIS_DIR / "brand-config.json"
        self.assertTrue(config_file.exists(), "brand-config.json should exist")

        with open(config_file, "r", encoding="utf-8") as f:
            brands = json.load(f)

        expected = ["DGK", "Element", "Globe", "Girl", "Jart", "Antiz", "MOB", "Zero", "April"]
        for brand in expected:
            self.assertIn(brand, brands)

        self.assertNotIn("Vans", brands)
        self.assertNotIn("Nike", brands)
        self.assertNotIn("Almost", brands)

    def test_filter_by_company_logic(self):
        products = [
            {"brand": "DGK"},
            {"brand": "Antiz"},
            {"brand": "Primitive"},
            {"brand": "Vans"},
            {"brand": "Unknown"},
        ]
        selected = ["DGK", "Antiz"]
        filtered = python_filter_by_company(products, selected)

        self.assertEqual(len(filtered), 2)
        self.assertTrue(any(p["brand"] == "DGK" for p in filtered))
        self.assertTrue(any(p["brand"] == "Antiz" for p in filtered))


if __name__ == "__main__":
    unittest.main()
