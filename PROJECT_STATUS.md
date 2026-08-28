---

# Sprint 18 Sonuçları

## Durum

OCR motoru PDF'nin tamamını başarıyla okuyabiliyor.

Gerçek ÇED PDF'lerinde koordinat tabloları tespit edildi.

Ancak yapılan debug çalışması sonucunda koordinat tablolarının satır tabanlı değil, blok tabanlı okunduğu görüldü.

Örnek yapı:

R.1
688662.000
4100000.000
37.02562583
35.12061291

R.2
690000.000
4100000.000
...

Bu nedenle mevcut regex tabanlı CoordinateEngine mimarisi yeterli değildir.

---

## Alınan Mimari Karar

CoordinateEngine tamamen yeniden tasarlanacaktır.

Yeni mimari:

coordinate/

    parser.py
    state_machine.py
    table_detector.py
    datum_detector.py
    coordinate_engine.py

---

## Sprint 19

State Machine Parser

Amaç:

PDF'den çıkan ham metni durum makinesi (State Machine) ile okuyarak;

LABEL

↓

UTM Y

↓

UTM X

↓

Latitude

↓

Longitude

bloklarını otomatik oluşturmak.

---

## Sprint 20

Table Parser

Amaç:

Bir PDF içerisindeki birden fazla koordinat tablosunu otomatik ayırmak.

Örnek:

- Ruhsat Alanı
- İşletme İzin Alanı
- Mevcut ÇED Alanı
- Talep ÇED Alanı
- Tesis Alanı

---

## Sprint 21

Coordinate Engine v2

Amaç:

Parser + Table Detector + Datum Detector birleşik çalışacak.

Çıktı:

Polygon nesneleri

↓

Harita

↓

Excel

↓

DXF

↓

SHP

---

## Önemli Not

Debug çalışması sonucunda OCR motorunun doğru çalıştığı doğrulanmıştır.

Sorun OCR'da değil, koordinat tablolarının PDF'den blok yapısında okunmasıdır.

Bu nedenle Sprint 19'dan itibaren regex tabanlı yaklaşım terk edilerek State Machine tabanlı parser geliştirilecektir.
## Sprint 19 Sonucu

Durum: Tamamlandı

Gerçek ÇED PDF üzerinde koordinat sistemi başarıyla geliştirildi.

Son test sonucu:

- Toplam sayfa: 137
- Taranan sayfa: 137
- Gerçek koordinat tablosu: 4
- Koordinat adayı: 19
- Polygon: 2

Tespit edilen polygonlar:

1. PROJE_ALANI
   - Nokta sayısı: 9
   - Datum: ED-50
   - Zon: 36

2. RUHSAT_ALANI
   - Nokta sayısı: 10
   - Datum: ED-50
   - Zon: 36

Tamamlanan bileşenler:

- State Machine Parser
- Table Detector v2
- Table Classifier
- Datum Detector
- Coordinate Engine
- Polygon Builder
- Project Model

Mimari akış:

PDF
→ OCR / Metin Katmanı
→ Table Detector
→ Table Classifier
→ Datum Detector
→ State Machine Parser
→ Coordinate Engine
→ Polygon Builder
→ Project Model

Önemli karar:

PDF içindeki nokta sırası değiştirilmez.
Polygonlar harita ve dışa aktarma aşamasında otomatik kapatılır.
Orijinal koordinat listesine fazladan kapanış noktası eklenmez.
## Sprint 20 Gün Sonu Durumu

Durum: Devam Ediyor

### Tamamlanan Çalışmalar

Harita görüntüleme altyapısı oluşturuldu.

Oluşturulan dosya:

- `src/map/map_viewer.py`

Harita penceresi ana arayüze bağlandı.

Menü yolu:

- CBS
- Haritada Göster

### Harita Özellikleri

Aşağıdaki özellikler başarıyla çalışmaktadır:

- Polygonların farklı renklerde gösterilmesi
- Polygon içlerinin yarı saydam doldurulması
- Fare tekeri ile yakınlaştırma ve uzaklaştırma
- Sol fare tuşu ile haritayı sürükleme
- Polygon lejantı
- Nokta adlarının gösterilmesi
- Noktaya tıklanınca koordinat bilgilerinin açılması
- Nokta tıklama olayının diğer noktalara aktarılmasının engellenmesi
- Polygon içine tıklayarak polygon seçme
- Seçilen polygon çizgisinin kalınlaştırılması
- Seçilen polygon dolgusunun koyulaştırılması
- Seçilen polygon bilgilerinin pencerenin altında gösterilmesi
- Başka polygon seçildiğinde önceki seçimin kaldırılması
- Üst üste gelen polygonlar arasında art arda tıklayarak geçiş yapılması

### Nokta Bilgi Penceresinde Gösterilen Alanlar

- Nokta adı
- Tablo türü
- UTM Y
- UTM X
- Enlem
- Boylam
- Datum
- Zon

### Polygon Bilgi Alanında Gösterilen Alanlar

- Polygon türü
- Bölüm başlığı
- Nokta sayısı
- UTM datum
- Coğrafi datum
- Zon
- DOM
- Projeksiyon

### Son Gerçek PDF Testi

- Toplam sayfa: 137
- Taranan sayfa: 137
- Koordinat adayı: 19
- Gerçek koordinat tablosu: 4
- Oluşturulan polygon: 2

Oluşturulan polygonlar:

1. `PROJE_ALANI`
   - Nokta sayısı: 9
   - Datum: ED-50
   - Coğrafi datum: WGS-84
   - Zon: 36
   - DOM: 33
   - Projeksiyon: 6 Derece

2. `RUHSAT_ALANI`
   - Nokta sayısı: 10
   - Datum: ED-50
   - Coğrafi datum: WGS-84
   - Zon: 36
   - DOM: 33
   - Projeksiyon: 6 Derece

### Mimari Akış

PDF  
→ OCR / PDF Metin Katmanı  
→ Table Detector  
→ Table Classifier  
→ Datum Detector  
→ State Machine Parser  
→ Coordinate Engine  
→ Polygon Builder  
→ Project Model  
→ Map Viewer

### Alınan Kararlar

- PDF içindeki nokta sırası değiştirilmez.
- Nokta listesine otomatik kapanış noktası eklenmez.
- Polygonlar çizim ve dışa aktarma aşamasında otomatik kapatılır.
- Nokta düzenleme özelliği geliştirilmeyecektir.
- Sistem mevcut ÇED verisini okuyacak, analiz edecek ve dışa aktaracaktır.
- Üst üste gelen polygonlarda tekrar tıklama ile seçim sırayla değiştirilir.

### Sonraki Çalışma

Sprint 20 devamında:

- Katman yöneticisi
- Polygon görünürlük kontrolü
- Seçilen polygonu görünüm merkezine alma
- Harita bilgi panelinin geliştirilmesi
- Gerçek koordinat sistemi altyapısı
- OpenStreetMap veya uydu altlığı hazırlığı