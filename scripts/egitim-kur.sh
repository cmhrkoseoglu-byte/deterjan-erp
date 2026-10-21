#!/usr/bin/env bash
# Eğitim ortamını boş bir Ubuntu 24.04 bulut sunucusuna tek komutla kurar (docs/EGITIM-ORTAMI.md).
# scripts/bulut-kur.sh'i eğitim kipinde (KIP=egitim) çalıştırır; değişkenler orada anlatılır.
#
# Kullanım (root olarak):
#   EGITIM_SIFRE='En-az-10-karakter' bash scripts/egitim-kur.sh
set -euo pipefail
export KIP=egitim
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$here" ] && [ -f "$here/bulut-kur.sh" ]; then
    exec bash "$here/bulut-kur.sh"
fi
# curl ... | bash ile çalıştırıldığında betik dosyası yoktur; aynı daldan indirilir.
exec bash <(curl -fsSL "https://raw.githubusercontent.com/cmhrkoseoglu-byte/deterjan-erp/${EGITIM_DAL:-${DAL:-main}}/scripts/bulut-kur.sh")
