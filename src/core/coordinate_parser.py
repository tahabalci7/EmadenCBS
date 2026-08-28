import re


HEDEF_BASLIKLAR = [
    "PROJEYE KONU ALAN VE KOORDİNATLARI",
    "TALEP EDİLEN ÇED ALANI",
    "ÇED ALANI SINIR KOORDİNATLARI",
    "ÇED ALANI KOORDİNATLARI"
]


def hedef_bolum_bul(metin):

    metin_buyuk = metin.upper()

    baslangic = -1

    bulunan_baslik = ""

    # Öncelik sırasına göre ara
    for baslik in HEDEF_BASLIKLAR:

        index = metin_buyuk.find(baslik)

        if index != -1:

            baslangic = index
            bulunan_baslik = baslik
            break


    if baslangic == -1:

        print(
            "ÇED alan başlığı bulunamadı"
        )

        return ""


    # Yeni tablo başlangıcı veya alan sonuna kadar
    sonraki = metin_buyuk.find(
        "TOPLAM ALAN",
        baslangic
    )


    if sonraki == -1:

        sonraki = baslangic + 5000


    print(
        "Seçilen bölüm:",
        bulunan_baslik
    )


    return metin[
        baslangic:sonraki
    ]



def koordinat_bul(metin):

    koordinatlar = []


    # Ondalıklı sayıları al
    sayilar = re.findall(
        r"\d+\.\d+",
        metin
    )


    sayilar = [
        float(x)
        for x in sayilar
    ]


    for i in range(
        len(sayilar)-1
    ):

        y = sayilar[i]
        x = sayilar[i+1]


        # ED50 UTM filtre
        if (
            600000 <= y <= 800000
            and
            4000000 <= x <= 5000000
        ):

            koordinatlar.append(
                {
                    "Y": y,
                    "X": x
                }
            )


    return koordinatlar



if __name__ == "__main__":


    with open(
        "ocr_sonuc.txt",
        "r",
        encoding="utf-8"
    ) as f:

        metin = f.read()



    bolum = hedef_bolum_bul(
        metin
    )


    sonuc = koordinat_bul(
        bolum
    )


    print(
        "\nBulunan koordinat:",
        len(sonuc)
    )


    for no,k in enumerate(
        sonuc,
        1
    ):

        print(
            no,
            k
        )