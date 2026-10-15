// Okutma geri bildirimi: kısa ses (Web Audio) ve titreşim. Desteklenmeyen tarayıcıda sessiz geçer.

let context: AudioContext | null = null;

function tone(frequency: number, duration: number, volume = 0.2): void {
  try {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    context ??= new Ctor();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "square";
    oscillator.frequency.value = frequency;
    gain.gain.value = volume;
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + duration / 1000);
  } catch {
    // Ses çalınamıyorsa görsel uyarı yeterli.
  }
}

export function successFeedback(): void {
  tone(1200, 80, 0.1);
}

export function errorFeedback(): void {
  tone(220, 450);
  try {
    navigator.vibrate?.([200, 100, 200]);
  } catch {
    // titreşim yok
  }
}
