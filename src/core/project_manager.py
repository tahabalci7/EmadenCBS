from src.models.project import Project


class ProjectManager:

    def __init__(self):
        self.project = Project()

    def new_project(self):
        self.project = Project()

    def add_pdf(self, pdf_path):
        if pdf_path not in self.project.pdf_files:
            self.project.pdf_files.append(pdf_path)

    def get_pdfs(self):
        return self.project.pdf_files

    def pdf_count(self):
        return len(self.project.pdf_files)

    def clear(self):
        self.new_project()