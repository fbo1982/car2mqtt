"""Render the real template for the isolated Playwright UI regression test."""
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.providers.registry import ProviderRegistry

template = Environment(loader=FileSystemLoader(ROOT / 'app/templates'),
                       autoescape=select_autoescape(['html'])).get_template('index.html')
html = template.render(
    version=(ROOT / 'VERSION').read_text().strip(),
    mqtt_settings={'host': '', 'port': 1883, 'base_topic': 'car', 'qos': 1, 'retain': True},
    providers=[p.model_dump(mode='json') for p in ProviderRegistry().all()],
    cards_json=json.dumps([]), helper_homezone_json='null', ui_settings_json='{}',
    zones_json='[]', mqtt_clients_json='[]',
)
Path(sys.argv[1]).write_text(html, encoding='utf-8', newline='\n')
