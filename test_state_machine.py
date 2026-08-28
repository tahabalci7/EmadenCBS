with open("temp/ocr_sonuc.txt", "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f.readlines() if line.strip()]

for i, line in enumerate(lines[:80], start=1):
    print(i, repr(line))