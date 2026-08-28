from dataclasses import dataclass, field
from typing import List


@dataclass
class Project:

    name: str = "Yeni Proje"

    pdf_files: List[str] = field(default_factory=list)

    coordinate_files: List[str] = field(default_factory=list)

    excel_files: List[str] = field(default_factory=list)