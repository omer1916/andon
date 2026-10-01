# Claude Code araçları

Bu projede Claude Code ile çalışırken kullanılan güvenlik ve tasarım araçları. Her araç kaynak
kodu okunarak seçildi; listede olup eklenmeyenler ve nedenleri en altta.

## Repoda olanlar: skill'ler (`.claude/skills/`)

Skill'ler düz Markdown talimatlarıdır; repoyu açan her Claude Code oturumu (bulut dahil) onları
kurulum yapmadan görür. Değiştirilmeden, aşağıdaki commit'lerden kopyalandı. Her klasörde kendi
lisans dosyası var.

| Skill'ler | Kaynak | Lisans | Ne için |
|---|---|---|---|
| `penetration-testing-with-strix`, `web-app-penetration-testing`, `api-security-testing`, `find-security-vulnerabilities-in-code`, `fix-security-vulnerabilities-with-strix`, `owasp-top-10-testing`, `application-security-testing`, `ci-security-scanning-with-strix`, `managed-pentesting-with-strix` | [usestrix/strix](https://github.com/usestrix/strix) `007ed1a` | Apache-2.0 | Strix'i çalıştırmak, bulguları düzeltmek, düzeltmeyi yeniden taramayla doğrulamak |
| `emil-design-eng`, `animate`, `review-animations`, `improve-animations`, `find-animation-opportunities`, `animation-vocabulary`, `apple-design`, `mobile-native` | [emilkowalski/skills](https://github.com/emilkowalski/skills) `d16ebe6` | MIT | Arayüz detayı, animasyon kararları, telefonda/tablette uygulama hissi |
| `redesign-existing-projects` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) `ce26fc2` | MIT | Var olan arayüzü "yapay zekâ yapmış gibi" görünen kalıplara karşı denetleme |

Emil Kowalski'nin React, React Native ve Swift'e özel skill'leri (`animate-expo`, `ask-sonner`,
`pick-ui-library`, `write-swift`, `prototype`) alınmadı; arayüz vanilla JavaScript. Taste
Skill'in diğer 12 skill'i açılış sayfası, React/Tailwind veya görsel üretimi üzerine.

## Plugin'ler (`.claude/settings.json`)

Plugin'ler hook ve MCP sunucusu çalıştırabildiği için bu dosyayı Claude kendi başına yazmadı;
aşağıdaki komutlar proje kökünde bir kez çalıştırılınca dosyayı oluşturur. Sonra commit'lenir
ve repoyu açan herkes aynı plugin'leri görür.

```bash
claude plugin marketplace add anthropics/claude-plugins-official --scope project
claude plugin marketplace add "pbakaus/impeccable#skill-v4.4.0" --scope project
claude plugin marketplace add "nextlevelbuilder/ui-ux-pro-max-skill#v2.15.0" --scope project

claude plugin install security-guidance@claude-plugins-official --scope project
claude plugin install claude-code-setup@claude-plugins-official --scope project
claude plugin install context7@claude-plugins-official --scope project
claude plugin install playwright@claude-plugins-official --scope project
claude plugin install frontend-design@claude-plugins-official --scope project
claude plugin install impeccable@impeccable --scope project
claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill --scope project
```

| Plugin | Kimden | Ne yapar | Dikkat |
|---|---|---|---|
| `security-guidance` | Anthropic | Düzenlemede tehlikeli kalıp uyarısı (`innerHTML`, `pickle.load`, gömülü anahtar...), tur sonunda diff'in LLM ile güvenlik incelemesi, commit'te dosyalar arası veri akışını izleyen inceleme | Her tur sonunda ve commit'te bir LLM çağrısı yapar (kullanım harcar). Kapatmak için `SECURITY_GUIDANCE_DISABLE=1` |
| `claude-code-setup` | Anthropic | Kod tabanını tarayıp işe yarayacak hook, skill, subagent ve MCP sunucusu önerir. Salt okur | |
| `context7` | Upstash | FastAPI, psycopg, pgvector gibi kütüphanelerin güncel belgelerini getirir | Belgeler topluluk katkılı; ilk kullanımda Context7 girişi ister |
| `playwright` | Microsoft | Claude tarayıcı açıp arayüzü kullanır, ekran görüntüsü alır, formu doldurur | |
| `frontend-design` | Anthropic | Sıradan şablon görünümünden kaçınan arayüz tasarımı | |
| `impeccable` | Paul Bakaus | `/impeccable` ile 24 komut (`audit`, `critique`, `polish`, `harden`...) ve 61 kurallı "yapay zekâ kokan tasarım" dedektörü | Hook'ları her düzenlemede çalışan bir ikili dosya kullanır; dosya GitHub sürümünden SHA-256 doğrulanarak indirilir |
| `ui-ux-pro-max` | NextLevelBuilder | Yerel, aranabilir tasarım veritabanı: 192 renk paleti, 74 yazı tipi eşleşmesi, 119 UX kuralı (Python, bağımlılıksız) | Yanında banner, sunum ve marka skill'leri de gelir |

Üçüncü taraf iki marketplace bir sürüm etiketine sabitlendi: yeni sürümler incelenmeden
gelmez. Güncellemek için etiket değiştirilir.

Tasarım skill'leri hızlı görünüm için CDN'den yazı tipi veya kütüphane eklemeyi önerebilir.
Bu projede arayüzün dış bağımlılığı yok ve fabrika ağında internet olmayabilir; öneriler bu
kurala göre uygulanmalı.

