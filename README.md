# Figma to FGUI Conversion Core

This package converts offline Figma JSON fixtures into a validated FGUI staging tree. It never writes to the source project.

```powershell
$env:PYTHONPATH = "src"
python -m pip install -e ".[dev]"
python -m figma_to_fgui.cli convert tests/fixtures/figma/simple-frame.json tests/fixtures/fgui Sample .staging changeset.json
```

Exit code `0` means the changeset is applicable. Exit code `2` means at least one `ERROR` diagnostic blocked application.
