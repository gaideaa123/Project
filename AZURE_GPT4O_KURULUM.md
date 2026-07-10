# Azure GPT-4o caption kurulumu

Caption API alanına Azure GPT-4o anahtarını girin. Uygulama anahtarı işletim sistemi kasasında tutar ve Azure'a `api-key` başlığıyla gönderir.

Varsayılan deployment URL'si hazırdır. Farklı deployment gerekiyorsa:

```powershell
$env:AZURE_GPT4O_API_URL="https://RESOURCE.cognitiveservices.azure.com/openai/deployments/DEPLOYMENT/chat/completions?api-version=2025-01-01-preview"
python app_tr.py
```

Sohbette veya repoda açık paylaşılmış anahtar iptal edilip yenilenmelidir.
