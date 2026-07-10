# SignalDesk Tek Tık Yayıncı

Bu ekran, seçilen videodan belirlenen sayıda standart yaratıcı varyant üretir, her varyant için Grok ile Türkçe caption yazar ve videoları aynı TikTok profiline tam 23 saat arayla kuyruğa ekler.

## Güvenlik

API anahtarlarını kaynak koda yazmayın. Grok anahtarı uygulama alanına bir kez girilir ve işletim sisteminin güvenli anahtar kasasında saklanır. Sohbet, ekran görüntüsü veya commit içinde paylaşılmış bir anahtarı iptal edip yenisini üretin.

## Hazırlık

1. Ana uygulamayı kurun ve `python app_tr.py` ile TikTok profilinizi OAuth üzerinden bağlayın.
2. FFmpeg ve FFprobe'un PATH üzerinde olduğunu doğrulayın: `ffmpeg -version` ve `ffprobe -version`.
3. Bağımlılıkları kurun: `pip install -r requirements.txt`.
4. Tek tık ekranını başlatın: `python run_one_click.py`.

## Kullanım

Video seçin, varyant sayısını ve TikTok profilini belirleyin, içerik konusunu bir cümleyle yazın ve **TEK TIKLA ÜRET VE KUYRUĞA AL** düğmesine basın. İlk video yaklaşık iki dakika sonrasına, kalanlar sırayla 23 saat arayla planlanır.

Varsayılan gizlilik `SELF_ONLY` değeridir. Herkese açık Direct Post, TikTok uygulama incelemesi ve uygun izinler olmadan çalışmaz. Varyant üretimi yaratıcı düzenleme içindir; platform denetimlerini atlatmak, spam veya izinsiz içerik çoğaltmak için tasarlanmamıştır.

Grok modeli ortam değişkeniyle değiştirilebilir:

```powershell
$env:GROK_MODEL="grok-3-mini"
python run_one_click.py
```
