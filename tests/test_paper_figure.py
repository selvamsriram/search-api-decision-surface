import copy
import json
import re
from pathlib import Path

from paper.figures import make_figures


def test_designer_export_updates_counts_correctness_rates_and_bar_lengths(tmp_path, monkeypatch):
    original = (make_figures.HERE / "Figure 3.html").read_text()
    target = tmp_path / "Figure 3.html"
    target.write_text(original)
    monkeypatch.setattr(make_figures, "HERE", tmp_path)
    calls = []
    monkeypatch.setattr(make_figures.subprocess, "run", lambda args, **kwargs: calls.append(args))
    data = copy.deepcopy(make_figures.FALLBACK)
    data["providers"]["tavily"]["bucket"]["blind"] = [66, 17]
    data["providers"]["tavily"]["bucket"]["noop"] = [18, 0]
    make_figures.render_partition_designer(data)
    source = target.read_text()
    template = json.loads(re.search(r'<script type="__bundler/template">\s*(.*?)\s*</script>', source, re.S).group(1))
    tavily = template.split('<!-- ===== Tavily row ===== -->')[1].split('<!-- ===== Firecrawl row ===== -->')[0]
    assert '>66</span>' in tavily and '>/ 17</span>' in tavily and '>26%</span>' in tavily
    assert '>18</span>' in tavily and '>/ 0</span>' in tavily and '>0%</span>' in tavily
    assert 'width:66%' in tavily and 'width:18%' in tavily
    assert 'width:1400px; height:600px' in template
    # Embedded fonts/runtime assets are preserved byte-for-byte.
    manifest = r'<script type="__bundler/manifest">\s*(.*?)\s*</script>'
    assert re.search(manifest, original, re.S).group(1) == re.search(manifest, source, re.S).group(1)
    assert len(calls) == 1 and Path(calls[0][-1]).name == 'fig3_decision_partition.png'
