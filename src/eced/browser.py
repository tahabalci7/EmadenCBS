import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright


BASE_URL = "https://eced-duyuru.csb.gov.tr/eced-prod/duyurular.xhtml"

PROJECT_CONFIG = {
    "EK-1": {
        "value": "1",
        "decision": "ÇED Olumlu",
    },
    "EK-2": {
        "value": "2",
        "decision": "ÇED Gerekli Değil/ÇED Olumlu",
    },
}


def get_result_table(page):
    table = (
        page.locator("table")
        .filter(
            has=page.get_by_role(
                "columnheader",
                name="Proje Adı",
                exact=True,
            )
        )
        .filter(
            has=page.get_by_role(
                "columnheader",
                name="Detay",
                exact=True,
            )
        )
    )

    if table.count() == 0:
        return None

    return table.first


def close_detail_dialog(page):
    try:
        visible_dialogs = page.locator(".ui-dialog:visible")

        if visible_dialogs.count() > 0:
            dialog = visible_dialogs.last
            close_button = dialog.locator(".ui-dialog-titlebar-close")

            if close_button.count() > 0:
                close_button.click(timeout=3000)
                page.wait_for_timeout(300)
                return

        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass


def run_search(page, province, project_type):
    if project_type not in PROJECT_CONFIG:
        raise ValueError(
            f"Geçersiz proje türü: {project_type}"
        )

    config = PROJECT_CONFIG[project_type]
    project_value = config["value"]
    decision_text = config["decision"]

    page.goto(
        BASE_URL,
        wait_until="networkidle",
        timeout=60000,
    )

    page.locator(
        '[id="form:duyuru-arama-fieldset:j_idt26"]'
    ).get_by_role("button").click()

    page.get_by_role(
        "option",
        name=province.upper(),
        exact=True,
    ).click()

    print(f"İl seçildi: {province.upper()}")

    page.locator(
        '[id="form:duyuru-arama-fieldset:j_idt28"]'
    ).get_by_role("button").click()

    page.get_by_role(
        "option",
        name="Petrol-Doğalgaz-III. ve IV.",
    ).click()

    print("Sektör seçildi.")

    page.locator(
        '[id="form:duyuru-arama-fieldset:alt-sektor"]'
    ).get_by_role("button").click()

    page.get_by_role(
        "option",
        name="IV. Grup Madenler",
        exact=True,
    ).click()

    print("Alt sektör seçildi.")

    project_type_result = page.evaluate(
        """
        (projectValue) => {
            const widget = PrimeFaces.widgets[
                "widget_form_duyuru_arama_fieldset_j_idt34"
            ];

            if (!widget) {
                throw new Error(
                    "Proje Türü PrimeFaces widget bulunamadı."
                );
            }

            widget.selectValue(projectValue);
            widget.hide();

            return {
                value: widget.getSelectedValue(),
                label: widget.getSelectedLabel()
            };
        }
        """,
        project_value,
    )

    print(
        f"Proje Türü: "
        f"{project_type_result['label']} "
        f"(VALUE={project_type_result['value']})"
    )

    page.evaluate(
        """
        () => {
            const widget = PrimeFaces.widgets[
                "widget_form_duyuru_arama_fieldset_j_idt41"
            ];

            if (!widget) {
                throw new Error(
                    "Karar Tipi PrimeFaces widget bulunamadı."
                );
            }

            widget.dynamicPanelLoad();
        }
        """
    )

    page.wait_for_function(
        """
        (decisionText) => {
            const select = document.getElementById(
                "form:duyuru-arama-fieldset:j_idt41_input"
            );

            if (!select) {
                return false;
            }

            return Array.from(select.options).some(
                option =>
                    option.text.trim() === decisionText
            );
        }
        """,
        arg=decision_text,
        timeout=15000,
    )

    decision_type_result = page.evaluate(
        """
        (decisionText) => {
            const widget = PrimeFaces.widgets[
                "widget_form_duyuru_arama_fieldset_j_idt41"
            ];

            const select = document.getElementById(
                "form:duyuru-arama-fieldset:j_idt41_input"
            );

            const option = Array.from(select.options).find(
                item => item.text.trim() === decisionText
            );

            if (!option) {
                throw new Error(
                    decisionText + " seçeneği bulunamadı."
                );
            }

            widget.selectValue(option.value);
            widget.hide();

            return {
                value: widget.getSelectedValue(),
                label: widget.getSelectedLabel()
            };
        }
        """,
        decision_text,
    )

    print(
        f"Karar Tipi: "
        f"{decision_type_result['label']} "
        f"(VALUE={decision_type_result['value']})"
    )

    page.get_by_role(
        "button",
        name=" Ara",
    ).click()

    page.wait_for_timeout(2500)

    print(
        f"Sorgu tamamlandı: "
        f"{province.upper()} | "
        f"{project_type} | "
        f"{decision_text}"
    )


