# Kullanıcı destekli Playwright testi

Bu runner görünür ve normal bir Chromium oturumu açar. Fingerprint taklidi,
automation flag gizleme, CAPTCHA atlatma veya platform kontrolü bastırma yapmaz.

## Kurulum

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Kullanım

TikTok Creator Center yükleme sayfasını açmak için:

```bash
python user_assisted_playwright.py
```

Farklı bir test sayfası açmak için:

```bash
python user_assisted_playwright.py --url https://example.com/upload
```

Yetkili bir test sayfasında metin yazıp bir elementi tıklamak için:

```bash
python user_assisted_playwright.py \
  --url https://example.com/upload \
  --text-selector '#caption' \
  --text 'Test gönderisi' \
  --click-selector '#continue'
```

Giriş veya doğrulama çıkarsa tarayıcıda elle tamamlayın. `--headless` sadece
arayüz gerektirmeyen test ortamları içindir; `--no-wait` sayfa hazır olduktan
sonra Enter beklemeden oturumu kapatır.

## Test

```bash
python -m py_compile user_assisted_playwright.py
python -m unittest -v test_user_assisted_playwright.py
```
