# Otomatik Yayınla ile düşürülmüş riskli web modu

## Araştırma özeti

Tam otomatik web yayınında sıfır tespit riski yoktur. Playwright Chrome'u CDP üzerinden yönetir ve bu kontrol kanalı teknik olarak gözlemlenebilir. Mevcut Chrome'a bağlanmak, uzantı kullanmak veya işletim sistemi seviyesinde tıklamak bunu güvenilir şekilde ortadan kaldırmaz; yalnız tespit yüzeyini başka yere taşır. Resmî, tam otomatik seçenek TikTok Content Posting API'dir, fakat denetlenmemiş API istemcilerinin gönderileri TikTok tarafından private görünürlüğe kısıtlanır.

## Seçilen denge

İstenen işleyiş gereği son **Yayınla** tıklaması otomatik kalır. Risk şu şekilde azaltılır:

- Session cookie Chrome'a enjekte edilmez.
- Kullanıcı TikTok'a normal, görünür Chrome profilinde giriş yapar.
- Stealth, fingerprint, WebDriver gizleme veya anti-bot bypass yaması kullanılmaz.
- Caption yazımında `dispatchEvent(new InputEvent(...))` gibi açıkça sentetik JavaScript olayları kaldırılır.
- Playwright'ın standart klavye ve tıklama aksiyonları kullanılır.
- Uygulamadaki açık son onaydan sonra mevcut otomatik Publish tıklaması çalışır.
- Hesaplar paralel değil sırayla işlenir; profil wrapperları her hesap sonunda geri yüklenir.
- TikTok telif/içerik kontrolü tamamlanmamışsa yayın fail-closed durur.

## Neden uzantı veya OS tıklaması seçilmedi

Chrome eklentisindeki `element.click()` olayı `isTrusted=false` üretir. Debugger tabanlı eklenti veya OS otomasyonu ise otomasyonu gizlemeye çalışır, kırılgandır ve hesap güvenliği riskini büyütür. Mevcut Chrome'a CDP ile bağlanmak da CDP tespit yüzeyini kaldırmaz.

## Gerçekçi sınır

Bu sürüm önceki koda göre daha temiz ve daha az riskli bir otomasyon yüzeyi sağlar, ancak tespit edilmezlik veya izlenme garantisi vermez. Kesin düşük risk gerekiyorsa iki gerçek seçenek vardır: son tıklamayı kullanıcıya bırakmak veya TikTok denetiminden geçmiş resmî Content Posting API istemcisi kullanmak.
