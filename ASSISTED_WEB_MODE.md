# Session ID bootstrap ve otomatik web yayını

## Araştırma sonucu

Session ID'yi her çalıştırmada zorla yeniden enjekte etmek, kalıcı Chrome profilinin TikTok tarafından oluşturulan daha geniş birinci taraf oturum durumunu sürekli ezme riski taşır. Daha dengeli yöntem, Session ID'yi yalnız boş profile giriş bootstrap'ı olarak kullanmak ve sonraki çalışmalarda Chrome profilinin kendi cookie/local storage/cache sürekliliğini korumaktır.

## Yeni davranış

1. Her hesap yine ayrı kalıcı Chrome profilinde açılır.
2. Profilde geçerli `sessionid` veya `sessionid_ss` zaten varsa kayıtlı Session ID yeniden enjekte edilmez.
3. Profil boşsa güvenli kasadaki Session ID bir kez `.tiktok.com` cookie'si olarak eklenir.
4. İlk TikTok navigasyonu CSRF, cihaz ve diğer birinci taraf durumunu normal biçimde oluşturur.
5. TikTok sessionı reddeder veya ek doğrulama isterse Chrome öne gelir ve kullanıcı normal girişi tamamlar.
6. Video/caption hazırlanır, uygulamadaki açık onaydan sonra **Yayınla** otomatik tıklanır.
7. Sonraki çalıştırma aynı kalıcı profil durumunu kullanır.

Caption yazımında JavaScript `dispatchEvent` kaldırılmıştır; standart Playwright klavye aksiyonları kullanılır. Stealth, fingerprint veya WebDriver gizleme yaması yoktur.

## Neden bu çözüm

Playwright dokümantasyonu kimlik doğrulama durumunun saklanıp yeniden kullanılmasını destekler ve bu durumun hassas olduğunu açıkça belirtir. TikTok da session ID'nin tarayıcı/cihazla kurulan güvenlik durumunun parçası olduğunu söyler. Bu nedenle sürekli cookie transplantı yerine bir kez bootstrap + kalıcı profil sürekliliği daha az bozucudur.

## Sınır

Bu yöntem Session ID isteğini ve otomatik final tıklamayı korurken gereksiz yeniden enjeksiyonu kaldırır. Playwright/CDP hâlâ teknik olarak tespit edilebilir; izlenme veya tespit edilmeme garantisi verilemez.
