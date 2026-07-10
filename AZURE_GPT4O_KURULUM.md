# Azure GPT-4o caption kurulumu

Uygulama caption üretimi için yalnızca Azure GPT-4o kullanır. API Ayarları ekranındaki **Azure GPT-4o API Key** alanına yenilenmiş anahtarı girin; anahtar işletim sistemi kasasında saklanır ve Azure'a `api-key` başlığıyla gönderilir.

Varsayılan deployment URL'si hazırdır. Farklı deployment gerekiyorsa:

```powershell
$env:AZURE_GPT4O_API_URL="https://RESOURCE.cognitiveservices.azure.com/openai/deployments/DEPLOYMENT/chat/completions?api-version=2025-01-01-preview"
python app_tr.py
```

Eski sağlayıcı adları yalnızca geriye dönük kayıt uyumluluğu için iç değişkenlerde kalabilir; ağ isteği hiçbir zaman bu sağlayıcılara gönderilmez.
