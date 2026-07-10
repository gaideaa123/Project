# Azure GPT-4o caption kurulumu

Uygulamadaki caption API alanına Azure GPT-4o anahtarını girin. İstekler Azure deployment adresine `api-key` başlığıyla gönderilir; anahtar kaynak koda yazılmaz.

Varsayılan deployment URL'si uygulamada tanımlıdır. Farklı deployment kullanmak için PowerShell'de:

```powershell
$env:AZURE_GPT4O_API_URL="https://RESOURCE.cognitiveservices.azure.com/openai/deployments/DEPLOYMENT/chat/completions?api-version=2025-01-01-preview"
python app_tr.py
```

Azure yanıt gövdesi OpenAI chat-completions biçiminde işlendiği için mevcut caption doğrulaması ve tekrar engelleme aynen çalışır.

Sohbette, ekranda veya repoda açık paylaşılmış API anahtarını Azure portalından iptal edip yenisini oluşturun.
