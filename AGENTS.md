# eMadenCBS Codex Çalışma Kuralları

## Ürün kapsamı

- eMadenCBS tek bir PDF için geliştirilmiyor.
- Amaç, yapıları farklı yüzlerce Türkçe ÇED PDF'sinde çalışabilecek genel bir ürün oluşturmaktır.
- Belirli PDF sayfasına, firma adına, ruhsat numarasına, proje adına veya belirli koordinat değerlerine özel parser kuralları yazma.
- Test PDF'leri yalnız genel mimari sorunları ortaya çıkarmak için kullanılır.

## Çalışma biçimi

- Her görevde önce mevcut kodu incele.
- Küçük ve tek amaçlı değişiklikler yap.
- Kullanıcı istemeden kapsam genişletme.
- Gereksiz refactor yapma.
- Çalışan kodu yeniden yazma.
- Birden fazla mimari değişikliği aynı pakette yapma.
- Mevcut davranışı korumayı önceliklendir.
- Varsayım yapmak yerine mevcut dosya ve runtime verisini incele.

## Git güvenliği

- Kullanıcı açıkça istemedikçe git add yapma.
- Kullanıcı açıkça istemedikçe commit yapma.
- git reset, git clean, git restore, checkout gibi çalışma kaybına yol açabilecek komutları kullanıcı açıkça istemedikçe kullanma.
- Kod değişikliğinden sonra git diff ile değişikliği göster.
- Beklenmeyen başka dosya değişikliği varsa dur ve bildir.

## Test yöntemi

- Python değişikliklerinden sonra uygun py_compile kontrolü yap.
- Ana fonksiyonel test yolu GUI'dir: `python main.py`
- Kullanıcı onayı olmadan yalnız standalone test sonucunu başarı ölçütü sayma.
- Parser değişiklikleri yalnız tek PDF ile değil, bilinen çalışan farklı PDF örnekleriyle regresyon testine tabi tutulmalıdır.

## Mimari ilkeler

- Text layer tercih edilen kaynaktır.
- OCR gerekli olduğunda fallback / tamamlayıcı kaynak olarak kullanılır.
- Aynı fiziksel tablonun text-layer ve OCR temsillerinin ayrı gerçek tablolar gibi davranabileceğini göz önünde bulundur.
- source_page ve source_method gibi provenance bilgisi korunmalıdır.
- table_index yalnız geçici sıra numarasıdır; fiziksel tablo kimliği kabul edilmemelidir.
- DEFAULT polygon_group geçersiz polygon anlamına gelmez.
- DEFAULT çözülmemiş veya kanıtı olmayan context olabilir.
- Gerçek farklı poligonlar yanlışlıkla birleştirilmemelidir.
- Duplicate temizliği yalnız metadata veya yalnız geometriye dayandırılmamalıdır.
- Alan türü, polygon grubu ve kaynak kimliği mümkün olduğunca nokta seviyesine kadar taşınmalıdır.

## Korunması gereken mevcut davranışlar

- Mevcut çalışan PDF'lerin koordinat çıkarımı bozulmamalıdır.
- KML çıktısı kullanıcı açıkça istemedikçe değiştirilmemelidir.
- Mevcut PolygonBuilder duplicate davranışı kanıt olmadan yeniden yazılmamalıdır.
- e-ÇED batch otomasyonu, koordinat/parsing motoru yeterince sağlam hale gelmeden ana geliştirme odağı yapılmamalıdır.

## İletişim

Bir görevi tamamladığında kısa olarak şunları bildir:

1. Hangi dosyalar değişti.
2. Ne değişti.
3. Hangi test/derleme kontrolü çalıştırıldı.
4. Sonuç.
5. Beklenmeyen durum veya risk varsa açıkça belirt.
