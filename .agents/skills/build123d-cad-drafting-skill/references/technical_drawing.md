# Technical Drawing Bridge

Use this reference when a build123d task moves from solid modeling into sheet layout.

- `TechnicalDrawing(...)` creates the border and title block.
- `project_to_viewport(...)` projects the 3D model into visible and hidden 2D edge sets.
- `ExtensionLine(...)` and `Text(...)` add dimensions and labels.
- `Draft(...)` controls dimension formatting.
- `ExportSVG(...)` writes the authoritative vector sheet; `ExportDXF(...)` is useful when downstream CAD needs DXF.
Official tutorial:

- https://build123d.readthedocs.io/en/latest/tech_drawing_tutorial.html
