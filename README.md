# Andon

Fabrika verisi ve bakım kılavuzları üzerinde çalışan bir yapay zekâ asistanı.

Operatör ya da bakım mühendisi sohbet ekranına şöyle bir soru yazar:

> Pres 3 hattında geçen ay kaç arıza oldu, bu tip arızada ilk neye bakmalıyım?

Asistan sorunun ilk kısmını veritabanından (PostgreSQL) sayarak, ikinci kısmını bakım
kılavuzlarında (pgvector ile anlamsal arama) arayarak cevaplar ve kaynağını gösterir.

> Andon, fabrikalarda bir hatta sorun olduğunda yanan uyarı ışığı sisteminin adıdır.

## Durum

Geliştirme aşamasında. Haftalık plan:

- [ ] Hafta 0: Kurulum
- [ ] Hafta 1: Veritabanı ve sahte veri
- [ ] Hafta 2: API
- [ ] Hafta 3: RAG
- [ ] Hafta 4: LLM ve agent
- [ ] Hafta 5: Güvenlik ve kalite
- [ ] Hafta 6: Arayüz ve sunum

## Geliştirme ortamı

Gerekenler: Python 3.12, Git, Docker Desktop.

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

Kontroller:

```bash
ruff check .
ruff format --check .
pytest
```

Her iş kendi branch'inde yapılır ve `main`'e pull request ile birleşir.
