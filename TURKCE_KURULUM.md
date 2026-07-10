# SignalDesk Türkçe kurulum ve TikTok anahtar rehberi

Bu rehber TikTok geliştirici uygulamasını, Client Key/Client Secret değerlerini ve kullanıcı Access Token/Refresh Token belirteçlerini resmî OAuth 2.0 akışıyla almayı anlatır.

> Önemli: Client Secret, Access Token ve Refresh Token parola kadar hassastır. Ekran görüntüsünde, e-postada, GitHub deposunda veya `.env` dosyasını Git'e ekleyerek paylaşmayın.

## 1. TikTok geliştirici hesabı açın

1. https://developers.tiktok.com/ adresine gidin.
2. Sağ üstten giriş yapın ve geliştirici hesabı kaydını tamamlayın.
3. Profil menüsünden **Manage apps** bölümünü açın.
4. **Connect an app** veya **Create app** seçeneğiyle yeni uygulama oluşturun.
5. Uygulama adı, açıklaması, şirket bilgileri, gizlilik politikası ve kullanım koşulları adreslerini gerçek bilgilerle doldurun.

Ajans müşterilerinin hesaplarını bağlayacaksanız her hesap sahibi OAuth izin ekranında kendisi onay vermelidir. Bir hesaptan alınan belirteci başka hesaba taşımayın.

## 2. Gerekli ürünleri ekleyin

Uygulamanın ürünler bölümünde şunları etkinleştirin:

1. **Login Kit**: Kullanıcının kendi TikTok hesabıyla giriş yapması ve izin vermesi için.
2. **Content Posting API**: Videoyu resmî API ile yüklemek/yayınlamak için.
3. Direct Post kullanacaksanız Content Posting API yapılandırmasında **Direct Post** erişimini seçin.

İzin kapsamları:

- `user.info.basic`: Bağlanan kullanıcının temel hesap bilgisini okumak için.
- `video.publish`: Direct Post ile doğrudan video göndermek için.
- Yalnızca TikTok gelen kutusuna taslak yükleme akışı kullanılırsa `video.upload` gerekebilir. Bu proje Direct Post kullandığı için ana kapsam `video.publish` değeridir.

TikTok incelemesinden geçmemiş istemcilerle gönderilen içerikler özel görünürlükle sınırlandırılabilir. Herkese açık üretim yayını için uygulama incelemesini tamamlayın.

## 3. Desktop Redirect URI ekleyin

Login Kit yapılandırmasında masaüstü yönlendirme adresi olarak tam şu değeri ekleyin:

```text
http://127.0.0.1:3455/callback/
```

TikTok panelindeki değer ile uygulamanın kullandığı değer karakter karakter aynı olmalıdır. Sondaki `/` işareti dahil. Farklı port kullanacaksanız hem panelde hem `TIKTOK_REDIRECT_URI` değişkeninde aynı değeri kullanın.

TikTok masaüstü Login Kit belgeleri localhost ve loopback yönlendirmelerini destekler. Üretim web uygulamalarında HTTPS ve kayıtlı alan adı kuralları farklıdır.

## 4. Client Key ve Client Secret alın

1. TikTok geliştirici panelinde **Manage apps** bölümünü açın.
2. Oluşturduğunuz uygulamayı seçin.
3. Uygulamanın temel bilgiler/credentials bölümünde **Client key** ve **Client secret** alanlarını bulun.
4. Client Secret gizliyse **Show** veya kopyalama düğmesini kullanın.
5. Bu iki değeri kaynak koduna yazmayın. İşletim sistemi ortam değişkeni olarak tanımlayın.

Client Key uygulamayı tanımlar. Client Secret uygulamanın gizli parolasıdır. Bunlar kullanıcı Access Token'ı değildir.

### Windows PowerShell, geçici oturum

```powershell
$env:TIKTOK_CLIENT_KEY="paneldeki-client-key"
$env:TIKTOK_CLIENT_SECRET="paneldeki-client-secret"
$env:TIKTOK_REDIRECT_URI="http://127.0.0.1:3455/callback/"
```

Kalıcı kullanıcı değişkeni isterseniz:

```powershell
[Environment]::SetEnvironmentVariable("TIKTOK_CLIENT_KEY", "paneldeki-client-key", "User")
[Environment]::SetEnvironmentVariable("TIKTOK_CLIENT_SECRET", "paneldeki-client-secret", "User")
[Environment]::SetEnvironmentVariable("TIKTOK_REDIRECT_URI", "http://127.0.0.1:3455/callback/", "User")
```

Yeni PowerShell penceresi açmadan kalıcı değişkenler mevcut oturuma gelmez.

### macOS veya Linux, geçici oturum

