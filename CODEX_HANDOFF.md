# eMadenCBS Teknik Handoff

## 1. Ürün hedefi

- eMadenCBS, Türkçe ÇED PDF'lerinden proje bilgileri ve koordinat tabloları çıkaran PySide6 masaüstü uygulamasıdır.
- Nihai amaç çok farklı yapıdaki ÇED PDF'lerini otomatik işleyerek doğru poligonlar ve KML üretmektir.
- Hiçbir çözüm belirli bir PDF, firma, ruhsat numarası, sayfa numarası veya belirli koordinata özel yazılmamalıdır.

## 2. Ana veri akışı

PDF  
→ text layer / seçilmiş OCR  
→ TableDetector  
→ TableClassifier / DatumDetector  
→ CoordinateEngine  
→ state_machine  
→ PolygonBuilder  
→ ProjectModel  
→ MapViewer / KMLExporter

## 3. Korunması gereken mevcut durum

- KML çıktısı mevcut haliyle kullanıcı tarafından uygun bulunmuştur.
- KML davranışı bu aşamada değiştirilmemelidir.
- ProjectInfoExtractor mevcut testlerde firma, maden türü, ruhsat, il ve ilçe bilgilerini doğru çıkarabilmektedir.
- PolygonBuilder'ın mevcut duplicate/subset mantığı kanıt olmadan değiştirilmemelidir.
- Ana fonksiyonel test GUI üzerinden `python main.py` ile yapılır.
- Parser değişiklikleri birden fazla farklı PDF ile regresyon testine tabi tutulmalıdır.

## 4. OCR performans durumu

534 sayfalık zor bir test PDF'sinde geçmişte yaklaşık 496 sayfa OCR ediliyor ve işlem yaklaşık 496 saniye sürüyordu.

Yapılan genel performans iyileştirmeleri sonucunda:

- hızlı text-layer taraması şu anda ilk 150 sayfayla sınırlı,
- hedef OCR sayfaları puanlanıyor,
- hedeflerden sınırlı sayıda güçlü aday seçiliyor,
- OCR grupları hedef sayfanın yaklaşık -1..+3 çevresini kullanıyor,
- aynı test dosyasında OCR edilen sayfa sayısı yaklaşık 10 seviyesine ve toplam süre yaklaşık 20 saniye seviyesine indirildi.

Bu davranışlar şu an korunmalıdır. İlk 150 sayfa sınırı genel ürün açısından ileride yeniden değerlendirilebilecek bir heuristiktir; PDF'ye özel kural değildir.

## 5. 20332 test PDF'sinin rolü

20332 yalnızca karmaşık bir stres/regresyon örneğidir. Bu PDF için özel parser kuralı yazılmayacaktır.

Bu dosyada gerçek runtime debug ile PolygonBuilder'a ulaşan gruplar incelendi.

Gözlenen ortak yapı:

RUHSAT_ALANI:

- DEFAULT
- POLIGON_1

PROJE_ALANI:

- DEFAULT
- POLIGON_1
- POLIGON_2

STOK_ALANI:

- DEFAULT
- POLIGON_2

SANTIYE_ALANI:

- DEFAULT

Bu çıktı PolygonBuilder'ın kendi başına fazladan poligon üretmediğini, aynı fiziksel tablo içindeki noktaların daha önce farklı context ile PolygonBuilder'a ulaştığını gösterdi.

20332 için geçici PolygonBuilder debug print kodu tamamen kaldırıldı.

## 6. Runtime teşhisinden doğrulanan genel problemler

### 6.1 DEFAULT tek başına hata değildir

DEFAULT:

- gerçek başlıksız bir poligon olabilir,
- polygon başlığı OCR tarafından okunamamış olabilir,
- devam sayfasında başlık önceki sayfada kalmış olabilir,
- parser context'i sıfırlanmış olabilir,
- fiziksel tablonun yalnız koordinat bölümünü içeren parçası olabilir.

Bu nedenle DEFAULT silinmemeli veya POLIGON_n ile otomatik birleştirilmemelidir.

### 6.2 Text-layer + OCR aynı fiziksel tabloyu tekrar üretebilir

