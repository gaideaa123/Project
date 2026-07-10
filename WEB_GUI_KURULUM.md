# app_tr.py Web Yayını

## Kurulum

```powershell
pip install -r requirements.txt
playwright install chromium
python app_tr.py
```

Google Chrome kuruluysa araç önce normal Chrome kanalını kullanır; yoksa Playwright Chromium'a düşer.

## GUI akışı

1. **Web Yayını** sekmesini açın.
2. Her TikTok hesabı için farklı bir tarayıcı profil adı yazın. Aynı ad, aynı yerel oturumu açar.
3. Numaralı videoyu ve captionu seçin.
4. **Tarayıcıyı Aç ve Yayını Hazırla** düğmesine basın.
5. İlk kullanımda TikTok girişini, CAPTCHA'yı ve 2FA'yı görünür tarayıcıda tamamlayın.
6. Araç videoyu yükler, captionu doldurur ve TikTok'un yayın düğmesini hazır etmesini bekler.
7. Tarayıcıda hesap, önizleme, görünürlük, yorum, Duet ve Stitch ayarlarını kontrol edin.
8. GUI'deki kontrol kutusunu işaretleyin.
9. **Onayla ve Yayınla** düğmesine basın. Araç yalnız bu açık onaydan sonra tarayıcıdaki Yayınla düğmesini tıklar.

## Güvenlik ve hata tanısı

Araç CAPTCHA veya 2FA'yı atlamaz, şifre okumaz, cookie dışa aktarmaz ve headless çalışmaz. Her hesap için kalıcı tarayıcı verisi yerel uygulama klasöründe ayrı tutulur.

Hata halinde ekran görüntüsü, HTML ve hata özeti şuraya yazılır:

```text
%LOCALAPPDATA%\SignalDesk\signaldesk-web-uploader\diagnostics
```

Bu klasör oturumla ilişkili sayfa içeriği barındırabilir; paylaşmadan önce kontrol edin ve repoya commit etmeyin.
