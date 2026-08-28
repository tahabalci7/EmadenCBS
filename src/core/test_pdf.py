from pdf_analyzer import PDFAnalyzer

pdf = input("PDF yolunu girin: ").strip().strip('"')

analiz = PDFAnalyzer(pdf)
sonuc = analiz.analyze()

print("----------------")
print("PDF ANALİZ")
print("----------------")

for k, v in sonuc.items():
    print(f"{k}: {v}")