MainWindow'da text-layer ve seçilmiş OCR metni birleşebildiği için aynı fiziksel koordinat tablosu sisteme iki farklı metinsel temsil olarak girebilir.

Bunlar farklı:

- table_index
- section
- polygon_group
- parser yöntemi
- hatta küçük koordinat farkları

alabilir.

### 6.3 table_index fiziksel tablo kimliği değildir

CoordinateEngine tarafından oluşturulan table_index yalnız mevcut tables listesindeki sıra numarasıdır.

OCR eklenmesi, başka bir tablonun bulunması veya tablo sınırlarının değişmesi table_index değerini değiştirebilir.

Bu nedenle ileride fiziksel tablo kimliği için kullanılmamalıdır.

### 6.4 İki parser ayrı context ile çalışabilir

state_machine içinde tek-satır ve 5-satır parser yolları vardır.

Aynı fiziksel nokta:

- text-layer'da 5-satırlık,
- OCR'da tek-satırlık

olarak görülebilir ve farklı context metadata ile üretilebilir.

### 6.5 OCR aykırı koordinatlar üretilebilir

Runtime örneğinde çevredeki UTM Y değerleri yaklaşık 713xxx iken OCR bazı noktalarda yaklaşık 537xxx değer üretmiştir.

Bu problem sabit koordinat önekleriyle çözülmemelidir. İleride grup içi robust geometri kontrolü ve UTM/coğrafi koordinat tutarlılığı kullanılmalıdır.

## 7. Mimari yön

Genel çözüm sırası:

A. SOURCE / OCR PROVENANCE  
B. TABLE IDENTITY  
C. POINT CONTEXT  
D. POLYGON GROUPING  
E. GEOMETRY VALIDATION  
F. DEDUPLICATION

Bu katmanlar tek seferde yeniden yazılmayacaktır. Her biri küçük ve ayrı geliştirme paketleri halinde uygulanacaktır.

## 8. Şu anki birinci öncelik

Sıradaki geliştirme:

AŞAMA A — SOURCE / OCR PROVENANCE

İlk hedef yalnız:

- source_page
- source_method = text_layer | ocr

bilgisini mümkün olduğunca erken oluşturmak ve sonraki katmanlara kaybetmeden taşımaktır.

İlk provenance değişikliğinde:

- TableDetector.find_tables() mevcut list[str] API'si hemen değiştirilmemeli,
- MainWindow raw_text davranışı bozulmamalı,
- PolygonBuilder mantığı değiştirilmemeli,
- state_machine gruplama mantığı değiştirilmemeli,
- dedup yapılmamalı,
- KML değiştirilmemeli.

Önce geriye uyumlu en küçük altyapı değişikliği tasarlanmalıdır.

## 9. Daha sonra planlanan metadata

İlerleyen aşamalarda point seviyesine kadar taşınması hedeflenen bilgiler:

- source_page
- source_method
- source_table_identity
- area_type
- polygon_group
- polygon_group_origin
- parser_method

DEFAULT ileride gerçek bir kimlikten çok unresolved context olarak modellenebilir; fakat bu değişiklik henüz yapılmayacaktır.

## 10. Deduplication ilkesi

İleride:

- metadata hangi noktaların birlikte değerlendirileceğini,
- geometri aday poligonların aynı fiziksel alan olup olmadığını,
- provenance ise hangi observation'ın tercih edileceğini

belirlemelidir.

Yalnız metadata veya yalnız geometri ile duplicate temizliği yapılmamalıdır.

## 11. Git checkpoint

AGENTS.md dosyasının eklendiği son doğrulanmış checkpoint:

`f90f988 - Add Codex project instructions`

Bu checkpoint'te çalışma ağacı temizdir.

## 12. Şu anda yapılmaması gerekenler

- 20332'ye özel çözüm yazma.
- DEFAULT grupları topluca silme.
- DEFAULT'u otomatik POLIGON_1/POLIGON_2'ye bağlama.
- PolygonBuilder duplicate sistemini yeniden yazma.
- state_machine parserlarını topluca refactor etme.
- TableDetector API'sini aniden değiştirme.
- KML kodunu değiştirme.
- e-ÇED batch geliştirmesine geri dönme.
- Kullanıcı onayı olmadan commit yapma.
