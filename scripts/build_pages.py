"""Build the browser-only GitHub Pages edition from the Flask templates."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs"
sys.path.insert(0, str(ROOT))

from rules import (MODES, PRODUCTS, SPACARE_ALKA_DOWN, SPACARE_ALKA_UP,
                   SPACARE_MINICHLOR, SPACARE_PH_DOWN, SPACARE_PH_UP,
                   SUNDANCE_GUIDE)


def build() -> None:
    OUTPUT.mkdir(exist_ok=True)
    static_output = OUTPUT / "static"
    if static_output.exists():
        shutil.rmtree(static_output)
    static_output.mkdir()
    for name in ("app.js", "pages-api.js", "style.css", "product-jar.png"):
        shutil.copy2(ROOT / "static" / name, static_output / name)
    shutil.copytree(ROOT / "static" / "icons", static_output / "icons")

    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "{{ url_for('static', filename='style.css') }}", "static/style.css"
    ).replace(
        '<script src="{{ url_for(\'static\', filename=\'app.js\') }}" defer></script>',
        '<script src="static/pages-config.js" defer></script>\n'
        '  <script src="static/pages-api.js" defer></script>\n'
        '  <script src="static/app.js" defer></script>',
    )
    html = html.replace(
        '    <div class="top-grid">',
        '    <p class="pages-note">Målinger og innstillinger lagres bare i denne nettleseren. '
        'Denne utgaven er ikke koblet til Home Assistant eller PoolLab.</p>\n'
        '    <div class="top-grid">',
        1,
    )
    html = html.replace(
        '  <title>Spa-hjelp</title>',
        '  <title>Spa-hjelp</title>\n'
        '  <link rel="icon" type="image/svg+xml" href="static/icons/hot_tub.svg">',
        1,
    )
    if "{{" in html or "{%" in html:
        raise ValueError("Unrendered Flask template expression in Pages HTML")
    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    (OUTPUT / ".nojekyll").touch()

    config = json.dumps({
        "products": PRODUCTS,
        "modes": MODES,
        "sources": {
            "sundance": SUNDANCE_GUIDE,
            "mini_chlor": SPACARE_MINICHLOR,
            "alka_up": SPACARE_ALKA_UP,
            "alka_down": SPACARE_ALKA_DOWN,
            "ph_up": SPACARE_PH_UP,
            "ph_down": SPACARE_PH_DOWN,
        },
    }, ensure_ascii=False)
    (OUTPUT / "static" / "pages-config.js").write_text(
        f"window.SPA_CONFIG = {config};\n", encoding="utf-8"
    )


if __name__ == "__main__":
    build()