def collect_current_page_reports(page):
    result_table = get_result_table(page)

    if result_table is None:
        return []

    rows = result_table.locator("tbody > tr")
    row_count = rows.count()

    reports = []

    for index in range(row_count):
        try:
            row = rows.nth(index)
            cells = row.locator("td")

            if cells.count() < 10:
                continue

            project_name = cells.nth(2).inner_text().strip()
            owner = cells.nth(3).inner_text().strip()
            district = cells.nth(1).inner_text().strip()

            detail_button = cells.nth(9).locator("button").first

            detail_button.click()
            page.wait_for_timeout(500)

            # -----------------------------
            # RAPOR / DOSYA BAĞLANTISI
            # EK-1 : ÇED Raporu
            # EK-2 : PTD Dosyası
            # -----------------------------

            report_link = page.get_by_role(
                "link",
                name=re.compile(
                    r"^(ÇED Raporu|PTD Dosyası)$",
                    re.IGNORECASE,
                ),
            ).first

            report_link.wait_for(
                state="visible",
                timeout=5000,
            )

            report_url = report_link.get_attribute(
                "href"
            )

            if report_url:
                reports.append(
                    {
                        "project_name": project_name,
                        "owner": owner,
                        "district": district,
                        "report_url": report_url,
                    }
                )

            close_detail_dialog(page)

        except Exception as exc:
            print(
                f"[UYARI] Sonuç satırı {index + 1} "
                f"okunamadı: {exc}"
            )
            close_detail_dialog(page)

    return reports


def collect_all_report_links(page):
    collected = []
    seen_keys = set()
    page_no = 1

    while True:
        result_table = get_result_table(page)

        if result_table is None:
            print(
                f"Sonuç sayfası {page_no}: "
                f"tablo bulunamadı."
            )
            break

        rows = result_table.locator(
            "tbody > tr"
        )

        visible_row_count = rows.count()

        print()
        print(
            f"Sonuç sayfası {page_no}: "
            f"ekranda {visible_row_count} satır var."
        )

        current = collect_current_page_reports(
            page
        )

        new_count = 0

        for item in current:
            # Sadece URL ile tekilleştirmiyoruz.
            # Aynı URL farklı bir proje satırında
            # bulunabilir.
            key = (
                item["project_name"],
                item["district"],
                item["report_url"],
            )

            if key in seen_keys:
                continue

            seen_keys.add(key)
            collected.append(item)
            new_count += 1

        print(
            f"Okunan rapor bağlantısı: "
            f"{len(current)}"
        )

        print(
            f"Yeni kayıt: {new_count}"
        )

        # -----------------------------
        # SONRAKİ SAYFA VAR MI?
        # -----------------------------

        next_buttons = page.locator(
            ".ui-paginator-next"
        )

        if next_buttons.count() == 0:
            break

        next_button = next_buttons.last

        classes = (
            next_button.get_attribute(
                "class"
            )
            or ""
        )

        if "ui-state-disabled" in classes:
            break

        # -----------------------------
        # MEVCUT SAYFANIN İMZASINI AL
        # -----------------------------

        old_signature = []

        for index in range(
            min(
                visible_row_count,
                10,
            )
        ):
            row = rows.nth(index)

            cells = row.locator(
                "td"
            )

            if cells.count() < 3:
                continue

            old_signature.append(
                cells.nth(2)
                .inner_text()
                .strip()
            )

        old_signature = "|".join(
            old_signature
        )

        print(
            "Sonraki sonuç sayfasına geçiliyor..."
        )

        next_button.click()

        # -----------------------------
        # GERÇEKTEN YENİ SAYFAYI BEKLE
        # -----------------------------

        page.wait_for_function(
            """
            (oldSignature) => {
                const tables = Array.from(
                    document.querySelectorAll("table")
                );

                const table = tables.find(t => {
                    const headers = Array.from(
                        t.querySelectorAll("th")
                    ).map(
                        th => th.innerText.trim()
                    );

                    return (
                        headers.includes("Proje Adı") &&
                        headers.includes("Detay")
                    );
                });

                if (!table) {
                    return false;
                }

                const rows = Array.from(
                    table.querySelectorAll(
                        "tbody > tr"
                    )
                );

                if (rows.length === 0) {
                    return false;
                }

                const signature = rows
                    .slice(0, 10)
                    .map(row => {
                        const cells =
                            row.querySelectorAll("td");

                        if (cells.length < 3) {
                            return "";
                        }

                        return cells[2]
                            .innerText
                            .trim();
                    })
                    .filter(Boolean)
                    .join("|");

                return (
                    signature &&
                    signature !== oldSignature
                );
            }
            """,
            arg=old_signature,
            timeout=15000,
        )

        # Yeni DOM'un oturması için kısa süre
        page.wait_for_timeout(
            500
        )

        page_no += 1

    print()
    print(
        f"Toplam benzersiz proje kaydı: "
        f"{len(collected)}"
    )

    return collected
