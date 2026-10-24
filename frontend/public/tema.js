// Gündüz / gece seçimi React yüklenmeden uygulanır; gece seçen kullanıcı açılışta beyaz parlama
// görmez. Canlıdaki CSP satır içi betiğe izin vermediği için ayrı dosyadır. Anahtar, Mantine'in
// renk şeması yöneticisininkiyle aynıdır (localStorageColorSchemeManager varsayılanı).
(function () {
  var scheme = "light";
  try {
    if (window.localStorage.getItem("mantine-color-scheme-value") === "dark") scheme = "dark";
  } catch (e) {
    // Gizli pencerede depolama kapalı olabilir; gündüz kalır.
  }
  document.documentElement.setAttribute("data-mantine-color-scheme", scheme);
})();
