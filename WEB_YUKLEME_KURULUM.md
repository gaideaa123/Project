# TikTok Studio web yükleme yardımcısı

Bu geçici araç görünür Chrome açar, kullanıcı oturumunu ayrı bir yerel profilde saklar, videoyu seçer ve captionu doldurur. CAPTCHA, 2FA, giriş veya son **Yayınla** onayını atlatmaz. TikTok arayüzü değişirse tanı ekran görüntüsü ve HTML kaydeder.

## Kurulum

```powershell
pip install -r requirements.txt
playwright install chrome
```

Chrome kanalı bulunamazsa bilgisayara Google Chrome kurun.

## Kullanım

Captionu UTF-8 dosyasına koyun:

```powershell
python web_uploader.py --profile hesap1 --video "C:\Users\ahmet\Music\cikti\1.mp4" --caption-file "C:\Users\ahmet\Music\cikti\1.txt"
```

İlk çalıştırmada açılan Chrome penceresinde TikTok hesabına kendiniz giriş yapın. Sonraki çalıştırmalarda aynı `--profile` adı aynı oturumu kullanır. Her TikTok hesabına ayrı profil adı verin.

Araç video ile captionu hazırlar ve yayın düğmesi etkinleşene kadar bekler. Privacy, yorum, Duet, Stitch ve içerik önizlemesini kontrol edip son **Yayınla** tıklamasını siz yapın.

## Neden tam otomatik değil?

Audit kısıtını veya TikTok güvenlik kontrollerini tarayıcı botuyla aşmaya çalışmak hesabı riske atar ve kırılgandır. Kullanıcı onaylı akış daha güvenli, gözlemlenebilir ve TikTok sayfa değişikliklerine karşı teşhis edilebilir.

## Hata tanısı

Hata olursa kayıtlar şu klasöre yazılır:

```text
%LOCALAPPDATA%\SignalDesk\signaldesk-web-uploader\diagnostics
```

`page.png`, `page.html` ve `error.json` dosyalarını kullanarak arayüz değişikliği bulunabilir. Tarayıcı oturum klasörlerini veya bu tanı dosyalarını repoya yüklemeyin; oturum bilgisi içerebilirler.