def make_session_from_browser(page):
    session = requests.Session()

    for cookie in page.context.cookies():
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )

    try:
        user_agent = page.evaluate("navigator.userAgent")
    except Exception:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        )

    session.headers.update(
        {
            "User-Agent": user_agent,
        }
    )

    return session


def extract_download_items(session, report_url):
    response = session.get(
        report_url,
        timeout=(30, 60),
    )

    response.raise_for_status()

    if not response.encoding:
        response.encoding = response.apparent_encoding

    page_html = response.text

    matches = re.findall(
        r'''window\.open\(\s*['"]([^'"]+)['"]\s*\)''',
        page_html,
        flags=re.IGNORECASE,
    )

    items = []
    seen = set()

    for raw_url in matches:
        raw_url = html.unescape(raw_url)
        absolute_url = urljoin(report_url, raw_url)

        query = parse_qs(
            urlparse(absolute_url).query
        )

        names = query.get("orjinalAd", [])

        if not names:
            continue

        file_name = Path(names[0]).name

        if not file_name.lower().endswith(".pdf"):
            continue

        key = (absolute_url, file_name)

        if key in seen:
            continue

        seen.add(key)

        items.append(
            {
                "file_name": file_name,
                "download_url": absolute_url,
            }
        )

    return items


def is_valid_pdf(path):
    if not path.exists():
        return False

    if path.stat().st_size < 5:
        return False

    try:
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def download_pdf_stream(
    session,
    download_url,
    save_path,
    referer,
):
    if (
        save_path.exists()
        and is_valid_pdf(save_path)
    ):
        print(
            f"  ↳ Zaten mevcut, atlandı: "
            f"{save_path.name}"
        )
        return True

    temp_path = save_path.with_suffix(
        save_path.suffix + ".part"
    )

    if temp_path.exists():
        temp_path.unlink()

    print(
        f"  ↳ İndiriliyor: {save_path.name}"
    )

    try:
        with session.get(
            download_url,
            stream=True,
            timeout=(30, 45),
            headers={
                "Referer": referer,
            },
        ) as response:
            response.raise_for_status()

            total_size = int(
                response.headers.get(
                    "Content-Length",
                    0,
                )
                or 0
            )

            downloaded = 0

            with temp_path.open("wb") as file:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    file.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = (
                            downloaded
                            / total_size
                            * 100
                        )

                        print(
                            f"\r     "
                            f"{downloaded / 1024 / 1024:.1f} MB "
                            f"/ "
                            f"{total_size / 1024 / 1024:.1f} MB "
                            f"(%{percent:.1f})",
                            end="",
                            flush=True,
                        )
                    else:
                        print(
                            f"\r     "
                            f"{downloaded / 1024 / 1024:.1f} MB",
                            end="",
                            flush=True,
                        )

            print()

        if not is_valid_pdf(temp_path):
            print(
                f"  ✗ PDF doğrulaması başarısız: "
                f"{save_path.name}"
            )

            if temp_path.exists():
                temp_path.unlink()

            return False

        temp_path.replace(
            save_path
        )

        print(
            f"  ✓ Kaydedildi: {save_path}"
        )

        return True

    except Exception as exc:
        print(
            f"\n  ✗ İndirme hatası: "
            f"{save_path.name} | {exc}"
        )

        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

        return False


