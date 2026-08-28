from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ECEDClient:
    BASE_URL = "https://eced.csb.gov.tr"

    def fetch_project_page(
        self,
        project_id: int,
    ) -> str:
        """
        e-ÇED proje sayfasının HTML içeriğini getirir.
        """

        url = (
            f"{self.BASE_URL}"
            f"/jsp/ek1/{project_id}"
        )

        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/142.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": (
                    "tr-TR,tr;q=0.9,en;q=0.8"
                ),
            },
        )

        try:
            with urlopen(
                request,
                timeout=30,
            ) as response:
                content = response.read()

                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )

                return content.decode(
                    charset,
                    errors="replace",
                )

        except HTTPError as error:
            raise RuntimeError(
                "e-ÇED sunucusu HTTP hatası döndürdü: "
                f"{error.code} {error.reason}"
            ) from error

        except URLError as error:
            raise RuntimeError(
                "e-ÇED sunucusuna bağlanılamadı: "
                f"{error.reason}"
            ) from error

        except TimeoutError as error:
            raise RuntimeError(
                "e-ÇED bağlantısı zaman aşımına uğradı."
            ) from error

    def save_project_page(
        self,
        project_id: int,
        output_path: str | Path,
    ) -> Path:
        """
        Proje sayfasını incelemek amacıyla HTML dosyası olarak kaydeder.
        """

        html = self.fetch_project_page(
            project_id,
        )

        output_file = Path(
            output_path,
        )

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_text(
            html,
            encoding="utf-8",
        )

        return output_file


if __name__ == "__main__":
    client = ECEDClient()

    try:
        saved_file = client.save_project_page(
            project_id=31515,
            output_path="debug/eced_31515.html",
        )

        print(
            "e-ÇED sayfası başarıyla indirildi."
        )

        print(
            f"Kaydedilen dosya: {saved_file.resolve()}"
        )

    except RuntimeError as error:
        print(
            f"HATA: {error}"
        )