```bash
export TIKTOK_CLIENT_KEY="paneldeki-client-key"
export TIKTOK_CLIENT_SECRET="paneldeki-client-secret"
export TIKTOK_REDIRECT_URI="http://127.0.0.1:3455/callback/"
```

Kalıcı kullanım için satırları `~/.zshrc` veya `~/.bashrc` dosyanıza ekleyip yeni terminal açabilirsiniz. Ortak bilgisayarda bunu yapmayın.

## 5. Access Token ve Refresh Token alın

Depodaki `oauth_helper.py`, TikTok Desktop Login Kit için PKCE kullanır. Rastgele `state`, `code_verifier` ve SHA-256 `code_challenge` oluşturur, tarayıcıyı açar, localhost callback'ini dinler ve yetkilendirme kodunu resmî token uç noktasında değiştirir.

Önce bağımlılıkları kurun:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
python oauth_helper.py
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python oauth_helper.py
```

Sonra:

1. Tarayıcıda doğru TikTok hesabıyla giriş yapın.
2. İstenen `user.info.basic` ve `video.publish` izinlerini kontrol edin.
3. İzin verin.
4. Tarayıcı callback sayfası açıldığında terminale dönün.
5. Terminalde gösterilen **Erişim belirteci** ve **Yenileme belirteci** değerlerini kopyalayın.
6. SignalDesk içinde **Profil Yönetimi** sekmesine girin.
7. Profil adı, Access Token ve Refresh Token alanlarını doldurup **Profil ekle** düğmesine basın.

SignalDesk belirteçleri işletim sisteminin güvenli kimlik kasasına yazar. `pipeline_registry.json` içinde belirteç tutulmaz.

## 6. Türkçe arayüzü çalıştırın

```bash
python app_tr.py
```

İngilizce çekirdek sürüm hâlâ `python app.py` ile açılabilir. Türkçe arayüz aynı çekirdeği ve aynı `pipeline_registry.json` verisini kullanır.

## 7. Uygulama incelemesi ve üretim yayını

Geliştirme testleri tamamlandığında TikTok geliştirici panelinden uygulama incelemesine başvurun. Genellikle şunlar gerekir:

- Uygulamanın gerçek amacı ve kullanıcı akışının açıklaması
- Login Kit ve Content Posting API kullanımını gösteren ekran kaydı
- İzinlerin neden gerektiğinin açıklaması
- Gizlilik politikası ve kullanım koşulları
- İçeriğin kullanıcının bilgisi/onayıyla gönderildiğini gösteren yayın ekranı
- İçerik görünürlüğü, yorum, duet ve stitch seçeneklerinin TikTok UX kurallarına uygun gösterimi
- Doğrulanmış alan adı veya uygulama bilgileri

İnceleme tamamlanmadan gönderiler `SELF_ONLY` ile sınırlandırılabilir. Bunu kodla aşmaya çalışmayın.

## 8. Sık görülen hatalar

### `redirect_uri` hatası

TikTok panelindeki Redirect URI ile ortam değişkeni aynı değil. Protokol, IP, port, yol ve sondaki `/` dahil eşleştirin.

### `invalid_client`

Client Key veya Client Secret yanlış, başka uygulamaya ait ya da başında/sonunda boşluk var. Değerleri yeniden kopyalayın.

### `scope_not_authorized` veya izin hatası

Login Kit/Content Posting API ürünü eklenmemiş, `video.publish` onaylanmamış veya uygulama incelemesi eksik olabilir. Geliştirici panelindeki ürün ve kapsam durumlarını kontrol edin.

### Token yenilenemiyor

SignalDesk'i açtığınız terminalde `TIKTOK_CLIENT_KEY` ve `TIKTOK_CLIENT_SECRET` bulunmalıdır. Kalıcı değişken eklediyseniz yeni terminal açın.

### Port 3455 kullanımda

Başka uygulamayı kapatın veya panelde yeni Redirect URI tanımlayıp aynı değeri ortam değişkenine yazın:

```powershell
$env:TIKTOK_REDIRECT_URI="http://127.0.0.1:4567/callback/"
```

### Gönderi yalnızca bana görünür

Bu genellikle TikTok'un denetlenmemiş istemci kısıtıdır. Uygulama incelemesini tamamlayın. SignalDesk creator info sonucuna uyar ve desteklenmeyen görünürlüğü zorlamaz.

## Resmî belgeler

- Desktop Login Kit: https://developers.tiktok.com/doc/login-kit-desktop/
- OAuth kullanıcı belirteçleri: https://developers.tiktok.com/doc/oauth-user-access-token-management
- Content Posting API başlangıç: https://developers.tiktok.com/doc/content-posting-api-get-started
- Direct Post referansı: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- Medya/chunk aktarımı: https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
