class ProjectModel:

    def __init__(
        self,
        pdf_path,
        coordinates,
        polygons,
        tables,
        diagnostics=None,
    ):
        self.pdf_path = pdf_path
        self.coordinates = coordinates
        self.polygons = polygons
        self.project_info = {}
        self.tables = tables
        self.diagnostics = list(diagnostics or [])

    @property
    def coordinate_count(self):
        return len(self.coordinates)

    @property
    def polygon_count(self):
        return len(self.polygons)

    @property
    def table_count(self):
        return len(self.tables)

    def to_dict(self):
        return {
            "pdf_path": self.pdf_path,
            "coordinate_count": self.coordinate_count,
            "polygon_count": self.polygon_count,
            "table_count": self.table_count,
            "coordinates": self.coordinates,
            "polygons": self.polygons,
        }
    def set_project_info(
        self,
        project_info,
    ):
        self.project_info = project_info