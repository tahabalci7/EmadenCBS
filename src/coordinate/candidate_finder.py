import re


class CandidateFinder:

    NUMBER_PATTERN = re.compile(r"\b\d{5,8}(?:[.,]\d+)?\b")

    @classmethod
    def find(cls, text):
        candidates = []

        for line_no, line in enumerate(text.splitlines(), start=1):
            matches = cls.NUMBER_PATTERN.findall(line)

            for value in matches:
                candidates.append({
                    "line": line_no,
                    "value": value,
                    "text": line.strip()
                })

        return candidates