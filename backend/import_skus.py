"""Normalize a saved query response without inventing product data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalize(source):
    if source.get('table') != 'product_list' or not isinstance(source.get('rows'), list):
        raise ValueError('Expected a product_list query result with rows')
    products = []
    for row in source['rows']:
        products.append({
            'sku': row['SKU'], 'name': row['ProductName'].strip(),
            'description': row.get('Description', ''), 'rrp': row['RRP'],
            'dimensions': {key: row.get(key) for key in ('weight', 'length', 'width', 'height', 'volume', 'Volumetric_GrossWeight')},
        })
    return products


if __name__ == '__main__':
    source = json.loads((ROOT / 'data/sku-query-result.json').read_text(encoding='utf-8'))
    products = normalize(source)
    (ROOT / 'data/products.json').write_text(json.dumps(products, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(products)} real product records.')
