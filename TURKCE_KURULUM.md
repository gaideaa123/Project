# SignalDesk Türkçe kurulum ve anahtar rehberi

## Hızlı başlangıç

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app_tr.py
```

Artık anahtarları PowerShell'e yazmanız gerekmiyor. Uygulamadaki **API Ayarları** sekmesine Client Key, Client Secret, Redirect URI ve OAuth kapsamlarını girip **Ayarları güvenli kasaya kaydet** düğmesine basın. Access Token ve Refresh Token her TikTok hesabına özel olduğu için **Profil Yönetimi** sekmesinden girilir.

## TikTok tarafında hazırlanacaklar

1. https://developers.tiktok.com/ adresine girip geliştirici hesabını tamamlayın.
2. Profil menüsünden **Manage apps** bölümünü açın ve uygulamanızı oluşturun.
3. Uygulamaya **Login Kit** ve **Content Posting API** ürünlerini ekleyin.
4. Direct Post için `video.publish`, temel profil bilgisi için `user.info.basic` kapsamını talep edin.
5. Login Kit masaüstü Redirect URI alanına tam olarak şunu ekleyin:

```text
http://127.0.0.1:3455/callback/
```

6. Uygulamanın credentials bölümündeki **Client key** ve **Client secret** değerlerini SignalDesk'in **API Ayarları** sekmesine girin.
7. **Profil belirteçlerini al** düğmesine basın. Açılan terminal ve tarayıcı akışında doğru TikTok hesabıyla izin verin.
8. Terminalde üretilen **Access Token** ve **Refresh Token** değerlerini kopyalayıp SignalDesk **Profil Yönetimi** sekmesinden ilgili profile kaydedin.

Client Key uygulamayı tanımlar. Client Secret uygulamanın gizli parolasıdır. Access Token ve Refresh Token ise izin veren TikTok kullanıcısına aittir. Bunları GitHub'a, ekran görüntüsüne veya mesaja koymayın.

## Güvenli saklama

Client Secret ile tüm kullanıcı belirteçleri `keyring` üzerinden Windows Kimlik Bilgisi Yöneticisi, macOS Keychain veya Linux Secret Service içinde saklanır. `pipeline_registry.json` dosyasında gizli anahtar bulunmaz.

## Önemli TikTok kuralları

TikTok incelemesinden geçmemiş istemcilerde gönderiler `SELF_ONLY` görünürlüğüyle sınırlandırılabilir. Herkese açık üretim yayını için uygulama incelemesini tamamlayın. SignalDesk creator-info cevabına uyar ve desteklenmeyen görünürlük değerini zorlamaz.

## Sorun giderme

`redirect_uri` hatasında panel ve GUI içindeki adresi protokol, IP, port, yol ve sondaki `/` dahil aynı yapın. `invalid_client` hatasında Client Key/Secret değerlerini yeniden kopyalayın. İzin hatasında Login Kit, Content Posting API ve `video.publish` durumunu kontrol edin. Port 3455 doluysa kullanan uygulamayı kapatın veya hem TikTok panelinde hem GUI'de aynı yeni portu tanımlayın.

## Resmî belgeler

- https://developers.tiktok.com/doc/login-kit-desktop/
- https://developers.tiktok.com/doc/oauth-user-access-token-management
- https://developers.tiktok.com/doc/content-posting-api-get-started
- https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