## GitHub tarafı

- **CodeQL** (`.github/workflows/codeql.yml`): Python, JavaScript ve iş akışı dosyalarını her
  PR'da ve haftada bir `security-extended` sorgularıyla tarar. Bulgular Security sekmesine
  düşer. Repo ayarlarında CodeQL "default setup" açıksa bu iş akışı yükleme yapamaz; ikisinden
  biri seçilmeli.
- **Dependabot** (`.github/dependabot.yml`): pip, GitHub Actions, Dockerfile ve docker-compose
  imajları için ayda bir, ekosistem başına tek PR. Güvenlik açığı uyarıları ve otomatik
  güvenlik PR'ları için repo ayarlarında Settings → Code security altında "Dependabot alerts"
  ve "Dependabot security updates" açılmalı. Gizli anahtar taraması için aynı yerde "Secret
  scanning" ve "Push protection" açılabilir (açık repolarda ücretsiz).

## Strix ile andon'u taramak

Strix, uygulamaya gerçekten saldırıp yalnızca çalışan bir saldırı örneğiyle (PoC) kanıtladığı
açıkları raporlar. Yalnızca sahibi olunan sistemlere karşı çalıştırılmalı. Docker ve bir LLM
anahtarı gerekir. Windows'ta aşağıdaki komutlar Git Bash'te çalışır.

```bash
pipx install strix-agent                       # Python 3.12+
export STRIX_LLM="gemini/gemini-3.8-flash"     # LiteLLM model adı; Anthropic/OpenAI da olur
export LLM_API_KEY="$GEMINI_API_KEY"
export STRIX_TELEMETRY=0                       # varsayılan olarak kullanım verisi gönderir

docker compose up -d --build                   # uygulama: http://localhost:8000

# Strix hedef klasörü yazılabilir bağlar; çalışma kopyası yerine temiz bir kopya ver.
git worktree add ../andon-strix HEAD
strix -n -t ../andon-strix -t http://host.docker.internal:8000 \
  --scan-mode standard --max-budget 5 --instruction-file docs/strix-talimat.md
```

[`docs/strix-talimat.md`](strix-talimat.md) Strix'e kullanıcıları, rolleri ve öncelikli
soruları (operatörün bakım kılavuzuna ulaşması, JWT, agent araçlarında SQL injection,
istenmeden bakım talebi açtırma, XSS) anlatır. Sonuçlar `strix_runs/<çalıştırma>/` altına
yazılır (`.gitignore`'da; içinde çalışan saldırı örnekleri var). Rapor okunduktan sonra
Claude'a "Strix bulgularını düzelt" demek `fix-security-vulnerabilities-with-strix`
skill'ini çalıştırır: kök nedeni düzeltir, sonra aynı açığı yeniden tarayarak kapandığını
doğrular.

Ücretsiz Gemini katmanının dakika başına istek sınırı uzun taramaları yavaşlatır.
`--max-budget` dolarsa tarama erken biter ve yine `0` ile çıkar; `run.json`'daki durum ve
maliyet kontrol edilmeli.

## Bütün projelerde kullanmak için

Yukarıdakiler yalnızca bu repoda geçerli. Aynı araçları bilgisayardaki her projede açmak için
komutlar `--scope project` yerine `--scope user` ile (ya da hiç `--scope` vermeden)
çalıştırılır. Skill'ler için:

```bash
npx skills add usestrix/strix
npx skills@latest add emilkowalski/skills
```

## Eklenmeyenler

| Araç | Neden |
|---|---|
| OmniRoute | Claude aboneliğini başka bir uygulamaya bağlamak Anthropic'in kullanım koşullarına aykırı; projenin issue'larında bağlandıktan dakikalar sonra kapatılan Claude Max hesapları bildirilmiş |
| Agent Reach | LinkedIn, Instagram ve X'i kullanıcının oturum çerezleriyle kazır. Bu sitelerin kullanım koşullarına aykırı; README'si hesap kapatılma riskine karşı yan hesap öneriyor. Kişisel veri toplamak KVKK sorunu da doğurur |
| Supabase plugin'i | Andon kendi PostgreSQL + pgvector'ünü kullanıyor; Supabase yok |
| Figma MCP | Projede Figma dosyası yok. Gerçek kullanım için ücretli Dev/Full koltuk gerekiyor (ücretsiz koltukta ayda 6 araç çağrısı) |
| 21st.dev (Magic / 21st MCP) | React + Tailwind bileşenleri üretir ve API anahtarı ister; arayüz vanilla JavaScript |
| Skill UI | ~240 yıldızlı küçük bir proje, Nisan 2026'dan beri güncellenmemiş ve repoda lisans dosyası yok. Başka bir markanın tasarım sistemini kopyalamak telif ve ticari takdim sorunu doğurabilir |
| Find Skills | Kendisi zararsız, ama incelenmemiş üçüncü taraf skill'leri kurar. Snyk'in yaklaşık 4.000 skill üzerindeki ToxicSkills incelemesinde 76'sı kötü amaçlı çıktı. Skill, kurulmadan önce okunmalı |
| Taste Skill'in tamamı | Ana skill açılış sayfası ve React/Tailwind odaklı, diğerleri görsel üretimi üzerine; vanilla CSS ile çalışan `redesign-existing-projects` alındı |