def download_project_reports(
    session,
    report,
    download_dir,
):
    report_url = report["report_url"]

    try:
        items = extract_download_items(
            session,
            report_url,
        )

    except Exception as exc:
        print(
            f"  ✗ ÇED Raporu sayfası okunamadı: {exc}"
        )
        return 0, 1

    if not items:
        print(
            "  ✗ PDF bağlantısı bulunamadı."
        )
        return 0, 1

    success = 0
    failed_items = []

    report_id = (
        urlparse(report_url)
        .path
        .rstrip("/")
        .split("/")[-1]
    )

    # -----------------------------
    # 1. TUR
    # -----------------------------

    for item in items:
        original_name = item["file_name"]

        if original_name.startswith(f"{report_id}_"):
            unique_file_name = original_name
        else:
            unique_file_name = (
                f"{report_id}_{original_name}"
            )

        save_path = (
            download_dir
            / unique_file_name
        )

        ok = download_pdf_stream(
            session=session,
            download_url=item["download_url"],
            save_path=save_path,
            referer=report_url,
        )

        if ok:
            success += 1
        else:
            failed_items.append(
                (
                    item,
                    save_path,
                )
            )

    # -----------------------------
    # 2. TUR - SADECE HATALILAR
    # -----------------------------

    if failed_items:
        print()
        print(
            f"  ↳ {len(failed_items)} dosya "
            f"başarısız oldu."
        )
        print(
            "  ↳ Başarısız dosyalar "
            "bir kez daha deneniyor..."
        )

        retry_failed = []

        for item, save_path in failed_items:
            print()
            print(
                f"  ↳ Tekrar deneniyor: "
                f"{save_path.name}"
            )

            ok = download_pdf_stream(
                session=session,
                download_url=item["download_url"],
                save_path=save_path,
                referer=report_url,
            )

            if ok:
                success += 1
            else:
                retry_failed.append(
                    (
                        item,
                        save_path,
                    )
                )

        failed_items = retry_failed

    failed = len(
        failed_items
    )

    return success, failed
def process_project_type(
    page,
    province,
    project_type,
    download_root=None,
):
    config = PROJECT_CONFIG[project_type]

    print()
    print("=" * 70)
    print(
        f"{province.upper()} | "
        f"{project_type} | "
        f"{config['decision']}"
    )
    print("=" * 70)

    run_search(
        page=page,
        province=province,
        project_type=project_type,
    )

    reports = collect_all_report_links(page)

    print()
    print(
        f"{project_type}: "
        f"Toplam {len(reports)} proje/ÇED Raporu adresi bulundu."
    )

    if not reports:
        return {
            "reports": 0,
            "downloaded": 0,
            "failed": 0,
        }

    download_dir = (
        Path(download_root) if download_root is not None else Path("downloads")
    ) / province.upper() / project_type

    download_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = make_session_from_browser(page)

    downloaded = 0
    failed = 0

    for index, report in enumerate(
        reports,
        start=1,
    ):
        print()
        print(
            f"[{index}/{len(reports)}] "
            f"{report['project_name']}"
        )

        print(
            f"  İlçe: {report['district']}"
        )

        success_count, failed_count = (
            download_project_reports(
                session=session,
                report=report,
                download_dir=download_dir,
            )
        )

        downloaded += success_count
        failed += failed_count

    print()
    print(
        f"{project_type} tamamlandı. "
        f"Başarılı/Mevcut: {downloaded} | "
        f"Hata: {failed}"
    )

    return {
        "reports": len(reports),
        "downloaded": downloaded,
        "failed": failed,
    }


def main(province="ADANA", download_root=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="msedge",
            headless=False,
        )

        context = browser.new_context()
        page = context.new_page()

        print("eMadenCBS e-ÇED toplu indirme başlatıldı.")
        print(f"İl: {province}")

        summaries = {}

        try:
            # EK-1 tamamen bitmeden EK-2 başlamaz.
            summaries["EK-1"] = process_project_type(
                page=page,
                province=province,
                project_type="EK-1",
                download_root=download_root,
            )

            print()
            print(
                "EK-1 tamamlandı. "
                "Şimdi EK-2 sorgusuna geçiliyor."
            )

            summaries["EK-2"] = process_project_type(
                page=page,
                province=province,
                project_type="EK-2",
                download_root=download_root,
            )

        finally:
            context.close()
            browser.close()

        print()
        print("=" * 70)
        print(f"{province} TAMAMLANDI")
        print("=" * 70)

        for project_type, summary in summaries.items():
            print(
                f"{project_type}: "
                f"{summary['reports']} proje | "
                f"{summary['downloaded']} başarılı/mevcut | "
                f"{summary['failed']} hata"
            )

        return summaries


if __name__ == "__main__":
    main()
